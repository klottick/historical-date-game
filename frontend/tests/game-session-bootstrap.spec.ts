import { createServer, type ServerResponse } from "node:http"
import { test as base, expect, type Page } from "@playwright/test"
import type * as Bootstrap from "../src/features/game/sessionBootstrap.ts"

type Outcome = {
  context_id?: string
  kind?: string
  failure?: string | null
  name?: string
}
declare global {
  interface Window {
    bootstrap: typeof Bootstrap
    outcomes: Outcome[]
    cancel: AbortController
  }
}

function gate() {
  let release!: () => void
  const promise = new Promise<void>((resolve) => {
    release = resolve
  })
  return { promise, release }
}

type RequestRecord = {
  method: string
  auth?: string
  cookie?: string
  guard?: string
  context?: string
  aborted: boolean
}
class SessionServer {
  requests: RequestRecord[] = []
  allocations = 0
  mutations = 0
  rejectCookie = false
  failPost = false
  mismatch = false
  malformed = false
  postGate: ReturnType<typeof gate> | null = null
  confirmationGate: ReturnType<typeof gate> | null = null
  url = ""
  server = createServer(async (request, response) => {
    response.setHeader("Access-Control-Allow-Origin", "http://127.0.0.1:5194")
    response.setHeader("Access-Control-Allow-Credentials", "true")
    response.setHeader(
      "Access-Control-Allow-Headers",
      "Authorization, X-Game-Request, X-Game-Context",
    )
    response.setHeader("Access-Control-Allow-Methods", "GET, POST")
    if (request.method === "OPTIONS") {
      response.writeHead(204).end()
      return
    }
    const record: RequestRecord = {
      method: request.method ?? "",
      auth: request.headers.authorization,
      cookie: request.headers.cookie,
      guard: request.headers["x-game-request"] as string | undefined,
      context: request.headers["x-game-context"] as string | undefined,
      aborted: false,
    }
    this.requests.push(record)
    response.on("close", () => {
      if (!response.writableEnded) record.aborted = true
    })
    if (request.url !== "/api/v1/games/session") {
      this.mutations++
      this.json(response, 500, {})
      return
    }
    const account =
      record.auth === "Bearer account-one" ||
      record.auth === "Bearer account-two"
    if (record.auth && !account) {
      this.json(response, 403, { detail: "Could not validate credentials" })
      return
    }
    const cookie = /bootstrap_test=(\d+)/.exec(record.cookie ?? "")?.[1]
    let context = account
      ? `a:${record.auth?.slice(7)}`
      : cookie
        ? `g:${cookie}`
        : null
    if (request.method === "POST") {
      if (record.guard !== "1") {
        this.json(response, 403, { detail: { code: "game_request_rejected" } })
        return
      }
      if (!context) {
        this.allocations++
        context = `g:${this.allocations}`
      }
      if (this.postGate) await this.postGate.promise
      if (response.destroyed) return
      if (this.failPost) {
        this.json(response, 503, { detail: { code: "unavailable" } })
        return
      }
      if (!account)
        response.setHeader(
          "Set-Cookie",
          `bootstrap_test=${context.slice(2)}; HttpOnly; SameSite=Lax; Path=/api/v1/games${this.rejectCookie ? "; Domain=example.invalid" : ""}`,
        )
    } else if (cookie && this.confirmationGate) {
      await this.confirmationGate.promise
    }
    if (response.destroyed) return
    if (!context) {
      this.json(response, 401, {
        detail: { code: "game_session_required", message: "Retry session" },
      })
      return
    }
    this.json(
      response,
      200,
      this.malformed
        ? {}
        : {
            kind: account ? "account" : "guest",
            context_id:
              this.mismatch && request.method === "GET"
                ? "g:different"
                : context,
          },
    )
  })
  json(response: ServerResponse, status: number, body: unknown) {
    response
      .writeHead(status, {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
        Vary: "Cookie, Authorization",
      })
      .end(JSON.stringify(body))
  }
  async start() {
    await new Promise<void>((resolve) =>
      this.server.listen(0, "127.0.0.1", resolve),
    )
    const address = this.server.address()
    if (!address || typeof address === "string")
      throw new Error("Expected loopback TCP server")
    this.url = `http://127.0.0.1:${address.port}`
  }
  async stop() {
    this.postGate?.release()
    this.confirmationGate?.release()
    this.server.closeAllConnections()
    await new Promise<void>((resolve) => this.server.close(() => resolve()))
  }
}

const test = base.extend<{ api: SessionServer }>({
  // biome-ignore lint/correctness/noEmptyPattern: Playwright requires destructured fixture arguments even without dependencies.
  api: async ({}, use) => {
    const api = new SessionServer()
    await api.start()
    try {
      await use(api)
    } finally {
      await api.stop()
    }
  },
})

async function load(page: Page, api: SessionServer) {
  await page.goto("/tests/fixtures/bootstrap.html")
  await page.evaluate(async (url) => {
    const sdkPath = "/src/client/client.gen.ts"
    const bootstrapPath = "/src/features/game/sessionBootstrap.ts"
    const { client } = await import(sdkPath)
    client.setConfig({ baseURL: url }) // Deliberately no main.tsx or auth callback.
    window.bootstrap = await import(bootstrapPath)
    window.outcomes = []
    window.cancel = new AbortController()
  }, api.url)
}

async function begin(
  page: Page,
  mode: "bootstrap" | "inspect" = "bootstrap",
  count = 1,
) {
  await page.evaluate(
    ({ mode, count }) => {
      for (let i = 0; i < count; i++) {
        window.bootstrap.ensureGameSession(mode, window.cancel.signal).then(
          (result) => window.outcomes.push(result),
          (error) =>
            window.outcomes.push({
              failure: window.bootstrap.sessionFailure(error),
              name: error.name,
            }),
        )
      }
    },
    { mode, count },
  )
}

async function retryGuest(page: Page) {
  await page.evaluate(() => {
    window.bootstrap.retryGuestBootstrap(window.cancel.signal).then(
      (result) => window.outcomes.push(result),
      (error) =>
        window.outcomes.push({
          failure: window.bootstrap.sessionFailure(error),
          name: error.name,
        }),
    )
  })
}
async function outcomes(page: Page, count = 1) {
  await expect
    .poll(() => page.evaluate(() => window.outcomes.length))
    .toBe(count)
  return page.evaluate(() => window.outcomes)
}

test("cold_tabs_share_confirmed_identity", async ({ context, page, api }) => {
  const other = await context.newPage()
  await load(page, api)
  await load(other, api)
  api.postGate = gate()
  api.confirmationGate = gate()
  await begin(page, "bootstrap", 2)
  await expect.poll(() => api.allocations).toBe(1)
  await begin(other)
  await other.waitForTimeout(150)
  expect(api.requests.map((r) => r.method)).toEqual(["GET", "POST"])
  expect(await page.evaluate(() => window.outcomes)).toEqual([])
  api.postGate.release()
  await expect.poll(() => api.requests.length).toBe(3)
  expect(await page.evaluate(() => window.outcomes)).toEqual([])
  expect(await other.evaluate(() => window.outcomes)).toEqual([])
  api.confirmationGate.release()
  expect(await outcomes(page, 2)).toEqual([
    { kind: "guest", context_id: "g:1" },
    { kind: "guest", context_id: "g:1" },
  ])
  expect(await outcomes(other)).toEqual([{ kind: "guest", context_id: "g:1" }])
  expect(api.allocations).toBe(1)
  expect(api.mutations).toBe(0)
  expect(
    api.requests
      .filter((r) => r.method === "POST")
      .every((r) => r.guard === "1"),
  ).toBe(true)
  // The only durable coordination value must not contain identity or credentials.
  expect(
    await page.evaluate(async () => {
      const databases = await indexedDB.databases()
      const name = databases[0]?.name
      if (!name) return []
      return new Promise((resolve, reject) => {
        const open = indexedDB.open(name)
        open.onerror = () => reject(open.error)
        open.onsuccess = () => {
          const db = open.result
          const tx = db.transaction(db.objectStoreNames[0], "readonly")
          const request = tx.objectStore(db.objectStoreNames[0]).getAll()
          request.onsuccess = () => resolve(request.result)
          tx.oncomplete = () => db.close()
        }
      })
    }),
  ).toEqual([1])
})

test("rejected_cookie_stops_bootstrap", async ({ context, page, api }) => {
  api.rejectCookie = true
  api.postGate = gate()
  await load(page, api)
  const other = await context.newPage()
  await load(other, api)
  await begin(page)
  await expect.poll(() => api.allocations).toBe(1)
  await begin(other)
  api.postGate.release()
  expect((await outcomes(page))[0].failure).toBe("storage")
  expect((await outcomes(other))[0].failure).toBe("storage")
  expect(api.allocations).toBe(1)
  expect(
    await page.evaluate(() =>
      localStorage.getItem("game-guest-cookie-rejected"),
    ),
  ).toBe("1")
  expect(await page.evaluate(() => Object.entries(localStorage))).toEqual([
    ["game-guest-cookie-rejected", "1"],
  ])
  await begin(page)
  expect((await outcomes(page, 2))[1].failure).toBe("storage")
  await load(page, api) // Reload destroys module memory, not the origin flag.
  await begin(page)
  expect((await outcomes(page))[0].failure).toBe("storage")
  expect(api.allocations).toBe(1)
  expect(api.requests.filter((r) => r.method === "POST")).toHaveLength(1)
  expect(api.mutations).toBe(0)
})

test("successful_guest_inspection_clears_rejection_without_allocating", async ({
  context,
  page,
  api,
}) => {
  api.rejectCookie = true
  await load(page, api)
  await begin(page)
  expect((await outcomes(page))[0].failure).toBe("storage")
  expect(
    await page.evaluate(() =>
      localStorage.getItem("game-guest-cookie-rejected"),
    ),
  ).toBe("1")
  await context.addCookies([
    {
      name: "bootstrap_test",
      value: "1",
      domain: "127.0.0.1",
      path: "/api/v1/games",
      httpOnly: true,
      sameSite: "Lax",
    },
  ])
  await begin(page, "inspect")
  expect((await outcomes(page, 2))[1]).toEqual({
    kind: "guest",
    context_id: "g:1",
  })
  expect(
    await page.evaluate(() =>
      localStorage.getItem("game-guest-cookie-rejected"),
    ),
  ).toBeNull()
  expect(api.allocations).toBe(1)
  expect(api.requests.filter((r) => r.method === "POST")).toHaveLength(1)
})

test("account_inspection_and_bootstrap_do_not_clear_guest_rejection", async ({
  page,
  api,
}) => {
  api.rejectCookie = true
  await load(page, api)
  await begin(page)
  expect((await outcomes(page))[0].failure).toBe("storage")
  await page.evaluate(() => localStorage.setItem("access_token", "account-one"))
  await begin(page, "inspect")
  expect((await outcomes(page, 2))[1].kind).toBe("account")
  await begin(page)
  expect((await outcomes(page, 3))[2].kind).toBe("account")
  expect(
    await page.evaluate(() =>
      localStorage.getItem("game-guest-cookie-rejected"),
    ),
  ).toBe("1")
  await page.evaluate(() => localStorage.removeItem("access_token"))
  await begin(page)
  expect((await outcomes(page, 4))[3].failure).toBe("storage")
  expect(api.allocations).toBe(1)
})

test("explicit_guest_retry_confirms_cookie_and_does_not_join_automatic_flight", async ({
  page,
  api,
}) => {
  api.rejectCookie = true
  await load(page, api)
  await begin(page)
  expect((await outcomes(page))[0].failure).toBe("storage")
  api.rejectCookie = false
  api.postGate = gate()
  await begin(page)
  await retryGuest(page)
  await expect.poll(() => api.allocations).toBe(2)
  expect((await outcomes(page, 2))[1].failure).toBe("storage")
  expect(
    await page.evaluate(() =>
      localStorage.getItem("game-guest-cookie-rejected"),
    ),
  ).toBe("1")
  api.postGate.release()
  expect((await outcomes(page, 3))[2]).toEqual({
    kind: "guest",
    context_id: "g:2",
  })
  expect(
    await page.evaluate(() =>
      localStorage.getItem("game-guest-cookie-rejected"),
    ),
  ).toBeNull()
  expect(await page.evaluate(() => localStorage.length)).toBe(0)
  expect(api.mutations).toBe(0)
})

test("aborted_explicit_retry_keeps_rejection_and_cannot_write_after_unlock", async ({
  context,
  page,
  api,
}) => {
  api.rejectCookie = true
  await load(page, api)
  await begin(page)
  expect((await outcomes(page))[0].failure).toBe("storage")
  api.postGate = gate()
  await retryGuest(page)
  await expect.poll(() => api.allocations).toBe(2)
  await page.evaluate(() => window.cancel.abort())
  expect((await outcomes(page, 2))[1].context_id).toBeUndefined()
  await expect
    .poll(
      () =>
        [...api.requests].reverse().find((r) => r.method === "POST")?.aborted,
    )
    .toBe(true)
  expect(
    await page.evaluate(() =>
      localStorage.getItem("game-guest-cookie-rejected"),
    ),
  ).toBe("1")
  const other = await context.newPage()
  await load(other, api)
  api.rejectCookie = false
  api.postGate.release()
  await retryGuest(other)
  expect((await outcomes(other))[0]).toEqual({
    kind: "guest",
    context_id: "g:3",
  })
  expect(
    await other.evaluate(() =>
      localStorage.getItem("game-guest-cookie-rejected"),
    ),
  ).toBeNull()
  await begin(other)
  expect((await outcomes(other, 2))[1].context_id).toBe("g:3")
  expect(api.allocations).toBe(3)
})

test("guest_flag_storage_access_failure_stops_before_post", async ({
  page,
  api,
}) => {
  await load(page, api)
  await page.evaluate(async () => {
    const sdkPath = "/src/client/client.gen.ts"
    const { client } = await import(sdkPath)
    client.setConfig({ auth: "" }) // Isolate flag access from account storage.
    Object.defineProperty(window, "localStorage", {
      get: () => {
        throw new DOMException("Denied", "SecurityError")
      },
    })
  })
  await begin(page)
  expect((await outcomes(page))[0].failure).toBe("storage")
  expect(api.requests.map((r) => r.method)).toEqual(["GET"])
  expect(api.allocations).toBe(0)
})

test("guest_flag_storage_write_failure_stops_before_post", async ({
  page,
  api,
}) => {
  await load(page, api)
  await page.evaluate(() => {
    Storage.prototype.setItem = () => {
      throw new DOMException("Quota", "QuotaExceededError")
    }
  })
  await begin(page)
  expect((await outcomes(page))[0].failure).toBe("storage")
  expect(api.requests.map((r) => r.method)).toEqual(["GET"])
  expect(api.allocations).toBe(0)
})

test("explicit_guest_retry_does_not_clear_flag_for_signed_in_account", async ({
  page,
  api,
}) => {
  await load(page, api)
  await page.evaluate(() => {
    localStorage.setItem("game-guest-cookie-rejected", "1")
    localStorage.setItem("access_token", "account-one")
  })
  await retryGuest(page)
  expect((await outcomes(page))[0].failure).toBe("identity_changed")
  expect(
    await page.evaluate(() =>
      localStorage.getItem("game-guest-cookie-rejected"),
    ),
  ).toBe("1")
  expect(api.requests).toEqual([])
})

test("inspection_never_allocates", async ({ page, api }) => {
  await load(page, api)
  await begin(page, "inspect", 2)
  expect((await outcomes(page, 2)).map((o) => o.failure)).toEqual([
    "missing",
    "missing",
  ])
  expect(api.requests.map((r) => r.method)).toEqual(["GET"])
  expect(api.allocations).toBe(0)
})

test("closed_tab_releases_coordination", async ({ context, page, api }) => {
  await load(page, api)
  api.postGate = gate()
  await begin(page)
  await expect.poll(() => api.allocations).toBe(1)
  const other = await context.newPage()
  await load(other, api)
  await begin(other)
  await other.waitForTimeout(100)
  expect(api.allocations).toBe(1)
  await page.close()
  await expect.poll(() => api.requests[1].aborted).toBe(true)
  api.postGate.release()
  expect(await outcomes(other)).toEqual([{ kind: "guest", context_id: "g:2" }])
  expect(api.requests[1].aborted).toBe(true)
  expect(api.mutations).toBe(0)
})

test("abort_cancels_transport_and_releases_lock", async ({
  context,
  page,
  api,
}) => {
  await load(page, api)
  api.postGate = gate()
  await begin(page)
  await expect.poll(() => api.allocations).toBe(1)
  await page.evaluate(() => window.cancel.abort())
  expect((await outcomes(page))[0].context_id).toBeUndefined()
  await expect.poll(() => api.requests[1].aborted).toBe(true)
  const other = await context.newPage()
  await load(other, api)
  api.postGate.release()
  await begin(other)
  expect((await outcomes(other))[0].context_id).toBe("g:2")
})

test("transport_is_bounded_and_late_response_cannot_confirm", async ({
  context,
  page,
  api,
}) => {
  await load(page, api)
  api.postGate = gate()
  const started = Date.now()
  await begin(page)
  await expect
    .poll(() => page.evaluate(() => window.outcomes.length), {
      timeout: 18_000,
    })
    .toBe(1)
  expect(Date.now() - started).toBeGreaterThan(14_000)
  expect(Date.now() - started).toBeLessThan(18_000)
  expect((await outcomes(page))[0].context_id).toBeUndefined()
  await expect.poll(() => api.requests[1].aborted).toBe(true)
  api.postGate.release()
  const other = await context.newPage()
  await load(other, api)
  await begin(other)
  expect((await outcomes(other))[0].context_id).toBe("g:2")
})

test("failed_request_releases_coordination_for_retry", async ({
  page,
  api,
}) => {
  api.failPost = true
  await load(page, api)
  await begin(page)
  expect((await outcomes(page))[0]).toMatchObject({ failure: null })
  api.failPost = false
  await begin(page)
  expect((await outcomes(page, 2))[1].context_id).toBe("g:2")
  expect(api.mutations).toBe(0)
})

test("unavailable_indexeddb_fails_closed_before_http", async ({
  page,
  api,
}) => {
  await page.goto("/tests/fixtures/bootstrap.html")
  await page.evaluate(() => {
    const iframe = document.createElement("iframe")
    iframe.name = "storage-denied"
    iframe.sandbox.add("allow-scripts")
    iframe.src = "/tests/fixtures/bootstrap.html"
    document.body.append(iframe)
  })
  await expect
    .poll(() => page.frame({ name: "storage-denied" })?.url())
    .toContain("bootstrap.html")
  const sandbox = page.frame({ name: "storage-denied" })!
  // Chromium itself denies storage in an opaque origin, without a fake IDB API.
  expect(
    await sandbox.evaluate(() => {
      try {
        indexedDB.open("native-storage-denial-probe")
        return "accessible"
      } catch (error) {
        return (error as Error).name
      }
    }),
  ).toBe("SecurityError")
  expect(
    await sandbox.evaluate(async (url) => {
      const sdkPath = "http://127.0.0.1:5194/src/client/client.gen.ts"
      const bootstrapPath =
        "http://127.0.0.1:5194/src/features/game/sessionBootstrap.ts"
      const { client } = await import(sdkPath)
      client.setConfig({ baseURL: url, auth: "" })
      const bootstrap = await import(bootstrapPath)
      try {
        await bootstrap.ensureGameSession("bootstrap")
        return "ready"
      } catch (error) {
        return bootstrap.sessionFailure(error)
      }
    }, api.url),
  ).toBe("storage")
  expect(api.requests).toEqual([])
  expect(api.allocations).toBe(0)
})

test("account_bearer_switch_aborts_without_reusing_old_flight", async ({
  page,
  api,
}) => {
  await load(page, api)
  await page.evaluate(() => localStorage.setItem("access_token", "account-one"))
  api.postGate = gate()
  await begin(page)
  await expect.poll(() => api.requests.length).toBe(2)
  expect(api.requests.every((r) => r.auth === "Bearer account-one")).toBe(true)
  await page.evaluate(() => localStorage.setItem("access_token", "account-two"))
  expect((await outcomes(page))[0].failure).toBe("identity_changed")
  await expect.poll(() => api.requests[1].aborted).toBe(true)
  api.postGate.release()
  await begin(page)
  expect((await outcomes(page, 2))[1]).toEqual({
    kind: "account",
    context_id: "a:account-two",
  })
  expect(api.allocations).toBe(0)
  expect(
    api.requests.slice(2).every((r) => r.auth === "Bearer account-two"),
  ).toBe(true)
  await page.evaluate(() => localStorage.removeItem("access_token"))
  await begin(page)
  expect((await outcomes(page, 3))[2]).toEqual({
    kind: "guest",
    context_id: "g:1",
  })
})

test("configured_auth_callback_is_honored_and_invalid_bearer_never_allocates", async ({
  page,
  api,
}) => {
  await load(page, api)
  await page.evaluate(async () => {
    const sdkPath = "/src/client/client.gen.ts"
    const { client } = await import(sdkPath)
    client.setConfig({ auth: () => localStorage.getItem("access_token") || "" })
    localStorage.setItem("access_token", "invalid-token")
  })
  await begin(page)
  expect((await outcomes(page))[0].failure).toBe("invalid")
  expect(api.requests.map((r) => r.method)).toEqual(["GET"])
  expect(api.requests[0].auth).toBe("Bearer invalid-token")
  expect(api.allocations).toBe(0)
})

test("confirmation_mismatch_or_malformed_identity_never_becomes_ready", async ({
  page,
  api,
}) => {
  await load(page, api)
  api.mismatch = true
  await begin(page)
  expect((await outcomes(page))[0].failure).toBe("identity_changed")
  api.mismatch = false
  api.malformed = true
  await begin(page)
  expect((await outcomes(page, 2))[1].failure).toBe("invalid")
  expect(api.mutations).toBe(0)
})

test("abort_while_waiting_never_enters_http_callback", async ({
  context,
  page,
  api,
}) => {
  await load(page, api)
  api.postGate = gate()
  await begin(page)
  await expect.poll(() => api.requests.length).toBe(2)
  const other = await context.newPage()
  await load(other, api)
  await begin(other)
  await other.evaluate(() => window.cancel.abort())
  expect((await outcomes(other))[0].context_id).toBeUndefined()
  api.postGate.release()
  expect((await outcomes(page))[0].context_id).toBe("g:1")
  expect(api.requests.map((r) => r.method)).toEqual(["GET", "POST", "GET"])
})

test("one_cancelled_subscriber_does_not_abort_another", async ({
  page,
  api,
}) => {
  await load(page, api)
  api.postGate = gate()
  await begin(page)
  await page.evaluate(() => {
    window.bootstrap
      .ensureGameSession("bootstrap")
      .then((result) => window.outcomes.push(result))
  })
  await expect.poll(() => api.allocations).toBe(1)
  await page.evaluate(() => window.cancel.abort())
  api.postGate.release()
  const results = await outcomes(page, 2)
  expect(results[0].context_id).toBeUndefined()
  expect(results[1]).toEqual({ kind: "guest", context_id: "g:1" })
  expect(api.requests[1].aborted).toBe(false)
})

test("auth_change_during_confirmation_rejects_old_context", async ({
  context,
  page,
  api,
}) => {
  await load(page, api)
  api.confirmationGate = gate()
  await begin(page)
  await expect.poll(() => api.requests.length).toBe(3)
  const other = await context.newPage()
  await other.goto("/tests/fixtures/bootstrap.html")
  await other.evaluate(() =>
    localStorage.setItem("access_token", "account-one"),
  )
  expect((await outcomes(page))[0].failure).toBe("identity_changed")
  await expect.poll(() => api.requests[2].aborted).toBe(true)
  api.confirmationGate.release()
  await begin(page)
  expect((await outcomes(page, 2))[1]).toEqual({
    kind: "account",
    context_id: "a:account-one",
  })
})

test("configured_auth_source_takes_precedence_over_fallback", async ({
  page,
  api,
}) => {
  await load(page, api)
  await page.evaluate(async () => {
    const sdkPath = "/src/client/client.gen.ts"
    const { client } = await import(sdkPath)
    client.setConfig({ auth: () => "account-one" })
    localStorage.setItem("access_token", "invalid-token")
  })
  await begin(page)
  expect((await outcomes(page))[0]).toEqual({
    kind: "account",
    context_id: "a:account-one",
  })
  expect(api.requests.every((r) => r.auth === "Bearer account-one")).toBe(true)
  expect(api.allocations).toBe(0)
})
