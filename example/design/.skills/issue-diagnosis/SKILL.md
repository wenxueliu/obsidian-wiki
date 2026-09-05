---
name: issue-diagnosis
description: Diagnose a product error from page symptoms, screenshots, logs, traces, or exception messages by combining Wiki knowledge with CodeGraph/code evidence, then produce a repair plan. Use whenever the user asks for root-cause analysis, troubleshooting, impact assessment, or a detailed fix方案 without immediately changing code.
---

# Issue Diagnosis and Repair Plan

Turn observed evidence into ranked hypotheses and a reviewable repair plan. Follow the project
`AGENTS.md`; do not modify code, configuration, data, or deployments.

## Inputs

Require an incident/issue ID, observed behavior, expected behavior when known, environment/version,
and at least one locator such as screenshot text, page state, timestamped log, trace, or exception.
Preserve raw evidence verbatim in references, not as unquestioned conclusions.

## Method

1. Resolve the matched `software-knowledge` context.
2. Normalize the symptom, timeline, affected user flow, scope, frequency, and reproduction status.
3. Query Wiki behaviors, rules, models, interfaces, decisions, operations, known failure modes,
   recovery knowledge, and related changes.
4. Use CodeGraph to trace the relevant entry point, handlers, callers/callees, data flow, error paths,
   configuration consumers, and tests at the current revision. Search code directly through
   CodeGraph when symbol or structural search is more precise than Wiki retrieval.
5. Rank hypotheses by supporting and contradicting evidence. Distinguish confirmed root cause from
   probable cause and identify the cheapest discriminating checks.
6. Produce a minimal repair strategy plus alternatives, blast radius, regression risks, and
   verification. Do not recommend a code edit without an exact evidence path to the affected area.

## Output

Write `docs/product-deliverables/diagnosis/<issue-id>.md` unless another target is supplied:

1. Status, symptom, expected behavior, environment, revision
2. Evidence and normalized timeline
3. Relevant Wiki knowledge and current implementation path
4. Ranked hypotheses with supporting/contradicting evidence
5. Root-cause conclusion and confidence, or next discriminating checks
6. Detailed repair tasks with files/symbols and invariants
7. Impact, compatibility, regression, rollout, rollback, and verification plan
8. Evidence ledger with log/screenshot locators, Wiki pages, tests, and CodeGraph query intents

Exclude security, privacy, authorization, and permission analysis unless explicitly requested. End
with `repair_plan_ready`, `needs_more_evidence`, or `not_reproduced`.
