# Summary

Describe **what** changed and **why**. Link to relevant ADRs / issues if applicable.

## Validation

- [ ] `make lint`
- [ ] `make typecheck`
- [ ] `make test`

If you touched the UI:

- [ ] `cd web && pnpm lint`
- [ ] `cd web && pnpm typecheck`
- [ ] `cd web && pnpm build`

If you touched Terraform:

- [ ] `make tf-check`

## Risk / rollout notes

- Risks:
- Rollback plan:
- Follow-ups:
