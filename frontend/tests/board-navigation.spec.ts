import { randomUUID } from "node:crypto"
import { mkdir, unlink, writeFile } from "node:fs/promises"
import { resolve } from "node:path"
import { expect, type Page, test } from "@playwright/test"
import type { BoardLayout } from "../src/features/game/boardGeometry"
import type { TimelineNavigator } from "../src/features/game/timelineNavigator"

declare global {
  interface Window {
    boardHarness: {
      layout: BoardLayout
      nav: TimelineNavigator
      offsets: { offset: number; time: number }[]
      pointer: { x: number; y: number } | null
      livePreview: boolean
    }
  }
}

async function harness(page: Page, count = 8) {
  await page.route("**/navigation-harness", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: `<style>body{margin:0;height:1600px}#viewport{position:absolute;left:100px;top:100px;width:320px;height:160px;overflow:hidden}#strip{height:160px;width:100000px}#overview{position:absolute;top:300px;width:100%}</style><div id="viewport" tabindex="0"><div id="strip"></div></div><button id="outside">Outside</button><button id="other">Other</button><nav id="overview"></nav>`,
    }),
  )
  await page.goto("/navigation-harness")
  await page.evaluate(async (count) => {
    const navPath = "/src/features/game/timelineNavigator.ts"
    const geometryPath = "/src/features/game/boardGeometry.ts"
    const { createTimelineNavigator } = await import(navPath)
    const { overviewMarks, insertionIndex } = await import(geometryPath)
    const viewport = document.getElementById("viewport")!
    const strip = document.getElementById("strip")!
    const layout: BoardLayout = {
      count,
      cardWidth: 100,
      gap: 20,
      viewportWidth: 320,
      offset: 0,
      previewSlot: null,
    }
    const offsets: { offset: number; time: number }[] = []
    const nav = createTimelineNavigator(
      viewport,
      () => ({ ...layout, viewportWidth: viewport.clientWidth }),
      (offset: number) => {
        layout.offset = offset
        offsets.push({ offset, time: performance.now() })
        strip.style.transform = `translateX(${-offset}px)`
        const h = window.boardHarness
        if (h.livePreview && h.pointer)
          layout.previewSlot = insertionIndex(
            h.pointer.x - viewport.getBoundingClientRect().left,
            { ...layout, viewportWidth: viewport.clientWidth },
          )
      },
    )
    window.boardHarness = {
      layout,
      nav,
      offsets,
      pointer: null,
      livePreview: false,
    }
    viewport.addEventListener("pointermove", (event) => {
      const h = window.boardHarness
      h.pointer = { x: event.clientX, y: event.clientY }
      if (h.livePreview)
        layout.previewSlot = insertionIndex(
          event.clientX - viewport.getBoundingClientRect().left,
          { ...layout, viewportWidth: viewport.clientWidth },
        )
      nav.track(h.pointer)
    })
    for (const mark of overviewMarks(count, 0, 2)) {
      const button = document.createElement("button")
      button.textContent = `${mark.start}–${mark.end}`
      button.dataset.start = String(mark.start)
      button.dataset.end = String(mark.end)
      button.onclick = () =>
        nav.reveal(mark.end === count - 1 ? count : mark.start)
      document.getElementById("overview")!.append(button)
    }
  }, count)
}

const offset = (page: Page) =>
  page.evaluate(() => window.boardHarness.layout.offset)

// Real RAF + native pointer: moving the strip must never scroll the document.
test("edge_pan_moves_window_not_document", async ({ page }) => {
  await harness(page)
  await page.mouse.move(419, 180)
  await expect.poll(() => offset(page)).toBeGreaterThan(30)
  await expect.poll(() => offset(page)).toBe(620)
  await page.mouse.move(101, 180)
  await expect.poll(() => offset(page)).toBeLessThan(590)
  await expect.poll(() => offset(page)).toBe(0)
  const state = await page.evaluate(() => ({
    offsets: window.boardHarness.offsets,
    scroll: [scrollX, scrollY, document.getElementById("viewport")!.scrollLeft],
  }))
  expect(state.scroll).toEqual([0, 0, 0])
  expect(state.offsets.every((x) => x.offset >= 0 && x.offset <= 620)).toBe(
    true,
  )
  for (let i = 1; i < state.offsets.length; i++) {
    const a = state.offsets[i - 1]
    const b = state.offsets[i]
    // Callback wall-time can differ from the RAF repaint timestamp; the hard
    // per-frame cap is 420px/sec * 50ms. Exact elapsed scaling is clock-tested.
    expect(Math.abs(b.offset - a.offset)).toBeLessThanOrEqual(21)
  }
})

test("pan_stops_on_cancel_blur_and_dispose", async ({ page }) => {
  await harness(page, 500)
  for (const reason of [
    "null",
    "stop",
    "pointercancel",
    "pointerup",
    "lostpointercapture",
    "blur",
    "hidden",
    "focusout",
    "dispose",
  ] as const) {
    await page.mouse.move(300, 180)
    await page.mouse.move(419, 180)
    const before = await offset(page)
    await expect.poll(() => offset(page)).toBeGreaterThan(before)
    await page.evaluate((reason) => {
      const { nav } = window.boardHarness
      if (reason === "null") nav.track(null)
      else if (reason === "stop") nav.stop()
      else if (reason === "dispose") nav.dispose()
      else if (reason === "hidden") {
        Object.defineProperty(document, "hidden", {
          configurable: true,
          value: true,
        })
        document.dispatchEvent(new Event("visibilitychange"))
        Object.defineProperty(document, "hidden", {
          configurable: true,
          value: false,
        })
      } else if (reason === "focusout") {
        document.getElementById("viewport")!.focus()
        document.getElementById("outside")!.focus()
      } else if (reason === "blur") window.dispatchEvent(new Event("blur"))
      else
        document
          .getElementById("viewport")!
          .dispatchEvent(new PointerEvent(reason, { bubbles: true }))
    }, reason)
    const stopped = await page.evaluate(() => ({
      offset: window.boardHarness.layout.offset,
      calls: window.boardHarness.offsets.length,
    }))
    await page.waitForTimeout(150)
    expect(
      await page.evaluate(() => ({
        offset: window.boardHarness.layout.offset,
        calls: window.boardHarness.offsets.length,
      })),
    ).toEqual(stopped)
  }
  await page.evaluate(() => {
    window.boardHarness.nav.track({ x: 419, y: 180 })
    window.boardHarness.nav.reveal(500)
    window.boardHarness.nav.dispose()
    document.getElementById("viewport")!.style.width = "100px"
  })
  const disposed = await offset(page)
  await page.waitForTimeout(150)
  expect(await offset(page)).toBe(disposed)
})

test("resize_during_pan_retains_target", async ({ page }) => {
  await harness(page, 500)
  await page.evaluate(() => {
    const h = window.boardHarness
    h.layout.previewSlot = 20
    h.nav.reveal(20)
  })
  expect(await offset(page)).toBe(2180)
  await page.mouse.move(419, 180)
  await expect.poll(() => offset(page)).toBeGreaterThan(2180)
  await page.evaluate(() => {
    document.getElementById("viewport")!.style.width = "160px"
  })
  await expect.poll(() => offset(page)).toBe(2340)
  expect(
    await page.evaluate(() => window.boardHarness.layout.previewSlot),
  ).toBe(20)
  await page.evaluate(() => {
    document.getElementById("viewport")!.style.width = "70000px"
  })
  await expect.poll(() => offset(page)).toBe(0)
})

test("overview_reaches_both_ends", async ({ page }) => {
  await harness(page, 500)
  expect(await page.locator("#overview button").count()).toBe(80)
  await page.locator('#overview button[data-end="499"]').click()
  expect(await offset(page)).toBe(59660)
  await page.locator('#overview button[data-start="0"]').click()
  expect(await offset(page)).toBe(0)
  expect(await page.evaluate(() => [scrollX, scrollY])).toEqual([0, 0])
})

test("elapsed_time_caps_background_jump_and_scales_edge_penetration", async ({
  page,
}) => {
  await page.clock.install({ time: new Date("2026-10-14T00:00:00Z") })
  await harness(page, 500)
  await page.clock.pauseAt(new Date("2026-10-14T00:00:01Z"))
  const started = await page.evaluate(() => {
    window.boardHarness.nav.track({ x: 396, y: 180 }) // 24px penetration = 210px/sec
    return performance.now()
  })
  await page.clock.runFor(160)
  const elapsed = await page.evaluate(() => {
    const offsets = window.boardHarness.offsets
    return offsets[offsets.length - 1].time
  })
  expect(await offset(page)).toBeCloseTo((210 * (elapsed - started)) / 1000, 1)
  expect(await offset(page)).toBeGreaterThan(30)
  const before = await offset(page)
  await page.clock.fastForward(10000)
  expect((await offset(page)) - before).toBeCloseTo(10.5, 1)
  await page.evaluate(() => window.boardHarness.nav.stop())
  const stopped = await offset(page)
  await page.clock.runFor(1000)
  expect(await offset(page)).toBe(stopped)
  const fullSpeedStarted = await page.evaluate(() => {
    window.boardHarness.nav.track({ x: 420, y: 180 })
    return performance.now()
  })
  await page.clock.runFor(160)
  const fullSpeedElapsed = await page.evaluate(() => {
    const offsets = window.boardHarness.offsets
    return offsets[offsets.length - 1].time
  })
  expect((await offset(page)) - stopped).toBeCloseTo(
    (420 * (fullSpeedElapsed - fullSpeedStarted)) / 1000,
    1,
  )
})

test("pointer_outside_vertical_band_or_in_center_does_not_pan", async ({
  page,
}) => {
  await harness(page, 500)
  for (const point of [
    { x: 419, y: 90 },
    { x: 419, y: 270 },
    { x: 300, y: 180 },
    { x: 450, y: 180 },
  ]) {
    await page.evaluate((point) => window.boardHarness.nav.track(point), point)
    await page.waitForTimeout(80)
    expect(await offset(page)).toBe(0)
  }
  expect(
    await page.evaluate(() => {
      try {
        window.boardHarness.nav.track({ x: NaN, y: 180 })
        return false
      } catch (error) {
        return error instanceof RangeError
      }
    }),
  ).toBe(true)
})

test("stationary_preview_remains_coherent_through_pan_and_reposition", async ({
  page,
}) => {
  await harness(page, 500)
  await page.evaluate(() => {
    window.boardHarness.livePreview = true
  })
  await page.mouse.move(419, 180)
  await expect.poll(() => offset(page)).toBeGreaterThan(150)
  // Opening a preview adds one stride; offset >150 can still correctly map
  // to slot 3. Wait for the same geometric target we assert below.
  await expect
    .poll(() => page.evaluate(() => window.boardHarness.layout.previewSlot))
    .toBeGreaterThan(3)
  const during = await page.evaluate(() => ({
    offset: window.boardHarness.layout.offset,
    slot: window.boardHarness.layout.previewSlot,
  }))
  expect(during.slot).toBeGreaterThan(3)
  await page.mouse.move(210, 180)
  const settled = await page.evaluate(() => ({
    offset: window.boardHarness.layout.offset,
    slot: window.boardHarness.layout.previewSlot,
  }))
  await page.waitForTimeout(150)
  expect(
    await page.evaluate(() => ({
      offset: window.boardHarness.layout.offset,
      slot: window.boardHarness.layout.previewSlot,
    })),
  ).toEqual(settled)
  await page.mouse.move(419, 180)
  await expect.poll(() => offset(page)).toBeGreaterThan(settled.offset + 100)
  await page.evaluate(() => window.boardHarness.nav.stop())
  const stopped = await offset(page)
  await page.waitForTimeout(100)
  expect(await offset(page)).toBe(stopped)
  expect(await page.evaluate(() => [scrollX, scrollY])).toEqual([0, 0])
})

test("focus_leaving_an_external_drag_source_stops_pan", async ({ page }) => {
  await harness(page, 500)
  // A pending-card hand is outside the viewport. Its focus loss must also end
  // navigation, not just focusout events originating inside the strip.
  await page.locator("#outside").focus()
  await page.mouse.move(419, 180)
  await expect.poll(() => offset(page)).toBeGreaterThan(30)
  await page.locator("#other").focus()
  const stopped = await offset(page)
  await page.waitForTimeout(150)
  expect(await offset(page)).toBe(stopped)
})

test("controlled_origin_denies_private_environment_and_evidence", async ({
  request,
}) => {
  const directory = resolve(
    "../.superpowers/sdd/2026-10-14-game-board-redesign/integration",
  )
  await mkdir(directory, { recursive: true, mode: 0o700 })
  const envName = `.env.board-deny-${randomUUID()}`
  const env = resolve(envName)
  const evidence = resolve(directory, `board-deny-${randomUUID()}.txt`)
  await writeFile(env, "Controlled private sentinel", {
    mode: 0o600,
    flag: "wx",
  })
  try {
    await writeFile(evidence, "Controlled private evidence", {
      mode: 0o600,
      flag: "wx",
    })
    try {
      for (const path of [`/${envName}`, `/@fs${env}`, `/@fs${evidence}`])
        expect((await request.get(path)).status()).toBe(403)
    } finally {
      await unlink(evidence)
    }
  } finally {
    await unlink(env)
  }
})
