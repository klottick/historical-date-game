import assert from "node:assert/strict"
import test from "node:test"
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
