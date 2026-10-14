// Node runner only. The browser receives public DTOs and chosen indices, not answers.
import { chmodSync } from "node:fs"
import { expect, type Page, type TestInfo } from "@playwright/test"
import type { GameSessionPublic, RunPublic } from "../src/client/types.gen"
import { boardEvidence } from "../tests/utils/boardEvidence"

export { ownedBackend } from "../tests/utils/ownedVerification"

import { loadCatalog } from "../tests-real-catalog/catalog"

export async function game(
  page: Page,
  path: string,
  context?: GameSessionPublic,
  data?: unknown,
) {
  return page.evaluate(
    async ({ path, context, data }) => {
      const response = await fetch(`/api/v1/games/${path}`, {
        method: data === undefined ? "GET" : "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-Game-Request": "1",
          ...(context ? { "X-Game-Context": context.context_id } : {}),
          ...(localStorage.getItem("access_token")
            ? {
                Authorization: `Bearer ${localStorage.getItem("access_token")}`,
              }
            : {}),
        },
        ...(data === undefined ? {} : { body: JSON.stringify(data) }),
      })
      return { status: response.status, body: await response.json() }
    },
    { path, context, data },
  )
}
export async function session(page: Page): Promise<GameSessionPublic> {
  const response = await game(page, "session")
  expect(response.status).toBe(200)
  return response.body
}
export async function ready(page: Page) {
  await page.goto("/")
  await expect(page.getByText(/Welcome! Play without an account/)).toBeVisible()
  const options = await game(page, "options")
  expect(options.status).toBe(200)
  return {
    identity: await session(page),
    catalog: loadCatalog(options.body.catalog_release_id),
  }
}
export async function start(
  page: Page,
  mode: "daily" | "freeplay" = "freeplay",
): Promise<RunPublic> {
  await page.goto(`/${mode}`)
  const button = page.getByRole("button", {
    name: mode === "daily" ? "Start Daily" : "Start Freeplay",
    exact: true,
  })
  await expect(button).toBeEnabled()
  const response = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" && r.url().endsWith(`/games/${mode}`),
  )
  await button.click()
  const result = await response
  expect(result.status()).toBe(200)
  const run: RunPublic = await result.json()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${run.revision}`,
  )
  return run
}
export function correctIndex(run: RunPublic, years: Map<string, number>) {
  const answer = years.get(run.pending!.event_id)
  expect(answer).toBeDefined()
  return run.timeline.filter(
    (card) =>
      (card.year.era === "CE" ? card.year.value : 1 - card.year.value) <
      answer!,
  ).length
}
export async function lock(page: Page): Promise<RunPublic> {
  const response = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/placements"),
  )
  await page.getByRole("button", { name: "Lock it in", exact: true }).click()
  const result = await response
  expect(result.status()).toBe(200)
  const run: RunPublic = await result.json()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${run.revision}`,
  )
  return run
}
export async function screenshot(page: Page, info: TestInfo, state: string) {
  const path = `${boardEvidence}/${info.testId.replace(/[^a-zA-Z0-9_-]/g, "_")}-${state}.png`
  await page.screenshot({ path, fullPage: true })
  chmodSync(path, 0o600)
}
