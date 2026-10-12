# Automated content imports and quarantine

Despite this retained filename and `review_status` contract, there is **no human
content/image review, approval queue, or manual publication gate**. C3 imports
private facts only. A passed `content` receipt is **never publication-ready**;
C4 must independently revalidate content and the frozen complete MediaCatalog,
then C5 verifies final receipts and actual asset bytes. No media acquisition,
publisher, CLI, or game functionality is implemented here.

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

This is a Python API invocation, not a new CLI. No human review command exists.
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
