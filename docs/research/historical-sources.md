# Historical fact sources — selected automated-only policy

**Research/retrieval date: 2026-10-12. Policy finalized: 2026-10-12. Status: SELECTED; user-approved automated-only policy `automated-v1`.**

Select `wikidata` + `wikipedia_en` for structured discovery and revision-pinned deterministic milestone/year resolution. Use original deterministic source-backed prompt templates or properly licensed text with its obligations; quarantine unresolved disputes instead of a human approval queue. Retain **all eight** master categories: births, deaths, battles, inventions, literature, arts, exploration, politics. The user explicitly approved these sources, Commons/fallback policy and fixed Daily categories with **no manual content/image review**. The unchanged four-field [selection](source-selection.json) records those choices. C1 finalizes policy only; adapters, machine receipts and publication checks belong to C2–C5. No production catalog is created here.

## Binding automated-only policy — verbatim approved amendment

1. No human fact/prompt/image approval queue, manual pilot, commissioned art,
   paid curation, compulsory specialist checks, or human recognition study.
   Remove active 394–792-hour/$11.8k–$47.5k budgets and 400-candidate/20–30-tester
   proposals from the selected beta path; describe old figures only as superseded
   optional manual-process estimates, not a new commitment or zero-effort promise.
2. Original deterministic source-backed prompt templates or properly licensed
   text with obligations. Keep provenance; do not claim human-verified truth or
   legal clearance. Names/descriptions cannot disclose the unanswered year.
3. Exact, deterministic milestone/year resolution only. Quarantine circa/ranges,
   conflicting unsupported calendars/years, ambiguous fuzzy duplicates and
   answer leaks instead of asking a person or guessing. Exact source entity plus
   milestone identity can merge sources; births/deaths stay separate.
4. Machine metadata/licensing checks for Commons origin and supported per-file
   rights, credit/adaptation permissions, relevance and safety. Missing/unknown/
   incompatible/territorial-only rights or risky text-heavy/date-bearing imagery
   use meaningful original SVG fallbacks. No blanket Commons rights assumption.
   Do not add NASA/Met/Smithsonian to selected core or expand download hosts.
5. Machine acceptance must emit versioned digest-bound receipts; changing status
   to approved is not publication validation. The master contract retains
   `review_status` but defines approved as machine-validated. New ValidationReceipt
   and automated-v1 policy are implemented in C2-C5, not in this documentation task.
6. At least 1,000 real unique accepted events still required; fixtures/research
   screens/raw leads do not count. Preserve broad eight-category coverage and
   coverage/difficulty heuristics as reports, without invented quality guarantees.
7. Fixed Daily categories remain battles, inventions, exploration, politics;
   shared seed per UTC date unchanged. No paid access, provisioning, merge/push,
   or application/dependency changes in this task.

## Evidence and reproducibility

[source-audit.csv](source-audit.csv) contains **128 actually retrieved candidates**, 16 primary-category candidates each. Every row records source/record IDs, article revision, region/era, raw date statements and qualifiers, reference counts, prompt, recognition/difficulty, duplicate judgment, image attempt/rights/relevance, decision, and fallback rationale. `ACCEPT_RESEARCH` means **AI research-screened fact candidate**, not completed human curation, legal clearance, or game-ready acceptance. All original dispositions and historical pending-human-review labels remain intact as research evidence, **not an active approval queue**. The 105 screens have no new machine acceptance receipts and do not count toward the final 1,000-event gate. `record_id` is a research key, not a future production identifier.

The full evidence index, exact response URLs/timestamps/digests, contact sheets, and verification results are in `.superpowers/sdd/2026-10-11-historical-date-game-beta/task-C1-report.md`. Raw evidence and report-only scripts are retained in the approved beta worktree's ignored `.superpowers/sdd/2026-10-11-historical-date-game-beta/c1-evidence/`; CSV `evidence_files` paths are relative to that local directory. The generator and verifier resolve this worktree from their own location, with no external-checkout evidence dependency. Evidence is **not** shipped with the four research files alone; archive/share the indexed local evidence before a cross-checkout handoff. The report records the preserved original copy separately for controller-directed cleanup.

## Current source/access/rights comparison

All linked terms below were retrieved on 2026-10-12; saved responses, not remembered license assumptions, underpin this comparison.

| Source or combination | Access and current rights evidence | Precision, coverage and decision |
| --- | --- | --- |
| Wikidata alone (structured knowledge base) | [Data access](https://www.wikidata.org/wiki/Wikidata:Data_access): structured data is CC0; read-only Action API `wbgetentities`, SPARQL discovery, and downloadable dumps. No account/key used. Keep source IDs and provenance although CC0 does not require attribution. Do not assume referenced books or linked media are CC0. | Broad coverage and explicit precision/calendars/qualifiers, but missing event-specific dates, contradictory claims, and inception/publication confusion. Reject as sole automatic acceptance source. |
| **Wikidata + English Wikipedia articles/open chronologies** | [Wikimedia terms §7](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use): applicable Wikipedia text reuse is CC BY-SA 4.0 with attribution, license notice, change marking, and share-alike where required; some imported text has additional provenance conditions. Read-only Action API article extracts/revisions and parsed chronologies; [October 12](https://en.wikipedia.org/wiki/October_12), [world-history timeline](https://en.wikipedia.org/wiki/Timeline_of_world_history), and the Wikimedia on-this-day feed were actually retrieved. These are **not independent sources from Wikidata** merely because they are separate endpoints. | Selected for discovery and deterministic prompt-specific year checking, not blindly joining a lead sentence and preferred claim. Original source-backed templates avoid bulk copied prose but do not assert legal clearance; retain article/revision attribution and enforce applicable text obligations. Do not redistribute article extracts as unlicensed original content. |
| Met Open Access + Wikimedia (specialist art dataset) | [Official repository/terms](https://github.com/metmuseum/openaccess), [API documentation](https://metmuseum.github.io/): selected metadata CC0, unrestricted commercial/noncommercial reuse; API needs no signup/key, documented maximum **80 requests/second**. Prefer bounded serial reads or pinned bulk metadata; images are explicitly separate from the CSV license. Cite museum/object and mark modifications; no endorsement. | Adds collection-specific dates and art coverage, not births/battles/politics. Three actual object responses were inspected. Great Wave object 45434 says `ca. 1830–32`, while numeric bounds are 1820–1842: neither yields a defensible exact year. Object 45734 (Quail and Millet) says late 17th century / 1667–1682. Object 437133 actually returned Monet's *Garden at Sainte-Adresse*, 1867, non-PD/no image; do not trust a documentation example as a current result. Useful later supplement, **not selected core**. |
| NASA histories + Wikimedia (specialist chronology/corroboration) | [Apollo 11 overview](https://www.nasa.gov/history/apollo-11-mission-overview/), [Shepard anniversary history](https://www.nasa.gov/history/60-years-ago-alan-shepard-becomes-the-first-american-in-space/), [notices](https://www.nasa.gov/nasa-web-privacy-policy-and-important-notices/), [media rules](https://www.nasa.gov/nasa-brand-center/images-and-media/). Public pages read without credentials; no general bulk-page quota established here, so serial bounded access only. Government-created material is generally not copyrighted in the US, but third-party material is not thereby cleared. | Independently corroborates Apollo/Gagarin milestones; much narrower, US/space-centric coverage. Human editorial sourcing and factual source disclosure must be distinguished from restricted AI-output attribution, as quoted below; neither bulk prose redistribution nor blanket CC0 is assumed. Not selected core. |
| Smithsonian Open Access + Wikimedia (alternative museum metadata) | [Official repository](https://github.com/Smithsonian/OpenAccess) documents line-delimited metadata, unit buckets and a move from GitHub archives to public AWS distribution. Official FAQ returned **403**; current rights exceptions and API quotas were not verified sufficiently. No signup/key request or provisioning attempted. | Plausible arts/objects/US-history supplement; no record sample or usable yield claimed. The stated millions of metadata records are not exact-year events. Defer selection until current terms and per-record rights are retrieved successfully. |

### NASA AI-attribution boundary — saved official policy

The saved `raw/terms-nasa.html` states at line 1671 that NASA cannot verify information incorporated into a large language model and that “attribution of the information directly to NASA is not permitted.” Line 1675 distinguishes **factual source disclosure**: “As a statement of fact, you can acknowledge your AI tool includes NASA source material, but do not imply any review or permission was granted by NASA for its specific use.” Line 1683 states: “All outputs from the AI model should be attributed to the AI product itself, not NASA.” It further specifies: "References like “according to NASA” or similar are prohibited in AI products."

For the historical terms comparison, **human editorial sourcing** means an editor checks an original source and documents that source; it is distinct from **AI-output attribution** or a factual disclosure of a tool's inputs. Citations here identify saved pages consulted, not NASA authorship, verification, endorsement or permission for this AI research-screened report. A hypothetical human-written route might fall outside the AI-output restriction, but human review alone must not be assumed to remove it. Future direct NASA adoption would require a separate scope/rights decision, potentially **owner/legal review**; this is not a gate in the selected automated-only path. NASA remains unselected. Do not attribute generated output to NASA or assume a Commons copy removes these restrictions; quarantine/fall back on unresolved rights rather than seek human clearance. No legal clearance is asserted.

### Rate and operational policy

[Current Wikimedia limits](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits) document 10 requests/minute for unidentified traffic, 200/minute for compliant User-Agent-only unauthenticated bots, and at most three concurrent requests. Limits can change and API-specific limits also apply. This audit used serial GETs, an identifying project User-Agent, `maxlag=5` on Action API requests, ≥1-second pauses, caching, and a stop on HTTP 429. Later acquisition must honor `Retry-After` and maxlag errors, back off, and not evade limits with credentials/IP rotation. Feed/SPARQL/bulk services require their own current operational checks; the 200/minute figure is not a guarantee for every endpoint. No paid services or applications were provisioned.

## Audit method and observed results

Sampling was **purposive and stratified**, not random: a fixed `seeds.tsv` of 16 recognizable or deliberately problematic subjects per category, spanning eras and regions, including negative precision and duplicate cases. Seeds were chosen before the bounded retrieval; this is not an exhaustive scan of the discovery reservoirs. Article introductory extracts, all relevant Wikidata time claims/qualifiers/reference counts, and image metadata were retrieved; discovery chronology pages additionally supplied wikitext. Retrieved prose and eight visual contact sheets were inspected; uncertain prompts were narrowed or quarantined. This was not a full-article or exhaustive reference review. Reference **counts** do not mean every cited source was opened, and no reference quantity alone certifies truth. Most corroboration remains within Wikimedia, with NASA and Met probes as limited external checks.

| Primary category | Retrieved | Research-screened | Distinct screened years | Quarantine / reject / duplicate | Screened yield |
| --- | ---: | ---: | ---: | ---: | ---: |
| births | 16 | 12 | 11 | 4 / 0 / 0 | 75.0% |
| deaths | 16 | 14 | 14 | 2 / 0 / 0 | 87.5% |
| battles | 16 | 15 | 15 | 1 / 0 / 0 | 93.8% |
| inventions | 16 | 13 | 13 | 3 / 0 / 0 | 81.3% |
| literature | 16 | 10 | 10 | 5 / 1 / 0 | 62.5% |
| arts | 16 | 11 | 11 | 4 / 1 / 0 | 68.8% |
| exploration | 16 | 15 | 15 | 0 / 0 / 1 | 93.8% |
| politics | 16 | 15 | 15 | 1 / 0 / 0 | 93.8% |
| **Unique total** | **128** | **105** | **95** | **20 / 2 / 1** | **82.0%** |

Overall quarantine 15.6%, outright rejection 1.6%, duplicate 0.8%; all non-acceptance 18.0%. Rows/categories are not additive memberships: the canonical Apollo 11 landing (C1-052) has inventions **and** exploration; C1-107 is a duplicate and is not counted. A person's birth, death and departure are different milestones, not automatically duplicates.

Screened events span **490 BCE–2019 CE**. Era counts: ancient (<500 CE) 5, medieval (500–1499) 12, early modern (1500–1799) 16, modern (1800–1945) 40, contemporary (1946+) 32. Primary-region counts: Europe 36, North America 14, South Asia 10, East Asia 9, Latin America 9, Oceania 8, North Africa 3, Southern Africa 3, Southeast Asia 3, West Asia 2, East Africa 2, West Africa 2, global 2, Central Asia 1, Antarctica 1. These labels locate the milestone/subject for research; they do not imply exclusive identity or exhaustive geography.

Difficulty assessments: all candidates easy 46 / medium 78 / hard 4; screened easy 40 / medium 65 / hard 0. Four specialist/hard seeds did not pass the fact screen. Recognition is an analyst judgment, **not player-tested**; the deliberately famous sample is likely easier than the remaining reservoirs. Gaps: ancient events, African/West Asian/Central Asian coverage, women's histories, Indigenous perspectives, non-European exploration, oral/non-English literature, and modern copyrighted art. Quarantining imprecise ancient dates worsens era imbalance. No random-sample confidence intervals or guaranteed scalable 82% production yield are justified.

### Exact-year and calendar rules

[Wikidata date documentation](https://www.wikidata.org/wiki/Help:Dates) describes precision (9=year, 10=month, 11=day), calendars, uncertainty and qualifiers. Keep the original value, calendar URI, precision, rank, before/after and qualifiers; preferred rank is not dispute resolution. A precise timestamp can still represent a traditional/approximate date. Never assign a single year from a decade, range, circa statement or uncertain conflicting year merely to fill a card.

Wikibase JSON signed BCE years are civil: `-0001` is 1 BCE. Do not accidentally apply RDF astronomical-year interpretation to that JSON. Display civil BCE `n`; internal ordering is **`1 - n`**, so 1 BCE maps to 0 and 1 CE to 1. There is no displayed year zero. Calendar conversion can cross a year boundary; record the historically supported convention rather than blanket converting all dates. Newton's birth (1642 Julian / 1643 Gregorian) and death (1726 legal Old Style / modern 1727) remain quarantined. Day disagreements within one uncontested year can be irrelevant to this year-only beta but must remain in provenance.

Quarantines include Caesar birth 100/102 BCE, Confucius circa/traditional alternatives, Murasaki decade/range, Red Cliffs 208–209, ancient compositions, *Hamlet* composition/publication ambiguity, *Gitanjali* edition mismatch, *Mona Lisa* and Great Wave ranges, and Ashoka's circa accession. Multi-century Benin Bronzes were not accepted. *The Bone People* has matching month-precision publication and prose evidence for 1984, but was rejected for insufficient global recognition without an explanatory anchor, not date uncertainty. Do not substitute a creator's biography for a work's date.

Narrowed prompts distinguish ENIAC's **1946 dedication** from 1945 completion; Jenner's **1796 demonstration** from 1798 publication claims; Bessemer's **1856 patent** from an 1855 inception claim; Stalingrad's **1943 end**, not its multi-year duration; Magellan-Elcano's **1522 completion**, not 1519 departure; and country/language-specific first publications/releases. Columbus's missing seed article was replaced with a real *Voyages of Christopher Columbus* article and the October 12 chronology; the prompt says Caribbean arrival, not discovery of uninhabited land.

## Evidenced, conditional route to ≥1,000 game-ready events

The target is **not yet demonstrated as a production catalog**. Evidence supports bounded discovery and automated validation, not a measured automated acceptance yield. Exact-year resolution, identity, provenance, prompts, media and release receipts can reject more than this research screen. Policy approval is complete; no manual pilot or per-record human acceptance is required. If deterministic acquisition cannot meet the target, report the shortfall and do not publish a beta release below 1,000 real unique accepted events. Never fabricate filler, promote uncertain dates or rename research screens as accepted events.

Actual retrieved reservoir pages and revision IDs are indexed in `discovery-summary.json`. Conservative extraction produced **9,513 overlapping unverified discovery leads**, not 9,513 viable or accepted events. Battle extraction checks explicit wikitext title presence; arts excludes birth/death rows; literature counts linked works rather than year navigation. Lists still include specialists, duplicates and uncertain dates.

| Category | Retrieved discovery capacity | Automated acquisition limitations |
| --- | --- | --- |
| births / deaths | 1,025 Nobel recipient entities, shared reservoir including organizations | Exclude organizations; birth and death are separate milestones. Add selected-source premodern/global biographies to address bias. |
| battles | 642 before 301; 1,132 in 301–1300; 981 in 1301–1600; 1,589 in 1801–1900 | Resolve a specific start/end milestone and exact year; quarantine disputed chronology. |
| inventions | 456 dated timeline bullets | Distinguish demonstration, patent, publication and completion using deterministic source-backed rules. |
| literature | 2,573 linked works | Select exact original-country/language publication milestones; quarantine unclear editions/ranges. |
| arts | 508 linked works | Reject uncertain composition dates; Met is comparison evidence, not a selected adapter. |
| exploration | 318 European-exploration + 90 space timeline entries | Selected-source non-European supplementation needed; use explicit departure/arrival/completion identity. |
| politics | 199 independence timeline rows | Supplement within selected sources with exact constitution/treaty/accession/election milestones; decolonisation article is qualitative evidence, not a counted reservoir. |

There is no measured per-category automated production yield. Discovery overlaps, specialist subjects and ambiguous dates reduce capacity. Supplementation is future acquisition, not evidence already counted. Process resumable bounded batches within source limits, producing a machine acceptance/quarantine report by category, era, region, difficulty heuristic and distinct year. Preserve all eight categories; do not extrapolate battles' sample yield to the whole catalog or make recognisability guarantees from metadata. Exact source entity plus milestone identity may merge citations; uncertain fuzzy aliases stay quarantined and birth/death identities stay distinct.

Each final event must pass deterministic fact/prompt/provenance and approved per-file media-or-original-fallback checks, with a passed final `ValidationReceipt` at stage `content_media`, bound to candidate/source SHA-256s, policy `automated-v1` and the independently computed canonical digest of the complete current MediaCatalog (all media/fallback metadata, filenames and asset SHAs). C3's `content` receipts have no media digest and are never publication-ready even when passed. C4 revalidates content plus media after freezing the complete batch and regenerates final receipts for all events after any catalog/rights change. C5 independently checks the current catalog digest and actual image/fallback bytes against every referenced current record SHA; a receipt alone is not asset integrity. Metadata or bytes changing invalidates final receipt/verification even when event/media/fallback references are unchanged. `review_status="approved"` means machine-validated only; a changed status label, stale receipt or passing research screen is not publication validation. C2 defines the contract, C3/C4 emit their staged receipts, C5 validates final receipts and immutable releases, and C6 must count at least 1,000 actual canonical accepted events, not category memberships or fixtures. Those components are not implemented by C1.

Report coverage and difficulty heuristics honestly rather than impose a human recognition study, paid curation or compulsory specialist check. Profile distinct years and inclusive bounds: sorted years with adjacent separation ≥`g` imply every-pair separation for integer gap `g ≥ 1`. Validate the final Daily union and actual eligible capacity for supported settings, with no duplicate event/year per run; narrow bounds/large gaps cannot promise 1,000 playable cards. Preserve BCE/CE mapping, no arbitrary round cap, immutable existing runs and all gameplay/security/license requirements.

### Effort/cost status — automated path, not a zero-effort promise

No paid access, manual pilot, human recognition study, commissioning or paid curation is authorized or required. Automated adapter/rules/testing, original SVG generation, source caching, processing, failure handling, storage and maintenance still require engineering effort; reliable automated yields/runtime/storage costs must be measured in C2–C6, not inferred from this screen. No dependencies, payments or provisioning are added here. Hosting/cost and deployment/launch authorization remain separate.

**Superseded optional manual-process estimates only:** the former 1,792/1,972-review planning model, 400-candidate human pilot, 20–30-tester study, 394–792 hours and $11.8k–$47.5k labor envelope are not the selected beta path, automated-yield forecasts, spending commitments or release gates. Former numeric era/region/category quotas and the ≥10-event preset proposal are likewise not new mandatory quality guarantees. Their history is retained in the C1 task report, not carried forward as active acceptance requirements.

## Selected fixed Daily categories

`["battles", "inventions", "exploration", "politics"]` — fixed, no rotation, **not all eight**. These favor identifiable milestones and exact-year prompts, while excluding biography and difficult work-date categories from initial Daily. Manual play retains all eight categories.

Resolved against the research-screened sample, the union contains **58 unique events / 54 distinct years**, excludes **47** other screened events, and is a proper nonempty subset. Apollo is counted once despite two memberships. This only establishes sample feasibility at gap 1 across the full sample bounds; it does not prove arbitrary filters or a final production Daily pool. Final release must validate the immutable machine-accepted union and supported gap/bound settings. Category choice must not create rotating pools or per-account seeds: the beta retains one shared seed per UTC date and one scored attempt/account/day. **These four initial categories are user-approved; no additional human content/category approval gate applies.**

## Selected immutable snapshot and validation procedure

In C3–C5, create a versioned source snapshot (e.g. `facts-2026-10-12-v1`; name is illustrative) before machine validation:

1. Save exact requests, source IDs, redirects, UTC retrieval times, HTTP status, relevant headers, raw bytes and SHA-256. Snapshot terms pages and license versions alongside records. Persist article `oldid` and content returned for that revision, not just a mutable URL. Preserve raw discovery separately from accepted events.
2. Retrieve Wikidata **`info` with claims** so each entity has `lastrevid`; keep statement IDs, values/qualifiers/references, rank and calendar/precision. This audit's initial claims batches omitted `info`: their SHA-256 snapshots are exact but entity revision IDs are absent. A later probe confirms `info` returns `lastrevid`; do not retrofit that later revision onto earlier claims.
3. Record machine decisions/issues, deterministic source-backed prompts, citations and immutable canonical IDs; maintain deduplication and category memberships separately. Archive attribution and derivative/share-alike obligations. Do not publish copied extracts under an incompatible license or erase an answer-bearing historical name to make a prompt pass; quarantine the candidate.
4. Store machine-validated media bytes/derivatives or original SVG fallbacks, rights metadata, author/credit/license links, file revision/SHA and safe alt text. Freeze the complete MediaCatalog and revalidate content plus media before binding final `content_media` receipts to candidate/source digests, policy and the full catalog digest; check actual asset bytes independently at publication/verification. Catalog/rights changes require fresh batch receipts. Export an immutable private validation/fact/media manifest tied to release digests. Retain old releases for existing runs; corrections create a new release, never mutate a frozen run.
5. Enforce receipt/integrity/rights/fallback and real-event count gates before publication, independent of research/source selection approval. This task finalizes approved policy and the scoped documentation commit only; no production importer, migration, acceptance receipts or release is created.

## Current approval and remaining boundaries

The explicit user amendment approves the selected sources, automated Commons/original-fallback path and fixed Daily choices without manual review. No new human source/media/content approval is required to finalize C1. Machine checks do not certify historical truth, global recognition or legal clearance; uncertainty is quarantined or falls back, not referred to a human queue. Actual ≥1,000-event publication, full automated integrity/rights/media validation, gameplay/device checks and deployment authorization remain future requirements. Historical pending-approval report entries describe earlier states, superseded by the dated finalization section.
