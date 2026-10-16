import { writeFileSync } from "node:fs"
import { expect, test } from "@playwright/test"
import type { PlaceCommand, RunPublic } from "../src/client/types.gen"
import { boardEvidence } from "../tests/utils/boardEvidence"
import {
  assertBoardFits,
  dragPendingToIndex,
  keyboardPreview,
} from "../tests/utils/gameBoard"
import {
  correctIndex,
  game,
  lock,
  ownedBackend,
  ready,
  screenshot,
  session,
  start,
} from "./boardSupport"

// These fail if preview scores, loss is sorted instead of attempted, or controls overflow.
for (const viewport of [
  { width: 1920, height: 900 },
  { width: 1366, height: 768 },
]) {
  test(`guest_sequence_fits_1080p_and_compact ${viewport.width}`, async ({
    page,
  }, info) => {
    await page.setViewportSize(viewport)
    const { identity, catalog } = await ready(page)
    if (info.project.name === "insecure-chromium") {
      expect(
        await page.evaluate(() => ({
          secure: isSecureContext,
          uuid: typeof crypto.randomUUID,
          rng: typeof crypto.getRandomValues,
          idb: typeof indexedDB,
          origin: location.origin,
        })),
      ).toEqual({
        secure: false,
        uuid: "undefined",
        rng: "function",
        idb: "object",
        origin: "http://guest.test:5184",
      })
    }
    for (const mode of ["daily", "freeplay"] as const) {
      let run = await start(page, mode)
      await assertBoardFits(page)
      await screenshot(page, info, `${mode}-start`)
      const posts: unknown[] = []
      const observe = (r: import("@playwright/test").Request) => {
        if (r.method() === "POST" && r.url().endsWith("/placements"))
          posts.push(r.postDataJSON())
      }
      page.on("request", observe)
      await dragPendingToIndex(page, correctIndex(run, catalog.years))
      await assertBoardFits(page)
      expect(posts).toEqual([])
      expect((await game(page, `runs/${run.run_id}`, identity)).body).toEqual(
        run,
      )
      await screenshot(page, info, `${mode}-preview`)
      run = await lock(page)
      expect(run.feedback!.correct).toBe(true)
      expect(run.streak).toBe(1)
      expect(posts).toHaveLength(1)
      await assertBoardFits(page)
      await screenshot(page, info, `${mode}-correct`)
      let wrong = 0
      for (const lives of [2, 1, 0]) {
        wrong = correctIndex(run, catalog.years) === 0 ? 1 : 0
        await keyboardPreview(page, wrong)
        run = await lock(page)
        expect(run.lives_remaining).toBe(lives)
        expect(run.feedback!.correct).toBe(false)
        expect(run.score).toBe(1)
        if (lives > 0) {
          expect(run.status).toBe("active")
          expect(run.streak).toBe(0)
          await page
            .getByRole("button", { name: "Continue", exact: true })
            .click()
        }
      }
      expect(run.status).toBe("lost")
      expect(run.feedback!.attempted_slot).toBe(wrong)
      expect(run.lives_remaining).toBe(0)
      expect(run.streak).toBe(0)
      expect(posts).toHaveLength(4)
      page.off("request", observe)
      await assertBoardFits(page)
      await screenshot(page, info, `${mode}-loss`)
      await page.reload()
      await expect(
        page.locator('.timeline-item[data-wrong="true"]'),
      ).toHaveAttribute("data-display-index", String(wrong))
      await assertBoardFits(page)
      await page
        .getByRole("link", {
          name: mode === "freeplay" ? "New Freeplay" : "Back to Home",
          exact: true,
        })
        .click()
      const next = await start(page)
      expect(next.run_id).not.toBe(run.run_id)
      await assertBoardFits(page)
    }
  })
}

test("real_slot_two_drag_and_repickup", async ({ page }, info) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  const { identity, catalog } = await ready(page)
  let run = await start(page)
  const requests: unknown[] = []
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/placements"))
      requests.push(r.postDataJSON())
  })
  for (let round = 0; round < 3; round++) {
    await dragPendingToIndex(page, 1, info.project.name === "game-mobile")
    await dragPendingToIndex(page, 0, info.project.name === "game-mobile")
    await dragPendingToIndex(
      page,
      run.timeline.length,
      info.project.name === "game-mobile",
    )
    await dragPendingToIndex(page, 1, info.project.name === "game-mobile")
    expect(requests).toHaveLength(round)
    expect((await game(page, `runs/${run.run_id}`, identity)).body).toEqual(run)
    await keyboardPreview(page, correctIndex(run, catalog.years))
    run = await lock(page)
    expect(run.feedback!.correct).toBe(true)
    await assertBoardFits(page)
  }
})

test("wrong_card_survives_lost_response_reload_and_restart", async ({
  page,
}, info) => {
  test.setTimeout(120_000)
  await page.setViewportSize({ width: 1366, height: 768 })
  const { identity, catalog } = await ready(page)
  let run = await start(page)
  await keyboardPreview(page, correctIndex(run, catalog.years))
  run = await lock(page)
  for (const lives of [2, 1]) {
    const wrong = correctIndex(run, catalog.years) === 0 ? 1 : 0
    await keyboardPreview(page, wrong)
    run = await lock(page)
    expect(run.lives_remaining).toBe(lives)
    expect(run.feedback!.correct).toBe(false)
    expect(run.status).toBe("active")
    await page.getByRole("button", { name: "Continue", exact: true }).click()
  }
  const wrong = correctIndex(run, catalog.years) === 0 ? 1 : 0
  const commands: PlaceCommand[] = []
  let committed: RunPublic | undefined
  await page.route("**/placements", async (route) => {
    commands.push(route.request().postDataJSON())
    const response = await route.fetch({
      url: route
        .request()
        .url()
        .replace("http://guest.test:5184/", "http://localhost:5184/"),
    })
    expect(response.status()).toBe(200)
    if (commands.length === 1) {
      committed = await response.json()
      await route.abort("failed")
    } else await route.fulfill({ response })
  })
  await dragPendingToIndex(page, wrong)
  await page.getByRole("button", { name: "Confirm", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Retry same move", exact: true }),
  ).toBeVisible()
  expect(committed!.status).toBe("lost")
  expect(committed!.lives_remaining).toBe(0)
  expect(committed!.score).toBe(1)
  expect(committed!.streak).toBe(0)
  expect(committed!.feedback!.attempted_slot).toBe(wrong)
  await page
    .getByRole("button", { name: "Retry same move", exact: true })
    .click()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${committed!.revision}`,
  )
  expect(commands).toHaveLength(2)
  expect(commands[1]).toEqual(commands[0])
  const before = committed!
  for (const restart of [false, true]) {
    if (restart) {
      ownedBackend("stop")
      ownedBackend("launch")
    }
    await page.reload()
    await expect(
      page.locator('.timeline-item[data-wrong="true"]'),
    ).toHaveAttribute("data-display-index", String(wrong))
    await expect(
      page.locator('.timeline-item[data-wrong="true"]'),
    ).toContainText(
      `${before.feedback!.card.year.value} ${before.feedback!.card.year.era}`,
    )
    await expect(page.locator(".correct-location")).toHaveAttribute(
      "data-correct-slot",
      String(
        before.feedback!.correct_slot +
          (wrong < before.feedback!.correct_slot ? 1 : 0),
      ),
    )
    expect((await game(page, `runs/${run.run_id}`, identity)).body).toEqual(
      before,
    )
    expect(
      (await game(page, `runs/${run.run_id}/placements`, identity, commands[0]))
        .body,
    ).toEqual(before)
    await assertBoardFits(page)
  }
  expect((await game(page, `runs/${run.run_id}`, identity)).body.revision).toBe(
    run.revision + 1,
  )
  writeFileSync(
    `${boardEvidence}/loss-restart-${info.project.name}.json`,
    JSON.stringify(
      {
        commands,
        before,
        after: (await game(page, `runs/${run.run_id}`, identity)).body,
      },
      null,
      2,
    ),
    { mode: 0o600 },
  )
  await screenshot(page, info, "loss-restart")
})

test("long_run_edge_navigation_has_no_scrollbar", async ({ page }, info) => {
  test.setTimeout(120_000)
  await page.setViewportSize({ width: 1366, height: 768 })
  const { identity, catalog } = await ready(page)
  let run = await start(page)
  for (let i = 0; i < 20; i++) {
    await keyboardPreview(page, correctIndex(run, catalog.years))
    run = await lock(page)
    expect(run.status).toBe("active")
    await assertBoardFits(page)
  }
  // Every logical boundary, with native edge panning at each end, remains preview-only.
  await dragPendingToIndex(page, run.timeline.length)
  expect(
    Number(
      await page.locator(".timeline-viewport").getAttribute("data-offset"),
    ),
  ).toBeGreaterThan(0)
  await assertBoardFits(page)
  await screenshot(page, info, "long-last")
  await dragPendingToIndex(page, 0)
  for (let i = 0; i <= run.timeline.length; i++) await keyboardPreview(page, i)
  expect((await game(page, `runs/${run.run_id}`, identity)).body).toEqual(run)
  // The pending card's left edge transitions for 180ms while its independent
  // translateX offset updates synchronously. Wait for that finite transition
  // before asserting the final, stable full-control bounds (never a fixed delay).
  await page.locator(".pending-position").evaluate(async (position) => {
    await Promise.all(
      position.getAnimations().map((animation) => animation.finished),
    )
  })
  await assertBoardFits(page)
})

test("revealed_links_credits_and_pending_privacy", async ({ page }, info) => {
  await page.setViewportSize({ width: 1920, height: 900 })
  const { catalog } = await ready(page)
  let run = await start(page)
  for (let round = 0; round < 3; round++) {
    expect(Object.keys(run.pending!).sort()).toEqual([
      "category_ids",
      "event_id",
      "media",
      "prompt",
    ])
    const pending = page.getByTestId("pending-card")
    await expect(pending).toContainText("Year hidden")
    await expect(
      pending.getByRole("button", { name: "Learn more", exact: true }),
    ).toHaveCount(0)
    await expect(
      pending.locator('a[href*="wikipedia.org"], a[href*="wikidata.org"]'),
    ).toHaveCount(0)
    const credits = page.getByRole("button", {
      name: "Credits/Sources",
      exact: true,
    })
    await credits.click()
    const dialog = page.getByRole("dialog")
    for (const card of [...run.timeline, run.pending!]) {
      const artwork = dialog
        .locator("section")
        .filter({ has: page.getByRole("heading", { name: /^Artwork for / }) })
        .filter({ hasText: card.prompt })
      await expect(artwork).toContainText(card.media.url)
      await expect(artwork).toContainText(card.media.fallback_url)
      for (const credit of card.media.credits) {
        await expect(artwork).toContainText(credit.label)
        if (credit.url)
          await expect(
            artwork
              .getByRole("link", { name: credit.label, exact: true })
              .first(),
          ).toHaveAttribute("href", credit.url)
      }
    }
    await page.keyboard.press("Escape")
    await expect(credits).toBeFocused()
    await keyboardPreview(page, correctIndex(run, catalog.years))
    run = await lock(page)
    const card = run.feedback!.card
    const learn = page
      .locator(`.game-card[data-event-id="${card.event_id}"]`)
      .getByRole("button", { name: "Learn more", exact: true })
    await learn.click()
    if (card.learn_more) {
      const link = dialog.getByRole("link", {
        name:
          card.learn_more.kind === "article"
            ? card.learn_more.label
            : `Source page · ${card.learn_more.label}`,
        exact: true,
      })
      await expect(link).toHaveAttribute("href", card.learn_more.url)
      expect(new URL(card.learn_more.url).protocol).toBe("https:")
      await expect(link).toHaveAttribute("rel", /noopener/)
    }
    await dialog.getByText("Source/provenance details", { exact: true }).click()
    for (const source of card.sources)
      await expect(
        dialog.getByRole("link", { name: source.label, exact: true }).first(),
      ).toHaveAttribute("href", source.url)
    await page.keyboard.press("Escape")
    await expect(learn).toBeFocused()
    await assertBoardFits(page)
  }
  // The image failure must preserve the same asset's full credits in the dialog.
  await page.route("**/media/**/*.svg", (route) => route.abort())
  await page.reload()
  await expect(
    page
      .getByTestId("pending-card")
      .getByRole("img", { name: /Image unavailable/ }),
  ).toBeVisible()
  await page
    .getByRole("button", { name: "Credits/Sources", exact: true })
    .click()
  for (const credit of run.pending!.media.credits)
    await expect(page.getByRole("dialog")).toContainText(credit.label)
  await page.keyboard.press("Escape")
  await screenshot(page, info, "links-fallback")
})

test("identity_change_during_drag_preserves_old_uncertain_command", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  const { identity } = await ready(page)
  const run = await start(page)
  const commands: PlaceCommand[] = []
  const errors: string[] = []
  const lifecycleWarnings: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))
  page.on("console", (message) => {
    if (message.text().includes("useInsertionEffect must not schedule updates"))
      lifecycleWarnings.push(message.text())
  })
  await page.route("**/placements", async (route) => {
    commands.push(route.request().postDataJSON())
    await route.abort("failed")
  })
  await keyboardPreview(page, 1)
  await page.getByRole("button", { name: "Confirm", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Retry same move", exact: true }),
  ).toBeVisible()
  const saved = await page.evaluate(() =>
    Object.fromEntries(
      Object.entries(sessionStorage).filter(
        ([key]) => key.startsWith("game:") && key.includes(":placement:"),
      ),
    ),
  )
  expect(Object.keys(saved)).toHaveLength(1)
  expect(Object.values(saved).map((value) => JSON.parse(value))).toContainEqual(
    commands[0],
  )
  const other = await start(page)
  const tile = (await page.locator(".pending-draggable").boundingBox())!
  const board = (await page.locator(".timeline-viewport").boundingBox())!
  await page.mouse.move(tile.x + 70, tile.y + 70)
  await page.mouse.down()
  await page.mouse.move(tile.x + 82, tile.y + 70)
  await page.mouse.move(board.x + 20, board.y + 90)
  await expect(page.locator(".preview-status")).toContainText("Card lifted")
  // Actual cross-tab identity notification while the native drag is still active.
  await page.evaluate(() => {
    localStorage.setItem("access_token", "expired-token")
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: "access_token",
        newValue: "expired-token",
        storageArea: localStorage,
      }),
    )
  })
  await expect(
    page.getByRole("heading", {
      name: "Game session unavailable",
      exact: true,
    }),
  ).toBeVisible()
  await expect(page.locator(".timeline-viewport")).toHaveCount(0)
  await page.mouse.up()
  expect(commands).toHaveLength(1)
  expect(
    await page.evaluate(() =>
      Object.fromEntries(
        Object.entries(sessionStorage).filter(
          ([key]) => key.startsWith("game:") && key.includes(":placement:"),
        ),
      ),
    ),
  ).toEqual(saved)
  expect(errors).toEqual([])
  writeFileSync(
    `${boardEvidence}/identity-native-drag-${info.project.name}.json`,
    JSON.stringify(
      {
        commands,
        lifecycleWarnings,
        pageErrors: errors,
        oldCommandRetained: true,
      },
      null,
      2,
    ),
    { mode: 0o600 },
  )
  // Returning to the old guest restores, but never automatically resubmits, its exact command.
  await page
    .getByRole("button", { name: "Continue as guest", exact: true })
    .click()
  await expect(page.getByText(/Welcome! Play without an account/)).toBeVisible()
  expect(await session(page)).toEqual(identity)
  await page.goto(`/play/${run.run_id}`)
  await expect(
    page.getByRole("button", { name: "Retry same move", exact: true }),
  ).toBeVisible()
  expect(commands).toHaveLength(1)
  await page.unroute("**/placements")
  const retryResponse = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/placements"),
  )
  await page
    .getByRole("button", { name: "Retry same move", exact: true })
    .click()
  const retried = await retryResponse
  expect(retried.status()).toBe(200)
  expect(retried.request().postDataJSON()).toEqual(commands[0])
  await expect(page.getByTestId("run-revision")).toHaveText("Revision: 1")
  expect(
    (await game(page, `runs/${other.run_id}`, identity)).body.revision,
  ).toBe(0)
})
