"""Installment Payment service — unified transaction-based implementation.

Orchestrates:
- Listing payable installments for a user
- Creating a grouped Pix payment (Transaction + TransactionItems)
- Confirming payment (idempotent)
- Listing withdrawable subscriptions
- Requesting plan withdrawal with closure
- Listing user financial history
"""

from datetime import date, datetime, timezone
from typing import List
from uuid import UUID

import zoneinfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.finance import (
    CreateInstallmentPaymentInput,
    HistoryEventDTO,
    HistoryResult,
    InstallmentPaymentDTO,
    InstallmentPaymentItemDTO,
    PayableInstallmentDTO,
    PayableInstallmentsResult,
    PlanWithdrawalDTO,
    RequestPlanWithdrawalInput,
    WithdrawableSubscriptionDTO,
    WithdrawableSubscriptionsResult,
)
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.notification import Notification
from app.domain.entities.principal_deposit import PrincipalDeposit
from app.domain.entities.subscription import SubscriptionStatus
from app.domain.entities.transaction import Transaction, TransactionStatus, TransactionType
from app.domain.entities.transaction_item import TransactionItem
from app.domain.exceptions import (
    DuplicatePaymentError,
    InvalidPaymentError,
    PaymentNotFoundError,
    SubscriptionNotFoundError,
)
from app.domain.services.installment_calculator import InstallmentCalculator
from app.domain.value_objects.money import Money
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.db.repositories.notification_repository import NotificationRepository
from app.infrastructure.db.repositories.plan_repository import PlanRepository
from app.infrastructure.db.repositories.principal_deposit_repository import (
    PrincipalDepositRepository,
)
from app.infrastructure.db.repositories.subscription_repository import SubscriptionRepository
from app.infrastructure.db.repositories.transaction_repository import TransactionRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.db.repositories.wallet_repository import WalletRepository
from app.infrastructure.payment.pix_gateway import PixGatewayAdapter

_DEFAULT_TZ = zoneinfo.ZoneInfo("America/Sao_Paulo")


class InstallmentPaymentService:
    """Service for installment payment operations (unified transaction model).

    All financial values come from stored subscription snapshots.
    No free-form amounts are accepted.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._transaction_repo = TransactionRepository(session)
        self._subscription_repo = SubscriptionRepository(session)
        self._plan_repo = PlanRepository(session)
        self._wallet_repo = WalletRepository(session)
        self._audit_repo = AuditLogRepository(session)
        self._principal_deposit_repo = PrincipalDepositRepository(session)
        self._notification_repo = NotificationRepository(session)
        self._user_repo = UserRepository(session)
        self._pix_gateway = PixGatewayAdapter()

    # ------------------------------------------------------------------
    # Lazy expiration
    # ------------------------------------------------------------------

    async def _expire_stale_user_payments(self, user_id: UUID) -> int:
        count = await self._transaction_repo.expire_stale_payments(
            user_id, TransactionType.SUBSCRIPTION_INSTALLMENT_PAYMENT
        )
        if count:
            await self._session.commit()
        return count

    # ------------------------------------------------------------------
    # Payable installments
    # ------------------------------------------------------------------

    async def get_payable_installments(
        self, user_id: UUID
    ) -> PayableInstallmentsResult:
        """List payable installments for a user."""
        await self._expire_stale_user_payments(user_id)

        subscriptions = await self._subscription_repo.get_active_by_user_id(user_id)
        today = self._today_local()

        installments: List[PayableInstallmentDTO] = []
        for sub in subscriptions:
            if sub.is_fully_paid:
                continue

            plan = await self._plan_repo.get_by_id(sub.plan_id, include_deleted=True)
            plan_title = plan.title if plan else "Plano removido"

            due_date = sub.next_due_date
            is_overdue = due_date < today
            is_due_today = due_date == today

            if is_overdue:
                status = "overdue"
            elif is_due_today:
                status = "due_today"
            else:
                status = "upcoming"

            pending_txs = await self._transaction_repo.get_pending_for_subscription(
                sub.id, TransactionType.SUBSCRIPTION_INSTALLMENT_PAYMENT
            )
            pending_id = pending_txs[0].id if pending_txs else None

            installments.append(
                PayableInstallmentDTO(
                    subscription_id=sub.id,
                    subscription_name=sub.name or plan_title,
                    plan_title=plan_title,
                    installment_number=sub.current_installment_number,
                    total_installments=sub.deposit_count,
                    amount_cents=sub.monthly_amount_cents,
                    due_date=due_date.isoformat(),
                    is_overdue=is_overdue,
                    status=status,
                    pending_payment_id=pending_id,
                )
            )

        priority = {"overdue": 0, "due_today": 1, "upcoming": 2}
        installments.sort(key=lambda i: (priority.get(i.status, 3), i.due_date))

        return PayableInstallmentsResult(installments=installments, total=len(installments))

    # ------------------------------------------------------------------
    # Create payment
    # ------------------------------------------------------------------

    async def create_payment(
        self, input_data: CreateInstallmentPaymentInput
    ) -> InstallmentPaymentDTO:
        """Create a grouped installment payment as a unified Transaction."""
        if not input_data.subscription_ids:
            raise InvalidPaymentError("Selecione pelo menos uma parcela")

        unique_ids = list(set(input_data.subscription_ids))

        items_data = []
        for sub_id in unique_ids:
            sub = await self._subscription_repo.get_by_id(sub_id)

            if not sub or sub.user_id != input_data.user_id:
                raise InvalidPaymentError(f"Assinatura não encontrada: {sub_id}")

            if sub.status != SubscriptionStatus.ACTIVE:
                raise InvalidPaymentError(f"Assinatura '{sub.name}' não está ativa")

            if sub.is_fully_paid:
                raise InvalidPaymentError(
                    f"Todas as parcelas de '{sub.name}' já foram pagas"
                )

            pending = await self._transaction_repo.get_pending_for_subscription(
                sub_id, TransactionType.SUBSCRIPTION_INSTALLMENT_PAYMENT
            )
            if pending:
                raise DuplicatePaymentError(
                    f"Já existe um pagamento pendente para '{sub.name}'"
                )

            plan = await self._plan_repo.get_by_id(sub.plan_id, include_deleted=True)
            plan_title = plan.title if plan else "Plano removido"

            items_data.append(
                {
                    "subscription_id": sub.id,
                    "subscription_name": sub.name or plan_title,
                    "plan_title": plan_title,
                    "amount_cents": sub.monthly_amount_cents,
                    "installment_number": sub.current_installment_number,
                }
            )

        from app.domain.constants import calculate_pix_fee

        base_total_cents = sum(item["amount_cents"] for item in items_data)
        pix_fee_cents = calculate_pix_fee(base_total_cents)
        total_cents = base_total_cents + pix_fee_cents

        item_count = len(items_data)
        description = (
            f"Blanco Financas - {item_count} "
            f"{'parcela' if item_count == 1 else 'parcelas'}"
        )

        # Persist first to obtain the real UUID, then call MP
        transaction = Transaction.create_installment_payment(
            user_id=input_data.user_id,
            total_amount_cents=total_cents,
            pix_qr_code_data="",
            expiration_minutes=30,
            pix_transaction_fee_cents=0,
            pix_transaction_id=None,
        )

        items = [
            TransactionItem.create(
                transaction_id=transaction.id,
                subscription_id=d["subscription_id"],
                subscription_name=d["subscription_name"],
                plan_title=d["plan_title"],
                amount_cents=d["amount_cents"],
                installment_number=d["installment_number"],
            )
            for d in items_data
        ]

        saved = await self._transaction_repo.save_with_items(transaction, items)

        # Load payer email for MP order
        user = await self._user_repo.get_by_id(input_data.user_id)
        payer_email = user.email.value if user else "pagador@testuser.com"

        pix_payload = await self._pix_gateway.create_payment(
            internal_transaction_id=saved.id,
            amount_cents=total_cents,
            description=description,
            payer_email=payer_email,
        )

        saved.pix_transaction_id = pix_payload.transaction_id
        saved.pix_qr_code_data = pix_payload.qr_code_data
        saved.expiration_minutes = pix_payload.expiration_minutes
        await self._transaction_repo.save(saved)

        audit = AuditLog.create(
            action=AuditAction.INSTALLMENT_PAYMENT_CREATED,
            actor_id=input_data.user_id,
            target_id=saved.id,
            target_type="transaction",
            details={
                "total_amount_cents": total_cents,
                "subscription_count": len(items_data),
                "subscription_ids": [str(d["subscription_id"]) for d in items_data],
            },
        )
        await self._audit_repo.save(audit)
        await self._session.commit()

        return self._to_dto(saved)

    # ------------------------------------------------------------------
    # Get payment
    # ------------------------------------------------------------------

    async def get_payment(self, payment_id: UUID, user_id: UUID) -> InstallmentPaymentDTO:
        """Get payment details with ownership check."""
        payment = await self._transaction_repo.get_by_id_with_items(payment_id)
        if (
            not payment
            or payment.transaction_type != TransactionType.SUBSCRIPTION_INSTALLMENT_PAYMENT
            or payment.user_id != user_id
        ):
            raise PaymentNotFoundError(str(payment_id))

        if payment.is_stale():
            payment.expire()
            await self._transaction_repo.save(payment)
            await self._session.commit()

        return self._to_dto(payment)

    # ------------------------------------------------------------------
    # Confirm payment (idempotent)
    # ------------------------------------------------------------------

    async def confirm_payment(
        self, payment_id: UUID, pix_transaction_id: str
    ) -> InstallmentPaymentDTO:
        """Confirm a payment after Pix verification (idempotent)."""
        payment = await self._transaction_repo.get_by_id_with_items(payment_id)
        if not payment:
            raise PaymentNotFoundError(str(payment_id))

        changed = payment.confirm_payment(pix_transaction_id)
        if not changed:
            return self._to_dto(payment)

        today = self._today_local()

        for item in payment.items:
            sub = await self._subscription_repo.get_by_id(item.subscription_id)
            if not sub:
                continue

            sub.record_deposit_paid(today)
            await self._subscription_repo.save(sub)

            wallet = await self._wallet_repo.get_by_user_id(payment.user_id)
            if wallet:
                amount = Money.from_cents(item.amount_cents)
                calculator = InstallmentCalculator(sub.guarantee_fund_percent)

                if item.installment_number == 1 and not sub.covers_activation_fees:
                    breakdown = calculator.calculate_first_installment(amount)
                else:
                    breakdown = calculator.calculate_subsequent_installment(amount)

                wallet.credit_investment(breakdown.investment_amount)
                wallet.add_fundo_garantidor(breakdown.fundo_garantidor_amount)
                await self._wallet_repo.save(wallet)

                existing = await self._principal_deposit_repo.get_by_item_id(item.id)
                if not existing and breakdown.investment_amount.cents > 0:
                    principal_deposit = PrincipalDeposit.create(
                        user_id=payment.user_id,
                        subscription_id=item.subscription_id,
                        transaction_item_id=item.id,
                        installment_number=item.installment_number,
                        principal_cents=breakdown.investment_amount.cents,
                        deposited_at=today,
                    )
                    await self._principal_deposit_repo.save(principal_deposit)

        saved = await self._transaction_repo.save(payment)
        # Re-load with items
        saved = await self._transaction_repo.get_by_id_with_items(saved.id)  # type: ignore[assignment]

        audit = AuditLog.create(
            action=AuditAction.INSTALLMENT_PAYMENT_CONFIRMED,
            actor_id=payment.user_id,
            target_id=saved.id,
            target_type="transaction",
            details={
                "pix_transaction_id": pix_transaction_id,
                "total_amount_cents": payment.amount_cents,
                "items_count": len(payment.items),
            },
        )
        await self._audit_repo.save(audit)
        await self._session.commit()

        return self._to_dto(saved)

    # ------------------------------------------------------------------
    # Withdrawable subscriptions
    # ------------------------------------------------------------------

    async def get_withdrawable_subscriptions(
        self, user_id: UUID
    ) -> WithdrawableSubscriptionsResult:
        """List subscriptions eligible for value withdrawal."""
        all_subs = await self._subscription_repo.get_by_user_id(user_id)

        result: List[WithdrawableSubscriptionDTO] = []
        for sub in all_subs:
            is_completed = sub.status == SubscriptionStatus.COMPLETED
            is_active_with_deposits = (
                sub.status == SubscriptionStatus.ACTIVE and sub.deposits_paid > 0
            )

            if not (is_completed or is_active_with_deposits):
                continue

            plan = await self._plan_repo.get_by_id(sub.plan_id, include_deleted=True)
            plan_title = plan.title if plan else "Plano removido"

            is_early = sub.status == SubscriptionStatus.ACTIVE
            withdrawable = sub.total_deposited_cents

            result.append(
                WithdrawableSubscriptionDTO(
                    subscription_id=sub.id,
                    subscription_name=sub.name or plan_title,
                    plan_title=plan_title,
                    status=sub.status.value,
                    is_early_termination=is_early,
                    withdrawable_amount_cents=withdrawable,
                    deposits_paid=sub.deposits_paid,
                    deposit_count=sub.deposit_count,
                    created_at=sub.created_at.isoformat(),
                )
            )

        return WithdrawableSubscriptionsResult(subscriptions=result, total=len(result))

    # ------------------------------------------------------------------
    # Request plan withdrawal
    # ------------------------------------------------------------------

    async def request_plan_withdrawal(
        self, input_data: RequestPlanWithdrawalInput
    ) -> PlanWithdrawalDTO:
        """Request withdrawal with plan closure."""
        sub = await self._subscription_repo.get_by_id(input_data.subscription_id)
        if not sub or sub.user_id != input_data.user_id:
            raise SubscriptionNotFoundError(str(input_data.subscription_id))

        is_completed = sub.status == SubscriptionStatus.COMPLETED
        is_active_with_deposits = (
            sub.status == SubscriptionStatus.ACTIVE and sub.deposits_paid > 0
        )

        if not (is_completed or is_active_with_deposits):
            raise InvalidPaymentError("Este plano não está elegível para retirada de valor")

        plan = await self._plan_repo.get_by_id(sub.plan_id, include_deleted=True)
        plan_title = plan.title if plan else "Plano removido"
        is_early = sub.status == SubscriptionStatus.ACTIVE
        amount_cents = sub.total_deposited_cents

        if is_early:
            sub.cancel()

        await self._subscription_repo.save(sub)

        description = (
            f"Retirada - {sub.name or plan_title}"
            f"{' (encerramento antecipado)' if is_early else ''}"
        )
        transaction = Transaction.create_withdrawal(
            user_id=input_data.user_id,
            amount_cents=amount_cents,
            bank_account=input_data.owner_name,
            pix_key=input_data.pix_key,
            pix_key_type=input_data.pix_key_type,
            subscription_id=sub.id,
            description=description,
        )
        await self._transaction_repo.save(transaction)

        audit = AuditLog.create(
            action=AuditAction.PLAN_WITHDRAWAL_REQUESTED,
            actor_id=input_data.user_id,
            target_id=sub.id,
            target_type="subscription",
            details={
                "subscription_id": str(sub.id),
                "amount_cents": amount_cents,
                "is_early_termination": is_early,
                "plan_title": plan_title,
            },
        )
        await self._audit_repo.save(audit)

        client = await self._user_repo.get_by_id(input_data.user_id)
        client_name = client.name if client else "Cliente"
        notification = Notification.create_withdrawal_requested(
            target_id=transaction.id,
            client_name=client_name,
            plan_title=plan_title,
            amount_cents=amount_cents,
        )
        await self._notification_repo.save(notification)

        await self._session.commit()

        return PlanWithdrawalDTO(
            subscription_id=sub.id,
            subscription_name=sub.name or plan_title,
            plan_title=plan_title,
            status="pending",
            amount_cents=amount_cents,
            is_early_termination=is_early,
            created_at=datetime.utcnow(),
        )

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    async def get_user_history(
        self, user_id: UUID, limit: int = 50, offset: int = 0
    ) -> HistoryResult:
        """Get financial history combining installment payments and withdrawals."""
        await self._expire_stale_user_payments(user_id)

        events: List[HistoryEventDTO] = []

        # 1. Installment payment transactions
        payments = await self._transaction_repo.get_by_user_id_with_items(
            user_id=user_id,
            transaction_type=TransactionType.SUBSCRIPTION_INSTALLMENT_PAYMENT,
            limit=limit,
            offset=offset,
        )
        for p in payments:
            plan_titles = list({item.plan_title for item in p.items})
            subscription_ids = list({str(item.subscription_id) for item in p.items})
            item_count = len(p.items)
            desc = (
                f"Pagamento de {item_count} "
                f"{'parcela' if item_count == 1 else 'parcelas'}"
            )
            events.append(
                HistoryEventDTO(
                    id=p.id,
                    event_type="installment_payment",
                    status=p.status.value,
                    amount_cents=p.amount_cents,
                    description=desc,
                    plan_titles=plan_titles,
                    subscription_ids=subscription_ids,
                    created_at=p.created_at,
                    confirmed_at=p.confirmed_at,
                )
            )

        # 2. Withdrawal transactions
        withdrawals = await self._transaction_repo.get_by_user_id(
            user_id=user_id,
            transaction_type=TransactionType.WITHDRAWAL,
            limit=limit,
            offset=offset,
        )
        for w in withdrawals:
            events.append(
                HistoryEventDTO(
                    id=w.id,
                    event_type="plan_withdrawal",
                    status=w.status.value,
                    amount_cents=w.amount_cents,
                    description=w.description or "Retirada de valor",
                    plan_titles=[],
                    subscription_ids=[str(w.subscription_id)] if w.subscription_id else [],
                    created_at=w.created_at,
                    confirmed_at=w.confirmed_at,
                    rejection_reason=w.rejection_reason,
                )
            )

        events.sort(key=lambda e: e.created_at, reverse=True)
        events = events[:limit]

        return HistoryResult(events=events, total=len(events))

    # ------------------------------------------------------------------
    # DTO mapping
    # ------------------------------------------------------------------

    def _to_dto(self, transaction: Transaction) -> InstallmentPaymentDTO:
        return InstallmentPaymentDTO(
            id=transaction.id,
            user_id=transaction.user_id,
            status=transaction.status.value,
            total_amount_cents=transaction.amount_cents,
            pix_qr_code_data=transaction.pix_qr_code_data,
            pix_transaction_id=transaction.pix_transaction_id,
            expiration_minutes=transaction.expiration_minutes or 30,
            items=[
                InstallmentPaymentItemDTO(
                    id=item.id,
                    subscription_id=item.subscription_id,
                    subscription_name=item.subscription_name,
                    plan_title=item.plan_title,
                    amount_cents=item.amount_cents,
                    installment_number=item.installment_number or 0,
                )
                for item in transaction.items
            ],
            pix_transaction_fee_cents=transaction.pix_transaction_fee_cents,
            created_at=transaction.created_at,
            updated_at=transaction.updated_at,
            confirmed_at=transaction.confirmed_at,
        )

    @staticmethod
    def _today_local() -> date:
        return datetime.now(_DEFAULT_TZ).date()
