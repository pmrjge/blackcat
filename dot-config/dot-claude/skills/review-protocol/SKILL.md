---
name: review-protocol
description: Load before reviewing code, a plan or security, or verifying work — evidence-gated findings, severity.
---
# Review protocol

## Scope
You are here because the brief asked or a review trigger fired (the rules list them); the builder already ran its own checks. Review the diff or artifact and its blast radius, not the whole codebase. One pass per artifact version.

## Principles
- Independent: judge the artifact, not the author's summary. Re-run the author's checks only when the report lacks their output or you have evidence against it.
- Evidence or nothing: each finding cites file:line, a command with ≤ 5 lines of its output, or a source URL with a quote. Confirm every finding (trace or reproduce); drop anything speculative, any "might", any taste. No style nits unless they hide a bug or the repo enforces them. Nothing verifiably wrong → VERDICT: pass, no questions, no follow-up.
- Ambiguity in the brief: state your assumption once in the report and review under it; never send a question back.
- Patch-ready: every finding carries a fix the author applies without asking — a unified diff against the reviewed revision, or the exact replacement text of a plan or proof step — and a proof: a command (test, repro, scanner rule, Lean check) that fails now and passes after the fix. A design-level finding names exactly what must change and the proof that will show it.

## Severity
- **CRITICAL** — exploitable security flaw, data loss/corruption, crash on the main path, wrong results.
- **HIGH** — likely bug in realistic use, missing auth/validation, race, leak, broken build or tests.
- **MEDIUM** — edge-case bug, weak error handling, performance problem at expected scale, missing tests for risky code.
- **LOW** — maintainability issue; report it only with a one-line patch.

## Plans
A **BLOCKING** finding means the plan cannot safely execute as written: an unverified load-bearing fact, a missing rollback/cleanup step, an ownership conflict between parallel steps, an ungated destructive action, a step with no objective done-when. Everything else is non-blocking. VERDICT fail = at least one BLOCKING finding.

## After the verdict
- pass-with-fixes: the author applies the patches and runs the proofs; no second review.
- fail: the author fixes, then re-runs only the failing findings' proofs (a verifier re-runs them for CRITICAL security or when the author cannot).
- Further rounds: the rules file's evidence-gated round trips ("Self-check and review").
- A re-check brief runs only the named proofs; no new findings unless a fix introduced them.

## Report
Clean pass: the rules' clean-finish line, then `VERDICT: pass — ran: <commands>`. Otherwise:
```
VERDICT: pass-with-fixes | fail
ASSUMED: <assumptions made for ambiguity; omit if none>
FINDINGS (most severe first):
- [SEV] path:line — defect — failure scenario
  evidence: <command + ≤ 5 lines output, or quote>
  proof: `<command>` (fails now)
  fix: <unified diff or exact replacement text>
NOT CHECKED: <what remains unverified; omit if nothing>
```

Related skills: `secure-coding` (security checklist), `formal-methods` (model check or proof beats reading), `proof-craft` (refereeing a mathematical argument).
