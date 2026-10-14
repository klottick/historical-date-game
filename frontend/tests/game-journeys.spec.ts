import { mkdir, writeFile } from "node:fs/promises"
import {
  test as base,
  devices,
  expect,
  type Locator,
  type Page,
} from "@playwright/test"
import type { RunPublic } from "../src/client/types.gen"
import { hundredCardRun } from "./fixtures/game-public"

import { fixtureAPI as api } from "./utils/apiOrigin"

const evidence =
  "../.superpowers/sdd/2026-10-13-historical-date-game-guest-play/task-5-evidence/fixture-artifacts"
type Player = {
  token: string
  headers: Record<string, string>
  name: string
  email: string
}
const test = base.extend<{ players: Player[] }>({
  players: async ({ page }, use) => {
    await page.goto("/")
    const admin = await page.evaluate(() =>
      localStorage.getItem("access_token"),
    )
    const players: Player[] = []
    try {
      for (let i = 0; i < 2; i++) {
        const id = crypto.randomUUID()
        const email = `journey-${id}@example.com`
        const name = `Timeline ${id.slice(0, 8)}`
        const password = "GameBrowser123!"
        expect(
          (
            await page.request.post(`${api}/users/`, {
              headers: { Authorization: `Bearer ${admin}` },
              data: { email, password, full_name: name },
            })
          ).ok(),
        ).toBeTruthy()
        const login = await page.request.post(`${api}/login/access-token`, {
          form: { username: email, password },
        })
        expect(login.ok()).toBeTruthy()
        const token = (await login.json()).access_token
        players.push({
          token,
          headers: { Authorization: `Bearer ${token}` },
          name,
          email,
        })
      }
      await page.evaluate(
        (token) => localStorage.setItem("access_token", token),
        players[0].token,
      )
      await use(players)
    } finally {
      for (const player of players)
        expect(
          (
            await page.request.delete(`${api}/users/me`, {
              headers: player.headers,
            })
          ).ok(),
        ).toBeTruthy()
    }
  },
})

function publicOnly(run: RunPublic) {
  if (run.pending) {
    expect(Object.keys(run.pending).sort()).toEqual([
      "category_ids",
      "event_id",
      "media",
      "prompt",
    ])
    expect(JSON.stringify(run.pending)).not.toMatch(
      /"(?:year|sources|explanation|seed|pool)"/,
    )
  }
  expect(JSON.stringify(run)).not.toMatch(
    /"(?:seed|pool|pending_year|owner_id|unused_events)"/,
  )
  expect(JSON.stringify(run)).not.toMatch(
    /(?:events\.jsonl|raw\.jsonl|manifest\.json)/,
  )
}

// Test-only answers for the retained *synthetic* builder in
// backend/tests/api/routes/test_game_daily.py::release (shift=0).
// Refuse unknown prompts; never inspect a DB, private catalog or production data.
function syntheticSlot(run: RunPublic) {
  const years: Record<string, number> = {
    "Synthetic Milestone 0 Revision 0 begins": 1800,
    "Synthetic Milestone 0 Revision 0 ends": 1870,
    "Synthetic Milestone 1 Revision 0 is launched": 1810,
    "Synthetic Milestone 1 Revision 0 lands": 1880,
    "Synthetic Milestone 2 Revision 0 is invented": 1820,
    "Synthetic Milestone 3 Revision 0 is established": 1830,
  }
  const year = years[run.pending!.prompt]
  expect(
    year,
    `Only the known synthetic fixture: ${run.pending!.prompt}`,
  ).toBeDefined()
  return run.timeline.filter(
    (card) => card.year.era === "BCE" || card.year.value < year,
  ).length
}

async function readRun(
  page: Page,
  id: string,
  player: Player,
): Promise<RunPublic> {
  const response = await page.request.get(`${api}/games/runs/${id}`, {
    headers: player.headers,
  })
  expect(response.ok()).toBeTruthy()
  return response.json()
}

async function lock(
  page: Page,
  run: RunPublic,
  slot: number,
): Promise<RunPublic> {
  publicOnly(run)
  const pending = page.getByTestId("pending-card")
  await expect(pending).toContainText("Year hidden")
  await expect(pending.locator("details")).toHaveCount(0)
  await expect(
    pending.locator('a[href*="wikidata"], a[href*="wikipedia"]'),
  ).toHaveCount(0)
  await page
    .getByRole("button", { name: `Slot ${slot + 1}`, exact: true })
    .click()
  const response = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/placements"),
  )
  await page.getByRole("button", { name: "Lock it in", exact: true }).click()
  const scored = await response
  expect(scored.ok()).toBeTruthy()
  const next: RunPublic = await scored.json()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${next.revision}`,
  )
  await expect(page.getByTestId("move-feedback")).toContainText(
    `${next.feedback!.card.year.value} ${next.feedback!.card.year.era}`,
  )
  publicOnly(next)
  return next
}

async function finishWin(page: Page, run: RunPublic) {
  let current = run
  while (current.status === "active") {
    expect(current.revision).toBeLessThan(8) // fixture safety guard, not an app round cap
    current = await lock(page, current, syntheticSlot(current))
    expect(current.feedback!.correct).toBe(true)
  }
  expect(current.status).toBe("won")
  expect(current.pending).toBeNull()
  await expect(
    page.getByRole("heading", { name: "Victory — catalog exhausted" }),
  ).toBeVisible()
  return current
}

async function configure(page: Page, gap = 10) {
  await page.goto("/freeplay")
  await expect(
    page.getByRole("button", { name: "Start Freeplay", exact: true }),
  ).toBeEnabled()
  for (const box of await page.getByRole("checkbox").all()) await box.uncheck()
  await page.getByRole("checkbox", { name: "Battles", exact: true }).check()
  await page.getByRole("checkbox", { name: "Exploration", exact: true }).check()
  await page.getByLabel("Start year", { exact: true }).fill("1800")
  await page
    .getByRole("combobox", { name: "Start era", exact: true })
    .selectOption("CE")
  await page.getByLabel("End year", { exact: true }).fill("1880")
  await page
    .getByRole("combobox", { name: "End era", exact: true })
    .selectOption("CE")
  await page.getByLabel("Minimum year gap").fill(String(gap))
}

async function startFreeplay(page: Page): Promise<RunPublic> {
  const response = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" && r.url().endsWith("/games/freeplay"),
  )
  await page
    .getByRole("button", { name: "Start Freeplay", exact: true })
    .click()
  const result = await response
  expect(result.ok()).toBeTruthy()
  const run = await result.json()
  await expect(page).toHaveURL(new RegExp(`/play/${run.run_id}$`))
  await expect(page.getByRole("heading", { name: "Next card" })).toBeVisible()
  return run
}

test("freeplay_category_bounds_gap_win_and_loss", async ({ page, players }) => {
  await configure(page)
  let run = await startFreeplay(page)
  expect(run.config).toEqual({
    category_ids: ["battles", "exploration"],
    start: { value: 1800, era: "CE" },
    end: { value: 1880, era: "CE" },
    min_gap: 10,
  })
  expect(run.mode).toBe("freeplay")
  expect(run.daily_date).toBeNull()
  const id = run.run_id
  run = await lock(page, run, syntheticSlot(run))
  await page.getByRole("link", { name: "Back to Home", exact: true }).click()
  await page
    .getByRole("link", {
      name: new RegExp(`Resume Freeplay.*${id.slice(0, 8)}`),
    })
    .click()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${run.revision}`,
  )
  expect(await readRun(page, id, players[0])).toEqual(run)
  const won = await finishWin(page, run)
  expect(won.timeline.map((card) => card.year.value)).toEqual([
    1800, 1810, 1870, 1880,
  ])
  expect(won.streak).toBe(3)
  const result = page.getByRole("region", { name: "Run result" })
  await expect(result).toContainText(
    "1800 CE–1880 CE, minimum gap 10; categories: Battles, Exploration)",
  )
  await expect(result).toContainText(won.catalog_release_id)
  await page.reload()
  await expect(
    page.getByRole("button", { name: "Lock it in", exact: true }),
  ).toHaveCount(0)
  expect(await readRun(page, id, players[0])).toEqual(won)
  await page.getByRole("link", { name: "New Freeplay", exact: true }).click()
  await configure(page, 70)
  const spaced = await finishWin(page, await startFreeplay(page))
  expect(spaced.timeline).toHaveLength(2)
  expect(
    spaced.timeline[1].year.value - spaced.timeline[0].year.value,
  ).toBeGreaterThanOrEqual(70)
  await configure(page)
  const fresh = await startFreeplay(page)
  expect(fresh.run_id).not.toBe(id)
  const lost = await lock(page, fresh, syntheticSlot(fresh) === 0 ? 1 : 0)
  expect(lost.status).toBe("lost")
  expect(lost.streak).toBe(0)
  await expect(
    page.getByRole("heading", { name: "Mistake — run complete" }),
  ).toBeVisible()
  await expect(page.getByRole("region", { name: "Run result" })).toContainText(
    `Correct slot: ${lost.feedback!.correct_slot + 1}`,
  )
  await expect(
    page.getByRole("button", { name: "Lock it in", exact: true }),
  ).toHaveCount(0)
})

test("daily_shared_game_one_attempt_and_leaderboard", async ({
  page,
  browser,
  players,
  isMobile,
}) => {
  const context = await browser.newContext({
    ...(isMobile ? devices["Pixel 5"] : devices["Desktop Chrome"]),
    baseURL: "http://localhost:5173",
    storageState: {
      cookies: [],
      origins: [
        {
          origin: "http://localhost:5173",
          localStorage: [{ name: "access_token", value: players[1].token }],
        },
      ],
    },
  })
  const other = await context.newPage()
  try {
    const runs: RunPublic[] = []
    const pages = [page, other]
    for (let i = 0; i < 2; i++) {
      const p = pages[i]
      await p.goto("/daily")
      const overview = await (
        await p.request.get(`${api}/games/daily`, {
          headers: players[i].headers,
        })
      ).json()
      const options = await (
        await p.request.get(`${api}/games/options`, {
          headers: players[i].headers,
        })
      ).json()
      await expect(p.getByText(/^Fixed categories:/)).toHaveText(
        "Fixed categories: Battles, Exploration, Inventions, Politics",
      )
      expect(
        overview.category_ids.every((id: string) =>
          options.categories.some((c: { id: string }) => c.id === id),
        ),
      ).toBe(true)
      expect(overview.attempt_run_id).toBeNull()
      expect(new Date(overview.reset_at).toISOString()).toBe(
        `${new Date(new Date(`${overview.day}T00:00:00Z`).getTime() + 86400000).toISOString()}`,
      )
      await expect(
        p.getByText(`${overview.day} UTC`, { exact: true }),
      ).toBeVisible()
      await expect(p.getByText(/^Resets at /)).toContainText(
        `${overview.reset_at} (UTC)`,
      )
      const response = p.waitForResponse(
        (r) =>
          r.request().method() === "POST" && r.url().endsWith("/games/daily"),
      )
      await p.getByRole("button", { name: "Start Daily", exact: true }).click()
      const started = await response
      expect(started.ok()).toBeTruthy()
      runs.push(await started.json())
      await expect(
        p.getByText(`Daily · ${runs[i].daily_date} UTC`, { exact: true }),
      ).toBeVisible()
      await p.goto("/daily")
      await p.getByRole("link", { name: "Resume Daily", exact: true }).click()
      await expect(p.getByRole("heading", { name: "Next card" })).toBeVisible()
    }
    expect(runs[0].run_id).not.toBe(runs[1].run_id)
    expect(runs[0].timeline).toEqual(runs[1].timeline)
    expect(runs[0].pending).toEqual(runs[1].pending)
    expect(runs[0].config).toEqual(runs[1].config)
    expect(runs[0].catalog_release_id).toBe(runs[1].catalog_release_id)
    expect(runs[0].daily_date).toBe(runs[1].daily_date)
    expect(
      (
        await page.request.get(`${api}/games/runs/${runs[1].run_id}`, {
          headers: players[0].headers,
        })
      ).status(),
    ).toBe(404)
    // Real correct prefix and complete shared order, not blind first-move losses.
    while (runs[0].status === "active") {
      expect(runs[0].pending).toEqual(runs[1].pending)
      for (let i = 0; i < 2; i++)
        runs[i] = await lock(pages[i], runs[i], syntheticSlot(runs[i]))
      expect(runs[0].timeline).toEqual(runs[1].timeline)
      expect(runs[0].status).toBe(runs[1].status)
    }
    expect(runs[0].status).toBe("won")
    expect(runs[0].streak).toBe(5)
    expect(runs[0].timeline.map((card) => card.year.value)).toEqual([
      1800, 1810, 1820, 1830, 1870, 1880,
    ])
    for (let i = 0; i < 2; i++) {
      const p = pages[i]
      await expect(p.getByRole("region", { name: "Run result" })).toContainText(
        "cannot be replayed",
      )
      await p.goto("/daily")
      await expect(
        p.getByRole("button", { name: "Start Daily", exact: true }),
      ).toHaveCount(0)
      await expect(
        p.getByRole("link", { name: "View Result", exact: true }),
      ).toBeVisible()
      const replay = await p.request.post(`${api}/games/daily`, {
        headers: players[i].headers,
        data: { operation_id: crypto.randomUUID() },
      })
      expect(replay.ok()).toBeTruthy()
      expect((await replay.json()).run_id).toBe(runs[i].run_id)
      const completedMove = await p.request.post(
        `${api}/games/runs/${runs[i].run_id}/placements`,
        {
          headers: players[i].headers,
          data: {
            operation_id: crypto.randomUUID(),
            expected_revision: runs[i].revision,
            event_id: runs[i].timeline[0].event_id,
            slot: 0,
          },
        },
      )
      expect(completedMove.status()).toBe(409)
      expect((await completedMove.json()).detail.code).toBe("terminal_state")
      const board = await (
        await p.request.get(
          `${api}/games/daily/${runs[i].daily_date}/leaderboard`,
          { headers: players[i].headers },
        )
      ).json()
      const entries = players.map((player) =>
        board.entries.find(
          (entry: { display_name: string }) =>
            entry.display_name === player.name,
        ),
      )
      expect(entries[0].rank).toBe(entries[1].rank)
      expect(entries.map((entry) => entry.streak)).toEqual([5, 5])
      for (const entry of board.entries)
        expect(Object.keys(entry).sort()).toEqual([
          "display_name",
          "rank",
          "status",
          "streak",
        ])
      expect(JSON.stringify(board)).not.toContain(players[i].email)
      await expect(
        p.getByRole("heading", {
          name: `Leaderboard · ${runs[i].daily_date} UTC`,
        }),
      ).toBeVisible()
      for (const player of players) {
        const row = p.getByRole("row").filter({ hasText: player.name })
        await expect(row).toContainText("Won")
        await expect(row.getByRole("cell").first()).toHaveText(
          String(entries[0].rank),
        )
      }
    }
  } finally {
    await context.close()
  }
})

test("sparse_and_unavailable_catalog_never_show_loss", async ({
  page,
  players,
}) => {
  await configure(page, 9999)
  const before = await (
    await page.request.get(`${api}/games/active-runs`, {
      headers: players[0].headers,
    })
  ).json()
  const sparse = page.waitForResponse(
    (r) =>
      r.url().endsWith("/games/freeplay") && r.request().method() === "POST",
  )
  await page.getByRole("button", { name: "Start Freeplay" }).click()
  expect((await sparse).status()).toBe(422)
  await expect(page.getByRole("alert")).toBeVisible()
  expect(
    await (
      await page.request.get(`${api}/games/active-runs`, {
        headers: players[0].headers,
      })
    ).json(),
  ).toEqual(before)
  await expect(page.getByText("Status: lost", { exact: true })).toHaveCount(0)
  await page.route("**/api/v1/games/options", (route) =>
    route.fulfill({
      status: 503,
      json: {
        detail: {
          code: "catalog_unavailable",
          message: "Catalog temporarily unavailable",
        },
      },
    }),
  )
  await page.reload()
  await expect(page.getByRole("alert")).toContainText(
    "Catalog temporarily unavailable",
  )
  await expect(
    page.getByRole("button", { name: "Start Freeplay" }),
  ).toHaveCount(0)
  await expect(page.getByText("Status: lost", { exact: true })).toHaveCount(0)
})

async function renderedContrast(
  locator: Locator,
  property = "color",
  backgroundSelector = ".game-card",
) {
  return locator.evaluate(
    (e, { property, backgroundSelector }) => {
      const luminance = (color: string) => {
        const canvas = document.createElement("canvas")
        canvas.width = canvas.height = 1
        const context = canvas.getContext("2d")!
        context.fillStyle = color
        context.fillRect(0, 0, 1, 1)
        const c = Array.from(context.getImageData(0, 0, 1, 1).data)
          .slice(0, 3)
          .map((n) => n / 255)
          .map((n) => (n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4))
        return c[0] * 0.2126 + c[1] * 0.7152 + c[2] * 0.0722
      }
      const value = getComputedStyle(e).getPropertyValue(property)
      const a = luminance(
        property === "box-shadow" ? value.match(/rgba?\([^)]+\)/)![0] : value,
      )
      const b = luminance(
        getComputedStyle(e.closest(backgroundSelector)!).backgroundColor,
      )
      return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
    },
    { property, backgroundSelector },
  )
}

test("keyboard_focus_and_rendered_text_control_contrast", async ({
  page,
  players,
}, info) => {
  await configure(page)
  const run = await startFreeplay(page)
  const measurements: Record<string, number> = {}
  for (const theme of ["light", "dark"]) {
    await page.evaluate(
      (value) => localStorage.setItem("vite-ui-theme", value),
      theme,
    )
    await page.reload()
    const handle = page.getByRole("button", { name: "Drag next card" })
    await handle.focus()
    await page.keyboard.press("Tab")
    await page.keyboard.press("Shift+Tab")
    await expect(handle).toBeFocused()
    expect(await handle.evaluate((e) => e.matches(":focus-visible"))).toBe(true)
    expect(await handle.evaluate((e) => getComputedStyle(e).outlineStyle)).toBe(
      "solid",
    )
    // Focus indicator on its actual cream control must meet nontext contrast.
    // The adjacent control surface is cream, rather than transparent wrapper.
    measurements[`${theme}-focus-control`] = await renderedContrast(
      handle,
      "outline-color",
      ".drag-handle",
    )
    expect(measurements[`${theme}-focus-control`]).toBeGreaterThanOrEqual(3)
    measurements[`${theme}-focus-dark-table`] = await renderedContrast(
      handle,
      "box-shadow",
      ".play-layout",
    )
    expect(measurements[`${theme}-focus-dark-table`]).toBeGreaterThanOrEqual(3)
    expect(
      await handle.evaluate((e) =>
        Number.parseFloat(getComputedStyle(e).outlineWidth),
      ),
    ).toBeGreaterThanOrEqual(3)
    await handle.scrollIntoViewIfNeeded()
    await page.screenshot({
      path: `${evidence}/U4-focus-${theme}-${info.project.name}.png`,
    })
    for (const selector of [
      ".game-card-category",
      ".game-card h3",
      ".game-card-year",
      ".event-image-credits",
    ]) {
      const element = page.getByTestId("pending-card").locator(selector)
      measurements[`${theme}-${selector}`] = await renderedContrast(element)
      expect(measurements[`${theme}-${selector}`]).toBeGreaterThanOrEqual(4.5)
    }
    for (const name of [
      "First slot",
      "Last slot",
      "Previous slot",
      "Next slot",
    ]) {
      const control = page.getByRole("button", { name, exact: true })
      await control.focus()
      await expect(control).toBeFocused()
      await expect(control).toBeInViewport()
      expect(await control.evaluate((e) => e.matches(":focus-visible"))).toBe(
        true,
      )
      expect(
        await renderedContrast(control, "color", ".slot-shortcuts button"),
      ).toBeGreaterThanOrEqual(4.5)
    }
    await page.getByRole("button", { name: "First slot", exact: true }).click()
    const lockButton = page.getByRole("button", {
      name: "Lock it in",
      exact: true,
    })
    await lockButton.focus()
    measurements[`${theme}-lock-text`] = await renderedContrast(
      lockButton,
      "color",
      ".placement-actions button",
    )
    expect(measurements[`${theme}-lock-text`]).toBeGreaterThanOrEqual(4.5)
  }
  expect((await readRun(page, run.run_id, players[0])).revision).toBe(0)
  await mkdir(evidence, { recursive: true })
  await writeFile(
    `${evidence}/U4-contrast-${info.project.name}.json`,
    JSON.stringify(measurements, null, 2),
  )
})

test("bce_ce_settings_and_readonly_daily_labels_remain_readable", async ({
  page,
  players,
}, info) => {
  const measurements: Record<string, number> = {}
  for (const theme of ["light", "dark"]) {
    await page.evaluate(
      (value) => localStorage.setItem("vite-ui-theme", value),
      theme,
    )
    await configure(page)
    const form = page.locator("form")
    for (const label of await form.locator("label span").all()) {
      measurements[`${theme}-${await label.innerText()}`] =
        await renderedContrast(label, "color", "form")
      expect(
        measurements[`${theme}-${await label.innerText()}`],
      ).toBeGreaterThanOrEqual(4.5)
    }
    for (const hint of await form.locator("p.text-muted-foreground").all())
      expect(
        await renderedContrast(hint, "color", "form"),
      ).toBeGreaterThanOrEqual(4.5)
    await page
      .getByRole("combobox", { name: "Start era", exact: true })
      .selectOption("BCE")
    await page.getByLabel("Start year", { exact: true }).fill("1")
    await page
      .getByRole("combobox", { name: "End era", exact: true })
      .selectOption("BCE")
    await page.getByLabel("End year", { exact: true }).fill("50")
    await expect(page.getByRole("alert")).toContainText(
      "Start year must be at or before end year",
    )
    await page.getByLabel("End year", { exact: true }).fill("0")
    await expect(page.getByRole("alert")).toContainText("no civil year zero")
    await expect(
      page.getByRole("button", { name: "Start Freeplay" }),
    ).toBeDisabled()
    await page
      .getByRole("combobox", { name: "End era", exact: true })
      .selectOption("CE")
    await page.getByLabel("End year", { exact: true }).fill("1880")
    await expect(
      page.getByRole("button", { name: "Start Freeplay" }),
    ).toBeEnabled()
    await page.goto("/daily")
    const labels = page.getByText(/^Fixed categories:/)
    await expect(labels).toHaveText(
      "Fixed categories: Battles, Exploration, Inventions, Politics",
    )
    measurements[`${theme}-readonly-categories`] = await renderedContrast(
      labels,
      "color",
      "section",
    )
    expect(measurements[`${theme}-readonly-categories`]).toBeGreaterThanOrEqual(
      4.5,
    )
    expect(
      await renderedContrast(page.getByText(/^Resets at /), "color", "section"),
    ).toBeGreaterThanOrEqual(4.5)
  }
  await configure(page)
  await page
    .getByRole("combobox", { name: "Start era", exact: true })
    .selectOption("BCE")
  await page.getByLabel("Start year", { exact: true }).fill("1")
  const run = await startFreeplay(page)
  expect(run.config.start).toEqual({ value: 1, era: "BCE" })
  const won = await finishWin(page, run)
  await expect(page.getByRole("region", { name: "Run result" })).toContainText(
    "1 BCE–1880 CE",
  )
  expect(await readRun(page, run.run_id, players[0])).toEqual(won)
  await writeFile(
    `${evidence}/U4-settings-contrast-${info.project.name}.json`,
    JSON.stringify(measurements, null, 2),
  )
})

test("hundred_card_timeline_every_slot_accessible", async ({
  page,
  players,
  isMobile,
}, info) => {
  test.setTimeout(120_000)
  void players // owned authentication even for public layout fixtures
  await mkdir(evidence, { recursive: true })
  const run = hundredCardRun()
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.route(`**/games/runs/${run.run_id}`, (route) =>
    route.fulfill({ json: run }),
  )
  let release!: () => void
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route("**/u4-slow-primary.svg", async (route) => {
    await held
    await route.abort()
  })
  await page.route("**/u4-broken-fallback.svg", (route) => route.abort())
  const commands: unknown[] = []
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/placements"))
      commands.push(request.postDataJSON())
  })
  try {
    await page.goto(`/play/${run.run_id}`, { waitUntil: "domcontentloaded" })
    const slots = page.getByRole("button", { name: /^Slot \d+$/ })
    await expect(slots).toHaveCount(101)
    const first = slots.first()
    const geometry = () =>
      first.evaluate((e) => {
        const r = e.getBoundingClientRect()
        return [r.x + scrollX, r.y + scrollY, r.width, r.height]
      })
    const before = await geometry()
    release()
    await expect(
      page
        .getByTestId("pending-card")
        .getByRole("img", { name: /Image unavailable/ }),
    ).toBeVisible()
    expect(await geometry()).toEqual(before)
    const visited = []
    for (let i = 0; i <= 100; i++) {
      const slot = slots.nth(i)
      await slot.scrollIntoViewIfNeeded()
      await slot.focus()
      await page.keyboard.press("Enter")
      if (isMobile) await slot.tap()
      await expect(slot).toHaveAttribute("aria-pressed", "true")
      await expect(slot).toBeInViewport()
      const dimensions = await slot.evaluate((e) => {
        const r = e.getBoundingClientRect()
        const x = Math.max(0, Math.min(innerWidth - 1, r.x + r.width / 2))
        const y = Math.max(0, Math.min(innerHeight - 1, r.y + r.height / 2))
        return {
          width: r.width,
          height: r.height,
          unobscured: e.contains(document.elementFromPoint(x, y)),
        }
      })
      expect(dimensions.width).toBeGreaterThanOrEqual(44)
      expect(dimensions.height).toBeGreaterThanOrEqual(44)
      expect(dimensions.unobscured).toBe(true)
      visited.push({ slot: i + 1, ...dimensions })
      if ([0, 50, 100].includes(i))
        await page.screenshot({
          path: `${evidence}/U4-100-${i + 1}-${info.project.name}.png`,
        })
    }
    // Native keyboard drag through all 101 ordinal targets, including scroll.
    const handle = page.getByRole("button", { name: "Drag next card" })
    await handle.focus()
    await page.keyboard.press("Space")
    for (let i = 0; i <= 100; i++) {
      await page.keyboard.press("ArrowRight")
      // Stable dnd-kit 0.5.0 recomputes scroll collisions after 50ms. A keyboard
      // target must survive that settling, not just flash before it is cleared.
      await page.waitForTimeout(80)
      try {
        await expect(slots.nth(i)).toHaveClass(/insertion-slot-over/)
      } catch (error) {
        await writeFile(
          `${evidence}/U4-keyboard-failure-${info.project.name}.json`,
          JSON.stringify(
            await page.evaluate(
              (slot) => ({
                slot,
                active: document.activeElement?.outerHTML,
                dragging: document
                  .querySelector(".pending-draggable")
                  ?.getAttribute("data-dragging"),
                over: Array.from(
                  document.querySelectorAll(".insertion-slot-over"),
                ).map((e) => e.getAttribute("data-slot")),
                scroll: scrollY,
              }),
              i,
            ),
            null,
            2,
          ),
        )
        await page.screenshot({
          path: `${evidence}/U4-keyboard-failure-${info.project.name}.png`,
        })
        throw error
      }
      await expect(slots.nth(i)).toBeInViewport()
    }
    await page.keyboard.press("Space")
    await expect(handle).toBeFocused()
    await expect(slots.last()).toHaveAttribute("aria-pressed", "true")
    if (!isMobile) {
      const timeline = page.locator(".game-timeline")
      await timeline.evaluate((e) => {
        e.scrollLeft = 0
      })
      await handle.scrollIntoViewIfNeeded()
      const start = (await handle.boundingBox())!
      const table = (await timeline.boundingBox())!
      await page.mouse.move(
        start.x + start.width / 2,
        start.y + start.height / 2,
      )
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
    // A pointer/touch drag after the ordinal keyboard operation must still use
    // normal geometry: this catches collision detection not being restored.
    await page.locator(".game-timeline").evaluate((e) => {
      e.scrollLeft = 0
    })
    await handle.scrollIntoViewIfNeeded()
    const source = (await handle.boundingBox())!
    const a = {
      x: source.x + source.width / 2,
      y: source.y + source.height / 2,
    }
    if (isMobile) {
      const cdp = await page.context().newCDPSession(page)
      try {
        await cdp.send("Input.dispatchTouchEvent", {
          type: "touchStart",
          touchPoints: [a],
        })
        await page.waitForTimeout(300) // real hold-to-drag activation threshold
        const viewport = page.viewportSize()!
        await cdp.send("Input.dispatchTouchEvent", {
          type: "touchMove",
          touchPoints: [{ x: a.x, y: viewport.height - 24 }],
        })
        await expect
          .poll(async () => {
            const box = (await first.boundingBox())!
            return box.y >= 0 && box.y + box.height <= viewport.height
          })
          .toBe(true)
        const box = (await first.boundingBox())!
        await cdp.send("Input.dispatchTouchEvent", {
          type: "touchMove",
          touchPoints: [
            { x: box.x + box.width / 2, y: box.y + box.height / 2 },
          ],
        })
        await expect(first).toHaveClass(/insertion-slot-over/)
        await cdp.send("Input.dispatchTouchEvent", {
          type: "touchEnd",
          touchPoints: [],
        })
      } finally {
        await cdp.detach()
      }
    } else {
      const box = (await first.boundingBox())!
      await page.mouse.move(a.x, a.y)
      await page.mouse.down()
      await page.mouse.move(a.x + 12, a.y, { steps: 3 })
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, {
        steps: 12,
      })
      await expect(first).toHaveClass(/insertion-slot-over/)
      await page.mouse.up()
    }
    await expect(first).toHaveAttribute("aria-pressed", "true")
    for (const name of [
      "First slot",
      "Last slot",
      "Previous slot",
      "Next slot",
      "Lock it in",
      "Cancel preview",
    ]) {
      const control = page.getByRole("button", { name, exact: true })
      await control.scrollIntoViewIfNeeded()
      await expect(control).toBeInViewport()
      expect((await control.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    }
    await expect(page.getByTestId("pending-card")).toContainText("CC0 1.0")
    const credits = page
      .getByTestId("pending-card")
      .locator(".event-image-credits")
    const creditRect = (await credits.boundingBox())!
    const handleRect = (await handle.boundingBox())!
    expect(creditRect.y + creditRect.height).toBeLessThanOrEqual(handleRect.y)
    expect(
      await page.evaluate(() => document.body.scrollWidth <= innerWidth),
    ).toBe(true)
    await expect(
      page.locator(".game-card-year").filter({ hasText: /^0 / }),
    ).toHaveCount(0)
    expect(
      await page
        .locator(".game-card")
        .first()
        .evaluate((e) => getComputedStyle(e).transitionDuration),
    ).toBe("0s")
    expect(commands).toEqual([])
    await page.getByRole("button", { name: "First slot", exact: true }).click()
    if (!isMobile)
      await page.screenshot({
        path: `${evidence}/U4-100-full-${info.project.name}.png`,
        fullPage: true,
      })
    await writeFile(
      `${evidence}/U4-100-layout-${info.project.name}.json`,
      JSON.stringify(
        {
          browser: info.project.name,
          version: page.context().browser()?.version(),
          viewport: page.viewportSize(),
          emulation: isMobile,
          visited,
          commands,
        },
        null,
        2,
      ),
    )
  } finally {
    release()
  }
})
