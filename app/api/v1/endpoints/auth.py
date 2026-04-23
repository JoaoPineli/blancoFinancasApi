"""Authentication endpoints."""

from fastapi import APIRouter, HTTPException, status

from app.api.v1.dependencies import CurrentUser, DbSession
from app.api.v1.schemas.auth import (
    ActivateAccountRequest,
    ActivateAccountResponse,
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
)
from app.api.v1.schemas.user import UserResponse
from app.application.dtos.auth import LoginInput
from app.application.dtos.registration import ActivateAccountInput, RegisterUserInput
from app.application.services.activation_service import ActivationService
from app.application.services.authentication_service import AuthenticationService
from app.application.services.registration_service import RegistrationService
from app.domain.exceptions import (
    AuthenticationError,
    InvalidCPFError,
    InvalidTokenError,
    UserAlreadyExistsError,
)
from app.infrastructure.email.exceptions import EmailError
from app.infrastructure.email.sendgrid_client import SendGridClient

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

    Creates a new user with REGISTERED status, generates an activation
    token, and sends a confirmation email. The user must confirm their
    email before they can access protected resources.
    """
    email_sender = SendGridClient()
    service = RegistrationService(session, email_sender)

    try:
        input_data = RegisterUserInput(
            name=request.name,
            email=request.email,
            password=request.password,
            cpf=request.cpf,
            phone=request.phone,
            nickname=request.nickname,
        )
        result = await service.register_user(input_data)

        return RegisterResponse(
            id=str(result.user_id),
            email=result.email,
            name=result.name,
        )
    except UserAlreadyExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=e.message,
        )
    except InvalidCPFError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid CPF",
        )
    except EmailError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to send confirmation email. Please try again later.",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
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
    Both ACTIVE and REGISTERED users can log in.
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
    summary="Activate account via email confirmation",
)
async def activate_account(
    request: ActivateAccountRequest,
    session: DbSession,
) -> ActivateAccountResponse:
    """Complete account activation by confirming email.

    This is a public endpoint that does NOT require JWT authentication.
    Authentication is done via the activation token.

    Transitions user status from REGISTERED to ACTIVE.
    """
    service = ActivationService(session)

    try:
        input_data = ActivateAccountInput(
            token=request.token,
        )
        result = await service.activate_account(input_data)

        return ActivateAccountResponse(
            user_id=str(result.user_id),
            email=result.email,
            name=result.name,
        )
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired activation token",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/resend-confirmation",
    status_code=status.HTTP_200_OK,
    summary="Resend confirmation email",
)
async def resend_confirmation(
    session: DbSession,
    current_user: CurrentUser,
) -> dict:
    """Resend confirmation email to the current user.

    Requires authentication. Only REGISTERED users can resend.
    Invalidates any existing activation tokens and generates a new one.
    """
    email_sender = SendGridClient()
    service = ActivationService(session, email_sender)

    try:
        await service.resend_confirmation(current_user.id)
        return {"message": "Confirmation email sent successfully"}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except EmailError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to send confirmation email. Please try again later.",
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
    Returns profile for both ACTIVE and REGISTERED users.
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
        nickname=current_user.nickname,
    )
