import { expect, test } from "@playwright/test"
import type { RunPublic } from "../src/client"
import { keyboardPreview } from "../tests/utils/gameBoard"

test("compiled release plays, reloads and enforces the guest/admin boundary", async ({
  page,
}) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))
  await page.goto("/")
  await expect(
    page.getByRole("heading", { name: "Historical Date Game", exact: true }),
  ).toBeVisible()
  await expect(page.getByText(/Welcome! Play without an account/)).toBeVisible()
  await page.goto("/freeplay")
  const startResponse = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" && r.url().endsWith("/games/freeplay"),
  )
  await page
    .getByRole("button", { name: "Start Freeplay", exact: true })
    .click()
  const started = await startResponse
  expect(started.status()).toBe(200)
  const run: RunPublic = await started.json()
  expect(Object.keys(run.pending ?? {}).sort()).toEqual([
    "category_ids",
    "event_id",
    "media",
    "prompt",
  ])
  const pending = page.getByTestId("pending-card")
  await expect(pending).toContainText("Year hidden")
  await expect
    .poll(() =>
      pending
        .locator("img")
        .evaluate(
          (img: HTMLImageElement) => img.complete && img.naturalWidth > 0,
        ),
    )
    .toBe(true)
  await page
    .getByRole("button", { name: "Credits/Sources", exact: true })
    .click()
  await expect(page.getByRole("dialog")).toContainText("CC0")
  await page.keyboard.press("Escape")
  await keyboardPreview(page, 0)
  const placement = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/placements"),
  )
  await page.getByRole("button", { name: "Confirm", exact: true }).click()
  expect((await placement).status()).toBe(200)
  await expect(page.getByTestId("run-revision")).toHaveText("Revision: 1")
  await page.reload()
  await expect(page.getByTestId("run-revision")).toHaveText("Revision: 1")
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(page.viewportSize()?.width ?? 0)
  await page.goto("/admin")
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByTestId("email-input")).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Log In", exact: true }),
  ).toBeVisible()
  expect(errors).toEqual([])
})
