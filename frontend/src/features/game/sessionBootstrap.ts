import { client } from "../../client/client.gen.ts"
import { GamesService } from "../../client/sdk.gen.ts"
import type { GameSessionPublic } from "../../client/types.gen.ts"
import { withBootstrapLock } from "./bootstrapLock.ts"
import {
  sessionError,
  sessionFailure,
  storageUnavailable,
} from "./identityState.ts"

export {
  gameQueryKey,
  gameRequestOptions,
  placementStorageKey,
  sessionFailure,
  startStorageKey,
} from "./identityState.ts"

type Mode = "bootstrap" | "inspect"
type Flight = {
  controller: AbortController
  promise: Promise<GameSessionPublic>
  subscribers: number
}
const flights = new Map<string, Flight>()
// Do not automatically issue another allocation after a failed cookie check.
// A successful non-allocating inspection can recover after cookies are enabled.
const rejectedCookies = new Set<string>()

async function accountAuth(): Promise<string> {
  try {
    const configured = client.getConfig().auth
    if (configured !== undefined) {
      return (
        (typeof configured === "function"
          ? await configured({ scheme: "bearer", type: "http" })
          : configured) || ""
      )
    }
    // These modules also run without main.tsx. Its callback uses this same source.
    return localStorage.getItem("access_token") || ""
  } catch {
    throw storageUnavailable()
  }
}

function validContext(value: GameSessionPublic): GameSessionPublic {
  if (
    !value ||
    !["guest", "account"].includes(value.kind) ||
    typeof value.context_id !== "string" ||
    !value.context_id.trim()
  ) {
    throw sessionError(
      "game_session_invalid",
      "Invalid session response; retry session setup",
    )
  }
  return { kind: value.kind, context_id: value.context_id }
}

async function runSession(
  mode: Mode,
  auth: string,
  controller: AbortController,
) {
  const changed = () =>
    sessionError(
      "game_identity_changed",
      "Account identity changed; retry session setup",
    )
  const assertAuth = async () => {
    if (auth !== (await accountAuth())) controller.abort(changed())
    if (controller.signal.aborted) throw controller.signal.reason
  }
  let checking = false
  const check = () => {
    if (checking || controller.signal.aborted) return
    checking = true
    assertAuth()
      .catch((error) => controller.abort(error))
      .finally(() => {
        checking = false
      })
  }
  const interval = setInterval(check, 25)
  const timeout = setTimeout(
    () =>
      controller.abort(
        new DOMException("Session setup timed out; retry", "TimeoutError"),
      ),
    15_000,
  )
  const closed = () =>
    controller.abort(new DOMException("Tab closed", "AbortError"))
  window.addEventListener("storage", check)
  window.addEventListener("pagehide", closed, { once: true })
  const options = {
    auth,
    withCredentials: true as const,
    timeout: 15_000,
    signal: controller.signal,
    throwOnError: true as const,
    headers: { "X-Game-Request": "1" },
  }
  const inspect = async () => {
    await assertAuth()
    const result = validContext(
      (await GamesService.readGameSession(options)).data,
    )
    await assertAuth()
    return result
  }
  try {
    if (mode === "inspect") {
      const context = await inspect()
      rejectedCookies.delete(auth)
      return context
    }
    if (rejectedCookies.has(auth)) throw storageUnavailable()
    return await withBootstrapLock(async (lockSignal) => {
      const lockAborted = () => controller.abort(lockSignal.reason)
      lockSignal.addEventListener("abort", lockAborted, { once: true })
      try {
        await assertAuth()
        let before: GameSessionPublic | undefined
        try {
          before = await inspect()
        } catch (error) {
          // Only a structured missing/expired guest session permits POST.
          // An explicit invalid account bearer never falls through to a guest.
          if (
            auth ||
            !["missing", "expired"].includes(sessionFailure(error) ?? "")
          )
            throw error
        }
        await assertAuth()
        const created = validContext(
          (await GamesService.bootstrapGameSession(options)).data,
        )
        await assertAuth()
        let confirmed: GameSessionPublic
        try {
          confirmed = await inspect()
        } catch (error) {
          if (
            !auth &&
            ["missing", "expired", "invalid"].includes(
              sessionFailure(error) ?? "",
            )
          ) {
            rejectedCookies.add(auth)
            throw storageUnavailable()
          }
          throw error
        }
        if (
          created.kind !== confirmed.kind ||
          created.context_id !== confirmed.context_id ||
          (before &&
            (before.kind !== confirmed.kind ||
              before.context_id !== confirmed.context_id))
        )
          throw changed()
        await assertAuth()
        return confirmed
      } finally {
        lockSignal.removeEventListener("abort", lockAborted)
      }
    }, controller.signal)
  } catch (error) {
    throw controller.signal.aborted ? controller.signal.reason : error
  } finally {
    clearInterval(interval)
    clearTimeout(timeout)
    window.removeEventListener("storage", check)
    window.removeEventListener("pagehide", closed)
  }
}

export async function ensureGameSession(
  mode: Mode,
  signal?: AbortSignal,
): Promise<GameSessionPublic> {
  if (signal?.aborted) throw signal.reason
  const auth = await accountAuth()
  if (signal?.aborted) throw signal.reason
  const key = JSON.stringify([mode, auth])
  let flight = flights.get(key)
  if (!flight || flight.controller.signal.aborted) {
    const controller = new AbortController()
    flight = {
      controller,
      subscribers: 0,
      promise: runSession(mode, auth, controller),
    }
    const current = flight
    flights.set(key, current)
    current.promise.then(
      () => {
        if (flights.get(key) === current) flights.delete(key)
      },
      () => {
        if (flights.get(key) === current) flights.delete(key)
      },
    )
  }
  const current = flight
  current.subscribers++
  return new Promise((resolve, reject) => {
    let settled = false
    const settle = (action: () => void) => {
      if (settled) return
      settled = true
      signal?.removeEventListener("abort", aborted)
      current.subscribers--
      action()
    }
    const aborted = () =>
      settle(() => {
        if (current.subscribers === 0) current.controller.abort(signal?.reason)
        reject(signal?.reason)
      })
    signal?.addEventListener("abort", aborted, { once: true })
    if (signal?.aborted) aborted()
    current.promise.then(
      (value) => settle(() => resolve(value)),
      (error) => settle(() => reject(error)),
    )
  })
}
