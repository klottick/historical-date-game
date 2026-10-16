import assert from "node:assert/strict"
import { test } from "node:test"
import type { RunPublic } from "../src/client/types.gen.ts"
import { lossTimeline } from "../src/features/game/lossTimeline.ts"

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
function run(attempted: number, correct: number): RunPublic {
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
    status: "lost",
    initial_lives: 3,
    lives_remaining: 0,
    score: 0,
    streak: 2,
    revision: 3,
    timeline: [card("a"), card("b"), card("c")],
    pending: null,
    feedback: {
      correct: false,
      card: card("wrong"),
      attempted_slot: attempted,
      correct_slot: correct,
    },
  }
}
test("attempted 1 stays at 1 while correct confirmed boundary 3 displays at 4; input untouched", () => {
  const input = run(1, 3)
  const copy = structuredClone(input)
  const result = lossTimeline(input)
  assert.deepEqual(
    result.items.map((item) => [item.card.event_id, item.wrong]),
    [
      ["a", false],
      ["wrong", true],
      ["b", false],
      ["c", false],
    ],
  )
  assert.equal(result.attemptedSlot, 1)
  assert.equal(result.correctSlot, 3)
  assert.equal(result.correctDisplaySlot, 4)
  assert.deepEqual(input, copy)
})
test("attempted last and correct first retains wrong at end and boundary 0", () => {
  const result = lossTimeline(run(3, 0))
  assert.equal(result.items[3].card.event_id, "wrong")
  assert.equal(result.correctDisplaySlot, 0)
})
test("invalid attempted slots never invent a wrong-card position", () => {
  for (const attempted of [-1, 4, 1.5, Number.NaN]) {
    const result = lossTimeline(run(attempted, 2))
    assert.equal(result.items.length, 3)
    assert.deepEqual(
      result.items.map((item) => [item.card.event_id, item.wrong]),
      [
        ["a", false],
        ["b", false],
        ["c", false],
      ],
    )
    assert.equal(result.attemptedSlot, null)
    assert.equal(result.correctSlot, 2)
    assert.equal(result.correctDisplaySlot, 2)
  }
})
test("correct feedback and active runs never add a wrong card or correct marker", () => {
  const input = run(1, 1)
  input.status = "active"
  input.feedback!.correct = true
  const result = lossTimeline(input)
  assert.equal(result.items.length, 3)
  assert.ok(result.items.every((item) => !item.wrong))
  assert.equal(result.correctDisplaySlot, null)
})
