# Technologies & Engineering Foundations

This document maps the engineering techniques, methodologies, and prior art that each PlanForge skill builds upon. Understanding these foundations helps users recognise familiar patterns and predict skill behaviour.

---

## plan-brainstorming

| Technique | Origin | How it's applied |
|---|---|---|
| Hard gate — no code without design | Design Review Boards (Google ARB, Amazon, Microsoft); Stage-Gate (Robert Cooper, 1986) | The skill physically blocks downstream execution until a specification is produced |
| One question at a time | Socratic Questioning; GROW model (John Whitmore, 1992); Active Listening in requirements engineering (Karl Wiegers, 1999) | Structured elicitation prevents scope ambiguity |
| 2–3 alternatives with trade-offs | Trade Study (NASA, DoD); Architecture Decision Records (Michael Nygard, 2011) | Forces explicit comparison before commitment |
| Adaptive depth (Quick / Standard / Deep) | Process Tailoring (ISO 12207:2008 §6.1); CMMI maturity levels (SEI, 2002) | Scales formality to project risk |
| Uncertainty sweep | INCOSE Requirements Verification Checklist; Wiegers' requirements inspection (30+ quality criteria) | Systematic scan for incompleteness and ambiguity |
| 8 mandatory spec sections | IEEE 830 SRS standard (1993) | Ensures structural completeness |
| Visual companion | Miro/FigJam facilitation; EventStorming (Alberto Brandolini, 2013) | Real-time visual feedback during exploration |

---

## plan-writing

| Technique | Origin | How it's applied |
|---|---|---|
| TDD cycle per task | Test-Driven Development (Kent Beck, 2002); Extreme Programming (1999) | Every plan step includes red → green → refactor |
| Strict size limit (10 min / 100 lines) | PSP (Watts Humphrey, 1995); INVEST criteria — "Small" (Bill Wake, 2003); Pomodoro Technique | Recursive splitting when a step exceeds the limit |
| Full code, no placeholders | Literate Programming (Donald Knuth, 1984); Jupyter Notebooks (Fernando Pérez, 2001) | Plan steps contain complete, executable code |
| Spec Contract Preflight | Design by Contract (Bertrand Meyer, 1988); Type-system interface contracts | Plan generation validates against the spec before writing |
| "Read before modify" invariant | IDE refactoring tools (IntelliJ, Eclipse, ~2001) | Agent must read the target section before editing |
| Exact line references | Unix patch/diff format (Larry Wall, 1975–1985) | Edits specify precise line ranges |
| Self-review checklist | Author self-inspection (Wiegers, 1999) | Structured verification before handoff |

---

## plan-iterative-revision

### Fingerprint-based issue identity

| Technique | Origin | How it's applied |
|---|---|---|
| Stable issue fingerprint | SonarQube issue keys (~2008); Coverity CID (~2006); Semgrep rule matches (~2019) | SHA-1(category + required_fix)[:8] gives each issue a persistent identity across iterations |
| Issue lifecycle tracking | Bugzilla (1998); Jira (2002) — NEW → RESOLVED → REOPENED | Fingerprints track issues through new → resolved → reintroduced states |

### Set-algebraic flow analysis

| Technique | Origin | How it's applied |
|---|---|---|
| `new = current − cumulative` | SonarQube "New Issues" / "New Code" period | Identifies issues appearing for the first time |
| `resolved = prev − current` | SonarQube "Fixed Issues" metric | Identifies issues that disappeared since last iteration |
| `persisted = prev ∩ current` | SonarQube "Remaining Issues" metric | Identifies issues present in both iterations |
| `reintroduced = (cumulative − prev) ∩ current` | SonarQube REOPENED status; Jira REOPENED workflow | Detects issues that were fixed but have returned |
| Regression detection → hard stop | Flaky test detection (Google, 2020); SonarQube Quality Gate on reopened issues | Loop halts immediately when reintroduced ≠ ∅ |
| Churn / stagnation detection | Deadlock detection (Dijkstra, 1965); Liveness analysis in model checking (Clarke, Emerson, Sifakis, 1980s) | Loop halts when no progress is made over a sliding window |
| Fixed-point convergence | Banach fixed-point theorem (1922); Fixed-point iteration in numerical analysis | Loop terminates when issue set reaches ∅ |

### Two-phase architecture

| Technique | Origin | How it's applied |
|---|---|---|
| Phase A (audit) reads only; Phase B (implement) writes only | Fagan Inspection (IBM, 1976); Separation of Duties (SOX, PCI-DSS) | Prevents the agent from silently masking issues it introduced |
| Immutable review files | Audit trail / Event log (SOX, PCI-DSS, Basel III); Git append-only history | Each iteration produces a numbered, never-overwritten review artifact |

### Error taxonomy

| Technique | Origin | How it's applied |
|---|---|---|
| 10-class taxonomy with per-class sweep | CWE (MITRE, ~2006); OWASP Top 10 (~2003); IEEE 1044 (1993) | Agent re-reads the plan once per class to prevent attention scattering |

---

## plan-splitter

| Technique | Origin | How it's applied |
|---|---|---|
| Hierarchical decomposition | WBS — Work Breakdown Structure (PMBOK/PMI, 1987); SAFe decomposition (Dean Leffingwell, ~2011) | Plan is split into self-contained stages |
| DAG dependencies | Make (Stuart Feldman, 1976); Bazel (Google, 2015); Apache Airflow DAGs (2015) | Stages declare explicit dependency edges |
| Self-contained bounded units | Bounded Context (Eric Evans, DDD, 2003); Independent Deployability (Sam Newman, 2015) | Each stage is executable without back-references |
| "Do not split" gate | Stage-Gate kill decision (Cooper, 1986) | Splitting is refused when the plan is already atomic |
| Roadmap as stage 0 | Project Charter (PMBOK) | A summary file precedes all stage files |
| Three-level verification | Three Lines of Defense (Basel Committee, ~2000s); Multi-tier code review (Google, Microsoft) | Automated → peer → deep-agent verification |
| Deep verification via subagent | Red Team / Blue Team (military, cybersecurity, ~1990s); Independent QA team | A separate agent audits each stage |

---

## plan-executor

| Technique | Origin | How it's applied |
|---|---|---|
| Immutable plan + separate state ledger | Terraform plan/apply + tfstate (HashiCorp, 2014); Flyway schema_history (2006); Liquibase DATABASECHANGELOG | Plan file is never modified; progress lives in a ledger |
| State managed only through CLI | Terraform CLI-only state mutation; Airflow metadata DB (2015) | Prevents manual ledger corruption |
| "No tests → escalation" gate | CI coverage gates (JaCoCo, Cobertura); SonarQube Quality Gate (~2008); Fail-fast (Google SRE Book, 2016) | Execution halts if test evidence is missing |
| Checkpoint / restore | Database savepoints (SQL standard, ~1992); VM snapshots (VMware, ~2001); Git tags on green builds | Agent can roll back to last known-good state |
| Adaptive verification levels (🟢/🟡/🔴) | Risk-based testing (ISTQB, ~2000s); Deployment pipelines with canary stages (Jez Humble, 2010) | Verification depth scales with assessed risk |
| Destructive operation confirmation | Terraform plan output with confirmation prompt (2014) | Irreversible actions require explicit approval |
| Multi-session parallelism | Make -j (GNU Make, ~1988); Airflow parallel tasks (2015) | Independent tasks can be distributed across sessions |
| Stop report on failure | CI/CD failure notifications (Jenkins, GitHub Actions, GitLab CI) | Structured report explains why execution halted |

---

## plan-resolver

| Technique | Origin | How it's applied |
|---|---|---|
| Read-only audit invariant | Financial audit (centuries); Separation of Duties (SOX, PCI-DSS, ISO 27001); Security audit / penetration testing (OWASP) | Resolver never modifies the plan or codebase |
| SHA-256 workspace snapshot | WORM storage (SEC Rule 17a-4, ~1990s); Reproducible Builds (Debian, ~2013); in-toto / SLSA (Google/NYU, ~2020) | Cryptographic proof that nothing changed during audit |
| Multi-pass with memory | Regression testing with known-bug suites; SonarQube historical analysis (~2008) | Each pass remembers previously found issues |
| Formal sign-off | FAT — Factory Acceptance Test; UAT — User Acceptance Testing (ISTQB); DO-178C certification (RTCA, 2012) | Final report serves as a verifiable completion artifact |
| Error taxonomy | CWE (MITRE, ~2006); OWASP Top 10 (~2003); IEEE 1044 (1993) | Standardised classification of findings |
| Report co-located with plan | Financial audit report attached to ledger (audit standard) | Report file lives next to the audited plan |

---

## Pipeline as a whole

The full skill pipeline (`brainstorming → writing → [splitter] → executor → resolver`, with `iterative-revision` available at any stage) draws from:

| Pipeline model | Origin | Shared principle |
|---|---|---|
| V-Model | German Federal Ministry of Defence, 1990s | Each design level has a corresponding verification level |
| Cleanroom Software Engineering | Harlan Mills, IBM, 1980s | Formal specification → stepwise refinement → statistical testing → certification |
| DO-178C | RTCA, 2012 | Immutable traceability, formal gates, independent audit |
| Terraform workflow | HashiCorp, 2014 | Immutable plan, state ledger, confirmation gates |
| MetaGPT | Tsinghua University, 2023 | Multi-agent pipeline with role specialisation and structured artifacts |

---

## Key design principles

| Principle | Provenance |
|---|---|
| Immutable source artifacts | Event Sourcing; Git; Blockchain (Merkle, 1979) |
| Formal gates between phases | Stage-Gate (Cooper, 1986); Design Review Boards |
| Machine-verifiable transitions | Static analysis gates (SonarQube, Coverity); CI/CD pipelines |
| Separation of read and write roles | Fagan Inspection (1976); SOX Separation of Duties (2002) |
| Deterministic tooling (Python stdlib, no deps) | Reproducible Builds (Debian); Hermetic builds (Bazel) |
| Append-only audit trail | WORM; Event log; in-toto supply-chain attestation |
