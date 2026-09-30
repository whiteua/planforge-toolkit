# Error Taxonomy

The 10 issue classes for Phase A. Within a lens, check one class at a time: it keeps attention
focused. Each class lists guiding questions.

## 1. logic

Contradictions, circular dependencies, unreachable branches, incompatible preconditions.

- Does a step rely on state that has not been created yet?
- Do two requirements contradict each other ("always X" vs "sometimes not X")?
- Are all branches and conditions reachable?
- Are the invariants declared at the top of the plan respected?

## 2. code

Missing files, functions or types; wrong signatures; race conditions; resource leaks.

- Do all mentioned files exist, and are all mentioned functions and classes found?
- Do the described signatures match the real ones?
- Is concurrency handled where state is shared?
- Is resource handling described (connections, files, transactions, unsubscribes)?

## 3. math

Formulas, units, off-by-one, overflow, rounding, currency.

- Are all formulas in consistent units, with explicit conversions?
- Is overflow or underflow possible?
- Off-by-one in ranges, indexes, date boundaries?
- Money rounding: mode (banker's or half-up) and precision fixed?
- Are currency rates applied consistently?

## 4. ops

Migrations, downtime, access rights, rollback, monitoring, secrets.

- Is there an explicit rollback for each destructive operation?
- Is the downtime or zero-downtime approach stated?
- Who has access (roles)? Least privilege?
- Where are secrets stored? Can they leak into logs or the plan?
- Is monitoring and alerting planned for the new functionality?
- Are feature flags or gradual rollout described?
- Which steps reach an external system, and on which environment? Is each environment listed in
  the plan header with the user's quoted permission? Does any step run on production when only
  a test environment is permitted (check the project script behind the command)?

## 5. db

Indexes, foreign keys, NOT NULL, column types, migrations, concurrency.

- Is every new WHERE/JOIN condition covered by an index?
- Are foreign keys defined, with consistent ON DELETE/UPDATE?
- Is NULL semantics explicit for every new column?
- Do column types fit the data (INT vs BIGINT, VARCHAR(N))?
- Are migrations idempotent, with a rollback migration?
- Are concurrent updates handled (optimistic or pessimistic locking)?
- Are there unique indexes for business keys?

## 6. contract

API and integration mismatches: methods, paths, payloads, status codes.

- Are method, path, query, body and response fully described?
- Do they match the real routing in the code?
- Is API versioning handled? Are breaking changes for existing clients marked?
- External integrations: timeouts, retries, idempotency keys?

## 7. tests

Acceptance criteria, testability, coverage.

- Does every feature have acceptance criteria, and are they measurable?
- Are test types stated (unit, integration, e2e)?
- Are edge cases listed explicitly?
- Are performance criteria (if relevant) quantitative?

## 8. security

Authorization, input validation, injections, secrets, OWASP.

- Does every new endpoint describe authentication and authorization?
- Is input validation and sanitization described?
- Are SQL, NoSQL and command injections excluded by parameterization?
- Are secrets kept out of the plan and code (placeholders are fine)?
- Are CSRF, XSS and SSRF handled where relevant?
- Can logging leak PII or tokens?
- Are rate limiting and brute-force protection mentioned where needed?

## 9. perf

N+1, missing pagination, uncontrolled joins, heavy work on the hot path.

- Do lists have pagination or limits?
- Any N+1 in loops over entities?
- Is caching described where it is clearly needed?
- Are expected data volumes and load estimated?
- Any blocking I/O on hot paths?

## 10. code-plan-mismatch

The plan describes a state that does not exist, ignores what exists, or uses different names.

- Do all mentioned names (classes, methods, tables, columns, endpoints) exist in the code?
- If the plan describes "how it works today", does that match reality?
- If the plan describes changes, are neighboring systems taken into account?
- Are existing migrations and schema versions reflected in the plan's starting point?

## Legacy: unfulfilled-contract

Old reviews used this category for contracts that the plan had not applied. New audits keep the
original category and use `carry` instead (see PHASE-A-AUDIT.md, Step 1), so that the fingerprint
stays stable.
