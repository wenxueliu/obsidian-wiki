---
name: design-spec
description: Generate a software design specification from an approved requirements specification using Wiki knowledge and the current codebase. Use for architecture design, change design, interface/data-flow design, technical方案, impact analysis, or deciding how an existing product should implement an SRS/PRD.
---

# Design Specification

Produce a design that satisfies the requirements and fits the current product. Follow the project
`AGENTS.md`; do not edit source code.

## Inputs

Require an approved requirements specification with stable requirement IDs. Accept diagrams,
constraints, previous proposals, and a target output path. Stop if requirements are materially
ambiguous rather than disguising product questions as technical choices.

## Method

1. Resolve the matched `software-knowledge` context.
2. Query Wiki systems, components, interfaces, models, processes, behaviors, rules, decisions,
   quality strategy, operations, and superseded alternatives relevant to each requirement.
3. Query CodeGraph for current entry points, owning symbols, implementations, dependencies, callers,
   data paths, interface boundaries, and nearby tests. Bind structural claims to the current revision.
4. Compare at least the viable alternatives. State drivers, trade-offs, rejected options, constraints,
   and conditions that would invalidate the preferred design.
5. Map every design element back to requirement IDs and forward to affected systems, interfaces,
   data, observability, rollout, and testability.
6. Keep code examples illustrative and minimal. Detailed file/symbol edits belong to
   `implementation-plan`.

## Output

Write `docs/product-deliverables/design/<feature-id>.md` unless another target is supplied:

1. Status, scope, source requirements, context and revision
2. Current-state evidence
3. Design goals, constraints, and non-goals
4. Proposed architecture and end-to-end flows
5. System/component responsibilities
6. Interface and data-model changes
7. Behavior, failure, recovery, observability, and compatibility handling
8. Alternatives and decision record
9. Requirement-to-design traceability matrix
10. Testability, rollout/migration, risks, open questions
11. Evidence ledger

Exclude security, privacy, authorization, and permission design unless explicitly requested. End
with `ready_for_implementation_planning` or the exact missing decisions.
