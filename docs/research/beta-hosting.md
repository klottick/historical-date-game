# Friends-beta hosting comparison

Research date: **2026-10-12 UTC**, baseline `3d07e3b`. Scope: F5's comparison
substep of [original L1](../superpowers/plans/2026-10-11-historical-date-game-beta-launch.md#task-l1-approved-hosting-and-production-safe-operations).
**Research only; provider, budget, domain, backup destination and contact remain
unapproved. No deployment or invitation authorization is implied.**

## Recommendation

Prefer **Hetzner CX23, x86 Linux, 2 shared vCPU / 4 GB RAM / 40 GB persistent
NVMe SSD**, in Germany or Finland **if geography and capacity suit the owner**.
Use independently operated, client-side-encrypted off-host backups, provisionally
Backblaze B2. In USD billing, propose **$10–15/month before tax** for the bounded
scenario below. This is a proposed ceiling range, not an approved budget or quote.
If friends are mainly in North America, or CX23 is unavailable, compare the
nearest **DigitalOcean Basic Regular bundled 2-vCPU / 4-GiB / 80-GiB SSD Droplet**:
propose **$30–40/month before tax**, including optional native daily backups.
Neither is managed application/database hosting or high availability.

Hetzner's static product page says “not available”; its public pricing API has
active EU entries. That establishes prices, **not orderable capacity**. Do not
assume availability or silently substitute a different plan. DigitalOcean's
regional product tables also do not guarantee capacity for a particular size.

## Measured retained storage, not a production benchmark

Read-only filesystem measurements at **2026-10-12T21:40:14Z**; decimal bytes unless
the provider explicitly uses GiB. No database query, dump, activation, cleanup,
service restart or load test was performed.

| Local ignored artifact | Logical bytes | Interpretation |
| --- | ---: | --- |
| `data/game/releases/jsonl-trial-2026-10-12-review-r1/` | 44,814,244 | Selected local release; 28 files, manifest declares 1,276 events, non-fixture |
| All three existing `data/game/releases/` releases | 134,442,718 | Conservatively retain all; no DB-derived run-reference inventory was attempted |
| Selected release's `source-snapshots/` | 6,647,070 | Included above; pinned reference bytes/notices/receipt, not an extra charge |
| Selected release's `media/` | 5,431 | Included above; eight fallback SVGs, not a real-photo storage estimate |
| `data/game/media/` | 5,431 | Eight additional local served copies |
| `data/game/local-catalog-runtime/media/` | 10,862 | Sixteen runtime copies; do not confuse copies with unique images |
| `data/game/acquisition/` | 1,017,832,630 | Offline work/cache/evidence; not all needed on the serving VM |
| Entire `data/game/` workspace | 1,155,308,365 | Includes releases, caches, runtime probes and fixture data; not production DB size |

All 27 manifest-bound files in each of the three releases matched their stored
digests. Selected manifest SHA-256:
`804ec52ccfc3e19cd955913b05cbfd59158f562408e45c1916fa8626d3ac50d3`.
This checks storage integrity, not content/legal clearance or launch readiness;
the [catalog research](catalog-expansion.md) records automated acceptance and
coverage limitations. The 1,276 events currently use fallbacks, with no accepted
external photos. Rights/provenance are part of retained release storage.

**Actual production PostgreSQL size (including indexes/WAL), dump size,
concurrency, RAM use, traffic, future photo yield and release growth are
unmeasured.** Do not equate JSONL size with database size. Before provisioning,
obtain approved measurements and revise the budget if necessary. Without a
database reference inventory, preserve all existing releases/media/rights; never
prune based on age alone.

4 GB is a sensible initial planning allowance for the existing Compose stack:
PostgreSQL, backend, static frontend and HTTPS proxy share one VM, with spare
memory for the OS, page cache and a backup operation. Illustrative allocations
are 1 GB DB, 1 GB backend, 0.25 GB frontend/proxy, 0.75 GB OS/cache and 1 GB
reserve; these are **not measured usage, tuning instructions or capacity
guarantees**. Shared CPU contention and concurrent backup/migration work can
still cause latency or OOM. Build images and prepare media offline, not during
scoring. Measure later; scale rather than claiming 4 GB supports an arbitrary
number of users.

For a 40-GB disk, an illustrative initial envelope is 12 GB OS/container images,
5 GB DB/WAL, 3 GB temporary dump/encryption workspace, 1 GB retained artifacts
and 1 GB bounded logs (22 GB total). These are allowances, not observations.
Review at 70% disk use and retain at least 25% free for WAL/migrations/recovery;
the current 134 MB release history is small, but retained history is unbounded.
An assumed 1,276 photos at 200 KB each adds about 255 MB per distinct image set;
originals, revisions and temporary transforms may cost much more. No pruning of
in-use immutable assets to force the disk budget.

## Current provider comparison

Prices are public list prices retrieved on the research date, not personalized
checkout quotes. No promotional credit, term commitment or invented currency
conversion is used. Hetzner EUR and USD are **separate published prices**.

| Item | Hetzner CX23, EU (`FSN1` / `NBG1` / `HEL1`) | DigitalOcean Basic Regular bundled (`s-2vcpu-4gb`) |
| --- | --- | --- |
| Compute / persistent root SSD | 2 shared vCPU, 4 GB, 40 GB NVMe; **€5.49 or $6.49/month** [H1–H2] | 2 shared vCPU, 4 GiB, 80 GiB SSD; **$24/month** [D1] |
| Public IPv4 | Separate **€0.50 or $0.60/month**; IPv6 free [H3,H5] | Original public IPv4, no extra reserved IP budgeted; **$0 incremental** for this bundled plan, not v5 [D1–D2,D4] |
| Compute + IPv4 | **€5.99 or $7.09/month** | **$24/month** |
| Extra SSD | **$0 initially**: use included persistent disk; additional volume price/size unquoted and needs re-budgeting | **$0 initially**: use included persistent disk; additional volume price/size unquoted and needs re-budgeting |
| Included outbound traffic | **20 TB/month EU**; incoming/internal traffic free; EU excess **€1 or $1.20/TB** [H1,H4–H5] | **4,000 GiB/month** on this plan; inbound free; excess **$0.01/GiB**, team-pooled [D1–D2] |
| Optional native daily disk backup | 20% server price: **€1.098 / $1.298** (about €1.10 / $1.30); seven slots; attached volumes excluded [H5–H6] | 30% Droplet price: **$7.20/month**; weekly 20% ($4.80) does not meet our daily policy [D1] |
| Optional native snapshots | **€0.0143 / $0.0199 per compressed GB/month**, as labeled by the product page/API; usage-dependent, not included in totals [H1,H5,H7] | **$0.06/GB/month**, usage-dependent, not included in totals [D1] |
| Independent daily encrypted backup | Proposed B2, same cost model for either host; **$0–0.70/month storage allowance** for 10–100 GB, plus excess egress/special transactions [B1] | Same |
| Region / latency tradeoff | CX23 price evidence covers Germany/Finland only. Hetzner also operates US/Singapore regions, but do **not** apply this CX23 EU price/traffic to them [H8] | More regional choices: e.g. NYC3/SFO3, FRA1/AMS3/LON1, TOR1/SGP1/BLR1/SYD1; exact plan capacity needs checking [D3] |

Pick the region near the majority of friends and acceptable for account-data
residency; their locations are unknown. Transatlantic round trips may affect
Lock it in responsiveness. **No latency measurements or location promise.**
Both retain local disk across ordinary restarts, not after VM destruction; the
existing PostgreSQL 18 persistent-volume layout and retained read-only game-data
mount remain L1 requirements. Persistence is not a backup.

## Monthly budget assumptions and itemization

Assume one always-on VM; traffic within the included quota; included root SSD;
10–100 GB total off-host retained encrypted data; one non-premium `.com` or `.dev`
if a domain is bought; no managed DB, CDN, load balancer or paid source access.
With B2's **$6.95/TB/30 days** rate, gross storage for 10–100 decimal GB is
$0.0695–0.695; its first 10 GB are free, hence the conservative **$0–0.70** range.
It is a usage allowance, not a minimum fee or claim that seven points fit 10 GB.

| Monthly line item (USD billing scenario) | Hetzner | DigitalOcean |
| --- | ---: | ---: |
| Compute | $6.49 | $24.00 |
| IPv4 | $0.60 | $0.00 incremental |
| Included SSD / in-quota traffic | $0 extra | $0 extra |
| Independent encrypted backup storage allowance | $0–0.70 | $0–0.70 |
| Existing owned domain/subdomain | $0 incremental; existing renewal still payable | Same |
| New domain alternative, renewal amortized | $0.92–1.07 | $0.92–1.07 |
| Optional native daily backups | $0–1.30 | $0–7.20 |
| Source/image access and manual curation | **$0** | **$0** |
| Total: existing domain, no native backup | **$7.09–7.79** | **$24.00–24.70** |
| Total: new domain + native daily backup | **$9.31–10.16** | **$32.12–32.97** |
| Proposed operating budget with contingency | **$10–15/month** | **$30–40/month** |

Domain examples [N1]: `.com` **$11.08/year** registration/renewal ($0.923/month);
`.dev` **$8.75 first year** ($0.729/month), then **$12.87/year** ($1.073/month).
The table budgets renewal rather than a first-year sale. Annual payment is due
up front, not actually billed monthly. These are generic non-premium TLD rates
including stated ICANN/other fees, **not availability checks for any name**.
Using an owner's existing subdomain avoids a new registration; its parent-domain
renewal price and DNS contract are unknown, not magically free. Public certificate
and included DNS services need no paid certificate line; renewal/HTTPS operation
is still engineering work. `.dev` requires HTTPS via HSTS [N2].

For EUR Hetzner billing, keep **€5.99/month** host+IPv4, optionally **€1.10** native
daily backups, **plus USD backup/domain charges** separately. There is no EUR
all-in total here: FX/card fees are unknown and currency cannot simply be changed
after Hetzner account creation [H5].

**Not priced / excluded from the numeric range:** VAT/sales taxes (owner country
and tax status unknown), FX/payment fees, premium domains/other TLDs, traffic
overages, storage above 100 GB, extra volumes, additional backup replicas,
temporary isolated restore VM/storage, paid monitoring/email delivery or support,
engineering labor and incident response. Choose existing restricted-account
admin recovery or separately price real-email reset delivery; an email forwarding
feature is not an outbound SMTP service. No paid curation or source-access budget:
the selected open source/media workflow has **$0 access charges**, while automated
acquisition, validation, attribution, storage and maintenance are not free effort
([source research](catalog-expansion.md#source-access-rights-and-next-approval)).

A planning allowance of **4–8 engineering hours for initial safe operations and
restore verification, then 1–3 hours/month** for updates/checks/drills is an estimate,
not measured labor or a promise; incidents may dominate. Owner time/rate remains
unpriced. This comparison does not authorize that implementation work.

## Recoverability and backup destination decision

Required for **either provider**, not implemented or verified by this research:

- Daily consistent DB dump with checksums, schema/app-image versions and complete
  catalog/media/rights inventory. Coordinate offline publication/activation while
  collecting that inventory; do not run source acquisition inside scoring.
- Client-side encryption before off-host transfer, private destination, narrow
  credentials, and independently recoverable encryption key held by the owner
  outside the VM. Do not publish secrets, access tokens or account dumps.
- Keep **at least seven retained successful daily restore points**. Verify transfer
  integrity before counting success/pruning; alert the chosen operations contact
  on failed or stale backups. Failed attempts cannot replace successful points.
- Retain **every catalog release, immutable media asset, source/rights notice,
  attribution/receipt and version inventory referenced by any existing run**, even
  beyond seven days. Seven DB dumps without their frozen catalog/media are not
  seven usable restore points. Retain current and old dependencies; deduplication
  is optional, not a basis for assuming zero storage cost.
- A conservative full-copy bound is `7 × (dump bytes + all retained artifacts)`
  plus encryption/inventory overhead and long-lived referenced history. Current
  three-release history alone is about **0.941 GB for seven full copies**. An
  **assumed**, unmeasured 1-GB dump would make that about 7.941 GB before overhead;
  growing DB/media/history can exceed the 10–100-GB allowance. Keep temporary local
  workspace and isolated restore space separate from the off-host estimate.
- Before invitations, retrieve/decrypt/check and restore to an **explicit separate
  project/target**, never over production. Prove preserved active runs, frozen
  Daily identity, media/credits and resume. Record duration/digests; RPO is roughly
  one successful daily interval, potentially longer after failure. RTO is unmeasured.

Host-native snapshots/backups are optional quick-rebuild conveniences, **not the
sole independent off-host, application-consistent, verified-restore protection**.
Their provider/account failure domain and incomplete attached-volume coverage
remain risks; seven native slots alone do not satisfy L1's contract.

Provisional B2 is a different provider from either VM host. Its pricing includes
free egress up to **3× average monthly stored data**, then **$0.01/GB**; Class A/B/C
calls are free for pay-as-you-go, but Class D is **$0.004/10,000**, with the first
2,500/day free [B1]. For illustration, restoring 100 GB beyond the free allowance
adds $1; repeated drills may incur more. Uploading backups counts toward the VM's
outbound allowance too. No special partner free-egress assumption.

B2 account region choices include US West/East, EU Central (Amsterdam) and Canada
East; data stays in the chosen region unless directed elsewhere. That choice is
not changeable on the same account [B2]. Owner approval must cover privacy/data
residency, credentials, billing and key custody. Ciphertext still leaves account,
object-size and timing metadata with the provider. Avoid exposing player identity
in object names; encryption does not establish legal compliance. An existing
owner-controlled off-host store is possible, but available capacity, reliability,
connectivity, privacy and incremental costs are unknown—not assumed $0.

Portable container images, standard DB dumps and digest-named assets reduce
lock-in; native snapshots, provider networking/IPs, backup API/lifecycle policies
and region-bound accounts do not migrate automatically. Off-host copies protect
against VM loss, not loss of both credentials and encryption keys. Independent
credentials/key recovery and restore exercises are necessary.

## Security and owner approval gates

Later original L1 work must use **HTTPS, nondefault secrets, exact production
origins, restricted enrollment and `PUBLIC_REGISTRATION_ENABLED=false`**. Expose
only intended HTTPS app/API/media traffic (HTTP for redirect/certificate needs,
SSH restricted); **no public DB, Adminer, proxy dashboard/API management,
Mailcatcher, private test routes, tokens or raw release/source manifests**. Only
answer-safe media bytes are public; retained catalog/rights/source artifacts stay
private/read-only to the app. Inspect rendered production Compose, not just YAML.
The existing base Compose is **not production-safe**: it publishes DB and Adminer.
This research changes no overlay, script, runbook, secret or service.

**Owner approval block — all pending; controller review first:**

| Decision | Required recorded choice |
| --- | --- |
| Provider / plan / billing currency | Hetzner CX23 or DigitalOcean bundled Basic Regular; no silent substitute |
| Region | Exact region, friend geography/latency tradeoff and acceptable residency; capacity recheck |
| Monthly ceiling | Currency, before/after-tax limit, included backup/domain costs, overage response and renewal cash payment |
| Domain | Existing authorized subdomain or new name/TLD/registrar; separate authorization for purchase/DNS changes |
| Backup destination | Provider/store/region, retention/capacity/cost/privacy, independent credentials and encryption-key custodian |
| Contact | Feedback address and named operator receiving failed-backup/health/budget alerts; recovery responsibility |
| Deployment authorization | **Separate explicit permission** for provisioning, paid work and original L1 implementation/production activation |

Budget approval is not launch approval. L2 restore, security, gameplay/device and
release gates plus owner go/no-go remain required before invitations.

## Official evidence and retrieval receipts

The UTC times below identify retained HTTP snapshots, not page publication dates.
Each was HTTP 200. Exact URL, response headers, bytes and SHA-256 are retained
privately under `.superpowers/sdd/2026-10-12-historical-date-game-beta-followup/F5-evidence/`
in `source-receipts.json`; `quoted-evidence.md` identifies the quoted facts. Public
Git contains this summary, not copies of large copyrighted provider pages.
Web tools read the official pages; raw read-only GETs then captured receipts.
Hetzner prices required its site's public pricing endpoint because static HTML
omitted rendered amounts. API `hourly` field names for traffic/snapshot products
are not unit definitions: the product page supplies TB / GB-month units.
No authenticated calculator, quote, signup or order was submitted.

| ID | Official URL / what supports the comparison | Retrieved UTC on 2026-10-12 |
| --- | --- | --- |
| H1 | [CX23 product](https://www.hetzner.com/cloud/cost-optimized/): CPU/RAM/disk, 20-TB EU traffic, price product mapping, availability warning, snapshot unit | 21:39:52Z |
| H2 | [CX23 price API](https://website-price-api.hetzner.com/api/v1/products/CLOUD_132): HEL1/FSN1/NBG1 €5.49/$6.49 monthly | 21:39:53Z |
| H3 | [IPv4 price API](https://website-price-api.hetzner.com/api/v1/products/CLOUD_21): €0.50/$0.60 monthly | 21:39:53Z |
| H4 | [Traffic price API](https://website-price-api.hetzner.com/api/v1/products/CLOUD_66): ALL €1/$1.20; not SIN1 | 21:39:53Z |
| H5 | [Billing FAQ](https://docs.hetzner.com/cloud/billing/faq/): separate IP, free IPv6/inbound, backup 20%, compressed snapshot size, currency/alerts | 21:39:54Z |
| H6 | [Backup overview](https://docs.hetzner.com/cloud/servers/backups-snapshots/overview/): seven daily slots, no attached volumes | 21:39:55Z |
| H7 | [Snapshot price API](https://website-price-api.hetzner.com/api/v1/products/CLOUD_24): €0.0143/$0.0199 | 21:39:54Z |
| H8 | [Cloud locations](https://www.hetzner.com/cloud/), [capacity FAQ](https://docs.hetzner.com/cloud/general/faq/): locations, possible provisioning restrictions | 21:39:51Z / 21:39:56Z |
| D1 | [Droplet prices](https://www.digitalocean.com/pricing/droplets): Basic **Regular bundled**, not Premium/v5; $24, 2 vCPU, 4 GiB, 80 GiB, 4,000 GiB, backup/snapshot rates | 21:39:56Z |
| D2 | [Droplet billing](https://docs.digitalocean.com/products/droplets/details/pricing/): bundled cap, transfer excess; v5 differs and IPv4 line item can change | 21:39:56Z |
| D3 | [Regions](https://docs.digitalocean.com/platform/regional-availability/): named datacenters; no exact-size capacity quote | 21:39:57Z |
| D4 | [Features](https://docs.digitalocean.com/products/droplets/details/features/): original IP, persistent boot disk, shared CPU, free firewall | 21:39:56Z |
| B1 | [B2 pricing](https://www.backblaze.com/cloud-storage/pricing): $6.95/TB/30 days, first 10 GB free, egress and transaction exceptions | 21:39:57Z |
| B2 | [B2 regions](https://www.backblaze.com/docs/cloud-storage-data-regions): residency/account-region constraint, same storage costs by region | 21:39:57Z |
| N1 | [Domain pricing](https://www.porkbun.com/products/domains), [.com](https://porkbun.com/tld/com): annual non-premium registration/renewal, USD and fees, DNS | 21:39:57Z / 21:39:58Z |
| N2 | [.dev](https://porkbun.com/tld/dev): sale/renewal and HSTS | 21:39:59Z |

Context7 additionally supplied official DigitalOcean shared-CPU suitability
guidance; **live official receipts above**, not documentation-index excerpts or
third-party reviews, establish prices. Recheck all rates, capacity, tax and domain
renewal before owner-approved expenditure; no price validity period is promised.
