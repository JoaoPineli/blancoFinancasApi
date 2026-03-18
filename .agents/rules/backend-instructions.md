# Agent Instructions — Backend (Blanco Finanças API)

> These instructions apply to **Antigravity** and any other AI agent working on this repository.
> The canonical rules for this system live in `backend-guardrails.md`.
> Everything described there must be followed without exception.

---

## Big Picture

- This repository contains the **Python backend API** for **Blanco Finanças**.
- The backend is **API-first**, consumed by a Nuxt frontend.
- There is **no server-side rendering**, no templates, and no frontend concerns.
- The system operates in a **critical financial domain**. Correctness, auditability, explicitness, and security are mandatory.
- **Context:** An investment platform where clients deposit monthly installments, and the system manages yields (poupança-based) and "Fundo Garantidor" retention.

---

## Agent Workflow (Antigravity-Specific)

When working on tasks of any non-trivial complexity, Antigravity must follow its structured agentic workflow:

1. **PLANNING mode** — Research the codebase, understand requirements, design the approach, and write an `implementation_plan.md`. Request user review before writing code.
2. **EXECUTION mode** — Implement the plan. If unexpected complexity is found, return to PLANNING.
3. **VERIFICATION mode** — Run tests, validate correctness, produce a `walkthrough.md` with proof of work.

For every significant change, a `task.md` checklist must be maintained and kept up-to-date.

### When to Stop and Ask

The agent **must stop and use `notify_user`** when:

- A financial formula or business rule is missing or ambiguous.
- A database schema change is required that isn't covered by an existing migration.
- A new dependency introduction seems necessary (requires explicit justification).
- An architectural boundary violation is the only apparent path forward.

**Do not infer, approximate, or silently fill gaps in financial or business logic.**

---

## Core Stack (Non-Negotiable)

- **FastAPI** — HTTP layer only
- **Pydantic v2** — request/response validation (I/O only)
- **SQLAlchemy 2.0** — database access (`AsyncSession` only)
- **Alembic** — schema migrations
- **python-jose** — JWT handling
- **passlib[bcrypt]** — password hashing
- **httpx** — external service integrations (BCB APIs, Pix gateways)
- **pytest + pytest-asyncio** — automated tests
- **WeasyPrint** or **ReportLab** — PDF contract generation
- **OpenPyXL** — Excel report generation
- **SendGrid** — Email sending API

No additional frameworks or ORMs may be introduced without strong technical justification.

---

## Python Environment (Required)

Before running **any** backend command (dev server, tests, migrations, linting, etc.), the conda environment must be activated:

```
conda activate blancofinancas
```

This applies to every terminal session. Do not assume the environment is already active.

---

## Async & Concurrency Model (Non-Negotiable)

- FastAPI endpoints are **async**
- Application services are **async**
- SQLAlchemy usage is **async (`AsyncSession` only)**
- Blocking I/O must be offloaded to background tasks or thread pools; keep the request path async.

Mixing sync and async code in the main thread is a design error.

---

## Architecture Map

Dependencies point inward. The domain layer must never depend on outer layers.

```
app/
├── main.py                 # FastAPI bootstrap
│
├── api/                    # HTTP layer (Routers, Schemas)
│   └── v1/
│       └── endpoints/      # auth, clients, finances, admin
│
├── application/            # Use Cases / Services
│   ├── services/           # ContractService, PixService, etc.
│   ├── use_cases/          # CreateDeposit, ApproveWithdrawal, etc.
│   └── dtos/               # Internal data transfer objects
│
├── domain/                 # Pure Business Rules (No frameworks)
│   ├── entities/           # Client, Plan, Contract, Transaction, Wallet
│   ├── value_objects/      # Money, CPF, Email
│   ├── services/           # Domain logic (e.g. PoupancaYieldCalculator)
│   └── exceptions.py       # Domain errors
│
├── infrastructure/         # External Implementations
│   ├── db/                 # SQLAlchemy models & repositories
│   ├── security/           # JWT, Password hashing
│   ├── pdf/                # Contract generation
│   ├── payment/            # Pix Gateway adapter
│   ├── exports/            # Excel export
│   ├── bcb/                # Banco Central do Brasil integration
│   │   ├── client.py       # HTTP client (httpx)
│   │   ├── schemas.py      # DTOs for SGS API responses
│   │   └── exceptions.py   # BCBUnavailable, InvalidSeries
│   └── email/              # External email
│       ├── email_sender.py
│       ├── sendgrid_client.py
│       └── exceptions.py
│
└── tests/
```

- All BCB access MUST go through the `BcbClient` adapter.
- Domain and Application layers must never call `httpx` directly.

### Layer Contracts

**API Layer (`app/api/`)** — Thin controllers only:
1. Receive and validate request (Pydantic)
2. Call Application Service
3. Convert result to response (Pydantic)
4. Map Domain errors → HTTP status codes

**Application Layer (`app/application/`)** — Stateless orchestrators:
- One use case = one business action
- Returns Domain Entities or DTOs — never HTTP responses or Pydantic models
- Controls transactions; coordinates repositories and domain services

**Domain Layer (`app/domain/`)** — Pure Python:
- No imports from FastAPI, SQLAlchemy, Pydantic, or httpx
- Entities encapsulate state and behavior (e.g., `Wallet.credit(amount)`)
- Invariants enforced in constructor or methods

**Infrastructure Layer (`app/infrastructure/`)** — Replaceable adapters:
- Maps ORM ↔ Domain Entity inside repositories
- Repositories return Domain Entities; ORM models must not leak outward

---

## Specific Functional Requirements

### Contracts & Plans

- PDF must be generated from Client and Plan data.
- The version accepted by the client must be **immutable**.
- Plans: "Geral" and "Pequeno Agricultor" are domain concepts.

### Transactions & Pix

- Backend creates Pix QR Code payload.
- Reconciliation must be idempotent, tolerant to redelivery, and fully traceable.
- Installment split logic (first vs. subsequent installments) must be strictly tested.

### Admin & Auditing

- RBAC with distinct scopes: `admin` and `client`.
- Critical actions must generate audit logs (who, when, what).
- Yield credits must store: SGS series ID, reference date range, effective rate applied.
- Reports: stream Excel files for "Fluxo de Caixa" and "Conciliação".

---

## HTTP & REST Guidelines

- **Nouns, not verbs:** `POST /api/v1/deposits`, not `/create_deposit`
- **Versioning:** All routes under `/api/v1/`

---

## Database Rules

### SQLAlchemy
- **2.0 syntax only:** `await session.execute(select(Model))`
- **Transactions** managed explicitly in the Service layer (Unit of Work pattern)
- **Repositories** return Domain Entities; ORM ↔ Domain mapping inside repository

### Migrations (Alembic)
- All schema changes via Alembic migrations.
- **Never** modify the database manually in production.

---

## Testing Rules

- **pytest + pytest-asyncio** are mandatory.
- Domain financial logic (yields, fees) must have **100% unit test coverage** with edge cases.
- Yield calculation tests must include:
  - Official BCB reference values
  - Cross-validation against known public examples
  - Edge cases: month boundaries, Selic threshold changes
- Integration tests use `httpx.AsyncClient` with a test database.

---

## Naming Conventions

| Concept | Pattern | Example |
|---|---|---|
| Services | `VerbNounService` | `GenerateContractService` |
| Repositories | `NounRepository` | `ClientRepository` |
| Use Cases | `ActionSubject` | `ApproveWithdrawal` |

---

## Critical Reminders for the Agent

- **Do not hallucinate** financial formulas. If a yield or tax formula is missing, stop and use `notify_user` to surface the gap.
- **Security first:** Always validate user ownership of resources. Client A must never access Client B's data.
- **Precision:** The Fundo Garantidor percentage (1% vs 1.3%) must be explicit and configurable — never hardcoded.
- **Fail loudly:** In financial systems, silent failures are worse than crashes. Throw, block, log — never swallow errors silently.
- The `backend-guardrails.md` is the final authority. It overrides any suggestion, convention, or shortcut.
