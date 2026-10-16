# Portable catalogue and reproducible builds

**Status:** Implemented locally. Requirement amended by the user: a clean public
source → new valid dataset path is required; exact historical recreation is
optional. Legacy source files stay on Mustafar. The original exact-replay design
below is historical where it conflicts with this amendment; its public-archive
acceptance gate no longer blocks completion. See
[current operations](../../operations/catalogue.md) for the fresh workflow.

## 1. Agreed intent and scope

A person cloning this repository should receive the final catalogue used by the
application, including its required assets and attribution. Running the game must
not require source downloads, the content pipeline, an author's private checkout,
or a pre-existing catalogue database.

The same repository must contain the code and instructions to reacquire the
source inputs and transform them into that catalogue. Raw downloads, acquisition
caches, intermediate artifacts, private reports, credentials and database dumps
remain outside Git. Rebuilding is a separate, explicit maintainer operation, not
part of application startup.

Success means proving two different workflows from a clean checkout:

1. **Run:** verify and install the committed catalogue without content-network
   access, then serve playable Daily and Freeplay with attribution and media.
2. **Rebuild:** fetch the locked source inputs, run the documented transformation
   and full validation, and reproduce the committed runtime payload exactly.

This design does not expand the catalogue, replace historical facts, change game
rules, relax content acceptance, introduce a manual curation queue, reset existing
games, or authorize publication or deployment. Production secrets, HTTPS and
registration configuration remain operator responsibilities.

## 2. Observed constraints

- The selected catalogue has 1,276 events: 1,271 chronology events and five birth
  supplements. Its existing `events.jsonl` is 2,157,207 bytes. Eight original CC0
  fallback SVGs total 5,431 bytes; there are no photographs.
- The complete private release is 44,814,244 bytes, including raw inputs,
  candidates, source evidence, decisions and receipts. Those are not runtime
  dependencies merely because the current format packages them together.
- `app.content.publish.verify_release` independently recomputes acceptance from
  those raw artifacts. `activate_catalog` invokes that verifier on every import.
  Deleting raw files or teaching that verifier to ignore their absence is unsafe.
- Catalogue release IDs are immutable. Reusing an ID with different manifest
  bytes fails; existing runs and Daily definitions retain their release IDs.
- `EventRecord`, category and media snapshots already provide the application's
  runtime inputs. Source citations also carry acquisition/provenance fields.
- The chronology dataset has a fixed upstream Git commit and file SHA-256s.
  Some original supplement responses lack complete upstream revision pins; the
  current cached bytes cannot be presumed reproducible from today's APIs.
- Import and verification use wall-clock dates, while receipts and some source
  metadata include acquisition times. Source pinning alone is not determinism.
- The backend Docker build context is `backend/`. Media serving accepts only
  release-qualified, digest-named SVG/WebP files, with no symlink aliases.

These observations are constraints, not a claim that a clean rebuild has passed.

## 3. Alternatives and recommendation

| Approach | Assessment |
| --- | --- |
| Commit the complete private release | Rejected: includes raw/intermediate material and couples deployment to the build audit. |
| Commit only events and bypass the existing verifier | Rejected: loses integrity, licence/media checks and a safe activation boundary. |
| Add an explicit runtime bundle, exported from a fully verified build | **Recommended:** small offline deployment artifact; full source validation remains a separate, stronger operation. |

Keep both formats explicit. A runtime bundle is not accepted as a full audit
release. Missing raw evidence must never make a full verification silently fall
back to runtime verification.

## 4. Artifact layout and ownership

Use `backend/catalogue/`, rather than the repository root, so the existing
backend-only Docker context can include it without admitting raw data, root
environment files or private worktrees into a larger build context.

```text
backend/catalogue/
  README.md
  default.json
  releases/<runtime-release-id>/
    runtime-manifest.json
    events.jsonl
    taxonomy.json
    media.json
    source-selection.json
    attribution.json
    build.lock.json
    LICENSE.catalog.txt
    NOTICE.catalog.md
  media/<runtime-release-id>/<sha256>.svg

data/catalogue-build/                 # ignored; outside backend build context
  sources/<input-digest>/
  workspaces/<build-id>/
  audit-releases/<build-release-id>/
  reports/<run-id>/
```

Only allowlisted final records, necessary public provenance, licence notices,
build recipes and referenced runtime assets enter the committed tree. Do not
copy `sources.json`, `raw.jsonl`, candidates, validation logs, HTTP headers,
local filesystem paths, cookies, guest/account rows or database exports into it.
Do not mutate or delete existing ignored source/audit directories during adoption.

`default.json` identifies an exact runtime release and its manifest SHA-256. It
is a reviewed Git change, not a mutable `latest` network reference. Old runtime
releases and their assets remain available while referenced by retained games.

## 5. Runtime contract and verifier

Introduce a distinct, strict `RuntimeCatalogManifest` with:

- `kind = "runtime-catalogue"` and `schema_version = 1`;
- a single-component runtime release ID, fixed release timestamp, fixture flag
  and event count;
- SHA-256s of every required release file, including the build lock, attribution
  and licence files; a separate digest map for this release's public media;
- the locked origin audit-release identity/digest and a deterministic runtime
  content digest over the sorted payload-file/media digest maps. These are
  provenance references, not embedded raw evidence.

The manifest does not hash itself. `default.json` supplies its external digest.
Strict JSON parsing rejects duplicate keys, unknown fields and non-finite values.
Paths remain canonical relative paths; verifier-controlled roots define release
files and `media/<runtime-release-id>/`, never arbitrary cross-root paths.

Retain the existing typed event, category and media records initially. Do not
introduce a second event DTO merely to remove small provenance fields. Export
must explicitly review those fields for public suitability, retaining meaningful
source IDs, citations and rights information without local-only evidence paths.
Preserve all existing event UUIDs, prompts, answers, explanations and category
assignments when packaging the first release.

The offline runtime verifier must check:

1. Exact supported format, release identity, complete file set, reference closure,
   file sizes and hashes; reject unexpected, missing or nonregular files.
2. No symlinks, path traversal, aliases/hard-linked artifacts or assets outside
   their release's qualified media directory. Read and validate bounded bytes
   consistently so activation does not reopen an unchecked changed payload.
3. Strict existing record schemas; nonempty unique event UUIDs and identity keys;
   all category/media/fallback references; required approval/date-precision shape;
   year and text safety, source URL and credit requirements.
4. Actual media hashes and supported file types, required fallback coverage,
   per-asset rights metadata, catalogue text attribution and licence notices.
5. Recomputed counts/coverage, source selection and Daily-category compatibility;
   the existing nonfixture minimum when requested. Never trust supplied counts.

Its result is a validated immutable snapshot suitable for installation. It does
**not** independently prove historical truth, upstream copyright ownership, raw
source eligibility or the integrity of an entire maliciously replaced bundle.
The reviewed Git commit/default digest is the distribution trust anchor. Full
raw-source acceptance remains the responsibility of build verification.

No download, source cache lookup, database connection or content rebuild is
allowed during runtime verification.

## 6. Export and immutable identity

Add an exporter that takes a fully verified audit release and produces a
create-only runtime bundle. It calls full build verification before exporting;
its input cannot be an unverified directory of apparently approved events.
The exporter enforces the final-file allowlist and writes atomically through a
private temporary directory. An existing destination ID is never overwritten.

The first runtime release gets a **new ID**, for example
`chronology-1276-runtime-v1`. Its manifest references the origin release digest.
Reusing the old audit release ID with a new runtime manifest is prohibited.

The first export must demonstrate parity with the catalogue currently used by
the app: the same 1,276 UUIDs and all event fields, category and media records,
asset bytes and public citation/credit behaviour. Required differences are the
new release identity, runtime manifest and portable distribution notices.

If implementation changes build-rule fingerprints, create and fully verify a
new audit generation from checked source inputs. Compare its complete accepted
event content with the retained catalogue before exporting. Never suppress
`stale_media_rules`, forge old receipts or relabel an unchecked directory as a
verified historical release to bootstrap the new format.

## 7. Installation and startup

Keep database installation separate from source acquisition and from application
request handling. The content CLI gains explicitly named runtime operations,
such as `runtime-export`, `runtime-verify`, `runtime-install` and
`runtime-initialize`; final names belong in the implementation plan.

Both the existing audit installer and the new runtime installer should feed a
small shared transaction-safe snapshot installer after their respective verifiers
finish. Preserve the advisory lock, exact immutable-manifest comparison and
transactional category/event/media/selection insertion. No weaker alternative
activation path may bypass the format-specific verifier.

Rules for `runtime-initialize`:

- After successful schema migration and account initialization, a fresh database
  with no selected catalogue may install and select the committed default.
- If that exact release is already selected, verify it and do nothing else.
- If a different catalogue is selected, do not switch it or replace its data.
  Report the existing selection and require an explicit operator command to
  install/select a replacement. No implicit startup catalogue upgrade.
- A conflicting existing release ID, corrupt bundle or failed transaction leaves
  the previous selection and rows unchanged and reports an actionable error.

Existing runs/Dailies remain bound to their old releases. Installation never
deletes gameplay, credentials, accounts, old catalogues or media. The separate
three-life migration's populated-gameplay refusal remains unchanged; this feature
does not authorize an upgrade reset or solve that migration by deleting data.

## 8. Docker, media and details

Copy `backend/catalogue/` into the backend image, outside any frontend/public web
root. Both prestart and backend use that same image/bundle. Copy only the checked
runtime tree; do not add acquisition archives or ignored workspaces to the image.

Fresh-install media defaults resolve to the packaged catalogue root so existing
`/media/<release-id>/<digest>.svg` URLs work immediately. Preserve explicit
external data-directory settings for existing installations. Public media is
read-only and uses real files, not symlink aliases. Request handlers do not copy,
download or regenerate assets.

For an installation with an explicit external media root, the explicit install
command provisions the new release's checked assets there create-only, before
selecting the release. It must not overwrite old assets or select a release whose
assets the backend cannot read. Prestart and backend must share that configured
root. On failure, harmless unselected new assets may remain, but old assets and
the database selection stay intact; no automatic media garbage collection occurs.

Only the qualified media subtree is HTTP-served. Test that catalogue manifests,
answers, build locks, raw data and attribution files cannot be fetched through
backend static routes, frontend development-server file routes or path traversal.
Catalogue publication in Git is deliberate; it is not a claim that players can
never obtain event answers from the public source repository. Pending DTOs still
must not disclose the selected answer or private run ordering.

For this first release, retain source-page fallback links derived from event
citations. There are no curated article enrichments to preserve. A private
event-links sidecar must not be required to self-host. Future article enrichment
would need its own validated, release-bound public artifact; it is not added here.

## 9. Reacquisition lock and source archive

`build.lock.json` is a nonsecret, versioned rebuild recipe. It identifies:

- acquisition/transform recipe versions and the relevant code/config/dependency
  digests, excluding generated catalogue/build-lock files from code fingerprints;
  Python/toolchain and locked dependency requirements;
- every exact source object: provider, immutable upstream locator where known,
  revision/commit ID, expected byte digest, size bound and source licence;
- source record/seed selection, original snapshot identity/timestamps, taxonomy,
  validation/source/Daily policy and media/fallback rules;
- the build evaluation date and all original source metadata required by the
  deterministic transform;
- the expected runtime release identity and digests of generated event, taxonomy,
  media, attribution, source-selection and licence payloads. The lock does not
  contain a digest of itself or of the manifest that hashes it; those are compared
  directly against the committed files after export.

The recipe must not embed the complete raw responses or accepted event rows as a
substitute for implementing acquisition and transformation. It must retain the
whole source-input scope used for duplicate/conflict/quarantine checks, not only
hand-picked passing rows.

Acquisition is an explicit command, with a project User-Agent, approved HTTPS
hosts, bounded sizes/timeouts, verified redirects, safe output paths and existing
throttle/stop rules. Cache hits must pass the same digest checks as downloads.
No unbounded retry, mutable `latest` fallback, login, paid service or secret is
required. A bad/missing source produces a structured failure before a build is
promoted or the committed catalogue is touched.

### Required treatment of legacy inputs

The five original birth supplements have incomplete upstream revision pinning.
Do not infer old revisions from current responses or silently substitute newer
facts. To support exact reconstruction of the existing catalogue, prepare a
**source-only archive outside Git**, distributed as a checksum-pinned release
asset after a public-content/privacy/licence audit. It contains only necessary
redistributable source inputs and source notices, not private operational proof.

The lock names each input digest and its acquisition route. Immutable upstream
objects are preferred; the source archive supplies exact historical inputs when
upstream cannot reproduce the original bytes. An explicitly supplied local
archive is also accepted only if its bytes match the lock. Downloads and archive
extraction must reject traversal, links, special files and expansion beyond
declared limits.

Archive hosting is not needed to run the app. Publishing an archive is a separate
external action, not authorized by approving this design alone. Until those bytes
are independently retrievable through a documented public route, the project
must not claim a clean-machine exact rebuild of all 1,276 events is supported.
Unavailable redistributable inputs block that claim; they do not justify removing
the five events or adding a compulsory manual curation process.

## 10. Deterministic transformation and comparison

Reuse the importer, adapters, classification, whole-input duplicate/conflict
checks, media policy and full publisher/verifier; do not create a second set of
normalization rules in a download script.

Introduce an explicit build context for eligibility/evaluation dates and stable
original snapshot metadata. Existing current-date safety remains the default for
new acquisitions. Locked replay deliberately uses the recipe's recorded context
and expected inputs; it is not an API option for changing scored Daily dates.

Distinguish original source observation timestamps from the current transport's
retrieval time. Do not record a fresh download as having occurred in the past.
Fresh transport receipts, durations, audit timestamps and local paths remain in
ignored run reports, not in deterministic runtime payloads. Original snapshot
timestamps needed to reproduce existing source citations are explicitly marked
as original observations in the locked recipe and provenance documentation.

Stable file ordering, JSON encoding, newline rules, event IDs, asset bytes and
release metadata must be specified by the exporter. The manifest timestamp is
locked release metadata, not the time each replay happens. Build/audit receipts
may contain fresh timestamps; they need not be byte-identical to old audit files.

The runtime manifest's origin audit reference is fixed historical provenance
recorded in the recipe, not the digest of each new replay's timestamped audit
directory. A replay must still fully verify its newly generated audit release and
match all locked payload digests before using that reference. Its fresh audit
digest and verification outcome go into the ignored replay report. This separates
the original release's provenance from evidence that today's rebuild reproduced
its payload, without pretending the two audit directories have identical bytes.

Define two different commands/results:

1. **Reproduce:** checked source acquisition, full build validation, runtime export
   into an ignored directory, then byte-for-byte comparison of every runtime
   payload/manifest/asset against the committed release. Do not copy the committed
   events into the rebuild output or treat equal counts as equality.
2. **Update:** explicit new source lock/policy as needed, a newly validated build,
   new immutable runtime release ID and a reviewable Git diff. Changes to the
   default pointer are separate intentional changes, never a replay side effect.

Every mismatch reports affected files and changed/missing/added event IDs, with
nonzero exit status. Neither command activates a database or overwrites the
committed catalogue. Any comparison field exclusion must be enumerated; the
runtime bundle itself has no timestamp exclusion that weakens byte equality.

## 11. Licensing and public-package review

Keep catalogue text attribution/share-alike obligations distinct from MIT code
and per-file media licences. Commit the catalogue licence/notice, dataset and
Wikipedia contributor credit, source links, modification notices and asset
credits. Ensure the app continues displaying required credits.

The current catalogue and upstream notices identify adapted text as CC BY-SA
4.0; fallback art is CC0. That permits a conditional redistribution design, not
a blanket legal-clearance claim. Respect any additional per-record obligations
and do not imply Wikimedia or dataset-author endorsement.

The tracked runtime directory and any external source archive each need an
explicit allowlist/privacy scan. Remove private-only metadata before constructing
the distribution artifact, without modifying preserved original evidence. Do not
push the previously private intermediate feature history; eventual publication
uses a clean, reviewed integration with only intended public files.

## 12. Verification and release gates

### Offline, clean-checkout gates

- Export/verify/install tests reject missing or extra files, duplicate IDs/JSON
  keys, malformed years, broken references, dishonest counts, bad licence/credit
  data, corrupted media, traversal, symlinks and aliased artifacts.
- Runtime format is rejected by the full audit verifier; incomplete audit input
  is never reinterpreted as a runtime bundle.
- Clean-checkout Docker and non-Docker verification use only tracked files, with
  no private checkout, `/tmp/opencode`, preserved raw directory or network cache.
  Build the normal dependency images first, then deny content-network access.
- A fresh owned disposable DB initializes the included default and has playable
  public options, Daily/Freeplay and working media/credits. It is not enough for
  generic API and homepage health checks to pass.
- Repeat installation is idempotent; conflicting IDs roll back; existing selected
  catalogues, old runs/Dailies and credentials remain unchanged.
- Packaged and rebuilt catalogues preserve current event/source/media behaviour,
  hidden pending years, authoritative scoring and owner-bound replay semantics.

### Rebuild gates

- Offline pipeline tests use small, committed synthetic fixtures for actual
  acquisition parsing, transformation and comparison; no developer cache assumed.
- A separate explicit acquisition/reproduction job starts with empty source cache,
  downloads the locked inputs, runs full acceptance/media verification and compares
  all runtime bytes. It reports missing legacy inputs honestly and never uses the
  committed catalogue as its own source material.
- Changing a source revision/digest, evaluation context, transformation rule,
  licence or generated record causes the appropriate rejection or comparison
  difference. Two isolated rebuilds with the same lock yield identical bundles.
- No test mutates the live catalogue/database. Target ownership, isolation and
  absence of foreign consumers are verified before integration-test setup.

Update self-host documentation with separate run/reproduce/update instructions,
licensing boundaries, dependencies and known source availability limitations.
The separate `main` branch-filter cleanup and local-only rollout-test/CI setup
blockers remain publication prerequisites, not extra implementation scope here.
This design does not hide them with skips or claim that packaging alone fixes them.

## 13. Non-goals and acceptance decision

No catalogue expansion or quality overhaul, photo acquisition, external hosting
provisioning, source-release upload, production reset, gameplay migration strategy,
repository split, push, merge or deployment is performed as part of this design.

Acceptance requires both a genuinely offline playable clean install and an
independently fetched exact rebuild. If only the first passes, describe the result
as **portable runtime catalogue; exact rebuild not yet demonstrated**, not fully
reproducible self-hosting. Any exception needs an explicit owner decision, not a
silent reduction of these requirements.
