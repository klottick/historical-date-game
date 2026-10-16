export const GAME_PROTOCOL_VERSION = 2 as const

export const protocolUpgradeMessage =
  "Game updated. Refresh and start a new game." as const

export function hasCompatibleGameProtocol(value: unknown): value is {
  protocol_version: typeof GAME_PROTOCOL_VERSION
} {
  return (
    typeof value === "object" &&
    value !== null &&
    "protocol_version" in value &&
    value.protocol_version === GAME_PROTOCOL_VERSION
  )
}

export function protocolUpgradeError() {
  return Object.assign(new Error(protocolUpgradeMessage), {
    code: "game_protocol_incompatible",
  })
}

export function isProtocolUpgradeError(error: unknown) {
  if (!error || typeof error !== "object") return false
  if ("code" in error && error.code === "game_protocol_incompatible")
    return true
  if ("response" in error) {
    const response = error.response
    if (
      typeof response === "object" &&
      response !== null &&
      "status" in response &&
      response.status === 404
    )
      return true
    if (
      typeof response === "object" &&
      response !== null &&
      "data" in response
    ) {
      const data = response.data
      if (
        typeof data === "object" &&
        data !== null &&
        "detail" in data &&
        typeof data.detail === "object" &&
        data.detail !== null &&
        "code" in data.detail &&
        data.detail.code === "game_protocol_incompatible"
      )
        return true
    }
  }
  return false
}
