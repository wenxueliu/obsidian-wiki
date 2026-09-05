---
name: test-design
description: Produce traceable test-case design from requirements and design specifications using Wiki behavior/rule knowledge and optional CodeGraph test discovery. Use for functional, boundary, compatibility, failure, migration, regression, or acceptance test design before implementation or review.
---

# Test Design

Design test coverage without implementing tests. Follow the project `AGENTS.md` and keep every case
traceable to requirements, design decisions, or known failure evidence.

## Inputs

Require the requirements specification. Require the design specification for implementation-aware
coverage; if it is unavailable, clearly limit the result to black-box requirement coverage.

## Method

1. Resolve the matched `software-knowledge` context.
2. Query Wiki behaviors, rules, models, process states, interfaces, compatibility facts, quality
   strategy, operations, incidents, and prior regressions.
3. Use CodeGraph when available to find existing test suites, test seams, affected callers,
   integrations, fixtures, state transitions, and likely regression surfaces.
4. Build a coverage model across happy paths, alternate paths, boundaries, invalid inputs, state and
   data combinations, failures/recovery, compatibility, migration, observability, and regression.
5. Avoid duplicate cases that exercise the same risk. Mark whether each case is unit, integration,
   contract, end-to-end, manual, or exploratory.
6. Identify requirements or design elements that are not testable and return them as specification
   defects rather than inventing expected results.

## Output

Write `docs/product-deliverables/tests/<feature-id>.md` unless another target is supplied:

1. Scope, inputs, environment assumptions, evidence
2. Coverage strategy and risk priorities
3. Test data and state model
4. Cases with ID, level, priority, preconditions, steps/input, expected result, and evidence source
5. Functional, boundary, compatibility, failure/recovery, migration, and regression sections
6. Requirement/design/test traceability matrix
7. Existing test reuse and CodeGraph anchors
8. Coverage gaps and specification defects

Do not add security, privacy, authorization, or permission cases unless explicitly requested. End
with `test_design_ready` or list the inputs preventing reliable expected results.
