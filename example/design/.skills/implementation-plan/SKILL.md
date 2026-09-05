---
name: implementation-plan
description: Convert approved requirements and design specifications into a detailed, coding-ready implementation plan grounded in Wiki constraints and CodeGraph impact analysis. Use when the user wants task breakdown, exact modification方案, affected files/symbols, sequencing, migration steps, or a handoff that coding can follow without consulting the Wiki.
---

# Detailed Implementation Plan

Create the frozen handoff consumed during coding. Follow the project `AGENTS.md`; inspect code but do
not modify it.

## Inputs

Require approved requirements and design specifications. Record their versions and stable IDs.
Reject contradictory or unapproved inputs and return them to the owning phase.

## Method

1. Resolve the matched `software-knowledge` context for the final pre-coding knowledge lookup.
2. Query Wiki constraints, decisions, interfaces, behaviors, rules, models, operations, quality
   strategy, and known failure modes that constrain implementation.
3. Use CodeGraph deeply: locate exact entry points, symbols, callers/callees, implementations,
   dependency paths, configuration, persistence boundaries, tests, and blast radius at the current
   repository revision.
4. Break work into ordered, independently verifiable tasks. For each task identify exact files or
   symbols, intended change, invariants, dependencies, tests, and completion evidence.
5. Include migrations, compatibility transitions, feature flags, rollout/rollback, generated assets,
   and documentation only when the approved design requires them.
6. Resolve evidence gaps before handoff or label the plan blocked. Do not tell the coding phase to
   “query the Wiki later.” Include all relevant Wiki-derived constraints directly in the plan.

## Output

Write `docs/product-deliverables/implementation/<feature-id>.md` unless another target is supplied:

1. Frozen input versions, repository revision, assumptions
2. Current implementation map with stable code anchors
3. Ordered task graph and dependencies
4. Per-task files/symbols, change details, invariants, and acceptance checks
5. Interface/data/configuration/migration changes
6. Test modifications and verification commands
7. Rollout, rollback, compatibility, and observability steps
8. Risks, unresolved blockers, and explicit exclusions
9. Requirement → design → task → test traceability
10. Evidence ledger and CodeGraph query intents

End with `ready_for_coding` only when a coding agent can execute the plan using the document,
repository, and tests without querying the Wiki. Otherwise return `planning_blocked`.
