# Beta catalog readiness — BLOCKED

Measured on 2026-10-12. **No real beta release was published or activated.**
The isolated, private C6 pilot has **22 distinct real sourced events** with
fresh automated `content_media` receipts and an independent C5 batch/asset check.
This is **978 short of 1,000** and must not be presented as a beta catalog.

## Measured coverage

| Category | Accepted events | Pilot leads | Final yield |
| --- | ---: | ---: | ---: |
| Births | 5 | 16 | 31.25% |
| Deaths | 3 | 16 | 18.75% |
| Battles | 5 | 16 | 31.25% |
| Inventions | 0 | 16 | 0% |
| Literature | 2 | 16 | 12.50% |
| Arts | 3 | 16 | 18.75% |
| Exploration | 1 | 16 | 6.25% |
| Politics | 3 | 16 | 18.75% |

Overall: **22/128 leads = 17.1875%**; **22/63 submitted distinct source keys =
34.9206%**. There are 41 importer quarantines. Before import, 62 lead rows lack
joint supported milestone fields, one lacks an exact entity, and one general
transistor/BJT scope remains explicitly excluded. One exact Apollo lead duplicate
was merged before import, not counted as another event. Research screens and
unsubmitted leads are not accepted events. All eight taxonomy categories remain
unchanged, but actual eight-category event coverage **fails**.

- Years: **22 distinct years, 1600–2013 CE**; BCE 0, ancient 0, medieval 0,
  early modern 4, modern 11, contemporary 7.
- Region memberships: Europe 9; Latin America, North America, Oceania,
  South Asia and Southeast Asia 2 each; East Africa, East Asia, Southern Africa
  and global 1 each. These are seed-location heuristics, not exclusive identities.
  North/West Africa, West/Central Asia, ancient and medieval coverage are absent.
- Fixed Daily categories remain `battles`, `inventions`, `exploration`, `politics`:
  their union has **9 events / 9 distinct years**. Full-bound maximum year capacity
  at gaps 1/5/10/25/50 is 9/8/8/7/5; arbitrary narrow bounds are not guaranteed.
- **0% photographs; 100% fallback-only; 100% meaningful fallback references.**
  C4 made actual event-specific source-P18 lookups: 22 decisions, 12 file attempts,
  10 cached Commons metadata responses. Eight original CC0 SVG assets total
  **5,431 bytes**, independently checked in frozen and separate media stores.
- All **22 available accepted events** were independently audited. The required
  **100-accepted-record audit fails**. Labels occur in concise 3–7-word official
  milestone prompts. Temporal-distance proxies are reported, not validated
  recognition or difficulty guarantees. No player pilot was performed.

## Sources, gates and blockers

Selected sources remain Wikidata structured data (CC0) and English Wikipedia
(CC BY-SA 4.0 attribution; original deterministic prompts, not copied extracts).
Accepted events retain 22 citations from each provider, binding **25 distinct
provider-response digests**. Articles have actual pinned revisions. The three
retained C1 Wikidata envelopes have **no entity revision IDs**; no later revision
has been retrofitted. Source terms and raw snapshots remain private.

Two bounded Wikidata requests exhausted three attempts each on `maxlag=5`;
the later retained response identifies query-service lag. No limit relaxation,
new provider, credentials, paid access or infrastructure was used. Expansion was
stopped, rather than acquiring thousands of unsupported leads. The measured
purposive pilot does not establish a scalable acceptance forecast.

C4 also returned Commons HTTP 429 for two events. Its current metadata/CLI path
continues after such fallback outcomes without provider-wide Retry-After
backoff/stop handling. This shared-code issue is reported privately, **not fixed
under C6's isolation scope**; media acquisition was not repeated.

Normal non-fixture C5 publication exited **1** with
`beta_requires_1000_distinct_accepted_nonfixture_events`.
Mandatory `verify --require-beta` exited **1** because no release manifest exists
after the rejected publication. **No exit-0 beta verification, certification,
fixture workaround, human review or legal clearance is claimed.**

Validation: `automated-v1`; adapter `selected-v7`.

| Binding | SHA-256 |
| --- | --- |
| Content input | `492e11d57a3908317453890506c3f0813081c2d91efdfc6e230bcd9eac4af5b3` |
| Whole MediaCatalog | `b8fc4ded39564f7e1e10c4cb0b3ba2fe886f4586036a369d4d6bce5d008e9298` |
| Media rules/dependencies | `5e769b010c32a62d9ca0b0d1598a2788a4785711ff13479cd88424fe74f448e7` |

Private resumable workspace: `data/game/acquisition/c6-workspace/`.
Evidence: `.superpowers/sdd/2026-10-11-historical-date-game-beta/c6-evidence/`
(`coverage.json`, `coverage-events.csv`, `category-yield.csv`,
`accepted-audit.json`, exact CLI results, source caches and code-issue evidence).
Full handoff: `.superpowers/sdd/2026-10-11-historical-date-game-beta/task-C6-report.md`.
Source access spending: **$0**; engineering/runtime/storage are not free-effort
claims. This document is intentionally unstaged; B2 activation remains blocked.

## 2026-10-12 approved JSONL trial — LOCAL RELEASE, NOT ACTIVATED

The preceding **BLOCKED C6 checkpoint is preserved as historical evidence**,
including its then-current limitations and staging scope. The later user-approved
offline chronology trial now has **1,276 distinct real accepted events** with
fresh `content_media` receipts and exit-0 standalone `verify --require-beta`.
These are **1,271 Wikipedia chronology events + five unchanged C6 birth facts**,
not fixtures or precomputed acceptance rows. No active DB/catalog was changed;
controller review is required before activation.

| Category | Final accepted events |
| --- | ---: |
| Births | 5 |
| Deaths | 171 |
| Battles | 544 |
| Inventions | 23 |
| Literature | 65 |
| Arts | 32 |
| Exploration | 145 |
| Politics | 291 |

All eight categories have events, **not balanced or deep coverage**: births,
inventions and arts are particularly thin. This is an automatic count/provenance
gate result, not manual historical review, recognition testing, legal clearance
or a promise that every Freeplay interval supports a long run.

### Actual source accounting

Pinned `mneedham/wikipedia-onthisday` commit
`9f30eae49675c8e71453b332f83a6b6b3bb297d4`; original JSONL is **6,626,097 bytes**,
SHA-256 `0fd539accf6ee5f31ddbf374ce24398381f5ac51def4309ce4c93e46daed30db`.
The **19,860 unique input rows** comprise 19,680 Wikipedia history rows, 176
Wikidata future/demo rows and four synthetic rows. The latter 180 are excluded.
The history subset contains 1,370 positive CE years and no BCE.

Automatic row dispositions: **1,271 accepted**, **18,589 quarantined**:
17,897 unresolved category; 203 conflicting explicit contextual years; 246
uncertain text; 33 suspected duplicates; 16 unsafe prompts; 14 answer leaks;
180 unselected future/demo/synthetic rows. There are no exact source-row or
cross-day passing duplicates in this file; that is not exhaustive semantic
deduplication. Conservative classification preserves the descriptions rather
than erasing answer dates. Row-level reasons and all 1,276 accepted automated
audits are retained privately, including an identified first-100 audit subset.

Canonical chronology answers are the **reported historical civil YEAR**, not a
converted Gregorian day/month claim. Original dates, source URLs, README/NOTICE,
download receipt and source file bytes are independently checked and frozen.
Dataset pinning is **not** Wikipedia article-revision pinning or independent
Wikidata corroboration. The unchanged original exact-source adapter handles the
five birth supplements; their older Wikidata response has no entity revision ID,
and none is retrofitted.

### Coverage and licensing limitations

- **569 distinct years, 9–2025 CE**, BCE 0. Ancient 17; medieval 274; early modern
  214; modern 437; contemporary 334 (same era boundaries as the C6 checkpoint).
- The chronology lacks region labels: **1,271 events remain unclassified by
  region**, not guessed from prose. The five C6 birth seed labels contribute one
  each to Europe, Latin America, North America, Oceania and Southeast Asia.
- Fixed Daily union: **1,003 events / 492 distinct years**. Full-range greedy
  capacity at gaps 1/5/10/25/50 is **492/194/116/59/34**. Narrow intervals and
  category-restricted pools have no general capacity guarantee.
- **0 photographs; 1,276 fallback events; eight meaningful original CC0 assets
  totaling 5,431 bytes.** JSONL decisions honestly say no source image metadata.
  Two already-cached supplement image attempts fail required-credit-link safety;
  three have no supported source image candidate. No new network request occurred.
- Prompts range from **3 to 55 words**. Time-distance proxies: 202 within 50 years,
  503 at 51–200 years, 571 over 200 years. These are not validated difficulty or
  recognizability assessments. No player pilot or manual content review occurred.
- Adapted Wikipedia catalog text retains contributor/dataset attribution,
  CC BY-SA 4.0 links and modification notices in checked catalog LICENSE/NOTICE
  artifacts and public credits. Application code remains separately MIT licensed;
  image/fallback credits are separate. No legal guarantee or endorsement is made.

### Local handoff and checks

Current ignored release: `data/game/releases/jsonl-trial-2026-10-12-final/`.
Standalone `verify --require-beta`: **exit 0, fixture=false, event_count=1276**.
Combined workspace: `data/game/acquisition/jsonl-combined-workspace/`.
An earlier local exploratory release without the `-final` suffix is retained but
predates the final acceptance fingerprint; use only the named final release.
Neither release is activated. Existing backend PID 1643276, port 8000, safe DB
5433 and browser fixture were not changed.

Verification: **64 focused chronology tests and 580 pure content/game/safety
tests pass**; Ruff and mypy pass. The destructive DB suite was intentionally not
run during browser use. Original exact-source adapter code is unchanged. Full
private commands, outputs, hashes, audit and limitations:
`.superpowers/sdd/2026-10-11-historical-date-game-beta/task-JSONL-report.md`.

## 2026-10-12 JSONL review round 1 — WHOLE-RAW GATES, NOT ACTIVATED

The C6 and initial JSONL checkpoints above remain historical evidence. Review
identified a late-gate integrity gap, not a demonstrated bad published catalog:
individually valid quarantined rows could bypass whole-input duplicate/conflict
constraints when restored with resealed bindings. C4 finalization and C5 standalone
verification now independently normalize **all 19,865 retained raw candidates**
once per batch using the same deterministic constraints as import. Stored
passed/quarantine decisions are not evidence of eligibility. Original exact-source
alias/date safety is preserved; the new shared rules are fingerprint-bound.

**Use `data/game/releases/jsonl-trial-2026-10-12-review-r1/` for current review.**
Fresh CLI publish and standalone `verify --require-beta` both exit 0:
**fixture=false, 1,276 events**, comprising **1,271 chronology + five C6 births**.
The earlier `-final` release is immutable and now correctly fails with
`stale_media_rules`; it is no longer the current-rules release.

- All **19,865 import dispositions and 1,276 candidate digests** match the prior
  generation. The reimport reports zero newly imported events, not zero accepted
  events; fresh media finalization reports 1,276 passed / zero failed.
- All 1,276 accepted events received an automated whole-raw eligibility and
  provenance audit. Actual Soyuz line 5001 remains excluded with
  `suspected_duplicate`; no stored decisions were used to establish eligibility.
- Event, candidate, raw, alias, taxonomy, source-policy, coverage, text-license,
  pinned chronology snapshot and all eight fallback bytes match the prior release.
- Counts/limitations above are unchanged: births 5, deaths 171, battles 544,
  inventions 23, literature 65, arts 32, exploration 145, politics 291; 569 distinct
  years, 9–2025 CE, no BCE; 1,271 events without regions; zero photographs and 1,276
  fallbacks. This remains **DONE_WITH_CONCERNS**, not balanced coverage, historical
  truth validation, human review, legal clearance or activation approval.
- Verification: **366 focused importer/chronology/media/publisher tests and 589
  pure content/game/safety tests**, four existing warnings; Ruff, formatting and
  mypy pass. No DB suite, live HTTP, service, game/UI or active-catalog change.

| Replacement binding | SHA-256 |
| --- | --- |
| Manifest | `804ec52ccfc3e19cd955913b05cbfd59158f562408e45c1916fa8626d3ac50d3` |
| Content input | `d9c665f4c1554aadea0dfb372e9c62470a54186587110163dd9c062f70086dac` |
| Whole MediaCatalog | `b8fc4ded39564f7e1e10c4cb0b3ba2fe886f4586036a369d4d6bce5d008e9298` |
| Media rules/dependencies | `fda414e26041f641ef125449f56ab5859d5e4b3f5d2f3cdd6eef4a0d46a93fa3` |

Private round-1 evidence: `jsonl-pilot/review-fix/` beside the existing private
`task-JSONL-report.md`. Controller followup remains scoped to the Important finding
and `dd52c87..` fix diff; no merge, push or activation is authorized here.
