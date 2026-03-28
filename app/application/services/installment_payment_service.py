"""Installment Payment service for grouped subscription installment payments.

Orchestrates:
- Listing payable installments for a user
- Creating a grouped Pix payment for selected installments
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
from app.domain.entities.installment_payment import InstallmentPayment, PaymentStatus
from app.domain.entities.subscription import SubscriptionStatus
from app.domain.entities.transaction import Transaction, TransactionType
from app.domain.exceptions import (
    AuthorizationError,
    DuplicatePaymentError,
    InvalidPaymentError,
    PaymentNotFoundError,
    SubscriptionNotFoundError,
)
from app.domain.services.installment_calculator import InstallmentCalculator
from app.domain.value_objects.money import Money
from app.domain.entities.principal_deposit import PrincipalDeposit
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.db.repositories.installment_payment_repository import (
    InstallmentPaymentRepository,
)
from app.infrastructure.db.repositories.plan_repository import PlanRepository
from app.infrastructure.db.repositories.principal_deposit_repository import (
    PrincipalDepositRepository,
)
from app.infrastructure.db.repositories.subscription_repository import (
    SubscriptionRepository,
)
from app.infrastructure.db.repositories.transaction_repository import (
    TransactionRepository,
)
from app.infrastructure.db.repositories.wallet_repository import WalletRepository
from app.infrastructure.payment.pix_gateway import PixGatewayAdapter

_DEFAULT_TZ = zoneinfo.ZoneInfo("America/Sao_Paulo")


class InstallmentPaymentService:
    """Service for installment payment operations.

    All financial values come from stored subscription snapshots.
    No free-form amounts are accepted.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._payment_repo = InstallmentPaymentRepository(session)
        self._subscription_repo = SubscriptionRepository(session)
        self._plan_repo = PlanRepository(session)
        self._wallet_repo = WalletRepository(session)
        self._transaction_repo = TransactionRepository(session)
        self._audit_repo = AuditLogRepository(session)
        self._principal_deposit_repo = PrincipalDepositRepository(session)
        self._pix_gateway = PixGatewayAdapter()

    # ------------------------------------------------------------------
    # Lazy expiration
    # ------------------------------------------------------------------

    async def _expire_stale_user_payments(self, user_id: UUID) -> int:
        """Expire any pending payments older than their expiration window.

        Called lazily before read operations so the user always sees
        accurate payment states without a background scheduler.

        Returns:
            Number of payments expired.
        """
        count = await self._payment_repo.expire_stale_payments(user_id)
        if count:
            await self._session.commit()
        return count

    # ------------------------------------------------------------------
    # Payable installments
    # ------------------------------------------------------------------

    async def get_payable_installments(
        self, user_id: UUID
    ) -> PayableInstallmentsResult:
        """List payable installments for a user.

        Returns one installment per active subscription (the current one).
        Ordered by urgency: overdue first, then due_today, then upcoming.

        Args:
            user_id: The authenticated user's UUID.

        Returns:
            PayableInstallmentsResult with ordered installments.
        """
        # Lazy-expire stale pending payments before listing
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

            # Check for existing pending payment
            pending_payments = await self._payment_repo.get_pending_for_subscription(sub.id)
            pending_id = pending_payments[0].id if pending_payments else None

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

        # Sort by urgency: overdue first, then due_today, then upcoming
        priority = {"overdue": 0, "due_today": 1, "upcoming": 2}
        installments.sort(key=lambda i: (priority.get(i.status, 3), i.due_date))

        return PayableInstallmentsResult(
            installments=installments,
            total=len(installments),
        )

    # ------------------------------------------------------------------
    # Create payment
    # ------------------------------------------------------------------

    async def create_payment(
        self, input_data: CreateInstallmentPaymentInput
    ) -> InstallmentPaymentDTO:
        """Create a grouped installment payment.

        Validates:
        - All subscription_ids belong to the user
        - All subscriptions are active and have unpaid installments
        - No duplicate pending payments exist for the selected subscriptions
        - Total is the exact sum of installment amounts

        Args:
            input_data: Contains user_id and list of subscription_ids.

        Returns:
            InstallmentPaymentDTO with Pix QR code data.

        Raises:
            InvalidPaymentError: If validation fails.
            DuplicatePaymentError: If duplicate pending payment exists.
        """
        if not input_data.subscription_ids:
            raise InvalidPaymentError("Selecione pelo menos uma parcela")

        # Deduplicate
        unique_ids = list(set(input_data.subscription_ids))

        items_data = []
        for sub_id in unique_ids:
            sub = await self._subscription_repo.get_by_id(sub_id)

            # Ownership check
            if not sub or sub.user_id != input_data.user_id:
                raise InvalidPaymentError(
                    f"Assinatura não encontrada: {sub_id}"
                )

            # Status check
            if sub.status != SubscriptionStatus.ACTIVE:
                raise InvalidPaymentError(
                    f"Assinatura '{sub.name}' não está ativa"
                )

            # Already fully paid check
            if sub.is_fully_paid:
                raise InvalidPaymentError(
                    f"Todas as parcelas de '{sub.name}' já foram pagas"
                )

            # Duplicate pending payment check
            pending = await self._payment_repo.get_pending_for_subscription(sub_id)
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

        total_cents = sum(item["amount_cents"] for item in items_data)

        # Generate Pix via gateway
        from uuid import uuid4

        temp_id = uuid4()
        description = (
            f"Blanco Financas - {len(items_data)} "
            f"{'parcela' if len(items_data) == 1 else 'parcelas'}"
        )
        pix_payload = self._pix_gateway.create_payment(
            internal_transaction_id=temp_id,
            amount_cents=total_cents,
            description=description,
        )

        # Create domain entity
        payment = InstallmentPayment.create(
            user_id=input_data.user_id,
            items_data=items_data,
            pix_qr_code_data=pix_payload.qr_code_data,
            expiration_minutes=pix_payload.expiration_minutes,
        )
        payment.pix_transaction_id = pix_payload.transaction_id

        # Persist
        saved = await self._payment_repo.save(payment)

        # Audit
        audit = AuditLog.create(
            action=AuditAction.INSTALLMENT_PAYMENT_CREATED,
            actor_id=input_data.user_id,
            target_id=saved.id,
            target_type="installment_payment",
            details={
                "total_amount_cents": total_cents,
                "subscription_count": len(items_data),
                "subscription_ids": [str(i["subscription_id"]) for i in items_data],
            },
        )
        await self._audit_repo.save(audit)
        await self._session.commit()

        return self._to_dto(saved)

    # ------------------------------------------------------------------
    # Get payment
    # ------------------------------------------------------------------

    async def get_payment(
        self, payment_id: UUID, user_id: UUID
    ) -> InstallmentPaymentDTO:
        """Get payment details with ownership check.

        Args:
            payment_id: Payment UUID.
            user_id: Authenticated user UUID for ownership validation.

        Returns:
            InstallmentPaymentDTO.

        Raises:
            PaymentNotFoundError: If not found or not owned by user.
        """
        payment = await self._payment_repo.get_by_id(payment_id)
        if not payment or payment.user_id != user_id:
            raise PaymentNotFoundError(str(payment_id))

        # Lazy-expire if this specific payment is stale
        if payment.is_stale():
            payment.expire()
            await self._payment_repo.save(payment)
            await self._session.commit()

        return self._to_dto(payment)

    # ------------------------------------------------------------------
    # Confirm payment (idempotent)
    # ------------------------------------------------------------------

    async def confirm_payment(
        self, payment_id: UUID, pix_transaction_id: str
    ) -> InstallmentPaymentDTO:
        """Confirm a payment after Pix verification.

        Idempotent: if already confirmed, returns current state.
        Atomic: updates all subscriptions + wallet in one transaction.

        Steps:
        1. Validate payment exists and is pending (or already confirmed).
        2. Update payment status to CONFIRMED.
        3. For each item: record deposit on subscription, update wallet.
        4. Create audit log.
        5. Commit atomically.

        Args:
            payment_id: Payment UUID.
            pix_transaction_id: Pix transaction ID from gateway.

        Returns:
            Updated InstallmentPaymentDTO.

        Raises:
            PaymentNotFoundError: If payment not found.
            InvalidPaymentError: If payment is in a terminal state.
        """
        payment = await self._payment_repo.get_by_id(payment_id)
        if not payment:
            raise PaymentNotFoundError(str(payment_id))

        # Idempotent: already confirmed
        changed = payment.confirm(pix_transaction_id)
        if not changed:
            return self._to_dto(payment)

        today = self._today_local()

        # Process each item
        for item in payment.items:
            sub = await self._subscription_repo.get_by_id(item.subscription_id)
            if not sub:
                continue

            # Record payment on subscription (advances due date, checks completion)
            sub.record_deposit_paid(today)
            await self._subscription_repo.save(sub)

            # Update wallet with installment breakdown
            wallet = await self._wallet_repo.get_by_user_id(payment.user_id)
            if wallet:
                amount = Money.from_cents(item.amount_cents)
                calculator = InstallmentCalculator(sub.guarantee_fund_percent)

                if item.installment_number == 1:
                    breakdown = calculator.calculate_first_installment(amount)
                else:
                    breakdown = calculator.calculate_subsequent_installment(amount)

                wallet.credit_investment(breakdown.investment_amount)
                wallet.add_fundo_garantidor(breakdown.fundo_garantidor_amount)
                await self._wallet_repo.save(wallet)

                # Record principal deposit for poupança yield tracking.
                # Idempotent: skip if a record already exists for this item
                # (handles re-delivery of a confirmed webhook).
                existing = await self._principal_deposit_repo.get_by_item_id(item.id)
                if not existing and breakdown.investment_amount.cents > 0:
                    principal_deposit = PrincipalDeposit.create(
                        user_id=payment.user_id,
                        subscription_id=item.subscription_id,
                        installment_payment_item_id=item.id,
                        installment_number=item.installment_number,
                        principal_cents=breakdown.investment_amount.cents,
                        deposited_at=today,
                    )
                    await self._principal_deposit_repo.save(principal_deposit)

        # Save payment
        saved = await self._payment_repo.save(payment)

        # Audit
        audit = AuditLog.create(
            action=AuditAction.INSTALLMENT_PAYMENT_CONFIRMED,
            actor_id=payment.user_id,
            target_id=saved.id,
            target_type="installment_payment",
            details={
                "pix_transaction_id": pix_transaction_id,
                "total_amount_cents": payment.total_amount_cents,
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
        """List subscriptions eligible for value withdrawal.

        Eligible scenarios:
        - COMPLETED: All installments paid (full withdrawal).
        - ACTIVE with deposits_paid > 0: Early termination (partial withdrawal).

        Args:
            user_id: The authenticated user's UUID.

        Returns:
            WithdrawableSubscriptionsResult.
        """
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

        return WithdrawableSubscriptionsResult(
            subscriptions=result,
            total=len(result),
        )

    # ------------------------------------------------------------------
    # Request plan withdrawal
    # ------------------------------------------------------------------

    async def request_plan_withdrawal(
        self, input_data: RequestPlanWithdrawalInput
    ) -> PlanWithdrawalDTO:
        """Request withdrawal with plan closure.

        Validates eligibility, closes the subscription, creates a
        pending withdrawal transaction, and logs the action.

        Args:
            input_data: Contains user_id and subscription_id.

        Returns:
            PlanWithdrawalDTO.

        Raises:
            SubscriptionNotFoundError: If not found or not owned.
            InvalidPaymentError: If subscription is not eligible.
        """
        sub = await self._subscription_repo.get_by_id(input_data.subscription_id)
        if not sub or sub.user_id != input_data.user_id:
            raise SubscriptionNotFoundError(str(input_data.subscription_id))

        is_completed = sub.status == SubscriptionStatus.COMPLETED
        is_active_with_deposits = (
            sub.status == SubscriptionStatus.ACTIVE and sub.deposits_paid > 0
        )

        if not (is_completed or is_active_with_deposits):
            raise InvalidPaymentError(
                "Este plano não está elegível para retirada de valor"
            )

        plan = await self._plan_repo.get_by_id(sub.plan_id, include_deleted=True)
        plan_title = plan.title if plan else "Plano removido"
        is_early = sub.status == SubscriptionStatus.ACTIVE
        amount_cents = sub.total_deposited_cents

        # Close subscription
        if is_early:
            sub.cancel()
        # Already COMPLETED: no status change needed

        await self._subscription_repo.save(sub)

        # Create withdrawal transaction for tracking
        description = (
            f"Retirada - {sub.name or plan_title}"
            f"{' (encerramento antecipado)' if is_early else ''}"
        )
        transaction = Transaction.create_withdrawal(
            user_id=input_data.user_id,
            amount_cents=amount_cents,
            bank_account="",  # To be filled by admin
            description=description,
        )
        await self._transaction_repo.save(transaction)

        # Audit
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
        """Get financial history for a user.

        Combines installment payments and withdrawal transactions
        into a unified timeline.

        Args:
            user_id: The user's UUID.
            limit: Max items to return.
            offset: Pagination offset.

        Returns:
            HistoryResult with merged events.
        """
        # Lazy-expire stale pending payments before building timeline
        await self._expire_stale_user_payments(user_id)

        events: List[HistoryEventDTO] = []

        # 1. Installment payments (all statuses)
        payments = await self._payment_repo.get_by_user_id(
            user_id, limit=limit, offset=offset
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
                    amount_cents=p.total_amount_cents,
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
                )
            )

        # Sort by date descending
        events.sort(key=lambda e: e.created_at, reverse=True)

        # Apply limit after merge
        events = events[:limit]

        return HistoryResult(events=events, total=len(events))

    # ------------------------------------------------------------------
    # DTO mapping
    # ------------------------------------------------------------------

    def _to_dto(self, payment: InstallmentPayment) -> InstallmentPaymentDTO:
        return InstallmentPaymentDTO(
            id=payment.id,
            user_id=payment.user_id,
            status=payment.status.value,
            total_amount_cents=payment.total_amount_cents,
            pix_qr_code_data=payment.pix_qr_code_data,
            pix_transaction_id=payment.pix_transaction_id,
            expiration_minutes=payment.expiration_minutes,
            items=[
                InstallmentPaymentItemDTO(
                    id=item.id,
                    subscription_id=item.subscription_id,
                    subscription_name=item.subscription_name,
                    plan_title=item.plan_title,
                    amount_cents=item.amount_cents,
                    installment_number=item.installment_number,
                )
                for item in payment.items
            ],
            created_at=payment.created_at,
            updated_at=payment.updated_at,
            confirmed_at=payment.confirmed_at,
        )

    @staticmethod
    def _today_local() -> date:
        """Return current calendar date in default timezone."""
        return datetime.now(_DEFAULT_TZ).date()
