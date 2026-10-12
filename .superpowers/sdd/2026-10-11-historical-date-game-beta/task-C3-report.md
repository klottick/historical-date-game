# C3 implementation report

Date: 2026-10-12. Worktree: `/home/klottick/repos/historical-date-game/.worktrees/beta`.
Branch: `feature/friends-beta`. Base: `bb2ff00481e0a67352d370bbaf4a15a06bf6bb75`.
Status: implemented and verified, scoped commit recorded below; controller handles independent review.

## Outcome and boundaries

Implemented the selected-provider adapter and private resumable importer using
the existing independently reviewed C2 EventRecord/SourceCitation/issues/receipts,
taxonomy, `validate_event`, candidate digests and policy version. No models were
reimplemented. No DB, network acquisition, media pipeline, publisher, CLI or game
functionality was added/exercised. No subagents were spawned and no whole plans
were loaded. No human content/image queue or manual review was introduced.

Real provider formats supported: Wikibase `wbgetentities` cached envelopes;
revision-pinned Wikidata Action API main-slot entity JSON; Wikipedia Action API
revision main-slot wikitext with exact milestone infobox fields/date templates;
and narrowly supported C1 cache-only introductory biography lifespans. This is
not a bespoke normalized-fixture adapter. The committed fixture contains
explicitly synthetic provider envelopes; actual cached C1 data stays private.

Network fetch uses selected hosts, a project User-Agent, `maxlag=5`, serial reads,
one-second pacing, three-attempt backoff, numeric/HTTP-date Retry-After, maxlag
handling, 8 MiB response and 256-request/2,000-record batch limits. Missing-cache
reads require a known source-byte digest and actual pinned revision. Wrong
digests/revisions and oversized/error responses fail closed. Actual request URL,
headers, status, UTC time and digest are cached; no live downloads were needed.
HTTPX syntax/streaming/MockTransport documentation was consulted through
Context7 `/encode/httpx/0.28.1`.

Exact entity+milestone identities produce deterministic UUIDs, persistent source
aliases and merged citations/categories. Birth/death remain separate. Conflicting
years/retargeted identities quarantine; fuzzy wording detects suspicion but
never merges facts. Unresolved milestone leads have per-source quarantine IDs,
not invented exact milestone aliases. All original payloads retain signed time,
calendar, precision, rank, uncertainty, timezone, qualifiers and references.
BCE `-0001` remains source civil 1 BCE → canonical 0, and magnitude 490 → -489.
C2 independently checks source tokens; unsupported evidence produces no token.

Original event-specific milestone prompts use an English source label, or the
exact entity-linked article title when that label is absent. Answer-bearing
labels quarantine without erasure. Persistent workspace uses a POSIX writer
lock, immutable generations, fsynced files/directories and a single atomic
`current.json` commit pointer. Changed source payloads/evidence, taxonomy,
calendar-year context, policy or explicit adapter-rule version invalidate prior
checks. Unchanged retry preserves UUIDs and returns imported=0. Fetch/write
crashes before pointer commit leave the prior generation authoritative.

Both passed and failed C2 receipts have `stage='content'` and
`media_catalog_sha256=None`; no C3 pass is publication-ready. Raw-only failures
bind the canonical raw group digest rather than pretending to have an
EventRecord. `docs/operations/content-review.md` defines all generation files,
source snapshot digests and the C4/C5 handoff/revalidation boundary.

## Exact commands and TDD evidence

All `uv` commands below ran in the worktree's `backend/` directory.

1. Wrote the synthetic provider fixture and core importer/fetch tests **before**
   production code. Ran `uv run pytest tests/content/test_importer.py -q`:
   expected RED, exit 2, missing `app.content.adapters` at collection. This is
   the exact missing-adapter failure required by the brief, not a passing test.
2. Added adapter/base/selected and importer. Same command: GREEN, **14 passed**.
3. Supplemental transport/provider-slot, template, fuzzy duplicate, answer leak,
   persistent conflict and crash tests exercised already implemented paths.
   The revision-cache regression exposed writes occurring before revision
   verification: same command RED, **1 failed / 21 passed**, specifically
   `test_revision_slot_mismatch_never_gets_cached`. Moved verification before
   cache commit. Same command GREEN, **22 passed**.
4. Added taxonomy-invalidation and source-alias-retarget regressions first.
   Same command RED, **2 failed / 22 passed**:
   `test_taxonomy_change_invalidates_content_pass` and
   `test_retargeted_source_alias_quarantines_old_and_new_identity`.
   Root causes: unchanged-input short circuit omitted taxonomy, and alias
   retargeting only failed the new identity while the old alias group remained
   accepted. Bound taxonomy/current year in the fingerprint and quarantined
   both affected groups. Same command GREEN, **24 passed**.
5. Added unresolved-milestone alias regression before the correction. Same
   command RED, **1 failed / 24 passed**:
   `test_unresolved_milestones_do_not_create_exact_aliases`.
   Root cause: unsupported placeholder milestones were being grouped as exact
   identity. Required a supported milestone for quarantine identity grouping.
   Same command subsequently GREEN, **25 passed**.
6. Actual C1 sample investigation found `Q7186` had `labels={}` in original
   `raw/entities-00.json`, while the exact linked Wikipedia title existed.
   Added fallback-label behavior test first. Same command RED,
   **1 failed / 25 passed**:
   `test_missing_english_label_uses_exact_linked_article_title`.
   Used the exact linked provider title, not manufactured prose/evidence.
   Final same command GREEN, **26 passed**.

Supplemental tests covering existing implemented paths are characterization
coverage; this report does not falsely claim every individual test had an
independent red cycle. The core behavior had the required initial RED, and all
subsequent corrections above had targeted observed RED before implementation.

Additional exact commands:

- `uv run ruff check --fix app/content/adapters app/content/importer.py tests/content/test_importer.py`
  — two new-file import formatting findings corrected, no other files modified.
- `uv run ruff format app/content/adapters app/content/importer.py tests/content/test_importer.py`
  — formatting limited to task files.
- Initial `uv run mypy app` identified new-file Any/type-inference errors; these
  were corrected, not hidden or waived. An unused type-ignore was removed.
- Final `uv run pytest tests/content/test_importer.py -q` — **26 passed**.
- Final `uv run pytest tests/content tests/safety -q` — **163 passed**.
- Final `uv run bash scripts/lint.sh` — **mypy succeeds for 28 source files;
  ruff check passes; ruff format confirms 28 app files formatted**.
- Final `uv run ruff check tests/content/test_importer.py` — passes.
- `git diff --check` — passes before staging/commit.
- `PYTHONPATH=. uv run python ../.superpowers/sdd/2026-10-11-historical-date-game-beta/c3-evidence/reconcile.py`
  — real adapter + importer against original local C1 cache; assertions check
  all 128 dispositions, passed candidate/source receipts, passed-year agreement
  and imported=0 on retry. No network or DB access.

Both pytest suites show four pre-existing warnings: Starlette/httpx test-client
deprecation and default SECRET_KEY, POSTGRES_PASSWORD and
FIRST_SUPERUSER_PASSWORD warnings. They are not suppressed or described as clean
warning-free runs. The full DB integration suite was **not run**, as explicitly
requested with the stopped DB. C2's inherited content-only no-op DB fixture is
unchanged; safety tests verify destructive DB protection.

## Actual sample reconciliation (all 128 candidates)

Canonical, complete per-row evidence is
`c3-evidence/reconciliation.json`: **128 rows**, each original candidate ID,
title, research decision/year, actual content result/year, issue codes, private
identity/UUID, raw digest and provider-source digests. It does not promote
`ACCEPT_RESEARCH` to production approval. `c3-evidence/reconcile.py` is the
offline reproducible verifier; `c3-evidence/summary.json` records totals/digests.
The actual workspace is `c3-evidence/workspace-final-v3/`; older diagnostic
generations/workspaces are retained, not treated as authoritative or deleted.

| C1 disposition | Content pass | Machine quarantine |
| --- | ---: | ---: |
| ACCEPT_RESEARCH | 6 | 99 |
| QUARANTINE | 0 | 20 |
| REJECT | 0 | 2 |
| DUPLICATE | 0 | 1 |
| **Total** | **6** | **122** |

Fresh import: imported=6, quarantined=122, duplicates=0. Retry: imported=0.
Receipts: **6 passed / 122 failed**, all content-only and without media digests.
There are **zero passing-year disagreements**, zero promoted research
quarantines/rejections, and zero claimed game-ready/production approved events.

Passing rows, all with exact provider corroboration and unchanged audit years:

| ID | Exact milestone | Canonical year |
| --- | --- | ---: |
| C1-008 | Simón Bolívar birth | 1783 |
| C1-027 | Marie Curie death | 1934 |
| C1-028 | Frida Kahlo death | 1954 |
| C1-029 | Nelson Mandela death | 2013 |
| C1-030 | Mahatma Gandhi death | 1948 |
| C1-031 | Martin Luther King Jr. death | 1968 |

The initial diagnostic run passed five; investigating the real missing English
label and adding a tested exact linked-title rule raised this to six. No dates,
revision IDs or source evidence were supplied from the audit to raise the count.

Every biographical rejection is listed below. Abbreviations map exactly to
receipt codes: C=`conflicting_dates`, K=`unresolved_calendar`,
W=`unresolved_wikipedia_date`, Q=`unsupported_qualifiers`,
P=`unsupported_precision`. All retain their raw evidence; none enters a human
queue. Rows omitted from this rejection table are the six passes above.

| ID | Subject / milestone | Rejection codes |
| --- | --- | --- |
| C1-001 | Julius Caesar birth | C,K,W,Q |
| C1-002 | Confucius birth | C,K,W,Q |
| C1-003 | Murasaki Shikibu birth | C,K,W,Q,P |
| C1-004 | Ibn Battuta birth | K,W |
| C1-005 | Leonardo da Vinci birth | K |
| C1-006 | Akbar birth | K,W |
| C1-007 | Isaac Newton birth | C,K,W,Q |
| C1-009 | Charles Darwin birth | W |
| C1-010 | Rabindranath Tagore birth | W,Q |
| C1-011 | Marie Curie birth | W |
| C1-012 | Frida Kahlo birth | W |
| C1-013 | Nelson Mandela birth | Q |
| C1-014 | Katherine Johnson birth | W |
| C1-015 | Sukarno birth | W |
| C1-016 | Jacinda Ardern birth | W |
| C1-017 | Julius Caesar death | K,Q |
| C1-018 | Cleopatra death | K,W,Q |
| C1-019 | Genghis Khan death | K,W,Q |
| C1-020 | Ibn Battuta death | C,K,W,Q |
| C1-021 | Leonardo da Vinci death | K |
| C1-022 | Akbar death | W |
| C1-023 | Isaac Newton death | K,W,Q |
| C1-024 | Simón Bolívar death | Q |
| C1-025 | Charles Darwin death | Q |
| C1-026 | Rabindranath Tagore death | Q |
| C1-032 | Steve Irwin death | Q |

All **95** candidates in **C1-033–C1-096 and C1-098–C1-128** have exactly
`unsupported_milestone`: the C1 seeds are category/title research leads without
machine-readable event/milestone/edition scope. C1's narrowed research prompts
(dedication vs completion, patent vs inception, landing vs launch, battle end
vs start, specific publication editions) are not accepted as normalized source
facts. The legacy bridge does not guess those fields or copy audit years/prompts.
The new pinned-snapshot path supports ten explicit milestone/property rules;
future acquisition must supply those exact actual fields. This substantial
coverage limitation is explicit, not represented as a source-quality judgment
or a demonstrated scalable acceptance yield. Of these 95, **78** were research
accepts, 14 research quarantines, 2 research rejects, 1 research duplicate.

**C1-097** has `unresolved_identity`: the original seed's article was missing.
C1 separately fetched an alternate Columbus voyages article/chronology, but no
exact redirect/entity mapping resolves the original source key in this bridge.
The adapter does not manufacture that mapping from the research judgment.
This remaining research accept therefore stays quarantined. C1-107's Apollo
duplicate stays an independent unresolved quarantine record; it does not become
an accepted alias absent a resolved landing milestone.

Issue counts overlap: conflicting_dates=5, unresolved_calendar=13,
unresolved_wikipedia_date=18, unsupported_qualifiers=15,
unsupported_precision=1, unsupported_milestone=95, unresolved_identity=1.
Unsupported Julian/traditional dates, qualifiers and difficult introductory
parentheses are not silently converted or stripped to expand acceptance.

Evidence digests:

- Original audit SHA-256: `581dedd0ffcdbd494601e4122357c929c1609beb1829d7825f830533cafe7192`.
- Final snapshot/workspace input SHA-256: `ee79452f0d51ccc6d0729ff939bbe071b7ff7fcc86591e3de39a5b2535401ddc`.
- Final 128-row reconciliation SHA-256: `e94bc7617a996faf5b1cdfe2794bd7bf1dcceb4394e4aef430062bb104098b1f`.
- Current generation: `generations/ee79452f0d51ccc6d0729ff939bbe071b7ff7fcc86591e3de39a5b2535401ddc-20261012T040055523820`.

## Self-review and limitations

Checked the exact brief and constraints against acquisition, normalization,
deduplication, update/crash behavior, source tokens and the C4/C5 contract.
Self-review produced the targeted regressions and fixes recorded above; no
independent review is claimed. Controller review remains required.

Remaining deliberate limits: narrow deterministic wikitext/lifespan grammars;
all qualifiers/deprecated statements conservatively rejected; no Julian
conversion; no fuzzy merge; no non-biographical legacy milestone inference;
known-digest acquisition rather than live discovery; local POSIX single-writer
filesystem guarantees only; quadratic duplicate suspicion checking; no deletion
API or automatic orphan cleanup. Cache-only C1 claims lack entity revision IDs,
and cached extracts are not asserted to be oldid-pinned content. Exact response
digests/timestamps remain the support; no later probe revisions were retrofitted.
Wikipedia civil-year grammar is accepted only with exact Gregorian-family
Wikibase corroboration; original absent/annotated calendar evidence remains raw.

No promise is made about meeting 1,000 events, recognition, historical truth or
legal clearance. Six content-only passes are not a production catalog, do not
count toward the publication gate, and have no media checks/final receipts.

## Files and commit

Explicit task files only:

1. `backend/app/content/adapters/__init__.py`
2. `backend/app/content/adapters/base.py`
3. `backend/app/content/adapters/selected.py`
4. `backend/app/content/importer.py`
5. `backend/tests/content/test_importer.py`
6. `backend/tests/fixtures/content/source-snapshot.json`
7. `docs/operations/content-review.md`

Private task report/evidence remain in the ignored SDD workspace, including this
report, reconciliation script/results and generated import workspace. Raw C1
cache and C2 schemas/validation/fixtures were not modified. No external changes
were reverted and nothing was pushed/merged.

Scoped commit: `618bca1656b3f75f107e45101e1d21cf884ef4bc` (on the requested branch).
Commit message: `feat: import and reconcile historical source snapshots`.

Exact commit/confirmation commands from the worktree root:

```bash
git add -- backend/app/content/adapters/__init__.py backend/app/content/adapters/base.py backend/app/content/adapters/selected.py backend/app/content/importer.py backend/tests/content/test_importer.py backend/tests/fixtures/content/source-snapshot.json docs/operations/content-review.md
git diff --cached --check
git diff --cached --stat
git status --short
git commit -m "feat: import and reconcile historical source snapshots"
git rev-parse HEAD
git status --short
git show --format=fuller --stat --oneline HEAD
```

Commit confirms exactly the seven task files above (1,784 inserted lines); final
tracked/unignored worktree status is clean. The ignored report/evidence are
available locally at the paths stated above and are not application artifacts.

---

# C3 fix round 1/5 — review I1/I2/I3 and real eight-category paths

Base: `618bca1656b3f75f107e45101e1d21cf884ef4bc`. Same beta worktree/branch.
Read `task-C3-review.md` in full before changes. No subagents or manual content/
image approval queue. This appended section records the current fix status;
the original implementation/evidence above is retained as history, not rewritten.

## Fixes and root causes

**I1 — unresolved recovery/migration.** The old alias table treated an unresolved
quarantine placeholder as proven exact identity, preventing every later
promotion. New writes reserve aliases for normalized exact identities; unresolved
dispositions remain in raw/quarantine/decisions. Reading a base workspace removes
legacy `unresolved:` aliases during version-forced revalidation. New exact source
evidence under that same source key promotes to its deterministic canonical UUID
and updates aliases/receipts atomically. Proven exact→different exact retargeting
still quarantines both old/new groups, covered by the existing regression.
The new tests deliberately seed the exact legacy alias/state layout rather than
only exercising workspaces created by the new writer. The real reconciliation
also starts from a private exact copy of the base evidence workspace and verifies
that legacy placeholders are migrated without changing its original files.

**I2 — active infobox scope.** Whole-page field regex matching admitted comments,
unrelated examples and nested templates as evidence. Wikitext now uses a stable
AST parser: one supported **active outer infobox**, its own top-level parameters,
and an explicit infobox-type/field whitelist for the requested milestone.
Comments, nowiki/tag-wrapped examples, unrelated/nested templates, duplicate
fields or unsupported active markup cannot substantiate an event. Footnote refs/
comments are excluded as separators, never concatenated into invented raw year
tokens; original source bytes/fields remain unchanged. Parsing is bounded by
the existing 8 MiB input limit, a 16 KiB field limit and a 512-character finite
active date grammar. Date regexes are full matches against these bounded active
values, not unbounded searches through page text.

**I3 — actual precision agreement.** Year projection hid contradictory finer
claims. Normalization now compares **every pair** of dates at their common
supported semantic precision, across statements, providers and persistent
source aliases. A year-only source cannot conceal conflicting months/days in
other sources. Declared Wikibase precision limits filled placeholder dates.
Compatible aliases reduce candidate precision to the common minimum rather
than inheriting a falsely precise first candidate. Same-source raw date forms
with compatible reduced precision are not falsely labelled contradictory;
all acquisition payloads/digests remain preserved.

No C2 models or validation rules changed. A direct civil/ISO raw citation can
support its actual precision; English/date-template fields cite the literal
source year substring and cap the emitted EventRecord at **year**, after comparing
their full resolved components for conflicts. No invented ISO strings are used
as raw evidence. In this actual eight-category sample all eight emitted events
are therefore year precision, with C2 agreement and content-only receipts.
Spaceflight clocks require explicit source UTC instead of assuming a timezone.
`invention_year` cannot create a second `discovery` milestone for the same fact;
that unsupported selector quarantines. Final adapter fingerprint is
`selected-v6`, forcing invalidation/migration of prior content checks.

## Necessary parser dependency: verified current stable tooling

Added **only** `mwparserfromhell>=0.7.2,<0.8.0` plus its lock entry. A stable parser
is necessary to distinguish active templates/parameters, comments, tags and
nesting; an ad-hoc whole-page regex cannot satisfy I2. Context7 documentation
`/earwig/mwparserfromhell` was resolved/queried for `parse`, nonrecursive
`filter_templates(recursive=False)`, parameter and node APIs before use.
Read current `https://pypi.org/pypi/mwparserfromhell/json`: latest stable is
**0.7.2**, Requires-Python **>=3.9**, source archive SHA-256
`f4193072e9ea93b9e88f772f60a02125c0602d32890d0bbdcb275ed58c8b3763`.

`uv sync` built/installed 0.7.2 successfully on repository Python 3.15. Runtime
metadata verification reports version 0.7.2, Requires-Python >=3.9, package MIT
license metadata and native tokenizer enabled. A comment/top-level smoke probe
found exactly one active template. `git diff -- backend/pyproject.toml backend/uv.lock`
confirms the one dependency addition and no unrelated upgrades. This package
license check is not content rights/legal clearance. No other dependencies,
providers or model changes were added.

## Observed red/green regressions (before production corrections)

Commands ran in `backend/`. No network/DB in unit/mock tests; C2's inherited
content no-op DB fixture remains unchanged.

1. Wrote I1 recovery/migration, I2 inactive/nested scope, and I3 finer-date
   regressions first. `uv run pytest tests/content/test_importer.py -q`:
   **RED 11 failed / 27 passed**. Failures: two unresolved promotions, five
   inactive/unrelated/nested field cases, four intra-/cross-provider same-year
   day/month contradictions. The common-year precision positive passed.
2. After I1 alone:
   `uv run pytest tests/content/test_importer.py -q -k 'unresolved_alias_promotes or retargeted_source_alias'`
   — **GREEN 3 passed / 35 deselected**, including exact retarget protection.
3. After AST-scoped I2:
   `uv run pytest tests/content/test_importer.py -q -k 'inactive_or_unrelated or reimport_and_aliases or bce_magnitude'`
   — **GREEN 8 passed / 30 deselected**.
4. Added template-hidden day conflict before I3 fix:
   `uv run pytest tests/content/test_importer.py -q -k 'same_year_finer or date_template_cannot_hide or common_year_precision'`
   — **RED 5 failed / 1 passed / 33 deselected**. After full common-precision
   comparison, `uv run pytest tests/content/test_importer.py -q` — **39 passed**.
5. After reading actual source infobox structures, wrote synthetic envelopes
   modelling those attributed structures and conflict endpoint tests, before
   adding their grammars:
   `uv run pytest tests/content/test_importer.py -q -k 'evidenced_ordinary or conflict_date_field'`
   — **RED 12 failed / 45 deselected** (all eight ordinary category structures,
   plus four start/end/shared/cross-year endpoints). Added bounded AST date
   template/literal/range rules and explicit ordinary fields. Full focused suite
   — **GREEN 57 passed**; ambiguous/reversed/circa/calendar ranges quarantine.
6. Additional persistent precision/timezone regressions first:
   `uv run pytest tests/content/test_importer.py -q -k 'persistent_aliases_cannot or compatible_alias_dates or spaceflight_clock'`
   — **RED 3 failed / 57 deselected**. Fixed cross-alias day conflict concealment,
   common precision reduction and missing explicit UTC. Full focused suite
   — **GREEN 60 passed**.
7. Duplicate milestone selector guard:
   `uv run pytest tests/content/test_importer.py -q -k invention_field_is_not`
   — **RED 1 failed / 60 deselected**. Removed invention-field discovery alias
   interpretation. Full focused suite — **GREEN 61 passed**.
8. Raw token preservation guard:
   `uv run pytest tests/content/test_importer.py -q -k inactive_nodes_do_not`
   — **RED 2 failed / 61 deselected**. Excluded comments/refs as separators,
   never joining separated digits into manufactured raw dates. Final full
   focused suite — **GREEN 63 passed**.

Initial type checking exposed four new tuple/dictionary inference findings;
explicit internal annotations fixed them without ignoring errors. All TDD reds
above are expected observed behavior regressions, not hidden failures.

## Real eight-category provider evidence (10 authorized reads, no fabricated facts)

Only **10** read-only English Wikipedia Action API page requests were sent,
within the user's <=16 limit. All used saved C1 audit oldids, single `revids`,
`prop=revisions|pageprops`, `rvprop=ids|content`, `rvslots=main`, `maxlag=5`,
the approved identifying User-Agent, serial >=1-second pacing and byte bounds.
The private acquisition helper reserves every attempt in its ledger before
sending; it stops on any HTTP/API error rather than evading Retry-After/limits.
All ten returned success; no retry/429/maxlag was encountered. No new Wikidata
reads, new fact providers, broad acquisition or paid access were used.

Exact commands:

```bash
PYTHONPATH=. uv run python ../.superpowers/sdd/2026-10-11-historical-date-game-beta/c3-evidence/round1/acquire_pinned.py C1-008 C1-029 C1-048 C1-053 C1-069 C1-083 C1-106 C1-119
PYTHONPATH=. uv run python ../.superpowers/sdd/2026-10-11-historical-date-game-beta/c3-evidence/round1/acquire_pinned.py C1-062 C1-061
PYTHONPATH=. uv run python ../.superpowers/sdd/2026-10-11-historical-date-game-beta/c3-evidence/round1/verify_categories.py
PYTHONPATH=. uv run python ../.superpowers/sdd/2026-10-11-historical-date-game-beta/c3-evidence/round1/reconcile_round1.py
```

Actual raw responses, exact URLs/headers/status/retrieval times/digests and
request ledger are under `c3-evidence/round1/raw/` and `requests.jsonl`.
Original Wikidata response bytes/metadata are copied **byte-for-byte**, checked
against original C1 cache SHA-256s, not edited, normalized into fake evidence or
retrofitted with later revisions. Missing original entity lastrevids remain
missing. The new pinned Wikipedia data has its actual recorded oldid/content.
Selectors below come from the observed active infobox milestone field plus
the matching original Wikidata property, not a researched prompt/year.

| Category / ID | Subject / exact milestone | Actual Wikipedia oldid / active field | Original WD claim / supported comparison |
| --- | --- | --- | --- |
| births / C1-008 | Simón Bolívar birth | 1379420160, officeholder birth_date={{birth date|1783|7|24|df=y}} | P569, +1783-07-24, day agreement |
| deaths / C1-029 | Nelson Mandela death | 1379501484, officeholder death_date={{death date and age|2013|12|5|1918|7|18|df=y}} | P570, +2013-12-05, day agreement |
| battles / C1-048 | Battle of Midway start | 1377146774, military conflict date=4–{{start date and age|1942|06|7|df=y}} | P580, +1942-06-04, resolved start-day agreement |
| inventions / C1-061 | transistor invention | 1379214217, electronic component invention_year=1947 | P575, +1947-12-00, common year 1947 |
| literature / C1-069 | Pride and Prejudice publication | 1377221099, book release_date=28 January 1813 | P577, +1813-01-28, day agreement |
| arts / C1-083 | Guernica creation | 1377111816, artwork year=1937 | P571, +1937-01-01 with **year precision 9**, common year 1937 |
| exploration / C1-106 | Vostok 1 launch | 1373619528, spaceflight launch_date={{start-date|April 12, 1961, 06:07|timezone=yes}} plus explicit source UTC/ref | P619, +1961-04-12, date agreement in UTC |
| politics / C1-119 | Indonesian independence proclamation occurrence | 1377046708, event date={{Start date and age|1945|8|17|df=yes}} | P585, +1945-08-17, day agreement |

`category-evidence.json` retains every actual selected statement (full raw value,
rank, qualifiers, precision/calendar/references), parsed source parts, actual
citations/acquisition digests and unchanged research decision. The verifier
checks normalization/C2, all eight taxonomy categories, exact audit-year
agreement, candidate digests, eight content-only receipts and imported=0 retry.
**Eight pass / zero quarantine** for this explicit eight-row batch. This is
source-backed path evidence, **not** general coverage/quality/legal certainty
or publication approval. The transistor infobox's own name is Bipolar Junction
Transistor (BJT); that original infobox content is retained, not rewritten to
imply a separately resolved subtype milestone. The article/entity-linked
invention_year and original Q5339 claim agree at year precision only.

Unused probes are reported, not silently forced into acceptance:
ENIAC (C1-053, oldid 1379781502) has historic-site **built=1945**, not a supported
dedication field proving the original P1619 date in 1946. Shinkansen (C1-062,
oldid 1378729220) has no supported top-level infobox. Neither is used as the
inventions demonstration or supplied an invented field. Their original bytes
are retained. Other narrower/reserved grammar paths remain limited as documented;
unsupported sources quarantine, not route to humans.

## Reconciliation changes, all original 128 rows retained

Original C1 cache alone, revalidated with these fixes: **6 passes / 122
quarantines**, unchanged from base. Applying the eight actual pinned-field
updates under the same source keys gives **12 passes / 116 quarantines**:
the original six remain, and C1-048, C1-061, C1-069, C1-083, C1-106, C1-119
gain resolved source fields. C1-008 and C1-029 update provenance without changing
canonical identities/years. All existing passing UUIDs remain stable.

| Original research decision | Current content pass | Current quarantine |
| --- | ---: | ---: |
| ACCEPT_RESEARCH | 12 | 93 |
| QUARANTINE | 0 | 20 |
| REJECT | 0 | 2 |
| DUPLICATE | 0 | 1 |
| Total | 12 | 116 |

No research decision is relabelled, no audit file changed, and **zero passing
year disagreements**. The complete 128-row result is
`c3-evidence/round1/reconciliation.json`; current workspace is
`round1/workspace-reconciled/`, with **12 passed / 116 failed** content-only
receipts and no media catalog digest. Immediate retry imported=0, duplicates=0.
The baseline/updated comparison intentionally replays legacy input then stronger
source input: first copied-base replay imported=0, later replays imported=2
(two provenance reversions), and the stronger update imported=8 (two updated
passes plus six new passes). These are changed-candidate counts, not additional
new facts beyond the active total 12.

Unlike the original verifier, the new verifier recomputes actual bytes for
**22** provider-response digests and checks raw entity/page payload equality
against those exact provider envelopes, before checking all candidate/receipt/
raw/source bindings. It verifies old-placeholder migration from base state,
stable existing UUIDs and all current passed years. It does not claim independent
historical truth verification or treat the parser/source token itself as proof.

Final artifact SHA-256s:

- Category evidence: `e7447744cdec2216d77bcf61762767086fadf58dc79428fc33d26d7c729ed316`.
- Explicit pinned-field snapshot: `0487746e8defa9e3117cc2a2f15fa21b8c152dc57462bb90e9ebf633f688b139`.
- 128-row reconciliation: `056d9f56b55f11672600e582cf316c457cd32d4c78f63aac3976680c161ae4ab`.
- Current complete-workspace input fingerprint: `db2dfc3499a345468704b0112c7f3ef90851cdd68be7691fe0b94b21d011bcd2`.

## Final checks, scope, self-review and commit

Exact final checks:

```bash
uv sync
uv run ruff format app/content/adapters/selected.py app/content/importer.py tests/content/test_importer.py
uv run pytest tests/content/test_importer.py -q
uv run pytest tests/content tests/safety -q
uv run bash scripts/lint.sh
uv run ruff check tests/content/test_importer.py
git diff --check
```

Final results: **63 focused importer tests pass; 200 content+safety tests pass;
mypy passes for 28 app source files; ruff check passes; all 28 app files satisfy
ruff format; importer test lint passes; git diff check passes**. Four inherited
pytest warnings remain (Starlette/httpx deprecation and three default credential
warnings). No full integration tests with the stopped DB were run. All unit/mock
tests are network/DB-free. New structural fixtures are explicitly synthetic,
attributed to observed actual source revisions, not edited live evidence.

Self-review checked recovery migration versus protected exact identities,
active AST scopes, finite date grammar/UTC, raw source token preservation,
pairwise precision/alias comparison and truthful year caps; it produced the
additional observed-red regressions above. Checked dependency diff for scope,
all eight actual paths, source byte/receipt bindings and old/new sample counts.
No independent reviewer approval or historical/legal/quality guarantee claimed.
Controller review remains pending. No C4/C5 behavior was added.

Remaining limits: finite known infobox/template grammars, conservative rejection
of qualifiers/deprecated/Julian/ambiguous dates, year-capped English/template
citations, cache-only original entity revisions, no human queue, no deletion API,
local POSIX writer guarantee and quadratic fuzzy suspicion checking. This does
not meet or claim the final 1,000-event production gate; all 12 passes are
content-only, without media or final publication receipts.

Scoped changed files (only these enter the fix commit):

1. `backend/app/content/adapters/selected.py`
2. `backend/app/content/importer.py`
3. `backend/tests/content/test_importer.py`
4. `backend/tests/fixtures/content/selected-provider-fields.json`
5. `backend/pyproject.toml` (necessary stable AST parser)
6. `backend/uv.lock` (only that dependency addition)
7. `docs/operations/content-review.md`

Private ignored scripts, raw responses, ledgers, verification summaries,
workspaces and this report stay under the beta SDD directory. Original C1 raw
cache/audit, C2 models/validator and other user work were not modified.

Fix commit: `73c042af0259c65ce6de0fff92d8c4bda4289aeb`.
Message: `fix: resolve scoped milestone dates and recover imports`.

Exact root-directory staging/commit confirmations:

```bash
git add -- backend/app/content/adapters/selected.py backend/app/content/importer.py backend/tests/content/test_importer.py backend/tests/fixtures/content/selected-provider-fields.json backend/pyproject.toml backend/uv.lock docs/operations/content-review.md
git diff --cached --check
git diff --cached --stat
git status --short
git commit -m "fix: resolve scoped milestone dates and recover imports"
git rev-parse HEAD
git status --short
git show --stat --oneline HEAD
```

Commit confirms exactly seven scoped files (784 insertions, 57 deletions).
Final tracked/unignored worktree status is clean; private report/evidence remain
locally available and ignored. No push, merge or unrelated file changes.

---

# C3 narrow fix round 2/5 — rereview Important R1

Base: `73c042af0259c65ce6de0fff92d8c4bda4289aeb`, same beta worktree/branch.
Read `task-C3-rereview-1.md` in full. Scope is only the duplicate/blank parameter
breakage, its regressions and necessary operational/disclaimer documentation.
No subagents, HTTP requests, dependencies, categories, schemas, importer redesign,
media/publisher/game changes or unrelated fixes.

## Root cause and correction

The supported outer-infobox extractor discarded a relevant parameter when
`str(param.value).strip()` was empty, then checked the remaining values for
uniqueness. Thus both `birth_date=1800` followed by an empty override and the
reverse ordering could incorrectly pass as a single source assertion.

The adapter now collects **all matching top-level parameter occurrences**,
including empty/whitespace/comment-only ones, checks that exactly one exists,
and only then selects/strips/cleans that single parameter's value. Multiple
occurrences quarantine conservatively in either order; no Wikipedia override
resolution is guessed. Original source text is preserved and failed receipts
remain failed content-only decisions. A single valid field still passes.

## Exact observed red/green evidence

Wrote regressions before editing production code:

- Six parameterized cases: empty, whitespace-only and comment-only duplicates,
  each before and after the valid field. Each asserts quarantine, absence from
  candidates, failed receipt and unchanged original raw wikitext.
- One positive case: a single valid birth_date still yields the correct year
  and a passed content receipt.

Command from `backend/`:

```bash
uv run pytest tests/content/test_importer.py -q -k 'duplicate_infobox_field or single_valid_infobox_field'
```

Before correction: **RED — 4 failed / 3 passed / 63 deselected**. The four
empty/whitespace cases reproduced R1 in both orderings, returning imported=1
instead of quarantine. The two comment-only duplicates already rejected under
the base implementation and remain explicit regression coverage; the single
valid field also already passed. This report does not claim those three cases
had an independent failing state.

After the occurrence-count correction, the identical command: **GREEN —
7 passed / 63 deselected**. No alternate evidence, field interpretation or
model/dependency changes were needed.

## Final verification and commands

```bash
uv run ruff format app/content/adapters/selected.py tests/content/test_importer.py
uv run pytest tests/content/test_importer.py -q
uv run pytest tests/content tests/safety -q
uv run bash scripts/lint.sh
uv run ruff check tests/content/test_importer.py
git diff --check
git diff --stat
git status --short
```

Final results: **70 importer tests passed; 207 content+safety tests passed;
mypy succeeded for 28 source files; app/test ruff checks passed; all 28 app files
passed format check; git diff check passed**. The same four inherited warnings
remain (Starlette/httpx deprecation and three default credential warnings).
No full integration suite with the stopped DB and no network acquisition ran.
The retained real-source cache/category artifacts were not edited or regenerated;
no new real-category or historical-equivalence claims are made in this round.

## Concerns and truthful interpretation

The actual transistor infobox names **Bipolar Junction Transistor (BJT)** while
the article/entity is general transistor **Q5339**. Its source field is only a
demonstration of the supported invention_year grammar, **not production-approved
historical equivalence** between subtype/general-entity milestones or a resolved
separate BJT identity. This is now explicit in the operations document as well
as the retained round1 report; no resolution was guessed.

Per narrow scope, the importer/fingerprint implementation is unchanged. Its
unchanged-input fast path does not re-run normalization on stored old decisions.
After deploying this parser correction, old decisions must be revalidated using
a fresh private workspace (or an authorized adapter-fingerprint update), not
carried forward as old passes. The operations document explicitly records this
existing operational constraint; automatic cache/version redesign is not claimed
as part of this three-file fix. C3 receipts remain content-only and never satisfy
publication approval by themselves.

## Files and commit

Only these files are included:

1. `backend/app/content/adapters/selected.py`
2. `backend/tests/content/test_importer.py`
3. `docs/operations/content-review.md`

Diff: **61 insertions / 6 deletions across three files**. The task report remains
private/ignored. No changes to source evidence, dependencies, importer, categories,
schemas or other user work. Self-review confirmed the count happens before any
value cleanup and both parameter orderings are covered. Controller review remains
pending; no historical/legal/quality guarantee or human approval queue is added.

Fix commit: `e654bd388b97e8a210f101676031b5ebe990de94`.
Message: `fix: quarantine blank duplicate milestone fields`.

Exact root-directory commit/confirmation commands:

```bash
git add -- backend/app/content/adapters/selected.py backend/tests/content/test_importer.py docs/operations/content-review.md
git diff --cached --check
git diff --cached --stat
git status --short
git commit -m "fix: quarantine blank duplicate milestone fields"
git rev-parse HEAD
git status --short
git show --stat --oneline HEAD
```

The commit contains only those three scoped files; tracked/unignored worktree
status is clean. The appended report remains ignored/local; no push or merge.

---

# C3 round2 completion — automatic invalidation of cached v6 passes

Base: `e654bd388b97e8a210f101676031b5ebe990de94`. This completes the same R1 fix,
superseding the previous round2 cached-decision limitation: **a fresh workspace
is no longer required to revalidate v6 decisions**. No network, subagents, new
dependencies, categories or broad redesign.

## Observed red/green before fingerprint correction

Added `test_v6_cached_duplicate_pass_revalidates_then_retry_retains_quarantine`
before changing the importer version. Its explicitly synthetic legacy fixture:

1. Stores the original duplicate/blank source field and exact source snapshot
   bytes, including `birth_date=1800` followed by `birth_date=`.
2. Reproduces only the old empty-value filter during fixture normalization to
   create the previous passing candidate/content receipt; original acquisition
   bytes and retained raw payload are not changed.
3. Independently hashes the literal historical `selected-v6` input schema and
   seeds that previous workspace state/pointer. It does not derive the expected
   old fingerprint from the current production rule version.
4. Runs the real current adapter/importer against the **same raw snapshot**,
   without the legacy fixture filter, and requires automatic quarantine.

Exact targeted command from `backend/`:

```bash
uv run pytest tests/content/test_importer.py -q -k v6_cached_duplicate_pass
```

Before fingerprint change: **RED — 1 failed / 70 deselected**. The unchanged
v6 fingerprint took the fast path and returned `(imported=0, quarantined=0)`
instead of `(0,1)`, leaving the old passed decision in place.

Changed the importer input fingerprint from **selected-v6 to selected-v7**,
with a local reminder to bump it alongside normalization fixes. No extra version
framework or private constant is necessary for the single existing literal.

Identical targeted command after bump: **GREEN — 1 passed / 70 deselected**.
The regression verifies that the pass is removed, the old canonical UUID is
retained in quarantine, a failed content-only receipt replaces the old pass,
and the input fingerprint changes. The next unchanged retry returns imported=0
and quarantined=1, retaining the same generation pointer and failed receipt.
All original snapshot bytes remain byte-for-byte unchanged.

## Final verification

Exact commands:

```bash
uv run ruff format app/content/importer.py tests/content/test_importer.py
uv run pytest tests/content/test_importer.py -q
uv run pytest tests/content tests/safety -q
uv run bash scripts/lint.sh
uv run ruff check tests/content/test_importer.py
git diff --check
git diff --stat
git status --short
```

Results: **71 importer tests passed; 208 content+safety tests passed; mypy passed
for 28 source files; app/test ruff checks passed; all 28 app source files passed
format check; git diff check passed**. The four inherited pytest warnings remain
unchanged and unsuppressed. No DB integration suite, network, new source evidence
or source-category acquisition/reconciliation scripts ran in this completion.

Operations docs now describe automatic selected-v6→selected-v7 revalidation and
the unchanged retry retaining quarantine. The existing transistor/BJT caveat is
unchanged: its field remains a grammar demonstration, not production-approved
historical subtype/general-entity equivalence or a guessed resolution. All C3
receipts still remain content-only, not publication acceptance.

## Scope and commit record

Scoped application/document changes:

- `backend/app/content/importer.py` — one fingerprint bump and explanatory comment.
- `backend/tests/content/test_importer.py` — previous-v6 pass/retry regression.
- `docs/operations/content-review.md` — current fingerprint/revalidation behavior.
- `.superpowers/sdd/2026-10-11-historical-date-game-beta/task-C3-report.md` — this appended record and retained historical task report.

The three application/operations files change by **86 insertions / 2 deletions**.
Per the explicit completion request to commit importer/tests/docs/report, the
previously ignored report is included in this completion commit. Earlier report
sections describing it as ignored/private record their historical state; the raw
responses, private workspaces, scripts and ledgers remain ignored and uncommitted.
No source evidence, dependencies, model contracts or other user work changed.

Completion commit message: `fix: invalidate cached v6 content decisions`.
Its commit identity is recorded by repository metadata and the controller
handoff, rather than a self-referential SHA inside this versioned report.
Exact scoped root-directory staging/commit commands:

```bash
git add -- backend/app/content/importer.py backend/tests/content/test_importer.py docs/operations/content-review.md
git add -f -- .superpowers/sdd/2026-10-11-historical-date-game-beta/task-C3-report.md
git diff --cached --check
git diff --cached --stat
git commit -m "fix: invalidate cached v6 content decisions"
git rev-parse HEAD
git status --short
git show --stat --oneline HEAD
```

No push or merge. Controller review remains pending; no human review queue or
historical/legal/quality guarantee is introduced.
