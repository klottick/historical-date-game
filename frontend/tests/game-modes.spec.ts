import { test as base, expect } from "@playwright/test"

// Each authenticated mode test owns its account, including across projects.
// Public enrollment deliberately has no login; the Daily lifecycle below
// already creates and cleans up its own player.
const test = base.extend<{ modePlayer: undefined }>({
  modePlayer: [
    async ({ page }, use) => {
      await page.goto("/")
      const admin = await page.evaluate(() =>
        localStorage.getItem("access_token"),
      )
      const email = `mode-preview-${crypto.randomUUID()}@example.com`
      const password = "GameBrowser123!"
      const api = "http://localhost:8000/api/v1"
      expect(
        (
          await page.request.post(`${api}/users/`, {
            headers: { Authorization: `Bearer ${admin}` },
            data: { email, password, full_name: "Mode player" },
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
        await use(undefined)
      } finally {
        expect(
          (await page.request.delete(`${api}/users/me`, { headers })).ok(),
        ).toBeTruthy()
      }
    },
    { auto: true },
  ],
})

test("daily_preview_does_not_start", async ({ page }) => {
  const starts: string[] = []
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/games/daily"))
      starts.push(request.url())
  })
  await page.goto("/daily")
  await expect(
    page.getByRole("heading", { name: "Daily challenge" }),
  ).toBeVisible()
  await expect(page.getByText(/UTC/).first()).toBeVisible()
  await expect(page.getByRole("button", { name: "Start Daily" })).toBeVisible()
  expect(starts).toEqual([])
  const token = await page.evaluate(() => localStorage.getItem("access_token"))
  const overview = await page.request.get(
    "http://localhost:8000/api/v1/games/daily",
    { headers: { Authorization: `Bearer ${token}` } },
  )
  expect((await overview.json()).attempt_run_id).toBeNull()
})

base.describe("public enrollment", () => {
  base.use({ storageState: { cookies: [], origins: [] } })
  base("signup_hidden_when_enrollment_closed", async ({ page }) => {
    // The public-config seam also exercises closed UI in the open enrollment
    // baseline suite; the U1 closed-backend run supplies this value for real.
    if (!process.env.U1_CLOSED_BACKEND) {
      await page.route("**/api/v1/utils/public-config", (route) =>
        route.fulfill({ json: { registration_open: false } }),
      )
    }
    await page.goto("/login")
    await expect(page.getByText(/Enrollment is restricted/)).toBeVisible()
    await expect(page.getByRole("link", { name: "Sign up" })).toHaveCount(0)
    await page.goto("/signup")
    await expect(page.getByText(/Enrollment is restricted/)).toBeVisible()
    await expect(
      page.getByRole("button", { name: "Sign Up", exact: true }),
    ).toHaveCount(0)
    await expect(
      page.getByRole("link", { name: "Log in", exact: true }),
    ).toBeVisible()
  })
})

test("uncertain freeplay start retries the exact operation after reload", async ({
  page,
}) => {
  await page.goto("/freeplay")
  await expect(
    page.getByRole("button", { name: "Start Freeplay" }),
  ).toBeEnabled()
  const commands: Record<string, unknown>[] = []
  await page.route("**/api/v1/games/freeplay", async (route) => {
    commands.push(route.request().postDataJSON())
    if (commands.length === 1) {
      await route.fetch() // Commit on the real backend, but lose its response.
      await route.abort("timedout")
    } else await route.continue()
  })
  await page.getByRole("button", { name: "Start Freeplay" }).click()
  await expect(page.getByRole("button", { name: "Retry start" })).toBeVisible()
  await expect(page.getByLabel("Minimum year gap")).toBeDisabled()
  await page.reload()
  await page.getByRole("button", { name: "Retry start" }).click()
  await expect(page).toHaveURL(/\/play\/[\da-f-]+$/)
  expect(commands).toHaveLength(2)
  expect(commands[1]).toEqual(commands[0])
})

base(
  "daily start, resume, result and leaderboard retain the UTC day",
  async ({ page }) => {
    // A distinct owned account makes this independent of preview and other runs.
    const adminToken = await (async () => {
      await page.goto("/")
      return page.evaluate(() => localStorage.getItem("access_token"))
    })()
    const email = `modes-${crypto.randomUUID()}@example.com`
    const password = "GameBrowser123!"
    const created = await page.request.post(
      "http://localhost:8000/api/v1/users/",
      {
        headers: { Authorization: `Bearer ${adminToken}` },
        data: { email, password, full_name: "Daily modes" },
      },
    )
    expect(created.ok()).toBeTruthy()
    const login = await page.request.post(
      "http://localhost:8000/api/v1/login/access-token",
      { form: { username: email, password } },
    )
    const token = (await login.json()).access_token
    await page.evaluate(
      (value) => localStorage.setItem("access_token", value),
      token,
    )
    const headers = { Authorization: `Bearer ${token}` }
    try {
      await page.goto("/daily")
      await page.getByRole("button", { name: "Start Daily" }).click()
      await expect(page).toHaveURL(/\/play\/[\da-f-]+$/)
      const id = page.url().split("/").pop()
      const url = `http://localhost:8000/api/v1/games/runs/${id}`
      let run = await (await page.request.get(url, { headers })).json()
      await expect(
        page.getByText(`Daily · ${run.daily_date} UTC`, { exact: true }),
      ).toBeVisible()
      await page.goto("/daily")
      await expect(
        page.getByRole("link", { name: "Resume Daily" }),
      ).toBeVisible()
      // Only public commands are used; no answer data enters the browser fixture.
      while (run.status === "active") {
        const response = await page.request.post(`${url}/placements`, {
          headers,
          data: {
            operation_id: crypto.randomUUID(),
            expected_revision: run.revision,
            event_id: run.pending.event_id,
            slot: 0,
          },
        })
        expect(response.ok()).toBeTruthy()
        run = await response.json()
      }
      await page.reload()
      await expect(
        page.getByRole("link", { name: "View Result" }),
      ).toBeVisible()
      await expect(
        page.getByRole("heading", {
          name: `Leaderboard · ${run.daily_date} UTC`,
        }),
      ).toBeVisible()
      await page.getByRole("link", { name: "View Result" }).click()
      await expect(
        page.getByText(`Daily · ${run.daily_date} UTC`, { exact: true }),
      ).toBeVisible()
      await expect(
        page.getByRole("heading", {
          name: `Leaderboard · ${run.daily_date} UTC`,
        }),
      ).toBeVisible()
    } finally {
      await page.request.delete("http://localhost:8000/api/v1/users/me", {
        headers,
      })
    }
  },
)

test("freeplay defaults, sparse error, start, and owned resume", async ({
  page,
}) => {
  await page.goto("/freeplay")
  await expect(page.getByRole("heading", { name: "Freeplay" })).toBeVisible()
  await expect(page.getByLabel("Minimum year gap")).toHaveValue("1")
  for (const checkbox of await page.getByRole("checkbox").all())
    await expect(checkbox).toBeChecked()
  const calls: unknown[] = []
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      request.url().endsWith("/games/freeplay")
    )
      calls.push(request.postDataJSON())
  })
  await page.getByLabel("Minimum year gap").fill("9999")
  const token = await page.evaluate(() => localStorage.getItem("access_token"))
  const headers = { Authorization: `Bearer ${token}` }
  const activeURL = "http://localhost:8000/api/v1/games/active-runs"
  const before = await (await page.request.get(activeURL, { headers })).json()
  const failedStart = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/games/freeplay"),
  )
  await page.getByRole("button", { name: "Start Freeplay" }).click()
  const response = await failedStart
  expect(response.status()).toBe(422)
  await expect(page.getByRole("alert")).toHaveText(
    (await response.json()).detail.message,
  )
  expect(await (await page.request.get(activeURL, { headers })).json()).toEqual(
    before,
  )
  expect(calls).toHaveLength(1)
  await page.getByLabel("Minimum year gap").fill("1")
  await page.getByRole("button", { name: "Start Freeplay" }).click()
  await expect(page).toHaveURL(/\/play\/[\da-f-]+$/)
  await expect(
    page.getByRole("heading", { name: "Freeplay run" }),
  ).toBeVisible()
  await expect(page.getByRole("heading", { name: "Next card" })).toBeVisible()
  const url = page.url()
  await page.goto("/")
  await page
    .getByRole("link", {
      name: new RegExp(`Resume Freeplay.*${url.split("/").pop()?.slice(0, 8)}`),
    })
    .click()
  await expect(page).toHaveURL(url)
})
