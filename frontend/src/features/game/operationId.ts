type RandomSource = {
  randomUUID?: () => string
  getRandomValues?: (bytes: Uint8Array<ArrayBuffer>) => void
}

/** Generate only NEW commands. Persisted/retried commands retain their UUID. */
export function operationId(
  source: RandomSource | null = globalThis.crypto,
): string {
  try {
    if (typeof source?.randomUUID === "function") return source.randomUUID()
    if (typeof source?.getRandomValues === "function") {
      // getRandomValues is available at the approved insecure HTTP LAN origin.
      const bytes = new Uint8Array(16)
      source.getRandomValues(bytes)
      bytes[6] = (bytes[6] & 0x0f) | 0x40
      bytes[8] = (bytes[8] & 0x3f) | 0x80
      const hex = Array.from(bytes, (byte) =>
        byte.toString(16).padStart(2, "0"),
      ).join("")
      return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
    }
  } catch {
    // Do not use weak randomness, nor create/send an unauthenticated command.
  }
  throw new Error(
    "Secure random source unavailable. No game command was sent; try another browser.",
  )
}
