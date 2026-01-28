"""Contract service."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.contract import (
    AcceptContractInput,
    ContractDTO,
    CreateContractInput,
)
from app.domain.entities.audit_log import AuditAction, AuditLog
from app.domain.entities.contract import Contract
from app.domain.exceptions import (
    UserNotFoundError,
    ContractNotFoundError,
    PlanNotFoundError,
)
from app.infrastructure.db.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.db.repositories.contract_repository import ContractRepository
from app.infrastructure.db.repositories.plan_repository import PlanRepository
from app.infrastructure.pdf.contract_generator import ContractPdfGenerator


class GenerateContractService:
    """Service for contract generation operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize service with database session."""
        self._session = session
        self._contract_repo = ContractRepository(session)
        self._user_repo = UserRepository(session)
        self._plan_repo = PlanRepository(session)
        self._audit_repo = AuditLogRepository(session)
        self._pdf_generator = ContractPdfGenerator()

    async def create_contract(self, input_data: CreateContractInput) -> ContractDTO:
        """Create a new contract for a user.

        Args:
            input_data: Contract creation data

        Returns:
            Created ContractDTO

        Raises:
            UserNotFoundError: If user not found
            PlanNotFoundError: If plan not found
        """
        # Validate user exists
        user = await self._user_repo.get_by_id(input_data.user_id)
        if not user:
            raise UserNotFoundError(str(input_data.user_id))

        # Validate plan exists
        plan = await self._plan_repo.get_by_id(input_data.plan_id)
        if not plan:
            raise PlanNotFoundError(str(input_data.plan_id))

        # Create contract
        contract = Contract.create(
            user_id=input_data.user_id,
            plan_id=input_data.plan_id,
        )

        # Save contract
        saved_contract = await self._contract_repo.save(contract)

        # Create audit log
        audit = AuditLog.create(
            action=AuditAction.CONTRACT_CREATED,
            actor_id=user.id,
            target_id=saved_contract.id,
            target_type="contract",
            details={"plan_id": str(plan.id), "plan_name": plan.name},
        )
        await self._audit_repo.save(audit)

        return self._to_dto(saved_contract)

    async def accept_contract(self, input_data: AcceptContractInput) -> ContractDTO:
        """Accept a pending contract.

        Generates the PDF and activates the contract.

        Args:
            input_data: Contract acceptance data

        Returns:
            Updated ContractDTO

        Raises:
            ContractNotFoundError: If contract not found
            ValueError: If contract is not pending or doesn't belong to user
        """
        # Get contract
        contract = await self._contract_repo.get_by_id(input_data.contract_id)
        if not contract:
            raise ContractNotFoundError(str(input_data.contract_id))

        # Validate ownership
        if contract.user_id != input_data.user_id:
            raise ContractNotFoundError(str(input_data.contract_id))

        # Get user and plan for PDF generation
        user = await self._user_repo.get_by_id(contract.user_id)
        plan = await self._plan_repo.get_by_id(contract.plan_id)

        if not user or not plan:
            raise ValueError("Invalid contract data")

        # Generate PDF
        pdf_path = self._pdf_generator.generate(
            user=user,
            plan=plan,
            contract_id=contract.id,
        )

        # Accept contract
        contract.accept(pdf_storage_path=pdf_path, duration_months=plan.duration_months)

        # Save updated contract
        saved_contract = await self._contract_repo.save(contract)

        # Create audit log
        audit = AuditLog.create(
            action=AuditAction.CONTRACT_ACCEPTED,
            actor_id=user.id,
            target_id=saved_contract.id,
            target_type="contract",
            details={"pdf_path": pdf_path},
        )
        await self._audit_repo.save(audit)

        return self._to_dto(saved_contract)

    async def get_contract(self, contract_id: UUID, user_id: UUID) -> ContractDTO:
        """Get a contract by ID.

        Args:
            contract_id: Contract UUID
            user_id: User UUID (for ownership validation)

        Returns:
            ContractDTO

        Raises:
            ContractNotFoundError: If contract not found or doesn't belong to user
        """
        contract = await self._contract_repo.get_by_id(contract_id)
        if not contract or contract.user_id != user_id:
            raise ContractNotFoundError(str(contract_id))

        return self._to_dto(contract)

    async def get_user_contracts(self, user_id: UUID) -> list[ContractDTO]:
        """Get all contracts for a user.

        Args:
            user_id: User UUID
        Returns:
            List of ContractDTO
        """
        contracts = await self._contract_repo.get_by_user_id(user_id)
        return [self._to_dto(c) for c in contracts]

    async def get_active_contract(self, user_id: UUID) -> ContractDTO | None:
        """Get active contract for a user.
        Args:
            user_id: User UUID

        Returns:
            ContractDTO or None
        """
        contract = await self._contract_repo.get_active_contract(user_id)
        return self._to_dto(contract) if contract else None

    def _to_dto(self, contract: Contract) -> ContractDTO:
        """Convert Contract entity to DTO."""
        return ContractDTO(
            id=contract.id,
            user_id=contract.user_id,
            plan_id=contract.plan_id,
            status=contract.status.value,
            pdf_storage_path=contract.pdf_storage_path,
            accepted_at=contract.accepted_at,
            start_date=contract.start_date,
            end_date=contract.end_date,
            created_at=contract.created_at,
        )
