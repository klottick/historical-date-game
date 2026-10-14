import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { existsSync, readFileSync } from "node:fs"
import { test } from "node:test"

test("test_real_catalog_suite_does_not_discover_fixture_journeys", () => {
  const env = { ...process.env }
  delete env.REAL_CATALOG_API_ORIGIN
  delete env.REAL_CATALOG_UI_ORIGIN
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
    { env, encoding: "utf8" },
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

test("real catalog UI binds all IPv4 interfaces with same-origin API and media", () => {
  const result = spawnSync(
    process.execPath,
    [
      "--input-type=module",
      "-e",
      `
    import { resolveConfig } from 'vite';
    const c = await resolveConfig({configFile:'vite.real-catalog.config.ts'}, 'serve');
    console.log(JSON.stringify({host:c.server.host,port:c.server.port,strictPort:c.server.strictPort,
      allowedHosts:c.server.allowedHosts,proxy:c.server.proxy,apiBase:c.define?.['import.meta.env.VITE_API_URL']}));
  `,
    ],
    {
      encoding: "utf8",
      env: { ...process.env, VITE_API_URL: "http://localhost:8000" },
    },
  )
  assert.equal(result.status, 0, result.stderr)
  const actual = JSON.parse(result.stdout.trim().split("\n").pop()!)
  assert.equal(actual.host, "0.0.0.0")
  assert.equal(actual.port, 5174)
  assert.equal(actual.strictPort, true)
  // Vite adds the configured bind host; it must not allow arbitrary hostnames.
  assert.ok(Array.isArray(actual.allowedHosts))
  assert.ok(actual.allowedHosts.every((host: string) => host === "0.0.0.0"))
  assert.deepEqual(actual.proxy, {
    "/api/": "http://127.0.0.1:8010",
    "/media/": "http://127.0.0.1:8010",
  })
  assert.equal(actual.apiBase, JSON.stringify(""))
})

for (const configFile of [
  "vite.config.ts",
  "vite.real-catalog.config.ts",
  "vite.guest-catalog.config.ts",
  "vite.board.config.ts",
]) {
  test(`${configFile} resolves strict private-file protection and retains installed Vite defaults`, () => {
    const result = spawnSync(
      process.execPath,
      [
        "--input-type=module",
        "-e",
        `
      import { resolveConfig } from 'vite';
      const defaults = await resolveConfig({configFile:false,envDir:false}, 'serve');
      const defaultDeny = [...defaults.server.fs.deny];
      const actual = await resolveConfig({configFile:${JSON.stringify(configFile)},envDir:false}, 'serve');
      console.log(JSON.stringify({strict:actual.server.fs.strict,deny:actual.server.fs.deny,defaults:defaultDeny}));
    `,
      ],
      { encoding: "utf8" },
    )
    assert.equal(result.status, 0, result.stderr)
    const actual = JSON.parse(result.stdout.trim().split("\n").pop()!)
    assert.equal(actual.strict, true)
    assert.ok(
      actual.defaults.length > 0,
      "installed default deny list is nonempty",
    )
    for (const pattern of [
      ...actual.defaults,
      "**/playwright/.auth/**",
      "**/tests-real-catalog/**",
      "**/tests-guest-catalog/**",
      "**/.superpowers/**",
      "**/data/game/**",
    ])
      assert.ok(
        actual.deny.includes(pattern),
        `${configFile} must retain deny: ${pattern}`,
      )
  })
}

test("isolated real and fixture runners accept explicit test origins", () => {
  const result = spawnSync(
    process.execPath,
    [
      "--input-type=module",
      "-e",
      `
    const real=await import('./playwright.real-catalog.config.ts');
    const fixture=await import('./tests/utils/apiOrigin.ts');
    console.log(JSON.stringify({api:real.realCatalogAPI,ui:real.realCatalogUIOrigin,
      base:real.default.use.baseURL,fixture:fixture.fixtureAPI,origin:fixture.fixtureAPIOrigin}));
  `,
    ],
    {
      encoding: "utf8",
      env: {
        ...process.env,
        REAL_CATALOG_API_ORIGIN: "http://localhost:8020",
        REAL_CATALOG_UI_ORIGIN: "http://localhost:5184",
        VITE_API_URL: "http://localhost:8021",
      },
    },
  )
  assert.equal(result.status, 0, result.stderr)
  assert.deepEqual(JSON.parse(result.stdout.trim()), {
    api: "http://localhost:8020/api/v1",
    ui: "http://localhost:5184",
    base: "http://localhost:5184",
    fixture: "http://localhost:8021/api/v1",
    origin: "http://localhost:8021",
  })
})

test("guest runner has no authentication setup and uses a genuine insecure browser hostname", () => {
  const result = spawnSync(
    process.execPath,
    [
      "--input-type=module",
      "-e",
      `
    const {default:c}=await import('./playwright.guest-catalog.config.ts');
    console.log(JSON.stringify({dir:c.testDir,workers:c.workers,server:c.webServer,
      projects:c.projects.map(p=>({name:p.name,dependencies:p.dependencies,state:p.use?.storageState,
        base:p.use?.baseURL,args:p.use?.launchOptions?.args}))}));
  `,
    ],
    { encoding: "utf8" },
  )
  assert.equal(result.status, 0, result.stderr)
  const c = JSON.parse(result.stdout.trim())
  assert.equal(c.dir, "./tests-guest-catalog")
  assert.equal(c.workers, 1)
  assert.equal(c.server, undefined)
  assert.equal(c.projects.length, 3)
  for (const project of c.projects) {
    assert.equal(project.dependencies, undefined)
    assert.equal(project.state, undefined)
  }
  const insecure = c.projects.find(
    (p: { name: string }) => p.name === "insecure-chromium",
  )
  assert.equal(insecure.base, "http://guest.test:5184")
  assert.ok(
    insecure.args.includes("--host-resolver-rules=MAP guest.test 127.0.0.1"),
  )
})

test("guest Vite binds strict loopback with only controlled additional hostname", () => {
  const result = spawnSync(
    process.execPath,
    [
      "--input-type=module",
      "-e",
      `
    import {resolveConfig} from 'vite';
    const c=await resolveConfig({configFile:'vite.guest-catalog.config.ts'},'serve');
    console.log(JSON.stringify({host:c.server.host,port:c.server.port,strict:c.server.strictPort,
      hosts:[...new Set(c.server.allowedHosts)],proxy:c.server.proxy,api:c.define['import.meta.env.VITE_API_URL']}));
  `,
    ],
    { encoding: "utf8" },
  )
  assert.equal(result.status, 0, result.stderr)
  assert.deepEqual(JSON.parse(result.stdout.trim().split("\n").pop()!), {
    host: "127.0.0.1",
    port: 5184,
    strict: true,
    hosts: ["guest.test", "127.0.0.1"],
    proxy: {
      "/api/": "http://127.0.0.1:8020",
      "/media/": "http://127.0.0.1:8020",
    },
    api: JSON.stringify(""),
  })
})

test("controlled Vite harnesses do not replace other running catalog dependency caches", () => {
  const result = spawnSync(
    process.execPath,
    [
      "--input-type=module",
      "-e",
      `
    import {resolveConfig} from 'vite';
    const paths=[];
    for (const configFile of ['vite.config.ts','vite.guest-catalog.config.ts','vite.bootstrap.config.ts','vite.identity.config.ts','vite.board.config.ts']) {
      paths.push((await resolveConfig({configFile},'serve')).cacheDir);
    }
    console.log(JSON.stringify(paths));
  `,
    ],
    { encoding: "utf8" },
  )
  assert.equal(result.status, 0, result.stderr)
  assert.equal(
    new Set(JSON.parse(result.stdout.trim().split("\n").pop()!)).size,
    5,
  )
})

test("board harness is loopback-only, no-account, isolated from fixture discovery", () => {
  const result = spawnSync(
    process.execPath,
    [
      "--input-type=module",
      "-e",
      `
    import {resolveConfig} from 'vite';
    const {default:c}=await import('./playwright.board.config.ts');
    const {default:fixture}=await import('./playwright.config.ts');
    const v=await resolveConfig({configFile:'vite.board.config.ts'},'serve');
    console.log(JSON.stringify({dir:c.testDir,match:c.testMatch,workers:c.workers,retries:c.retries,
      projects:c.projects,base:c.use.baseURL,server:c.webServer,ignore:fixture.testIgnore,
      host:v.server.host,port:v.server.port,strict:v.server.strictPort,proxy:v.server.proxy,
      api:v.define['import.meta.env.VITE_API_URL'],envDir:v.envDir}));
  `,
    ],
    { encoding: "utf8" },
  )
  assert.equal(result.status, 0, result.stderr)
  const c = JSON.parse(result.stdout.trim().split("\n").pop()!)
  assert.equal(c.dir, "./tests")
  assert.deepEqual(c.match, [
    "**/board-navigation.spec.ts",
    "**/board-ux.spec.ts",
    "**/game-board-ux.spec.ts",
  ])
  assert.equal(c.workers, 1)
  assert.equal(c.retries, 0)
  assert.equal(c.projects, undefined)
  assert.equal(c.base, "http://127.0.0.1:5186")
  assert.equal(c.server.url, c.base)
  assert.equal(c.server.reuseExistingServer, false)
  assert.ok(c.server.command.includes("vite.board.config.ts"))
  assert.ok(c.ignore.includes("**/board-navigation.spec.ts"))
  assert.ok(c.ignore.includes("**/board-ux.spec.ts"))
  assert.ok(c.ignore.includes("**/game-board-ux.spec.ts"))
  assert.equal(c.host, "127.0.0.1")
  assert.equal(c.port, 5186)
  assert.equal(c.strict, true)
  assert.equal(c.proxy, undefined)
  assert.equal(c.api, JSON.stringify(""))
  assert.ok(c.envDir.endsWith("/frontend/tests"))
})
