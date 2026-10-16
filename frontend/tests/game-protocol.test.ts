import assert from "node:assert/strict"
import test from "node:test"
import type { GameOptions } from "../src/client/types.gen.ts"
import {
  GAME_PROTOCOL_VERSION,
  hasCompatibleGameProtocol,
  protocolUpgradeMessage,
} from "../src/features/game/gameProtocol.ts"
import {
  gameQueryKey,
  placementStorageKey,
  startStorageKey,
} from "../src/features/game/identityState.ts"
import {
  beginPlacement,
  markUncertain,
  type PlacementState,
} from "../src/features/game/placementState.ts"

const media = {
  url: "/image.svg",
  fallback_url: "/fallback.svg",
  alt_text: "Illustration",
  fit: "contain" as const,
  credits: [],
}
const state: PlacementState = {
  run: {
    run_id: "run",
    mode: "freeplay",
    daily_date: null,
    catalog_release_id: "release",
    config: {
      category_ids: ["science"],
      start: { era: "CE", value: 1 },
      end: { era: "CE", value: 2000 },
      min_gap: 1,
    },
    categories: [],
    status: "active",
    initial_lives: 3,
    lives_remaining: 3,
    score: 0,
    streak: 0,
    revision: 0,
    timeline: [],
    pending: { event_id: "pending", prompt: "Prompt", category_ids: [], media },
    feedback: null,
  },
  selectedSlot: 0,
  command: null,
  phase: "idle",
}

test("new placement and exact retry retain protocol 2 and the original command", () => {
  const first = beginPlacement(state, "same-operation")
  assert.equal(first.command?.protocol_version, GAME_PROTOCOL_VERSION)
  assert.deepEqual(
    beginPlacement(markUncertain(first), "different-operation").command,
    first.command,
  )
})

test("recovery and query namespaces are v2 without changing account-token identity", () => {
  assert.equal(
    startStorageKey("guest:a", "freeplay"),
    "game:v2:guest%3Aa:start:freeplay",
  )
  assert.equal(
    placementStorageKey("guest:a", "run/b"),
    "game:v2:guest%3Aa:placement:run%2Fb",
  )
  assert.deepEqual(gameQueryKey("guest:a", "run", "run/b"), [
    "game",
    2,
    "guest:a",
    "run",
    "run/b",
  ])
})

test("only protocol 2 is accepted and incompatibility messaging is actionable", () => {
  assert.equal(hasCompatibleGameProtocol({ protocol_version: 2 }), true)
  assert.equal(hasCompatibleGameProtocol({ protocol_version: 1 }), false)
  assert.equal(hasCompatibleGameProtocol({}), false)
  assert.equal(
    protocolUpgradeMessage,
    "Game updated. Refresh and start a new game.",
  )
})

test("generated options DTO makes protocol release acceptance explicit", () => {
  const options: Pick<GameOptions, "protocol_version"> = { protocol_version: 2 }
  assert.equal(hasCompatibleGameProtocol(options), true)
})
