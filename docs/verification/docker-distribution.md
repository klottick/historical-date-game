# Prebuilt Docker distribution verification

## Scope and approval boundary

Implementation is local on a clean branch descended from public `main`
`76ba4c3d740237af99bc8db7fb9b1e4f5d25e40a`, not from private feature history.
Only Linux amd64 containers are supported and tested; no ARM image, privileged
emulation setup or multi-platform index is involved.

**Not yet verified:** actual hosted PR/release workflows, GHCR publication,
anonymous public package access, and downloaded *published* release installation.
Push, merge, tag/release creation and any package-visibility change each require
separate approval. No live application deployment or retained database migration
is part of this implementation. Local preview images are not released images.

## Local evidence

The public-base isolated backend baseline passed **1,574 tests**, 92% coverage.
Frontend baseline lint, typecheck, 86 unit tests and build passed; controlled
bootstrap 23 and identity 34 browser tests passed. The original full controlled
board baseline had **one focus-visible failure** in
`tab_reveals_long_sequence_cards_without_native_scroll_or_pointer_drift` (66
passed, one skipped). Its later isolated diagnostic passed without code changes;
that does not erase the baseline failure or count as an acceptance retry.

Before final whole-change verification, the distribution suite passed **57
checks**, including actual native image/context probes, actual validator CLI and
local HTTP-registry publication protocol tests. Full local smoke passed on both
normal Docker loopback publication and an offline internal network with no app
default egress route. Desktop and mobile compiled-browser checks ran with zero
retries. These smokes cover:

- Non-root native imports, frozen runtime dependencies, packaged 1,276-event
  catalogue and immutable media hashes; safe SPA/API/media boundaries.
- Daily/Freeplay scoring, three lives, owner-bound reads and exact move replay;
  original account login, guest/admin separation, credits/sources and media.
- Configuration/catalogue/storage refusal; read-only readiness failures and
  recovery for missing media or unavailable PostgreSQL.
- Populated legacy migration refusal with every database table hash unchanged.
- App/database replacement preserving all row hashes and old immutable media.
- PostgreSQL dump, complete historical media and private environment recovery
  into fresh volumes, preserved credentials/guest sessions/replay, and refusal
  of a populated restore destination.
- Bounded clean app/database shutdown, first-failure evidence and strictly
  ownership-checked cleanup; no unrelated Docker pruning or service restart.

Final verification results and the independent review are recorded below when
completed. Earlier source-free preview runs used only installer files in the
installation directory; they are not evidence of downloaded GitHub assets.

## Reproducing local checks

Use the repository's locked development tools on fresh owned resources:

```sh
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s scripts/distribution/tests -v
backend/.venv/bin/python scripts/test_workflow_contracts.py
```

Build exactly once natively, then supply the resulting local image to
`scripts/distribution/smoke.py --image REF --platform linux/amd64 --browser
--evidence-dir NEW_PRIVATE_DIRECTORY`, and separately with `--offline`.
`HDG_CONTEXT_AUDIT=1 HDG_TEST_IMAGE=REF` enables actual build-context/image probes
in the distribution suite. Do not substitute a retained development/test database
for the isolated full backend fixture; follow its exact endpoint/ownership guards.

The smoke extracts and executes the marked backup/restore shell blocks from the
shipped `INSTALL.md`, not a second undocumented procedure. Only fixture ownership
labels, private origin/credentials and offline networking are rendered into a
temporary Compose file. The documented commands themselves run unchanged; private
backups are never uploaded as evidence.

Registry protocol tests use a task-owned local HTTP server and a synthetic Docker
executable. They prove exact manifest-byte promotion, failure propagation and
stale/partial retry refusal, **not GHCR compatibility or anonymous visibility**.

## Remote acceptance after approvals

1. Inspect actual read-only PR CI before merge, including first-failure artifacts.
2. After a separately approved canonical stable tag/release, inspect release job
   logs and same-run image/archive/config identity and publication journal.
3. Run the anonymous acceptance command documented in `INSTALL.md` with an empty
   private Docker credential directory; verify version/full-SHA/latest digests and
   actual Linux amd64 config match the recorded tested image.
4. Verify all five downloaded assets/checksums in an empty installation directory,
   then exercise gameplay, account login, replacement, documented backup/restore
   and graceful shutdown using those downloaded files and pulled image.
5. Report exact source/version/digest and every unmet gate. Public source does
   not establish anonymous GHCR access; ask before changing visibility.

An asset-only retry never republishes or rewrites aliases, even after a newer
release exists. All other partial-publication repair is an explicitly reviewed
operator action; see the shipped guide. Docker does not confer TLS, new
authentication, rate limiting, public-hosting hardening or independent auditing.
