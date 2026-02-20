# AGENTS.md

## Start here

1. **Validation:** read `harness.toml` to see how to validate changes.
2. **Durable source of truth:**
   - `docs/DOMAIN.md` (what we’re building and why)
   - `docs/DESIGN.md` (architecture and dependency rules)
   - `docs/CONTRACTS.md` (interfaces, invariants, compatibility)
3. **Execution loop:** `docs/WORKFLOW.md`
4. **Use task templates:** `agents/tasks/` (FEATURE / BUGFIX / REFACTOR / DOCS)

## Non‑negotiables

- **Repo-first:** don’t invent architecture or rules that aren’t encoded in the repo.
- **Protect invariants:** domain invariants live in `docs/DOMAIN.md`.
- **Respect boundaries:** dependency rules live in `docs/DESIGN.md`.
- **Protect contracts:** public interfaces and compatibility rules live in `docs/CONTRACTS.md`.
- **Always validate:** run the harness tasks relevant to your change.

## Primary validation commands

```bash
python scripts/harness.py lint
python scripts/harness.py typecheck
python scripts/harness.py test
```

## When to escalate to a human

- Requirements are ambiguous in a way that affects contracts/boundaries.
- A change breaks an invariant or requires a significant tradeoff.
- There’s a security or secrets concern.
- Harness gates can’t be made green without skipping meaningful checks.

## Output format (final response)

Use `agents/checklists/CHANGE_SUMMARY.md`:

- what changed
- why it changed
- how it was validated
- risks / rollout notes
- follow-ups / debt introduced
