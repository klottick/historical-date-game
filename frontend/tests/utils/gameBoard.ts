import { expect, type Page } from "@playwright/test"

// Shared by controlled and real-backend consumers; only public UI geometry.
export async function keyboardPreview(page: Page, slot: number) {
  const tile = page.locator(".pending-position .pending-draggable")
  const prior = await page
    .locator(".pending-position")
    .getAttribute("data-preview-slot")
  await tile.focus()
  await page.keyboard.press("Space")
  const from = prior === null ? 0 : Number(prior)
  if (slot === 0) await page.keyboard.press("Home")
  else
    for (let i = 0; i < Math.abs(slot - from); i++)
      await page.keyboard.press(slot > from ? "ArrowRight" : "ArrowLeft")
  await page.keyboard.press("Space")
  await expect(page.locator("[data-preview-slot]")).toHaveAttribute(
    "data-preview-slot",
    String(slot),
  )
  await expect(tile).toBeFocused()
}

export async function dragPendingToIndex(
  page: Page,
  slot: number,
  touch = false,
) {
  const tile = page.locator(".pending-position .pending-draggable")
  await tile.hover({ position: { x: 70, y: 70 } })
  const source = await tile.boundingBox()
  const viewport = await page.locator(".timeline-viewport").boundingBox()
  const dimensions = await page
    .locator(".timeline-viewport")
    .evaluate((element) => {
      const style = getComputedStyle(element)
      return {
        width: Number.parseFloat(style.getPropertyValue("--card-width")),
        gap: Number.parseFloat(style.getPropertyValue("--card-gap")),
        offset: Number(element.getAttribute("data-offset")),
      }
    })
  if (!source || !viewport) throw new Error("Board geometry unavailable")
  const stride = dimensions.width + dimensions.gap
  const x = Math.max(
    viewport.x + 8,
    Math.min(
      viewport.x + viewport.width - 4,
      viewport.x + slot * stride - dimensions.offset - dimensions.gap / 2,
    ),
  )
  const y = viewport.y + 90
  const cdp = touch ? await page.context().newCDPSession(page) : null
  async function move(x: number, y: number) {
    if (cdp)
      await cdp.send("Input.dispatchTouchEvent", {
        type: "touchMove",
        touchPoints: [{ x, y }],
      })
    else await page.mouse.move(x, y, { steps: 8 })
  }
  try {
    if (cdp) {
      await cdp.send("Input.dispatchTouchEvent", {
        type: "touchStart",
        touchPoints: [{ x: source.x + 70, y: source.y + 70 }],
      })
      await page.waitForTimeout(250) // The real touch activation delay, not a retry.
    } else {
      await page.mouse.move(source.x + 70, source.y + 70)
      await page.mouse.down()
    }
    await move(source.x + 82, source.y + 70)
    await move(x, y)
    const hover = await page
      .locator(".timeline-viewport")
      .getAttribute("data-hovered-slot")
    if (hover !== null && hover !== "" && Number(hover) < slot)
      await move(Math.min(viewport.x + viewport.width - 4, x + stride), y)
    await expect(page.locator(".timeline-viewport")).toHaveAttribute(
      "data-hovered-slot",
      String(slot),
      { timeout: 15000 }, // Offscreen boundaries require actual edge pan.
    )
    if (cdp)
      await cdp.send("Input.dispatchTouchEvent", {
        type: "touchEnd",
        touchPoints: [],
      })
    else await page.mouse.up()
    await expect(page.locator("[data-preview-slot]")).toHaveAttribute(
      "data-preview-slot",
      String(slot),
    )
  } finally {
    await cdp?.detach()
  }
}

// No scrollIntoView/zoom adjustment: measure the user's actual available surface.
export async function assertBoardFits(page: Page): Promise<void> {
  const dimensions = await page.evaluate(() => ({
    width: document.documentElement.scrollWidth,
    height: document.documentElement.scrollHeight,
    viewportWidth: innerWidth,
    viewportHeight: innerHeight,
    x: scrollX,
    y: scrollY,
    scale: visualViewport?.scale,
  }))
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewportWidth)
  expect(dimensions.height).toBeLessThanOrEqual(dimensions.viewportHeight)
  expect([dimensions.x, dimensions.y, dimensions.scale]).toEqual([0, 0, 1])
  for (const control of await page
    .locator(
      ".game-heading, .timeline-stage, .timeline-overview, .placement-actions button, .game-results > a, .game-results > button, .game-footer > button, .game-footer > a",
    )
    .all()) {
    const rect = await control.boundingBox()
    expect(rect).not.toBeNull()
    expect(rect!.x).toBeGreaterThanOrEqual(0)
    expect(rect!.y).toBeGreaterThanOrEqual(0)
    expect(rect!.x + rect!.width).toBeLessThanOrEqual(dimensions.viewportWidth)
    expect(rect!.y + rect!.height).toBeLessThanOrEqual(
      dimensions.viewportHeight,
    )
  }
  expect(
    await page.locator(".timeline-viewport").evaluate((e) => e.scrollLeft),
  ).toBe(0)
}
