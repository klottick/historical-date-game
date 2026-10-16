import { isAxiosError } from "axios"
import type { GameSessionPublic } from "../../client/types.gen.ts"

export function accountToken() {
  try {
    return localStorage.getItem("access_token") || ""
  } catch {
    return ""
  }
}
export function notifyAccountChange() {
  window.dispatchEvent(new Event("game-account-change"))
}
export function subscribeAccountChange(callback: () => void) {
  const timer = window.setInterval(callback, 50)
  window.addEventListener("storage", callback)
  window.addEventListener("game-account-change", callback)
  return () => {
    clearInterval(timer)
    window.removeEventListener("storage", callback)
    window.removeEventListener("game-account-change", callback)
  }
}

export function gameRequestOptions(context: GameSessionPublic): {
  withCredentials: true
  headers: Record<string, string>
} {
  return {
    withCredentials: true,
    headers: { "X-Game-Request": "1", "X-Game-Context": context.context_id },
  }
}

export function startStorageKey(contextId: string, mode: "daily" | "freeplay") {
  return `game:v2:${encodeURIComponent(contextId)}:start:${mode}`
}

export function placementStorageKey(contextId: string, runId: string) {
  return `game:v2:${encodeURIComponent(contextId)}:placement:${encodeURIComponent(runId)}`
}

export function gameQueryKey(contextId: string, resource: string, id?: string) {
  return id === undefined
    ? ["game", 2, contextId, resource]
    : ["game", 2, contextId, resource, id]
}

export function sessionError(code: string, message: string) {
  return Object.assign(new Error(message), { code })
}

export function storageUnavailable() {
  return sessionError(
    "guest_storage_unavailable",
    "Browser storage or cookies are unavailable. Enable them and retry session setup.",
  )
}

export function sessionFailure(
  error: unknown,
):
  | "missing"
  | "expired"
  | "invalid"
  | "identity_changed"
  | "origin"
  | "storage"
  | null {
  let code: unknown
  let status: number | undefined
  if (isAxiosError(error)) {
    status = error.response?.status
    const detail: unknown = error.response?.data?.detail
    if (detail && typeof detail === "object" && "code" in detail)
      code = detail.code
  } else if (error && typeof error === "object" && "code" in error) {
    code = error.code
  }
  switch (code) {
    case "game_session_required":
      return "missing"
    case "game_session_expired":
      return "expired"
    case "game_session_invalid":
    case "invalid_account":
      return "invalid"
    case "game_identity_changed":
      return "identity_changed"
    case "game_request_rejected":
      return "origin"
    case "guest_storage_unavailable":
      return "storage"
  }
  if (
    status === 409 &&
    (typeof code !== "string" || /^(game_session_|game_identity_)/.test(code))
  )
    return "invalid"
  // Existing account OAuth errors are unstructured; malformed auth responses
  // must still retain unresolved commands, never become a historical loss.
  return status === 401 || status === 403 ? "invalid" : null
}
