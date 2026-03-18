# Backend Architecture & Guardrails

**Blanco Finanças API – Finance-Grade Backend Rules**

This document defines **non-negotiable rules** for the Blanco Finanças backend.
It exists to prevent **financial, accounting, legal, and security** errors that are not obvious in superficial reviews.

If something is **not explicitly allowed here**, consider it **forbidden**.

This applies equally to:

- Human developers
- AI agents
- Temporary scripts, prototypes, or operational shortcuts

---

## 1. Architectural Authority & Boundaries

### 1.1 Separation of Responsibilities (Hard Rules)

**API / Controllers (`app/api/`)**

- MAY:
  - Validate input and output (Pydantic)
  - Resolve authentication and authorization
  - Call use cases from the Application layer
- MUST NOT:
  - Contain business rules
  - Calculate financial values
  - Access the database directly
  - Call external services

Thin controllers are mandatory. Any logic beyond orchestration is a defect.

---

**Application / Use Cases (`app/application/`)**

- ARE the only place where:
  - Use cases are orchestrated
  - Transactions are controlled
  - Repositories and domain services are coordinated
- MUST:
  - Be stateless
  - Return domain entities or internal DTOs
- MUST NOT:
  - Know about HTTP, FastAPI, or Pydantic
  - Know about persistence details or external libraries

One use case = one well-defined business action.

---

**Domain (`app/domain/`)**

- Is the ultimate authority on business rules
- MUST:
  - Be pure Python
  - Contain explicit invariants
  - Fail immediately when rules are violated
- MUST NOT:
  - Import FastAPI, SQLAlchemy, Pydantic, or httpx
  - Perform any type of I/O

If a financial rule is not in the domain, it does not officially exist.

---

**Infrastructure (`app/infrastructure/`)**

- IMPLEMENTS external details:
  - Database
  - External APIs (BCB, Pix)
  - PDF, Excel, security
- DOES NOT DEFINE business rules
- Is replaceable by definition

---

## 2. Financial Correctness (Zero Tolerance Zone)

### 2.1 Numerical Rules

- `float` is strictly forbidden for monetary values
- All financial amounts must use:
  - `decimal.Decimal` in memory
  - `DECIMAL` or `BIGINT` (cents) in the database
- Rounding strategies must be:
  - Explicit
  - Centralized
  - Tested

Implicit financial calculations are considered critical defects.

### 2.2 Source of Financial Values

- The backend is the **single source of truth**
- No financial value may be:
  - Inferred
  - Approximated
  - Recalculated without persistence

If a value cannot be explained in an audit, it must not exist.

---

## 3. Yield Calculation (Poupança)

### 3.1 Official Source (Mandatory)

- ONLY permitted source:
  - **Banco Central do Brasil – SGS API**
- Accepted series:
  - SGS 25 (until 03/05/2012)
  - SGS 195 (from 04/05/2012 onward)

Any other source is forbidden, even if considered equivalent.

### 3.2 Implementation Rules

- The calculation must:
  - Respect the deposit anniversary date
  - Be daily (not simplified monthly)
  - Be deterministic
- All logic must reside in:
  - `domain/services/PoupancaYieldCalculator`
- The service must have:
  - Full test coverage
  - Test cases based on official BCB values

BCB calls must never occur during calculation.

### 3.3 External Data Persistence

- BCB data must be:
  - Persisted locally
  - Versioned
- Calculations must use stored snapshots

Recalculating with live data is unacceptable.

---

## 4. Fundo Garantidor

- The percentage (1% to 1.3%) must be:
  - Configurable
  - Centralized
  - Fully testable
- The logic must:
  - Be isolated in the domain
  - Never be duplicated in services or controllers

A hardcoded percentage is a critical error.

---

## 5. Contracts, Transactions, and Pix

### 5.1 Contracts

- Generated PDFs must be:
  - Immutable after acceptance
  - Auditable
- Any regeneration must:
  - Preserve the original version
  - Be explicitly versioned

### 5.2 Pix and Reconciliation

- The backend is responsible for:
  - Generating the Pix payload
  - Correlating callbacks with pending transactions
- Reconciliation must be:
  - Idempotent
  - Tolerant to redelivery
  - Fully traceable

Do not assume correct event ordering.

---

## 6. Authentication, Authorization, and Security

### 6.1 Authentication

- JWT is mandatory
- Tokens must:
  - Have explicit scope
  - Have a defined expiration
- Passwords must:
  - Be stored only as hashes (bcrypt)
  - Never be returned or logged

### 6.2 Authorization

- Every action must:
  - Validate ownership
  - Validate role (admin vs client)
- Never trust:
  - IDs coming from the frontend
  - Hidden routes or UI

The API assumes a malicious client by default.

---

## 7. Database & Transactions

### 7.1 SQLAlchemy

- 2.0 syntax only
- `AsyncSession` only
- Explicit transactions

### 7.2 Repositories

- Return domain entities
- Map ORM ↔ domain
- Do not expose SQLAlchemy models

Entities must not leak persistence details.

---

## 8. Logs, Auditing, and Traceability

- Critical actions must record:
  - Who
  - When
  - What
- Audit logs must be:
  - Immutable
  - Queryable
- Credited yields must store:
  - SGS series used
  - Reference date range
  - Effective rate applied

Without traceability, the system is invalid.

---

## 9. Testing (Mandatory)

- `pytest` and `pytest-asyncio` are mandatory
- The domain must have full coverage
- Tests must include:
  - Edge cases
  - Boundary dates
  - Rule changes (e.g., Selic threshold)

Happy-path-only tests are insufficient.

---

## 10. Dependency Policy

- Adding dependencies is forbidden by default
- Only permitted if it:
  - Increases security or precision
  - Does not duplicate existing features
  - Has a clear technical justification

Developer convenience is not a valid argument.

---

## 11. AI Agent Constraints

This document applies to all AI agents, including **Antigravity**.

The agent **must not**:

- Invent financial formulas
- Create implicit rules
- Assume undocumented business limits

When in doubt, the agent **must stop** and explicitly signal the gap (via `notify_user` in Antigravity's case) instead of filling it with assumptions.

---

## 12. Failure Philosophy

In financial systems:

- Failing loudly is better than failing silently
- Inconsistent states must:
  - Throw an error
  - Block execution
- Silent fallbacks are forbidden

---

## 13. Final Principle

Any change that:

- Reduces financial precision
- Diminishes auditability
- Mixes responsibilities

Is wrong by definition and requires explicit, documented justification.
