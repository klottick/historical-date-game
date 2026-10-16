import { chmodSync } from "node:fs"
import { resolve } from "node:path"
import { expect, type Page, test } from "@playwright/test"
import { boardEvidence } from "./utils/boardEvidence"
import {
  controlledBoard,
  controlledRun,
  dragTile,
  keyboardPreview,
  media,
  revealed,
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
      ".pending-confirm, .placement-actions button, .game-results > a, .game-footer > button, .game-footer > a",
    )
    .all())
    await expect(control).toBeInViewport({ ratio: 1 })
}

async function settleBoard(page: Page) {
  await page.evaluate(async () => {
    await Promise.all(
      document.documentElement
        .getAnimations({ subtree: true })
        .map((animation) => animation.finished.catch(() => undefined)),
    )
  })
}

async function previewPairDelta(page: Page) {
  return page.locator(".timeline-viewport").evaluate((element) => {
    const first = element.querySelector<HTMLElement>(
      '.timeline-item[data-display-index="0"]',
    )!
    const preview =
      element.parentElement!.querySelector<HTMLElement>(".pending-position")!
    const probe = document.createElement("span")
    probe.style.cssText =
      "position:absolute;visibility:hidden;pointer-events:none;height:0;padding:0;border:0"
    probe.style.width = "var(--card-width)"
    element.append(probe)
    const width = probe.getBoundingClientRect().width
    probe.style.width = "var(--card-gap)"
    const gap = probe.getBoundingClientRect().width
    probe.remove()
    return Math.abs(
      preview.getBoundingClientRect().left -
        first.getBoundingClientRect().left -
        (width + gap),
    )
  })
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
  const initialPositionWidth = (await page
    .locator(".pending-position")
    .boundingBox())!.width
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
    expect(
      Math.abs(
        (await page.locator(".pending-position").boundingBox())!.width -
          initialPositionWidth,
      ),
    ).toBeLessThan(0.5)
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

test("inline_confirm_is_visible_below_preview_and_is_the_only_submit_action", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  const state = await controlledBoard(page, controlledRun(3))
  await keyboardPreview(page, 1)
  await settleBoard(page)
  expect(await previewPairDelta(page)).toBeLessThan(0.5)
  const confirm = page.getByRole("button", { name: "Confirm", exact: true })
  const buttonBox = (await confirm.boundingBox())!
  const cardBox = (await page.getByTestId("pending-card").boundingBox())!
  expect(buttonBox.y).toBeGreaterThanOrEqual(cardBox.y + cardBox.height)
  expect(buttonBox.height).toBeGreaterThanOrEqual(44)
  expect(
    Math.abs(buttonBox.x + buttonBox.width / 2 - cardBox.x - cardBox.width / 2),
  ).toBeLessThan(2)
  await fitsDesktop(page)
  const palette = await page.evaluate(() => ({
    canvas: getComputedStyle(document.querySelector(".timeline-viewport")!)
      .backgroundColor,
    card: getComputedStyle(
      document.querySelector(".pending-draggable .game-card")!,
    ).backgroundColor,
    confirm: getComputedStyle(document.querySelector(".pending-confirm")!)
      .backgroundColor,
    confirmText: getComputedStyle(document.querySelector(".pending-confirm")!)
      .color,
  }))
  expect(palette.canvas).toBe("rgb(233, 225, 210)")
  expect(palette.card).toBe("rgb(247, 241, 229)")
  expect(palette.confirm).toBe("rgb(82, 107, 76)")
  expect(palette.confirmText).toBe("rgb(255, 253, 247)")
  await page
    .locator("html")
    .evaluate((element) => element.classList.add("dark"))
  await expect(page.locator(".timeline-viewport")).toHaveCSS(
    "background-color",
    palette.canvas,
  )
  await expect(page.locator(".pending-draggable .game-card")).toHaveCSS(
    "background-color",
    palette.card,
  )
  await page
    .locator("html")
    .evaluate((element) => element.classList.remove("dark"))
  expect(state.moves).toHaveLength(0)
  await confirm.click()
  expect(state.moves).toHaveLength(1)
})

test("wide_desktop_expands_the_measured_card_and_keeps_inline_confirm_visible", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1920, height: 900 })
  const state = await controlledBoard(page, controlledRun(3))
  await keyboardPreview(page, 1)
  await settleBoard(page)
  expect(await previewPairDelta(page)).toBeLessThan(0.5)
  const confirm = page.getByRole("button", { name: "Confirm", exact: true })
  const buttonBox = (await confirm.boundingBox())!
  const cardBox = (await page.getByTestId("pending-card").boundingBox())!
  expect(cardBox.width).toBeGreaterThan(230)
  expect(buttonBox.y).toBeGreaterThanOrEqual(cardBox.y + cardBox.height)
  expect(buttonBox.height).toBeGreaterThanOrEqual(44)
  expect(
    Math.abs(buttonBox.x + buttonBox.width / 2 - cardBox.x - cardBox.width / 2),
  ).toBeLessThan(2)
  await fitsDesktop(page)
  await page.setViewportSize({ width: 1366, height: 768 })
  await settleBoard(page)
  await expect(page.locator(".pending-position")).toHaveAttribute(
    "data-preview-slot",
    "1",
  )
  await expect(confirm).toBeInViewport({ ratio: 1 })
  await fitsDesktop(page)
  expect(state.moves).toHaveLength(0)
  await confirm.click()
  expect(state.moves).toHaveLength(1)
})

test("lives_show_filled_and_spent_hearts_with_an_accessible_numeric_label", async ({
  page,
}) => {
  const state = await controlledBoard(page)
  for (const [remaining, filled] of [
    [3, 3],
    [1, 1],
    [0, 0],
  ] as const) {
    state.run.lives_remaining = remaining
    await page.reload()
    await expect(
      page.getByText(`Lives: ${remaining} of 3`, { exact: true }),
    ).toBeVisible()
    expect(
      await page.locator(".game-life").evaluateAll((hearts) =>
        hearts.map((heart) => ({
          state: heart.getAttribute("data-state"),
          glyph: heart.textContent,
        })),
      ),
    ).toEqual([
      ...Array.from({ length: filled }, () => ({
        state: "remaining",
        glyph: "♥",
      })),
      ...Array.from({ length: 3 - filled }, () => ({
        state: "spent",
        glyph: "♡",
      })),
    ])
  }
})

test("short_prompt_does_not_reserve_empty_title_lines_above_the_footer", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  const run = controlledRun()
  run.pending!.prompt = "A short historical prompt."
  const state = await controlledBoard(page, run)
  const metrics = await page.locator(".pending-draggable").evaluate((card) => {
    const title = card.querySelector("h3")!
    const footer = card.querySelector(".game-card-footer")!
    const titleBox = title.getBoundingClientRect()
    const footerBox = footer.getBoundingClientRect()
    return {
      titleHeight: titleBox.height,
      lineHeight: Number.parseFloat(getComputedStyle(title).lineHeight),
      footerGap: footerBox.top - titleBox.bottom,
    }
  })
  expect(metrics.titleHeight).toBeLessThan(metrics.lineHeight * 2)
  expect(metrics.footerGap).toBeLessThan(metrics.lineHeight * 2)
  await expect(
    page.getByRole("button", { name: "Read full prompt", exact: true }),
  ).toHaveCount(0)
  expect(state.moves).toHaveLength(0)
})

for (const viewport of [
  { width: 1366, height: 768 },
  { width: 1920, height: 900 },
])
  test(`long_prompt_footer_stays_inside_card_and_separate_from_confirm ${viewport.width}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    const run = controlledRun(1)
    run.pending!.prompt = "Long public pending description. ".repeat(60)
    const state = await controlledBoard(page, run)
    await keyboardPreview(page, 0)
    await settleBoard(page)

    const card = page.getByTestId("pending-card")
    const footer = card.locator(".game-card-footer")
    const readFull = page.getByRole("button", {
      name: "Read full prompt",
      exact: true,
    })
    const confirm = page.getByRole("button", { name: "Confirm", exact: true })
    const bounds = await page.evaluate(() => {
      const rect = (selector: string) => {
        const box = document.querySelector(selector)!.getBoundingClientRect()
        return {
          top: box.top,
          right: box.right,
          bottom: box.bottom,
          left: box.left,
        }
      }
      return {
        card: rect(".pending-draggable .game-card"),
        footer: rect(".pending-draggable .game-card-footer"),
        read: rect(".pending-draggable .game-card-footer button"),
        confirm: rect(".pending-confirm"),
      }
    })
    expect(bounds.footer.bottom).toBeLessThanOrEqual(bounds.card.bottom + 0.5)
    expect(bounds.read.bottom).toBeLessThanOrEqual(bounds.card.bottom + 0.5)
    expect(bounds.confirm.top).toBeGreaterThanOrEqual(bounds.card.bottom)
    expect((await footer.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    expect((await readFull.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    expect((await confirm.boundingBox())!.height).toBeGreaterThanOrEqual(44)

    const hitTargets = await page.evaluate(() => {
      const footerButton = document.querySelector(
        ".pending-draggable .game-card-footer button",
      )!
      const confirmButton = document.querySelector(".pending-confirm")!
      const center = (element: Element) => {
        const box = element.getBoundingClientRect()
        return document.elementFromPoint(
          box.left + box.width / 2,
          box.top + box.height / 2,
        )
      }
      return {
        footer: center(footerButton) === footerButton,
        confirm: center(confirmButton) === confirmButton,
      }
    })
    expect(hitTargets).toEqual({ footer: true, confirm: true })
    await readFull.click()
    await expect(page.getByRole("dialog")).toContainText(run.pending!.prompt)
    await expect(page.getByRole("dialog")).not.toContainText("900 CE")
    await page.keyboard.press("Escape")
    expect(state.moves).toHaveLength(0)
    if (viewport.width > 767) await fitsDesktop(page)
  })

test("mobile_hand_is_compact_and_preview_reveals_card_without_leaking_year", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const run = controlledRun(1)
  run.pending!.prompt = "Long public pending description. ".repeat(12)
  const state = await controlledBoard(page, run)
  const card = page.locator(".pending-draggable .game-card")
  await expect(card).toHaveAttribute("class", /game-card-pending/)
  await expect(card).toHaveCSS("height", "120px")
  await expect(page.getByRole("button", { name: "Confirm" })).toHaveCount(0)
  await keyboardPreview(page, 0)
  await expect(
    page.getByRole("button", { name: "Confirm", exact: true }),
  ).toBeVisible()
  const cardBox = (await card.boundingBox())!
  const footerBox = (await card.locator(".game-card-footer").boundingBox())!
  expect(footerBox.y + footerBox.height).toBeLessThanOrEqual(
    cardBox.y + cardBox.height + 0.5,
  )
  await expect(
    page.getByRole("button", { name: "Read full prompt" }),
  ).toBeVisible()
  await page.getByRole("button", { name: "Read full prompt" }).click()
  await expect(page.getByRole("dialog")).not.toContainText("900 CE")
  await page.keyboard.press("Escape")
  expect(state.moves).toHaveLength(0)
})

test("developer_widget_launchers_are_absent_by_default", async ({ page }) => {
  const state = await controlledBoard(page, controlledRun(1))
  await expect(page.locator("[aria-label*='devtools' i]")).toHaveCount(0)
  await expect(page.locator("[data-tanstack-devtools]")).toHaveCount(0)
  expect(state.moves).toHaveLength(0)
})

test("developer_widget_launchers_appear_with_explicit_opt_in", async ({
  page,
}) => {
  test.skip(
    process.env.VITE_SHOW_DEVTOOLS !== "true",
    "requires explicit opt-in",
  )
  await controlledBoard(page, controlledRun(1))
  await expect(page.locator("[aria-label*='devtools' i]")).toHaveCount(2)
  await expect(page.locator("[aria-label*='devtools' i]").first()).toBeVisible()
})

for (const [name, width, height] of [
  ["desktop-1920x900", 1920, 900],
  ["desktop-1366x768", 1366, 768],
  ["mobile-390x844", 390, 844],
] as const) {
  test(`capture_${name}_board_evidence`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const state = await controlledBoard(page, controlledRun(3))
    await keyboardPreview(page, 1)
    await settleBoard(page)
    expect(await previewPairDelta(page)).toBeLessThan(0.5)
    const confirm = page.getByRole("button", { name: "Confirm", exact: true })
    await expect(confirm).toBeVisible()
    await expect(confirm).toBeInViewport({ ratio: 1 })
    if (width > 767) await fitsDesktop(page)
    else
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width)
    expect(state.moves).toHaveLength(0)
    const path = resolve(
      boardEvidence,
      `task5-review-hearts-intrinsic-${name}.png`,
    )
    await page.screenshot({ path, fullPage: true })
    chmodSync(path, 0o600)
  })
}

test("two_hundred_percent_zoom_equivalent_reflows_without_horizontal_page_scroll", async ({
  page,
}) => {
  await page.setViewportSize({ width: 683, height: 384 })
  const state = await controlledBoard(page, controlledRun(3))
  await keyboardPreview(page, 1)
  await settleBoard(page)
  await expect(
    page.getByRole("button", { name: "Confirm", exact: true }),
  ).toBeInViewport({ ratio: 1 })
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(683)
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
      const probe = document.createElement("span")
      probe.style.cssText =
        "position:absolute;visibility:hidden;pointer-events:none;height:0;padding:0;border:0"
      probe.style.width = "var(--card-width)"
      element.append(probe)
      const cardWidth = probe.getBoundingClientRect().width
      probe.style.width = "var(--card-gap)"
      const gap = probe.getBoundingClientRect().width
      probe.remove()
      const origin = 0
      const stride = cardWidth + gap
      const card = element
        .querySelector(`[data-display-index="${ordinal}"]`)!
        .getBoundingClientRect()
      const offset = Number(element.getAttribute("data-offset"))
      return {
        scrollLeft: element.scrollLeft,
        x: card.left - board.left,
        expectedX: origin + ordinal * stride - offset,
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
    expect(Math.abs(geometry.x - geometry.expectedX)).toBeLessThan(0.5)
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
  await page.mouse.move(tile.x + 70, tile.y + 70)
  await page.mouse.down()
  await page.mouse.move(tile.x + 82, tile.y + 70)
  // One target move avoids opening an earlier insertion preview along an
  // interpolated path; this checks the focused transform's pointer alignment.
  const pointerGeometry = await viewport.evaluate((element) => {
    const probe = document.createElement("span")
    probe.style.cssText =
      "position:absolute;visibility:hidden;pointer-events:none;height:0;padding:0;border:0"
    probe.style.width = "var(--card-width)"
    element.append(probe)
    const width = probe.getBoundingClientRect().width
    probe.style.width = "var(--card-gap)"
    const gap = probe.getBoundingClientRect().width
    probe.remove()
    return {
      origin: 0,
      stride: width + gap,
      width,
      offset: Number(element.getAttribute("data-offset")),
    }
  })
  await page.mouse.move(
    board.x +
      pointerGeometry.origin +
      15 * pointerGeometry.stride -
      pointerGeometry.offset +
      pointerGeometry.width / 2,
    board.y + 90,
  )
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
        const probe = document.createElement("span")
        probe.style.cssText =
          "position:absolute;visibility:hidden;pointer-events:none;height:0;padding:0;border:0"
        probe.style.width = "var(--card-width)"
        element.append(probe)
        const width = probe.getBoundingClientRect().width
        probe.style.width = "var(--card-gap)"
        const gap = probe.getBoundingClientRect().width
        probe.remove()
        return (
          card.getBoundingClientRect().left -
          element.getBoundingClientRect().left -
          (18 * (width + gap) - Number(element.getAttribute("data-offset")))
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
  const previewStride = await viewport.evaluate((element) => {
    const probe = document.createElement("span")
    probe.style.cssText =
      "position:absolute;visibility:hidden;pointer-events:none;height:0;padding:0;border:0"
    probe.style.width = "var(--card-width)"
    element.append(probe)
    const width = probe.getBoundingClientRect().width
    probe.style.width = "var(--card-gap)"
    const gap = probe.getBoundingClientRect().width
    probe.remove()
    return width + gap
  })
  expect(previewGeometry.x).toBeCloseTo(
    18 * previewStride - previewGeometry.offset,
    4,
  )
  await details.nth(17).click()
  await expect(page.getByRole("dialog")).toBeVisible()
  await page.keyboard.press("Escape")
  await expect(details.nth(17)).toBeFocused()
  await expect(page.locator("[data-preview-slot]")).toHaveAttribute(
    "data-preview-slot",
    "16",
  )
  expect(state.moves).toHaveLength(0)
  await page.getByRole("button", { name: "Confirm", exact: true }).click()
  await expect(page.getByTestId("run-revision")).toHaveText("Revision: 1")
  expect(state.moves).toHaveLength(1)
  expect(state.moves[0].slot).toBe(16)
})

test("nonfinal_mistake_review_survives_reload_and_continue_is_local_only", async ({
  page,
}) => {
  const run = controlledRun(3)
  const state = await controlledBoard(page, run)
  let placements = 0
  await page.route("**/placements", async (route) => {
    if (route.request().method() !== "POST") return route.continue()
    placements++
    const command = route.request().postDataJSON() as { slot: number }
    const corrected = {
      ...revealed(700),
      event_id: "pending",
      prompt: "Public pending prompt",
    }
    state.run = {
      ...state.run,
      revision: state.run.revision + 1,
      status: "active",
      lives_remaining: 2,
      score: 0,
      streak: 0,
      timeline: [
        ...state.run.timeline.slice(0, command.slot),
        corrected,
        ...state.run.timeline.slice(command.slot),
      ],
      pending: {
        event_id: "next",
        prompt: "Next public prompt",
        category_ids: ["history"],
        media,
      },
      feedback: {
        correct: false,
        card: corrected,
        attempted_slot: command.slot,
        correct_slot: 2,
      },
    }
    await route.fulfill({ status: 200, json: state.run })
  })
  await keyboardPreview(page, 1)
  await page.getByRole("button", { name: "Confirm", exact: true }).click()
  await expect(page.getByRole("button", { name: "Continue" })).toBeVisible()
  await expect(page.getByText("Incorrect — 2 lives left.")).toBeVisible()
  await expect(page.locator(".pending-draggable")).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: "Confirm", exact: true }),
  ).toHaveCount(0)
  expect(placements).toBe(1)
  await page.reload()
  await expect(page.getByRole("button", { name: "Continue" })).toBeVisible()
  await expect(page.locator(".pending-draggable")).toHaveCount(0)
  await page.getByRole("button", { name: "Continue" }).click()
  await expect(page.locator(".pending-draggable")).toBeVisible()
  await expect(page.getByText("Next public prompt")).toBeVisible()
  await expect(page.locator(".timeline-item[data-wrong=true]")).toHaveCount(0)
  expect(placements).toBe(1)
})

test("pool_exhaustion_win_after_nonfinal_miss_defers_results_until_continue", async ({
  page,
}) => {
  const state = await controlledBoard(page, controlledRun(2))
  await page.route("**/placements", async (route) => {
    if (route.request().method() !== "POST") return route.continue()
    const corrected = {
      ...revealed(700),
      event_id: "pending",
      prompt: "Public pending prompt",
    }
    state.run = {
      ...state.run,
      revision: state.run.revision + 1,
      status: "won",
      lives_remaining: 2,
      timeline: [state.run.timeline[0], corrected, state.run.timeline[1]],
      pending: null,
      feedback: {
        correct: false,
        card: corrected,
        attempted_slot: 1,
        correct_slot: 2,
      },
    }
    await route.fulfill({ status: 200, json: state.run })
  })
  await keyboardPreview(page, 1)
  await page.getByRole("button", { name: "Confirm", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Continue", exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("heading", { name: "Victory — catalog exhausted" }),
  ).toHaveCount(0)
  await page.getByRole("button", { name: "Continue", exact: true }).click()
  await expect(
    page.getByRole("heading", { name: "Victory — catalog exhausted" }),
  ).toBeVisible()
})

for (const size of [
  { width: 1920, height: 900 },
  { width: 1366, height: 768 },
])
  test(`loss_fits_whole_desktop_controls ${size.width}`, async ({ page }) => {
    await page.setViewportSize(size)
    const run = controlledRun()
    run.status = "lost"
    run.lives_remaining = 0
    run.pending = null
    run.feedback = {
      correct: false,
      card: {
        ...run.timeline[0],
        event_id: "legacy-wrong",
        prompt: "Legacy wrong event",
      },
      attempted_slot: 1,
      correct_slot: 3,
    }
    await controlledBoard(page, run, false)
    await page.goto(`/play/${run.run_id}`)
    await expect(
      page.getByText(
        "Incorrect — 0 lives left. The correct location is marked.",
      ),
    ).toBeInViewport({ ratio: 1 })
    await expect(
      page.locator('.timeline-item[data-wrong="true"] .game-card'),
    ).toBeInViewport({
      ratio: 1,
    })
    await expect(page.locator(".timeline-item").first()).toBeInViewport({
      ratio: 1,
    })
    await expect(
      page.getByRole("button", { name: "Run details", exact: true }),
    ).toBeInViewport({ ratio: 1 })
    await expect(page.locator('.timeline-item[data-wrong="true"]')).toHaveCount(
      1,
    )
    await fitsDesktop(page)
    await page.reload()
    await expect(
      page.locator('.timeline-item[data-wrong="true"] .game-card'),
    ).toBeInViewport({
      ratio: 1,
    })
    await fitsDesktop(page)
  })

test("drag_actual_tile_into_second_boundary", async ({ page }) => {
  const state = await controlledBoard(page)
  await dragTile(page, 1)
  await expect(
    page.getByRole("button", { name: "Confirm", exact: true }),
  ).toBeEnabled()
  expect(state.moves).toHaveLength(0)
  await page.getByRole("button", { name: "Confirm", exact: true }).click()
  await expect(page.getByTestId("run-revision")).toContainText("1")
  expect(state.moves).toHaveLength(1)
  expect(state.moves[0].slot).toBe(1)
})

test("repositioning_a_centered_preview_backwards_keeps_the_stationary_slot", async ({
  page,
}) => {
  const state = await controlledBoard(page)
  await dragTile(page, 2)
  await expect(page.locator("[data-preview-slot]")).toHaveAttribute(
    "data-preview-slot",
    "2",
  )

  await dragTile(page, 1)
  await expect(page.locator("[data-preview-slot]")).toHaveAttribute(
    "data-preview-slot",
    "1",
  )
  expect(state.moves).toHaveLength(0)
})

test("preview_can_be_picked_up_repositioned_and_returned", async ({ page }) => {
  const state = await controlledBoard(page)
  await dragTile(page, 1)
  await expect(page.locator(".pending-draggable")).toHaveCount(1)
  await expect(
    page.getByRole("button", { name: "Confirm", exact: true }),
  ).toBeVisible()
  await dragTile(page, 2)
  await expect(page.locator(".pending-draggable")).toHaveCount(1)
  await settleBoard(page)
  const confirm = page.getByRole("button", { name: "Confirm", exact: true })
  const confirmBox = (await confirm.boundingBox())!
  const cardBox = (await page.getByTestId("pending-card").boundingBox())!
  expect(confirmBox.y).toBeGreaterThanOrEqual(cardBox.y + cardBox.height)
  expect(
    Math.abs(
      confirmBox.x + confirmBox.width / 2 - cardBox.x - cardBox.width / 2,
    ),
  ).toBeLessThan(2)
  await page.getByRole("button", { name: "Return to hand" }).click()
  await expect(page.locator("[data-preview-slot]")).toHaveCount(0)
  await expect(confirm).toHaveCount(0)
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
        page.getByRole("button", { name: "Confirm", exact: true }),
      ).toBeInViewport()
      await page.getByRole("button", { name: "Confirm", exact: true }).click()
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
    for (const remainingMiss of [2, 3]) {
      await expect(
        page.getByRole("button", { name: "Continue", exact: true }),
      ).toBeVisible()
      await page.getByRole("button", { name: "Continue", exact: true }).click()
      await keyboardPreview(page, 0)
      await page.getByRole("button", { name: "Confirm", exact: true }).click()
      await expect(page.getByTestId("run-revision")).toHaveText(
        `Revision: ${state.moves.length}`,
      )
      if (remainingMiss < 3)
        await expect(
          page.getByRole("button", { name: "Continue", exact: true }),
        ).toBeVisible()
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
    expect(state.moves).toHaveLength(4)
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
  // The closing animation restores trigger focus asynchronously. Finish that
  // lifecycle before moving focus to the full-card keyboard drag surface.
  await expect(
    page.getByRole("button", { name: "Read full prompt" }),
  ).toBeFocused()
  await page.locator(".pending-draggable").focus()
  await expect(page.locator(".pending-draggable h3")).toHaveText(
    run.pending!.prompt.trim(),
  )
  expect(
    await page
      .locator(".pending-draggable h3")
      .evaluate((e) => getComputedStyle(e).overflowY),
  ).toBe("hidden")
  await keyboardPreview(page, 1)
  await expect(
    page.getByRole("button", { name: "Confirm", exact: true }),
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

test("medium_prompt_overflow_is_measured_and_full_wording_stays_year_hidden", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const run = controlledRun()
  run.pending!.prompt =
    "Several short words wrap across this compact card and keep every piece of the original historical wording available to read."
  expect(run.pending!.prompt.length).toBeLessThan(180)
  const state = await controlledBoard(page, run)
  const readFull = page.getByRole("button", {
    name: "Read full prompt",
    exact: true,
  })
  await expect(readFull).toBeVisible()
  for (const element of await page.locator(".pending-draggable *").all())
    expect(
      await element.evaluate((node) => getComputedStyle(node).overflowY),
    ).not.toMatch(/^(auto|scroll)$/)
  await readFull.click()
  await expect(page.getByRole("dialog")).toContainText(run.pending!.prompt)
  await expect(page.getByRole("dialog")).not.toContainText("900 CE")
  await page.keyboard.press("Escape")
  await expect(readFull).toBeFocused()
  state.run.pending!.prompt = "W".repeat(150)
  await page.reload()
  await expect(readFull).toBeVisible()
  await readFull.click()
  await expect(page.getByRole("dialog")).toContainText("W".repeat(150))
  await expect(page.getByRole("dialog")).not.toContainText("900 CE")
  await page.keyboard.press("Escape")
  expect(state.moves).toHaveLength(0)
})
test("owner_or_revision_change_cancels_pan_without_clearing_command", async ({
  page,
}) => {
  const state = await controlledBoard(page)
  await keyboardPreview(page, 1)
  state.failMove = true
  await page.getByRole("button", { name: "Confirm", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Retry same move" }),
  ).toBeVisible()
  const saved = await page.evaluate(() =>
    sessionStorage.getItem(
      "game:v2:controlled-board:placement:11111111-1111-4111-8111-111111111111",
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
        "game:v2:controlled-board:placement:11111111-1111-4111-8111-111111111111",
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
    page.getByRole("button", { name: "Confirm", exact: true }),
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
    page.getByRole("button", { name: "Confirm", exact: true }),
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
  await page.getByRole("button", { name: "Confirm", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Retry same move", exact: true }),
  ).toBeVisible()
  await expect(page.getByTestId("run-revision")).toHaveText("Revision: 0")
  const saved = await page.evaluate(() =>
    sessionStorage.getItem(
      "game:v2:controlled-board:placement:11111111-1111-4111-8111-111111111111",
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
        "game:v2:controlled-board:placement:11111111-1111-4111-8111-111111111111",
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
    page.getByRole("button", { name: "Confirm", exact: true }),
  ).toBeEnabled()
  expect(state.moves).toHaveLength(0)
})
test("mobile_keyboard_docked_hand_reveals_whole_preview", async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 727 })
  const run = controlledRun(3)
  run.mode = "daily"
  run.daily_date = "2026-10-14"
  const state = await controlledBoard(page, run)
  await page.mouse.wheel(0, 300)
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(0)
  await page.locator(".pending-draggable").focus()
  await keyboardPreview(page, 0)
  await expect(page.locator(".pending-draggable")).toBeInViewport({ ratio: 1 })
  expect(
    await page
      .locator(".timeline-viewport")
      .evaluate((element) => element.scrollLeft),
  ).toBe(0)
  expect(state.moves).toHaveLength(0)
})
test("owner_change_interrupts_active_native_pan", async ({ page }) => {
  const lifecycleWarnings: string[] = []
  page.on("console", (message) => {
    if (message.text().includes("useInsertionEffect must not schedule updates"))
      lifecycleWarnings.push(message.text())
  })
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
  // Triage evidence, not warning suppression or a claim of a lifecycle fix.
  console.log("owner teardown lifecycle diagnostics:", lifecycleWarnings)
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
      page.getByRole("button", { name: "Confirm", exact: true }),
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
  const viewport = page.locator(".timeline-viewport")
  await expect
    .poll(async () => {
      const data = await viewport.evaluate((element) => {
        const items = element.querySelectorAll<HTMLElement>(".timeline-item")
        const tile =
          element.parentElement!.querySelector<HTMLElement>(
            ".pending-draggable",
          )!
        return {
          tile: tile.getBoundingClientRect().left,
          first: items[0].getBoundingClientRect().left,
          second: items[1].getBoundingClientRect().left,
        }
      })
      return Math.abs(data.tile - data.first - (data.second - data.first) / 2)
    })
    .toBeLessThan(0.1)
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
  ).toBe("rgb(247, 241, 229)")
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
    page.getByRole("button", { name: "Confirm", exact: true }),
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
    await page.getByRole("button", { name: "Confirm", exact: true }).click()
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
    await page.getByRole("button", { name: "Confirm", exact: true }).click()
    await expect(page.getByTestId("run-revision")).toHaveText(
      `Revision: ${state.moves.length}`,
    )
  }
  for (const remainingMiss of [2, 3]) {
    await expect(
      page.getByRole("button", { name: "Continue", exact: true }),
    ).toBeVisible()
    await page.getByRole("button", { name: "Continue", exact: true }).click()
    await keyboardPreview(page, 0)
    await page.getByRole("button", { name: "Confirm", exact: true }).click()
    await expect(page.getByTestId("run-revision")).toHaveText(
      `Revision: ${state.moves.length}`,
    )
    if (remainingMiss < 3)
      await expect(
        page.getByRole("button", { name: "Continue", exact: true }),
      ).toBeVisible()
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
