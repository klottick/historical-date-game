import { client } from "../../client/client.gen.ts"
import { GamesService } from "../../client/sdk.gen.ts"
import type { GameSessionPublic } from "../../client/types.gen.ts"
import { withBootstrapLock } from "./bootstrapLock.ts"
import {
  hasCompatibleGameProtocol,
  protocolUpgradeError,
} from "./gameProtocol.ts"
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
type AttemptMode = Mode | "retry"
type Flight = {
  controller: AbortController
  promise: Promise<GameSessionPublic>
  subscribers: number
}
const flights = new Map<string, Flight>()
// Availability state only: no credential, context, or account metadata. This is
// not a lock/lease; every read/write below occurs inside the IndexedDB writer.
const guestRejectionKey = "game-guest-cookie-rejected"
const guestStorageProbeKey = "game-guest-storage-probe"

function guestCookieRejected(): boolean {
  try {
    const storage = window.localStorage
    const rejected = storage.getItem(guestRejectionKey) === "1"
    // Readable storage can still have writes disabled or exhausted quota. Prove
    // that a rejection can be persisted before issuing an allocating request.
    storage.setItem(guestStorageProbeKey, "1")
    storage.removeItem(guestStorageProbeKey)
    return rejected
  } catch {
    throw storageUnavailable()
  }
}

function recordGuestRejection() {
  try {
    window.localStorage.setItem(guestRejectionKey, "1")
  } catch {
    throw storageUnavailable()
  }
}

function clearGuestRejection() {
  try {
    window.localStorage.removeItem(guestRejectionKey)
  } catch {
    throw storageUnavailable()
  }
}

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
    !hasCompatibleGameProtocol(value) ||
    typeof value.context_id !== "string" ||
    !value.context_id.trim()
  ) {
    throw sessionError(
      hasCompatibleGameProtocol(value)
        ? "game_session_invalid"
        : "game_protocol_incompatible",
      hasCompatibleGameProtocol(value)
        ? "Invalid session response; retry session setup"
        : protocolUpgradeError().message,
    )
  }
  return { kind: value.kind, context_id: value.context_id, protocol_version: 2 }
}

async function runSession(
  mode: AttemptMode,
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
    // Guest continuation must be a separate deliberate sign-out decision by
    // the caller, never an implicit fallback from an account bearer.
    if (mode === "retry" && auth) throw changed()
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
            mode === "inspect" ||
            auth ||
            !["missing", "expired"].includes(sessionFailure(error) ?? "")
          )
            throw error
        }
        await assertAuth()
        if (mode === "inspect") {
          if (before!.kind === "guest") clearGuestRejection()
          return before!
        }
        if (!auth) {
          const rejected = guestCookieRejected()
          if (before?.kind === "guest") {
            // A successful guest inspection proves cookie acceptance. Account
            // responses must never erase this origin-wide guest failure state.
            clearGuestRejection()
          } else if (rejected && mode !== "retry") {
            throw storageUnavailable()
          }
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
            // An aborted/stale callback must not publish a rejection after its
            // lock was released or overwrite another tab's successful recovery.
            await assertAuth()
            recordGuestRejection()
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
        if (confirmed.kind === "guest") clearGuestRejection()
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

async function joinSession(
  mode: AttemptMode,
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

export function ensureGameSession(
  mode: Mode,
  signal?: AbortSignal,
): Promise<GameSessionPublic> {
  return joinSession(mode, signal)
}

/** Call only from a deliberate Retry/New-play user action, not an effect, query
 * retry, or unresolved-command replay. Does not sign out or transfer commands.
 * An explicit guest-only flight may retry despite the rejection flag, under the
 * same native lock. The flag stays set until guest-cookie confirmation succeeds,
 * so cancellation, transport failure, or another rejection cannot silently
 * re-enable automatic allocation. Never nests a second bootstrap lock.
 */
export function retryGuestBootstrap(
  signal?: AbortSignal,
): Promise<GameSessionPublic> {
  return joinSession("retry", signal)
}
