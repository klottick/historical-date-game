import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { readFileSync } from "node:fs"
import test from "node:test"

test("fresh browser CI provisions an owned fixture before browser consumers", () => {
  const workflow = readFileSync("../.github/workflows/playwright.yml", "utf8")
  const seed = workflow.indexOf("tests.browser.ci_fixture prepare")
  const browser = workflow.indexOf("- name: Run Playwright tests")
  assert.ok(seed > 0, "missing guarded CI fixture provision")
  assert.ok(seed < browser, "fixture must precede browser consumers")
  assert.match(workflow, /POSTGRES_DB: historical_date_game_guest_fixture_test/)
  assert.match(workflow, /COMPOSE_FILE=/)
})

test("CI waits for backend health after fixture verification and before browser consumers", () => {
  const workflow = readFileSync("../.github/workflows/playwright.yml", "utf8")
  const seed = workflow.indexOf("tests.browser.ci_fixture prepare")
  const healthy = workflow.indexOf(
    "docker compose up -d --wait backend mailcatcher",
  )
  const browser = workflow.indexOf("- name: Run Playwright tests")
  assert.ok(seed > 0, "missing verified fixture provision")
  assert.ok(healthy > 0, "missing explicit backend health wait")
  assert.ok(seed < healthy, "verify fixture before starting backend")
  assert.ok(healthy < browser, "backend health must precede browser consumers")
})

test("runner temp is resolved in a step, not an unavailable job-env context", () => {
  const workflow = readFileSync("../.github/workflows/playwright.yml", "utf8")
  assert.doesNotMatch(workflow, /^ {6}COMPOSE_FILE:.*runner\.temp/m)
  assert.match(workflow, /COMPOSE_FILE=.*\$RUNNER_TEMP.*\$GITHUB_ENV/)
})

test("Docker browser API and media use the UI origin without weakening guest cookies", () => {
  const result = spawnSync(
    process.execPath,
    [
      "--input-type=module",
      "-e",
      `import {resolveConfig} from 'vite';
       const c=await resolveConfig({configFile:'vite.playwright.config.ts'},'serve');
       console.log(JSON.stringify({proxy:c.server.proxy,api:c.define?.['import.meta.env.VITE_API_URL'],deny:c.server.fs.deny}));`,
    ],
    {
      encoding: "utf8",
      env: { ...process.env, PLAYWRIGHT_API_PROXY: "http://backend:8000" },
    },
  )
  assert.equal(result.status, 0, result.stderr)
  const actual = JSON.parse(result.stdout.trim().split("\n").pop()!)
  assert.deepEqual(actual.proxy, {
    "/api/": "http://backend:8000",
    "/media/": "http://backend:8000",
  })
  assert.equal(actual.api, JSON.stringify(""))
  assert.ok(actual.deny.includes("**/.superpowers/**"))
  const compose = readFileSync("../docker-compose.override.yml", "utf8")
  assert.match(compose, /VITE_API_URL=http:\/\/localhost:5173/)
})

test("controlled CI harnesses stay serial, zero-retry and isolated", () => {
  const workflow = readFileSync("../.github/workflows/playwright.yml", "utf8")
  for (const harness of ["board", "bootstrap", "identity"]) {
    assert.match(
      workflow,
      new RegExp(
        `--config=playwright\\.${harness}\\.config\\.ts --workers=1 --retries=0 --output=test-results/${harness}`,
      ),
    )
  }
  assert.match(
    workflow,
    /needs:\s*- test-playwright\s*- test-controlled-browser/,
  )
})
