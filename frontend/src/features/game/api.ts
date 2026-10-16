import { isAxiosError } from "axios"
import { GamesService, UtilsService } from "../../client/sdk.gen.ts"
import type {
  DailyOverview,
  DailyStart,
  FreeplayStart,
  GameOptions,
  GameSessionPublic,
  LeaderboardPublic,
  PlaceCommand,
  PublicConfig,
  RunPublic,
} from "../../client/types.gen.ts"
import {
  hasCompatibleGameProtocol,
  isProtocolUpgradeError,
  protocolUpgradeError,
} from "./gameProtocol.ts"
import {
  gameRequestOptions,
  sessionError,
  sessionFailure,
} from "./identityState.ts"

// A public context is not authorization. Keep its confirmed bearer and lifetime
// out of DTOs/storage, and never consult mutable client auth for an owned call.
const bindings = new WeakMap<
  GameSessionPublic,
  {
    auth: string
    current: () => boolean
    accountId?: string
    signal?: AbortSignal
  }
>()
export function bindGameContext(
  context: GameSessionPublic,
  auth: string,
  current: () => boolean,
  accountId?: string,
  signal?: AbortSignal,
) {
  bindings.set(context, { auth, current, accountId, signal })
}
export function isCurrentGameContext(context: GameSessionPublic) {
  return bindings.get(context)?.current() === true
}
function assertContext(context: GameSessionPublic) {
  if (!isCurrentGameContext(context))
    throw sessionError(
      "game_identity_changed",
      "Identity changed; retry session inspection. Your saved commands remain with their original player.",
    )
}
function ownedOptions(context: GameSessionPublic, signal?: AbortSignal) {
  assertContext(context)
  const binding = bindings.get(context)!
  return {
    ...gameRequestOptions(context),
    auth: binding.auth,
    signal:
      signal && binding.signal
        ? AbortSignal.any([signal, binding.signal])
        : (signal ?? binding.signal),
    // Generated auth resolution is asynchronous even for a literal token.
    requestValidator: async () => assertContext(context),
    throwOnError: true as const,
  }
}
async function ownedResult<T>(
  context: GameSessionPublic,
  request: Promise<{ data: T }>,
): Promise<T> {
  try {
    const result = await request
    assertContext(context)
    return result.data
  } catch (error) {
    assertContext(context)
    throw error
  }
}
export function adoptAccountStart(
  context: GameSessionPublic,
  _key: string,
  _mode: "daily" | "freeplay",
) {
  // Unversioned commands belong to the incompatible protocol and are never replayed.
  assertContext(context)
}
// Caller must have completed a fresh owned GET, never merely a cached read.
export function adoptAccountPlacement(
  context: GameSessionPublic,
  _key: string,
  _runId: string,
) {
  // Unversioned commands belong to the incompatible protocol and are never replayed.
  assertContext(context)
}

// Reuse the generated client's base URL, bearer auth, and Axios error shape.
export async function getGameOptions(): Promise<GameOptions> {
  const options = (await GamesService.readOptions({ throwOnError: true })).data
  if (!hasCompatibleGameProtocol(options)) throw protocolUpgradeError()
  return options
}
export async function getPublicConfig(): Promise<PublicConfig> {
  return (await UtilsService.publicConfig({ throwOnError: true })).data
}
export async function getDaily(
  context: GameSessionPublic,
  signal?: AbortSignal,
): Promise<DailyOverview> {
  return ownedResult(
    context,
    GamesService.readDaily(ownedOptions(context, signal)),
  )
}
export async function startFreeplay(
  input: FreeplayStart,
  context: GameSessionPublic,
): Promise<RunPublic> {
  return ownedResult(
    context,
    GamesService.startFreeplay({ body: input, ...ownedOptions(context) }),
  )
}
export async function startDaily(
  input: DailyStart,
  context: GameSessionPublic,
): Promise<RunPublic> {
  return ownedResult(
    context,
    GamesService.startDaily({ body: input, ...ownedOptions(context) }),
  )
}
export async function getRun(
  runId: string,
  context: GameSessionPublic,
  signal?: AbortSignal,
): Promise<RunPublic> {
  return ownedResult(
    context,
    GamesService.readRun({
      path: { run_id: runId },
      ...ownedOptions(context, signal),
    }),
  )
}
export async function getActiveRuns(
  context: GameSessionPublic,
  signal?: AbortSignal,
): Promise<RunPublic[]> {
  return ownedResult(
    context,
    GamesService.readActiveRuns(ownedOptions(context, signal)),
  )
}
export async function placeCard(
  runId: string,
  input: PlaceCommand,
  context: GameSessionPublic,
): Promise<RunPublic> {
  return ownedResult(
    context,
    GamesService.placeCard({
      path: { run_id: runId },
      body: input,
      timeout: 15000,
      ...ownedOptions(context),
    }),
  )
}

export function gameFailure(
  error: unknown,
):
  | "auth"
  | "conflict"
  | "validation"
  | "unavailable"
  | "network"
  | "rejected"
  | "incompatible" {
  if (isProtocolUpgradeError(error)) return "incompatible"
  const status = isAxiosError(error) ? error.response?.status : undefined
  // The existing auth dependency returns 403 for expired/invalid bearer tokens.
  if (status === 401 || status === 403) return "auth"
  if (status === 409) return "conflict"
  if (status === 422) return "validation"
  if (status === undefined) return "network"
  if (status === 408 || status === 429 || status >= 500) return "unavailable"
  return "rejected"
}

export async function getLeaderboard(
  day: string,
  context: GameSessionPublic,
  signal?: AbortSignal,
): Promise<LeaderboardPublic> {
  return ownedResult(
    context,
    GamesService.readLeaderboard({
      path: { day },
      ...ownedOptions(context, signal),
    }),
  )
}

export function isKnownFailure(error: unknown): boolean {
  if (sessionFailure(error) !== null || isProtocolUpgradeError(error))
    return false
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
