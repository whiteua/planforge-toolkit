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
| 8 mandatory spec sections | IEEE 830 SRS standard (1993) | Ensures structural completeness; checked deterministically by `brainstorm_tool.py spec-check` |
| Visual companion | Miro/FigJam facilitation; EventStorming (Alberto Brandolini, 2013) | Real-time visual feedback during exploration |
| Findings triage and traceability | Defect triage (IEEE 1044 anomaly classification); requirements traceability matrix | JSON review findings are validated by a CLI, verified against code, and each id is traced to a fix or to Out of Scope by a coverage gate |
| Fidelity check | Requirements traceability; goal-question-metric (Basili, 1994) | The request is restated in one sentence at the start and compared with the spec's Goal and Out of Scope before hand-off; drift is named and asked about |
| Chain settings decided up front | Single source of truth; configuration as code | Decisions for the whole chain and environment access are written into the spec, validated by `spec-check` and read by every later skill through one rule (`settings`) |
| Separate read and change consent | Least privilege; change approval (ITIL change enablement) | `read=` / `write=` per environment with `run`, `task` or `deny`; production changes are never allowed for a whole run |
| Shared append-only backlog | Product backlog (Scrum); append-only log | `backlog-append` adds one line at the end of a goal's section and verifies that every other byte is unchanged; `backlog-mark` checks off an item of an approved spec and `backlog-unmark` unchecks one an amended or withdrawn spec no longer covers, each changing only its checkbox byte; `backlog-sweep` reads a section's open items and the specs of its chain journal for a match by meaning that the user confirms; `[-]` marks an item the user cancelled |
| Deterministic language detection | Unicode block heuristics | `detect-lang`: Cyrillic letters over 5% of all letters → Russian; every user-facing message of every skill follows it |
| Chain journal as a state machine | Workflow engines (Apache Airflow task states, 2015; AWS Step Functions, 2016); finite-state machines | Each plan has seven stages with checked transitions (`illegal-transition`, exit 1); a finished stage re-opens only for a named reason; events are append-only and `journal-validate` replays them against the stored statuses and checks every time field against the `YYYY-MM-DDTHH:MM:SSZ` format |
| Lock file with stale takeover | `git` `index.lock`; exclusive create (`O_CREAT \| O_EXCL`) | Writes take `<journal>.lock`, wait up to 10 s (`journal-locked`) and take over a lock older than 60 s with a `lock-takeover` event |
| Atomic replace | POSIX `rename(2)` atomicity; write-temp-then-rename | The journal and `BACKLOG.md` are written to a temporary file in the same directory and swapped with `os.replace`; the file mode and a symlinked target are kept |
| Reconciliation from artifacts | Kubernetes controller reconcile loop (2014); `fsck` | `journal-reconcile` derives stage statuses from the files the skills left (plan, completion, roadmap, ledger, diff report, reports, commits) and turns a changed stage input into a drift question |
| Single findings stream | Deduplicated issue intake (Sentry fingerprinting); single source of truth | Findings of the executor, the resolver and the revision are recorded once per `file` + `summary`, appended to `BACKLOG.md` at once and exported as `<goal>-followups.json`, the input format of `findings-parse` |
| Questions as durable state | Human-in-the-loop callback tasks (AWS Step Functions); ticket lifecycle | A run without a confirmation channel records `Qn` (`open → answered → applied`) and stops; the owning skill applies the answer on resume |
| Amend mode by the spec's owner | Change control (IEEE 828 configuration management); single ownership | An approved spec is changed in place by `plan-brainstorming`, re-checked and re-approved; the journal sees the change through the `writing` stage's input hash and asks a drift question instead of keeping a stale plan |

---

## plan-writing

| Technique | Origin | How it's applied |
|---|---|---|
| TDD cycle per task | Test-Driven Development (Kent Beck, 2002); Extreme Programming (1999) | Every task writes the failing test, runs it, implements, runs it again |
| Codebase grounding | Fact-checking / citation requirements; reproducible baselines in CI | Existing symbols are cited as `path:line`, `Create:` targets must be new, and the plan header records the test baseline; `plan-check --root` verifies paths against the repository |
| Strict size limit (10 min / 100 lines) with justified exceptions | PSP (Watts Humphrey, 1995); INVEST criteria — "Small" (Bill Wake, 2003); Pomodoro Technique; deviation records with a rationale (MISRA Compliance) | Recursive splitting when a task exceeds the limit; a task that cannot be split carries `**Size:** <N> lines — <reason>`, and `plan-check` fails above 150 lines without it |
| Full code, no placeholders | Literate Programming (Donald Knuth, 1984); Jupyter Notebooks (Fernando Pérez, 2001) | Plan steps contain complete, executable code |
| Spec Contract Preflight | Design by Contract (Bertrand Meyer, 1988); Type-system interface contracts | `brainstorm_tool.py spec-check` validates the spec before any plan is written |
| Plan format contract check | Schema validation / linting (lint, Stephen Johnson, 1978) | `plan_tool.py plan-check` enforces the header, task headings, unique ids and task core that the executor and resolver parse |
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
| Churn / stagnation detection | Deadlock detection (Dijkstra, 1965); Liveness analysis in model checking (Clarke, Emerson, Sifakis, 1980s) | Loop halts when the issue set is unchanged or nothing is resolved over a sliding window |
| Stuck-issue escalation | Starvation detection in schedulers; SLA breach escalation in ITSM | A fingerprint present in 3 consecutive audits stops the loop for a manual decision |
| Single gate authority | Policy decision point (XACML, 2003); Quality Gates (SonarQube) | One `record` call evaluates every gate over the current run's history; the agent only executes the action |
| Fixed-point convergence | Banach fixed-point theorem (1922); Fixed-point iteration in numerical analysis | Loop terminates when issue set reaches ∅ |

### Two-phase architecture

| Technique | Origin | How it's applied |
|---|---|---|
| Phase A (audit) reads only; Phase B (implement) writes only | Fagan Inspection (IBM, 1976); Separation of Duties (SOX, PCI-DSS) | Prevents the agent from silently masking issues it introduced |
| Immutable review files | Audit trail / Event log (SOX, PCI-DSS, Basel III); Git append-only history | Each iteration produces a numbered, never-overwritten review artifact, rendered and validated by the tool from the agent's JSON findings |

### Error taxonomy

| Technique | Origin | How it's applied |
|---|---|---|
| 10-class taxonomy with per-class sweep | CWE (MITRE, ~2006); OWASP Top 10 (~2003); IEEE 1044 (1993) | Agent reads the plan once and checks one class at a time to prevent attention scattering |

### Chain integration

| Technique | Origin | How it's applied |
|---|---|---|
| Settings from the spec | Single source of truth | `bootstrap` returns the chain settings; preset and stop policy are taken from them without a question, and `read=run` allows read-only checks of that environment during the audit |

---

## plan-splitter

| Technique | Origin | How it's applied |
|---|---|---|
| Hierarchical decomposition | WBS — Work Breakdown Structure (PMBOK/PMI, 1987); SAFe decomposition (Dean Leffingwell, ~2011) | Plan is split into self-contained parts |
| DAG dependencies | Make (Stuart Feldman, 1976); Bazel (Google, 2015); Apache Airflow DAGs (2015) | Stages declare explicit dependency edges |
| Self-contained bounded units | Bounded Context (Eric Evans, DDD, 2003); Independent Deployability (Sam Newman, 2015) | Each part is executable without back-references |
| "Do not split" gate | Stage-Gate kill decision (Cooper, 1986) | Splitting is refused when the plan is already atomic |
| Roadmap file | Project Charter (PMBOK) | `<base>-roadmap.md` holds the dependency table and parallel groups; parts are `<base>-a.md`, `-b.md`, … |
| Three-level verification | Three Lines of Defense (Basel Committee, ~2000s); Multi-tier code review (Google, Microsoft) | A: formal checks (`validate-all`), B: cross-validation (task coverage, origin hash), C: the agent re-reads every part for self-sufficiency and handoff |
| Deep verification with a machine gate | Red Team / Blue Team (military, cybersecurity, ~1990s); Independent QA team; Quality Gates (SonarQube) | One `plan-iterative-revision` run audits every part in turn; `verify-status` accepts a claimed result only when the review files and part hashes prove it |
| Task properties carried verbatim | Lossless transformation; traceability | `**External:**` and `**Size:**` lines move into the parts unchanged; the `split` setting replaces the gate in a chain |

---

## plan-executor

| Technique | Origin | How it's applied |
|---|---|---|
| Immutable plan + separate state ledger | Terraform plan/apply + tfstate (HashiCorp, 2014); Flyway schema_history (2006); Liquibase DATABASECHANGELOG | Plan file is never modified; progress lives in a ledger |
| State managed only through CLI | Terraform CLI-only state mutation; Airflow metadata DB (2015) | Prevents manual ledger corruption |
| "No tests → escalation" gate | CI coverage gates (JaCoCo, Cobertura); SonarQube Quality Gate (~2008); Fail-fast (Google SRE Book, 2016) | Execution halts if test evidence is missing |
| Checkpoint / restore | Database savepoints (SQL standard, ~1992); VM snapshots (VMware, ~2001); `git stash create` / hidden refs (Git plumbing) | Per-unit snapshots in `refs/plan-executor/<run>/<unit>` via a temporary index and `commit-tree`; restore returns files to the last good snapshot without touching the branch, HEAD or index |
| Adaptive verification levels (🟢/🟡/🔴) | Risk-based testing (ISTQB, ~2000s); Deployment pipelines with canary stages (Jez Humble, 2010) | Verification depth scales with assessed risk |
| Destructive operation confirmation | Terraform plan output with confirmation prompt (2014) | Irreversible actions require explicit approval |
| Retry-first ordering with stagnation stop | Circuit breaker (Nygard, *Release It!*, 2007); bounded retry with backoff | A failed unit is retried before anything else runs; 3 attempts or the same error signature twice stops the run |
| Drift detection on resume | Terraform state refresh / plan drift (HashiCorp); lockfile hashes (npm, Cargo) | The ledger stores the plan's SHA-256; a changed plan stops the run until the engineer decides |
| Confirmation for external units | Change approval for production access (ITIL change enablement); least privilege; standard changes pre-approved | A unit marked `External` runs without a question only when its access is `run` in the settings or consented for the run (`consent`); `unit-begin` reports `confirmed` and the `source` of the consent, and run consents are cleared on resume |
| Foreign-change detection | File integrity monitoring (Tripwire, 1992); expected-state comparison | `unit-begin` compares the working tree with the ledger's `expected_tree` and stops with `foreign-changes` (added, modified, deleted paths) before the next unit |
| Per-file restore | Partial rollback; `git checkout <tree> -- <paths>` | `checkpoint-restore --paths` restores only the listed files; `--exec-dir` moves the expected tree so a retry raises no false alarm |
| Settings drift | Terraform plan drift; lockfile hashes | The ledger stores the SHA-256 of the settings' source; a changed spec stops the run with `settings-drift` until the engineer accepts it |
| Risk-scaled gate per unit | Risk-based testing (ISTQB) | Checkpoint, documentation-only and test-only tasks get a lighter gate than the plan tier |
| Stop report on failure | CI/CD failure notifications (Jenkins, GitHub Actions, GitLab CI) | Structured report explains why execution halted |
| Diff report of the run | Code review diffs (Gerrit, GitHub pull requests); `git diff --numstat` | `run-diff --markdown` writes `<base>-diffs.md`: a file table with status and line counts, one `diff` block per file with an adaptive fence, cut at 400 lines, pipeline artifacts excluded; `--include-fixes` adds the audit's fixes, and fix files git ignores are listed under "Not included (ignored by git)" |
| Scoped commit stage | Maker–checker; Git hooks; Conventional Commits (2017) | `commit-run` commits only the run's files and the audit's fix files with hooks; it refuses a non-empty index, files the user had changed before the run (`mixed-files`, against `baseline_head`), foreign changes and the edits of a failed unit that was not rolled back (`failed-attempt`), and never pushes, amends, forces or skips hooks |
| Graceful degradation without git | Feature detection | Outside git, `run-diff --markdown` and `commit-run` fail with `no-git` and the `diffs` and `commit` stages are `skipped`; the rest of the run works |

---

## plan-resolver

| Technique | Origin | How it's applied |
|---|---|---|
| Read-only audit invariant | Financial audit (centuries); Separation of Duties (SOX, PCI-DSS, ISO 27001); Security audit / penetration testing (OWASP) | An audit pass never modifies the plan or codebase; it writes only its report and appended lines of `BACKLOG.md`, and `assert-readonly` allows exactly these paths |
| Separated fix → re-audit loop | Separation of Duties (maker–checker); PDCA cycle (Deming, 1950s); bounded retry / circuit breaker | `fix`/`auto` repair code in a separate phase under SHA-256 protection of the plan and reports; only an independent re-audit closes an issue; the loop stops on final, cycle limit (default 2), stall, or issues needing a user decision |
| SHA-256 workspace snapshot | WORM storage (SEC Rule 17a-4, ~1990s); Reproducible Builds (Debian, ~2013); in-toto / SLSA (Google/NYU, ~2020) | Cryptographic proof that nothing changed during audit |
| Multi-pass with memory | Regression testing with known-bug suites; SonarQube historical analysis (~2008) | Each pass remembers previously found issues |
| Formal sign-off | FAT — Factory Acceptance Test; UAT — User Acceptance Testing (ISTQB); DO-178C certification (RTCA, 2012) | Final report serves as a verifiable completion artifact |
| Error taxonomy | CWE (MITRE, ~2006); OWASP Top 10 (~2003); IEEE 1044 (1993) | Standardised classification of findings |
| Report co-located with plan | Financial audit report attached to ledger (audit standard) | Report file lives next to the audited plan |
| Probe evidence for verification tasks | Test evidence in acceptance records (FAT/UAT) | A checkpoint or manual verification is closed by its command and result (`evidence_probe`), never by an arbitrary code reference; code tasks still need an anchor |
| Executor-reported marker | Reliance on the work of others (ISA 600, audit standard) | Tasks the audit cannot re-verify are closed on the executor's record and listed separately |
| Verified evidence anchors | Citation checking; link validation | `validate-report --root` checks that every `path#Lx-Ly` on a closed task or in issue evidence points at existing lines |
| Authoritative fix diff | Reproducible builds; before/after snapshots | The fix phase is bracketed by workspace fingerprints and `snapshot-diff` lists the changed files, which the Fix Log must account for |
| Re-verification under a run-scope read | Reliance limited to what cannot be re-performed (ISA 500) | With `read=run`, tasks marked `External (read)` are re-checked by the audit instead of being closed as `executor-reported` |
| Fix files handed to the commit stage | Separation of Duties (maker–checker) | The fix phase records the files `snapshot-diff` lists as `fix_files` (repository-root paths) in the chain journal; the resolver runs no mutating git command, and its gate names `/plan-executor <plan> commit` |

---

## plan-chain-runner

| Technique | Origin | How it's applied |
|---|---|---|
| Dependency-graph scheduling | Make (Stuart Feldman, 1976); Apache Airflow DAG scheduler (2015) | `run-next` issues a spec's stages only after the specs it depends on are committed; independent specs are planned in parallel up to `parallel` |
| Mutual exclusion for code stages | Critical sections (Dijkstra, 1965); single-writer principle | Execution, diffs, audit and commit run for one plan at a time, because the executor and the resolver watch the whole working tree |
| Quiescent audit | Write freeze during an audit; snapshot isolation | Nothing else is issued while an audit runs, and the runner writes nothing into the journal then; only the session file outside the working tree |
| Trust, but verify agent reports | Reconciliation loop (Kubernetes controllers, 2014) | A stage counts as done only when `journal-reconcile` and `journal-show` confirm it; an unconfirmed stage after any return of the agent (or 60 minutes of silence) gets one retry, then a `not-confirmed:` question |
| Host capability profiles with graceful degradation | Feature detection; capability negotiation | `claude-code` (Claude Code `Agent` tool, model per role), `github-copilot` (GitHub Copilot CLI `task` tool, effort inherited), `fallback` (one session, one stage at a time); a missing capability moves the runner to the next profile |
| Model per role | Role specialisation (MetaGPT, 2023); cost-tiered workers | `~/.planforge/runner.json` maps each role to a model and effort; a full model id pins the version (`settings-load` `pinned`), an alias follows the newest model of its family; `model-pick --journal --unsupported` falls back to the role's `fallback` model from the journal's table or asks |
| Session lease with heartbeat | Leases (Gray & Cheriton, 1989); heartbeat failure detection; fencing tokens | The session file holds the session id and `heartbeat_at`; younger than 30 minutes means another runner is active, older means an abandoned run (asked about when a stage is still running); `--heartbeat`/`--end` with another id fail with `session-taken-over` |
| ETA from history | Evidence-based scheduling (Joel Spolsky, 2007) | `run-eta` averages the journal's past stage durations and per-unit execution times |
| Machine-readable questions | Enumerated answers; command tokens in protocols | Questions the scheduler acts on start with fixed prefixes and take fixed tokens (`accept`/`fix`, `retry`/`stop`, `rewrite`/`keep`) |

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
| Resumable, journaled chain | Event sourcing; workflow engines (Airflow, Step Functions) |
