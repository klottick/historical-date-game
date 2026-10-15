import assert from "node:assert/strict"
import { test } from "node:test"
import * as geometry from "../src/features/game/boardGeometry.ts"
import {
  type BoardLayout,
  clampOffset,
  insertionIndex,
  offsetToReveal,
  overviewMarks,
} from "../src/features/game/boardGeometry.ts"

const layout: BoardLayout = {
  count: 3,
  cardWidth: 100,
  gap: 20,
  viewportWidth: 160,
  offset: 0,
  previewSlot: null,
}

// Physical slots are not confirmed ordinals; gaps and preview-only windows
// must not invent visible events. These expectations are hand-derived.
test("confirmed card starts share expanded geometry without moving preview predecessors", () => {
  assert.equal(typeof geometry.confirmedCardStart, "function")
  assert.equal(geometry.confirmedCardStart(0, { ...layout, previewSlot: 1 }), 0)
  assert.equal(
    geometry.confirmedCardStart(1, { ...layout, previewSlot: 1 }),
    240,
  )
  assert.equal(
    geometry.confirmedCardStart(2, { ...layout, previewSlot: 1 }),
    360,
  )
  assert.equal(geometry.confirmedCardStart(2, layout), 240)
  assert.throws(() => geometry.confirmedCardStart(3, layout), RangeError)
})

test("visible confirmed projection accounts for preview before inside and after window", () => {
  assert.equal(typeof geometry.visibleConfirmedRange, "function")
  const base = { ...layout, count: 6, viewportWidth: 160, offset: 240 }
  for (const [previewSlot, want] of [
    [null, { first: 2, last: 3 }],
    [0, { first: 1, last: 2 }],
    [2, { first: 2, last: 2 }],
    [3, { first: 2, last: 2 }],
    [6, { first: 2, last: 3 }],
  ] as const)
    assert.deepEqual(
      geometry.visibleConfirmedRange({ ...base, previewSlot }),
      want,
    )
})

test("visible confirmed projection excludes touching edges gaps and preview-only windows", () => {
  assert.equal(typeof geometry.visibleConfirmedRange, "function")
  for (const [change, want] of [
    [{ offset: 100, viewportWidth: 20 }, null],
    [
      { offset: 99, viewportWidth: 22 },
      { first: 0, last: 1 },
    ],
    [{ offset: 120, viewportWidth: 100, previewSlot: 1 }, null],
    [
      { offset: 119, viewportWidth: 122, previewSlot: 1 },
      { first: 1, last: 1 },
    ],
    [{ count: 0 }, null],
    [{ count: 0, previewSlot: 0 }, null],
    [
      { count: 1, viewportWidth: 500 },
      { first: 0, last: 0 },
    ],
  ] as const) {
    const range = geometry.visibleConfirmedRange({ ...layout, ...change })
    assert.deepEqual(range, want)
    if (range === null)
      assert.ok(
        overviewMarks(layout.count, -1, -1).every((mark) => !mark.visible),
      )
  }
})

test("visible confirmed projection clamps beginning end and aggregated marks", () => {
  assert.equal(typeof geometry.visibleConfirmedRange, "function")
  const base = {
    count: 12,
    cardWidth: 230,
    gap: 16,
    viewportWidth: 1064,
    offset: 0,
    previewSlot: 0,
  }
  assert.deepEqual(geometry.visibleConfirmedRange(base), { first: 0, last: 3 })
  assert.deepEqual(geometry.visibleConfirmedRange({ ...base, offset: 99999 }), {
    first: 7,
    last: 11,
  })
  const range = geometry.visibleConfirmedRange({
    ...base,
    count: 100,
    offset: 99999,
  })!
  assert.deepEqual(range, { first: 95, last: 99 })
  assert.deepEqual(
    overviewMarks(100, range.first, range.last).filter((mark) => mark.visible),
    [
      { start: 95, end: 95, visible: true },
      { start: 96, end: 96, visible: true },
      { start: 97, end: 97, visible: true },
      { start: 98, end: 99, visible: true },
    ],
  )
})

// Catches center/index off-by-one (especially old displayed slot 2 = index 1).
test("test_all_insertion_boundaries", () => {
  for (const [x, want] of [
    [-100, 0],
    [49.99, 0],
    [50, 1],
    [110, 1],
    [169.99, 1],
    [170, 2],
    [230, 2],
    [289.99, 2],
    [290, 3],
    [1000, 3],
  ]) {
    assert.equal(insertionIndex(x, layout), want, `x=${x}`)
    assert.equal(insertionIndex(x - 120, { ...layout, offset: 120 }), want)
  }
  assert.equal(insertionIndex(10, { ...layout, count: 0 }), 0)
  assert.equal(insertionIndex(110, { ...layout, count: 500 }), 1)
})

// Catches repeatedly subtracting inserted width and rebasing against animation.
test("test_preview_space_does_not_oscillate", () => {
  for (const [x, initial, want] of [
    [110, null, 1],
    [160, null, 1],
    [200, 1, 1],
    [239.99, 1, 1],
    [250, 1, 1],
    [290, 1, 2],
    [500, 1, 3],
    [10, 2, 0],
  ] as const) {
    let previewSlot: number | null = initial
    for (let frame = 0; frame < 100; frame++) {
      previewSlot = insertionIndex(x, { ...layout, previewSlot })
      assert.equal(previewSlot, want, `x=${x}, frame=${frame}`)
    }
  }
  assert.equal(
    insertionIndex(130, { ...layout, offset: 120, previewSlot: 1 }),
    1,
  )
  assert.equal(insertionIndex(460, { ...layout, previewSlot: 3 }), 3)
  assert.equal(insertionIndex(60, { ...layout, count: 0, previewSlot: 0 }), 0)
  // Check every initial preview, including both ends of a long sequence. Only
  // the returned ordinal is fed back; no animated neighbor rect is consulted.
  for (const count of [1, 3, 500]) {
    for (const initial of [null, 0, 1, count]) {
      for (const x of [
        -10,
        49.99,
        50,
        110,
        169.99,
        170,
        290,
        350,
        120 * count,
      ]) {
        const current = { ...layout, count, offset: 120, previewSlot: initial }
        const selected = insertionIndex(x, current)
        assert.equal(
          insertionIndex(x, { ...current, previewSlot: selected }),
          selected,
        )
      }
    }
  }
})

test("test_resize_clamps_and_reveals_target", () => {
  assert.equal(clampOffset(-10, layout), 0)
  assert.equal(clampOffset(999, layout), 180)
  assert.equal(clampOffset(999, { ...layout, previewSlot: 1 }), 300)
  assert.equal(clampOffset(180, { ...layout, viewportWidth: 400 }), 0)
  assert.equal(clampOffset(10, { ...layout, count: 0 }), 0)
  assert.equal(offsetToReveal(0, { ...layout, offset: 180 }), 0)
  assert.equal(offsetToReveal(1, { ...layout, offset: 180 }), 110)
  assert.equal(offsetToReveal(3, layout), 180)
  assert.equal(offsetToReveal(1, { ...layout, previewSlot: 1 }), 60)
  assert.equal(
    offsetToReveal(1, { ...layout, previewSlot: 1, viewportWidth: 80 }),
    130,
  )
  assert.equal(offsetToReveal(3, { ...layout, previewSlot: 3 }), 300)
  assert.equal(offsetToReveal(0, { ...layout, count: 0, previewSlot: 0 }), 0)
})

test("test_overview_aggregates_500_events_without_hidden_years", () => {
  const marks = overviewMarks(500, 123, 135)
  assert.equal(marks.length, 80)
  assert.deepEqual(marks[0], { start: 0, end: 5, visible: false })
  assert.deepEqual(marks[marks.length - 1], {
    start: 493,
    end: 499,
    visible: false,
  })
  assert.equal(marks.filter((m) => m.visible).length, 3)
  let next = 0
  for (const mark of marks) {
    assert.equal(mark.start, next)
    assert.ok(mark.end >= mark.start)
    assert.deepEqual(Object.keys(mark).sort(), ["end", "start", "visible"])
    next = mark.end + 1
  }
  assert.equal(next, 500)
  assert.deepEqual(overviewMarks(0, 0, 0), [])
  assert.deepEqual(overviewMarks(1, 0, 0), [
    { start: 0, end: 0, visible: true },
  ])
  assert.deepEqual(overviewMarks(3, 1, 1, 2), [
    { start: 0, end: 0, visible: false },
    { start: 1, end: 2, visible: true },
  ])
  assert.deepEqual(overviewMarks(500, 123, 135, 1), [
    { start: 0, end: 499, visible: true },
  ])
})

test("geometry rejects malformed and overflowing inputs instead of emitting NaN", () => {
  for (const change of [
    { count: NaN },
    { count: -1 },
    { count: 1.5 },
    { count: Infinity },
    { cardWidth: 0 },
    { cardWidth: Infinity },
    { gap: -1 },
    { gap: NaN },
    { viewportWidth: 0 },
    { viewportWidth: Infinity },
    { offset: NaN },
    { previewSlot: -1 },
    { previewSlot: 4 },
    { previewSlot: 1.5 },
    { cardWidth: Number.MAX_VALUE },
  ]) {
    const bad = { ...layout, ...change }
    assert.throws(() => insertionIndex(10, bad), RangeError)
    assert.throws(() => clampOffset(0, bad), RangeError)
    assert.throws(() => offsetToReveal(1, bad), RangeError)
    assert.throws(() => geometry.visibleConfirmedRange(bad), RangeError)
    assert.throws(() => geometry.confirmedCardStart(0, bad), RangeError)
  }
  for (const bad of [NaN, Infinity, -Infinity]) {
    assert.throws(() => insertionIndex(bad, layout), RangeError)
    assert.throws(() => clampOffset(bad, layout), RangeError)
  }
  for (const bad of [-1, 4, 0.5, NaN])
    assert.throws(() => offsetToReveal(bad, layout), RangeError)
  assert.throws(() => overviewMarks(Infinity, 0, 1), RangeError)
  assert.throws(() => overviewMarks(5, 2, 1), RangeError)
  assert.throws(() => overviewMarks(5, 0, NaN), RangeError)
  assert.throws(() => overviewMarks(5, 0, 1, 0), RangeError)
})

test("finite large preview reveal does not overflow its midpoint", () => {
  assert.equal(
    offsetToReveal(1, {
      count: 1,
      cardWidth: 8e307,
      gap: 0,
      viewportWidth: 100,
      offset: 0,
      previewSlot: 1,
    }),
    1.2e308,
  )
})
