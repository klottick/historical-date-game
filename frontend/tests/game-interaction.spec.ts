import { mkdir, writeFile } from "node:fs/promises"
import { test as base, expect, type Page } from "@playwright/test"
import type { PlaceCommand, RunPublic } from "../src/client/types.gen"

const api = "http://localhost:8000/api/v1"
const test = base.extend<{ run: RunPublic; headers: Record<string, string> }>({
  headers: async ({ page }, use) => {
    await page.goto("/")
    const admin = await page.evaluate(() =>
      localStorage.getItem("access_token"),
    )
    const email = `interaction-${crypto.randomUUID()}@example.com`
    const password = "GameBrowser123!"
    expect(
      (
        await page.request.post(`${api}/users/`, {
          headers: { Authorization: `Bearer ${admin}` },
          data: { email, password, full_name: "Card player" },
        })
      ).ok(),
    ).toBeTruthy()
    const login = await page.request.post(`${api}/login/access-token`, {
      form: { username: email, password },
    })
    const token = (await login.json()).access_token
    const headers = { Authorization: `Bearer ${token}` }
    await page.evaluate(
      (value) => localStorage.setItem("access_token", value),
      token,
    )
    try {
      await use(headers)
    } finally {
      expect(
        (await page.request.delete(`${api}/users/me`, { headers })).ok(),
      ).toBeTruthy()
    }
  },
  run: async ({ page, headers }, use) => {
    const options = await (
      await page.request.get(`${api}/games/options`, { headers })
    ).json()
    const response = await page.request.post(`${api}/games/freeplay`, {
      headers,
      data: {
        operation_id: crypto.randomUUID(),
        catalog_release_id: options.catalog_release_id,
        config: {
          category_ids: options.categories.map((c: { id: string }) => c.id),
          start: options.start,
          end: options.end,
          min_gap: 1,
        },
      },
    })
    expect(response.ok()).toBeTruthy()
    const run: RunPublic = await response.json()
    // Normal imagery must come from real verified/mounted backend assets.
    // Only the explicit failure tests below intercept image requests.
    for (const card of [...run.timeline, run.pending!]) {
      for (const url of new Set([card.media.url, card.media.fallback_url])) {
        expect(
          (
            await page.request.get(new URL(url, "http://localhost:8000").href)
          ).status(),
          `Actual backend media: ${url}`,
        ).toBe(200)
      }
    }
    await use(run)
  },
})

async function open(page: Page, run: RunPublic) {
  await page.goto(`/play/${run.run_id}`)
  await expect(page.getByRole("heading", { name: "Next card" })).toBeVisible()
}
function posts(page: Page) {
  const commands: PlaceCommand[] = []
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/placements"))
      commands.push(r.postDataJSON())
  })
  return commands
}
async function drag(page: Page, target: string, touch: boolean) {
  const handle = page.getByRole("button", { name: "Drag next card" })
  await handle.scrollIntoViewIfNeeded()
  const start = (await handle.boundingBox())!
  const end = (await page.locator(target).boundingBox())!
  const a = { x: start.x + start.width / 2, y: start.y + start.height / 2 }
  const b = { x: end.x + end.width / 2, y: end.y + end.height / 2 }
  if (touch) {
    const cdp = await page.context().newCDPSession(page)
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchStart",
      touchPoints: [a],
    })
    await page.waitForTimeout(300)
    const height = await page.evaluate(() => innerHeight)
    const edge = Math.min(height - 24, Math.max(24, b.y))
    for (let i = 1; i <= 12; i++)
      await cdp.send("Input.dispatchTouchEvent", {
        type: "touchMove",
        touchPoints: [
          { x: a.x + ((b.x - a.x) * i) / 12, y: a.y + ((edge - a.y) * i) / 12 },
        ],
      })
    if (b.y > height || b.y < 0) {
      await expect
        .poll(async () => {
          const box = (await page.locator(target).boundingBox())!
          return box.y >= 0 && box.y + box.height <= height
        })
        .toBeTruthy()
    }
    const visible = (await page.locator(target).boundingBox())!
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [
        { x: visible.x + visible.width / 2, y: visible.y + visible.height / 2 },
      ],
    })
    await expect(page.locator(".insertion-slot-over")).toHaveCount(
      target.includes("data-slot") ? 1 : 0,
    )
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchEnd",
      touchPoints: [],
    })
    await cdp.detach()
  } else {
    await page.mouse.move(a.x, a.y)
    await page.mouse.down()
    await page.mouse.move(a.x + 12, a.y, { steps: 3 })
    await page.mouse.move(b.x, b.y, { steps: 12 })
    await page.mouse.up()
  }
}

async function keyboardDrop(page: Page, slot: number) {
  const handle = page.getByRole("button", { name: "Drag next card" })
  await handle.focus()
  await page.keyboard.press("Space")
  await expect(page.locator(".pending-draggable")).toHaveAttribute(
    "data-dragging",
    "true",
  )
  for (let i = 0; i <= slot; i++) await page.keyboard.press("ArrowRight")
  await expect(page.locator(`[data-slot="${slot}"]`)).toHaveClass(
    /insertion-slot-over/,
  )
  await page.keyboard.press("Space")
  await expect(
    page.getByRole("button", { name: `Slot ${slot + 1}`, exact: true }),
  ).toHaveAttribute("aria-pressed", "true")
  await expect(handle).toBeFocused()
}

test("drop_previews_reposition_and_lock", async ({
  page,
  run,
  isMobile,
}, info) => {
  await open(page, run)
  const commands = posts(page)
  await expect(page.getByRole("button", { name: /^Slot \d+$/ })).toHaveCount(
    run.timeline.length + 1,
  )
  await expect(
    page.getByRole("button", { name: "Drag next card" }),
  ).toHaveCount(1)
  await drag(page, '[data-slot="0"]', isMobile)
  await expect(
    page.getByRole("button", { name: "Slot 1", exact: true }),
  ).toHaveAttribute("aria-pressed", "true")
  await page.getByRole("button", { name: "Last slot", exact: true }).click()
  await expect(
    page.getByRole("button", {
      name: `Slot ${run.timeline.length + 1}`,
      exact: true,
    }),
  ).toHaveAttribute("aria-pressed", "true")
  expect(commands).toHaveLength(0)
  const dir =
    "../.superpowers/sdd/2026-10-11-historical-date-game-beta/artifacts"
  await mkdir(dir, { recursive: true })
  await page.screenshot({
    path: `${dir}/U3-${info.project.name}.png`,
    fullPage: true,
  })
  await info.attach("layout", {
    body: JSON.stringify(
      await page.evaluate(() => ({
        viewport: [innerWidth, innerHeight],
        body: document.body.scrollWidth,
        timeline: document
          .querySelector(".game-timeline")
          ?.getBoundingClientRect()
          .toJSON(),
        pending: document
          .querySelector('[data-testid="pending-card"]')
          ?.getBoundingClientRect()
          .toJSON(),
      })),
    ),
    contentType: "application/json",
  })
  await writeFile(
    `${dir}/U3-layout-${info.project.name}.json`,
    JSON.stringify(
      await page.evaluate(() => ({
        viewport: [innerWidth, innerHeight],
        body: document.body.scrollWidth,
        timeline: document
          .querySelector(".game-timeline")
          ?.getBoundingClientRect()
          .toJSON(),
        pending: document
          .querySelector('[data-testid="pending-card"]')
          ?.getBoundingClientRect()
          .toJSON(),
        slots: Array.from(document.querySelectorAll(".insertion-slot")).map(
          (e) => e.getBoundingClientRect().toJSON(),
        ),
        controls: Array.from(
          document.querySelectorAll(
            ".placement-actions button, .slot-shortcuts button, .drag-handle",
          ),
        ).map((e) => ({
          text: e.textContent,
          ...e.getBoundingClientRect().toJSON(),
        })),
      })),
      null,
      2,
    ),
  )
  const response = page.waitForResponse((r) => r.url().endsWith("/placements"))
  await page.getByRole("button", { name: "Lock it in", exact: true }).click()
  expect((await response).ok()).toBeTruthy()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${run.revision + 1}`,
  )
  expect(commands).toHaveLength(1)
  expect(commands[0].slot).toBe(run.timeline.length)
})

test("outside_drop_and_escape_do_not_submit", async ({
  page,
  run,
  isMobile,
}) => {
  await open(page, run)
  const commands = posts(page)
  await page.getByRole("button", { name: "Slot 1", exact: true }).click()
  await drag(page, ".game-heading", isMobile)
  await expect(
    page.getByText("No slot selected.", { exact: true }),
  ).toBeVisible()
  const handle = page.getByRole("button", { name: "Drag next card" })
  await handle.focus()
  await page.keyboard.press("Space")
  await page.keyboard.press("Escape")
  await expect(handle).toBeFocused()
  await expect(
    page.getByRole("button", { name: "Lock it in", exact: true }),
  ).toBeDisabled()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${run.revision}`,
  )
  expect(commands).toHaveLength(0)
})

test("touch_and_keyboard_can_place_every_slot", async ({
  page,
  run,
  isMobile,
}) => {
  await open(page, run)
  const commands = posts(page)
  for (let index = 0; index <= run.timeline.length; index++) {
    const slot = page.getByRole("button", {
      name: `Slot ${index + 1}`,
      exact: true,
    })
    const box = (await slot.boundingBox())!
    expect(box.height).toBeGreaterThanOrEqual(44)
    expect(box.width).toBeGreaterThanOrEqual(44)
    if (isMobile) await slot.tap()
    else await slot.click()
    await expect(slot).toHaveAttribute("aria-pressed", "true")
    await slot.focus()
    await page.keyboard.press("Enter")
    await expect(slot).toBeFocused()
    await keyboardDrop(page, index)
  }
  await page.getByRole("button", { name: "First slot", exact: true }).click()
  await page.getByRole("button", { name: "Next slot", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Slot 2", exact: true }),
  ).toHaveAttribute("aria-pressed", "true")
  await page.getByRole("button", { name: "Previous slot", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Slot 1", exact: true }),
  ).toHaveAttribute("aria-pressed", "true")
  expect(commands).toHaveLength(0)
})

test("image_failure_does_not_change_state", async ({ page, run }, info) => {
  // Controlled public media only: failure must not change scoring or geometry.
  const media = {
    ...run.pending!.media,
    url: "/failed-primary.svg",
    fallback_url: "/failed-fallback.svg",
  }
  await page.route(`**/games/runs/${run.run_id}`, (r) =>
    r.fulfill({ json: { ...run, pending: { ...run.pending, media } } }),
  )
  const requests: string[] = []
  await page.route("**/failed-*.svg", async (r) => {
    requests.push(r.request().url())
    await r.abort()
  })
  await open(page, run)
  const commands = posts(page)
  await page.getByRole("button", { name: "Slot 1", exact: true }).click()
  await expect(
    page
      .getByTestId("pending-card")
      .getByRole("img", { name: /Image unavailable/ }),
  ).toBeVisible()
  for (const credit of media.credits)
    await expect(page.getByTestId("pending-card")).toContainText(credit.label)
  expect(requests.filter((r) => r.endsWith("failed-primary.svg"))).toHaveLength(
    1,
  )
  expect(
    requests.filter((r) => r.endsWith("failed-fallback.svg")),
  ).toHaveLength(1)
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${run.revision}`,
  )
  await expect(
    page.getByText(`Streak: ${run.streak}`, { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByText("Preview: slot 1.", { exact: true }),
  ).toBeVisible()
  expect(commands).toHaveLength(0)
  await page.screenshot({
    path: `../.superpowers/sdd/2026-10-11-historical-date-game-beta/artifacts/U3-placeholder-${info.project.name}.png`,
    fullPage: true,
  })
})

test("public_media_loads_from_api_origin", async ({ page, run }) => {
  await open(page, run)
  const image = page.getByTestId("pending-card").locator("img")
  await expect(image).toBeVisible()
  await expect
    .poll(() => image.evaluate((e: HTMLImageElement) => e.naturalWidth))
    .toBeGreaterThan(0)
  const window = (await page
    .getByTestId("pending-card")
    .locator(".event-image-window")
    .boundingBox())!
  expect(window.width / window.height).toBeCloseTo(4 / 3, 2)
  expect(await image.evaluate((e) => getComputedStyle(e).objectFit)).toBe(
    run.pending!.media.fit,
  )
  if (run.pending!.media.url.startsWith("/"))
    expect(await image.getAttribute("src")).toBe(
      `http://localhost:8000${run.pending!.media.url}`,
    )
})

test("long_timeline_all_gaps_and_controls_remain_reachable", async ({
  page,
  run,
  isMobile,
}, info) => {
  // Layout-only public DTO: repeating a revealed card exposes no new answers.
  const cards = Array.from({ length: 8 }, (_, i) => ({
    ...run.timeline[0],
    event_id: `layout-${i}`,
  }))
  await page.route(`**/games/runs/${run.run_id}`, (r) =>
    r.fulfill({ json: { ...run, timeline: cards } }),
  )
  await open(page, run)
  const commands = posts(page)
  await expect(page.getByRole("button", { name: /^Slot \d+$/ })).toHaveCount(9)
  for (let index = 0; index < 9; index++) {
    const slot = page.getByRole("button", {
      name: `Slot ${index + 1}`,
      exact: true,
    })
    await slot.scrollIntoViewIfNeeded()
    if (isMobile) await slot.tap()
    else {
      await slot.focus()
      await page.keyboard.press("Enter")
    }
    await expect(slot).toHaveAttribute("aria-pressed", "true")
    await keyboardDrop(page, index)
  }
  if (!isMobile) {
    const timeline = page.locator(".game-timeline")
    await timeline.evaluate((e) => {
      e.scrollLeft = 0
    })
    const handle = page.getByRole("button", { name: "Drag next card" })
    await handle.scrollIntoViewIfNeeded()
    const start = (await handle.boundingBox())!
    const table = (await timeline.boundingBox())!
    await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2)
    await page.mouse.down()
    await page.mouse.move(
      table.x + table.width - 12,
      table.y + table.height / 2,
      { steps: 16 },
    )
    await expect
      .poll(() => timeline.evaluate((e) => e.scrollLeft))
      .toBeGreaterThan(0)
    await page.keyboard.press("Escape")
    await page.mouse.up()
  }
  for (const name of [
    "First slot",
    "Last slot",
    "Previous slot",
    "Next slot",
    "Lock it in",
  ]) {
    const control = page.getByRole("button", { name, exact: true })
    await control.scrollIntoViewIfNeeded()
    await expect(control).toBeInViewport()
    const box = (await control.boundingBox())!
    expect(box.height).toBeGreaterThanOrEqual(44)
  }
  expect(
    await page.evaluate(() => document.body.scrollWidth <= innerWidth),
  ).toBeTruthy()
  const dimensions = await page.locator(".game-timeline").evaluate((e) => ({
    width: e.clientWidth,
    scrollWidth: e.scrollWidth,
    height: e.clientHeight,
    direction: getComputedStyle(e).flexDirection,
  }))
  expect(dimensions.direction).toBe(isMobile ? "column" : "row")
  if (!isMobile)
    expect(dimensions.scrollWidth).toBeGreaterThan(dimensions.width)
  console.info(
    `U3 ${info.project.name} long timeline: ${JSON.stringify(dimensions)}`,
  )
  await page.screenshot({
    path: `../.superpowers/sdd/2026-10-11-historical-date-game-beta/artifacts/U3-long-${info.project.name}.png`,
    fullPage: true,
  })
  expect(commands).toHaveLength(0)
})

test("slow_image_and_primary_failure_preserve_target_geometry", async ({
  page,
  run,
}) => {
  const media = {
    ...run.pending!.media,
    url: "/slow-primary.svg",
    fallback_url: run.pending!.media.fallback_url,
  }
  await page.route(`**/games/runs/${run.run_id}`, (r) =>
    r.fulfill({ json: { ...run, pending: { ...run.pending, media } } }),
  )
  let release!: () => void
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route("**/slow-primary.svg", async (r) => {
    await held
    await r.abort()
  })
  try {
    await page.goto(`/play/${run.run_id}`, { waitUntil: "domcontentloaded" })
    const slot = page.getByRole("button", { name: "Slot 1", exact: true })
    await expect(slot).toBeVisible()
    const geometry = () =>
      slot.evaluate((e) => {
        const rect = e.getBoundingClientRect()
        return {
          x: rect.x + scrollX,
          y: rect.y + scrollY,
          width: rect.width,
          height: rect.height,
        }
      })
    const before = await geometry()
    await slot.click()
    await expect(
      page.getByRole("button", { name: "Lock it in", exact: true }),
    ).toBeEnabled()
    release()
    const image = page.getByTestId("pending-card").locator("img")
    await expect
      .poll(() => image.evaluate((e: HTMLImageElement) => e.naturalWidth))
      .toBeGreaterThan(0)
    expect(await geometry()).toEqual(before)
    await expect(slot).toHaveAttribute("aria-pressed", "true")
    await expect(page.getByTestId("run-revision")).toHaveText(
      `Revision: ${run.revision}`,
    )
  } finally {
    release()
  }
})

test("lifted_overlay_keeps_the_frame_and_reduced_motion_removes_decoration", async ({
  page,
  run,
}, info) => {
  await open(page, run)
  const handle = page.getByRole("button", { name: "Drag next card" })
  await handle.focus()
  await page.keyboard.press("Space")
  const overlay = page.locator(".game-drag-overlay")
  await expect(overlay).toBeVisible()
  expect(
    await overlay
      .locator(".game-card")
      .evaluate((e) => getComputedStyle(e).backgroundColor),
  ).toBe("rgb(247, 240, 223)")
  await page.screenshot({
    path: `../.superpowers/sdd/2026-10-11-historical-date-game-beta/artifacts/U3-lift-${info.project.name}.png`,
  })
  await page.keyboard.press("Escape")
  await expect(overlay).toBeHidden()
  await page.emulateMedia({ reducedMotion: "reduce" })
  await handle.focus()
  await page.keyboard.press("Space")
  await expect(overlay).toBeVisible()
  await expect
    .poll(() => overlay.evaluate((e) => getComputedStyle(e).transform))
    .toBe("none")
  await page.keyboard.press("Escape")
  await expect(
    page.getByRole("button", { name: "Lock it in", exact: true }),
  ).toBeDisabled()
})

test("victory_keeps_full_width_timeline_and_navigation_nonblocking", async ({
  page,
  run,
  isMobile,
}, info) => {
  const won: RunPublic = {
    ...run,
    status: "won",
    pending: null,
    feedback: null,
    streak: 7,
    revision: 8,
  }
  await page.route(`**/games/runs/${run.run_id}`, (r) =>
    r.fulfill({ json: won }),
  )
  await page.goto(`/play/${run.run_id}`)
  await expect(
    page.getByRole("heading", { name: "Victory — catalog exhausted" }),
  ).toBeVisible()
  await expect(page.getByRole("dialog")).toHaveCount(0)
  const width = (await page.locator(".timeline-panel").boundingBox())!.width
  expect(width).toBeGreaterThan(isMobile ? 300 : 900)
  await expect(
    page.getByRole("link", { name: "New Freeplay", exact: true }),
  ).toBeVisible()
  const link = (await page
    .getByRole("link", { name: "New Freeplay", exact: true })
    .boundingBox())!
  const report = (await page
    .getByRole("button", { name: "Report content issue" })
    .boundingBox())!
  expect(link.height).toBeGreaterThanOrEqual(44)
  expect(report.x - link.x - link.width).toBeGreaterThanOrEqual(8)
  await page.screenshot({
    path: `../.superpowers/sdd/2026-10-11-historical-date-game-beta/artifacts/U3-victory-${info.project.name}.png`,
    fullPage: true,
  })
})

test("mistake_credits_remain_readable_on_the_cream_result_in_dark_theme", async ({
  page,
  run,
}, info) => {
  await page.evaluate(() => localStorage.setItem("vite-ui-theme", "dark"))
  const lost: RunPublic = {
    ...run,
    status: "lost",
    pending: null,
    feedback: { correct: false, card: run.timeline[0], correct_slot: 0 },
  }
  await page.route(`**/games/runs/${run.run_id}`, (r) =>
    r.fulfill({ json: lost }),
  )
  await page.goto(`/play/${run.run_id}`)
  const credits = page
    .getByRole("region", { name: "Run result" })
    .locator(".text-muted-foreground")
  await expect(credits).toBeVisible()
  const contrast = await credits.evaluate((e) => {
    const luminance = (color: string) => {
      const canvas = document.createElement("canvas")
      canvas.width = canvas.height = 1
      const context = canvas.getContext("2d")!
      context.fillStyle = color
      context.fillRect(0, 0, 1, 1)
      const channels = Array.from(context.getImageData(0, 0, 1, 1).data)
        .slice(0, 3)
        .map((n) => n / 255)
        .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
      return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
    }
    const a = luminance(getComputedStyle(e).color)
    const b = luminance(
      getComputedStyle(e.closest(".move-feedback")!).backgroundColor,
    )
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
  })
  expect(contrast).toBeGreaterThanOrEqual(4.5)
  await page.screenshot({
    path: `../.superpowers/sdd/2026-10-11-historical-date-game-beta/artifacts/U3-mistake-${info.project.name}.png`,
    fullPage: true,
  })
})

test("reduced_motion_preserves_feedback", async ({
  page,
  run,
  headers,
}, info) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  let current = run
  for (let attempt = 0; attempt < 20; attempt++) {
    await open(page, current)
    await page.getByRole("button", { name: "Slot 1", exact: true }).click()
    const response = page.waitForResponse((r) =>
      r.url().endsWith("/placements"),
    )
    await page.getByRole("button", { name: "Lock it in", exact: true }).click()
    const scored: RunPublic = await (await response).json()
    await expect(page.getByTestId("move-feedback")).toContainText(
      scored.feedback!.correct ? "Correct" : "Correct slot",
    )
    await expect(page.getByTestId("move-feedback")).toContainText(
      `${scored.feedback!.card.year.value} ${scored.feedback!.card.year.era}`,
    )
    if (scored.feedback!.correct) {
      await expect(page.getByTestId("move-feedback")).toContainText(
        `Streak: ${scored.streak}`,
      )
      expect(
        await page
          .getByTestId("move-feedback")
          .evaluate((e) => getComputedStyle(e).animationName),
      ).toBe("none")
      await page.screenshot({
        path: `../.superpowers/sdd/2026-10-11-historical-date-game-beta/artifacts/U3-reduced-motion-${info.project.name}.png`,
        fullPage: true,
      })
      return
    }
    current = await (
      await page.request.post(`${api}/games/freeplay`, {
        headers,
        data: {
          operation_id: crypto.randomUUID(),
          catalog_release_id: run.catalog_release_id,
          config: run.config,
        },
      })
    ).json()
  }
  throw new Error("No successful blind move after 20 independent runs")
})
