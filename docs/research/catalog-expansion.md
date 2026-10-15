# Catalog expansion — bounded F3 evidence

Measured 2026-10-12 against `c3a07ac`. **Research complete; expansion BLOCKED
pending source/date-contract review and acquisition access.** The existing
1,276-event catalog remains usable locally. No adapter, policy, DB, service, UI,
media assignment or release was changed; no release was published or promoted.
There was no human fact/image curation or legal clearance.

## Reconciled baseline

Selected release: `data/game/releases/jsonl-trial-2026-10-12-review-r1/`;
manifest SHA-256
`804ec52ccfc3e19cd955913b05cbfd59158f562408e45c1916fa8626d3ac50d3`.
An offline whole-raw normalization, once for the baseline, independently reproduces
**1,276 accepted / 18,589 quarantined from 19,865 raw candidates**. All 27
manifest-bound files, pinned chronology bytes, eight fallback assets, prior
first-100/all-event audits and current 1,276 whole-raw content rechecks reconcile.
Stored pass flags do not establish eligibility.

| Category | Accepted | New 100-identity media sample |
| --- | ---: | ---: |
| births | 5 | 5 |
| deaths | 171 | 14 |
| battles | 544 | 14 |
| inventions | 23 | 14 |
| literature | 65 | 14 |
| arts | 32 | 13 |
| exploration | 145 | 13 |
| politics | 291 | 13 |

- **569 distinct years, 9–2025 CE; BCE 0**. Ancient/medieval/early-modern/modern/
  contemporary counts: **17/274/214/437/334** (boundaries 500/1500/1800/1946).
- **1,271 region-unclassified** chronology events. Five inherited birth seed
  labels contribute one each to Europe, Latin America, North America, Oceania
  and Southeast Asia; these are not new inferred geographic facts.
- Daily union: **1,003 events / 492 years**; full-range greedy capacities at
  integer gaps 1/5/10/25/50: **492/194/116/59/34**. No narrow-bound guarantee.
- **0 usable external images / 1,276 fallbacks**; eight original CC0 SVGs,
  **5,431 bytes**. Thin categories, absent BCE and regional gaps remain limitations.
- Raw reason counts: unresolved category 17,897; contradictory contextual year
  203; uncertain text 246; suspected duplicates 33; unsafe prompts 16; answer
  leaks 14; unselected demo/future/synthetic inputs 180.

## Three routes, evaluated in order

### 1. Genuine approved Wikidata/Wikipedia caches

The unchanged `SelectedSourceAdapter` and whole-raw constraints independently
recheck the inherited caches, not C1 research judgments:

| Cache | Raw | Passing identities | Quarantined identities | Identity delta vs baseline |
| --- | ---: | ---: | ---: | ---: |
| C1 legacy cache | 128 | 6 (1 birth, 5 deaths) | 122 | 5 deaths |
| C6 pinned pilot | 63 | 22 | 41 | 17 nonbirth identities |

C6 passing category memberships: births 5, deaths 3, battles 5, inventions 0,
literature 2, arts 3, exploration 1, politics 3. Its five births already exist
in the baseline. **Additional passing births/inventions/BCE: 0** in either cache.
C1/C6 identity deltas overlap and are **not net new deduplicated historical facts**:
different provider identities may describe existing chronology milestones.
They were not combined, imported or counted toward a new release. Date qualifiers,
unsupported fields/calendars, conflicts and precision failures remain quarantines.
Old entity responses without revisions remain old responses; no revision or
Wikidata field was fabricated. The general-transistor/BJT exclusion stands.

### 2. Additional conservative chronology action grammars

The exact pinned positive-CE-only JSONL supplies **15 lexical hits** for narrowly
specified patent grants, film releases and first opera performances. A conservative
documentary screen leaves **13 leads: 5 inventions / 8 arts**, excluding one
multi-sentence film row and one patent row with a later second milestone.
Initial 14-lead output is retained privately and superseded by that refinement.
**New accepted events: 0; subject-image associations: 0.** Full-corpus ambiguity,
deduplication and independent late gates have not been run under proposed rules.

Source-backed examples retained with row hashes: line 2640, John Greenough's
patent grant; line 523, *Metropolis* release; line 19264, *Hansel and Gretel* first
performance. Negative examples: line 4702, Daimler's later motorcycle narrative;
line 8475, multi-sentence *Cleopatra* release; line 737, letters patent; line 4254,
colonization patent. The proposed milestone is **patent grant**, not proof of an
invention's origin date. Bare topic keywords, patent applications, dates in prose,
negations, retroactive/future actions and existing failures cannot establish it.
Any grammar change requires its own reviewed tests/fingerprint change. It cannot
manufacture births, BCE, regions or article/image provenance from this snapshot.

### 3. Official selected-page XML exports

Cached C1 `October 12` wikitext first supplied 129 linked-year-prefix birth leads
and two BCE rows; its response has **no pinned parse revision** and remains
discovery only. The cached world-history page is an index, not an event dataset.
Then **one** public, serial, identifying-UA Action API GET exported the current
revisions of `October 12` and `Timeline of ancient history`, retaining original
XML plus URL/status/all response headers, timestamp and actual payload digest.

- Endpoint: `https://en.wikipedia.org/w/api.php`; parameters `action=query`,
  `titles=October 12|Timeline of ancient history`, `export=1`, `exportnowrap=1`,
  `format=json`, `formatversion=2`, **`maxlag=5`**. Response was XML, not JSON.
- **HTTP 200**, no API error or Retry-After, **137,326 bytes**, SHA-256
  `29fa4af25b427ba0505b0f4bf3339213bdb810da047279d684a3acdb5890b0cd`.
- `October 12`: page 22530, revision **1379933667**; 456 screened chronology
  bullets with exact year prefixes, including 256 birth rows and two BCE rows.
  **253 distinct leading linked birth subjects** survive the structural screen;
  three answer-bearing disambiguation targets do not. 204 exact-prefix years.
- `Timeline of ancient history`: page 17255423, revision **1378663587**; 262
  bullets, 140 exact-prefix rows (130 BCE), **128 structurally unblocked leads
  (118 BCE)**, 120 exact-prefix years. Range/circa prefixes, unresolved templates,
  uncertain bodies and missing links remain explicit blockers (overlapping reasons).
  Most leads lack an eligible category/action; all regions remain unclassified.

These are **source/discovery and structural-screen counts**, not accepted facts,
cross-source deduplication, corroborated calendars or rights-cleared pictures.
Linked titles are real source targets, **not yet pinned target article IDs/QIDs**.
Ancient exact-looking prefixes are not an automatic truth guarantee. Neither export
is supported acceptance input for the current adapters. No full dump, 35 GiB
download, third-party source, query-service bypass or endpoint rotation was used.

## Exact matching and picture feasibility

Use taxonomy-order category round-robin queues sorted by event UUID; skip seen
IDs and exhausted queues until 100 distinct identities. All five births are real;
no replacement fillers. The table above records the actual sample.

- **Exact subject identities: 5/100; unknown subjects: 95/100**. A calendar-page
  citation is not an exact event/subject article association.
- **Exact source-P18 file candidates: 2/100**, both matched to retained original
  Commons payload hashes. Three exact birth subjects lack supported P18 candidates.
- Existing C4 candidate/credit checks reproduce **two
  `unsafe_required_credit_link` failures**. Both claim public domain, but neither
  is a safe usable image; one also contains territorial-rights ambiguity.
- **Usable images 0/100; needed fallbacks 100/100**. No original/thumbnail download
  or new Commons lookup; downstream byte checks were not reached for failed files.
  The new export adds **zero sample matches**: no sampled chronology row cites
  October 12. No fuzzy/prose/title search joins were attempted.

The historical C1 image-screen percentages are not production acceptance yields.
Retain mandatory credits; do not remove unsafe credit links or dates to force a
pass. Existing C4 rights/relevance/safety/byte gates and immutable C5 verification
remain required; unknown/unsafe media use meaningful fallbacks.

## Source access, rights and next approval

Before the live read, checked digest-backed Wikimedia rate guidance and inherited
provider status: serial traffic, identifying UA, at most three concurrent requests,
respect Retry-After/maxlag. This probe used **one request, zero retries**, 30-second
timeout and 2 MiB response ceiling. Wikidata's recorded six maxlag failures and
Commons' two historical 429s were **not retried or cleared**. Three inherited
HTTP-200 maxlag bodies and Retry-After headers remain accessible; historical
Commons failure bodies/headers are incomplete evidence, not retrofitted receipts.
The corrected provider-wide stop regressions now pass; absence of a local stop
file is not permission to evade a provider's earlier stop. No access window promised.

Source text reuse remains Wikipedia-contributor **CC BY-SA 4.0**, with article
revision/history attribution, license link, adaptations marked and separate MIT
application/image licenses. Structured Wikidata claims are CC0; each Commons
file needs separate supported rights, creator/credit, safety and exact relevance.
Cached terms support this proposal, not legal certification. Source access cost
**$0**; download runtime 1.239 s, baseline offline audit 10.529 s. Engineering,
storage and maintenance are not free-effort claims.

**Next owner choice:** approve a bounded XML-discovery producer feeding unchanged
selected-source date checks after provider readiness, or explicitly review a new
reported-civil-year Wikipedia chronology contract for births/BCE. The latter is
not implicitly covered by the positive-CE JSONL approval. The preferred immediate
continuation is discovery-only; direct XML acceptance stays blocked. Narrow
JSONL grammar work is a separately reviewable small extension, not a substitute
for missing BCE/birth/image evidence. No producer/adapter implementation is
authorized by this research result.

Private selected proposal, exact format/IDs/calendar/dedup/rights/gates/regressions
and bounded acquisition command:
`.superpowers/sdd/2026-10-12-historical-date-game-beta-followup/F3-continuation/selected-expansion-brief.md`.
Full report: same directory's `task-F3-report.md`; retained evidence/scripts:
`data/game/acquisition/followup-probe/`. Inherited C1/C6/JSONL evidence was read,
not edited. The named pure content regressions pass **366 tests, four existing
warnings**; no backend-wide/DB suite or service operation was run.
