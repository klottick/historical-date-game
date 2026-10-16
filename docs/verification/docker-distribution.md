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

### Final local checkpoint

At source commit `098c9b1a4a63c091913ad4adc0a99b8d74e13ff0`:

| Gate | Observed result |
| --- | --- |
| Fresh full isolated backend | 1,574 passed at `ddbf1e4` (identical backend tree at this checkpoint); legacy pytest collector coverage 89% (release checks run separately) |
| Distribution checks with actual context/image probes | 58 passed |
| Backend mypy/Ruff/format | Passed, 76 application files |
| Frontend lint/typecheck/unit/build | Passed, 86 unit tests |
| Workflow contracts/actionlint | Passed |
| Controlled bootstrap/identity browsers | 23 / 34 passed, zero retries |
| Controlled board full suite | **Failed:** 66 passed, one skipped, one failed in the same baseline navigation test; final failure is geometry delta exactly 0.5 versus `< 0.5` at line 498 |
| Compiled image desktop/mobile browsers | Passed in both normal loopback and offline source-free installations, zero retries |
| Documented backup/restore, replacement and shutdown | Passed in both final image smokes; populated-target restore refused |
| Packaged catalogue/media/licence preservation | All 36 paths match public base exactly |
| Saved image privacy audit | 12 layers, 9,686 files; injected private-data sentinels absent |

The final preview image ID is
`sha256:54d236eb204758415e9c4e0d3e1f681a90c051235420d398d5b2d0eda65aa214`
(100,458,561 bytes). This is a local Docker image ID, **not a published registry
manifest digest**. It was built once from a task-owned source archive with nested
synthetic secret/raw/private-worktree files; the saved layers were then audited.
Normal and offline full image smokes used this same image and the exact shipped
backup/restore command blocks. Private evidence and first failures remain in the
ignored execution workspace; the protected `.env` hash and LAN process identities
were checked unchanged.

**The overall all-green gate remains blocked by the pre-existing controlled-board
failure.** No retries or unrelated board/tolerance changes were made. A source
fixture browser attempt also encountered the existing Vite denial of a scratch
checkout under `.superpowers` (setup failed, 112 tests not run). A fresh run outside
that tree had 101 passed/12 failed because the launcher expected internal-IP URLs
while the browser correctly used the same-origin proxy. Trace inspection confirmed
the mismatch. Correcting only that launcher origin produced **113 passed, zero
retries**, with fresh owned DB/API/mail fixtures; all prior failures are retained.
A separate scratch-directory cleanup failure came from root-owned Python cache
files, not retained data. Test containers/network were removed after label checks;
the source copy remains private, without an ownership workaround.

A separate instrumented diagnostic copied the unchanged board/app and original
assertions to an owned source directory, adding only focus/layout logging. It
passed 67 tests with one skipped; this is **not an acceptance retry**. Measurements
showed an initial card's CSS `left` still transitioning (for example, rendered
243.913px versus target 243.188px) during keyboard focus. The existing 180ms `left`
transition can therefore outlast initial measured layout publication while the
test compares against the final target immediately. This supports a timing cause
for the geometry assertion; it does not reproduce/explain the original baseline
focus-visible failure or prove either issue fixed. No board/test changes were
made in the actual branch.

The independent whole-change review found five Important issues and no Critical
or Minor issues: nested artifact/body credential exposure, complete-member-boundary
truncated media acceptance, recovery project continuity, registry `latest` rollback
after release metadata changes, and missing frontend asset readiness. Each received
an observed failing behavioral regression before its fix. The repair pass:

- Recursively sanitizes nested diagnostics and drops body/image resources and
  arbitrary serialized values; raw copies stay private. Uploaded diagnostics are
  metadata-only, not viewer-complete blobs/merged HTML reports. Hosted runner-local
  originals are ephemeral, not durable private storage.
- Requires a terminal complete path/size/hash media inventory before promotion.
- Persists the validated recovery project name in private `.env`; the smoke also
  runs the later maintenance commands without `-p` and does not bake resource
  project names into its fixture.
- Independently verifies current registry `latest` config/version/immutable aliases,
  rejecting backward/equal promotion or changed state even if GitHub history was
  edited. Registry writes still are not atomic; external concurrent mutation is
  not a supported substitute for serialized publication.
- Emits Vite's build manifest and checks the entry plus all static/dynamic assets
  at app creation and on readiness, refusing missing index/JS/CSS/lazy chunks.

### Revised-image verification after the fix pass

Runtime/build source commit: `99ca1c66b35bff6737f731b75eb05837e83ae8a3`.
The revised preview image is
`sha256:55796e369f5369f28163d6041a63e9982f6f558af6d5bd5506fb59a3cb717a47`
(100,460,597 bytes). It was built once natively, then reused for the complete
normal-loopback and offline-browser smoke runs, including the new inventory-based
media restore and subsequent documented maintenance with the persisted project.
Both runs passed all checks, with no cleanup failures. The complete distribution
suite passed **66/66, no skips**, with actual context/image probes, including gates
on every browser/service diagnostic upload when sanitization fails. An additional
real retained Playwright trace nested inside an archive passed resource-redaction
checks (74 members); the original remained untouched. The redaction regression
also covers extra serialized fields beside sensitive `name`/`value` pairs.

The revised saved-image audit covered 12 layers/9,688 files with no injected
private sentinel. Backend mypy/Ruff/format, frontend lint/typecheck/86 unit tests/
build, workflow contracts and actionlint passed again. The fresh full isolated
backend run against runtime source `99ca1c6` passed **1,574 tests in 624.10s**,
89% legacy pytest coverage; release modules are exercised by the separate
distribution/image checks. All three newly owned test containers were removed.
The backend tree is unchanged through tooling checkpoint `f33d108`.

The scratch backend launcher's original result JSON captured the outer branch's
HEAD at completion, not its isolated source checkout. Both original results are
preserved with explicit provenance-correction records; actual checkout HEADs and
unchanged backend trees were verified rather than attributing tests to an untested
revision. This affects provenance bookkeeping, not the observed test results.

No second independent review
was substituted for regressions: the five findings were fixed and tested by the
implementer in one repair pass. No review approval or all-green claim is inferred.

Local packaging checks and the review repair pass are recorded; Task 7 remains
blocked at the overall board gate and approval-gated external steps. The branch
and private evidence remain in place. No push/merge/tag/release/visibility change
or live service deployment has been performed.

The prior preview ID above does not contain these fixes. Earlier source-free preview runs
used only installer files in the installation directory; they are not evidence of
downloaded GitHub assets.

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
