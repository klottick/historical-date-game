import { randomUUID } from "node:crypto"
import { appendFile, writeFile } from "node:fs/promises"
import { test as base, devices, expect, type Page } from "@playwright/test"
import {
  realCatalogAPI as api,
  realCatalogUIOrigin,
} from "../playwright.real-catalog.config"
import type { RunPublic } from "../src/client/types.gen"
import { loadCatalog, slugs } from "./catalog"

const evidence =
  "../.superpowers/sdd/2026-10-13-historical-date-game-guest-play/task-5-evidence"
type Player = { token: string; headers: Record<string, string> }
const test = base.extend<{
  players: Player[]
  catalog: ReturnType<typeof loadCatalog>
}>({
  players: async ({ request, page }, use) => {
    const login = await request.post(`${api}/login/access-token`, {
      form: {
        username: process.env.FIRST_SUPERUSER!,
        password: process.env.FIRST_SUPERUSER_PASSWORD!,
      },
    })
    expect(login.ok()).toBeTruthy()
    const headers = {
      Authorization: `Bearer ${(await login.json()).access_token}`,
    }
    const players: Player[] = []
    for (let i = 0; i < 2; i++) {
      const email = `f2-journey-${randomUUID()}@example.com`
      const password = `${randomUUID()}Aa!`
      const created = await request.post(`${api}/users/`, {
        headers,
        data: { email, password, full_name: `F2 journey ${i + 1}` },
      })
      expect(created.ok()).toBeTruthy()
      const response = await request.post(`${api}/login/access-token`, {
        form: { username: email, password },
      })
      expect(response.ok()).toBeTruthy()
      const token = (await response.json()).access_token
      players.push({ token, headers: { Authorization: `Bearer ${token}` } })
      // Keep only scoped players, privately, for owner play/restart; no DB cleanup.
      await appendFile(
        "playwright/.auth/real-catalog-journey-players.jsonl",
        `${JSON.stringify({ email, password, token, id: (await created.json()).id })}\n`,
        { mode: 0o600 },
      )
    }
    await page.addInitScript(
      (token) => localStorage.setItem("access_token", token),
      players[0].token,
    )
    await use(players)
  },
  catalog: async ({ request, players }, use) => {
    const response = await request.get(`${api}/games/options`, {
      headers: players[0].headers,
    })
    expect(response.ok()).toBeTruthy()
    await use(loadCatalog((await response.json()).catalog_release_id))
  },
})

export function publicOnly(run: RunPublic) {
  if (run.pending) {
    expect(Object.keys(run.pending).sort()).toEqual([
      "category_ids",
      "event_id",
      "media",
      "prompt",
    ])
    expect(JSON.stringify(run.pending)).not.toMatch(
      /"(?:year|sources|explanation|seed|pool|snapshot_id|raw_date)"/,
    )
    expect(JSON.stringify(run.pending)).not.toMatch(
      /events\.jsonl|raw\.jsonl|manifest\.json|snapshot_id/,
    )
    const urls = run.pending.media.credits.map((c) => c.url).filter(Boolean)
    expect(
      urls.every((url) => !/(?:wikipedia|wikidata)\.org\//.test(url!)),
    ).toBe(true)
  }
  // Revealed source citations may include the legitimate upstream JSONL URL.
  expect(JSON.stringify(run)).not.toMatch(
    /"(?:seed|pool|pending_year|owner_id|unused_events|snapshot_id)"/,
  )
}

export function slot(run: RunPublic, years: Map<string, number>) {
  const answer = years.get(run.pending!.event_id)
  expect(answer, "pending ID belongs to verified real catalog").toBeDefined()
  return run.timeline.filter(
    (c) => (c.year.era === "CE" ? c.year.value : 1 - c.year.value) < answer!,
  ).length
}

async function readRun(
  page: Page,
  run: RunPublic,
  player: Player,
): Promise<RunPublic> {
  const response = await page.request.get(`${api}/games/runs/${run.run_id}`, {
    headers: player.headers,
  })
  expect(response.ok()).toBeTruthy()
  return response.json()
}

export async function lock(
  page: Page,
  run: RunPublic,
  index: number,
  mobile = false,
): Promise<RunPublic> {
  publicOnly(run)
  const pending = page.getByTestId("pending-card")
  await expect(pending.locator("img")).toBeVisible()
  await expect
    .poll(() =>
      pending
        .locator("img")
        .evaluate(
          (image: HTMLImageElement) => image.complete && image.naturalWidth > 0,
        ),
    )
    .toBe(true)
  await expect(pending).toContainText("Year hidden")
  await expect(pending.locator("details")).toHaveCount(0)
  await expect(
    pending.locator('a[href*="wikipedia.org/"],a[href*="wikidata.org/"]'),
  ).toHaveCount(0)
  const target = page.getByRole("button", {
    name: `Slot ${index + 1}`,
    exact: true,
  })
  if (mobile) await target.tap()
  else {
    await target.focus()
    await page.keyboard.press("Enter")
  }
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

async function configure(
  page: Page,
  small?: { start: number; end: number; gap: number },
) {
  await page.goto("/freeplay")
  await expect(
    page.getByRole("button", { name: "Start Freeplay", exact: true }),
  ).toBeEnabled()
  if (small) {
    await page
      .getByLabel("Start year", { exact: true })
      .fill(String(small.start))
    await page.getByLabel("End year", { exact: true }).fill(String(small.end))
    await page.getByLabel("Minimum year gap").fill(String(small.gap))
  }
}

async function start(page: Page): Promise<RunPublic> {
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
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${run.revision}`,
  )
  return run
}

test("actual release options, readable safe credits, asset HTTP and private artifacts", async ({
  page,
  players,
  catalog,
}, info) => {
  await configure(page)
  const options = await (
    await page.request.get(`${api}/games/options`, {
      headers: players[0].headers,
    })
  ).json()
  expect(options.catalog_release_id).toBe(catalog.manifest.release_id)
  expect(options.categories.map((c: { id: string }) => c.id).sort()).toEqual(
    [...slugs].sort(),
  )
  expect(options.start).toEqual({ value: 9, era: "CE" })
  expect(options.end).toEqual({ value: 2025, era: "CE" })
  expect(options.registration_open).toBe(false)
  expect(
    (
      await page.request.post(`${api}/users/signup`, {
        data: {
          email: `f2-blocked-${randomUUID()}@example.com`,
          password: `${randomUUID()}Aa!`,
          full_name: "Blocked",
        },
      })
    ).status(),
  ).toBe(403)
  for (const box of await page.getByRole("checkbox").all())
    await expect(box).toBeChecked()
  // The five Wikidata births have public-domain text, unlike the chronology.
  // Select chronology categories here to require its mandatory CC BY-SA credits.
  await page.getByRole("checkbox", { name: "Births", exact: true }).uncheck()
  const run = await start(page)
  publicOnly(run)
  const pending = page.getByTestId("pending-card")
  expect(run.pending!.media.credits.length).toBeGreaterThan(0)
  expect(run.pending!.media.credits).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        label: expect.stringMatching(
          /^Catalog text: adapted from Wikipedia contributors.*CC BY-SA 4\.0/,
        ),
        url: "https://github.com/mneedham/wikipedia-onthisday",
      }),
      {
        label: "Catalog text license: CC BY-SA 4.0",
        url: "https://creativecommons.org/licenses/by-sa/4.0/",
      },
    ]),
  )
  for (const credit of run.pending!.media.credits) {
    await expect(pending.locator(".event-image-credits")).toContainText(
      credit.label,
    )
    await expect(pending.locator(".event-image-credits")).toBeVisible()
    if (credit.url)
      await expect(
        pending.getByRole("link", { name: credit.label, exact: true }),
      ).toHaveAttribute("href", credit.url)
  }
  const assetChecks = []
  for (const [name, digest] of Object.entries(catalog.manifest.files) as [
    string,
    string,
  ][]) {
    if (!name.startsWith("media/")) continue
    const response = await page.request.get(
      `${new URL(api).origin}/media/${catalog.manifest.release_id}/${name.slice("media/".length)}`,
    )
    expect(response.status()).toBe(200)
    const { createHash } = await import("node:crypto")
    expect(
      createHash("sha256")
        .update(await response.body())
        .digest("hex"),
    ).toBe(digest)
    assetChecks.push({
      path: `media/${catalog.manifest.release_id}/${name.slice("media/".length)}`,
      status: response.status(),
    })
  }
  expect(assetChecks).toHaveLength(8)
  const frontendDenied = []
  for (const path of [
    "/playwright/.auth/real-catalog-players.json",
    "/playwright/.auth/real-catalog.json",
    "/playwright/.auth/real-catalog-restart-players.json?raw",
    `/@fs${process.cwd()}/playwright/.auth/real-catalog-players.json`,
    "/tests-real-catalog/catalog.ts?raw",
    `/@fs${process.env.REAL_CATALOG_RELEASE_DIR}/events.jsonl`,
    `/@fs${process.env.REAL_CATALOG_RELEASE_DIR}/manifest.json`,
  ]) {
    const response = await page.request.get(`${realCatalogUIOrigin}${path}`)
    expect([403, 404]).toContain(response.status())
    frontendDenied.push({ path, status: response.status() })
  }
  const denied = []
  for (const path of [
    "/media/",
    "/manifest.json",
    "/events.jsonl",
    "/raw.jsonl",
    "/snapshots/",
    "/receipts/",
    "/media/manifest.json",
    "/media/events.jsonl",
    "/media/raw.jsonl",
    "/media/snapshots/",
    "/media/receipts/",
    ...Object.keys(catalog.manifest.files)
      .filter((name) => name.startsWith("media/"))
      .map((name) => `/${name}`),
    ...[
      "manifest.json",
      "events.jsonl",
      "raw.jsonl",
      "snapshots/source.json",
      "receipts/acquisition.json",
      "",
    ].map((name) => `/media/${catalog.manifest.release_id}/${name}`),
    `/data/game/releases/${catalog.manifest.release_id}/manifest.json`,
  ]) {
    const response = await page.request.get(`${new URL(api).origin}${path}`)
    expect([403, 404]).toContain(response.status())
    denied.push({ path, status: response.status() })
  }
  await page.route("**/media/**/*.svg", (route) => route.abort())
  await page.reload()
  await expect(
    pending.getByRole("img", { name: /Image unavailable/ }),
  ).toBeVisible()
  for (const credit of run.pending!.media.credits)
    await expect(pending).toContainText(credit.label)
  expect(await readRun(page, run, players[0])).toEqual(run)
  await writeFile(
    `${evidence}/privacy-${info.project.name}.json`,
    JSON.stringify(
      {
        options,
        eventCount: catalog.manifest.event_count,
        assetChecks,
        frontendDenied,
        denied,
      },
      null,
      2,
    ),
    { mode: 0o600 },
  )
  await page.screenshot({
    path: `${evidence}/failed-media-${info.project.name}.png`,
    fullPage: true,
  })
})

test("genuine two-year range and pairwise gap win with keyboard drop preview", async ({
  page,
  players,
  catalog,
  isMobile,
}, info) => {
  await configure(page, catalog.small)
  let run = await start(page)
  const commands: unknown[] = []
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/placements"))
      commands.push(r.postDataJSON())
  })
  const handle = page.getByRole("button", { name: "Drag next card" })
  await handle.focus()
  await page.keyboard.press("Space")
  await page.keyboard.press("ArrowRight")
  await expect(
    page.getByRole("button", { name: "Slot 1", exact: true }),
  ).toHaveClass(/insertion-slot-over/)
  await page.keyboard.press("Space")
  await expect(
    page.getByRole("button", { name: "Slot 1", exact: true }),
  ).toHaveAttribute("aria-pressed", "true")
  expect(commands).toEqual([])
  expect(await readRun(page, run, players[0])).toEqual(run)
  run = await lock(page, run, slot(run, catalog.years), isMobile)
  expect(run.status).toBe("won")
  expect(run.pending).toBeNull()
  expect(run.streak).toBe(1)
  expect(run.timeline.map((c) => c.year.value)).toEqual([
    catalog.small.start,
    catalog.small.end,
  ])
  expect(
    run.timeline[1].year.value - run.timeline[0].year.value,
  ).toBeGreaterThanOrEqual(catalog.small.gap)
  await expect(
    page.getByRole("heading", { name: "Victory — catalog exhausted" }),
  ).toBeVisible()
  await expect(page.getByRole("region", { name: "Run result" })).toContainText(
    `${catalog.small.start} CE–${catalog.small.end} CE, minimum gap ${catalog.small.gap}`,
  )
  await expect(page.getByRole("region", { name: "Run result" })).toContainText(
    catalog.manifest.release_id,
  )
  const revealed = page
    .locator(".game-card-revealed")
    .filter({ hasText: run.feedback!.card.prompt })
  await revealed.getByText("Event details & sources", { exact: true }).click()
  await expect(revealed).toContainText(run.feedback!.card.explanation)
  for (const source of run.feedback!.card.sources)
    await expect(
      revealed.getByRole("link", { name: source.label, exact: true }),
    ).toHaveAttribute("href", source.url)
  await page.reload()
  expect(await readRun(page, run, players[0])).toEqual(run)
  await expect(
    page.getByRole("button", { name: "Lock it in", exact: true }),
  ).toHaveCount(0)
  await page.screenshot({
    path: `${evidence}/real-win-${info.project.name}.png`,
    fullPage: true,
  })
})

test("broad freeplay correct, exact idempotency, reload resume, loss and new run", async ({
  page,
  players,
  catalog,
  isMobile,
}) => {
  await configure(page)
  let run = await start(page)
  expect(run.config.start).toEqual({ value: 9, era: "CE" })
  expect(run.config.end).toEqual({ value: 2025, era: "CE" })
  expect(run.config.min_gap).toBe(1)
  expect([...run.config.category_ids].sort()).toEqual([...slugs].sort())
  let command: unknown
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/placements"))
      command = r.postDataJSON()
  })
  run = await lock(page, run, slot(run, catalog.years), isMobile)
  expect(run.feedback!.correct).toBe(true)
  expect(run.status).toBe("active")
  const retry = await page.request.post(
    `${api}/games/runs/${run.run_id}/placements`,
    { headers: players[0].headers, data: command },
  )
  expect(retry.ok()).toBeTruthy()
  expect(await retry.json()).toEqual(run)
  await page.reload()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${run.revision}`,
  )
  expect(await readRun(page, run, players[0])).toEqual(run)
  await page.getByRole("link", { name: "Back to Home", exact: true }).click()
  await page
    .getByRole("link", {
      name: new RegExp(`Resume Freeplay.*${run.run_id.slice(0, 8)}`),
    })
    .click()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${run.revision}`,
  )
  run = await lock(page, run, slot(run, catalog.years) === 0 ? 1 : 0, isMobile)
  expect(run.status).toBe("lost")
  expect(run.streak).toBe(1)
  await expect(
    page.getByRole("heading", { name: "Mistake — run complete" }),
  ).toBeVisible()
  await page.reload()
  expect(await readRun(page, run, players[0])).toEqual(run)
  await page.getByRole("link", { name: "New Freeplay", exact: true }).click()
  const next = await start(page)
  expect(next.run_id).not.toBe(run.run_id)
  expect(next.revision).toBe(0)
})

test("uncertain real committed response retries same operation without double scoring", async ({
  page,
  players,
  catalog,
  isMobile,
}, info) => {
  await configure(page)
  const run = await start(page)
  const commands: unknown[] = []
  let committed: RunPublic | undefined
  await page.route("**/placements", async (route) => {
    commands.push(route.request().postDataJSON())
    const response = await route.fetch()
    expect(response.ok()).toBeTruthy()
    if (commands.length === 1) {
      committed = await response.json()
      await route.abort("failed")
    } else await route.fulfill({ response })
  })
  const target = page.getByRole("button", {
    name: `Slot ${slot(run, catalog.years) + 1}`,
    exact: true,
  })
  if (isMobile) await target.tap()
  else await target.click()
  await page.getByRole("button", { name: "Lock it in", exact: true }).click()
  await expect(page.getByRole("alert")).toContainText("your run is not lost")
  expect(committed!.revision).toBe(run.revision + 1)
  expect(committed!.status).toBe("active")
  await page
    .getByRole("button", { name: "Retry same move", exact: true })
    .click()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${committed!.revision}`,
  )
  expect(commands).toHaveLength(2)
  expect(commands[1]).toEqual(commands[0])
  expect(await readRun(page, run, players[0])).toEqual(committed)
  await page.reload()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${committed!.revision}`,
  )
  await writeFile(
    `${evidence}/uncertain-${info.project.name}.json`,
    JSON.stringify({ commands, committed }, null, 2),
    { mode: 0o600 },
  )
})

test("two fresh Daily players share real correct prefix, one attempt and owned reads", async ({
  page,
  browser,
  players,
  catalog,
  isMobile,
}, info) => {
  const context = await browser.newContext({
    ...devices[isMobile ? "Pixel 5" : "Desktop Chrome"],
    baseURL: realCatalogUIOrigin,
    storageState: {
      cookies: [],
      origins: [
        {
          origin: realCatalogUIOrigin,
          localStorage: [{ name: "access_token", value: players[1].token }],
        },
      ],
    },
  })
  try {
    const other = await context.newPage()
    const pages = [page, other]
    const runs: RunPublic[] = []
    for (let i = 0; i < 2; i++) {
      await pages[i].goto("/daily")
      await expect(pages[i].getByText(/^Fixed categories:/)).toHaveText(
        "Fixed categories: Battles, Exploration, Inventions, Politics",
      )
      await expect(pages[i].getByRole("checkbox")).toHaveCount(0)
      const overview = await (
        await page.request.get(`${api}/games/daily`, {
          headers: players[i].headers,
        })
      ).json()
      expect(overview.attempt_run_id).toBeNull()
      const response = pages[i].waitForResponse(
        (r) =>
          r.request().method() === "POST" && r.url().endsWith("/games/daily"),
      )
      await pages[i]
        .getByRole("button", { name: "Start Daily", exact: true })
        .click()
      expect((await response).ok()).toBeTruthy()
      runs.push(await (await response).json())
      await expect(pages[i].getByTestId("run-revision")).toHaveText(
        "Revision: 0",
      )
    }
    expect(runs[0].run_id).not.toBe(runs[1].run_id)
    expect(runs[0].timeline).toEqual(runs[1].timeline)
    expect(runs[0].pending).toEqual(runs[1].pending)
    expect(runs[0].config).toEqual(runs[1].config)
    expect([...runs[0].config.category_ids].sort()).toEqual([
      "battles",
      "exploration",
      "inventions",
      "politics",
    ])
    expect(runs[0].daily_date).toBe(runs[1].daily_date)
    expect(runs[0].catalog_release_id).toBe(catalog.manifest.release_id)
    expect(
      (
        await page.request.get(`${api}/games/runs/${runs[1].run_id}`, {
          headers: players[0].headers,
        })
      ).status(),
    ).toBe(404)
    for (let round = 0; round < 3; round++) {
      expect(runs[0].pending).toEqual(runs[1].pending)
      for (let i = 0; i < 2; i++) {
        runs[i] = await lock(
          pages[i],
          runs[i],
          slot(runs[i], catalog.years),
          isMobile,
        )
        expect(runs[i].feedback!.correct).toBe(true)
        expect(runs[i].status).toBe("active")
      }
      expect(runs[0].timeline).toEqual(runs[1].timeline)
    }
    for (let i = 0; i < 2; i++) {
      const repeat = await page.request.post(`${api}/games/daily`, {
        headers: players[i].headers,
        data: { operation_id: randomUUID() },
      })
      expect(repeat.ok()).toBeTruthy()
      expect(await repeat.json()).toEqual(runs[i])
      await pages[i].reload()
      expect(await readRun(pages[i], runs[i], players[i])).toEqual(runs[i])
      await pages[i].goto("/daily")
      await expect(
        pages[i].getByRole("button", { name: "Start Daily", exact: true }),
      ).toHaveCount(0)
      await pages[i]
        .getByRole("link", { name: "Resume Daily", exact: true })
        .click()
      await expect(pages[i].getByTestId("run-revision")).toHaveText(
        "Revision: 3",
      )
    }
    await writeFile(
      `${evidence}/daily-${info.project.name}.json`,
      JSON.stringify({ runs, emulation: isMobile }, null, 2),
      { mode: 0o600 },
    )
    await page.screenshot({
      path: `${evidence}/daily-${info.project.name}.png`,
      fullPage: true,
    })
  } finally {
    await context.close()
  }
})
