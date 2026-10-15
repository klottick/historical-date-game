import assert from "node:assert/strict"
import test from "node:test"
import axios from "axios"
import { client } from "../src/client/client.gen.ts"
import * as gameApi from "../src/features/game/api.ts"
import { isKnownFailure } from "../src/features/game/api.ts"
import {
  gameQueryKey,
  gameRequestOptions,
  placementStorageKey,
  sessionFailure,
  startStorageKey,
} from "../src/features/game/identityState.ts"

test("commands and private queries are partitioned by confirmed context", () => {
  assert.equal(startStorageKey("g:one", "daily"), "game:g%3Aone:start:daily")
  assert.equal(
    placementStorageKey("g:one", "run"),
    "game:g%3Aone:placement:run",
  )
  assert.deepEqual(gameQueryKey("g:one", "run", "run"), [
    "game",
    "g:one",
    "run",
    "run",
  ])
  assert.deepEqual(gameQueryKey("a:two", "active"), ["game", "a:two", "active"])
  assert.notEqual(
    startStorageKey("g:one", "daily"),
    startStorageKey("a:two", "daily"),
  )
  assert.notEqual(
    placementStorageKey("g:one", "run"),
    placementStorageKey("a:two", "run"),
  )
  assert.notEqual(
    placementStorageKey("a:b", "c"),
    placementStorageKey("a", "b:c"),
  )
  assert.notEqual(
    startStorageKey("g:one", "daily"),
    startStorageKey("g:one", "freeplay"),
  )
})

test("owned requests carry cookies, the mutation guard and the confirmed context", () => {
  for (const kind of ["guest", "account"] as const) {
    assert.deepEqual(gameRequestOptions({ kind, context_id: "context" }), {
      withCredentials: true,
      headers: { "X-Game-Request": "1", "X-Game-Context": "context" },
    })
  }
})

function httpError(code: unknown, status = 401) {
  return {
    isAxiosError: true,
    response: { status, data: { detail: { code, message: "Unavailable" } } },
  }
}

test("session failures remain recovery failures, not historical rejection", () => {
  for (const [code, expected] of [
    ["game_session_required", "missing"],
    ["game_session_expired", "expired"],
    ["game_session_invalid", "invalid"],
    ["invalid_account", "invalid"],
    ["game_identity_changed", "identity_changed"],
    ["game_request_rejected", "origin"],
  ] as const)
    assert.equal(sessionFailure(httpError(code)), expected)
  assert.equal(
    sessionFailure(
      Object.assign(new Error("Retry browser storage"), {
        code: "guest_storage_unavailable",
      }),
    ),
    "storage",
  )
  // An invalid/expired account can also use the existing unstructured OAuth error.
  assert.equal(
    sessionFailure({
      isAxiosError: true,
      response: {
        status: 403,
        data: { detail: "Could not validate credentials" },
      },
    }),
    "invalid",
  )
  assert.equal(sessionFailure(httpError({ malformed: true })), "invalid")
  assert.equal(sessionFailure(httpError("unknown_auth_code")), "invalid")
  assert.equal(
    sessionFailure(httpError("game_identity_changed", 409)),
    "identity_changed",
  )
  assert.equal(sessionFailure(httpError({ malformed: true }, 409)), "invalid")
  assert.equal(
    sessionFailure(httpError("game_identity_unknown", 409)),
    "invalid",
  )
  for (const error of [
    httpError("operation_conflict", 409),
    httpError("invalid_slot", 422),
    httpError("unavailable", 503),
    new Error("network"),
    { code: "ERR_CANCELED" },
  ]) {
    assert.equal(sessionFailure(error), null)
  }
})

test("identity and malformed auth errors cannot discard unresolved commands", () => {
  for (const error of [
    httpError("game_identity_changed", 409),
    httpError("game_identity_unknown", 409),
    httpError({ malformed: true }, 409),
    httpError("game_session_required"),
    httpError({ malformed: true }),
    httpError("game_request_rejected", 403),
  ]) {
    assert.equal(isKnownFailure(error), false)
  }
  assert.equal(isKnownFailure(httpError("stale_revision", 409)), true)
})

test("captured account auth survives generated client async auth pipeline", async () => {
  assert.equal(typeof gameApi.bindGameContext, "function")
  let token = "first"
  let current = true
  const context = { kind: "account" as const, context_id: "account-first" }
  gameApi.bindGameContext(context, "first", () => current, "owner-first")
  const sent: unknown[] = []
  const transport = axios.create({
    adapter: async (options) => {
      sent.push(options.headers)
      return {
        data: [],
        status: 200,
        statusText: "OK",
        headers: {},
        config: options,
      }
    },
  })
  client.setConfig({ auth: async () => token, axios: transport })
  await gameApi.getActiveRuns(context)
  assert.equal(sent.length, 1)
  const guest = { kind: "guest" as const, context_id: "guest" }
  gameApi.bindGameContext(guest, "", () => true)
  await gameApi.getActiveRuns(guest)
  assert.equal((sent[1] as Record<string, string>).Authorization, undefined)
  assert.equal(sent.length, 2)
  const stale = { kind: "account" as const, context_id: "stale" }
  let valid = true
  gameApi.bindGameContext(stale, "first", () => valid)
  const pending = gameApi.getActiveRuns(stale)
  valid = false // Switch while the generated pipeline awaits auth resolution.
  await assert.rejects(pending, { code: "game_identity_changed" })
  assert.equal(sent.length, 2)
  assert.equal(
    (sent[0] as Record<string, string>).Authorization,
    "Bearer first",
  )
  token = "second"
  current = false
  await assert.rejects(gameApi.getActiveRuns(context), {
    code: "game_identity_changed",
  })
  assert.equal(sent.length, 2)
})

test("legacy command migration refuses collisions and preserves original bytes", () => {
  assert.equal(typeof gameApi.adoptLegacyOperation, "function")
  const values = new Map<string, string>([
    ["legacy", '{"operation_id":"old"}'],
    ["new", '{"operation_id":"other"}'],
  ])
  Object.assign(globalThis, {
    sessionStorage: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    },
  })
  assert.throws(
    () => gameApi.adoptLegacyOperation("legacy", "new"),
    /conflict/i,
  )
  assert.equal(values.get("legacy"), '{"operation_id":"old"}')
  assert.equal(values.get("new"), '{"operation_id":"other"}')
  values.delete("new")
  gameApi.adoptLegacyOperation("legacy", "new")
  assert.equal(values.get("new"), '{"operation_id":"old"}')
  assert.equal(values.has("legacy"), false)
  values.set("game-start:owner-first:daily", '{"operation_id":"original"}')
  const guest = { kind: "guest" as const, context_id: "guest" }
  gameApi.bindGameContext(guest, "", () => true, "owner-first")
  gameApi.adoptAccountStart(guest, "guest-destination", "daily")
  assert.equal(values.has("guest-destination"), false)
  const unconfirmed = { kind: "account" as const, context_id: "unconfirmed" }
  gameApi.bindGameContext(unconfirmed, "first", () => true)
  gameApi.adoptAccountStart(unconfirmed, "unconfirmed-destination", "daily")
  assert.equal(values.has("unconfirmed-destination"), false)
  const otherAccount = { kind: "account" as const, context_id: "other-account" }
  gameApi.bindGameContext(otherAccount, "second", () => true, "owner-second")
  gameApi.adoptAccountStart(otherAccount, "other-destination", "daily")
  assert.equal(values.has("other-destination"), false)
  assert.equal(
    values.get("game-start:owner-first:daily"),
    '{"operation_id":"original"}',
  )
})
