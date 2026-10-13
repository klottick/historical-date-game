import { isAxiosError } from "axios"
import { GamesService, UtilsService } from "../../client/sdk.gen.ts"
import type {
  DailyOverview,
  DailyStart,
  FreeplayStart,
  GameOptions,
  LeaderboardPublic,
  PlaceCommand,
  PublicConfig,
  RunPublic,
} from "../../client/types.gen.ts"
import { sessionFailure } from "./identityState.ts"

// Reuse the generated client's base URL, bearer auth, and Axios error shape.
export async function getGameOptions(): Promise<GameOptions> {
  return (await GamesService.readOptions({ throwOnError: true })).data
}
export async function getPublicConfig(): Promise<PublicConfig> {
  return (await UtilsService.publicConfig({ throwOnError: true })).data
}
export async function getDaily(): Promise<DailyOverview> {
  return (await GamesService.readDaily({ throwOnError: true })).data
}
export async function startFreeplay(input: FreeplayStart): Promise<RunPublic> {
  return (await GamesService.startFreeplay({ body: input, throwOnError: true }))
    .data
}
export async function startDaily(input: DailyStart): Promise<RunPublic> {
  return (await GamesService.startDaily({ body: input, throwOnError: true }))
    .data
}
export async function getRun(runId: string): Promise<RunPublic> {
  return (
    await GamesService.readRun({ path: { run_id: runId }, throwOnError: true })
  ).data
}
export async function getActiveRuns(): Promise<RunPublic[]> {
  return (await GamesService.readActiveRuns({ throwOnError: true })).data
}
export async function placeCard(
  runId: string,
  input: PlaceCommand,
): Promise<RunPublic> {
  return (
    await GamesService.placeCard({
      path: { run_id: runId },
      body: input,
      timeout: 15000,
      throwOnError: true,
    })
  ).data
}

export function gameFailure(
  error: unknown,
): "auth" | "conflict" | "validation" | "unavailable" | "network" | "rejected" {
  const status = isAxiosError(error) ? error.response?.status : undefined
  // The existing auth dependency returns 403 for expired/invalid bearer tokens.
  if (status === 401 || status === 403) return "auth"
  if (status === 409) return "conflict"
  if (status === 422) return "validation"
  if (status === undefined) return "network"
  if (status === 408 || status === 429 || status >= 500) return "unavailable"
  return "rejected"
}

export function renewRunLogin(runId: string): void {
  sessionStorage.setItem("game-login-return", `/play/${runId}`)
  localStorage.removeItem("access_token")
  window.location.assign("/login")
}
export async function getLeaderboard(day: string): Promise<LeaderboardPublic> {
  return (
    await GamesService.readLeaderboard({ path: { day }, throwOnError: true })
  ).data
}

export function isKnownFailure(error: unknown): boolean {
  if (sessionFailure(error) !== null) return false
  const status = isAxiosError(error) ? error.response?.status : undefined
  // Transport errors, timeouts, throttling and server failures may follow a commit.
  return (
    status !== undefined &&
    status >= 400 &&
    status < 500 &&
    status !== 408 &&
    status !== 429
  )
}

export function readStartOperation<T>(key: string): T | null {
  const saved = sessionStorage.getItem(key)
  return saved ? JSON.parse(saved) : null
}

export function saveStartOperation<T extends DailyStart>(
  key: string,
  command: T,
): T {
  // Never replace an unresolved action with a new UUID or changed payload.
  const saved = readStartOperation<T>(key)
  if (saved) return saved
  sessionStorage.setItem(key, JSON.stringify(command))
  return command
}
