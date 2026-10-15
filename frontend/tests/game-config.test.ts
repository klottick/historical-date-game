import assert from "node:assert/strict"
import { test } from "node:test"
import type {
  GameConfig,
  GameOptions,
  YearInput,
} from "../src/client/types.gen.ts"
import {
  defaultConfig,
  formatYear,
  parseSafeInteger,
  validateConfig,
} from "../src/features/game/config.ts"

const options: GameOptions = {
  catalog_release_id: "fixture",
  categories: [
    { id: "births", label: "Births" },
    { id: "politics", label: "Politics" },
  ],
  start: { value: 100, era: "BCE" },
  end: { value: 2026, era: "CE" },
  registration_open: false,
}
const config = (): GameConfig => defaultConfig(options)

test("config_rejects_empty_unknown_and_zero_year", () => {
  for (const category_ids of [[], ["unknown"], [""], [" births"], [true]]) {
    assert.ok(
      validateConfig({ ...config(), category_ids } as GameConfig, options)
        .length,
    )
  }
  for (const value of [
    0,
    -1,
    true,
    1.5,
    "1",
    Number.MAX_SAFE_INTEGER + 1,
    NaN,
    Infinity,
  ]) {
    assert.ok(
      validateConfig(
        { ...config(), start: { value, era: "CE" } } as GameConfig,
        options,
      ).length,
    )
  }
  assert.ok(
    validateConfig(
      { ...config(), start: { value: 1, era: "AD" } } as unknown as GameConfig,
      options,
    ).length,
  )
})

test("UI integer text is checked before floating-point rounding", () => {
  for (const value of [
    "9007199254740992",
    "9007199254740993",
    "9007199254740991.1",
    "1.00000000000000001",
    "1.5",
    "-1",
    "",
    "1e3",
  ]) {
    assert.ok(Number.isNaN(parseSafeInteger(value)), value)
  }
  assert.equal(parseSafeInteger("9007199254740991"), Number.MAX_SAFE_INTEGER)
  assert.equal(parseSafeInteger("1"), 1)
  assert.equal(parseSafeInteger("10"), 10)
  assert.equal(parseSafeInteger("0"), 0) // Config validation rejects civil zero/gap zero.
})

test("era_bounds_and_gap_match_backend", () => {
  for (const [start, end] of [
    [
      { value: 1, era: "CE" },
      { value: 1, era: "BCE" },
    ],
    [
      { value: 1, era: "BCE" },
      { value: 2, era: "BCE" },
    ],
    [
      { value: 2, era: "CE" },
      { value: 1, era: "CE" },
    ],
  ] as [YearInput, YearInput][]) {
    assert.ok(validateConfig({ ...config(), start, end }, options).length)
  }
  for (const min_gap of [0, -1, true, 1.5, "1", Number.MAX_SAFE_INTEGER + 1]) {
    assert.ok(
      validateConfig({ ...config(), min_gap } as GameConfig, options).length,
    )
  }
  const inclusive: GameConfig = {
    ...config(),
    start: { value: 1, era: "BCE" },
    end: { value: 1, era: "CE" },
    min_gap: 10,
  }
  assert.deepEqual(validateConfig(inclusive, options), [])
  assert.equal(formatYear(inclusive.start), "1 BCE")
  assert.equal(formatYear(inclusive.end), "1 CE")
  assert.deepEqual(
    validateConfig({ ...config(), end: config().start }, options),
    [],
  )
  assert.deepEqual(
    validateConfig(
      { ...config(), category_ids: ["births", "births", "politics"] },
      options,
    ),
    [],
  )
})

test("defaults use the full published union, inclusive bounds, and gap one", () => {
  assert.deepEqual(config(), {
    category_ids: ["births", "politics"],
    start: options.start,
    end: options.end,
    min_gap: 1,
  })
  const first = config()
  first.start.value = 20
  assert.equal(options.start.value, 100)
  assert.deepEqual(validateConfig(config(), options), [])
})
