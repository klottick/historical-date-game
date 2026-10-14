import { expect, type Page, test } from "@playwright/test"
import {
  controlledBoard,
  controlledRun,
  dragTile,
  keyboardPreview,
} from "./utils/controlledBoard"

async function fitsDesktop(page: Page) {
  const dimensions = await page.evaluate(() => ({
    w: document.documentElement.scrollWidth,
    h: document.documentElement.scrollHeight,
    iw: innerWidth,
    ih: innerHeight,
    x: scrollX,
    y: scrollY,
  }))
  expect(dimensions.w).toBeLessThanOrEqual(dimensions.iw)
  expect(dimensions.h).toBeLessThanOrEqual(dimensions.ih)
  expect([dimensions.x, dimensions.y]).toEqual([0, 0])
  for (const control of await page
    .locator(
      ".placement-actions button, .game-results > a, .game-footer > button, .game-footer > a",
    )
    .all())
    await expect(control).toBeInViewport({ ratio: 1 })
}

test("unavailable_resize_measurement_preserves_last_valid_layout", async ({
  page,
}) => {
  const pageErrors: string[] = []
  page.on("pageerror", (error) => pageErrors.push(error.message))
  const state = await controlledBoard(page, controlledRun(20))
  await keyboardPreview(page, 15)
  const viewport = page.locator(".timeline-viewport")
  const offset = await viewport.getAttribute("data-offset")
  for (const [width, gap] of [
    ["initial", "16px"],
    ["NaNpx", "16px"],
    ["0px", "16px"],
    ["-1px", "16px"],
    ["Infinity", "16px"],
    ["1e308px", "16px"],
    ["230px", "-1px"],
  ]) {
    await viewport.evaluate(
      (element, values) => {
        const node = element as HTMLElement
        node.style.setProperty("--card-width", values[0])
        node.style.setProperty("--card-gap", values[1])
        node.style.right = node.style.right === "1px" ? "2px" : "1px"
      },
      [width, gap],
    )
    await page.evaluate(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    )
    expect(pageErrors).toEqual([])
    await expect(viewport).toHaveAttribute("data-offset", offset!)
    expect((await page.locator(".pending-position").boundingBox())!.width).toBe(
      230,
    )
  }
  await viewport.evaluate((element) => {
    ;(element as HTMLElement).style.display = "none"
  })
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  )
  expect(pageErrors).toEqual([])
  await expect(viewport).toHaveAttribute("data-offset", offset!)
  await viewport.evaluate((element) => {
    const node = element as HTMLElement
    node.style.setProperty("--card-width", "210px")
    node.style.setProperty("--card-gap", "12px")
    node.style.right = "3px"
    node.style.removeProperty("display")
  })
  await expect
    .poll(
      async () =>
        (await page.locator(".pending-position").boundingBox())!.width,
    )
    .toBe(210)
  await keyboardPreview(page, 0)
  expect(pageErrors).toEqual([])
  expect(state.moves).toHaveLength(0)
})

test("tab_reveals_long_sequence_cards_without_native_scroll_or_pointer_drift", async ({
  page,
}) => {
  const state = await controlledBoard(page, controlledRun(100))
  const details = page
    .locator(".timeline-item")
    .getByRole("button", { name: "Learn more", exact: true })
  const viewport = page.locator(".timeline-viewport")
  await details.first().focus()
  for (let index = 0; index <= 15; index++) {
    if (index > 0) await page.keyboard.press("Tab")
    await expect(details.nth(index)).toBeFocused()
    if (index > 0)
      expect(
        await details
          .nth(index)
          .evaluate((element) => element.matches(":focus-visible")),
      ).toBe(true)
    await expect(details.nth(index)).toBeInViewport({ ratio: 1 })
    const geometry = await viewport.evaluate((element, ordinal) => {
      const board = element.getBoundingClientRect()
      const card = element
        .querySelector(`[data-display-index="${ordinal}"]`)!
        .getBoundingClientRect()
      const offset = Number(element.getAttribute("data-offset"))
      return {
        scrollLeft: element.scrollLeft,
        x: card.left - board.left,
        expectedX: ordinal * 246 - offset,
        cardRight: card.right - board.left,
        width: board.width,
      }
    }, index)
    expect(geometry.scrollLeft).toBe(0)
    expect(
      await page
        .locator(".timeline-stage")
        .evaluate((element) => element.scrollLeft),
    ).toBe(0)
    expect(geometry.x).toBeCloseTo(geometry.expectedX, 5)
    expect(geometry.x).toBeGreaterThanOrEqual(0)
    expect(geometry.cardRight).toBeLessThanOrEqual(geometry.width)
  }
  expect(Number(await viewport.getAttribute("data-offset"))).toBeGreaterThan(0)
  await details.nth(15).click()
  await expect(page.getByRole("dialog")).toBeVisible()
  await page.keyboard.press("Escape")
  await expect(details.nth(15)).toBeFocused()
  const tile = (await page.locator(".pending-draggable").boundingBox())!
  const board = (await viewport.boundingBox())!
  const offset = Number(await viewport.getAttribute("data-offset"))
  await page.mouse.move(tile.x + 70, tile.y + 70)
  await page.mouse.down()
  await page.mouse.move(tile.x + 82, tile.y + 70)
  // One target move avoids opening an earlier insertion preview along an
  // interpolated path; this checks the focused transform's pointer alignment.
  await page.mouse.move(board.x + 15 * 246 - offset + 150, board.y + 90)
  await expect(viewport).toHaveAttribute("data-hovered-slot", "16")
  await page.mouse.up()
  await expect(page.locator("[data-preview-slot]")).toHaveAttribute(
    "data-preview-slot",
    "16",
  )
  await details.nth(17).focus()
  await expect(page.locator(".timeline-item").nth(17)).toBeInViewport({
    ratio: 1,
  })
  // Insertion state is already correct; neighbors still have their specified
  // 180ms left transition. Check exact display geometry once that settles.
  await expect
    .poll(() =>
      viewport.evaluate((element) => {
        const card = element.querySelector('[data-display-index="17"]')!
        return (
          card.getBoundingClientRect().left -
          element.getBoundingClientRect().left -
          (18 * 246 - Number(element.getAttribute("data-offset")))
        )
      }),
    )
    .toBeCloseTo(0, 4)
  const previewGeometry = await viewport.evaluate((element) => {
    const card = element.querySelector('[data-display-index="17"]')!
    return {
      native: element.scrollLeft,
      offset: Number(element.getAttribute("data-offset")),
      x:
        card.getBoundingClientRect().left -
        element.getBoundingClientRect().left,
    }
  })
  expect(previewGeometry.native).toBe(0)
  expect(previewGeometry.x).toBeCloseTo(18 * 246 - previewGeometry.offset, 4)
  await details.nth(17).click()
  await expect(page.getByRole("dialog")).toBeVisible()
  await page.keyboard.press("Escape")
  await expect(details.nth(17)).toBeFocused()
  await expect(page.locator("[data-preview-slot]")).toHaveAttribute(
    "data-preview-slot",
    "16",
  )
  expect(state.moves).toHaveLength(0)
  await page.getByRole("button", { name: "Lock it in", exact: true }).click()
  await expect(page.getByTestId("run-revision")).toHaveText("Revision: 1")
  expect(state.moves).toHaveLength(1)
  expect(state.moves[0].slot).toBe(16)
})

for (const size of [
  { width: 1920, height: 900 },
  { width: 1366, height: 768 },
])
  test(`legacy_loss_fits_whole_desktop_controls ${size.width}`, async ({
    page,
  }) => {
    await page.setViewportSize(size)
    const run = controlledRun()
    run.status = "lost"
    run.pending = null
    run.feedback = {
      correct: false,
      card: {
        ...run.timeline[0],
        event_id: "legacy-wrong",
        prompt: "Legacy wrong event",
      },
      attempted_slot: null,
      correct_slot: 3,
    }
    await controlledBoard(page, run, false)
    await page.goto(`/play/${run.run_id}`)
    await expect(
      page.getByText("Old placement position unavailable.", { exact: true }),
    ).toBeInViewport({ ratio: 1 })
    await expect(page.locator(".legacy-loss .game-card")).toBeInViewport({
      ratio: 1,
    })
    await expect(page.locator(".timeline-item").first()).toBeInViewport({
      ratio: 1,
    })
    await expect(
      page.getByRole("button", { name: "Run details", exact: true }),
    ).toBeInViewport({ ratio: 1 })
    await expect(page.locator(".timeline-item[data-wrong=true]")).toHaveCount(0)
    await fitsDesktop(page)
    await page.reload()
    await expect(page.locator(".legacy-loss .game-card")).toBeInViewport({
      ratio: 1,
    })
    await fitsDesktop(page)
  })

test("drag_actual_tile_into_second_boundary", async ({ page }) => {
  const state = await controlledBoard(page)
  await dragTile(page, 1)
  await expect(
    page.getByRole("button", { name: "Lock it in", exact: true }),
  ).toBeEnabled()
  expect(state.moves).toHaveLength(0)
  await page.getByRole("button", { name: "Lock it in", exact: true }).click()
  await expect(page.getByTestId("run-revision")).toContainText("1")
  expect(state.moves).toHaveLength(1)
  expect(state.moves[0].slot).toBe(1)
})
test("preview_can_be_picked_up_repositioned_and_returned", async ({ page }) => {
  const state = await controlledBoard(page)
  await dragTile(page, 1)
  await expect(page.locator(".pending-draggable")).toHaveCount(1)
  await dragTile(page, 2)
  await expect(page.locator(".pending-draggable")).toHaveCount(1)
  await page.getByRole("button", { name: "Return to hand" }).click()
  await expect(page.locator("[data-preview-slot]")).toHaveCount(0)
  await expect(page.locator(".pending-draggable")).toHaveCount(1)
  expect(state.moves).toHaveLength(0)
})
test("keyboard_placement_uses_same_tile", async ({ page }) => {
  const state = await controlledBoard(page)
  await keyboardPreview(page, 3)
  await expect(page.locator(".pending-draggable")).toBeFocused()
  await page.keyboard.press("Enter")
  await page.keyboard.press("Home")
  await page.keyboard.press("Escape")
  await expect(page.locator("[data-preview-slot]")).toHaveAttribute(
    "data-preview-slot",
    "3",
  )
  expect(state.moves).toHaveLength(0)
})
test("details_tap_never_drags_or_scores", async ({ page }) => {
  const state = await controlledBoard(page)
  await page.getByRole("button", { name: "Learn more" }).first().click()
  await expect(page.getByRole("dialog")).toBeVisible()
  await expect(
    page.locator(".pending-draggable[data-dragging=true]"),
  ).toHaveCount(0)
  expect(state.moves).toHaveLength(0)
})
test("all_boundaries_reachable_after_auto_pan", async ({ page }) => {
  const state = await controlledBoard(page, controlledRun(12))
  const tile = await page.locator(".pending-draggable").boundingBox()
  const board = await page.locator(".timeline-viewport").boundingBox()
  if (!tile || !board) throw new Error("No geometry")
  await page.mouse.move(tile.x + 60, tile.y + 70)
  await page.mouse.down()
  await page.mouse.move(tile.x + 75, tile.y + 70)
  await page.mouse.move(board.x + board.width - 4, board.y + 90, { steps: 10 })
  await expect(page.locator(".timeline-viewport")).toHaveAttribute(
    "data-hovered-slot",
    "12",
    { timeout: 15000 },
  )
  await page.mouse.up()
  await expect(page.locator("[data-preview-slot]")).toHaveAttribute(
    "data-preview-slot",
    "12",
  )
  for (let slot = 0; slot <= 12; slot++) await keyboardPreview(page, slot)
  expect(state.moves).toHaveLength(0)
  expect(await page.evaluate(() => [scrollX, scrollY])).toEqual([0, 0])
})
for (const size of [
  { width: 1920, height: 900 },
  { width: 1366, height: 768 },
])
  test(`full_sequence_fits_desktop_viewports ${size.width}`, async ({
    page,
  }) => {
    await page.setViewportSize(size)
    const state = await controlledBoard(page, controlledRun(), false)
    await page.goto("/freeplay")
    await expect(
      page.getByRole("button", { name: "Start Freeplay", exact: true }),
    ).toBeInViewport()
    await fitsDesktop(page)
    await page
      .getByRole("button", { name: "Start Freeplay", exact: true })
      .click()
    await expect(page.locator(".pending-draggable")).toBeVisible()
    await fitsDesktop(page)
    for (const slot of [1, 0]) {
      await keyboardPreview(page, slot)
      await fitsDesktop(page)
      await expect(
        page.getByRole("button", { name: "Lock it in", exact: true }),
      ).toBeInViewport()
      await page
        .getByRole("button", { name: "Lock it in", exact: true })
        .click()
      await expect(page.getByTestId("run-revision")).toContainText(
        String(state.moves.length),
      )
      await fitsDesktop(page)
      if (state.moves.length === 1) {
        await expect(page.getByTestId("move-feedback")).toContainText("Correct")
        await expect(page.locator(".pending-draggable")).toContainText(
          "Next public prompt",
        )
      }
    }
    await expect(page.getByText("Wrong", { exact: true })).toBeInViewport()
    await expect(
      page.getByRole("link", { name: "New Freeplay", exact: true }),
    ).toBeInViewport()
    await page.getByRole("link", { name: "New Freeplay", exact: true }).click()
    await fitsDesktop(page)
    await page
      .getByRole("button", { name: "Start Freeplay", exact: true })
      .click()
    await expect(page.locator(".pending-draggable")).toBeVisible()
    expect(state.starts).toBe(2)
    expect(state.moves).toHaveLength(2)
    await fitsDesktop(page)
  })
test("long_prompt_keeps_controls_and_full_text_accessible", async ({
  page,
}) => {
  const run = controlledRun()
  run.pending!.prompt = "Long public pending description. ".repeat(60)
  const state = await controlledBoard(page, run)
  await page.getByRole("button", { name: "Read full prompt" }).click()
  await expect(page.getByRole("dialog")).toContainText(
    run.pending!.prompt.trim(),
  )
  await expect(page.getByRole("dialog")).not.toContainText("900 CE")
  await page.keyboard.press("Escape")
  await page.locator(".pending-draggable").focus()
  await expect(page.locator(".pending-draggable h3")).toHaveText(
    run.pending!.prompt.trim(),
  )
  expect(
    await page
      .locator(".pending-draggable h3")
      .evaluate((e) => getComputedStyle(e).overflowY),
  ).toBe("auto")
  await keyboardPreview(page, 1)
  await expect(
    page.getByRole("button", { name: "Lock it in", exact: true }),
  ).toBeInViewport()
  expect(state.moves).toHaveLength(0)
  await expect(
    page
      .locator(".pending-draggable")
      .getByRole("button", { name: "Learn more" }),
  ).toHaveCount(0)
  await page.getByRole("button", { name: "Credits/Sources" }).click()
  await expect(page.getByRole("dialog")).not.toContainText("900 CE")
  await expect(
    page.getByRole("dialog").getByRole("heading", { name: /Event sources$/ }),
  ).toHaveCount(3)
})
test("loss_reload_retains_attempted_position_and_correct_marker", async ({
  page,
}) => {
  const run = controlledRun()
  run.status = "lost"
  run.pending = null
  run.feedback = {
    correct: false,
    card: { ...run.timeline[0], event_id: "wrong", prompt: "Wrong event" },
    attempted_slot: 1,
    correct_slot: 3,
  }
  await controlledBoard(page, run, false)
  await page.goto(`/play/${run.run_id}`)
  for (let i = 0; i < 2; i++) {
    await expect(
      page.locator(".timeline-item[data-wrong=true]"),
    ).toHaveAttribute("data-display-index", "1")
    await expect(page.locator(".correct-location")).toHaveAttribute(
      "data-correct-slot",
      "4",
    )
    if (!i) await page.reload()
  }
})
test("credits_retain_every_license_and_fallback_association", async ({
  page,
}) => {
  await controlledBoard(page)
  await page.getByRole("button", { name: "Credits/Sources" }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog).toContainText("Public pending prompt")
  await expect(dialog).toContainText("Fallback artwork · Historical Date Game")
  await expect(
    dialog.getByRole("link", { name: "Illustrator · CC BY 4.0" }).first(),
  ).toHaveAttribute("href", "https://creativecommons.org/licenses/by/4.0/")
  await expect(dialog).toContainText("Dataset provenance")
  await expect(dialog).toContainText("Wikipedia calendar lineage · CC BY-SA")
  await expect(dialog).toContainText("/assets/game-fallback.svg")
})
test("article_vs_source_labels_are_honest", async ({ page }) => {
  await controlledBoard(page)
  await page.getByRole("button", { name: "Learn more" }).first().click()
  await expect(
    page
      .getByRole("dialog")
      .getByRole("link", { name: "Wikipedia article", exact: true }),
  ).toHaveAttribute("href", "https://en.wikipedia.org/wiki/History")
  await page.keyboard.press("Escape")
  await page.getByRole("button", { name: "Learn more" }).nth(1).click()
  await expect(
    page.getByRole("dialog").getByRole("link", { name: /Source page/ }),
  ).toHaveAttribute("href", "https://en.wikipedia.org/wiki/January_1")
})
test("dialog_focus_returns_without_changing_preview", async ({ page }) => {
  const state = await controlledBoard(page)
  await keyboardPreview(page, 1)
  const trigger = page.getByRole("button", { name: "Credits/Sources" })
  await trigger.click()
  await expect(page.getByRole("dialog")).toBeVisible()
  await page.keyboard.press("Escape")
  await expect(trigger).toBeFocused()
  await expect(page.locator("[data-preview-slot]")).toHaveAttribute(
    "data-preview-slot",
    "1",
  )
  expect(state.moves).toHaveLength(0)
})
test("owner_or_revision_change_cancels_pan_without_clearing_command", async ({
  page,
}) => {
  const state = await controlledBoard(page)
  await keyboardPreview(page, 1)
  state.failMove = true
  await page.getByRole("button", { name: "Lock it in", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Retry same move" }),
  ).toBeVisible()
  const saved = await page.evaluate(() =>
    sessionStorage.getItem(
      "game:controlled-board:placement:11111111-1111-4111-8111-111111111111",
    ),
  )
  await expect(page.locator(".pending-draggable")).toHaveAttribute(
    "aria-disabled",
    "true",
  )
  await page.getByRole("button", { name: "Retry same move" }).click()
  await expect.poll(() => state.moves.length).toBe(2)
  expect(state.moves[1]).toEqual(state.moves[0])
  expect(JSON.parse(saved!)).toEqual(state.moves[0])
  await page.evaluate(() => {
    localStorage.setItem("access_token", "different")
  })
  await expect(page.locator(".pending-draggable")).toHaveCount(0)
  expect(
    await page.evaluate(() =>
      sessionStorage.getItem(
        "game:controlled-board:placement:11111111-1111-4111-8111-111111111111",
      ),
    ),
  ).toBe(saved)
})
test("interrupted_touch_and_reduced_motion_do_not_strand_preview", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 1366, height: 768 },
    hasTouch: true,
    deviceScaleFactor: 2,
    reducedMotion: "reduce",
  })
  const page = await context.newPage()
  const state = await controlledBoard(page)
  await keyboardPreview(page, 1)
  const tile = await page.locator(".pending-draggable").boundingBox()
  if (!tile) throw new Error("No tile")
  const cdp = await context.newCDPSession(page)
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [{ x: tile.x + 70, y: tile.y + 70 }],
  })
  await page.waitForTimeout(250)
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchMove",
    touchPoints: [{ x: tile.x + 100, y: tile.y + 80 }],
  })
  await expect(page.locator(".timeline-viewport")).toHaveAttribute(
    "data-hovered-slot",
    "1",
  )
  await expect(
    page.getByRole("button", { name: "Lock it in", exact: true }),
  ).toBeDisabled()
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchCancel",
    touchPoints: [],
  })
  await expect(page.locator("[data-preview-slot]")).toHaveAttribute(
    "data-preview-slot",
    "1",
  )
  await expect(
    page.getByRole("button", { name: "Lock it in", exact: true }),
  ).toBeEnabled()
  expect(state.moves).toHaveLength(0)
  await context.close()
})
test("committed_response_loss_retries_exact_saved_command_and_scores_once", async ({
  page,
}) => {
  const state = await controlledBoard(page)
  await dragTile(page, 1)
  expect(state.moves).toHaveLength(0)
  state.loseResponse = true
  await page.getByRole("button", { name: "Lock it in", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Retry same move", exact: true }),
  ).toBeVisible()
  await expect(page.getByTestId("run-revision")).toHaveText("Revision: 0")
  const saved = await page.evaluate(() =>
    sessionStorage.getItem(
      "game:controlled-board:placement:11111111-1111-4111-8111-111111111111",
    ),
  )
  expect(JSON.parse(saved!)).toEqual(state.moves[0])
  expect(state.scoredOutcomes).toBe(1)
  await expect(page.locator(".pending-draggable")).toHaveAttribute(
    "aria-disabled",
    "true",
  )
  await expect(
    page.getByRole("button", { name: "Return to hand", exact: true }),
  ).toBeDisabled()
  await page
    .getByRole("button", { name: "Retry same move", exact: true })
    .click()
  await expect(page.getByTestId("run-revision")).toHaveText("Revision: 1")
  expect(state.moves).toHaveLength(2)
  expect(state.moves[1]).toEqual(state.moves[0])
  expect(state.scoredOutcomes).toBe(1)
  await expect(page.getByText("Streak: 1", { exact: true })).toBeVisible()
  expect(
    await page.evaluate(() =>
      sessionStorage.getItem(
        "game:controlled-board:placement:11111111-1111-4111-8111-111111111111",
      ),
    ),
  ).toBeNull()
})
test("outside_pointer_drop_preserves_the_previous_preview", async ({
  page,
}) => {
  const state = await controlledBoard(page)
  await keyboardPreview(page, 1)
  const tile = (await page.locator(".pending-draggable").boundingBox())!
  await page.mouse.move(tile.x + 70, tile.y + 70)
  await page.mouse.down()
  await page.mouse.move(tile.x + 82, tile.y + 70)
  await page.mouse.move(30, 20, { steps: 12 })
  await expect(page.locator(".timeline-viewport")).toHaveAttribute(
    "data-hovered-slot",
    "",
  )
  await page.mouse.up()
  await expect(page.locator("[data-preview-slot]")).toHaveAttribute(
    "data-preview-slot",
    "1",
  )
  await expect(
    page.getByRole("button", { name: "Lock it in", exact: true }),
  ).toBeEnabled()
  expect(state.moves).toHaveLength(0)
})
test("owner_change_interrupts_active_native_pan", async ({ page }) => {
  const state = await controlledBoard(page, controlledRun(20))
  const tile = (await page.locator(".pending-draggable").boundingBox())!
  const board = (await page.locator(".timeline-viewport").boundingBox())!
  await page.mouse.move(tile.x + 70, tile.y + 70)
  await page.mouse.down()
  await page.mouse.move(tile.x + 82, tile.y + 70)
  await page.mouse.move(board.x + board.width - 4, board.y + 90)
  await expect
    .poll(async () =>
      Number(
        await page.locator(".timeline-viewport").getAttribute("data-offset"),
      ),
    )
    .toBeGreaterThan(20)
  await page.evaluate(() => localStorage.setItem("access_token", "different"))
  await expect(page.locator(".timeline-viewport")).toHaveCount(0)
  await page.mouse.up()
  expect(state.moves).toHaveLength(0)
})
for (const count of [100, 500])
  test(`synthetic long sequence ${count}`, async ({ page }) => {
    const state = await controlledBoard(page, controlledRun(count))
    await page.locator(".pending-draggable").focus()
    await page.keyboard.press("Space")
    await page.keyboard.press("End")
    await page.keyboard.press("Space")
    await expect(page.locator("[data-preview-slot]")).toHaveAttribute(
      "data-preview-slot",
      String(count),
    )
    await expect(page.locator(".pending-draggable")).toBeInViewport()
    expect(await page.locator(".overview-mark").count()).toBeLessThanOrEqual(80)
    await expect(
      page.getByRole("button", { name: "Lock it in", exact: true }),
    ).toBeInViewport()
    expect(state.moves).toHaveLength(0)
  })

test("late_loss_centers_the_entire_wrong_card_without_fabricating_a_visible_correct_boundary", async ({
  page,
}) => {
  const run = controlledRun(100)
  run.status = "lost"
  run.pending = null
  run.feedback = {
    correct: false,
    card: { ...run.timeline[0], event_id: "late-wrong" },
    attempted_slot: 90,
    correct_slot: 0,
  }
  await controlledBoard(page, run, false)
  await page.goto(`/play/${run.run_id}`)
  const wrong = page.locator(".timeline-item[data-wrong=true]")
  await expect(wrong).toBeInViewport({ ratio: 1 })
  const board = await page.locator(".timeline-viewport").boundingBox()
  if (!board) throw new Error("Missing loss geometry")
  await expect
    .poll(async () => {
      const card = (await wrong.boundingBox())!
      return Math.abs(card.x + card.width / 2 - board.x - board.width / 2)
    })
    .toBeLessThan(2)
  await expect(page.locator(".correct-location")).not.toBeInViewport()
  await expect(
    page.getByRole("img", { name: "Correct location", exact: true }),
  ).toBeVisible()
})

test("keyboard_lift_moves_the_actual_tile_before_drop", async ({ page }) => {
  const state = await controlledBoard(page)
  await page.locator(".pending-draggable").focus()
  await page.keyboard.press("Space")
  await page.keyboard.press("ArrowRight")
  const tile = await page.locator(".pending-draggable").boundingBox()
  const viewport = await page.locator(".timeline-viewport").boundingBox()
  if (!tile || !viewport) throw new Error("Missing tile geometry")
  await expect
    .poll(
      async () => (await page.locator(".pending-draggable").boundingBox())!.x,
    )
    .toBe(viewport.x + 246)
  await page.keyboard.press("Escape")
  await expect(page.locator("[data-preview-slot]")).toHaveCount(0)
  expect(state.moves).toHaveLength(0)
})

test("one_live_tile_has_a_readable_frame_while_pointer_dragging", async ({
  page,
}) => {
  const state = await controlledBoard(page)
  const tile = await page.locator(".pending-draggable").boundingBox()
  const board = await page.locator(".timeline-viewport").boundingBox()
  if (!tile || !board) throw new Error("No geometry")
  await page.mouse.move(tile.x + 70, tile.y + 70)
  await page.mouse.down()
  await page.mouse.move(tile.x + 82, tile.y + 70)
  await page.mouse.move(board.x + 400, board.y + 90)
  await expect(page.locator(".pending-draggable")).toHaveCount(1)
  expect(
    await page
      .locator(".pending-draggable")
      .evaluate((e) => getComputedStyle(e).opacity),
  ).toBe("1")
  expect(
    await page
      .locator(".pending-draggable .game-card")
      .evaluate((e) => getComputedStyle(e).backgroundColor),
  ).toBe("rgb(247, 240, 223)")
  await page.keyboard.press("Escape")
  await page.mouse.up()
  await expect(page.locator(".pending-draggable")).toHaveCount(1)
  expect(state.moves).toHaveLength(0)
})

test("small_screen_keeps_a_readable_timeline_window_and_accessible_controls", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await controlledBoard(page)
  const width = await page
    .locator(".timeline-viewport")
    .evaluate((e) => e.clientWidth)
  expect(width).toBeGreaterThanOrEqual(200)
  await keyboardPreview(page, 1)
  await expect(page.locator(".pending-draggable")).toBeInViewport({ ratio: 1 })
  await expect(
    page.getByRole("button", { name: "Lock it in", exact: true }),
  ).toBeVisible()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true)
  expect(state.moves).toHaveLength(0)
})

for (const viewport of [
  { width: 1366, height: 768 },
  { width: 390, height: 844 },
])
  test(`native_touch_drop_reaches_each_boundary_without_scoring_before_lock ${viewport.width}`, async ({
    browser,
  }) => {
    const context = await browser.newContext({
      viewport,
      hasTouch: true,
      deviceScaleFactor: 2,
    })
    const page = await context.newPage()
    const state = await controlledBoard(page)
    for (let slot = 0; slot <= 3; slot++) {
      await dragTile(page, slot, true)
      expect(state.moves).toHaveLength(0)
      if (slot !== 3)
        await page
          .getByRole("button", { name: "Return to hand", exact: true })
          .click()
    }
    await page.getByRole("button", { name: "Lock it in", exact: true }).click()
    await expect(page.getByTestId("run-revision")).toHaveText("Revision: 1")
    expect(state.moves).toHaveLength(1)
    expect(state.moves[0].slot).toBe(3)
    await context.close()
  })

test("authoritative_revision_interrupts_native_pan_and_does_not_preview_or_score", async ({
  page,
}) => {
  const state = await controlledBoard(page, controlledRun(20))
  const tile = await page.locator(".pending-draggable").boundingBox()
  const board = await page.locator(".timeline-viewport").boundingBox()
  if (!tile || !board) throw new Error("Missing geometry")
  await page.mouse.move(tile.x + 70, tile.y + 70)
  await page.mouse.down()
  await page.mouse.move(tile.x + 82, tile.y + 70)
  await page.mouse.move(board.x + board.width - 4, board.y + 90)
  await expect
    .poll(async () =>
      Number(
        await page.locator(".timeline-viewport").getAttribute("data-offset"),
      ),
    )
    .toBeGreaterThan(20)
  state.run = { ...state.run, revision: 1 }
  await page.evaluate(() => window.dispatchEvent(new Event("visibilitychange")))
  await expect(page.getByTestId("run-revision")).toHaveText("Revision: 1")
  await expect(page.locator(".timeline-viewport")).toHaveAttribute(
    "data-hovered-slot",
    "",
  )
  const offset = await page
    .locator(".timeline-viewport")
    .getAttribute("data-offset")
  await page.waitForTimeout(250) // More than one pan frame: assert resources stopped.
  await expect(page.locator(".timeline-viewport")).toHaveAttribute(
    "data-offset",
    offset!,
  )
  await page.mouse.up()
  await expect(page.locator("[data-preview-slot]")).toHaveCount(0)
  expect(state.moves).toHaveLength(0)
})

test("daily_start_and_finished_navigation_remain_bounded_with_long_leaderboard", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  const state = await controlledBoard(page, controlledRun(), false)
  await page.goto("/daily")
  await expect(
    page.getByRole("button", { name: "Start Daily", exact: true }),
  ).toBeInViewport()
  expect(
    await page.evaluate(() => document.documentElement.scrollHeight),
  ).toBeLessThanOrEqual(768)
  await page.getByRole("button", { name: "Start Daily", exact: true }).click()
  for (const slot of [1, 0]) {
    await keyboardPreview(page, slot)
    await page.getByRole("button", { name: "Lock it in", exact: true }).click()
    await expect(page.getByTestId("run-revision")).toHaveText(
      `Revision: ${state.moves.length}`,
    )
  }
  await expect(
    page.getByRole("link", { name: "Daily challenge", exact: true }),
  ).toBeInViewport()
  await expect(
    page.getByRole("link", { name: "New Freeplay", exact: true }),
  ).toHaveCount(0)
  await page
    .getByRole("button", { name: "Run details & leaderboard", exact: true })
    .click()
  await expect(page.getByRole("dialog")).toContainText("Public player 49")
  await page.keyboard.press("Escape")
  await expect(
    page.getByRole("button", {
      name: "Run details & leaderboard",
      exact: true,
    }),
  ).toBeFocused()
  await page.getByRole("link", { name: "Daily challenge", exact: true }).click()
  await expect(
    page.getByText("Public player 49", { exact: true }),
  ).toBeAttached()
  await expect(
    page.getByRole("link", { name: "View Result", exact: true }),
  ).toBeInViewport()
  expect(
    await page.evaluate(() => document.documentElement.scrollHeight),
  ).toBeLessThanOrEqual(768)
})
