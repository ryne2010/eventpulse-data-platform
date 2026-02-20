# Style

This repo aims to be readable, boring, and mechanically checkable.

## Python

- Formatting: `ruff format`
- Lint: `ruff check`
- Typecheck: `pyright` (preferred) and `mypy` (also supported)
- Tests: `pytest`

Conventions:

- Prefer small functions with clear names.
- Validate inputs at boundaries (API, loaders).
- Use explicit types for public function signatures.
- Avoid hidden global state.

## Terraform

- Always run `terraform fmt -recursive` (enforced via pre-commit).
- Keep modules small and readable.
- Prefer explicit IAM bindings and include rationale in comments.

## Docs

When changing behavior:

- Update `docs/DOMAIN.md` if “what/why” changes.
- Update `docs/CONTRACTS.md` if an interface/invariant changes.
- Add an ADR under `docs/DECISIONS/` for significant decisions.
