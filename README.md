# Blanco Finanças API

Backend for Blanco Finanças — a Brazilian investment platform managing subscription-based savings plans with poupança yield tracking, PIX payments, and PDF contracts.

## Stack

- **Python 3.11+**
- **FastAPI** — HTTP layer
- **SQLAlchemy 2.0 (async)** + **asyncpg** — PostgreSQL access
- **Alembic** — schema migrations
- **Pydantic v2** — request/response validation
- **APScheduler** — daily yield processing and expiration jobs
- **python-jose** — JWT authentication
- **passlib[bcrypt]** — password hashing
- **httpx** — async HTTP client for external services
- **WeasyPrint** — PDF contract generation
- **OpenPyXL** — Excel report exports
- **pytest + pytest-asyncio** — test suite

## External Integrations

| Service | Purpose |
|---|---|
| Banco Central do Brasil (BCB) SGS API | Authoritative poupança yield rates (Series 25 / 195) |
| Mercado Pago | PIX payment processing + webhooks |
| SendGrid | Transactional email notifications |

## Setup

1. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Linux/Mac
   .venv\Scripts\activate      # Windows
   ```

2. Install dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

3. Copy and fill in environment variables:
   ```bash
   cp .env.example .env
   ```

4. Run database migrations:
   ```bash
   alembic upgrade head
   ```

5. Start the development server:
   ```bash
   uvicorn app.main:app --reload
   ```

API docs available at `http://localhost:8000/docs`.

## Environment Variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL async connection string |
| `SECRET_KEY` | JWT signing secret |
| `ALGORITHM` | JWT algorithm (e.g. `HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token TTL |
| `BCB_API_BASE_URL` | Banco Central SGS base URL |
| `SENDGRID_API_KEY` | SendGrid API key |
| `MERCADOPAGO_ACCESS_TOKEN` | Mercado Pago credentials |
| `WEBHOOK_SECRET` | Webhook signature verification |
| `WEBHOOK_URL` | Public URL for payment callbacks |
| `CORS_ORIGINS` | Allowed frontend origins |
| `FRONTEND_URL` | Used in email links |

## Architecture

Clean Architecture with dependencies flowing inward: `API → Application → Domain ← Infrastructure`

```
app/
├── api/v1/
│   ├── endpoints/      # Thin FastAPI routers (auth, users, clients, finances,
│   │                   #   subscriptions, admin)
│   ├── schemas/        # Pydantic request/response models
│   ├── dependencies.py # Dependency injection
│   └── router.py
├── application/
│   └── services/       # 13 stateless use-case services
│       ├── authentication_service.py
│       ├── registration_service.py
│       ├── subscription_service.py
│       ├── subscription_activation_payment_service.py
│       ├── installment_payment_service.py
│       ├── contract_service.py
│       ├── activation_service.py
│       ├── deposit_service.py
│       ├── withdrawal_service.py
│       ├── yield_service.py
│       ├── plan_service.py
│       ├── notification_service.py
│       └── invitation_service.py
├── domain/
│   ├── entities/       # 14 pure Python domain models (no framework imports)
│   ├── services/       # Domain services: installment calc, yield calc, FGC,
│   │                   #   plan recommendation, due date
│   └── value_objects/  # CPF, Email, Money (Decimal-only)
└── infrastructure/
    ├── db/
    │   ├── models.py   # SQLAlchemy ORM models
    │   ├── session.py
    │   └── repositories/  # 14 repositories (ORM ↔ domain mapping)
    ├── bcb/            # BCB API client
    ├── payment/        # Mercado Pago / PIX gateway
    ├── email/          # SendGrid client
    ├── security/       # JWT + password hashing
    ├── pdf/            # WeasyPrint contract generator
    ├── exports/        # CSV, Excel, PDF report generators
    └── scheduler/      # APScheduler jobs (yield, expiration)
```

## Domain Rules

- **Money is always `Decimal`** — `float` is never used for financial values.
- **BCB SGS API is the sole source of truth** for poupança rates. No hardcoded or approximated values.
- **Installment structure**: first payment includes activation fees + insurance + FGC fund; subsequent payments are principal + FGC only.
- **Contracts are immutable** once accepted by the client — generated PDFs cannot be regenerated.
- **Audit logging is mandatory** for all critical actions.

## Testing

```bash
# All tests with coverage
pytest --cov=app tests/

# Single file
pytest tests/path/to/test_file.py

# Single test
pytest tests/path/to/test_file.py::test_function_name
```

100% coverage is required for all financial logic.

## Other Commands

```bash
# Lint
ruff check app tests

# Type check
mypy app
```
