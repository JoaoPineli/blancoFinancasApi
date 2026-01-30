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
                title=p.title,
                description=p.description,
                min_value_cents=p.min_value_cents,
                max_value_cents=p.max_value_cents,
                min_duration_months=p.min_duration_months,
                max_duration_months=p.max_duration_months,
                admin_tax_value_cents=p.admin_tax_value_cents,
                insurance_percent=p.insurance_percent,
                guarantee_fund_percent_1=p.guarantee_fund_percent_1,
                guarantee_fund_percent_2=p.guarantee_fund_percent_2,
                guarantee_fund_threshold_cents=p.guarantee_fund_threshold_cents,
                active=p.active,
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
            user_id=current_user.id,
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
            user_id=current_user.id,
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
