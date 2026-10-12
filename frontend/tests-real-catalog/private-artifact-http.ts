// Explicit alternate-server HTTP regression, not a browser-discovery module.
// Run only after inspecting/launching owned loopback default and real Vite servers.
import assert from "node:assert/strict"
import { resolve } from "node:path"

const alternate = process.env.F2_PRIVACY_DEFAULT_ORIGIN
assert.ok(
  alternate,
  "F2_PRIVACY_DEFAULT_ORIGIN requires an explicitly owned default Vite server",
)
const parsed = new URL(alternate)
assert.equal(parsed.protocol, "http:")
assert.ok(["localhost", "127.0.0.1"].includes(parsed.hostname))
assert.ok(["5173", "5175"].includes(parsed.port))
const release = process.env.REAL_CATALOG_RELEASE_DIR
assert.ok(
  release,
  "REAL_CATALOG_RELEASE_DIR is required for actual artifact paths",
)
const frontendRoot = resolve(import.meta.dirname, "..")
const auth = resolve(frontendRoot, "playwright/.auth/real-catalog-players.json")
const paths = [
  "/playwright/.auth/real-catalog.json",
  "/playwright/.auth/real-catalog-players.json",
  "/playwright/.auth/real-catalog-players.json?raw",
  "/playwright/.auth/real-catalog-restart-players.json?download=1",
  "/playwright/.auth/real-catalog-journey-players.jsonl",
  `/@fs${auth}`,
  `/@fs${auth}?raw`,
  "/tests-real-catalog/catalog.ts?raw",
  `/@fs${release}/manifest.json`,
  `/@fs${release}/events.jsonl`,
  `/@fs${release}/raw.jsonl`,
  `/@fs${resolve(frontendRoot, "../.superpowers/sdd/2026-10-12-historical-date-game-beta-followup/task-F2-report.md")}`,
]
const failures = []
for (const origin of [alternate, "http://localhost:5174"]) {
  for (const path of paths) {
    const response = await fetch(`${origin}${path}`)
    const length = (await response.arrayBuffer()).byteLength
    // Never print response bodies, tokens, passwords, or a private answer map.
    console.log(
      JSON.stringify({ origin, path, status: response.status, length }),
    )
    if (![403, 404].includes(response.status))
      failures.push({ origin, path, status: response.status })
  }
  for (const path of ["/", "/src/main.tsx"]) {
    const response = await fetch(`${origin}${path}`)
    console.log(
      JSON.stringify({
        origin,
        path,
        status: response.status,
        length: (await response.arrayBuffer()).byteLength,
      }),
    )
    assert.equal(response.status, 200, "ordinary UI/JS remains available")
  }
}
assert.deepEqual(
  failures,
  [],
  "private artifacts must be denied on default AND real origins",
)
