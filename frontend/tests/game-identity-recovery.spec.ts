import { mkdir, unlink, writeFile } from "node:fs/promises"
import { expect, type Page, test } from "@playwright/test"
import type {
  FreeplayStart,
  GameOptions,
  PlaceCommand,
  RunPublic,
} from "../src/client/types.gen"
import { keyboardPreview } from "./utils/boardInteraction"

const runId = "11111111-1111-4111-8111-111111111111"
const media = {
  url: "/assets/game-fallback.svg",
  fallback_url: "/assets/game-fallback.svg",
  alt_text: "Historical illustration",
  fit: "contain",
  credits: [{ label: "Fixture credit", url: null }],
}
const options: GameOptions = {
  protocol_version: 2,
  catalog_release_id: "controlled-ui",
  categories: [{ id: "history", label: "History" }],
  start: { value: 1, era: "CE" },
  end: { value: 2000, era: "CE" },
  registration_open: false,
}
const run: RunPublic = {
  run_id: runId,
  mode: "freeplay",
  daily_date: null,
  catalog_release_id: options.catalog_release_id,
  config: {
    category_ids: ["history"],
    start: options.start,
    end: options.end,
    min_gap: 1,
  },
  categories: options.categories,
  status: "active",
  initial_lives: 3,
  lives_remaining: 3,
  score: 0,
  streak: 0,
  revision: 0,
  timeline: [
    {
      event_id: "anchor",
      prompt: "Anchor",
      category_ids: ["history"],
      media,
      year: { value: 100, era: "CE" },
      explanation: "Anchor explanation",
      sources: [],
    },
  ],
  pending: {
    event_id: "pending",
    prompt: "Private pending card",
    category_ids: ["history"],
    media,
  },
  feedback: null,
}
async function harness(page: Page, token = "") {
  if (token)
    await page.addInitScript(
      (value) => localStorage.setItem("access_token", value),
      token,
    )
  const state = {
    run: structuredClone(run),
    guest: true,
    expired: false,
    bootstraps: 0,
    profiles: 0,
    moves: [] as { context: string | undefined; command: PlaceCommand }[],
    starts: [] as FreeplayStart[],
    delayMove: undefined as Promise<void> | undefined,
    delayRead: undefined as Promise<void> | undefined,
    delayStart: undefined as Promise<void> | undefined,
    delayLogin: undefined as Promise<void> | undefined,
    failStart: false,
    unavailableAccount: undefined as "inactive" | "deleted" | undefined,
    dailyStarts: [] as { operation_id: string; protocol_version: number }[],
    optionsProtocol: 2,
    missingRun: false,
  }
  await page.context().route("**/api/v1/**", async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace("/api/v1", "")
    const auth = request.headers().authorization
    const context = auth
      ? `account-${auth.replace("Bearer ", "")}`
      : "guest-one"
    const json = (value: unknown, status = 200) =>
      route.fulfill({ status, json: value })
    const accountFailure = () =>
      json(
        {
          detail: {
            code: "invalid_account",
            message:
              state.unavailableAccount === "inactive"
                ? "Inactive user"
                : "User not found",
          },
        },
        state.unavailableAccount === "inactive" ? 400 : 404,
      )
    if (path === "/utils/public-config")
      return json({ registration_open: false })
    if (path === "/login/access-token") {
      await state.delayLogin
      return json({ access_token: "one", token_type: "bearer" })
    }
    if (path === "/users/me") {
      state.profiles++
      if (!auth || state.expired)
        return json({ detail: "Could not validate credentials" }, 403)
      return json({
        id: auth.endsWith("two") ? "owner-two" : "owner-one",
        email: "player@example.com",
        full_name: "Account player",
        is_active: true,
        is_superuser: false,
      })
    }
    if (path === "/games/options")
      return json({ ...options, protocol_version: state.optionsProtocol })
    if (path === "/items/") {
      await state.delayRead
      return json({
        data: [
          {
            id: context,
            title: auth?.endsWith("two")
              ? "New account item"
              : "Private old account item",
            description: "Private description",
            owner_id: context,
          },
        ],
        count: 1,
      })
    }
    if (path === "/games/session") {
      if (auth && state.unavailableAccount) return accountFailure()
      if (auth && state.expired)
        return json({ detail: "Could not validate credentials" }, 403)
      if (request.method() === "POST") {
        state.bootstraps++
        state.guest = true
        state.expired = false
      }
      if (state.expired || (!auth && !state.guest))
        return json(
          {
            detail: {
              code: state.expired
                ? "game_session_expired"
                : "game_session_required",
              message: "Session unavailable",
            },
          },
          401,
        )
      return json({
        kind: auth ? "account" : "guest",
        context_id: context,
        protocol_version: 2,
      })
    }
    if (path === "/games/active-runs") return json([])
    if (path === "/games/daily" && request.method() === "POST") {
      state.dailyStarts.push(request.postDataJSON())
      await state.delayStart
      if (auth && state.unavailableAccount) return accountFailure()
      return json({ ...run, mode: "daily", daily_date: "2026-10-13" })
    }
    if (path === "/games/daily")
      return json({
        day: "2026-10-13",
        reset_at: "2099-10-14T00:00:00Z",
        category_ids: ["history"],
        attempt_run_id: null,
      })
    if (path === "/games/freeplay") {
      state.starts.push(request.postDataJSON())
      await state.delayStart
      if (auth && state.unavailableAccount) return accountFailure()
      if (state.failStart)
        return json(
          {
            detail: {
              code: "game_session_expired",
              message: "Session expired",
            },
          },
          401,
        )
      return json(state.run)
    }
    if (path.endsWith("/placements")) {
      state.moves.push({
        context: request.headers()["x-game-context"],
        command: request.postDataJSON(),
      })
      await state.delayMove
      if (auth && state.unavailableAccount) return accountFailure()
      return json(
        {
          detail: { code: "game_session_expired", message: "Session expired" },
        },
        401,
      )
    }
    if (path === `/games/runs/${runId}`) {
      await state.delayRead
      if (state.missingRun) return json({ detail: "Not found" }, 404)
      if (auth && state.unavailableAccount) return accountFailure()
      if (state.expired)
        return json(
          {
            detail: {
              code: "game_session_expired",
              message: "Session expired",
            },
          },
          401,
        )
      if (auth?.endsWith("two")) return json({ detail: "Not found" }, 404)
      return json(state.run)
    }
    return json({ detail: `Unexpected controlled endpoint ${path}` }, 404)
  })
  return state
}
async function openBoard(page: Page) {
  await page.goto(`/play/${runId}`)
  await expect(page.locator(".pending-draggable")).toBeVisible()
}
async function move(page: Page) {
  await keyboardPreview(page, 0)
  await page.getByRole("button", { name: "Confirm", exact: true }).click()
}
async function saved(page: Page, key: string) {
  return page.evaluate((value) => sessionStorage.getItem(value), key)
}

test("malformed or denied review storage never suppresses review or submits", async ({
  page,
}) => {
  const state = await harness(page, "one")
  const wrong = { ...run.timeline[0], event_id: "wrong", prompt: "Wrong event" }
  state.run = {
    ...run,
    status: "active",
    revision: 1,
    lives_remaining: 2,
    timeline: [run.timeline[0], wrong],
    pending: {
      event_id: "next",
      prompt: "Next private card",
      category_ids: ["history"],
      media,
    },
    feedback: {
      correct: false,
      card: wrong,
      attempted_slot: 0,
      correct_slot: 1,
    },
  }
  const key = `game-mistake-review:v1:account-one:${runId}:1`
  await page.addInitScript((reviewKey) => {
    const getItem = Storage.prototype.getItem
    const setItem = Storage.prototype.setItem
    Storage.prototype.getItem = function (key) {
      if (key === reviewKey) return "not-an-acknowledgement"
      return getItem.call(this, key)
    }
    Storage.prototype.setItem = function (key, value) {
      if (key === reviewKey) throw new DOMException("denied", "SecurityError")
      return setItem.call(this, key, value)
    }
  }, key)
  await page.goto(`/play/${runId}`)
  await expect(
    page.getByRole("button", { name: "Continue", exact: true }),
  ).toBeVisible()
  await page.getByRole("button", { name: "Continue", exact: true }).click()
  await expect(page.locator(".pending-draggable")).toBeVisible()
  expect(state.moves).toHaveLength(0)
  await page.reload()
  await expect(
    page.getByRole("button", { name: "Continue", exact: true }),
  ).toBeVisible()
  expect(state.moves).toHaveLength(0)
})

test("account switch during mistake review cannot acknowledge or submit old-context state", async ({
  page,
}) => {
  const state = await harness(page, "one")
  const wrong = { ...run.timeline[0], event_id: "wrong", prompt: "Wrong event" }
  state.run = {
    ...run,
    status: "active",
    revision: 1,
    lives_remaining: 2,
    timeline: [run.timeline[0], wrong],
    pending: {
      event_id: "next",
      prompt: "Next private card",
      category_ids: ["history"],
      media,
    },
    feedback: {
      correct: false,
      card: wrong,
      attempted_slot: 0,
      correct_slot: 1,
    },
  }
  await page.goto(`/play/${runId}`)
  await expect(
    page.getByRole("button", { name: "Continue", exact: true }),
  ).toBeVisible()
  await page.evaluate(() => localStorage.setItem("access_token", "two"))
  await expect(
    page.getByRole("button", { name: "Continue", exact: true }),
  ).toHaveCount(0)
  expect(state.moves).toHaveLength(0)
  expect(
    await page.evaluate(
      () =>
        Object.keys(sessionStorage).filter((key) =>
          key.startsWith("game-mistake-review:"),
        ).length,
    ),
  ).toBe(0)
})

for (const accountState of ["inactive", "deleted"] as const) {
  test(`${accountState} account owned read offers session recovery without replacement`, async ({
    page,
  }) => {
    const pageErrors: string[] = []
    page.on("pageerror", (error) => pageErrors.push(error.message))
    const state = await harness(page, "one")
    let release!: () => void
    state.delayRead = new Promise<void>((resolve) => {
      release = resolve
    })
    await page.goto(`/play/${runId}`)
    await expect(
      page.getByRole("heading", { name: "Loading run…" }),
    ).toBeVisible()
    state.unavailableAccount = accountState
    release()
    await expect(
      page.getByRole("button", { name: "Retry session", exact: true }),
    ).toBeVisible()
    await expect(page.getByTestId("pending-card")).toHaveCount(0)
    await page
      .getByRole("button", { name: "Retry session", exact: true })
      .click()
    await expect(
      page.getByRole("button", { name: "Continue as guest" }),
    ).toBeVisible()
    expect(state.bootstraps).toBe(0)
    expect(state.moves).toHaveLength(0)
    await page.getByRole("button", { name: "Continue as guest" }).click()
    await expect(page).toHaveURL(/\/$/)
    await expect(
      page.getByRole("heading", { name: "Historical Date Game", exact: true }),
    ).toBeVisible()
    expect(state.moves).toHaveLength(0)
    expect(state.starts).toHaveLength(0)
    expect(state.dailyStarts).toHaveLength(0)
    expect(pageErrors).toEqual([])
  })

  test(`${accountState} account placement retains exact UUID and body through explicit guest continuation`, async ({
    page,
  }) => {
    const pageErrors: string[] = []
    page.on("pageerror", (error) => pageErrors.push(error.message))
    const state = await harness(page, "one")
    await openBoard(page)
    let release!: () => void
    state.delayMove = new Promise<void>((resolve) => {
      release = resolve
    })
    await move(page)
    await expect.poll(() => state.moves.length).toBe(1)
    const key = `game:v2:account-one:placement:${runId}`
    const original = await saved(page, key)
    expect(JSON.parse(original!)).toEqual(state.moves[0].command)
    state.unavailableAccount = accountState
    release()
    await expect(
      page.getByRole("button", { name: "Retry session", exact: true }),
    ).toBeVisible()
    expect(await saved(page, key)).toBe(original)
    await page
      .getByRole("button", { name: "Retry session", exact: true })
      .click()
    await expect(
      page.getByRole("button", { name: "Continue as guest" }),
    ).toBeVisible()
    expect(state.bootstraps).toBe(0)
    expect(state.moves).toHaveLength(1)
    expect(await saved(page, key)).toBe(original)
    await page.getByRole("button", { name: "Continue as guest" }).click()
    await expect(page).toHaveURL(/\/$/)
    await expect(
      page.getByRole("heading", { name: "Historical Date Game", exact: true }),
    ).toBeVisible()
    expect(await saved(page, key)).toBe(original)
    expect(state.moves).toHaveLength(1)
    expect(await saved(page, `game:v2:guest-one:placement:${runId}`)).toBeNull()
    expect(pageErrors).toEqual([])
  })

  for (const mode of ["daily", "freeplay"] as const) {
    test(`${accountState} account ${mode} start retains exact UUID and body without automatic replay`, async ({
      page,
    }) => {
      const state = await harness(page, "one")
      let release!: () => void
      state.delayStart = new Promise<void>((resolve) => {
        release = resolve
      })
      await page.goto(`/${mode}`)
      await page
        .getByRole("button", {
          name: mode === "daily" ? "Start Daily" : "Start Freeplay",
          exact: true,
        })
        .click()
      const starts = mode === "daily" ? state.dailyStarts : state.starts
      await expect.poll(() => starts.length).toBe(1)
      const bootstrapsBeforeFailure = state.bootstraps
      const key = `game:v2:account-one:start:${mode}`
      const original = await saved(page, key)
      expect(JSON.parse(original!)).toEqual(starts[0])
      expect(starts[0].protocol_version).toBe(2)
      state.unavailableAccount = accountState
      release()
      await expect(
        page.getByRole("button", { name: "Retry session", exact: true }),
      ).toBeVisible()
      expect(await saved(page, key)).toBe(original)
      await page
        .getByRole("button", { name: "Retry session", exact: true })
        .click()
      await expect(
        page.getByRole("button", { name: "Continue as guest" }),
      ).toBeVisible()
      expect(state.bootstraps).toBe(bootstrapsBeforeFailure)
      expect(starts).toHaveLength(1)
      await page.getByRole("button", { name: "Continue as guest" }).click()
      await expect(page).toHaveURL(/\/$/)
      await expect(
        page.getByRole("heading", {
          name: "Historical Date Game",
          exact: true,
        }),
      ).toBeVisible()
      expect(await saved(page, key)).toBe(original)
      expect(starts).toHaveLength(1)
      expect(await saved(page, `game:v2:guest-one:start:${mode}`)).toBeNull()
    })
  }
}

test("missing owned run shows refresh guidance rather than session recovery", async ({
  page,
}) => {
  await harness(page, "two")
  await page.goto(`/play/${runId}`)
  await expect(
    page.getByRole("heading", { name: "Run unavailable" }),
  ).toBeVisible()
  await expect(page.getByRole("alert")).toContainText(
    "Game updated. Refresh and start a new game.",
  )
  await expect(
    page.getByRole("button", { name: "Retry session", exact: true }),
  ).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: "Continue as guest" }),
  ).toHaveCount(0)
})

test("guest_home_has_no_login_gate", async ({ page }) => {
  const state = await harness(page)
  state.guest = false
  await page.goto("/")
  await expect(
    page.getByRole("heading", { name: "Historical Date Game", exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("link", { name: "Daily challenge" }),
  ).toBeVisible()
  await expect(
    page.getByRole("link", { name: "Sign in", exact: true }),
  ).toBeVisible()
  await page.getByRole("link", { name: "Daily challenge" }).click()
  await expect(page.getByRole("button", { name: "Start Daily" })).toBeVisible()
  expect(state.bootstraps).toBeGreaterThan(0)
  await page.goto("/freeplay")
  await page.getByRole("button", { name: "Start Freeplay" }).click()
  await expect(page.locator(".pending-draggable")).toBeVisible()
  await expect(page.getByTestId("pending-card")).not.toContainText("100 CE")
  await page
    .getByRole("button", { name: "Credits/Sources", exact: true })
    .click()
  await expect(
    page.getByRole("dialog").getByText("Fixture credit").first(),
  ).toBeVisible()
  await expect(page.getByRole("dialog")).toContainText(media.url)
  await page.keyboard.press("Escape")
})
test("guest_does_not_request_user_me", async ({ page }) => {
  const state = await harness(page)
  await page.goto("/freeplay")
  await expect(
    page.getByRole("button", { name: "Start Freeplay" }),
  ).toBeVisible()
  expect(state.profiles).toBe(0)
})
test("guest_settings_and_admin_stay_protected", async ({ page }) => {
  const state = await harness(page)
  for (const path of ["/settings", "/admin", "/items"]) {
    await page.goto(path)
    await expect(page).toHaveURL(/\/login$/)
  }
  expect(state.profiles).toBe(0)
})
test("identity_switch_does_not_replay_uncertain_move", async ({ page }) => {
  const state = await harness(page, "one")
  await openBoard(page)
  let release!: () => void
  state.delayMove = new Promise<void>((resolve) => {
    release = resolve
  })
  await move(page)
  await expect.poll(() => state.moves.length).toBe(1)
  const command = state.moves[0].command
  const key = `game:v2:account-one:placement:${runId}`
  const tab = await page.context().newPage()
  await tab.goto("/")
  await tab.evaluate(() => localStorage.setItem("access_token", "two"))
  await expect(page.getByTestId("pending-card")).toHaveCount(0)
  release()
  await expect(
    page.getByRole("heading", { name: "Run unavailable" }),
  ).toBeVisible()
  expect(JSON.parse((await saved(page, key))!)).toEqual(command)
  expect(state.moves).toHaveLength(1)
  await tab.evaluate(() => localStorage.setItem("access_token", "one"))
  await expect(
    page.getByRole("button", { name: "Retry same move" }),
  ).toBeVisible()
  await page.evaluate(() => window.dispatchEvent(new Event("focus")))
  expect(JSON.parse((await saved(page, key))!)).toEqual(command)
  expect(state.moves).toHaveLength(1)
})
test("expired_guest_does_not_bootstrap_during_move", async ({ page }) => {
  const state = await harness(page)
  await openBoard(page)
  const before = state.bootstraps
  state.expired = true
  await move(page)
  await expect(
    page.getByRole("button", { name: "Retry session", exact: true }),
  ).toBeVisible()
  await page.getByRole("button", { name: "Retry session", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Continue as guest" }),
  ).toBeVisible()
  expect(state.bootstraps).toBe(before)
  const key = `game:v2:guest-one:placement:${runId}`
  expect(JSON.parse((await saved(page, key))!)).toEqual(state.moves[0].command)
  expect(state.moves).toHaveLength(1)
  expect(page.url()).not.toContain("login")
})
test("expired_account_can_explicitly_continue_as_guest", async ({ page }) => {
  const state = await harness(page, "one")
  await openBoard(page)
  state.expired = true
  await move(page)
  await page.getByRole("button", { name: "Continue as guest" }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(
    page.getByRole("heading", { name: "Historical Date Game", exact: true }),
  ).toBeVisible()
  expect(
    await page.evaluate(() => localStorage.getItem("access_token")),
  ).toBeNull()
  expect(state.moves).toHaveLength(1)
  expect(
    await saved(page, `game:v2:account-one:placement:${runId}`),
  ).not.toBeNull()
})
test("old_account_start_record_is_ignored_and_fresh_start_uses_protocol_2", async ({
  page,
}) => {
  const state = await harness(page, "one")
  const command = {
    operation_id: "22222222-2222-4222-8222-222222222222",
    catalog_release_id: options.catalog_release_id,
    config: run.config,
  }
  await page.addInitScript(
    (value) =>
      sessionStorage.setItem(
        "game-start:owner-one:freeplay",
        JSON.stringify(value),
      ),
    command,
  )
  await page.goto("/freeplay")
  await expect(
    page.getByRole("button", { name: "Start Freeplay" }),
  ).toBeVisible()
  expect(await saved(page, "game:v2:account-one:start:freeplay")).toBeNull()
  expect(await saved(page, "game-start:owner-one:freeplay")).toEqual(
    JSON.stringify(command),
  )
  expect(state.starts).toHaveLength(0)
  await page.getByRole("button", { name: "Start Freeplay" }).click()
  await expect(page.locator(".pending-draggable")).toBeVisible()
  expect(state.starts).toHaveLength(1)
  expect(state.starts[0].protocol_version).toBe(2)
  expect(state.starts[0].operation_id).not.toBe(command.operation_id)
})
test("old placement record without protocol is ignored after fresh owned read", async ({
  page,
}) => {
  const state = await harness(page, "one")
  const command = {
    operation_id: "33333333-3333-4333-8333-333333333333",
    expected_revision: 0,
    event_id: "pending",
    slot: 0,
  }
  const legacy = `game-placement:owner-one:${runId}`
  await page.addInitScript(
    ({ key, value }) => sessionStorage.setItem(key, JSON.stringify(value)),
    { key: legacy, value: command },
  )
  let release!: () => void
  state.delayRead = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.goto(`/play/${runId}`)
  await expect(
    page.getByRole("heading", { name: "Loading run…" }),
  ).toBeVisible()
  expect(await saved(page, legacy)).not.toBeNull()
  release()
  await expect(page.getByTestId("pending-card")).toBeVisible()
  expect(await saved(page, `game:v2:account-one:placement:${runId}`)).toBeNull()
  expect(await saved(page, legacy)).toEqual(JSON.stringify(command))
  expect(state.moves).toHaveLength(0)
  expect(await page.evaluate(() => localStorage.getItem("access_token"))).toBe(
    "one",
  )
})

test("delayed successful start cannot consume an old context command or navigate a new player", async ({
  page,
}) => {
  const state = await harness(page, "one")
  let release!: () => void
  state.delayStart = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.goto("/freeplay")
  await page.getByRole("button", { name: "Start Freeplay" }).click()
  await expect.poll(() => state.starts.length).toBe(1)
  const key = "game:v2:account-one:start:freeplay"
  await page.evaluate(() => localStorage.setItem("access_token", "two"))
  await expect(
    page.getByRole("button", { name: "Start Freeplay" }),
  ).toBeVisible()
  release()
  await expect(page).toHaveURL(/\/freeplay$/)
  expect(JSON.parse((await saved(page, key))!)).toEqual(state.starts[0])
  expect(await saved(page, "game:v2:account-two:start:freeplay")).toBeNull()
})
test("delayed owned GET cannot display another player's pending answers", async ({
  page,
}) => {
  const state = await harness(page, "one")
  let release!: () => void
  state.delayRead = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.goto(`/play/${runId}`)
  await expect(
    page.getByRole("heading", { name: "Loading run…" }),
  ).toBeVisible()
  await page.evaluate(() => localStorage.setItem("access_token", "two"))
  release()
  await expect(
    page.getByRole("heading", { name: "Run unavailable" }),
  ).toBeVisible()
  await expect(page.getByTestId("pending-card")).toHaveCount(0)
  expect(state.moves).toHaveLength(0)
})
test("legacy start record is ignored without blocking new protocol play", async ({
  page,
}) => {
  await harness(page, "one")
  await page.addInitScript(() => {
    sessionStorage.setItem(
      "game-start:owner-one:daily",
      '{"operation_id":"old"}',
    )
    sessionStorage.setItem(
      "game:account-one:start:daily",
      '{"operation_id":"new"}',
    )
  })
  await page.goto("/daily")
  await expect(page.getByRole("button", { name: "Start Daily" })).toBeVisible()
  expect(await saved(page, "game:v2:account-one:start:daily")).toBeNull()
  expect(await saved(page, "game-start:owner-one:daily")).toBe(
    '{"operation_id":"old"}',
  )
  expect(await saved(page, "game:v2:account-one:start:daily")).toBeNull()
  expect(await saved(page, "game:account-one:start:daily")).toBe(
    '{"operation_id":"new"}',
  )
})
test("sign out returns to guest Home and optional sign in restores account without transfer", async ({
  page,
}) => {
  const state = await harness(page, "one")
  await page.goto("/")
  await page.getByRole("button", { name: /Account player/ }).click()
  await page.getByRole("menuitem", { name: "Log Out", exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(
    page.getByRole("link", { name: "Sign in", exact: true }),
  ).toBeVisible()
  await page.getByRole("link", { name: "Sign in", exact: true }).click()
  await page.getByLabel("Email", { exact: true }).fill("player@example.com")
  await page
    .getByPlaceholder("Password", { exact: true })
    .fill("controlled-password")
  await page.getByRole("button", { name: "Log In" }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByText("Welcome back, Account player.")).toBeVisible()
  expect(state.moves).toHaveLength(0)
})
test("private verification artifacts remain denied by the owned UI server", async ({
  page,
}) => {
  const root = new URL("../", import.meta.url).pathname
  const paths = [
    ".env.identity-deny-probe",
    "playwright/.auth/identity-deny-probe.json",
    ".superpowers/identity-deny-probe.txt",
  ]
  const owned: string[] = []
  try {
    for (const path of paths) {
      await mkdir(`${root}${path.substring(0, path.lastIndexOf("/")) || "."}`, {
        recursive: true,
      })
      await writeFile(`${root}${path}`, "public-test-sentinel-not-a-secret", {
        flag: "wx",
      })
      owned.push(path)
      for (const url of [`/${path}`, `/@fs${root}${path}`]) {
        const response = await page.request.get(url)
        expect(response.status()).toBe(403)
        expect(await response.text()).not.toContain(
          "public-test-sentinel-not-a-secret",
        )
      }
    }
  } finally {
    for (const path of owned) await unlink(`${root}${path}`)
  }
})

test("expired guest owned GET offers inspection retry without allocation", async ({
  page,
}) => {
  const state = await harness(page)
  let release!: () => void
  state.delayRead = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.goto(`/play/${runId}`)
  await expect(
    page.getByRole("heading", { name: "Loading run…" }),
  ).toBeVisible()
  state.expired = true
  release()
  await expect(
    page.getByRole("button", { name: "Retry session", exact: true }),
  ).toBeVisible()
  expect(state.bootstraps).toBe(0)
})
test("route changes after session failure cannot silently allocate a replacement guest", async ({
  page,
}) => {
  const state = await harness(page)
  await openBoard(page)
  state.expired = true
  await move(page)
  await expect(
    page.getByRole("button", { name: "Continue as guest" }),
  ).toBeVisible()
  await page.getByRole("link", { name: "← Home", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Retry session", exact: true }),
  ).toBeVisible()
  expect(state.bootstraps).toBe(0)
  expect(state.moves).toHaveLength(1)
})

test("protected item queries cannot retain delayed private data after account switch", async ({
  page,
}) => {
  const state = await harness(page, "one")
  let release!: () => void
  state.delayRead = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.goto("/items")
  await expect(
    page.getByRole("heading", { name: "Items", exact: true }),
  ).toBeVisible()
  await page.evaluate(() => localStorage.setItem("access_token", "two"))
  release()
  await expect(
    page.getByText("New account item", { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByText("Private old account item", { exact: true }),
  ).toHaveCount(0)
  await page.evaluate(() => localStorage.removeItem("access_token"))
  await expect(page).toHaveURL(/\/login$/)
})

test("late public game failure on an account page cannot force login", async ({
  page,
}) => {
  const state = await harness(page, "one")
  let release!: () => void
  state.delayStart = new Promise<void>((resolve) => {
    release = resolve
  })
  state.failStart = true
  await page.goto("/freeplay")
  await page.getByRole("button", { name: "Start Freeplay" }).click()
  await expect.poll(() => state.starts.length).toBe(1)
  await page.getByRole("link", { name: "Account", exact: true }).click()
  await expect(
    page.getByRole("heading", { name: "User Settings", exact: true }),
  ).toBeVisible()
  const response = page.waitForResponse((value) =>
    value.url().endsWith("/games/freeplay"),
  )
  release()
  await response
  // Let response callbacks settle before asserting absence of a redirect.
  await page.waitForTimeout(150)
  await expect(page).toHaveURL(/\/settings$/)
  expect(await page.evaluate(() => localStorage.getItem("access_token"))).toBe(
    "one",
  )
  expect(await saved(page, "game:v2:account-one:start:freeplay")).not.toBeNull()
})

test("legacy placement record is ignored and never submitted", async ({
  page,
}) => {
  const state = await harness(page, "one")
  const command: PlaceCommand = {
    operation_id: "33333333-3333-4333-8333-333333333333",
    protocol_version: 2,
    expected_revision: 0,
    event_id: "pending",
    slot: 0,
  }
  await page.addInitScript(
    ({ id, value }) => {
      sessionStorage.setItem(
        `game-placement:owner-one:${id}`,
        JSON.stringify(value),
      )
    },
    { id: runId, value: command },
  )
  await page.goto(`/play/${runId}`)
  await expect(page.getByTestId("pending-card")).toBeVisible()
  expect(state.moves).toHaveLength(0)
  expect(
    JSON.parse((await saved(page, `game-placement:owner-one:${runId}`))!),
  ).toEqual(command)
  expect(await saved(page, `game:v2:account-one:placement:${runId}`)).toBeNull()
  await expect(
    page.getByRole("button", { name: "Confirm", exact: true }),
  ).toHaveCount(0)
})

test("unsupported options show refresh guidance and cannot start play", async ({
  page,
}) => {
  const state = await harness(page)
  state.optionsProtocol = 1
  await page.goto("/freeplay")
  await expect(page.getByRole("alert")).toContainText(
    "Game updated. Refresh and start a new game.",
  )
  await expect(
    page.getByRole("button", { name: "Start Freeplay" }),
  ).toHaveCount(0)
  expect(state.starts).toHaveLength(0)
})

test("missing old run shows refresh guidance without allocating or replacing recovery", async ({
  page,
}) => {
  const state = await harness(page, "one")
  state.missingRun = true
  const oldCommand = {
    operation_id: "55555555-5555-4555-8555-555555555555",
    expected_revision: 0,
    event_id: "pending",
    slot: 0,
  }
  const legacyKey = `game:account-one:placement:${runId}`
  await page.addInitScript(
    ({ key, value }) => sessionStorage.setItem(key, JSON.stringify(value)),
    { key: legacyKey, value: oldCommand },
  )
  await page.goto(`/play/${runId}`)
  await expect(page.getByRole("alert")).toContainText(
    "Game updated. Refresh and start a new game.",
  )
  expect(state.moves).toHaveLength(0)
  expect(state.starts).toHaveLength(0)
  expect(state.bootstraps).toBe(0)
  expect(await page.evaluate(() => localStorage.getItem("access_token"))).toBe(
    "one",
  )
  expect(await saved(page, legacyKey)).toEqual(JSON.stringify(oldCommand))
})

test("expired accounts on protected routes still go to login", async ({
  page,
}) => {
  const state = await harness(page, "one")
  state.expired = true
  await page.goto("/settings")
  await expect(page).toHaveURL(/\/login$/)
})

test("a regular signed-in account cannot open admin", async ({ page }) => {
  await harness(page, "one")
  await page.goto("/admin")
  await expect(page).toHaveURL(/\/$/)
  await expect(
    page.getByRole("heading", { name: "Historical Date Game", exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("link", { name: "Admin", exact: true }),
  ).toHaveCount(0)
})

test("a delayed login response cannot replace an account selected in another tab", async ({
  page,
}) => {
  const state = await harness(page)
  let release!: () => void
  state.delayLogin = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.goto("/login")
  await page.getByTestId("email-input").fill("player@example.com")
  await page.getByTestId("password-input").fill("controlled-password")
  const requested = page.waitForRequest((request) =>
    request.url().endsWith("/login/access-token"),
  )
  await page.getByRole("button", { name: "Log In", exact: true }).click()
  await requested
  const tab = await page.context().newPage()
  await tab.goto("/")
  await tab.evaluate(() => localStorage.setItem("access_token", "two"))
  const response = page.waitForResponse((value) =>
    value.url().endsWith("/login/access-token"),
  )
  release()
  await response
  await page.waitForTimeout(150)
  expect(await page.evaluate(() => localStorage.getItem("access_token"))).toBe(
    "two",
  )
})
