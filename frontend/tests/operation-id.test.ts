import assert from "node:assert/strict"
import { existsSync } from "node:fs"
import { test } from "node:test"

async function generator() {
  assert.ok(
    existsSync("src/features/game/operationId.ts"),
    "cryptographic operation UUID utility is missing",
  )
  return (await import("../src/features/game/operationId.ts")).operationId
}

test("native operation UUID uses the provider method without fallback", async () => {
  const operationId = await generator()
  const source = {
    value: "00112233-4455-4677-8899-aabbccddeeff",
    randomUUID() {
      return this.value
    },
    getRandomValues() {
      assert.fail("native UUID must not draw fallback bytes")
    },
  }
  assert.equal(operationId(source), "00112233-4455-4677-8899-aabbccddeeff")
})

test("insecure-context fallback retains every random byte except RFC v4 reserved bits", async () => {
  const operationId = await generator()
  const source = {
    getRandomValues(bytes: Uint8Array) {
      assert.equal(bytes.length, 16)
      bytes.set([
        0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99, 0xaa, 0xbb,
        0xcc, 0xdd, 0xee, 0xff,
      ])
      return bytes
    },
  }
  assert.equal(operationId(source), "00112233-4455-4677-8899-aabbccddeeff")
})

test("fallback forces version 4 and RFC variant without discarding remaining entropy", async () => {
  const operationId = await generator()
  for (const [byte, expected] of [
    [0x00, "00000000-0000-4000-8000-000000000000"],
    [0xff, "ffffffff-ffff-4fff-bfff-ffffffffffff"],
  ] as const) {
    assert.equal(
      operationId({ getRandomValues: (bytes) => bytes.fill(byte) }),
      expected,
    )
  }
})

test("default real cryptographic provider produces distinct RFC v4 operation IDs", async () => {
  const operationId = await generator()
  const ids = Array.from({ length: 100 }, () => operationId())
  assert.equal(new Set(ids).size, 100)
  for (const id of ids)
    assert.match(
      id,
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    )
})

test("missing cryptographic source fails closed with an understandable error", async () => {
  const operationId = await generator()
  for (const source of [null, {}])
    assert.throws(
      () => operationId(source),
      /Secure random source unavailable.*No game command was sent/,
    )
})

test("cryptographic provider failure never falls back to weak randomness", async () => {
  const operationId = await generator()
  assert.throws(
    () =>
      operationId({
        getRandomValues() {
          throw new Error("unavailable")
        },
      }),
    /Secure random source unavailable.*No game command was sent/,
  )
})
