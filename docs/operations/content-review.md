# Automated content imports and quarantine

Despite this retained filename and `review_status` contract, there is **no human
content/image review, approval queue, or manual publication gate**. C3 imports
private facts only. A passed `content` receipt is **never publication-ready**;
C4 must independently revalidate content and the frozen complete MediaCatalog,
then C5 verifies final receipts and actual asset bytes. C4's Python media API is
described below; the private publisher/CLI workflow is documented at the end.
This does not implement game functionality or public serving.

## Supported selected-provider snapshots

`SelectedSourceAdapter` uses only `wikidata` and `wikipedia_en`, as selected in
`docs/research/source-selection.json`. New missing-cache requests are serial,
revision-pinned Wikimedia Action API reads (`action=query`, a single `revids`,
`prop=revisions`, `rvprop=ids|content`, `rvslots=main`). Include `pageprops` for
Wikipedia's exact Wikidata entity association. Wikidata main-slot content is
Wikibase entity JSON; Wikipedia main-slot content is wikitext. A cached
`wbgetentities` envelope with matching `lastrevid` is also supported. Never pass
an unsupported `revision` parameter to `wbgetentities` or combine latest
extracts with an oldid to claim they are pinned article content.

Prepare a private directory with `snapshot.json`:

```json
{
  "snapshot_id": "facts-immutable-batch-1",
  "requests": [
    {
      "source_id": "wikidata",
      "file": "raw/entity.json",
      "sha256": "<exact response byte SHA-256>",
      "acquired_at": "<actual UTC acquisition timestamp>",
      "params": {
        "action": "query", "prop": "revisions", "revids": "<actual revision>",
        "rvprop": "ids|content", "rvslots": "main"
      }
    },
    {
      "source_id": "wikipedia_en",
      "file": "raw/article.json",
      "sha256": "<exact response byte SHA-256>",
      "acquired_at": "<actual UTC acquisition timestamp>",
      "params": {
        "action": "query", "prop": "revisions|pageprops", "revids": "<actual revision>",
        "rvprop": "ids|content", "rvslots": "main"
      }
    }
  ],
  "records": [
    {
      "source_id": "wikidata", "record_id": "<persistent acquisition key>",
      "entity_id": "<exact Q identifier>", "milestone": "birth",
      "category_ids": ["births"], "region_ids": []
    }
  ]
}
```

Placeholders above are documentation, **not fabricated source evidence**. Supply
real pinned IDs, bytes, metadata and digests from bounded acquisition. This
importer is not a discovery crawler: missing-cache retrieval requires an already
known digest and pinned revision. A digest mismatch or revision mismatch halts
without advancing the workspace. Cache hits make no network request. Paths must
remain inside the snapshot root. Archive source terms/licensing evidence with
the snapshot separately; source selection is not a claim of legal clearance.

Missing-cache requests record exact URL, status, response headers, actual UTC
retrieval time, User-Agent and byte digest in `<file>.meta.json`. The identifying
User-Agent and `maxlag=5` are set on every request. Acquisition sleeps at least
one second per request, uses no concurrency, caps a response at 8 MiB, a batch
at 256 requests / 2,000 records, and each request at three attempts. HTTP 429/503,
Action API maxlag and transport failures use bounded exponential backoff,
honoring both numeric and HTTP-date Retry-After. Delays over 120 seconds stop
the run for a later retry, not evade the provider limit. Other HTTP/API errors
fail closed. No credentials, host expansion, IP rotation or unbounded downloads.

### Exact normalization, not prose reconstruction

Supported milestones map directly to actual provider statements and supported
infobox types/active parameters:

| Milestone | Wikidata property | Supported outer infobox / ordinary fields |
| --- | --- | --- |
| birth / death | P569 / P570 | person, officeholder: birth_date / death_date |
| publication | P577 | book: published, pub_date, publication_date, release_date |
| creation | P571 | artwork: year |
| invention | P575 | electronic component: invention_year |
| start / end | P580 / P582 | military conflict: start_date / end_date, or exact endpoint of date |
| occurrence | P585 | event, military conflict: date (one exact date, not an interval) |
| launch / landing | P619 / P620 | spaceflight: launch_date / landing_date |
| inception | P571 | organization: established / formation; company: foundation / founded |
| premiere | P1191 | musical composition: premiere |

Category memberships use the eight C2 taxonomy slugs. Ordinary active fields
have real retained source-backed examples across all eight categories: Bolívar
birth, Mandela death, Midway start, transistor invention, Pride and Prejudice
publication, Guernica creation, Vostok 1 launch, Indonesian proclamation
occurrence. This demonstrates these particular normalization paths, not broad
automatic coverage of every article/type or historical truth. Inception/premiere
are declared conservative paths without a real round1 demonstration. Discovery
remains reserved but has no supported infobox grammar: an invention_year field
cannot also create a duplicate discovery milestone. Other
infobox layouts, edition scopes and milestones are **not inferred**. Expand
rules with source-backed tests and bump `selected-v7` in the fingerprint.

Wikitext is parsed with stable `mwparserfromhell` 0.7.2, not searched for field
lines throughout page text. Only one supported **active top-level** infobox can
substantiate the requested milestone. Comments, nowiki/tag-wrapped examples,
unrelated/nested templates and duplicate milestone fields cannot supply facts.
Every relevant top-level parameter occurrence is counted before value cleanup;
duplicates quarantine in either order, including blank or comment-only values.
Date fields are bounded (16 KiB before footnote/comment exclusion; 512 characters
of active date grammar); the original bytes/templates/annotations stay private
and unchanged. Footnote refs/comments are excluded from date interpretation,
not treated as event fields; their exclusion never concatenates separated digits
into an invented raw year. Unsupported active markup remains quarantined.

The retained transistor example's infobox names Bipolar Junction Transistor
(BJT), while its article/entity is general transistor Q5339. It demonstrates
the `invention_year` grammar, not production-approved historical equivalence
between subtype and general-entity milestones. No identity resolution is guessed.

All claims for the selected property are checked, not just preferred rank.
Unknown/non-time values, deprecated claims, any qualifiers, uncertainty bounds,
unsupported calendars/precision and conflicting exact dates quarantine the entire
identity. The policy is intentionally stricter than C1's research screen.
Exact civil/ISO fields, full English dates and supported parsed date templates
corroborate the same entity/milestone. A military-conflict `date` can resolve
ordered exact day endpoints, including shared month/year (`4–7 June 1942` or
`4–{{start date and age|1942|06|7|df=y}}`) and explicit full cross-year endpoints.
The start/end prompt names the selected milestone, not the whole interval.
Vague year ranges, circa/alternative/reversed dates or calendar annotations are
rejected. Spaceflight clocks require explicit source UTC; unsupported time zones
are never silently converted. English/template citations retain the actual
source year substring, not manufactured ISO evidence.

All statements and both providers are compared **pairwise at their common
supported exact precision**, including persistent exact aliases. A year-only
source cannot hide conflicting finer dates elsewhere. Declared Wikibase
precision governs filled placeholder month/day components. Conflicting
months/days quarantine even when years agree. Event precision is the minimum of
all semantically supported source dates and C2-supported raw citation precision:
year-only citations stay year, ISO day citations can establish day when all
sources agree. English/template raw year substrings intentionally cap emitted
events at year **after** full source-date conflict checks. C2 contracts/validation
were not broadened. Raw provider envelopes retain full date components and
precision; a content receipt is not a finer-date historical truth guarantee.
Wikipedia's unannotated civil-year grammar is supported only when corroborated
by the exact Gregorian-family Wikibase milestone; calendar annotations are not
silently converted. Its citation labels that supported convention
`proleptic-gregorian`; the unmodified provider data (including absent metadata)
is retained privately.

Raw Wikibase time/sign, precision, calendar URI, timezone, before/after, rank,
statement IDs, qualifiers and references are preserved in `raw.jsonl` and
quarantine. Gregorian-family exact dates alone produce the C2 token
`source-resolved:<gregorian|proleptic-gregorian>:year_index=<integer>`.
For positive civil magnitude `n`, CE is `n`, BCE is `1-n`. JSON `-0001` denotes
1 BCE (canonical 0), **not astronomical year -1**. C2 independently crosschecks
the retained raw dates/calendars. No token is manufactured for a rejected date.

Prompts are original deterministic milestone templates using the English source
label (or the exact entity-linked Wikipedia title if that label is absent),
not copied Wikipedia extracts or C1 judgments. C2 rejects answer-bearing labels
without erasing historical names. Exact entity + milestone identities merge
citations/categories; birth/death stay separate. Exact-to-different-exact source
aliases quarantine both old and new identities. Unresolved placeholders are
dispositions, not exact aliases: older unresolved alias entries are migrated
away, and the same source key can promote to proven exact identity through new
automated source evidence. Similar same-milestone wording at
similarity ≥0.90 quarantines both candidates and never creates fuzzy aliases.
This is a conservative duplicate heuristic, not proof of universal detection.

### C1 cache compatibility and limitations

The adapter also reads the retained C1 `seeds.tsv`, `raw/wiki-*.json`,
`raw/entities-*.json`, and associated actual `.meta.json` digests/timestamps.
It does **not** read audit decisions, prompts, researched years, aggregate
`pages.json`/`entities.json`, or later revision probes to manufacture evidence.
It checks original response bytes and preserves absent entity revision IDs.
Cached extracts are cited at their actual acquired request URL + snapshot hash,
**not** claimed to be oldid-pinned content. Only unambiguous leading biography
lifespans are supported in that legacy layout; non-biographical research leads
have no structured milestone/edition scope and quarantine. A research duplicate
such as Apollo's two category leads cannot be merged into an accepted fact until
its precise landing milestone is supported by actual selected-source fields.

## Run and inspect (no DB required)

From `backend/`, replace paths with private snapshot/workspace directories:

```bash
uv run python - <<'PY'
from pathlib import Path
from app.content.adapters.selected import SelectedSourceAdapter
from app.content.importer import import_snapshot
print(import_snapshot(SelectedSourceAdapter(), Path("/path/to/snapshot"), Path("/path/to/workspace")))
PY
uv run pytest tests/content/test_importer.py -q
uv run pytest tests/content tests/safety -q
uv run ruff check app
uv run mypy app
```

The Python API above remains available; equivalent CLI commands appear below.
No human review command exists.
Quarantine is the final machine outcome for unsupported data, not a work queue.
Later supported source updates may resolve it through fresh automated checks.

## Persistent workspace contract for C4/C5

The only authoritative commit point is `current.json`, containing a relative
`generation` and `input_sha256`. Resolve it **once** per read, then use that
immutable generation under `generations/`. Never union files from different
generations or publish unreferenced/orphaned generations.

| Generation file | Private contents |
| --- | --- |
| `raw.jsonl` | Every current source-key payload, both provider envelopes and acquisition metadata; no evidence rewriting |
| `candidates.jsonl` | C2 EventRecords passing content only (`review_status='approved'` means machine content pass, not publishable) |
| `quarantine.jsonl` | Failed raw groups, issues/codes and optional quarantined EventRecord |
| `aliases.json` | Persistent exact source-key → identity + stable UUID; source keys are JSON-encoded `[source_id, record_id]` |
| `receipts.jsonl` | C2 ValidationReceipts, passed **and failed**, `stage='content'`, `media_catalog_sha256=null` |
| `decisions.jsonl` | One disposition for every source key, candidate/raw/source digests and issue codes |
| `sources.json` | Snapshot-byte SHA-256s and each record's raw digest + acquisition evidence; input fingerprint |
| `state.json` | Resume state: active raw keys, aliases, previous candidate digests and totals |

Receipts bind all candidate fields via C2 `candidate_digest` and sorted unique
provider-response digests. A failed raw-only group has no valid EventRecord:
its `candidate_sha256` instead binds the canonical ordered raw group, as recorded
in quarantine/decisions. **Never** reinterpret that failed receipt as an event
pass. IDs derive deterministically from exact identity, never year/prompt; aliases
and IDs survive updates and retries.

`aliases.json` contains only proven exact identities. An unresolved quarantine
UUID is per source key and is not a canonical event ID. Recovery replaces that
placeholder disposition/failed receipt with the proven identity's deterministic
UUID, updates aliases and regenerates checks atomically. It does not retarget a
previously proven exact identity or authorize fuzzy identity inference. Legacy
`unresolved:` entries in `state.json` are removed during the next revalidation;
the adapter-version change forces migration even for unchanged source inputs.

Imports upsert persistent source keys. Partial batches do not silently delete
previous keys; unsupported corrections revoke old passes. There is no deletion
API in C3. The fingerprint includes all raw inputs/evidence, taxonomy, current
year, policy and adapter-rule version. Unchanged imports keep the same generation
and receipts and return `imported=0`. Any changed input regenerates the entire
active content decision set; do not reuse prior-generation receipts. `imported`
counts newly passed/changed canonical candidates; `quarantined` counts active
failed raw keys; `duplicates` counts exact merged extra keys among passing facts.

After a parser correction, do not rely on the unchanged-import fast path to
recheck old decisions. Force revalidation through an updated adapter fingerprint
or import the retained snapshot into a fresh private workspace; never carry an
old pass forward without those fresh checks.
The blank-duplicate correction bumps the fingerprint to `selected-v7`: the next
import automatically revalidates a prior `selected-v6` workspace even when the
source snapshot is unchanged. Old duplicate-field passes are revoked into
quarantine; subsequent unchanged retries retain that failed decision.

A filesystem lock serializes writers. Files and directories are fsynced before
an atomic pointer rename. Crashes/fetch failures before that rename leave the
previous generation readable; retry upserts the same keys without duplicates.
Orphan generations are not authoritative and are retained for diagnosis, not
automatically deleted. Local POSIX filesystem semantics are required; no network
filesystem or distributed-writer guarantee is made. Fuzzy checking is quadratic
in active candidates; measure larger catalog runs rather than promise throughput.

C4 consumes current candidates, raw provenance/source digests and identities;
it does **not** carry a C3 pass into publication acceptance. It freezes media and
rechecks content+media for all current candidates with fresh `content_media`
receipts. C5 consumes only independently verified final artifacts and digests.
Neither C1 research screens nor these C3 content passes count as the final
1,000-event publication gate.

## C4 automated media API and C5 handoff

`app.content.media.pipeline.assign_media(event, selection, workspace)` consumes
an **unchanged current C3 candidate**, its retained raw provider envelopes and
the selected Commons/original-art policy. Resolve `current.json` once to load
that generation's candidates. It attempts up to three exact, unqualified,
nondeprecated Wikidata P18 file names for **each event**. This is a real per-event
candidate lookup, not a fallback-only stub or open-ended image search. With no
P18 candidate it records that reason and selects representative original art.

Commons metadata is cached privately in
`media-cache/commons/<sha256-of-normalized-File-title>.json`, with a matching
`.meta.json` containing the exact response SHA-256, fixed Commons endpoint and
actual metadata retrieval timestamp. Missing cache entries optionally make one
serial fixed-endpoint `imageinfo`/`extmetadata` request per selected title, sleeping
one second and setting `maxlag=5` and an identifying User-Agent. Redirects,
provider errors and responses over 1 MiB / bounded request time are failures, not
a retry loop. File title/repository, original URL, SHA-1, revision timestamp,
credit, license/version and metadata digest are retained in private decisions.
No C1 research screen is promoted to media approval. Cached snapshot bytes never
silently refresh or overwrite; a new metadata acquisition must be supplied as
a new private snapshot/workspace rather than replacing an authoritative batch.

### Provider throttling: incomplete batch, explicit retry

Commons HTTP **429/503** (including pinned upload downloads), and HTTP-200
MediaWiki `maxlag`/`ratelimited`/`rate-limited`/`throttled`/`actionthrottled`
errors **stop the batch**, not select image fallback. No later uncached metadata
or image request runs in that stopped workspace. The CLI exits nonzero, writes
structured `commons_throttled`/`incomplete` retry information to stderr, and
emits no successful summary or new final receipts. Individual missing-image,
unsupported-rights and ordinary request failures still use reasoned fallback.

Private `commons-throttle.json` records status, API error, original Retry-After,
observation/deadline/basis and an evidence reference. Private digest-named
`media-failures/commons/*.json` captures the bounded response body/hash and only
Retry-After, Date, Content-Type and X-Database-Lag response headers; never cookies,
authorization or request tokens. HTTP errors are **not** installed as successful
Commons cache snapshots. Partial body failures retain the known throttle status;
body limits are 1 MiB / 20s between reads. Upload body streams already closed by
`raise_for_status` are not reopened; their status/headers remain available and
body evidence explicitly says truncated/unavailable. Persistence errors also
stop rather than fall back; a successful marker write protects future commands
even if the detailed evidence write subsequently fails.

Retry-After accepts integer seconds and timezone-aware HTTP-date; server Date
can extend (never shorten) the interval for clock skew. Missing, invalid,
negative or past declarations default to **300 seconds**; zero seconds means
at least one second. Unrepresentably long explicit intervals remain blocked
(`retry_at: null`), not shortened. No long sleep or automatic retry is added.
After a finite deadline, rerun explicitly:

```sh
cd backend
uv run python -m app.content.cli media \
  --selection ../docs/research/source-selection.json \
  --workspace /private/workspace --retry-throttled
```

Early retry and ordinary reruns after expiration both remain nonzero without
requests. Explicit retry clears only the expired operational marker under the
media lock, retaining immutable failure evidence and successful caches. It
revisits current candidates and reuses successful cached metadata/originals;
finalization still requires a complete, independently revalidated current batch.
A stopped finalizer cannot reuse an older complete stage as a new pass. Already
frozen final generations/receipts/assets and C3 source normalization remain
untouched. Cache-only metadata reads remain usable while stopped, but cannot
finalize the incomplete batch. This is a workspace/batch stop, not a distributed
quota coordinator across independently operated workspaces.

Throttling does **not** relax media/license/date/safety acceptance or bump the
acceptance policy fingerprint. `commons_transport.fingerprint_source` narrowly
projects only the exact operational hook spellings to the BASE `0bc76c7` source
before hashing; every other pipeline byte, all other media modules and policy/
provenance checks remain bound. Tests verify equality to that C5 base fingerprint
and that actual pipeline acceptance changes still invalidate it. Acquisition-only
stop/retry implementation is outside the media-policy source set, so previously
valid frozen batches do not require a pointless refresh for this fix.

Supported per-file rights are CC0, CC BY / CC BY-SA 2.0, 3.0 and 4.0, and explicit
`PD-self`, `PD-author`, `PD-old-100-expired` or
`PD-Art (PD-old-100-expired)` bases. A generic PD label alone is insufficient.
Conflicting license fields/URLs/versions, missing creator/credit, territorial-only
or non-Commons files, unsupported licensing and unresolved restrictions use
fallbacks. Required credit text **and its links** are preserved as plain text,
not removed to hide dates. Conversion/resizing and compatible adaptation terms
are included in `MediaRecord.attribution`; creator, source URL, exact license URL,
revision/SHA-1/metadata identity and actual original acquisition time remain in
the record/evidence. UI consumers must display accessible attribution and license
links, and escape these plain strings rather than interpreting source HTML.
Supplied `ObjectName` work titles are retained separately from the file title in
private candidate evidence and included unchanged in derivative attribution,
including the required title for CC BY/BY-SA 2.0/3.0. An unsafe supplied title
uses fallback, never title omission. Finalization independently rebuilds that
complete credit from the current cached file metadata. Explicit Commons
`cc-zero`/`cc0` tokens and `CC0`/`CC0 1.0` labels normalize to CC0; public-domain
dedication usage terms are checked separately from BY/BY-SA attribution terms.
Conflicting dedication/attribution declarations still fail closed.

Acceptance is intentionally narrow: source-P18 subject-context photographs must
fit **exact structural productions**, not arbitrary `of <prose>` descriptions.
Portraits require the exact current source English subject name, a bounded
capitalized proper-name grammar, and exactly the plain-background composition.
Objects and ships require source-matched subjects from closed positive physical
classes (transistor, microscope, telescope, steam engine, telephone, light bulb;
sailing ship), with no extra clause, object, sign or document. Unrecognized names,
classes or compositions fall back, rather than inventing visual truth. Names with
unsupported scripts/initials/suffixes currently also fall back. Additional risk
and Arabic/Roman/Unicode date screens apply to all metadata and complete public
credits. No OCR or visual recognition certainty is claimed.
Artwork, books/editions, battle/political scenes, maps/documents/title pages,
plaques, text-heavy/titled images and ambiguous rights, sensitivity or composition
use fallback unless a future supported automated rule establishes their safety.
This deliberately excludes many otherwise open photographs; neither image yield
nor real production catalog acceptance is measured here. Alt text honestly labels
accepted photographs as subject context, not photographs of the exact milestone.

Originals are digest-bound private cache entries in
`media-cache/originals/<upstream-sha1>.bin` plus `.meta.json` acquisition evidence.
Downloads allow **only HTTPS `upload.wikimedia.org`**, with no credentials or
nonstandard port. Every redirect is checked before sending; all resolved targets
must be globally routable, with private/link-local and IPv4-mapped IPv6 rejected.
The transport pins the checked IP while retaining the approved Host/TLS SNI and
certificate validation, closing the dial-time DNS-rebinding gap. Environment
proxies and automatic redirects are disabled. Limits are five requests per
download, 16 MiB, 10-second HTTP operation timeouts and a 30-second elapsed-time
budget checked between requests/chunks. OS DNS resolution itself is not
interruptibly deadline-bounded; a blocking operation may finish up to its timeout
after the budget. Local POSIX and trusted local workspace writers are assumed.

Preparation rejects unsupported/animated/broken images, oversized dimensions
(10,000 per side) or pixels (20 million), embedded textual/EXIF metadata and
decompression-bomb **warnings as well as errors**. WebP derivatives preserve the
full composition (`fit='contain'`, no crops), bounded to 1,600 pixels per side.
Only checked optional container metadata is stripped, never required credits.
No external media URL is a gameplay download. Public files are create-only
`media/<sha256>.webp`; existing different bytes cannot be replaced.

The eight packaged SVGs in `backend/app/content/fallbacks/` are original authored
geometric illustrations, offered under CC0 1.0 with generation provenance. They
share a palette and depict cradle/sun, memorial/branch, shields, mechanism/lamp,
open unlettered book, abstract canvas/brush, compass/route and civic assembly.
They contain no copied stock, text, dates, logos, scripts or external resources.
SVG element/attribute/palette/label checks and byte SHA checks run automatically.
Every final catalog's public fallback alt text **and creator** are rechecked for
current sensitivity/text/date safety, including unreferenced fallbacks; metadata
digest freshness alone is not a safety pass.
Birth/death milestones map to their own illustration; the other six taxonomy
categories map to battle/invention/book/art/exploration/politics. All candidates
have coherent fallbacks, even when they also have a photograph. SVG assets also
use create-only `media/<sha256>.svg` names; changed artwork creates a new URL.

### Atomic draft and final layout (no separate content contracts)

C3 generations are **never modified**. C4 uses the existing C2 EventRecord,
MediaRecord, FallbackRecord, MediaCatalog and ValidationReceipt types:

| Location | Meaning |
| --- | --- |
| `media-staging.json` → `media-staging/<batch-id>/` | Atomic private draft pointer; generation contains `assignments.json` (event ID → assigned EventRecord), `media.json` and event-specific `decisions.json`; no final receipts |
| `media-assets/media/<digest>.<webp\|svg>` | Shared immutable prepared assets; many events may reference identical physical bytes |
| `media-current.json` → `media-generations/<batch-id>/` | **Only C4 handoff commit point**, bound to exact C3 generation/input digest and canonical whole-media-catalog digest |
| Final `events.jsonl`, `media.json`, `validation.json`, `receipts.jsonl` | Assigned events, complete frozen MediaCatalog and all fresh final receipts (`validation.json` is an array; JSONL contains the same receipts) |
| Final `raw.jsonl`, `sources.json`, `aliases.json`, `candidates.jsonl`, `taxonomy.json`, `source-selection.json`, `decisions.json` | Coherent private source snapshot, unchanged C3 candidates and event-specific lookup/rights/relevance/fallback evidence |
| Final `media-cache/commons/*.{json,meta.json}`, `media-cache/originals/*.{bin,meta.json}` | Independent private copies of **selected** cached Commons metadata/originals and acquisition receipts; hashed in `batch.json`, never public assets |
| Final `media/<digest>.<webp\|svg>` | Independent byte copies, **frozen before validation**, never hardlinks to mutable/corrupted draft cache |
| Final `batch.json` | Private recovery/integrity summary: artifact byte hashes, source generation/input digest, catalog digest, event count and aggregate pass; **not a publisher CatalogManifest** |

`finalize_media_receipts(workspace)` refuses partial assignments or an obsolete C3
generation. It freezes the entire catalog and asset bytes, independently reruns
selected-source normalization/date/conflict/provenance and C2 content validation,
duplicate suspicion checks, per-event media rights/safety/relevance/credit checks,
fallback mapping and every current asset's actual SHA. It does not trust C3 pass
flags. All receipts use `stage='content_media'`, `automated-v1`, the assigned
candidate digest, C3-consistent sorted unique provider snapshot digests and C2's
canonical **whole** `media_catalog_digest`. Any catalog metadata/rights change
invalidates every old receipt, including events with unchanged fallback keys or
shared image IDs. Finalization always rechecks every event and writes fresh
receipts for the whole batch; failed receipts are persisted for machine diagnosis,
not sent to a human queue.

Writers take the C3 import lock then the C4 media lock, fsync files/directories
and atomically replace pointers only after coherent generations are complete.
Failed writes keep the previous pointer; orphan generations are not authoritative
and are retained. Reassigning after a C3 update starts a fresh draft; completing
it is required before finalization. Metadata/source/assets/receipts from different
generations must never be joined.

**C5:** resolve `media-current.json` once; require its content generation/input to
match the selected current C3 input, verify `batch.json` file hashes and recompute
the complete typed MediaCatalog digest. **Also independently call
`app.content.media.pipeline.media_rules_digest()`**: the final pointer, batch and
every decision must contain a matching `media_rules_sha256`. Missing or obsolete
fingerprints invalidate the handoff, even if old receipts/candidates/catalogs
otherwise match. This fingerprint binds the current C4 source, packaged art,
shared schemas/validation/import normalization and installed Python/Pillow/httpx/
pydantic/mwparserfromhell versions. Code/dependency corrections require complete
fresh assignments and whole-batch revalidation, not reusing a former pass.
`assign_media` starts a new draft on fingerprint change; finalization records
`stale_media_rules` failed receipts for obsolete/missing decision fingerprints.
The shared `automated-v1` receipt shape stays unchanged: C2 `validate_receipt`
alone does **not** check code/dependency freshness, so this batch check is
mandatory before C5 accepts persisted final receipts. Immutable already-published
run assets remain unchanged; this is a gate for new publication under current
rules, not mutation of historical releases. Independently load all events and final
receipts, derive each event's current source digests from retained raw evidence,
call C2 `validate_receipt`, reject any missing/failed/stale receipt, and hash actual
referenced image/fallback bytes against current record SHAs again. A pointer or
aggregate pass field alone is not proof. Use only this frozen generation when
building a release; do not read mutable drafts/cache. Keep source metadata,
decisions and receipts private. Publisher/CLI/release minimum-count checks remain
C5 responsibilities; no real catalog, legal clearance, deployment or manual
artist/device/content approval is claimed or required by C4.

Automated verification, from `backend/` (no database required):

```bash
uv run pytest tests/content/test_media.py -q
uv run pytest tests/content tests/safety -q
uv run ruff check app tests/content/test_media.py
uv run mypy app
```

## C5 immutable publication and executable CLI

From `backend/`, use private local POSIX paths and the committed selection:

```bash
uv run python -m app.content.cli import \
  --selection ../docs/research/source-selection.json \
  --snapshot /private/pinned-snapshot --workspace /private/content-workspace
uv run python -m app.content.cli media \
  --selection ../docs/research/source-selection.json \
  --workspace /private/content-workspace
uv run python -m app.content.cli publish \
  --workspace /private/content-workspace --output /private/catalog-releases \
  --release-id beta-immutable-1
uv run python -m app.content.cli verify \
  --release /private/catalog-releases/beta-immutable-1 \
  --media /private/catalog-releases/beta-immutable-1/media --require-beta
```

Commands emit JSON on stdout, diagnostics on stderr, and nonzero exit on failure.
Import reports `imported`, `duplicates`, and `quarantined` counts; quarantine is
excluded from candidates/publication, not a human queue. Approved adapters and
the committed machine selection are required. Cached imports/media do not need
the database; missing-cache acquisition follows the bounded C3/C4 policies above.
The media command assigns **every** current candidate in UUID order, then invokes
`finalize_media_receipts` once for the whole batch. Partial/stale batches or failed
final receipts cannot publish. There is no approve/review/override command.

For small, explicitly synthetic smoke catalogs, add `--fixture` to `publish` and
omit `--require-beta` from `verify`. This is not a way to label a beta corpus:
normal publication and beta verification require at least **1,000 independently
accepted events**, unique by both UUID and private identity, and `fixture=false`.
Pending/quarantined events, duplicate memberships, failed/missing receipts and
supplied manifest/report counts cannot inflate that gate. Tests cover 999/1,000
accepted synthetic shapes; that is not evidence of 1,000 real historical events.

### Acceptance is recomputed, not a report flag

Publication holds the C3/C4 reader locks and resolves each current pointer once.
It requires the C4 pointer/batch to match the current C3 generation/input and the
independently recomputed current `media_rules_digest()`. Frozen raw/source/alias/
candidate snapshots must match that C3 generation. Every final decision must have
the same current rules fingerprint and approved selection. All declared batch
file hashes are checked; an orphan/draft generation is never a publication input.

Both publisher and verifier independently load typed events, receipts, taxonomy
and MediaCatalog. They enforce the current taxonomy/selection, unique UUIDs and
identities, exact candidate/source/catalog/policy receipt bindings using C2's
four-argument `validate_receipt`, plus current source normalization and media
rights/relevance/provenance checks. Only passed `content_media`/`automated-v1`
receipts without issues qualify; C3 content passes never do. Per-event source
digests come from the retained **private raw acquisition evidence and source
receipts**, not `ValidationReceipt.source_sha256`. Raw canonical digests, evidence,
aliases and source metadata are checked again, and source licensing/attribution
obligations remain in citations, raw records and private rights decisions.

Selected Commons metadata, original-image bytes and acquisition receipts are now
frozen by C4 into the final batch. Independent checks reconstruct mandatory
credits/rights from those snapshots and regenerate derivatives in temporary
storage, not from the mutable workspace cache. Missing or inconsistent private
rights/original provenance fails closed. Every actual image **and every fallback**
is independently hashed/decoded/checked, including unused packaged fallbacks and
fallbacks for events with images. Filenames must be the record's content digest;
changing bytes does not become valid by refreshing manifest/batch hash entries.
Changed catalog metadata invalidates all old final receipts; C4 must reassign and
refreeze/revalidate the complete batch under current rules.

### Release layout and integrity boundary

Each create-only `/private/catalog-releases/<release-id>/` contains:

- `manifest.json` — C2 `CatalogManifest`; its declared release identity must equal
  the directory basename, independently of the file digest map.
- `events.jsonl`, `media.json`, `taxonomy.json`, `source-selection.json`.
- Private `validation.json`, `receipts.jsonl`, `candidates.jsonl`, `raw.jsonl`,
  `sources.json`, `aliases.json`, `decisions.json`, `batch.json`, and the selected
  `media-cache/` provenance snapshots. Never publicly serve these files.
- `coverage.json` — recomputed review status, CE/BCE era, region/category counts,
  distinct years/range, image counts and fallback coverage. Verification compares
  it to actual typed events/catalog, not to supplied summary assertions.
- `media/<sha256>.webp` and `media/<sha256>.svg` — the **only** directory eligible
  for future B5 public serving. No raw encyclopedia prose, snapshots, private
  identity keys or reports may enter public assets.

The manifest hashes every required artifact, selected private snapshot, image and
fallback. Unexpected/unhashed files, missing records/assets, absolute or traversing
artifact paths and symlinks (including parent directories) are rejected. The
explicit `verify --media` directory is checked against all current record SHAs in
addition to the release's frozen copies; it may be a separate digest asset store.

Records are canonically serialized with sorted JSON keys, events/receipts by UUID,
raw records by persistent source key, media by asset ID and taxonomy by slug.
Publishing the same frozen batch under different IDs preserves every artifact
digest; manifest identity/`created_at` differ. Reusing an ID always fails, even
for identical bytes. Cooperating local writers are serialized with a publication
lock; files/directories are fsynced and the complete private temporary directory
is atomically renamed only after validation. A write failure exposes no partial
release. Trusted local filesystem writers are assumed: these are integrity
hashes, **not signatures** against malicious replacement of an entire corpus.
Code/dependency rule changes require new C4 batches; current-rule verification
may reject an older release without modifying its already-frozen assets.

DB-free verification:

```bash
uv run pytest tests/content/test_publish.py -q
uv run pytest tests/content tests/safety -q
uv run ruff check app tests/content/test_publish.py tests/content/test_media.py
uv run mypy app
```
