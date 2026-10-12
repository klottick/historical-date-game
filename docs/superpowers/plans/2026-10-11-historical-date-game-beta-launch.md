# Historical Date Game Beta Launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy a recoverable friends-only beta, prove release gates, and gather one week of feedback before widening access.

**Architecture:** One small Linux host runs the existing app/database/proxy containers with HTTPS and persistent PostgreSQL plus retained catalog/media storage. Daily off-host backups and a tested restore protect scored progress and immutable content. No new application services are required.

**Tech Stack:** Existing Docker Compose/Traefik/PostgreSQL, shell scripts, cron or systemd timer, app health checks/sanitized error capture, existing CI.

**Spec:** `docs/superpowers/specs/2026-10-11-historical-date-game-beta-design.md`, sections 8-10. Read the [master plan](2026-10-11-historical-date-game-beta.md) first.

## Global Constraints

All master constraints/contracts apply. Friends only; public registration disabled, private test endpoints local-only, HTTPS and nondefault secrets mandatory. Keep **at least seven retained daily restore points**, all referenced catalog/media/rights artifacts, and verify restore before inviting players. Provisioning/cost requires owner approval.

## Review Focus

Master focus 5 belongs to L2: a deployment/restart/restore must preserve active runs, frozen Daily identity, media/credits, and resume. Production overlays must remove existing published DB/admin/proxy-management exposure rather than merely document it.

---

## Task L1: approved hosting and production-safe operations

**Files:** Create `docs/research/beta-hosting.md`, `docker-compose.beta.yml`, `docker-compose.traefik.beta.yml`, `scripts/{backup-beta,restore-beta}.sh`, `docs/operations/beta-runbook.md`, `backend/tests/game/test_deployment_config.py`; update `deployment.md`, applicable CI Compose checks. Do not commit production `.env`/secrets.

**Interfaces:** `backup-beta.sh <compose-project> <backup-directory>` creates a timestamped consistent DB dump plus catalog/media/rights snapshot, inventory/digests and image/schema versions; `restore-beta.sh <archive-directory> <explicit-new-project>` refuses the production project and restores into a separate target. Runbook supplies production command/env locations, release/rollback versions and ownership. Compose overlays use persistent game-data bind/volume mounted read-only into backend, and DB uses existing PostgreSQL 18 volume layout.

- [ ] Compare at least two suitable host options/current prices including storage, backups, bandwidth/media, domain, operational work and expected monthly cost. Recommend one host sized initially around 2 vCPU/4GB RAM with persistent SSD and off-host encrypted backups, subject to measured image/database size. Obtain owner approval of provider/budget/domain, restore storage location, and feedback contact before provisioning. Source/image acquisition costs from C1 also belong in the budget.
- [ ] Write deployment-config regression tests asserting rendered production Compose has no DB published ports, Adminer/private endpoint exposure, proxy dashboard routers/API management exposure, Mailcatcher, dev bind mounts, or test runners. Assert `PUBLIC_REGISTRATION_ENABLED=false`, production environment, explicit nonempty secrets/origins, retained game data, and container DB port 5432. Run `uv run pytest tests/game/test_deployment_config.py -q`; expect unsafe-base-config failure before overlays exist. This pure test uses B1's no-op fixture.
- [ ] Implement production overlays using stable Docker Compose with version >=2.24.4 for `!override`; use `ports: !reset []` to clear inherited DB bindings and `labels: !override` to replace dashboard/admin routing rather than merge it. Disable Adminer via explicit profile and routing, remove Traefik dashboard/API routes and command flags while preserving HTTPS redirect middleware. Use `docker compose -f docker-compose.yml -f docker-compose.beta.yml ...`, never implicit development override; use the explicit Traefik files/overlay separately. Mount game assets for serving but keep source/release artifacts private. Set backend/prestart `POSTGRES_PORT=5432`; do not inherit host test port 5433.
- [ ] Implement backup/restore scripts with `set -euo pipefail`, no tracing/secrets in output, required explicit project names, safe paths, recorded checksums, permissions, encrypted off-host copy and failure alert. At backup, suspend catalog activation/media publication until artifact inventory and DB snapshot complete; immutable scoring transactions remain snapshot-safe. Retain at least seven successful daily points, verify transfer before pruning, and retain every release/media referenced by an existing run. Never run broad volume deletion or overwrite production during restore.
- [ ] Write runbook covering TLS/DNS, restricted account enrollment/display names, real-email reset or documented admin recovery, secrets/origin checks, private route exclusion, `VITE_FEEDBACK_EMAIL`, sanitized logs/error reporting, health checks, migration/activation, daily backup scheduling, deploy and versioned rollback. Rollback app images only when schema compatible; restore to separate target for destructive recovery decisions. All media download/preparation stays offline, outside scoring transactions.
- [ ] Run deployment tests and `docker compose -f docker-compose.yml -f docker-compose.beta.yml config --quiet`, plus corresponding Traefik render check using a synthetic production env. Inspect actual exposure/settings, not just YAML text. Record approvals/render evidence and commit ops files: `git commit -m "ops: prepare restricted recoverable beta deployment"`.

## Task L2: verify and release the complete beta

**Files:** Create `scripts/verify-beta.sh`, `backend/tests/game/test_release_check.py`, `docs/beta/release-checklist.md`, `docs/beta/restore-drill.md`; update `docs/operations/beta-runbook.md` with measured deployment details and `.github/workflows/{test-backend,playwright,test-docker-compose}.yml` to seed fixture catalogs/run all checks where needed. F0 already establishes `_test` database settings.

**Interfaces:** `verify-beta.sh <release-dir> <media-dir>` fails on fixture releases, fewer than 1,000 accepted events, missing integrity/rights/media, or failed automated checks. It uses the separate approved test backend/database for integration/browser checks, never cleans production. Evidence records code/image versions, schema, active catalog ID, Daily categories, test output, source/media reviews and manual signoff.

- [ ] Write `test_release_check_rejects_fixture_shortfall_and_tampering` in `test_release_check.py` using synthetic C5 inputs and mocked command runners; assert nonzero exit for fixture/999-event/tampered artifacts and propagation of any failed verification command. Run `uv run pytest tests/game/test_release_check.py -q`; expect missing-script failure, then implement script orchestration and rerun green. A legitimate >=1,000-event artifact plus all green tests returns exit 0. Do not synthesize large fake fixtures to claim real content readiness.
- [ ] Run backend unit/integration tests, existing and new browser/unit tests, lint/typechecks/builds, client regeneration twice, pre-commit, and Compose/container checks in the test environment. Verify CI's database names satisfy F0 guard and CI includes content/media/rule/concurrency checks. Save actual output/counts; no reuse of modernization-only evidence as proof of gameplay.
- [ ] Activate C6's real non-fixture catalog on the owner-approved host; deploy tagged backend/frontend images with production overlays and HTTPS. Use B2 CLI to validate/activate with `--require-beta`; check secrets/origins/private routes and that direct manifest paths are inaccessible. Create real restricted beta accounts via admin; do not open public signup to simplify tests.
- [ ] Create an active Daily and Freeplay, make a scored move, back up, restart/redeploy, and verify identical run revision/timeline/pending card and frozen Daily definition. Restore that backup into an isolated target with matching catalog/media/rights inventory; verify same progress/card/credits, complete the restored run, and record restore duration/digests. Never expose copied production accounts in a public test restore or run test-cleanup against it.
- [ ] Complete the release-checklist: documented approved sources, >=1,000 accepted identities, broad coverage review, picture/fallback evidence, both wins/losses, Daily fairness/one attempt/ties, 100-card manual desktop/touch play, all required accessibility and failure recovery checks, HTTPS/backup restore/health, and owner unassisted play. Resolve known scoring/fairness/answer-exposure/progress-loss defects before invitation.
- [ ] Obtain owner go/no-go and record invitation/feedback instructions. Commit release script and redacted evidence: `git commit -m "docs: verify friends-beta release and recovery gates"`. No automatic merge/push beyond separately approved integration instructions.

## Task L3: one-week friends trial and bounded follow-up

**Files:** Create `docs/beta/{friends-trial,feedback-triage}.md`; update readiness/runbook only as needed.

**Interfaces:** Trial notes contain anonymized player labels, dates, event/run IDs for reports, severity, reproducible problem, disposition, and explicit next-step recommendations. Do not record credentials or unnecessary personal data.

- [ ] Invite approved friends only after L2 passes. Explain one Daily attempt/UTC reset, unlimited Freeplay categories/range/gap, confirmation controls, resume, and how to report confusing events or progress issues. Run the trial for one week and seek feedback from at least three players.
- [ ] Collect recognisability, ambiguity, spacing usefulness, picture relevance, tactile/touch/keyboard friction, and voluntary Freeplay replay/Daily return feedback. Track it as learning evidence, not a guaranteed retention rate or launch date.
- [ ] Triage scoring/fairness/progress-loss/security issues as widening-access blockers; reproduce and regression-test fixes via the owning task/skills. Correct content through a new immutable release, never change existing Daily/run answers or reset attempts. Review difficult wording/coverage before adding new modes.
- [ ] Review findings with the owner and choose remain friends-only, iterate, or separately plan wider launch. Commit only sanitized trial/triage notes: `git commit -m "docs: summarize friends-beta learning and follow-up"`.
