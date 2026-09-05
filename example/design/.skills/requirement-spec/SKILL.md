---
name: requirement-spec
description: Create an evidence-backed product requirements specification from an original or incomplete request. Use whenever a user asks to clarify requirements, fill product-detail gaps from the Wiki, reduce manual clarification, define acceptance criteria, or produce an SRS/PRD before solution design.
---

# Requirement Specification

Turn one original request into a reviewable requirements specification. Follow the project
`AGENTS.md`; this skill analyzes and writes the specification but does not design or implement code.

## Inputs

Require the original request and a feature/change identifier. Accept linked conversations,
mockups, existing requirements, and explicit constraints as supporting inputs. List missing inputs
instead of inventing them.

## Method

1. Resolve the frozen Wiki context and confirm the active Pack is `software-knowledge` and matched.
2. Decompose the request into actors, goals, triggers, observable behaviors, business rules, domain
   terms, data semantics, constraints, non-goals, dependencies, and acceptance signals.
3. Query relevant Wiki terms, capabilities, behaviors, rules, models, processes, interfaces,
   decisions, and known limitations. Use retrieved knowledge to answer only questions supported by
   evidence.
4. Use CodeGraph only when existing implementation facts can clarify current behavior or feasibility.
   Record the repository revision and query intent. Do not turn current implementation into a new
   requirement without labeling the inference.
5. Separate resolved details, assumptions requiring confirmation, conflicts, and genuinely open
   questions. Minimize questions by answering from evidence, but never hide uncertainty.
6. Make every requirement observable and give it a stable ID. Derive acceptance criteria from the
   requested behavior and known rules.

## Output

Write `docs/product-deliverables/requirements/<feature-id>.md` unless another target is supplied:

1. Document status, feature ID, inputs, Wiki context, repository revision
2. Background, problem, goals, non-goals
3. Actors and usage scenarios
4. Terms and domain rules
5. Functional requirements with stable IDs
6. Data, interface, compatibility, and operational requirements
7. Acceptance criteria mapped to requirement IDs
8. Assumptions, conflicts, unresolved questions
9. Evidence ledger with Wiki pages and optional CodeGraph/code anchors

Exclude security, privacy, authorization, and permission analysis unless explicitly requested.
Conclude with readiness: `ready_for_design` or `needs_clarification`, including the blocking items.
