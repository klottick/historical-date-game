import assert from "node:assert/strict"
import { existsSync } from "node:fs"
import test from "node:test"

async function helper() {
  assert.ok(
    existsSync("tests/utils/gameOptions.ts"),
    "missing public options setup assertion",
  )
  return await import("./utils/gameOptions.ts")
}

const options = {
  catalog_release_id: "synthetic-release",
  categories: [{ id: "history", label: "History" }],
  start: { value: 1, era: "CE" },
  end: { value: 2000, era: "CE" },
  registration_open: false,
}

test("setup fails actionably on catalog_unavailable before any category dereference", async () => {
  const { readGameOptions } = await helper()
  await assert.rejects(
    readGameOptions({
      status: () => 503,
      json: async () => ({ detail: { code: "catalog_unavailable" } }),
    }),
    /games\/options.*503.*catalog_unavailable/,
  )
})

test("setup requires the complete populated public options schema", async () => {
  const { readGameOptions } = await helper()
  for (const invalid of [
    {},
    { ...options, categories: [] },
    { ...options, categories: [{ id: "history" }] },
    { ...options, start: { value: 0, era: "CE" } },
    { ...options, end: { value: 2000, era: "AD" } },
    { ...options, registration_open: undefined },
  ]) {
    await assert.rejects(
      readGameOptions({ status: () => 200, json: async () => invalid }),
      /Invalid public games\/options schema/,
    )
  }
  assert.deepEqual(
    await readGameOptions({ status: () => 200, json: async () => options }),
    options,
  )
})
