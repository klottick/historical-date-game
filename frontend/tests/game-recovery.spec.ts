import { test as base, expect, type Page } from "@playwright/test"
import type { PlaceCommand, RunPublic } from "../src/client/types.gen"

import { fixtureAPI as api } from "./utils/apiOrigin"
import { keyboardPreview } from "./utils/boardInteraction"
import { readGameOptions } from "./utils/gameOptions"

const test = base.extend<{
  player: {
    email: string
    password: string
    headers: Record<string, string>
    adminToken: string
  }
  run: RunPublic
}>({
  player: async ({ page }, use) => {
    await page.goto("/")
    const admin = await page.evaluate(() =>
      localStorage.getItem("access_token"),
    )
    const email = `recovery-${crypto.randomUUID()}@example.com`
    const password = "GameBrowser123!"
    const created = await page.request.post(`${api}/users/`, {
      headers: { Authorization: `Bearer ${admin}` },
      data: { email, password, full_name: "Recovery player" },
    })
    expect(created.ok()).toBeTruthy()
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
      await use({ email, password, headers, adminToken: admin! })
    } finally {
      expect(
        (await page.request.delete(`${api}/users/me`, { headers })).ok(),
      ).toBeTruthy()
    }
  },
  run: async ({ page, player }, use) => {
    const options = await readGameOptions(
      await page.request.get(`${api}/games/options`, {
        headers: player.headers,
      }),
    )
    const response = await page.request.post(`${api}/games/freeplay`, {
      headers: player.headers,
      data: {
        operation_id: crypto.randomUUID(),
        catalog_release_id: options.catalog_release_id,
        config: {
          category_ids: options.categories.map(
            (category: { id: string }) => category.id,
          ),
          start: options.start,
          end: options.end,
          min_gap: 1,
        },
      },
    })
    expect(response.ok()).toBeTruthy()
    await use(await response.json())
  },
})
const runURL = (run: RunPublic) => `${api}/games/runs/${run.run_id}`
async function openRun(page: Page, run: RunPublic) {
  await page.goto(`/play/${run.run_id}`)
  await expect(page.getByRole("heading", { name: "Next card" })).toBeVisible()
}

test("run ownership prevents another account from reading a pending card", async ({
  page,
  player,
  run,
}) => {
  const denied = await page.request.get(runURL(run), {
    headers: { Authorization: `Bearer ${player.adminToken}` },
  })
  expect(denied.status()).toBe(404)
  await page.evaluate(
    (token) => localStorage.setItem("access_token", token),
    player.adminToken,
  )
  await page.goto(`/play/${run.run_id}`)
  await expect(
    page.getByRole("heading", { name: "Run unavailable" }),
  ).toBeVisible()
  await expect(page.getByTestId("pending-card")).toHaveCount(0)
  await expect(
    page.getByText(run.pending!.prompt, { exact: true }),
  ).toHaveCount(0)
})

test("committed_move_response_lost_then_retry", async ({
  page,
  player,
  run,
}, testInfo) => {
  await openRun(page, run)
  const commands: PlaceCommand[] = []
  let committed: RunPublic | undefined
  await page.route(`**/games/runs/${run.run_id}/placements`, async (route) => {
    commands.push(route.request().postDataJSON())
    if (commands.length === 1) {
      const response = await route.fetch()
      expect(response.ok()).toBeTruthy()
      committed = await response.json()
      const read = await page.request.get(runURL(run), {
        headers: player.headers,
      })
      expect((await read.json()).revision).toBe(run.revision + 1)
      await route.abort("timedout") // Only lose the response AFTER verified commit.
    } else await route.continue()
  })
  await keyboardPreview(page, 0)
  await page.getByRole("button", { name: "Lock it in", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Retry same move" }),
  ).toBeVisible()
  await expect(page.getByTestId("pending-card")).toContainText(
    run.pending!.prompt,
  )
  await expect(
    page.getByText(`Streak: ${run.streak}`, { exact: true }),
  ).toBeVisible()
  await page.getByRole("button", { name: "Retry same move" }).click()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${run.revision + 1}`,
  )
  expect(commands).toHaveLength(2)
  expect(commands[1]).toEqual(commands[0])
  const after = await (
    await page.request.get(runURL(run), { headers: player.headers })
  ).json()
  expect(after).toEqual(committed)
  await testInfo.attach("committed-response-evidence", {
    body: JSON.stringify({
      before_revision: run.revision,
      committed_revision: committed!.revision,
      after_revision: after.revision,
      commands,
      status: after.status,
    }),
    contentType: "application/json",
  })
  console.info(
    `U2 committed response proof: before=${run.revision}, committed=${committed!.revision}, after=${after.revision}, streak_before=${run.streak}, streak_committed=${committed!.streak}, streak_after=${after.streak}, operation=${commands[0].operation_id}, identical_retry=${JSON.stringify(commands[0]) === JSON.stringify(commands[1])}, status=${after.status}`,
  )
})

for (const committed of [false, true]) {
  test(`route re-entry waits for fresh progress before ${committed ? "clearing a committed" : "restoring an uncertain"} command`, async ({
    page,
    player,
    run,
  }, testInfo) => {
    // Reach the second round through an actual successful browser POST. Blind
    // guesses can lose; new owned runs avoid an answer map or private fixtures.
    let initial = run
    let advanced: RunPublic | undefined
    for (let attempt = 0; attempt < 20; attempt++) {
      await openRun(page, initial)
      const response = page.waitForResponse(
        (value) => value.url() === `${runURL(initial)}/placements`,
      )
      await keyboardPreview(page, 0)
      await page
        .getByRole("button", { name: "Lock it in", exact: true })
        .click()
      const result: RunPublic = await (await response).json()
      await expect(page.getByTestId("run-revision")).toHaveText("Revision: 1")
      if (result.status === "active") {
        advanced = result
        break
      }
      const started = await page.request.post(`${api}/games/freeplay`, {
        headers: player.headers,
        data: {
          operation_id: crypto.randomUUID(),
          catalog_release_id: initial.catalog_release_id,
          config: initial.config,
        },
      })
      expect(started.ok()).toBeTruthy()
      initial = await started.json()
    }
    expect(
      advanced,
      "A successful blind move is required to reproduce cross-round cache hydration",
    ).toBeDefined()
    const round = advanced!
    const session = await (
      await page.request.get(`${api}/games/session`, {
        headers: player.headers,
      })
    ).json()
    const storageKey = `game:${encodeURIComponent(session.context_id)}:placement:${encodeURIComponent(round.run_id)}`
    const commands: PlaceCommand[] = []
    await page.route(
      `**/games/runs/${round.run_id}/placements`,
      async (route) => {
        commands.push(route.request().postDataJSON())
        if (commands.length === 1) {
          if (committed) expect((await route.fetch()).ok()).toBeTruthy()
          await route.abort("timedout")
        } else await route.continue()
      },
    )
    await keyboardPreview(page, 0)
    await page.getByRole("button", { name: "Lock it in", exact: true }).click()
    await expect(
      page.getByRole("button", { name: "Retry same move" }),
    ).toBeVisible()
    const saved = commands[0]
    expect(saved.expected_revision).toBe(1)
    expect(saved.event_id).toBe(round.pending!.event_id)
    expect(
      await page.evaluate(
        (key) => JSON.parse(sessionStorage.getItem(key)!),
        storageKey,
      ),
    ).toEqual(saved)

    let release!: () => void
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    let captured!: () => void
    const ready = new Promise<void>((resolve) => {
      captured = resolve
    })
    let fresh: RunPublic | undefined
    await page.route(`**/games/runs/${round.run_id}`, async (route) => {
      const response = await route.fetch()
      fresh = await response.json()
      captured()
      await held
      await route.fulfill({ response })
    })
    try {
      // SPA navigation preserves QueryClient's previous cached GET, unlike reload.
      await page
        .getByRole("link", { name: "Back to Home", exact: true })
        .click()
      await expect(
        page.getByRole("heading", {
          name: "Historical Date Game",
          exact: true,
        }),
      ).toBeVisible()
      await page.goBack()
      await ready
      expect(fresh!.revision).toBe(committed ? 2 : 1)
      expect(
        await page.evaluate(
          (key) => JSON.parse(sessionStorage.getItem(key)!),
          storageKey,
        ),
      ).toEqual(saved)
      await expect(
        page.getByRole("heading", { name: "Loading run…" }),
      ).toBeVisible()
      await expect(page.getByTestId("pending-card")).toHaveCount(0)
      await expect(
        page.getByRole("button", { name: "Lock it in", exact: true }),
      ).toHaveCount(0)
      expect(commands).toHaveLength(1)
      const read = page.waitForResponse(
        (response) =>
          response.url() === runURL(round) &&
          response.request().method() === "GET",
      )
      release()
      await read
      await expect(page.getByTestId("run-revision")).toHaveText(
        `Revision: ${fresh!.revision}`,
      )
      if (!committed) {
        await expect(
          page.getByRole("button", { name: "Retry same move" }),
        ).toBeVisible()
        await expect(page.getByTestId("pending-card")).toContainText(
          round.pending!.prompt,
        )
        await expect(
          page.getByRole("button", { name: "Lock it in", exact: true }),
        ).toBeDisabled()
        expect(
          await page.evaluate(
            (key) => JSON.parse(sessionStorage.getItem(key)!),
            storageKey,
          ),
        ).toEqual(saved)
        await page.getByRole("button", { name: "Retry same move" }).click()
        await expect(page.getByTestId("run-revision")).toHaveText("Revision: 2")
        expect(commands).toHaveLength(2)
        expect(commands[1]).toEqual(saved)
      } else {
        expect(
          await page.evaluate((key) => sessionStorage.getItem(key), storageKey),
        ).toBeNull()
        await expect(
          page.getByRole("button", { name: "Retry same move" }),
        ).toHaveCount(0)
        expect(commands).toHaveLength(1)
        if (fresh!.pending)
          await expect(page.getByTestId("pending-card")).toContainText(
            fresh!.pending.prompt,
          )
        else await expect(page.getByTestId("pending-card")).toHaveCount(0)
      }
      const after: RunPublic = await (
        await page.request.get(runURL(round), { headers: player.headers })
      ).json()
      expect(after.revision).toBe(2)
      if (committed) expect(after).toEqual(fresh)
      console.info(
        `U2-I1 remount proof: command_revision=1, held_GET_revision=${fresh!.revision}, preserved_while_held=true, after_revision=${after.revision}, operation=${saved.operation_id}, exact_retry=${!committed}, newer_cleared=${committed}`,
      )
      await testInfo.attach("remount-recovery-proof", {
        body: JSON.stringify({
          held_revision: fresh!.revision,
          commands,
          after_revision: after.revision,
        }),
        contentType: "application/json",
      })
    } finally {
      release()
    }
  })
}

test("equal revision focus and reconnect preserve an uncertain command", async ({
  page,
  player,
  run,
}) => {
  await openRun(page, run)
  const commands: PlaceCommand[] = []
  await page.route(`**/games/runs/${run.run_id}/placements`, async (route) => {
    commands.push(route.request().postDataJSON())
    if (commands.length === 1) await route.abort("timedout")
    else await route.continue()
  })
  await keyboardPreview(page, 0)
  await page.getByRole("button", { name: "Lock it in", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Retry same move" }),
  ).toBeVisible()
  for (const event of ["visibilitychange", "online"]) {
    const read = page.waitForResponse(
      (response) =>
        response.url() === runURL(run) && response.request().method() === "GET",
    )
    await page.evaluate((type) => {
      if (type === "online") window.dispatchEvent(new Event("offline"))
      window.dispatchEvent(new Event(type))
    }, event)
    await read
    await expect(
      page.getByRole("button", { name: "Retry same move" }),
    ).toBeVisible()
    await expect(page.locator(".pending-draggable")).toHaveAttribute(
      "aria-disabled",
      "true",
    )
  }
  await page.reload()
  await expect(
    page.getByRole("button", { name: "Retry same move" }),
  ).toBeVisible()
  await page.getByRole("button", { name: "Retry same move" }).click()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${run.revision + 1}`,
  )
  expect(commands[1]).toEqual(commands[0])
  expect(
    (
      await (
        await page.request.get(runURL(run), { headers: player.headers })
      ).json()
    ).revision,
  ).toBe(run.revision + 1)
})

test("validation and service failure are not historical losses", async ({
  page,
  player,
  run,
}) => {
  await openRun(page, run)
  let status = 422
  await page.route(`**/games/runs/${run.run_id}/placements`, (route) =>
    route.fulfill({
      status,
      json: {
        detail: { code: "test_failure", message: "Rejected test placement" },
      },
    }),
  )
  await keyboardPreview(page, 0)
  await page.getByRole("button", { name: "Lock it in", exact: true }).click()
  await expect(page.getByRole("alert")).toContainText("Invalid placement")
  await expect(
    page.getByRole("button", { name: "Lock it in", exact: true }),
  ).toBeEnabled()
  await expect(page.locator("[data-preview-slot]")).toHaveAttribute(
    "data-preview-slot",
    "0",
  )
  status = 503
  await page.getByRole("button", { name: "Lock it in", exact: true }).click()
  await expect(page.getByRole("alert")).toContainText(
    "Game service unavailable",
  )
  await expect(
    page.getByRole("button", { name: "Retry same move" }),
  ).toBeVisible()
  expect(
    (
      await (
        await page.request.get(runURL(run), { headers: player.headers })
      ).json()
    ).revision,
  ).toBe(run.revision)
  await page.getByRole("button", { name: "Check server progress" }).click()
  await expect(
    page.getByRole("button", { name: "Lock it in", exact: true }),
  ).toBeEnabled()
  await expect(
    page.getByTestId("pending-card").locator(".game-card"),
  ).toHaveAttribute("data-event-id", run.pending!.event_id)
  await expect(page.locator("[data-preview-slot]")).toHaveAttribute(
    "data-preview-slot",
    "0",
  )
})

test("delayed authoritative read cannot roll back a committed move", async ({
  page,
  player,
  run,
}) => {
  await openRun(page, run)
  let release!: () => void
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  let captured!: () => void
  const ready = new Promise<void>((resolve) => {
    captured = resolve
  })
  await page.route(`**/games/runs/${run.run_id}`, async (route) => {
    const response = await route.fetch()
    expect((await response.json()).revision).toBe(run.revision)
    captured()
    await held
    await route.fulfill({ response })
  })
  await page.evaluate(() => window.dispatchEvent(new Event("visibilitychange")))
  await ready
  try {
    await keyboardPreview(page, 0)
    await page.getByRole("button", { name: "Lock it in", exact: true }).click()
    await expect(page.getByTestId("run-revision")).toHaveText(
      `Revision: ${run.revision + 1}`,
    )
    const read = page.waitForResponse(
      (response) =>
        response.url() === runURL(run) && response.request().method() === "GET",
    )
    release()
    await read
    await expect(page.getByTestId("run-revision")).toHaveText(
      `Revision: ${run.revision + 1}`,
    )
    expect(
      (
        await (
          await page.request.get(runURL(run), { headers: player.headers })
        ).json()
      ).revision,
    ).toBe(run.revision + 1)
  } finally {
    release()
  }
})

test("placement authentication renewal keeps the exact recoverable command", async ({
  page,
  player,
  run,
}) => {
  await openRun(page, run)
  const commands: PlaceCommand[] = []
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/placements"))
      commands.push(request.postDataJSON())
  })
  await keyboardPreview(page, 0)
  // Expire authorization at the server boundary, without pretending that a
  // bearer replacement is the same identity. Retain the original exact move.
  await page.route(`**/games/runs/${run.run_id}/placements`, async (route) => {
    if (commands.length === 1)
      await route.fulfill({
        status: 403,
        json: { detail: "Could not validate credentials" },
      })
    else await route.continue()
  })
  await page.getByRole("button", { name: "Lock it in", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Retry session", exact: true }),
  ).toBeVisible()
  await page.getByRole("link", { name: "Sign in", exact: true }).click()
  await expect(page).toHaveURL(/\/login/)
  await page.getByTestId("email-input").fill(player.email)
  await page.getByTestId("password-input").fill(player.password)
  await page.getByRole("button", { name: "Log In", exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/play/${run.run_id}$`))
  await expect(
    page.getByRole("button", { name: "Retry same move" }),
  ).toBeVisible()
  await page.getByRole("button", { name: "Retry same move" }).click()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${run.revision + 1}`,
  )
  expect(commands).toHaveLength(2)
  expect(commands[1]).toEqual(commands[0])
})

test("public won DTO displays exhaustion rather than mistake and Daily has no replay", async ({
  page,
  run,
}) => {
  // Layout-only fixture: all data comes from a public DTO, with no answer map.
  const won: RunPublic = {
    ...run,
    mode: "daily",
    daily_date: "2026-10-12",
    status: "won",
    pending: null,
    feedback: null,
    streak: 7,
    revision: 8,
  }
  await page.route(`**/games/runs/${run.run_id}`, (route) =>
    route.fulfill({ json: won }),
  )
  await page.route("**/games/daily/2026-10-12/leaderboard", (route) =>
    route.fulfill({ json: { day: "2026-10-12", entries: [] } }),
  )
  await page.goto(`/play/${run.run_id}`)
  await expect(
    page.getByRole("heading", { name: "Victory — catalog exhausted" }),
  ).toBeVisible()
  await expect(page.getByText(/No eligible unused event remains/)).toBeVisible()
  const details = page.getByRole("button", {
    name: "Run details & leaderboard",
    exact: true,
  })
  await details.click()
  await expect(page.getByRole("dialog")).toContainText(run.catalog_release_id)
  await page.keyboard.press("Escape")
  await expect(details).toBeFocused()
  await expect(page.getByText("Final streak: 7", { exact: true })).toBeVisible()
  await expect(page.getByText(/cannot be replayed/)).toBeVisible()
  await expect(
    page.getByRole("button", {
      name: /Lock it in|Start Daily|Retry same move/,
    }),
  ).toHaveCount(0)
  await expect(page.getByRole("link", { name: "New Freeplay" })).toHaveCount(0)
})

test("two_tabs_one_authoritative_move", async ({
  page,
  context,
  player,
  run,
}) => {
  await openRun(page, run)
  const second = await context.newPage()
  try {
    await openRun(second, run)
    await keyboardPreview(page, 0)
    await keyboardPreview(second, 0)
    await page.getByRole("button", { name: "Lock it in", exact: true }).click()
    await expect(page.getByTestId("run-revision")).toHaveText(
      `Revision: ${run.revision + 1}`,
    )
    const response = second.waitForResponse((value) =>
      value.url().endsWith("/placements"),
    )
    await second
      .getByRole("button", { name: "Lock it in", exact: true })
      .click()
    expect((await response).status()).toBe(409)
    await expect(second.getByTestId("run-revision")).toHaveText(
      `Revision: ${run.revision + 1}`,
    )
    expect(
      (
        await (
          await page.request.get(runURL(run), { headers: player.headers })
        ).json()
      ).revision,
    ).toBe(run.revision + 1)
  } finally {
    await second.close()
  }
})

test("reload_and_login_renewal_preserve_progress", async ({
  page,
  player,
  run,
}) => {
  await openRun(page, run)
  await keyboardPreview(page, 0)
  await page.getByRole("button", { name: "Lock it in", exact: true }).click()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${run.revision + 1}`,
  )
  await page.reload()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${run.revision + 1}`,
  )
  await page.evaluate(() =>
    localStorage.setItem("access_token", "expired-token"),
  )
  await page.reload()
  await expect(
    page.getByRole("button", { name: "Retry session", exact: true }),
  ).toBeVisible()
  await page.getByRole("link", { name: "Sign in", exact: true }).click()
  await expect(page).toHaveURL(/\/login/)
  await page.getByTestId("email-input").fill(player.email)
  await page.getByTestId("password-input").fill(player.password)
  await page.getByRole("button", { name: "Log In", exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/play/${run.run_id}$`))
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${run.revision + 1}`,
  )
  expect(
    (
      await (
        await page.request.get(runURL(run), { headers: player.headers })
      ).json()
    ).revision,
  ).toBe(run.revision + 1)
})

test("preview sends no move and feedback instructions work on active cards and results", async ({
  page,
  player,
  run,
}) => {
  await openRun(page, run)
  const posts: string[] = []
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/placements"))
      posts.push(request.url())
  })
  await expect(page.locator(".timeline-item")).toHaveCount(run.timeline.length)
  await keyboardPreview(page, 0)
  await page.getByRole("button", { name: "Return to hand" }).click()
  expect(posts).toEqual([])
  await page.getByRole("button", { name: "Report content issue" }).click()
  await expect(page.getByRole("dialog")).toContainText(run.pending!.event_id)
  await expect(page.getByRole("dialog")).toContainText(run.run_id)
  await expect(page.getByRole("dialog")).toContainText(/host|email report/i)
  await expect(page.getByRole("dialog")).not.toContainText(player.email)
  const report = await page
    .getByRole("dialog")
    .getByRole("textbox")
    .inputValue()
  expect(report).not.toContain(player.email)
  expect(report).not.toMatch(/Bearer|access_token|seed|year:/i)
  const emailLink = page.getByRole("link", { name: "Email report" })
  if (process.env.VITE_FEEDBACK_EMAIL) await expect(emailLink).toHaveCount(1)
  if (await emailLink.count()) {
    const href = decodeURIComponent((await emailLink.getAttribute("href"))!)
    expect(href).toContain(`Run ID: ${run.run_id}`)
    expect(href).toContain(`Event ID: ${run.pending!.event_id}`)
    expect(href).not.toContain(player.email)
  } else
    await expect(page.getByRole("dialog")).toContainText(
      "No feedback email is configured yet",
    )
  await page.getByRole("button", { name: "Close", exact: true }).click()
  await page.getByRole("link", { name: "New Freeplay", exact: true }).click()
  await expect(page).toHaveURL(/\/freeplay$/)
  await page.goto("/")
  await page
    .getByRole("link", {
      name: new RegExp(`Resume Freeplay.*${run.run_id.slice(0, 8)}`),
    })
    .click()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${run.revision}`,
  )
  let current = run
  while (current.status === "active") {
    const response = await page.request.post(`${runURL(run)}/placements`, {
      headers: player.headers,
      data: {
        operation_id: crypto.randomUUID(),
        expected_revision: current.revision,
        event_id: current.pending!.event_id,
        slot: 0,
      },
    })
    expect(response.ok()).toBeTruthy()
    const previous = current
    current = await response.json()
    if (current.status === "lost") expect(current.streak).toBe(previous.streak)
  }
  await page.reload()
  await expect(
    page.getByText(`Final streak: ${current.streak}`, { exact: true }),
  ).toBeVisible()
  if (current.status === "lost") {
    await expect(
      page.getByRole("heading", { name: "Mistake — run complete" }),
    ).toBeVisible()
    await expect(page.locator(".correct-location")).toHaveAttribute(
      "data-correct-slot",
      String(
        current.feedback!.correct_slot +
          (current.feedback!.attempted_slot! <= current.feedback!.correct_slot
            ? 1
            : 0),
      ),
    )
    const wrongCard = page.locator(".timeline-item[data-wrong=true]")
    await expect(wrongCard).toContainText(
      `${current.feedback!.card.year.value} ${current.feedback!.card.year.era}`,
    )
    await wrongCard
      .getByRole("button", { name: "Learn more", exact: true })
      .click()
    await page
      .getByRole("dialog")
      .getByText("Source/provenance details", { exact: true })
      .click()
    await expect(page.getByRole("dialog")).toContainText(
      current.feedback!.card.explanation,
    )
    await page.keyboard.press("Escape")
  }
  await page
    .getByRole("button", { name: "Report content issue" })
    .first()
    .click()
  await expect(page.getByRole("dialog")).toContainText(run.run_id)
})
