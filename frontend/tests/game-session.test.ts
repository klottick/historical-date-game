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
  assert.equal(startStorageKey("g:one", "daily"), "game:v2:g%3Aone:start:daily")
  assert.equal(
    placementStorageKey("g:one", "run"),
    "game:v2:g%3Aone:placement:run",
  )
  assert.deepEqual(gameQueryKey("g:one", "run", "run"), [
    "game",
    2,
    "g:one",
    "run",
    "run",
  ])
  assert.deepEqual(gameQueryKey("a:two", "active"), [
    "game",
    2,
    "a:two",
    "active",
  ])
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
    assert.deepEqual(
      gameRequestOptions({ kind, context_id: "context", protocol_version: 2 }),
      {
        withCredentials: true,
        headers: { "X-Game-Request": "1", "X-Game-Context": "context" },
      },
    )
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
  const context = {
    kind: "account" as const,
    context_id: "account-first",
    protocol_version: 2 as const,
  }
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
  const guest = {
    kind: "guest" as const,
    context_id: "guest",
    protocol_version: 2 as const,
  }
  gameApi.bindGameContext(guest, "", () => true)
  await gameApi.getActiveRuns(guest)
  assert.equal((sent[1] as Record<string, string>).Authorization, undefined)
  assert.equal(sent.length, 2)
  const stale = {
    kind: "account" as const,
    context_id: "stale",
    protocol_version: 2 as const,
  }
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

test("old unversioned commands are never adopted into v2 recovery", () => {
  const values = new Map<string, string>([
    ["game-start:owner-one:daily", '{"operation_id":"old-start"}'],
    ["game-placement:owner-one:run", '{"operation_id":"old-move"}'],
  ])
  Object.assign(globalThis, {
    sessionStorage: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    },
  })
  const guest = {
    kind: "guest" as const,
    context_id: "guest",
    protocol_version: 2 as const,
  }
  gameApi.bindGameContext(guest, "", () => true, "owner-first")
  gameApi.adoptAccountStart(guest, "game:v2:guest:start:daily", "daily")
  gameApi.adoptAccountPlacement(guest, "game:v2:guest:placement:run", "run")
  assert.equal(values.has("game:v2:guest:start:daily"), false)
  assert.equal(values.has("game:v2:guest:placement:run"), false)
  const unconfirmed = {
    kind: "account" as const,
    context_id: "unconfirmed",
    protocol_version: 2 as const,
  }
  gameApi.bindGameContext(unconfirmed, "first", () => true)
  gameApi.adoptAccountStart(
    unconfirmed,
    "game:v2:unconfirmed:start:daily",
    "daily",
  )
  assert.equal(values.has("game:v2:unconfirmed:start:daily"), false)
  const otherAccount = {
    kind: "account" as const,
    context_id: "other-account",
    protocol_version: 2 as const,
  }
  gameApi.bindGameContext(otherAccount, "second", () => true, "owner-second")
  gameApi.adoptAccountStart(otherAccount, "game:v2:other:start:daily", "daily")
  assert.equal(values.has("game:v2:other:start:daily"), false)
  assert.equal(
    values.get("game-start:owner-one:daily"),
    '{"operation_id":"old-start"}',
  )
  assert.equal(
    values.get("game-placement:owner-one:run"),
    '{"operation_id":"old-move"}',
  )
})
