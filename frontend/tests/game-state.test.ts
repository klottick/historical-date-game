import assert from "node:assert/strict"
import test from "node:test"
import type { RunPublic } from "../src/client/types.gen.ts"
import {
  acceptRun,
  beginPlacement,
  markUncertain,
  type PlacementState,
  selectSlot,
} from "../src/features/game/placementState.ts"

const media = {
  url: "/image.svg",
  fallback_url: "/fallback.svg",
  alt_text: "Illustration",
  fit: "contain",
  credits: [],
}
const run: RunPublic = {
  run_id: "run-a",
  mode: "freeplay",
  daily_date: null,
  catalog_release_id: "fixture",
  config: {
    category_ids: ["science"],
    start: { era: "CE", value: 1 },
    end: { era: "CE", value: 2000 },
    min_gap: 1,
  },
  categories: [],
  status: "active",
  streak: 2,
  revision: 3,
  timeline: [
    {
      event_id: "anchor",
      prompt: "Anchor",
      category_ids: ["science"],
      media,
      year: { era: "CE", value: 100 },
      explanation: "Public explanation",
      sources: [],
    },
  ],
  pending: {
    event_id: "pending",
    prompt: "Unanswered",
    category_ids: ["science"],
    media,
  },
  feedback: null,
}
const initial: PlacementState = {
  run,
  selectedSlot: null,
  command: null,
  phase: "idle",
}

test("preview_never_scores", () => {
  for (const slot of [0, 1, null]) {
    const preview = selectSlot(initial, slot)
    assert.equal(preview.run, run)
    assert.equal(preview.run.streak, 2)
    assert.equal(preview.run.revision, 3)
    assert.equal(preview.command, null)
    assert.equal(preview.phase, "idle")
    assert.equal(preview.selectedSlot, slot)
  }
})
test("begin requires a valid selected slot and blocks duplicate inflight submit", () => {
  for (const slot of [null, -1, 2, 0.5, Number.NaN]) {
    const invalid = { ...initial, selectedSlot: slot }
    assert.equal(beginPlacement(invalid, "op"), invalid)
  }
  assert.equal(beginPlacement(initial, "op"), initial)
  const sending = beginPlacement(selectSlot(initial, 1), "first")
  assert.deepEqual(sending.command, {
    operation_id: "first",
    expected_revision: 3,
    event_id: "pending",
    slot: 1,
  })
  assert.equal(sending.phase, "sending")
  assert.equal(beginPlacement(sending, "duplicate"), sending)
  assert.equal(selectSlot(sending, 0), sending)
  assert.equal(
    beginPlacement(
      { ...initial, run: { ...run, status: "lost", pending: null } },
      "op",
    ).command,
    null,
  )
})
test("timeout_retains_operation_and_preview", () => {
  const sending = beginPlacement(selectSlot(initial, 1), "same-uuid")
  const uncertain = markUncertain(sending)
  assert.deepEqual(uncertain.command, sending.command)
  assert.equal(uncertain.selectedSlot, 1)
  assert.equal(uncertain.phase, "uncertain")
  assert.equal(selectSlot(uncertain, 0), uncertain)
  const retry = beginPlacement(uncertain, "must-not-replace")
  assert.deepEqual(retry.command, sending.command)
  assert.equal(retry.phase, "sending")
})
test("older_response_cannot_roll_back", () => {
  const newer = { ...initial, run: { ...run, revision: 4, streak: 3 } }
  assert.equal(acceptRun(newer, run), newer)
  assert.equal(
    acceptRun(initial, { ...run, run_id: "another-run", revision: 50 }),
    initial,
  )
})
test("newer authoritative revision clears stale command and preview", () => {
  const state = markUncertain(beginPlacement(selectSlot(initial, 1), "op"))
  const updated = acceptRun(state, {
    ...run,
    revision: 4,
    streak: 3,
    pending: { ...run.pending!, event_id: "next" },
  })
  assert.equal(updated.run.revision, 4)
  assert.equal(updated.selectedSlot, null)
  assert.equal(updated.command, null)
  assert.equal(updated.phase, "idle")
  assert.equal(markUncertain(updated), updated)
})
test("equal revision polling never resolves sending uncertainty or conflict", () => {
  const sending = beginPlacement(selectSlot(initial, 1), "op")
  for (const state of [
    sending,
    markUncertain(sending),
    { ...sending, phase: "reconcile" as const },
  ]) {
    assert.equal(acceptRun(state, { ...run }), state)
  }
  assert.equal(acceptRun(selectSlot(initial, 0), { ...run }).selectedSlot, 0)
})
test("invalid slot selections are ignored", () => {
  for (const slot of [-1, 2, 0.5, Number.NaN])
    assert.equal(selectSlot(initial, slot), initial)
})
