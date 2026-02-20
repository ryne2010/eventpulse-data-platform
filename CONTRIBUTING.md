# Contributing

This repo is designed to be **readable, mechanically validated, and agent-friendly**.

Keep contributions small, testable, and legible.

## Principles

- The repository is the system of record: encode decisions in versioned docs.
- Prefer mechanical validation (lint/typecheck/tests) over subjective review.
- Preserve architectural boundaries and contracts.

## Before you change behavior

If a change affects public interfaces, invariants, or architecture:

1. Write or update an ADR in `docs/DECISIONS/`.
2. Update `docs/CONTRACTS.md` and/or `docs/DESIGN.md`.
3. Ensure tests cover the intended behavior.

## Tooling setup

### Python

```bash
uv sync --dev
```

### UI

```bash
cd web
corepack enable
pnpm install
```

## Development loop

- Plan the change.
- Implement the smallest coherent slice.
- Validate locally:

```bash
python scripts/harness.py lint
python scripts/harness.py typecheck
python scripts/harness.py test
```

- Update docs if behavior or contracts changed.

## Pull request expectations

Use the PR template (`.github/pull_request_template.md`). A PR should include:

- intent (“what” and “why”)
- risks and rollout notes if relevant
- validation evidence (commands run, results)
- follow-up tasks if debt was introduced

## Decision records (ADR)

Use `docs/DECISIONS/ADR_TEMPLATE.md` for significant changes.

## Agent contributions

Agents should:

- start from `AGENTS.md`
- work in small diffs
- run the harness before final output
- summarize changes using `agents/checklists/CHANGE_SUMMARY.md`
- escalate if intent or contracts are unclear
