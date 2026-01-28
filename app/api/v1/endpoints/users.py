"""Client endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.v1.dependencies import CurrentAdmin, CurrentUser, DbSession
from app.api.v1.schemas.user import (
    UserListResponse,
    UserResponse,
    UserStatusRequest,
    UpdateUserRequest,
)
from app.api.v1.schemas.contract import (
    AcceptContractRequest,
    ContractResponse,
    CreateContractRequest,
    PlanListResponse,
    PlanResponse,
)
from app.application.dtos.contract import AcceptContractInput, CreateContractInput
from app.application.services.contract_service import GenerateContractService
from app.domain.entities.user import UserStatus
from app.domain.exceptions import (
    UserNotFoundError,
    ContractNotFoundError,
    PlanNotFoundError,
)
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.db.repositories.plan_repository import PlanRepository

router = APIRouter()


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
)
async def get_current_profile(
    current_user: CurrentUser,
) -> UserResponse:
    """Get the current authenticated user's profile."""
    return UserResponse(
        id=str(current_user.id),
        cpf=current_user.cpf.formatted,
        email=current_user.email.value,
        name=current_user.name,
        role=current_user.role.value,
        status=current_user.status.value,
        phone=current_user.phone,
        created_at=current_user.created_at,
    )


@router.get(
    "/plans",
    response_model=PlanListResponse,
    summary="Get available plans",
)
async def get_plans(
    session: DbSession,
    current_user: CurrentUser,
) -> PlanListResponse:
    """Get all active investment plans."""
    plan_repo = PlanRepository(session)
    plans = await plan_repo.get_active_plans()

    return PlanListResponse(
        plans=[
            PlanResponse(
                id=str(p.id),
                name=p.name,
                plan_type=p.plan_type.value,
                description=p.description,
                monthly_installment_cents=p.monthly_installment_cents,
                duration_months=p.duration_months,
                fundo_garantidor_percentage=p.fundo_garantidor_percentage,
                status=p.status.value,
            )
            for p in plans
        ]
    )


@router.post(
    "/contracts",
    response_model=ContractResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new contract",
)
async def create_contract(
    request: CreateContractRequest,
    session: DbSession,
    current_user: CurrentUser,
) -> ContractResponse:
    """Create a new contract for a plan."""
    service = GenerateContractService(session)

    try:
        input_data = CreateContractInput(
            client_id=current_user.id,
            plan_id=UUID(request.plan_id),
        )
        contract = await service.create_contract(input_data)

        return ContractResponse(
            id=str(contract.id),
            user_id=str(contract.user_id),
            plan_id=str(contract.plan_id),
            status=contract.status,
            pdf_storage_path=contract.pdf_storage_path,
            accepted_at=contract.accepted_at,
            start_date=contract.start_date,
            end_date=contract.end_date,
            created_at=contract.created_at,
        )
    except PlanNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message,
        )


@router.post(
    "/contracts/accept",
    response_model=ContractResponse,
    summary="Accept a pending contract",
)
async def accept_contract(
    request: AcceptContractRequest,
    session: DbSession,
    current_user: CurrentUser,
) -> ContractResponse:
    """Accept a pending contract and generate PDF."""
    service = GenerateContractService(session)

    try:
        input_data = AcceptContractInput(
            contract_id=UUID(request.contract_id),
            client_id=current_user.id,
        )
        contract = await service.accept_contract(input_data)

        return ContractResponse(
            id=str(contract.id),
            user_id=str(contract.user_id),
            plan_id=str(contract.plan_id),
            status=contract.status,
            pdf_storage_path=contract.pdf_storage_path,
            accepted_at=contract.accepted_at,
            start_date=contract.start_date,
            end_date=contract.end_date,
            created_at=contract.created_at,
        )
    except ContractNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/contracts",
    response_model=list[ContractResponse],
    summary="Get client contracts",
)
async def get_contracts(
    session: DbSession,
    current_user: CurrentUser,
) -> list[ContractResponse]:
    """Get all contracts for the current client."""
    service = GenerateContractService(session)
    contracts = await service.get_user_contracts(current_user.id)

    return [
        ContractResponse(
            id=str(c.id),
            user_id=str(c.user_id),
            plan_id=str(c.plan_id),
            status=c.status,
            pdf_storage_path=c.pdf_storage_path,
            accepted_at=c.accepted_at,
            start_date=c.start_date,
            end_date=c.end_date,
            created_at=c.created_at,
        )
        for c in contracts
    ]


@router.get(
    "/contracts/active",
    response_model=ContractResponse | None,
    summary="Get active contract",
)
async def get_active_contract(
    session: DbSession,
    current_user: CurrentUser,
) -> ContractResponse | None:
    """Get the current active contract for the client."""
    service = GenerateContractService(session)
    contract = await service.get_active_contract(current_user.id)

    if not contract:
        return None

    return ContractResponse(
        id=str(contract.id),
        user_id=str(contract.user_id),
        plan_id=str(contract.plan_id),
        status=contract.status,
        pdf_storage_path=contract.pdf_storage_path,
        accepted_at=contract.accepted_at,
        start_date=contract.start_date,
        end_date=contract.end_date,
        created_at=contract.created_at,
    )
