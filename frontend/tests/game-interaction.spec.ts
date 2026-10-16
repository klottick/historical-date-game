import { chmod, mkdir, writeFile } from "node:fs/promises"
import { test as base, expect, type Page } from "@playwright/test"
import type { PlaceCommand, RunPublic } from "../src/client/types.gen"
import { fixtureAPI as api, fixtureAPIOrigin } from "./utils/apiOrigin"
import { boardEvidence } from "./utils/boardEvidence"
import { dragTile, keyboardPreview } from "./utils/boardInteraction"
import { readGameOptions } from "./utils/gameOptions"

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
    const options = await readGameOptions(
      await page.request.get(`${api}/games/options`, { headers }),
    )
    const response = await page.request.post(`${api}/games/freeplay`, {
      headers,
      data: {
        operation_id: crypto.randomUUID(),
        protocol_version: 2,
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
    // Normal imagery is still verified against actual mounted backend assets.
    for (const card of [...run.timeline, run.pending!])
      for (const url of new Set([card.media.url, card.media.fallback_url]))
        expect(
          (
            await page.request.get(new URL(url, fixtureAPIOrigin).href)
          ).status(),
          `Actual backend media: ${url}`,
        ).toBe(200)
    await use(run)
  },
})
const evidence = boardEvidence
async function open(page: Page, run: RunPublic) {
  await page.goto(`/play/${run.run_id}`)
  await expect(page.getByTestId("pending-card")).toBeVisible()
}
function posts(page: Page) {
  const commands: PlaceCommand[] = []
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/placements"))
      commands.push(request.postDataJSON())
  })
  return commands
}
async function capture(page: Page, name: string) {
  await mkdir(evidence, { recursive: true, mode: 0o700 })
  await page.screenshot({ path: `${evidence}/${name}.png`, fullPage: true })
  await chmod(`${evidence}/${name}.png`, 0o600)
}

test("drop_previews_reposition_and_lock", async ({
  page,
  run,
  isMobile,
}, info) => {
  await open(page, run)
  const commands = posts(page)
  await expect(page.locator(".timeline-item")).toHaveCount(run.timeline.length)
  await expect(page.locator(".pending-draggable")).toHaveCount(1)
  await dragTile(page, 0, isMobile)
  await keyboardPreview(page, run.timeline.length)
  expect(commands).toHaveLength(0)
  await capture(page, `U3-${info.project.name}`)
  const response = page.waitForResponse((r) => r.url().endsWith("/placements"))
  await page.getByRole("button", { name: "Confirm", exact: true }).click()
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
  await keyboardPreview(page, 0)
  const tile = (await page.locator(".pending-draggable").boundingBox())!
  if (isMobile) {
    const cdp = await page.context().newCDPSession(page)
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchStart",
      touchPoints: [{ x: tile.x + 70, y: tile.y + 70 }],
    })
    await page.waitForTimeout(250)
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [{ x: 30, y: 20 }],
    })
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchEnd",
      touchPoints: [],
    })
    await cdp.detach()
  } else {
    await page.mouse.move(tile.x + 70, tile.y + 70)
    await page.mouse.down()
    await page.mouse.move(30, 20, { steps: 12 })
    await page.mouse.up()
  }
  // Approved contract: an outside drop preserves the previous unlocked preview.
  await expect(page.locator("[data-preview-slot]")).toHaveAttribute(
    "data-preview-slot",
    "0",
  )
  await page
    .getByRole("button", { name: "Return to hand", exact: true })
    .click()
  const surface = page.locator(".pending-draggable")
  await surface.focus()
  await page.keyboard.press("Space")
  await page.keyboard.press("Escape")
  await expect(surface).toBeFocused()
  await expect(
    page.getByRole("button", { name: "Confirm", exact: true }),
  ).toHaveCount(0)
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
    if (index > 0)
      await page
        .getByRole("button", { name: "Return to hand", exact: true })
        .click()
    if (isMobile) await dragTile(page, index, true)
    await keyboardPreview(page, index)
    const box = (await page.locator(".pending-draggable").boundingBox())!
    expect(box.height).toBeGreaterThanOrEqual(44)
    expect(box.width).toBeGreaterThanOrEqual(44)
    await expect(page.locator(".pending-draggable")).toBeInViewport({
      ratio: 1,
    })
  }
  await keyboardPreview(page, 1)
  await keyboardPreview(page, 0)
  expect(commands).toHaveLength(0)
})

test("image_failure_does_not_change_state", async ({ page, run }, info) => {
  const media = {
    ...run.pending!.media,
    url: "/failed-primary.svg",
    fallback_url: "/failed-fallback.svg",
  }
  await page.route(`**/games/runs/${run.run_id}`, (route) =>
    route.fulfill({ json: { ...run, pending: { ...run.pending, media } } }),
  )
  const requests: string[] = []
  await page.route("**/failed-*.svg", async (route) => {
    requests.push(route.request().url())
    await route.abort()
  })
  await open(page, run)
  const commands = posts(page)
  await keyboardPreview(page, 0)
  await expect(
    page
      .getByTestId("pending-card")
      .getByRole("img", { name: /Image unavailable/ }),
  ).toBeVisible()
  await page
    .getByRole("button", { name: "Credits/Sources", exact: true })
    .click()
  for (const credit of media.credits)
    await expect(page.getByRole("dialog")).toContainText(credit.label)
  await expect(page.getByRole("dialog")).toContainText(media.url)
  await expect(page.getByRole("dialog")).toContainText(media.fallback_url)
  await page.keyboard.press("Escape")
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
  await expect(page.locator("[data-preview-slot]")).toHaveAttribute(
    "data-preview-slot",
    "0",
  )
  expect(commands).toHaveLength(0)
  await capture(page, `U3-placeholder-${info.project.name}`)
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
  expect(window.width).toBeGreaterThanOrEqual(80)
  expect(window.height).toBeGreaterThanOrEqual(80)
  expect(await image.evaluate((e) => getComputedStyle(e).objectFit)).toBe(
    run.pending!.media.fit,
  )
  if (run.pending!.media.url.startsWith("/"))
    expect(await image.getAttribute("src")).toBe(
      `${fixtureAPIOrigin}${run.pending!.media.url}`,
    )
})

test("long_timeline_all_gaps_and_controls_remain_reachable", async ({
  page,
  run,
  isMobile,
}, info) => {
  const cards = Array.from({ length: 8 }, (_, index) => ({
    ...run.timeline[0],
    event_id: `layout-${index}`,
  }))
  await page.route(`**/games/runs/${run.run_id}`, (route) =>
    route.fulfill({ json: { ...run, timeline: cards } }),
  )
  await open(page, run)
  const commands = posts(page)
  await expect(page.locator(".timeline-item")).toHaveCount(8)
  for (let index = 0; index <= 8; index++) {
    await keyboardPreview(page, index)
    await expect(page.locator(".pending-draggable")).toBeInViewport({
      ratio: 1,
    })
  }
  if (!isMobile) {
    await page
      .getByRole("button", { name: "Return to hand", exact: true })
      .click()
    await page
      .getByRole("button", { name: "Show beginning", exact: true })
      .click()
    // Like dragTile, wait for the card's settle to be actionable before pickup.
    await page
      .locator(".pending-draggable")
      .hover({ position: { x: 70, y: 70 } })
    const tile = (await page.locator(".pending-draggable").boundingBox())!
    const board = (await page.locator(".timeline-viewport").boundingBox())!
    await page.mouse.move(tile.x + 70, tile.y + 70)
    await page.mouse.down()
    await page.mouse.move(tile.x + 82, tile.y + 70, { steps: 8 })
    await expect(page.locator(".preview-status")).toContainText("Card lifted")
    await page.mouse.move(board.x + board.width - 4, board.y + 90, {
      steps: 16,
    })
    await expect
      .poll(async () =>
        Number(
          await page.locator(".timeline-viewport").getAttribute("data-offset"),
        ),
      )
      .toBeGreaterThan(0)
    await page.keyboard.press("Escape")
    await page.mouse.up()
  }
  for (const name of [
    "Show beginning",
    "Show end",
    ...(isMobile ? ["Confirm"] : []),
  ]) {
    const control = page.getByRole("button", { name, exact: true })
    await expect(control).toBeVisible()
    expect((await control.boundingBox())!.height).toBeGreaterThanOrEqual(44)
  }
  expect(
    await page.evaluate(() => document.body.scrollWidth <= innerWidth),
  ).toBe(true)
  const dimensions = await page.locator(".timeline-viewport").evaluate((e) => ({
    width: e.clientWidth,
    height: e.clientHeight,
    overflow: getComputedStyle(e).overflowX,
  }))
  expect(dimensions.width).toBeGreaterThanOrEqual(200)
  expect(dimensions.height).toBeGreaterThanOrEqual(320)
  expect(dimensions.overflow).toBe("clip")
  await mkdir(evidence, { recursive: true, mode: 0o700 })
  await writeFile(
    `${evidence}/U3-long-${info.project.name}.json`,
    JSON.stringify(dimensions),
    { mode: 0o600 },
  )
  await capture(page, `U3-long-${info.project.name}`)
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
  await page.route(`**/games/runs/${run.run_id}`, (route) =>
    route.fulfill({ json: { ...run, pending: { ...run.pending, media } } }),
  )
  let release!: () => void
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route("**/slow-primary.svg", async (route) => {
    await held
    await route.abort()
  })
  try {
    await page.goto(`/play/${run.run_id}`, { waitUntil: "domcontentloaded" })
    await expect(page.locator(".timeline-viewport")).toBeVisible()
    const geometry = () =>
      page
        .locator(".timeline-viewport")
        .evaluate((e) => e.getBoundingClientRect().toJSON())
    const before = await geometry()
    await keyboardPreview(page, 0)
    await expect(
      page.getByRole("button", { name: "Confirm", exact: true }),
    ).toBeEnabled()
    release()
    const image = page.getByTestId("pending-card").locator("img")
    await expect
      .poll(() => image.evaluate((e: HTMLImageElement) => e.naturalWidth))
      .toBeGreaterThan(0)
    expect(await geometry()).toEqual(before)
    await expect(page.locator("[data-preview-slot]")).toHaveAttribute(
      "data-preview-slot",
      "0",
    )
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
  const tile = page.locator(".pending-draggable")
  await tile.focus()
  await page.keyboard.press("Space")
  await expect(page.locator(".insertion-preview")).toBeVisible()
  await expect(tile).toBeInViewport({ ratio: 1 })
  expect(
    await tile
      .locator(".game-card")
      .evaluate((e) => getComputedStyle(e).backgroundColor),
  ).toBe("rgb(247, 241, 229)")
  await capture(page, `U3-lift-${info.project.name}`)
  await page.keyboard.press("Escape")
  await expect(page.locator(".insertion-preview")).toHaveCount(0)
  await page.emulateMedia({ reducedMotion: "reduce" })
  await tile.focus()
  await page.keyboard.press("Space")
  await expect(page.locator(".insertion-preview")).toBeVisible()
  expect(
    await page
      .locator(".pending-position")
      .evaluate((e) => getComputedStyle(e).transitionDuration),
  ).toBe("0s")
  await page.keyboard.press("Escape")
  await expect(
    page.getByRole("button", { name: "Confirm", exact: true }),
  ).toHaveCount(0)
})

test("victory_keeps_full_width_timeline_and_navigation_nonblocking", async ({
  page,
  run,
  isMobile,
}, info) => {
  const won: RunPublic = {
    ...run,
    status: "won",
    initial_lives: 3,
    lives_remaining: 3,
    score: 3,
    pending: null,
    feedback: null,
    streak: 7,
    revision: 8,
  }
  await page.route(`**/games/runs/${run.run_id}`, (route) =>
    route.fulfill({ json: won }),
  )
  await page.goto(`/play/${run.run_id}`)
  await expect(
    page.getByRole("heading", { name: "Victory — catalog exhausted" }),
  ).toBeVisible()
  await expect(page.getByRole("dialog")).toHaveCount(0)
  expect(
    (await page.locator(".timeline-viewport").boundingBox())!.width,
  ).toBeGreaterThan(isMobile ? 300 : 900)
  const link = page.getByRole("link", { name: "New Freeplay", exact: true })
  const report = page.getByRole("button", {
    name: "Report content issue",
    exact: true,
  })
  await expect(link).toBeVisible()
  await expect(report).toBeVisible()
  expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(44)
  expect((await report.boundingBox())!.height).toBeGreaterThanOrEqual(44)
  const a = (await link.boundingBox())!
  const b = (await report.boundingBox())!
  expect(
    a.x + a.width <= b.x ||
      b.x + b.width <= a.x ||
      a.y + a.height <= b.y ||
      b.y + b.height <= a.y,
  ).toBe(true)
  await capture(page, `U3-victory-${info.project.name}`)
})

test("mistake_credits_remain_readable_on_the_cream_result_in_dark_theme", async ({
  page,
  run,
}, info) => {
  await page.evaluate(() => localStorage.setItem("vite-ui-theme", "dark"))
  const lost: RunPublic = {
    ...run,
    status: "lost",
    initial_lives: 3,
    lives_remaining: 0,
    score: 0,
    pending: null,
    feedback: {
      correct: false,
      card: { ...run.timeline[0], event_id: "mistaken-event" },
      attempted_slot: 0,
      correct_slot: 0,
    },
  }
  await page.route(`**/games/runs/${run.run_id}`, (route) =>
    route.fulfill({ json: lost }),
  )
  await page.goto(`/play/${run.run_id}`)
  await expect(page.locator('.timeline-item[data-wrong="true"]')).toHaveCount(1)
  await expect(
    page.getByText("Old placement position unavailable.", { exact: true }),
  ).toHaveCount(0)
  await page
    .getByRole("button", { name: "Credits/Sources", exact: true })
    .click()
  const credits = page.getByRole("dialog").locator("li").first()
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
      getComputedStyle(e.closest(".game-dialog")!).backgroundColor,
    )
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
  })
  expect(contrast).toBeGreaterThanOrEqual(4.5)
  for (const credit of run.timeline[0].media.credits)
    await expect(page.getByRole("dialog")).toContainText(credit.label)
  await capture(page, `U3-mistake-${info.project.name}`)
})

test("reduced_motion_preserves_feedback", async ({ page, run }, info) => {
  // The retained test_game_daily.py synthetic fixture only; no private catalog
  // or answer is injected into the page, and no blind-trial retry loop is used.
  const years: Record<string, number> = {
    "Synthetic Milestone 0 Revision 0 begins": 1800,
    "Synthetic Milestone 0 Revision 0 ends": 1870,
    "Synthetic Milestone 1 Revision 0 is launched": 1810,
    "Synthetic Milestone 1 Revision 0 lands": 1880,
    "Synthetic Milestone 2 Revision 0 is invented": 1820,
    "Synthetic Milestone 3 Revision 0 is established": 1830,
    "Synthetic Milestone 4 Revision 0 is born": 1000,
    "Synthetic Milestone 4 Revision 0 dies": 2000,
  }
  const year = years[run.pending!.prompt]
  expect(
    year,
    `Known synthetic fixture only: ${run.pending!.prompt}`,
  ).toBeDefined()
  const slot = run.timeline.filter(
    (card) => card.year.era === "BCE" || card.year.value < year,
  ).length
  await page.emulateMedia({ reducedMotion: "reduce" })
  await open(page, run)
  await keyboardPreview(page, slot)
  const response = page.waitForResponse((r) => r.url().endsWith("/placements"))
  await page.getByRole("button", { name: "Confirm", exact: true }).click()
  const scored: RunPublic = await (await response).json()
  expect(scored.feedback!.correct).toBe(true)
  await expect(page.getByTestId("move-feedback")).toContainText("Correct")
  await expect(
    page.locator(
      `.game-card[data-event-id="${scored.feedback!.card.event_id}"]`,
    ),
  ).toContainText(
    `${scored.feedback!.card.year.value} ${scored.feedback!.card.year.era}`,
  )
  await expect(
    page.getByText(`Streak: ${scored.streak}`, { exact: true }),
  ).toBeVisible()
  expect(
    await page
      .getByTestId("move-feedback")
      .evaluate((e) => getComputedStyle(e).animationName),
  ).toBe("none")
  await capture(page, `U3-reduced-motion-${info.project.name}`)
})
