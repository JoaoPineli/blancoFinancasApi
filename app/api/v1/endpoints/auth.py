"""Authentication endpoints."""

from fastapi import APIRouter, HTTPException, status

from app.api.v1.dependencies import CurrentUser, DbSession
from app.api.v1.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
)
from app.api.v1.schemas.user import UserResponse
from app.api.v1.schemas.invitation import (
    ActivateAccountRequest,
    ActivateAccountResponse,
)
from app.application.dtos.auth import LoginInput, RegisterUserInput
from app.application.dtos.invitation import ActivateAccountInput
from app.application.services.activation_service import ActivationService
from app.application.services.authentication_service import AuthenticationService
from app.domain.exceptions import AuthenticationError, InvalidTokenError, InvalidCPFError

router = APIRouter()


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(
    request: RegisterRequest,
    session: DbSession,
) -> RegisterResponse:
    """Register a new user account.

    Creates a new user with associated wallet.
    """
    service = AuthenticationService(session)

    try:
        input_data = RegisterUserInput(
            cpf=request.cpf,
            email=request.email,
            name=request.name,
            password=request.password,
            phone=request.phone,
        )
        user = await service.register_user(input_data)

        # CPF is guaranteed to be set for registered users (not invited)
        assert user.cpf is not None

        return RegisterResponse(
            id=str(user.id),
            cpf=user.cpf.formatted,
            email=user.email.value,
            name=user.name,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )

@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login to get access token",
)
async def login(
    request: LoginRequest,
    session: DbSession,
) -> TokenResponse:
    """Authenticate and get access token.

    Returns JWT token for subsequent authenticated requests.
    """
    service = AuthenticationService(session)

    try:
        input_data = LoginInput(
            email=request.email,
            password=request.password,
        )
        result = await service.login(input_data)

        return TokenResponse(
            access_token=result.access_token,
            token_type=result.token_type,
            user_id=str(result.user_id),
            role=result.role.value,
            name=result.name,
        )
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=e.message,
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post(
    "/activate",
    response_model=ActivateAccountResponse,
    status_code=status.HTTP_200_OK,
    summary="Activate an invited account",
)
async def activate_account(
    request: ActivateAccountRequest,
    session: DbSession,
) -> ActivateAccountResponse:
    """Complete account activation for an invited user.

    This is a public endpoint that does NOT require JWT authentication.
    Authentication is done via the activation token.

    Sets the user's password, CPF, phone, and optionally nickname.
    Transitions user status from INVITED to ACTIVE.
    """
    service = ActivationService(session)

    try:
        input_data = ActivateAccountInput(
            token=request.token,
            password=request.password,
            cpf=request.cpf,
            phone=request.phone,
            nickname=request.nickname,
        )
        result = await service.activate_account(input_data)

        return ActivateAccountResponse(
            user_id=str(result.user_id),
            email=result.email,
            name=result.name,
        )
    except InvalidTokenError:
        # Generic error to prevent token/user enumeration
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired activation token",
        )
    except InvalidCPFError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid CPF",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
)
async def get_current_profile(
    current_user: CurrentUser,
) -> UserResponse:
    """Get the current authenticated user's profile.

    Used for session restoration and token validation.
    Requires valid JWT token in Authorization header.
    """
    return UserResponse(
        id=str(current_user.id),
        cpf=current_user.cpf.formatted if current_user.cpf else "",
        email=current_user.email.value,
        name=current_user.name,
        role=current_user.role.value,
        status=current_user.status.value,
        phone=current_user.phone,
        created_at=current_user.created_at,
    )
