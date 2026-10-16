# Clean Main Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the reviewed game/catalogue snapshot to remote `main` with portable tests and meaningful CI, excluding private feature history.

**Architecture:** Keep live application/rollout guards unchanged; move test dependencies into disposable synthetic fixtures and explicit CI preparation. Assemble a single-parent publication commit from the final public tree, never merge or push the feature branch. Verify the candidate in a fresh clone before a normal fast-forward push.

**Tech Stack:** Git/GitHub Actions, Python/pytest/uv, PostgreSQL/Docker, Node/Playwright.

**Spec:** User-approved in-chat publication scope: fix clean-clone CI and stale `master` filters; prepare a clean public snapshot; verify, push `main`, inspect actual CI. Existing game/catalogue specs remain unchanged.

## Global Constraints

- Preserve live LAN API/UI, retained databases, accounts, gameplay, source/media, `.env`, original reset/provenance evidence and all worktrees. Never repeat the gameplay reset or signal live processes.
- Preserve primary checkout's 83 staged publication paths until an identical reviewed publication replaces them deliberately. No hard reset, forced checkout, force push, tag/feature-history push, release or deployment.
- Historical reports deleted from the final tree still exist in unpublished feature history: that history MUST NOT become an ancestor of remote `main`.
- No skipped test failures, weakened ownership/path/provenance guards, fabricated original receipts, or private dataset dependency in public CI.
- All DB verification uses newly created task-owned isolated PostgreSQL resources, not retained databases or live Compose services. No broad Compose teardown/prune on this host.
- Publication must not trigger staging deployment: make that workflow explicit manual dispatch. Production remains release-only and no release is created.
- The user requested continuous execution; do not pause for another plan confirmation.

## Review Focus

1. An empty Linux runner has no `/tmp/opencode` or retained checkout: regression fixtures must initialize their own scratch/files.
2. Wrong profile/database/foreign owner: preparation and tests must refuse before mutation, using existing finite ownership guards.
3. Migration/reset tests share a secondary database: seed synthetic baseline, serialize use and preserve scoped cleanup.
4. Squash removes original developer commits: recovery tests must use real disposable Git histories, not missing production-history objects.
5. Main push could start deployment or expose deleted reports: test workflow triggers and inspect outgoing commit ancestry/tree before push.

---

### Task 1: Portable backend test fixtures and preparation

**Files:** Modify `backend/tests/browser/test_three_lives_local_rollout.py`, `test_three_lives_migration.py` as required; create `backend/tests/browser/ci_backend.py` and narrowly scoped test support/regressions under `backend/tests/`. Do not change application code or real rollout helpers.

**Interfaces:** `python -m tests.browser.ci_backend prepare` requires `HDG_VERIFICATION_PROFILE=lives`, `POSTGRES_DB=historical_date_game_lives_backend_test`, loopback port `5433`, local environment. It prepares/owns that target and `historical_date_game_lives_migration_test`, migrates and seeds a synthetic selected catalogue on the latter for migration/recovery/reset proofs. No private real-catalogue seed or startup/reset helper is invoked.

- [x] Reproduce missing temporary root, profile mismatch and retained-source dependency in an exported checkout/isolated PostgreSQL; record named red tests.
- [x] Write regression tests for preparation refusing unsafe settings/ownership, portable scratch/source/sidecar fixtures and real recovery-Git provenance checks.
- [x] Implement minimal fixture/preparation changes; preserve existing negative guard/tampering assertions and production helper bytes.
- [x] Run the entire backend suite from a clean clone with actual Git metadata, no retained source/worktree/.env and newly owned disposable databases/Mailcatcher. No deselection, skip or weakened acceptance gate for the affected tests. Report any unrelated failures by name.
- [x] Commit only task test/support paths; keep detailed evidence ignored.

### Task 2: Workflow/default-branch compatibility without deployment

**Files:** Modify `.github/workflows/{test-backend,lint-backend,playwright,test-docker-compose,latest-changes,deploy-staging}.yml`; targeted branch documentation in `deployment.md`; add pure workflow-contract regressions in `scripts/test_workflow_contracts.py` (runs without the backend database fixture).

**Interfaces:** Backend workflow consumes Task 1 CLI and exact lives-profile/target variables. Other tests retain their existing scoped fixture profiles. Staging consumes `workflow_dispatch` only.

- [x] Add and run red checks for `main` push/PR filters, no automatic staging/production push deployment, backend preparation/profile and always-run cleanup of CI-owned Compose project.
- [x] Update five test/automation branch filters to `main`, staging to manual dispatch, wire backend preparation and isolated project name with real migration/seed ordering; ensure failure cleanup uses `if: always()` and finite CI project resources.
- [x] Validate workflow syntax/contracts and full backend lint/typecheck. Do not recreate live Compose stack; use separate task-owned project or containers for local verification.
- [x] Commit workflow/test/documentation paths. The lint gate exposed three previously unformatted current catalogue source files: apply whitespace-only fixes, prove AST equality, and rerun fresh generation. Immutable catalogue assets, historical locks and recipe pins remain unchanged.

### Task 3: Clean publication tree, fresh-clone verification and review

**Files:** Final tracked public tree; task-owned publication checkout/clone and ignored audit reports. Existing immutable catalogue and `.env` bytes are preserved.

**Interfaces:** Publication parent is the freshly fetched `origin/main`; tree is reviewed final feature tree excluding any private evidence and existing uncommitted `.env`. Candidate has exactly one new commit on that parent, no feature-history ancestors.

- [ ] Fetch origin; capture primary index, feature `.env` hash and LAN process identities. Reconcile any remote/new user changes non-destructively.
- [ ] Assemble candidate in a separate clean publication checkout without changing primary staged work or live worktree. Audit all outgoing paths and sensitive token patterns; verify private reports are absent from tree and ancestry. Do not publish local tags.
- [ ] Clone the candidate into new empty scratch and run backend tests, frontend lint/typecheck/unit/build and appropriate controlled/fixture browser/Compose tests on isolated resources. Verify packaged runtime with content network denied. Record actual outcomes and limitations; fix material failures before push.
- [ ] Request independent review of test/workflow fixes and publication ancestry/privacy evidence; fix Important/Critical findings and rerun affected checks.

### Task 4: Publish and verify

**Files:** Remote `refs/heads/main`; primary checkout tracking. No release, deployment or worktree deletion.

- [ ] Recheck remote main is the verified parent and candidate tree matches reviewed files; normal fast-forward push only `HEAD:refs/heads/main`.
- [ ] Verify remote SHA/tree, GitHub default branch, outgoing ancestry and actual workflow runs. Inspect failures rather than claiming earlier local tests prove CI green.
- [ ] Integrate reviewed clean commit into primary `main` without discarding staged/user work: first verify that all staged paths match candidate, then use a safe index/branch update only if no conflicting work exists. Keep all worktrees, dirty `.env` and evidence intact.
- [ ] Report published SHA, actual CI outcomes, any external service/action limitations, and unchanged live services. No production deployment or release claim.

## Execution record

Detailed diagnostics and step results remain in ignored task evidence; only generic plan/test/workflow/documentation and reviewed application/catalogue files belong in the publication tree. Full app/catalogue behavior was already reviewed; new reviews focus on portability, integration and safe publication rather than replaying private feature history.
