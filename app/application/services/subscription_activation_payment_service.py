"""Subscription Activation Payment service — unified transaction-based implementation.

Handles:
- Creating (or returning existing) a pending activation payment for an INACTIVE subscription
- Fetching an activation payment by ID with ownership check
- Confirming an activation payment (idempotent), which also activates the subscription
"""

from datetime import datetime, timezone
from uuid import UUID

import zoneinfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.finance import (
    ActivationPaymentDTO,
    CreateActivationPaymentInput,
)
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.subscription import SubscriptionStatus
from app.domain.entities.transaction import Transaction, TransactionStatus, TransactionType
from app.domain.entities.transaction_item import TransactionItem
from app.domain.exceptions import (
    InvalidPaymentError,
    PaymentNotFoundError,
    SubscriptionNotFoundError,
)
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.db.repositories.plan_repository import PlanRepository
from app.infrastructure.db.repositories.subscription_repository import SubscriptionRepository
from app.infrastructure.db.repositories.transaction_repository import TransactionRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.payment.pix_gateway import PixGatewayAdapter

_DEFAULT_TZ = zoneinfo.ZoneInfo("America/Sao_Paulo")


class SubscriptionActivationPaymentService:
    """Service for subscription activation payment operations (unified transaction model).

    The activation payment is a one-time Pix that covers admin_tax + insurance
    before the subscription becomes ACTIVE.  Idempotent: calling create_or_get_pending
    twice returns the same pending transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._transaction_repo = TransactionRepository(session)
        self._subscription_repo = SubscriptionRepository(session)
        self._plan_repo = PlanRepository(session)
        self._audit_repo = AuditLogRepository(session)
        self._user_repo = UserRepository(session)
        self._pix_gateway = PixGatewayAdapter()

    # ------------------------------------------------------------------
    # Lazy expiration helper
    # ------------------------------------------------------------------

    async def _expire_stale(self, user_id: UUID, subscription_id: UUID) -> None:
        await self._transaction_repo.expire_stale_payments(
            user_id, TransactionType.SUBSCRIPTION_ACTIVATION_PAYMENT
        )

    # ------------------------------------------------------------------
    # Create or return existing pending payment
    # ------------------------------------------------------------------

    async def create_or_get_pending(
        self, input_data: CreateActivationPaymentInput
    ) -> ActivationPaymentDTO:
        """Idempotently return or create a pending activation payment."""
        sub = await self._subscription_repo.get_by_id(input_data.subscription_id)

        if not sub or sub.user_id != input_data.user_id:
            raise SubscriptionNotFoundError(str(input_data.subscription_id))

        if sub.status != SubscriptionStatus.INACTIVE:
            raise InvalidPaymentError(
                "Pagamento de ativação só é possível para assinaturas inativas"
            )

        # Expire stale pending payments before checking for existing
        await self._expire_stale(input_data.user_id, input_data.subscription_id)

        pending = await self._transaction_repo.get_pending_for_subscription(
            input_data.subscription_id,
            TransactionType.SUBSCRIPTION_ACTIVATION_PAYMENT,
        )
        if pending:
            tx = pending[0]
            # Reload with items
            tx = await self._transaction_repo.get_by_id_with_items(tx.id)  # type: ignore[assignment]
            return self._to_dto(tx)  # type: ignore[arg-type]

        plan = await self._plan_repo.get_by_id(sub.plan_id, include_deleted=True)
        if not plan:
            raise InvalidPaymentError("Plano não encontrado para esta assinatura")

        from app.domain.constants import calculate_pix_fee
        from app.domain.services.installment_calculator import (
            InstallmentCalculator,
        )
        from app.domain.value_objects.money import Money

        monthly = Money.from_cents(sub.monthly_amount_cents)
        calculator = InstallmentCalculator(sub.guarantee_fund_percent)
        breakdown = calculator.calculate_first_installment(monthly)

        admin_tax_cents = breakdown.fee_amount.cents
        insurance_cents = breakdown.insurance_amount.cents
        base_total = admin_tax_cents + insurance_cents
        pix_fee_cents = calculate_pix_fee(base_total)
        total_cents = base_total + pix_fee_cents

        plan_title = plan.title
        sub_name = sub.name or plan_title

        # Persist first to obtain the real UUID, then call MP
        transaction = Transaction.create_activation_payment(
            user_id=input_data.user_id,
            subscription_id=input_data.subscription_id,
            admin_tax_cents=admin_tax_cents,
            insurance_cents=insurance_cents,
            pix_transaction_fee_cents=pix_fee_cents,
            pix_qr_code_data="",
            expiration_minutes=30,
            pix_transaction_id=None,
        )

        item = TransactionItem.create(
            transaction_id=transaction.id,
            subscription_id=input_data.subscription_id,
            subscription_name=sub_name,
            plan_title=plan_title,
            amount_cents=total_cents,
            installment_number=None,
        )

        saved = await self._transaction_repo.save_with_items(transaction, [item])

        # Load payer email for MP order
        user = await self._user_repo.get_by_id(input_data.user_id)
        payer_email = user.email.value if user else "pagador@testuser.com"

        pix_payload = await self._pix_gateway.create_payment(
            internal_transaction_id=saved.id,
            amount_cents=total_cents,
            description=f"Ativação - {sub_name}",
            payer_email=payer_email,
        )

        saved.pix_transaction_id = pix_payload.transaction_id
        saved.pix_qr_code_data = pix_payload.qr_code_data
        saved.pix_qr_code_base64 = pix_payload.qr_code_base64
        saved.expiration_minutes = pix_payload.expiration_minutes
        await self._transaction_repo.save(saved)

        audit = AuditLog.create(
            action=AuditAction.SUBSCRIPTION_ACTIVATION_PAYMENT_CREATED,
            actor_id=input_data.user_id,
            target_id=saved.id,
            target_type="transaction",
            details={
                "subscription_id": str(input_data.subscription_id),
                "admin_tax_cents": admin_tax_cents,
                "insurance_cents": insurance_cents,
                "pix_transaction_fee_cents": pix_fee_cents,
                "total_amount_cents": total_cents,
            },
        )
        await self._audit_repo.save(audit)
        await self._session.commit()

        return self._to_dto(saved)

    # ------------------------------------------------------------------
    # Get payment by ID
    # ------------------------------------------------------------------

    async def get_payment(self, payment_id: UUID, user_id: UUID) -> ActivationPaymentDTO:
        """Get activation payment by ID with ownership check."""
        tx = await self._transaction_repo.get_by_id_with_items(payment_id)
        if (
            not tx
            or tx.transaction_type != TransactionType.SUBSCRIPTION_ACTIVATION_PAYMENT
            or tx.user_id != user_id
        ):
            raise PaymentNotFoundError(str(payment_id))

        if tx.is_stale():
            tx.expire()
            await self._transaction_repo.save(tx)
            await self._session.commit()

        return self._to_dto(tx)

    async def get_payment_for_subscription(
        self, subscription_id: UUID, user_id: UUID
    ) -> ActivationPaymentDTO:
        """Get the activation payment for a subscription (pending or most recent)."""
        sub = await self._subscription_repo.get_by_id(subscription_id)
        if not sub or sub.user_id != user_id:
            raise SubscriptionNotFoundError(str(subscription_id))

        await self._expire_stale(user_id, subscription_id)

        pending = await self._transaction_repo.get_pending_for_subscription(
            subscription_id, TransactionType.SUBSCRIPTION_ACTIVATION_PAYMENT
        )
        if pending:
            tx = await self._transaction_repo.get_by_id_with_items(pending[0].id)
            if tx:
                return self._to_dto(tx)

        latest = await self._transaction_repo.get_latest_for_subscription(
            subscription_id, TransactionType.SUBSCRIPTION_ACTIVATION_PAYMENT
        )
        if not latest:
            raise PaymentNotFoundError(f"No activation payment for {subscription_id}")

        return self._to_dto(latest)

    # ------------------------------------------------------------------
    # Confirm payment (idempotent)
    # ------------------------------------------------------------------

    async def confirm_payment(
        self, payment_id: UUID, pix_transaction_id: str
    ) -> ActivationPaymentDTO:
        """Confirm an activation payment and activate the subscription (idempotent)."""
        tx = await self._transaction_repo.get_by_id_with_items(payment_id)
        if not tx or tx.transaction_type != TransactionType.SUBSCRIPTION_ACTIVATION_PAYMENT:
            raise PaymentNotFoundError(str(payment_id))

        changed = tx.confirm_payment(pix_transaction_id)
        if not changed:
            return self._to_dto(tx)

        # Activate the subscription
        if tx.subscription_id:
            sub = await self._subscription_repo.get_by_id(tx.subscription_id)
            if sub and sub.status == SubscriptionStatus.INACTIVE:
                from datetime import date
                today = datetime.now(_DEFAULT_TZ).date()
                sub.activate(deposit_day_of_month=sub.deposit_day_of_month, today_local=today)
                sub.covers_activation_fees = True
                await self._subscription_repo.save(sub)

        await self._transaction_repo.save(tx)

        audit = AuditLog.create(
            action=AuditAction.SUBSCRIPTION_ACTIVATION_PAYMENT_CONFIRMED,
            actor_id=tx.user_id,
            target_id=tx.id,
            target_type="transaction",
            details={
                "pix_transaction_id": pix_transaction_id,
                "subscription_id": str(tx.subscription_id),
                "total_amount_cents": tx.amount_cents,
            },
        )
        await self._audit_repo.save(audit)
        await self._session.commit()

        result = await self._transaction_repo.get_by_id_with_items(tx.id)
        return self._to_dto(result)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # DTO mapping
    # ------------------------------------------------------------------

    def _to_dto(self, tx: Transaction) -> ActivationPaymentDTO:
        return ActivationPaymentDTO(
            id=tx.id,
            user_id=tx.user_id,
            subscription_id=tx.subscription_id,  # type: ignore[arg-type]
            status=tx.status.value,
            admin_tax_cents=tx.admin_tax_cents or 0,
            insurance_cents=tx.insurance_cents or 0,
            pix_transaction_fee_cents=tx.pix_transaction_fee_cents,
            total_amount_cents=tx.amount_cents,
            pix_qr_code_data=tx.pix_qr_code_data,
            pix_qr_code_base64=tx.pix_qr_code_base64,
            pix_transaction_id=tx.pix_transaction_id,
            expiration_minutes=tx.expiration_minutes or 30,
            created_at=tx.created_at,
            updated_at=tx.updated_at,
            confirmed_at=tx.confirmed_at,
        )
