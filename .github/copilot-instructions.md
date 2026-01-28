# Copilot Instructions — Backend (Blanco Finanças API)

## Big picture

- This repository contains the **Python backend API** for **Blanco Finanças**.
- The backend is **API-first**, consumed by a Nuxt frontend.
- There is **no server-side rendering**, no templates, and no frontend concerns.
- The system operates in a **critical financial domain**. Correctness, auditability, explicitness, and security are mandatory.
- **Context:** An investment platform where clients deposit monthly installments, and the system manages yields (poupança-based) and "Fundo Garantidor" retention.
- ARCHITECTURE_AND_GUARDRAILS.md is the rulebook for this application, everything listed there should be followed to the dot.

---

## Core Stack (Non-negotiable)

- **FastAPI** — HTTP layer only
- **Pydantic v2** — request/response validation (I/O only)
- **SQLAlchemy 2.0** — database access (AsyncSession only)
- **Alembic** — schema migrations
- **python-jose** — JWT handling
- **passlib[bcrypt]** — password hashing
- **httpx** — external service integrations (e.g., Central Bank APIs, Pix gateways)
- **pytest + pytest-asyncio** — automated tests
- **WeasyPrint** or **ReportLab** — PDF Contract Generation
- **OpenPyXL** — Excel Report Generation
- **SendGrid** — Email sending api

No additional frameworks or ORMs may be introduced without strong technical justification.

---

## Async & Concurrency Model (Non-negotiable)

- FastAPI endpoints are **async**
- Application services are **async**
- SQLAlchemy usage is **async (AsyncSession only)**
- Blocking I/O (e.g., synchronous file writing, long CPU math) must be offloaded to background tasks or thread pools if necessary, but keep the request path async.

Mixing sync and async code in the main thread is a design error.

---

## Financial Precision Standards (Zero Tolerance)

### 1. Money Handling

- **Never use `float`** for monetary values.
- Use Python's `decimal.Decimal` for all in-memory calculations.
- In the database, store money as **BigInteger (cents)** or **Numeric/Decimal** type with fixed precision (e.g., `DECIMAL(20, 4)`).
- All rounding strategies must be explicit (e.g., `ROUND_HALF_UP`).

### 2. Yield & Fee Calculations

- **Yield Calculation (Poupança):** Must fetch official indices or use a strictly defined constant. Do not hardcode magic numbers deep in code; use a configuration or database parameter.
- **Fundo Garantidor:** Logic (1% to 1.3%) must be isolated in a Domain Service, testable independently of the API.

#### Official Poupança Yield Source (Non-negotiable)

- The ONLY accepted source for poupança yield data is the **Banco Central do Brasil – SGS API**.
- Approved series:
  - **SGS 25** — Depósitos de poupança (até 03/05/2012)
  - **SGS 195** — Depósitos de poupança (a partir de 04/05/2012)
- Series switching (pre/post 2012) must be explicit and covered by tests.
- No third-party APIs, scraping, spreadsheets, or Caixa website parsing are allowed.

---

## Architectural Principles (Strict Clean Architecture)

The codebase **must be layered** and **dependencies must point inward**.

```
app/
├── main.py                 # FastAPI bootstrap
│
├── api/                       # HTTP layer (Routers, Schemas)
│   ├── v1/
│   │   ├── endpoints/         # auth, clients, finances, admin
│
├── application/               # Use Cases / Services
│   ├── services/              # e.g. ContractService, PixService
│   ├── use_cases/             # Specific actions: CreateDeposit, ApproveWithdrawal
│   └── dtos/                  # Internal data transfer objects
│
├── domain/                    # Pure Business Rules (No frameworks)
│   ├── entities/              # Client, Plan, Contract, Transaction, Wallet
│   ├── value_objects/         # Money, CPF, Email
│   ├── services/              # Domain-specific logic (e.g. YieldCalculator)
│   └── exceptions.py          # Domain errors
│
├── infrastructure/            # External Implementations
│   ├── db/                    # SQLAlchemy models & repositories
│   ├── security/              # JWT, Password hashing
│   ├── pdf/                   # Contract generation impl
│   ├── payment/               # Pix Gateway adapter
│   ├── exports/               # Excel export impl
│   ├── bcb/                   # Banco Central do Brasil integration
│   │   ├── client.py          # HTTP client (httpx)
│   │   ├── schemas.py         # DTOs for SGS API responses
│   │   └── exceptions.py      # BCBUnavailable, InvalidSeries
│   └── email/                 # External email tools
│       ├── email_sender.py    # Common email interface
│       ├── sendgrid_client.py # Implementation for sendgrid
│       └── exceptions.py      # Invalid API Key, Service unavailable
└── tests/
```

- All access to Banco Central data MUST go through the `BcbClient` adapter.
- Domain and Application layers must never call `httpx` directly.

---

### Application Services (Use Cases)

- One service/use case = **one specific business action**.
- **Stateless**: Do not store state on the service instance.
- **Orchestrator**: Coordinate Domain Entities and Repositories.
- **Prohibited**: Services must not return HTTP responses or Pydantic models. They return Domain Entities or DTOs.

### Domain Layer

- **Pure Python**: No imports from FastAPI, SQLAlchemy, or Pydantic.
- **Entities**: Must encapsulate state and behavior (e.g., `Wallet.credit(amount)`).
- **Invariants**: Validate business rules inside the entity constructor or methods (e.g., "Withdrawal cannot exceed balance").

---

## Domain Rules for Poupança Yield Calculation (Mandatory)

- Yield calculation logic MUST live in `domain/services/PoupancaYieldCalculator`.
- The calculator must:
  - Respect deposit anniversary dates
  - Apply daily accumulation (not naive monthly multiplication)
  - Be deterministic and pure (no I/O)
- TR and Selic-based rules must be explicit and configurable.
- The service must have 100% unit test coverage.

---

## External Financial Data Persistence

- All BCB yield data used in calculations MUST be persisted locally.
- Calculations must reference stored data snapshots, not live API calls.
- Recalculation must be deterministic for the same snapshot.

---

## Specific Functional Requirements (Backend Focus)

### 1. Contracts & Plans

- **Contract Generation:** The backend must render a PDF based on the Client and Plan data. This PDF must be stored (S3 or filesystem) or generated on-the-fly, but the version accepted by the client must be immutable.
- **Plans:** "Geral" and "Pequeno Agricultor" are domain concepts.

### 2. Transactions & Pix

- **QR Code Generation:** The backend creates the payload for the Pix QR Code.
- **Reconciliation:** Implement a robust mechanism to match incoming webhooks/callbacks from the Payment Gateway to the pending Transaction entity.
- **Installment Logic:** Logic to split the first installment (Fees + Insurance + Fundo) vs subsequent installments (Investment + Fundo) must be strictly tested.

### 3. Admin & Auditing

- **Role Based Access Control (RBAC):** Distinct scopes for `admin` and `client`.
- **Audit Logs:** Critical actions (approving withdrawals, changing plan status) must be logged (who, when, what).
- **Reports:** Endpoints to stream generated Excel files for "Fluxo de Caixa" and "Conciliação".

---

## HTTP & REST Guidelines

### Endpoints

- **Nouns, not verbs:** `POST /api/v1/deposits` (Create deposit), not `/create_deposit`.
- **Versioning:** All routes under `/api/v1/`.

### Controllers (Routers)

- **Thin Controllers:**
  - Receive Request (Pydantic).
  - Call Application Service.
  - Convert Result to Response (Pydantic).
  - Handle Exceptions (Map Domain Error -> HTTP Status).

---

## Database Rules

### SQLAlchemy

- **2.0 Syntax Only**: `await session.execute(select(Model))`
- **Transactions**: Managed explicitly in the Service layer (Unit of Work pattern recommended).
- **Repositories**: Return Domain Entities. Mapping between ORM Model <-> Domain Entity happens inside the repository.

### Migrations (Alembic)

- All schema changes via Alembic.
- **Never** modify the DB manually in production.

---

## Testing Rules (Additional Financial Constraints)

- **pytest** is mandatory.
- **High Coverage on Domain:** Financial logic (Yields, Fees) must have 100% unit test coverage with edge cases.
- Yield calculation tests must include:
  - Official BCB reference values
  - Cross-validation against known public examples
  - Edge cases (month boundaries, Selic threshold changes)
- **Integration Tests:** Use `httpx` and `AsyncClient` to test API endpoints with a test database.

---

## Naming Conventions

- **Services**: `VerbNounService` (e.g., `GenerateContractService`)
- **Repositories**: `NounRepository` (e.g., `ClientRepository`)
- **Use Cases**: `ActionSubject` (e.g., `ApproveWithdrawal`)

---

## Auditability Requirements

- Any credited yield MUST store:
  - Source SGS series ID
  - Reference date range
  - Applied effective rate
- Audit data must be immutable and queryable.

---

## Final Note for AI

- **Do not hallucinate** financial formulas. If a formula for yield or tax is missing, ask for clarification.
- **Security First**: Validate user ownership of resources (e.g., Client A cannot see Client B's contract).
- **Precision**: When dealing with the "Fundo Garantidor" percentage (1% vs 1.3%), ensure the logic is explicit and configurable.
- Follow the ARCHITECTURE_AND_GUARDRAILS.md file to the dot no mater what
