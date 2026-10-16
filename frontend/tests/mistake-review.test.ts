import assert from "node:assert/strict"
import test from "node:test"
import type { RunPublic } from "../src/client/types.gen.ts"
import { lossTimeline } from "../src/features/game/lossTimeline.ts"
import {
  isMistakeReviewAcknowledgement,
  mistakeReviewKey,
  needsMistakeReview,
} from "../src/features/game/mistakeReview.ts"
import {
  acceptRun,
  type PlacementState,
} from "../src/features/game/placementState.ts"

const card = (id: string) => ({
  event_id: id,
  prompt: id,
  category_ids: [],
  media: {
    url: "x",
    fallback_url: "y",
    alt_text: "art",
    fit: "contain",
    credits: [],
  },
  year: { value: 1, era: "CE" as const },
  explanation: "notes",
  sources: [],
})
function missedRun(status: RunPublic["status"] = "active"): RunPublic {
  return {
    run_id: "r",
    mode: "freeplay",
    daily_date: null,
    catalog_release_id: "c",
    config: {
      category_ids: [],
      start: { value: 1, era: "CE" },
      end: { value: 10, era: "CE" },
      min_gap: 1,
    },
    categories: [],
    status,
    initial_lives: 3,
    lives_remaining: status === "won" ? 2 : 2,
    score: 1,
    streak: 0,
    revision: 3,
    // Server has already committed the correction into its sorted canonical timeline.
    timeline: [card("a"), card("wrong"), card("b"), card("c")],
    pending: null,
    feedback: {
      correct: false,
      card: card("wrong"),
      attempted_slot: 1,
      correct_slot: 2,
    },
  }
}

test("needs review for nonfinal misses, including pool-exhaustion wins only", () => {
  for (const status of ["active", "won"] as const) {
    const run = missedRun(status)
    assert.equal(needsMistakeReview(run, false), true)
    assert.equal(needsMistakeReview(run, true), false)
  }
  assert.equal(
    needsMistakeReview({ ...missedRun("lost"), lives_remaining: 0 }, false),
    false,
  )
  assert.equal(
    needsMistakeReview(
      { ...missedRun(), feedback: { ...missedRun().feedback!, correct: true } },
      false,
    ),
    false,
  )
  assert.equal(
    needsMistakeReview({ ...missedRun(), feedback: null }, false),
    false,
  )
})

test("revision acknowledgement keys are scoped and malformed values are not acknowledgement", () => {
  assert.notEqual(mistakeReviewKey("a", "r", 3), mistakeReviewKey("b", "r", 3))
  assert.notEqual(
    mistakeReviewKey("a", "r", 3),
    mistakeReviewKey("a", "other", 3),
  )
  assert.notEqual(mistakeReviewKey("a", "r", 3), mistakeReviewKey("a", "r", 4))
  assert.equal(isMistakeReviewAcknowledgement("acknowledged"), true)
  for (const value of [null, "true", 'acknowledged"', "{}", 1])
    assert.equal(isMistakeReviewAcknowledgement(value), false)
})

test("review projection removes committed wrong card before attempted insertion without mutating run", () => {
  for (const [attempted, correct, expected] of [
    [0, 0, ["wrong", "a", "b", "c"]],
    [1, 2, ["a", "wrong", "b", "c"]],
    [3, 1, ["a", "b", "c", "wrong"]],
  ] as const) {
    const run = missedRun()
    run.feedback!.attempted_slot = attempted
    run.feedback!.correct_slot = correct
    const before = structuredClone(run.timeline)
    const display = lossTimeline(run, true)
    assert.deepEqual(
      display.items.map((item) => item.card.event_id),
      expected,
    )
    assert.equal(display.items.filter((item) => item.wrong).length, 1)
    assert.deepEqual(run.timeline, before)
    assert.equal(
      display.correctDisplaySlot,
      correct + (attempted <= correct ? 1 : 0),
    )
  }
})

test("newer accepted revision owns subsequent review state", () => {
  const first = missedRun()
  const state: PlacementState = {
    run: first,
    selectedSlot: null,
    command: null,
    phase: "idle",
  }
  const newer = { ...first, revision: 4 }
  const accepted = acceptRun(state, newer)
  assert.equal(accepted.run.revision, 4)
  assert.equal(acceptRun(accepted, first), accepted)
})
