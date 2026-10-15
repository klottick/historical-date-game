import assert from "node:assert/strict"
import path from "node:path"
import { test } from "node:test"
import ts from "typescript"

test("typecheck discovers guest catalog tests and guest/identity configurations", () => {
  const config = ts.readConfigFile("tsconfig.json", ts.sys.readFile)
  assert.equal(config.error, undefined)
  const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, ".")
  assert.deepEqual(parsed.errors, [])
  const roots = new Set(parsed.fileNames.map((name) => path.resolve(name)))
  for (const file of [
    "tests-guest-catalog/game-guest.spec.ts",
    "playwright.guest-catalog.config.ts",
    "playwright.identity.config.ts",
    "vite.guest-catalog.config.ts",
    "vite.identity.config.ts",
  ]) {
    assert.ok(
      roots.has(path.resolve(file)),
      `Unchecked verification root: ${file}`,
    )
  }
})
