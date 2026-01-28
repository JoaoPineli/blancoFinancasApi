"""Test configuration and fixtures."""

import asyncio
from typing import AsyncGenerator, Generator, List

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.db.models import Base
from app.infrastructure.db.session import get_db_session
from app.infrastructure.email.email_sender import (
    EmailMessage,
    EmailRecipient,
    EmailSender,
    EmailSendResult,
)
from app.main import app


# Test database URL (use SQLite for tests)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


class MockEmailSender(EmailSender):
    """Mock email sender for testing.

    Records all sent emails for assertion without actually sending.
    """

    def __init__(self) -> None:
        """Initialize mock sender with empty sent emails list."""
        self.sent_emails: List[EmailMessage] = []
        self.should_fail: bool = False

    async def send(self, message: EmailMessage) -> EmailSendResult:
        """Mock send that records the email."""
        if self.should_fail:
            from app.infrastructure.email.exceptions import EmailSendFailedError
            raise EmailSendFailedError("Mock email failure", status_code=500)

        self.sent_emails.append(message)
        return EmailSendResult(success=True, status_code=202, message_id="mock-id")

    async def send_transactional(
        self,
        to_email: str,
        to_name: str | None,
        subject: str,
        html_content: str,
        plain_content: str | None = None,
    ) -> EmailSendResult:
        """Mock send transactional email."""
        message = EmailMessage(
            from_email="test@blancofinancas.com.br",
            from_name="Blanco Finanças",
            to=[EmailRecipient(email=to_email, name=to_name)],
            subject=subject,
            html_content=html_content,
            plain_content=plain_content,
        )
        return await self.send(message)


@pytest.fixture
def mock_email_sender() -> MockEmailSender:
    """Create a mock email sender for testing."""
    return MockEmailSender()


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_engine():
    """Create test database engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture(scope="session")
async def test_session_factory(test_engine):
    """Create test session factory (session-scoped for reuse)."""
    return async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest.fixture
async def test_session(test_session_factory) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session."""
    async with test_session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def client(test_session_factory) -> AsyncGenerator[AsyncClient, None]:
    """Create test HTTP client with overridden database dependency."""

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        async with test_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_get_db_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
