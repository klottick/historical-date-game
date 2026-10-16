# Historical Date Game runtime catalogue

Default: **chronology-1276-runtime-v2**, 1,276 events and eight CC0 fallback SVGs.
`default.json` pins the reviewed manifest digest. This directory contains only
final runtime records, their build recipe, public provenance/licences and assets;
no raw source inputs, acquisition caches, audit reports or database exports.

The immutable v1 release and assets remain unchanged for retained games. Its
historical recipe requires its original code version. The v2 recipe includes the
shared Daily playability gate and standalone locked-date export. Both are now
historical: use code `4b96e38` for v1 replay, `8b2c862` for v2. New acquisition
features do not modify those immutable bytes or pretend old code pins match.

From `backend/`, after installing dependencies, verify offline without a DB:

```bash
.venv/bin/python -c 'from pathlib import Path; from app.content.runtime import verify_default; print(verify_default(Path("catalogue")).manifest.model_dump_json())'
```

See [catalogue operations](../../docs/operations/catalogue.md) for run,
initialize/install, shared external media storage, acquisition, reproduction and
explicit candidate-update commands. Startup never replaces an existing catalogue
selection. Preserve old release assets while retained games reference them.

**Offline play and public-source fresh generation are separate workflows.** Use
`python -m app.content.rebuild_cli fresh --output <new-ignored-directory>
--release-id <new-id>` from `backend/` to build a new chronology-only dataset
without private inputs. It normally has about 1,271 events and no Births events;
the current 1,276-event default remains unchanged. Exact recreation of the old
release is optional; its historical receipt/five supplement envelopes remain on
Mustafar. No source archive upload is required. See operations for commands,
validation/coverage limits and optional locked replay of a fresh generation.

Adapted catalogue text: **CC BY-SA 4.0**, credited to Wikipedia contributors via
mneedham/wikipedia-onthisday. Changes include automatic selection, categories and
year-only presentation. Per-record Wikipedia/Wikidata source credits remain in
`events.jsonl`; structured data and original geometric fallback artwork are CC0.
Application code is separately MIT. Preserve `LICENSE.catalog.txt`,
`NOTICE.catalog.md`, `attribution.json`, source citations/contributor histories and
per-asset `media.json` credits. No endorsement or blanket legal clearance is
claimed. Source archive distribution needs its own review and authorization.

Only qualified digest-named media is HTTP-served; do not publish this directory
as a static web root. Answers are intentionally distributed in Git, not in pending
gameplay responses. Runtime verification proves supported semantics/integrity
against the reviewed default digest, not independent historical truth or upstream
copyright ownership; full raw-source verification is a separate build gate.
