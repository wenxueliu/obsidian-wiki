# Product Design Agent Rules

This repository develops one product. Replace the placeholders below before using the example:

- Product: `<PRODUCT_NAME>`
- Repository: `<REPOSITORY_PATH_OR_URL>`
- Primary vault: `<VAULT_PROFILE_OR_PATH>`
- Knowledge Pack: `software-knowledge`
- Deliverables root: `docs/product-deliverables/`

## Operating boundary

Use the Wiki only for requirements clarification, solution design, implementation planning, test
design, and issue diagnosis. Do not query or update the Wiki while writing code. Coding consumes
the approved detailed implementation plan and verifies it against the current repository and tests.
If implementation evidence invalidates the plan, stop coding and return the task to design or
implementation planning.

Security requirements, privacy analysis, authorization design, and permission test matrices are
outside this product workflow unless the input explicitly requests them. This scope rule does not
disable filesystem safety, source traceability, validation, or protection against accidental
overwrites.

The five design skills produce documents and plans only. They do not edit source code, run database
migrations, deploy services, or mark a proposed conclusion as approved.

## Evidence routing

- Use the resolved Wiki for durable product semantics: terminology, capabilities, behaviors, rules,
  models, processes, interfaces, decisions, quality strategy, operations, and earlier lessons.
- Use CodeGraph for current code structure: symbols, callers and callees, dependencies, entry
  points, implementations, test seams, and impact paths.
- CodeGraph may also search the repository when a query is structural or symbol-oriented. Wiki
  search remains preferred for intent, business meaning, constraints, decisions, and failure
  knowledge.
- Treat the current repository revision and executable tests as authoritative for current
  implementation facts. Treat approved requirements and design specifications as authoritative for
  intended behavior. Use the Wiki to explain durable context and rationale.
- Record the vault/config source, repository revision, Wiki pages consulted, CodeGraph queries, and
  unresolved evidence gaps in every deliverable.

## Shared execution rules

1. Resolve `wiki-context` once and require an active `software-knowledge` Pack with
   `optional_metadata.active_knowledge_pack.status=matched`.
2. Search index/frontmatter/summary first and open only relevant Wiki sections or pages.
3. Use CodeGraph only when code evidence can materially answer the question. Never copy a complete
   call graph or symbol inventory into the deliverable.
4. Distinguish `confirmed`, `inferred`, `conflicting`, and `unknown` statements.
5. Cite every non-obvious conclusion to an input section, Wiki page, code symbol/revision, test, log,
   or screenshot locator.
6. Do not silently resolve contradictions. Explain which authority wins and list remaining gaps.
7. Write the requested deliverable beneath `docs/product-deliverables/` unless the user supplies an
   explicit target.
8. Existing deliverables are owner content. Propose a diff or write a new version unless overwrite
   approval is explicit.

## Deliverable handoff

- Requirements specifications feed `design-spec` and `test-design`.
- Design specifications feed `implementation-plan` and `test-design`.
- The approved implementation plan is the only Wiki-derived artifact consumed during coding.
- Diagnosis results are repair plans; implementation begins only after the repair plan is approved.
- Accepted durable conclusions may later be compiled into the Wiki, but delivery documents
  themselves are not automatically Wiki knowledge pages.
