---
name: review-protocol
description: Load before reviewing code, a plan or security, or verifying someone else's work. Review and verification protocol — independence rules, severity rubric and report format.
---
# Review protocol

## Principles
- Independent: judge the artifact, not the author's summary. Re-derive and re-run.
- Evidence or it didn't happen: each finding cites file:line, a command with its output, or a source URL.
- Real issues only: no style nits unless they hide a bug or the repo enforces them. Confirm every finding (trace or reproduce) before reporting it.

## Severity
- **CRITICAL** — exploitable security flaw, data loss/corruption, crash on the main path, wrong results.
- **HIGH** — likely bug in realistic use, missing auth/validation, race, leak, broken build or tests.
- **MEDIUM** — edge-case bug, weak error handling, performance problem at expected scale, missing tests for risky code.
- **LOW** — maintainability issue worth fixing soon.

## Plans
For a plan (not code): a **BLOCKING** finding means the plan cannot safely execute as written — an unverified load-bearing fact, a missing rollback/cleanup step, an ownership conflict between parallel steps, an ungated destructive action, or a step with no objective done-when. Everything else (style, sequencing that works but could be tighter, minor risk without a mitigation) is **non-blocking**. VERDICT fail means at least one BLOCKING finding remains.

## Report
```
VERDICT: pass | pass-with-fixes | fail
FINDINGS (most severe first):
- [SEV] path:line — defect — concrete failure scenario — fix
CHECKED: what you read/ran
NOT CHECKED: what remains unverified
```

Related skills: `secure-coding` (the security checklist), `formal-methods` (when a model check or proof beats reading), `proof-craft` (refereeing a mathematical argument).
