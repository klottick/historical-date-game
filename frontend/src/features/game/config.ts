import type {
  GameConfig,
  GameOptions,
  YearInput,
} from "../../client/types.gen.ts"

export function parseSafeInteger(text: string): number {
  // Validate the original digits before JS can round a fractional or int64 input.
  if (!/^\d+$/.test(text)) return NaN
  const value = Number(text)
  return Number.isSafeInteger(value) ? value : NaN
}

function validYear(year: YearInput): boolean {
  return (
    Number.isSafeInteger(year.value) &&
    year.value > 0 &&
    (year.era === "BCE" || year.era === "CE")
  )
}

function yearIndex(year: YearInput): number {
  return year.era === "BCE" ? 1 - year.value : year.value
}

export function formatYear(year: YearInput): string {
  if (!validYear(year))
    throw new Error("Year must be a positive safe integer with a BCE or CE era")
  return `${year.value} ${year.era}`
}

export function defaultConfig(options: GameOptions): GameConfig {
  return {
    category_ids: options.categories.map((category) => category.id),
    start: { ...options.start },
    end: { ...options.end },
    min_gap: 1,
  }
}

export function validateConfig(
  config: GameConfig,
  options: GameOptions,
): string[] {
  const errors: string[] = []
  const known = new Set(options.categories.map((category) => category.id))
  if (!config.category_ids.length) errors.push("Choose at least one category.")
  if (
    config.category_ids.some((id) => typeof id !== "string" || !known.has(id))
  ) {
    errors.push("Choose only published categories.")
  }
  const startValid = validYear(config.start)
  const endValid = validYear(config.end)
  if (!startValid || !endValid)
    errors.push(
      "Years must be positive safe whole numbers with BCE or CE eras; there is no civil year zero.",
    )
  if (
    startValid &&
    endValid &&
    yearIndex(config.start) > yearIndex(config.end)
  ) {
    errors.push("Start year must be at or before end year.")
  }
  if (!Number.isSafeInteger(config.min_gap) || config.min_gap < 1)
    errors.push("Minimum year gap must be a safe whole number of at least 1.")
  return errors
}
