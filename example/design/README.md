# Single-product design workflow example

This example shows how one product team can use the `software-knowledge` Knowledge Pack during
requirements, design, test design, and diagnosis without consulting the Wiki while coding.

```text
design/
├── AGENTS.md
└── .skills/
    ├── requirement-spec/SKILL.md
    ├── design-spec/SKILL.md
    ├── implementation-plan/SKILL.md
    ├── test-design/SKILL.md
    └── issue-diagnosis/SKILL.md
```

The files are examples, not production skills registered by this repository. Copy `AGENTS.md` and
the desired skill directories into a product repository, then adapt the placeholders and output
paths. Agent-specific setup may install the skill directories under `.agents/skills/`,
`.claude/skills/`, or another supported project-local target.

## Intended sequence

1. `requirement-spec` turns an original request into an evidence-backed requirements specification.
2. `design-spec` combines that specification, Wiki knowledge, and current code structure into a
   design specification.
3. `implementation-plan` produces the detailed coding handoff: exact impact, edits, and checks.
4. `test-design` derives functional, boundary, compatibility, failure, and regression test cases.
5. `issue-diagnosis` turns observed errors or logs into an evidence-ranked repair plan.

During implementation, use the approved detailed implementation plan plus the current repository
and tests. Do not query the Wiki again unless the task returns to analysis or the approved plan is
invalidated.

## Required environment

- An initialized vault using the `software-knowledge` Knowledge Pack.
- The normal `wiki-context` and `wiki-query` skills.
- Optional CodeGraph integration. When it is unavailable, the skills report the missing structural
  evidence instead of inventing results.
- Product-specific values filled into `AGENTS.md`.

Generated specifications are delivery artifacts, not automatically canonical Wiki pages. Compile
only durable terms, rules, behaviors, decisions, quality strategy, and failure knowledge back into
the Wiki through the normal ingest/update workflow.
