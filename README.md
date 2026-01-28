# Blanco Finanças API

Backend API for Blanco Finanças - Investment Platform.

## Stack

- **FastAPI** — HTTP layer
- **Pydantic v2** — request/response validation
- **SQLAlchemy 2.0** — database access (AsyncSession)
- **Alembic** — schema migrations
- **python-jose** — JWT handling
- **passlib[bcrypt]** — password hashing
- **httpx** — external service integrations
- **pytest + pytest-asyncio** — automated tests
- **WeasyPrint** — PDF Contract Generation
- **OpenPyXL** — Excel Report Generation

## Setup

1. Create a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/Mac
   .venv\Scripts\activate     # Windows
   ```

2. Install dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

3. Configure environment variables (copy `.env.example` to `.env`)

4. Run migrations:
   ```bash
   alembic upgrade head
   ```

5. Start the server:
   ```bash
   uvicorn app.main:app --reload
   ```

## Architecture

This project follows Clean Architecture principles:

- `app/api/` — HTTP layer (Routers, Schemas)
- `app/application/` — Use Cases / Services
- `app/domain/` — Pure Business Rules (No frameworks)
- `app/infrastructure/` — External Implementations

## Testing

```bash
pytest --cov=app tests/
```
