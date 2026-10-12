// Node test runner ONLY. Never import into src or pass answers to page.evaluate.
import assert from "node:assert/strict"
import { createHash } from "node:crypto"
import { readFileSync, realpathSync } from "node:fs"
import { isAbsolute, resolve, sep } from "node:path"

export const expectedManifestSHA =
  "804ec52ccfc3e19cd955913b05cbfd59158f562408e45c1916fa8626d3ac50d3"
export const slugs = [
  "births",
  "deaths",
  "battles",
  "inventions",
  "literature",
  "arts",
  "exploration",
  "politics",
]
type PrivateEvent = {
  event_id: string
  year_index: number
  category_ids: string[]
}

export function loadCatalog(selectedRelease?: string) {
  const directory = process.env.REAL_CATALOG_RELEASE_DIR
  assert.ok(
    directory,
    "REAL_CATALOG_RELEASE_DIR is required; no fixture fallback",
  )
  assert.ok(isAbsolute(directory), "private release path must be absolute")
  const root = realpathSync(directory)
  const bytes = readFileSync(resolve(root, "manifest.json"))
  const sha = (b: Buffer) => createHash("sha256").update(b).digest("hex")
  assert.equal(sha(bytes), expectedManifestSHA, "current pinned manifest hash")
  const manifest = JSON.parse(bytes.toString())
  assert.equal(manifest.fixture, false, "real suite refuses fixtures")
  assert.ok(manifest.event_count >= 1000, "at least 1000 accepted events")
  assert.equal(
    manifest.release_id,
    selectedRelease,
    "API must select the verified real release before answers load",
  )
  for (const [name, digest] of Object.entries(manifest.files)) {
    const file = realpathSync(resolve(root, name))
    assert.ok(
      file.startsWith(`${root}${sep}`),
      "manifest file stays private inside release",
    )
    assert.equal(sha(readFileSync(file)), digest, `release integrity: ${name}`)
  }
  const events: PrivateEvent[] = readFileSync(
    resolve(root, "events.jsonl"),
    "utf8",
  )
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line))
  assert.equal(events.length, manifest.event_count)
  assert.equal(new Set(events.map((e) => e.event_id)).size, events.length)
  const years = new Map(events.map((e) => [e.event_id, e.year_index]))
  // Consecutive actual occupied years yield exactly two usable years, not a fake pool.
  const occupied = [...new Set(events.map((e) => e.year_index))].sort(
    (a, b) => a - b,
  )
  const start = occupied[0]
  const end = occupied[1]
  return { manifest, years, small: { start, end, gap: end - start } }
}
