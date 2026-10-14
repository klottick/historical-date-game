// Actual owned backend + immutable real release. Answers remain in Node only.
import { execFileSync } from "node:child_process"
import { createHash, randomUUID } from "node:crypto"
import { appendFileSync, existsSync, mkdirSync, writeFileSync } from "node:fs"
import { resolve } from "node:path"
import { expect, type Page, test } from "@playwright/test"
import type {
  GameSessionPublic,
  PlaceCommand,
  RunPublic,
} from "../src/client/types.gen"
import {
  boardEvidence,
  verificationDatabase,
  verificationRuntime,
} from "../tests/utils/boardEvidence"
import { keyboardPreview } from "../tests/utils/boardInteraction"
import { ownedBackend as owned } from "../tests/utils/ownedVerification"
import { loadCatalog } from "../tests-real-catalog/catalog"

const evidence = boardEvidence
const backend = resolve("../backend")
const python = resolve(backend, ".venv/bin/python")
const api = "http://localhost:8020/api/v1"

// Browser fetch is essential: Node's request context does not resolve guest.test.
async function game(
  page: Page,
  path: string,
  context?: GameSessionPublic,
  data?: unknown,
) {
  return page.evaluate(
    async ({ path, context, data }) => {
      const response = await fetch(`/api/v1/games/${path}`, {
        method: data === undefined ? "GET" : "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-Game-Request": "1",
          ...(context ? { "X-Game-Context": context.context_id } : {}),
          ...(localStorage.getItem("access_token")
            ? {
                Authorization: `Bearer ${localStorage.getItem("access_token")}`,
              }
            : {}),
        },
        ...(data === undefined ? {} : { body: JSON.stringify(data) }),
      })
      return { status: response.status, body: await response.json() }
    },
    { path, context, data },
  )
}
async function session(page: Page): Promise<GameSessionPublic> {
  const response = await game(page, "session")
  expect(response.status).toBe(200)
  expect(Object.keys(response.body).sort()).toEqual(["context_id", "kind"])
  return response.body
}
async function ready(page: Page) {
  await page.goto("/")
  await expect(page.getByText(/Welcome! Play without an account/)).toBeVisible()
  await expect(
    page.getByRole("heading", { name: "Historical Date Game", exact: true }),
  ).toBeVisible()
  await expect(page.getByTestId("email-input")).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: "Continue as guest", exact: true }),
  ).toHaveCount(0)
  return session(page)
}
function privateFree(run: RunPublic) {
  expect(JSON.stringify(run)).not.toMatch(
    /"(?:seed|pool|owner_id|unused_events|snapshot_id|pending_year)"/,
  )
  if (run.pending) {
    expect(Object.keys(run.pending).sort()).toEqual([
      "category_ids",
      "event_id",
      "media",
      "prompt",
    ])
    expect(JSON.stringify(run.pending)).not.toMatch(
      /"(?:year|sources|explanation|raw_date)"/,
    )
  }
}
async function catalog(page: Page) {
  const options = await game(page, "options")
  expect(options.status).toBe(200)
  return loadCatalog(options.body.catalog_release_id)
}
function slot(run: RunPublic, years: Map<string, number>) {
  const answer = years.get(run.pending!.event_id)
  expect(answer !== undefined).toBe(true)
  return run.timeline.filter(
    (c) => (c.year.era === "CE" ? c.year.value : 1 - c.year.value) < answer!,
  ).length
}
async function start(
  page: Page,
  mode: "daily" | "freeplay",
): Promise<RunPublic> {
  await page.goto(`/${mode}`)
  const button = page.getByRole("button", {
    name: mode === "daily" ? "Start Daily" : "Start Freeplay",
    exact: true,
  })
  await expect(button).toBeEnabled()
  const response = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" && r.url().endsWith(`/games/${mode}`),
  )
  await button.click()
  const result = await response
  expect(result.status()).toBe(200)
  const run: RunPublic = await result.json()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${run.revision}`,
  )
  privateFree(run)
  return run
}
async function move(
  page: Page,
  run: RunPublic,
  index: number,
): Promise<RunPublic> {
  privateFree(run)
  const pending = page.getByTestId("pending-card")
  await expect(pending).toContainText("Year hidden")
  await expect
    .poll(() =>
      pending
        .locator("img")
        .evaluate((i: HTMLImageElement) => i.complete && i.naturalWidth > 0),
    )
    .toBe(true)
  await expect(pending.locator("details")).toHaveCount(0)
  await page
    .getByRole("button", { name: "Credits/Sources", exact: true })
    .click()
  for (const credit of run.pending!.media.credits)
    await expect(page.getByRole("dialog")).toContainText(credit.label)
  await page.keyboard.press("Escape")
  await keyboardPreview(page, index)
  const response = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/placements"),
  )
  await page.getByRole("button", { name: "Lock it in", exact: true }).click()
  const result = await response
  expect(result.status()).toBe(200)
  const next: RunPublic = await result.json()
  await expect(page.getByTestId("run-revision")).toHaveText(
    `Revision: ${next.revision}`,
  )
  privateFree(next)
  return next
}

test("fresh no-login Home, secure cookie boundary, real media and private HTTP denial", async ({
  page,
  context,
  request,
}) => {
  const responses: Promise<{
    httpOnly: boolean
    path: boolean
    lax: boolean
    hostOnly: boolean
    noStore: boolean
  }>[] = []
  page.on("response", (r) => {
    if (r.request().method() !== "POST" || !r.url().endsWith("/games/session"))
      return
    responses.push(
      r.allHeaders().then((headers) => {
        const cookie = headers["set-cookie"] || ""
        return {
          httpOnly: /httponly/i.test(cookie),
          path: /path=\/api\/v1\/games/i.test(cookie),
          lax: /samesite=lax/i.test(cookie),
          hostOnly: !/domain=/i.test(cookie),
          noStore: headers["cache-control"] === "no-store",
        }
      }),
    )
  })
  const identity = await ready(page)
  expect(identity.kind).toBe("guest")
  expect(responses.length).toBeGreaterThan(0)
  expect(
    (await Promise.all(responses)).every((r) =>
      Object.values(r).every(Boolean),
    ),
  ).toBe(true)
  const cookies = await context.cookies()
  const cookie = cookies.find((c) => c.name === "hdg_guest_verification")!
  // Never assert/serialize the raw cookie value.
  expect(
    Boolean(
      cookie?.httpOnly &&
        cookie.path === "/api/v1/games" &&
        cookie.sameSite === "Lax",
    ),
  ).toBe(true)
  expect(
    await page.evaluate(() =>
      document.cookie.includes("hdg_guest_verification"),
    ),
  ).toBe(false)
  expect((await game(page, "active-runs", identity)).body).toEqual([])
  expect((await request.get(`${api}/users/me`)).status()).toBe(401)
  const release = await catalog(page)
  // Probe an actual private artifact, not Vite's HTML fallback for absent files.
  mkdirSync("playwright/.auth", { recursive: true, mode: 0o700 })
  writeFileSync(
    "playwright/.auth/guest-denial-probe.json",
    JSON.stringify({ privateProbe: true }),
    { mode: 0o600 },
  )
  for (const [name, hash] of Object.entries(release.manifest.files) as [
    string,
    string,
  ][]) {
    if (!name.startsWith("media/")) continue
    const asset = await request.get(
      `http://localhost:5184/media/${release.manifest.release_id}/${name.slice(6)}`,
    )
    expect(asset.status()).toBe(200)
    expect(
      createHash("sha256")
        .update(await asset.body())
        .digest("hex"),
    ).toBe(hash)
  }
  const existingPrivateFiles = [
    resolve("../.env"),
    resolve("playwright/.auth/guest-denial-probe.json"),
    resolve("tests-real-catalog/catalog.ts"),
    resolve(verificationRuntime, "seed.json"),
    ...(process.env.GAME_EVENT_LINKS_FILE
      ? [process.env.GAME_EVENT_LINKS_FILE]
      : []),
    resolve(process.env.REAL_CATALOG_RELEASE_DIR!, "events.jsonl"),
    resolve(process.env.REAL_CATALOG_RELEASE_DIR!, "manifest.json"),
  ]
  for (const file of existingPrivateFiles) {
    expect(
      existsSync(file),
      "disclosure probes must target existing files",
    ).toBe(true)
    expect([403, 404]).toContain(
      (await request.get(`http://localhost:5184/@fs${file}`)).status(),
    )
  }
  for (const path of [
    "/playwright/.auth/guest-denial-probe.json",
    "/tests-real-catalog/catalog.ts?raw",
    "/tests-guest-catalog/game-guest.spec.ts?raw",
    "/.env",
    "/.env?raw",
    `/@fs${process.env.REAL_CATALOG_RELEASE_DIR}/events.jsonl`,
    `/@fs${process.env.REAL_CATALOG_RELEASE_DIR}/manifest.json`,
  ]) {
    expect([403, 404]).toContain(
      (await request.get(`http://localhost:5184${path}`)).status(),
    )
  }
  for (const path of [
    "/events.jsonl",
    "/manifest.json",
    "/raw.jsonl",
    "/media/events.jsonl",
    "/media/manifest.json",
    `/media/${release.manifest.release_id}/events.jsonl`,
    `/media/${release.manifest.release_id}/manifest.json`,
  ]) {
    expect([403, 404]).toContain(
      (await request.get(`http://localhost:8020${path}`)).status(),
    )
  }
})

test("Freeplay correct, reload, exact committed retry, loss and new run", async ({
  page,
}) => {
  const identity = await ready(page)
  const release = await catalog(page)
  let run = await start(page, "freeplay")
  run = await move(page, run, slot(run, release.years))
  expect(run.feedback!.correct).toBe(true)
  expect(run.streak).toBe(1)
  await page.reload()
  await expect(page.getByTestId("run-revision")).toHaveText("Revision: 1")
  expect((await game(page, `runs/${run.run_id}`, identity)).body).toEqual(run)
  const commands: PlaceCommand[] = []
  let committed: RunPublic | undefined
  await page.route("**/placements", async (route) => {
    commands.push(route.request().postDataJSON())
    // Only this Node-side committed-response interceptor needs loopback transport;
    // the actual UI/browser stays at guest.test (Chromium-only DNS mapping).
    const request = route.request()
    const response = await route.fetch({
      url: request
        .url()
        .replace("http://guest.test:5184/", "http://localhost:5184/"),
      headers: await request.allHeaders(),
    })
    expect(response.status()).toBe(200)
    if (commands.length === 1) {
      committed = await response.json()
      await route.abort("failed")
    } else await route.fulfill({ response })
  })
  await keyboardPreview(page, slot(run, release.years))
  await page.getByRole("button", { name: "Lock it in", exact: true }).click()
  await expect(page.getByRole("alert")).toContainText("your run is not lost")
  // Retrying a saved command must not require a NEW cryptographic operation ID.
  await page.evaluate(() => {
    for (const name of ["randomUUID", "getRandomValues"])
      Object.defineProperty(crypto, name, {
        configurable: true,
        value: () => {
          throw new Error("No RNG available for new commands")
        },
      })
  })
  await page
    .getByRole("button", { name: "Retry same move", exact: true })
    .click()
  await expect(page.getByTestId("run-revision")).toHaveText("Revision: 2")
  await page.evaluate(() => {
    for (const name of ["randomUUID", "getRandomValues"])
      Reflect.deleteProperty(crypto, name)
  })
  expect(commands.length).toBe(2)
  expect(commands[1]).toEqual(commands[0])
  expect((await game(page, `runs/${run.run_id}`, identity)).body).toEqual(
    committed,
  )
  await page.reload()
  await expect(page.getByTestId("run-revision")).toHaveText("Revision: 2")
  await page.unroute("**/placements")
  run = committed!
  run = await move(page, run, slot(run, release.years) === 0 ? 1 : 0)
  expect(run.status).toBe("lost")
  expect(run.streak).toBe(2)
  await expect(
    page.getByRole("heading", { name: "Mistake — run complete" }),
  ).toBeVisible()
  await page.reload()
  expect((await game(page, `runs/${run.run_id}`, identity)).body).toEqual(run)
  const next = await start(page, "freeplay")
  expect(next.run_id).not.toBe(run.run_id)
})

test("two guests and account share Daily prefix, isolate reads/moves, one attempt after reload", async ({
  page,
  browser,
  baseURL,
  request,
}) => {
  const second = await browser.newContext({ baseURL })
  const account = await browser.newContext({ baseURL })
  try {
    const other = await second.newPage()
    const signed = await account.newPage()
    const identities = [await ready(page), await ready(other)]
    const release = await catalog(page)
    const login = await request.post(`${api}/login/access-token`, {
      form: {
        username: process.env.FIRST_SUPERUSER!,
        password: process.env.FIRST_SUPERUSER_PASSWORD!,
      },
    })
    expect(login.status()).toBe(200)
    const adminHeaders = {
      Authorization: `Bearer ${(await login.json()).access_token}`,
    }
    const email = `guest-proof-${randomUUID()}@example.com`
    const password = `${randomUUID()}Aa!`
    expect(
      (
        await request.post(`${api}/users/`, {
          headers: adminHeaders,
          data: { email, password, full_name: "Guest proof account" },
        })
      ).status(),
    ).toBe(200)
    const tokenResponse = await request.post(`${api}/login/access-token`, {
      form: { username: email, password },
    })
    expect(tokenResponse.status()).toBe(200)
    await signed.addInitScript(
      (token) => localStorage.setItem("access_token", token),
      (await tokenResponse.json()).access_token,
    )
    await signed.goto("/")
    await expect(signed.getByText(/Welcome back/)).toBeVisible()
    identities.push(await session(signed))
    expect(identities[2].kind).toBe("account")
    expect(new Set(identities.map((i) => i.context_id)).size).toBe(3)
    const pages = [page, other, signed]
    const runs: RunPublic[] = []
    for (const player of pages) runs.push(await start(player, "daily"))
    expect(new Set(runs.map((r) => r.run_id)).size).toBe(3)
    for (const run of runs.slice(1)) {
      expect(run.timeline).toEqual(runs[0].timeline)
      expect(run.pending).toEqual(runs[0].pending)
      expect(run.config).toEqual(runs[0].config)
    }
    for (let owner = 0; owner < 3; owner++) {
      const foreign = runs[(owner + 1) % 3]
      expect(
        (await game(pages[owner], `runs/${foreign.run_id}`, identities[owner]))
          .status,
      ).toBe(404)
      expect(
        (
          await game(
            pages[owner],
            `runs/${foreign.run_id}/placements`,
            identities[owner],
            {
              operation_id: randomUUID(),
              expected_revision: 0,
              event_id: foreign.pending!.event_id,
              slot: 0,
            },
          )
        ).status,
      ).toBe(404)
    }
    for (let round = 0; round < 3; round++) {
      for (let i = 0; i < 3; i++)
        runs[i] = await move(pages[i], runs[i], slot(runs[i], release.years))
      for (const run of runs.slice(1)) {
        expect(run.timeline).toEqual(runs[0].timeline)
        expect(run.pending).toEqual(runs[0].pending)
      }
    }
    for (let i = 0; i < 3; i++) {
      const repeated = await game(pages[i], "daily", identities[i], {
        operation_id: randomUUID(),
      })
      expect(repeated.status).toBe(200)
      expect(repeated.body).toEqual(runs[i])
      await pages[i].reload()
      await expect(pages[i].getByTestId("run-revision")).toHaveText(
        "Revision: 3",
      )
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
  } finally {
    await second.close()
    await account.close()
  }
})

test("simultaneous native cold tabs share one guest and one Daily, including insecure IndexedDB", async ({
  context,
  page,
}, info) => {
  const second = await context.newPage()
  await Promise.all([ready(page), ready(second)])
  if (info.project.name === "insecure-chromium") {
    expect(
      await page.evaluate(() => ({
        secure: window.isSecureContext,
        locks: Boolean(navigator.locks),
        idb: Boolean(indexedDB),
        origin: location.origin,
      })),
    ).toEqual({
      secure: false,
      locks: false,
      idb: true,
      origin: "http://guest.test:5184",
    })
  }
  const [firstIdentity, secondIdentity] = await Promise.all([
    session(page),
    session(second),
  ])
  expect(firstIdentity).toEqual(secondIdentity)
  const runs = await Promise.all([start(page, "daily"), start(second, "daily")])
  expect(runs[0]).toEqual(runs[1])
  expect((await game(page, "active-runs", firstIdentity)).body).toHaveLength(1)
})

for (const failure of ["deleted", "expired"] as const) {
  test(`cookie ${failure} mid-move is availability, no automatic allocation or scoring`, async ({
    page,
    context,
  }) => {
    const identity = await ready(page)
    const run = await start(page, "freeplay")
    const posts: string[] = []
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().endsWith("/games/session"))
        posts.push(r.url())
    })
    if (failure === "deleted") await context.clearCookies()
    else {
      const output = execFileSync(
        python,
        [
          "-c",
          `
from uuid import UUID
from datetime import UTC, datetime, timedelta
from sqlmodel import Session, select
from app.core.db import engine
from app.game.guest_models import GuestSession
from tests.browser.guest_test_environment import require_owned_guest_database
require_owned_guest_database()
with Session(engine) as session:
    row = session.exec(select(GuestSession).where(GuestSession.public_id == UUID('${identity.context_id.slice(2)}'))).one()
    row.created_at = datetime.now(UTC) - timedelta(days=91)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.add(row)
    session.commit()
`,
        ],
        {
          cwd: backend,
          env: {
            ...process.env,
            POSTGRES_DB: verificationDatabase,
            POSTGRES_SERVER: "127.0.0.1",
            POSTGRES_PORT: "5433",
          },
          encoding: "utf8",
        },
      )
      appendFileSync(`${evidence}/expiry.log`, output, { mode: 0o600 })
    }
    await keyboardPreview(page, 0)
    await page.getByRole("button", { name: "Lock it in", exact: true }).click()
    await expect(page.getByRole("alert")).toContainText("Your run is not lost")
    await page
      .getByRole("button", { name: "Retry session", exact: true })
      .click()
    await expect(
      page.getByRole("button", { name: "Continue as guest", exact: true }),
    ).toBeVisible()
    expect(posts).toEqual([])
    expect((await game(page, `runs/${run.run_id}`, identity)).status).toBe(401)
    await page
      .getByRole("button", { name: "Continue as guest", exact: true })
      .click()
    await expect(
      page.getByText(/Welcome! Play without an account/),
    ).toBeVisible()
    const replacement = await session(page)
    expect(replacement.context_id).not.toBe(identity.context_id)
    expect((await game(page, `runs/${run.run_id}`, replacement)).status).toBe(
      404,
    )
    expect((await game(page, "active-runs", replacement)).body).toEqual([])
  })
}

test("bootstrap transport failure does not score or repeatedly allocate", async ({
  page,
}) => {
  let posts = 0
  await page.route("**/games/session", async (route) => {
    if (route.request().method() === "POST") {
      posts++
      await route.abort("failed")
    } else await route.continue()
  })
  const scored: string[] = []
  page.on("request", (r) => {
    if (r.method() === "POST" && /\/games\/(daily|freeplay)$/.test(r.url()))
      scored.push(r.url())
  })
  await page.goto("/")
  await expect(page.getByRole("alert")).toContainText("Your run is not lost")
  await page.getByRole("button", { name: "Retry session", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Continue as guest", exact: true }),
  ).toBeVisible()
  expect(posts).toBe(1)
  expect(scored).toEqual([])
  await page.unroute("**/games/session")
  await page
    .getByRole("button", { name: "Continue as guest", exact: true })
    .click()
  await expect(page.getByText(/Welcome! Play without an account/)).toBeVisible()
})

test("actual owned backend restart preserves progressed guest Daily and Freeplay DTOs", async ({
  page,
}, info) => {
  test.setTimeout(120_000)
  const identity = await ready(page)
  const release = await catalog(page)
  const runs: RunPublic[] = []
  for (const mode of ["daily", "freeplay"] as const) {
    const initial = await start(page, mode)
    runs.push(await move(page, initial, slot(initial, release.years)))
  }
  owned("stop")
  owned("launch")
  const results = []
  for (const before of runs) {
    const rehydrated = await game(page, `runs/${before.run_id}`, identity)
    expect(rehydrated.status).toBe(200)
    expect(rehydrated.body).toEqual(before)
    await page.goto(`/play/${before.run_id}`)
    await expect(page.getByTestId("run-revision")).toHaveText("Revision: 1")
    expect(await session(page)).toEqual(identity)
    const after = await move(page, before, slot(before, release.years))
    expect(after.revision).toBe(2)
    expect(after.streak).toBe(2)
    expect(after.status).toBe("active")
    results.push({ before, rehydrated: rehydrated.body, after })
  }
  writeFileSync(
    `${evidence}/guest-restart-${info.project.name}.json`,
    JSON.stringify({ identicalRehydration: true, results }, null, 2),
    { mode: 0o600 },
  )
})

test("optional sign-in/out and expired account never replay guest commands, protected pages stay gated", async ({
  page,
}) => {
  const guest = await ready(page)
  const run = await start(page, "freeplay")
  const commands: PlaceCommand[] = []
  await page.route("**/placements", async (route) => {
    commands.push(route.request().postDataJSON())
    await route.abort("failed")
  })
  await keyboardPreview(page, 0)
  await page.getByRole("button", { name: "Lock it in", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Retry same move", exact: true }),
  ).toBeVisible()
  await page.getByRole("link", { name: "Sign in", exact: true }).click()
  await page.getByTestId("email-input").fill(process.env.FIRST_SUPERUSER!)
  await page
    .getByTestId("password-input")
    .fill(process.env.FIRST_SUPERUSER_PASSWORD!)
  await page.getByRole("button", { name: "Log In", exact: true }).click()
  await expect(page.getByText(/Welcome back/)).toBeVisible()
  const account = await session(page)
  expect(account.kind).toBe("account")
  expect((await game(page, `runs/${run.run_id}`, account)).status).toBe(404)
  expect(commands).toHaveLength(1)
  await page.goto("/settings")
  await expect(page).toHaveURL(/\/settings$/)
  if (!(await page.getByTestId("user-menu").isVisible()))
    await page
      .getByRole("button", { name: /^(Open|Collapse) Sidebar$/ })
      .click()
  await page.getByTestId("user-menu").click()
  await page.getByRole("menuitem", { name: "Log Out", exact: true }).click()
  await expect(page.getByText(/Welcome! Play without an account/)).toBeVisible()
  expect(await session(page)).toEqual(guest)
  expect(commands).toHaveLength(1)
  await page.goto("/login")
  await page.getByTestId("email-input").fill(process.env.FIRST_SUPERUSER!)
  await page
    .getByTestId("password-input")
    .fill(process.env.FIRST_SUPERUSER_PASSWORD!)
  await page.getByRole("button", { name: "Log In", exact: true }).click()
  await expect(page.getByText(/Welcome back/)).toBeVisible()
  expect(await session(page)).toEqual(account)
  await page.goto("/freeplay")
  await expect(
    page.getByRole("button", { name: "Start Freeplay", exact: true }),
  ).toBeEnabled()
  await page.evaluate(() =>
    localStorage.setItem("access_token", "expired-token"),
  )
  await page.reload()
  await expect(page.getByRole("alert")).toContainText("Your run is not lost")
  await expect(
    page
      .locator("section")
      .filter({
        has: page.getByRole("heading", {
          name: "Game session unavailable",
          exact: true,
        }),
      })
      .getByRole("link", { name: "Sign in", exact: true }),
  ).toBeVisible()
  await expect(page).toHaveURL(/\/freeplay$/)
  expect(commands).toHaveLength(1)
  await page
    .getByRole("button", { name: "Continue as guest", exact: true })
    .click()
  await expect(page.getByText(/Welcome! Play without an account/)).toBeVisible()
  expect(await session(page)).toEqual(guest)
  await page.goto(`/play/${run.run_id}`)
  await expect(
    page.getByRole("button", { name: "Retry same move", exact: true }),
  ).toBeVisible()
  expect(commands).toHaveLength(1)
  await page.unroute("**/placements")
  await page
    .getByRole("button", { name: "Retry same move", exact: true })
    .click()
  await expect(page.getByTestId("run-revision")).toHaveText("Revision: 1")
  for (const path of ["/settings", "/admin", "/items"]) {
    await page.goto(path)
    await expect(page).toHaveURL(/\/login$/)
  }
})
