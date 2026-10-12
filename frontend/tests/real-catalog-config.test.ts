import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { existsSync, readFileSync } from "node:fs"
import { test } from "node:test"

test("test_real_catalog_suite_does_not_discover_fixture_journeys", () => {
  assert.ok(
    existsSync("playwright.real-catalog.config.ts"),
    "separate real configuration is missing",
  )
  const result = spawnSync(
    process.execPath,
    [
      "--input-type=module",
      "-e",
      `
    const { default: c, realCatalogAPI, realCatalogAuthFile } = await import('./playwright.real-catalog.config.ts');
    console.log(JSON.stringify({testDir:c.testDir,testMatch:c.testMatch,baseURL:c.use.baseURL,
      api:realCatalogAPI,auth:realCatalogAuthFile,webServer:c.webServer,
      projects:c.projects.map(p=>({name:p.name,dependencies:p.dependencies,storageState:p.use?.storageState}))}));
  `,
    ],
    { encoding: "utf8" },
  )
  assert.equal(result.status, 0, result.stderr)
  const c = JSON.parse(result.stdout.trim())
  assert.deepEqual(c, {
    testDir: "./tests-real-catalog",
    testMatch: "**/*.spec.ts",
    baseURL: "http://localhost:5174",
    api: "http://localhost:8010/api/v1",
    auth: "playwright/.auth/real-catalog.json",
    projects: [
      { name: "setup" },
      ...["chromium", "game-mobile"].map((name) => ({
        name,
        dependencies: ["setup"],
        storageState: "playwright/.auth/real-catalog.json",
      })),
    ],
  })
  assert.match(
    readFileSync("playwright.config.ts", "utf8"),
    /testDir: '\.\/tests'/,
  )
})

test("real setup refuses a missing private release instead of fixture fallback", () => {
  assert.ok(
    existsSync("tests-real-catalog/catalog.ts"),
    "private release guard is missing",
  )
  const env = { ...process.env }
  delete env.REAL_CATALOG_RELEASE_DIR
  const result = spawnSync(
    process.execPath,
    [
      "--input-type=module",
      "-e",
      `const {loadCatalog}=await import('./tests-real-catalog/catalog.ts'); loadCatalog();`,
    ],
    { env, encoding: "utf8" },
  )
  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /REAL_CATALOG_RELEASE_DIR is required/)
})

test("real runner refuses a relative release path", () => {
  const result = spawnSync(
    process.execPath,
    [
      "--input-type=module",
      "-e",
      `const {loadCatalog}=await import('./tests-real-catalog/catalog.ts'); loadCatalog('fixture');`,
    ],
    {
      env: { ...process.env, REAL_CATALOG_RELEASE_DIR: "../data/game" },
      encoding: "utf8",
    },
  )
  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /private release path must be absolute/)
})

test("test-only real catalog answers stay outside application imports and Vite environment", () => {
  const config = readFileSync("playwright.real-catalog.config.ts", "utf8")
  const setup = readFileSync("tests-real-catalog/auth.setup.ts", "utf8")
  const catalog = readFileSync("tests-real-catalog/catalog.ts", "utf8")
  assert.match(config, /storageState: realCatalogAuthFile/)
  assert.match(setup, /loadCatalog\(options.catalog_release_id\)/)
  assert.match(catalog, /REAL_CATALOG_RELEASE_DIR/)
  assert.doesNotMatch(catalog, /VITE_REAL|page\.evaluate\s*\(/)
  // Only structural guards here; the final emitted-bundle scan uses actual IDs.
  const { stdout, status } = spawnSync(
    process.execPath,
    [
      "--input-type=module",
      "-e",
      `
    import {readdirSync,readFileSync} from 'node:fs';
    const walk=p=>readdirSync(p,{withFileTypes:true}).flatMap(e=>e.isDirectory()?walk(p+'/'+e.name):[p+'/'+e.name]);
    console.log(walk('src').filter(p=>/\\.[tj]sx?$/.test(p)).filter(p=>/tests-real-catalog|REAL_CATALOG_RELEASE_DIR/.test(readFileSync(p,'utf8'))).join('\\n'));
  `,
    ],
    { encoding: "utf8" },
  )
  assert.equal(status, 0)
  assert.equal(stdout.trim(), "")
})
