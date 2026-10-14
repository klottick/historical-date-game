import type { APIResponse } from "@playwright/test"
import type { GameOptions } from "../../src/client/types.gen.ts"

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null
const nonempty = (value: unknown) =>
  typeof value === "string" && value.trim().length > 0
const year = (value: unknown) =>
  record(value) &&
  Number.isInteger(value.value) &&
  Number(value.value) > 0 &&
  ["BCE", "CE"].includes(String(value.era))

// Public DTO only. Fail setup explicitly instead of dereferencing error payloads
// or silently substituting an empty catalog and skipping actual backend coverage.
export async function readGameOptions(
  response: Pick<APIResponse, "status" | "json">,
): Promise<GameOptions> {
  const status = response.status()
  if (status !== 200) {
    const body: unknown = await response.json().catch(() => null)
    const code =
      record(body) && record(body.detail) ? body.detail.code : undefined
    throw new Error(
      `games/options setup: HTTP ${status}; ${String(code ?? "no error code")}`,
    )
  }
  const body: unknown = await response.json()
  if (
    !record(body) ||
    !nonempty(body.catalog_release_id) ||
    !Array.isArray(body.categories) ||
    body.categories.length === 0 ||
    !body.categories.every(
      (category: unknown) =>
        record(category) && nonempty(category.id) && nonempty(category.label),
    ) ||
    !year(body.start) ||
    !year(body.end) ||
    typeof body.registration_open !== "boolean"
  ) {
    throw new Error(
      "Invalid public games/options schema; provision the verified browser fixture first",
    )
  }
  return body as GameOptions
}
