import { expect, type Page, test } from "@playwright/test"
import {
  controlledBoard,
  controlledRun,
  keyboardPreview,
} from "./utils/controlledBoard"

const pageErrors = new WeakMap<Page, string[]>()
test.beforeEach(({ page }) => {
  const errors: string[] = []
  pageErrors.set(page, errors)
  page.on("pageerror", (error) => errors.push(error.message))
})
test.afterEach(({ page }) => {
  expect(pageErrors.get(page)).toEqual([])
})

// Test oracle observes settled painted cards, not production projection helpers.
async function expectProjectedCards(page: Page, ordinals?: number[]) {
  const viewport = page.locator(".timeline-viewport")
  await expect
    .poll(() =>
      viewport.evaluate((element) => {
        const left = element.getBoundingClientRect().left
        const offset = Number(element.getAttribute("data-offset"))
        return Math.max(
          0,
          ...[...element.querySelectorAll<HTMLElement>(".timeline-item")].map(
            (card) =>
              Math.abs(
                card.getBoundingClientRect().left -
                  left -
                  (Number.parseFloat(card.style.left) - offset),
              ),
          ),
        )
      }),
    )
    .toBeLessThan(0.1)
  const projection = await page.evaluate(() => {
    const viewport = document.querySelector(".timeline-viewport")!
    const window = viewport.getBoundingClientRect()
    const visible = [
      ...viewport.querySelectorAll<HTMLElement>(".timeline-item"),
    ]
      .filter((card) => {
        const rect = card.getBoundingClientRect()
        return rect.right > window.left && rect.left < window.right
      })
      .map((card) => Number(card.dataset.displayIndex))
    const marks = [
      ...document.querySelectorAll<HTMLElement>(".overview-mark"),
    ].map((mark) => {
      const [start, end] = mark
        .getAttribute("aria-label")!
        .match(/\d+/g)!
        .map(Number)
      return {
        visible: mark.dataset.visible === "true",
        expected: visible.some(
          (index) => index >= start - 1 && index <= end - 1,
        ),
      }
    })
    return { visible, marks }
  })
  if (ordinals) expect(projection.visible).toEqual(ordinals)
  expect(projection.marks.map((mark) => mark.visible)).toEqual(
    projection.marks.map((mark) => mark.expected),
  )
}

async function expectTransformOnly(page: Page) {
  expect(
    await page.evaluate(() => [
      scrollX,
      scrollY,
      document.querySelector(".timeline-stage")!.scrollLeft,
      document.querySelector(".timeline-viewport")!.scrollLeft,
    ]),
  ).toEqual([0, 0, 0, 0])
}

async function expectVisiblePendingFocus(page: Page, nested = false) {
  const target = nested
    ? page.getByRole("button", { name: "Read full prompt", exact: true })
    : page.locator(".pending-draggable")
  await expect(target).toBeFocused()
  expect(
    await target.evaluate((element) => element.matches(":focus-visible")),
  ).toBe(true)
  expect(
    await target.evaluate((element) => {
      const style = getComputedStyle(element)
      return (
        style.outlineStyle !== "none" &&
        Number.parseFloat(style.outlineWidth) > 0
      )
    }),
  ).toBe(true)
  await expect
    .poll(() =>
      page.evaluate(() => {
        const tile = document
          .querySelector(".pending-draggable")!
          .getBoundingClientRect()
        const window = document
          .querySelector(".timeline-viewport")!
          .getBoundingClientRect()
        return tile.left >= window.left && tile.right <= window.right
      }),
    )
    .toBe(true)
  await expect(target).toBeInViewport({ ratio: 1 })
  await expectTransformOnly(page)
}

for (const slot of [0, 2, 12])
  test(`overview projects settled preview ${slot} before inside after window`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1366, height: 768 })
    const state = await controlledBoard(page, controlledRun(12))
    await expectProjectedCards(page, [0, 1, 2, 3, 4])
    await keyboardPreview(page, slot)
    await page
      .getByRole("button", { name: "Show beginning", exact: true })
      .click()
    await expectProjectedCards(
      page,
      slot === 12 ? [0, 1, 2, 3, 4] : [0, 1, 2, 3],
    )
    await page.getByRole("button", { name: "Show end", exact: true }).click()
    await expectProjectedCards(
      page,
      slot === 12 ? [8, 9, 10, 11] : [7, 8, 9, 10, 11],
    )
    await expectTransformOnly(page)
    expect(state.moves).toHaveLength(0)
  })

test("overview projects active pointer hover and keyboard end hover without scoring", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  const state = await controlledBoard(page, controlledRun(12))
  const tile = (await page.locator(".pending-draggable").boundingBox())!
  const board = (await page.locator(".timeline-viewport").boundingBox())!
  await page.mouse.move(tile.x + 70, tile.y + 70)
  await page.mouse.down()
  await page.mouse.move(tile.x + 82, tile.y + 70)
  await page.mouse.move(board.x + 12, board.y + 90)
  await expect(page.locator(".timeline-viewport")).toHaveAttribute(
    "data-hovered-slot",
    "0",
  )
  await expectProjectedCards(page, [0, 1, 2, 3])
  // Preview 0 already occupies one stride: physical boundary 3 is logical 2.
  await page.mouse.move(board.x + 730, board.y + 90)
  await expect(page.locator(".timeline-viewport")).toHaveAttribute(
    "data-hovered-slot",
    "2",
  )
  await expectProjectedCards(page, [0, 1, 2, 3])
  await page.mouse.up()
  await page.locator(".pending-draggable").focus()
  await page.keyboard.press("Space")
  await page.keyboard.press("End")
  await expect(page.locator(".timeline-viewport")).toHaveAttribute(
    "data-hovered-slot",
    "12",
  )
  await expectProjectedCards(page, [8, 9, 10, 11])
  await page.keyboard.press("Escape")
  expect(state.moves).toHaveLength(0)
})

test("overview aggregated marks project expanded end window", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  const state = await controlledBoard(page, controlledRun(100))
  await keyboardPreview(page, 0)
  await page.getByRole("button", { name: "Show end", exact: true }).click()
  await expectProjectedCards(page, [95, 96, 97, 98, 99])
  await expect(page.locator(".overview-mark")).toHaveCount(80)
  expect(state.moves).toHaveLength(0)
})

test("overview preview-only window highlights no phantom confirmed mark", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await controlledBoard(page, controlledRun(12))
  // Responsive window narrower than one card: a normal Home/drop reveals only it.
  await page.locator(".game-table").evaluate((element) => {
    ;(element as HTMLElement).style.width = "210px"
  })
  await keyboardPreview(page, 0)
  await expectProjectedCards(page, [])
  await expect(page.locator('.overview-mark[data-visible="true"]')).toHaveCount(
    0,
  )
  expect(state.moves).toHaveLength(0)
})

test("Tab reveals earlier pending preview after overview end and confirmed dialog return", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  const state = await controlledBoard(page, controlledRun(12))
  await keyboardPreview(page, 0)
  await page.getByRole("button", { name: "Show end", exact: true }).click()
  const detail = page
    .locator(".timeline-item")
    .last()
    .getByRole("button", { name: "Learn more", exact: true })
  await detail.click()
  await expect(page.getByRole("dialog")).toBeVisible()
  await page.keyboard.press("Escape")
  await expect(detail).toBeFocused()
  await page.keyboard.press("Tab")
  await expectVisiblePendingFocus(page)
  await expect(page.locator(".pending-position")).toHaveAttribute(
    "data-preview-slot",
    "0",
  )
  expect(state.moves).toHaveLength(0)
})

test("ShiftTab reveals current repositioned pending preview after overview beginning", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  const state = await controlledBoard(page, controlledRun(12))
  await keyboardPreview(page, 0)
  await page.keyboard.press("Space")
  await page.keyboard.press("End")
  await page.keyboard.press("Space")
  await page
    .getByRole("button", { name: "Show beginning", exact: true })
    .click()
  await page.keyboard.press("Shift+Tab")
  const confirm = page.getByRole("button", { name: "Confirm", exact: true })
  await expect(confirm).toBeFocused()
  await expect(confirm).toBeInViewport({ ratio: 1 })
  await expectTransformOnly(page)
  await expect(page.locator(".pending-position")).toHaveAttribute(
    "data-preview-slot",
    "12",
  )
  expect(state.moves).toHaveLength(0)
})

test("pending prompt dialog restores visible nested focus after overview navigation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  const run = controlledRun(12)
  run.pending!.prompt = "Long public pending description. ".repeat(10)
  const state = await controlledBoard(page, run)
  await keyboardPreview(page, 0)
  await page.getByRole("button", { name: "Show end", exact: true }).click()
  // Ordinary reverse traversal: twelve event marks, beginning, pending prompt.
  // The preview's local Confirm action is now part of the keyboard order.
  for (let step = 0; step < 15; step++) await page.keyboard.press("Shift+Tab")
  await expectVisiblePendingFocus(page, true)
  await page.keyboard.press("Enter")
  await expect(page.getByRole("dialog")).toBeVisible()
  await page.keyboard.press("Escape")
  await expectVisiblePendingFocus(page, true)
  await expect(page.locator(".pending-position")).toHaveAttribute(
    "data-preview-slot",
    "0",
  )
  expect(state.moves).toHaveLength(0)
})

test("Tab to docked hand preserves overview window and exposes visible focus", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  const state = await controlledBoard(page, controlledRun(12))
  await page.getByRole("button", { name: "Show end", exact: true }).click()
  await page
    .locator(".timeline-item")
    .last()
    .getByRole("button", { name: "Learn more", exact: true })
    .focus()
  const offset = await page
    .locator(".timeline-viewport")
    .getAttribute("data-offset")
  await page.keyboard.press("Tab")
  await expect(page.locator(".pending-draggable")).toBeFocused()
  await expect(page.locator(".pending-draggable")).toBeInViewport({ ratio: 1 })
  expect(
    await page
      .locator(".pending-draggable")
      .evaluate((element) => element.matches(":focus-visible")),
  ).toBe(true)
  await expect(page.locator(".timeline-viewport")).toHaveAttribute(
    "data-offset",
    offset!,
  )
  await expectTransformOnly(page)
  expect(state.moves).toHaveLength(0)
})
