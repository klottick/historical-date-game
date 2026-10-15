import { useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react"
import { type GameSessionPublic, UsersService } from "@/client"
import { adoptAccountStart, bindGameContext, isCurrentGameContext } from "./api"
import {
  accountToken,
  notifyAccountChange,
  sessionFailure,
  subscribeAccountChange,
} from "./identityState"
import {
  ensureGameSession,
  gameQueryKey,
  retryGuestBootstrap,
  startStorageKey,
} from "./sessionBootstrap"

type SessionState = {
  context: GameSessionPublic | null
  loading: boolean
  error: unknown
  retrySession: () => void
  continueAsGuest: () => void
  failSession: (error: unknown) => void
}
const Session = createContext<SessionState | null>(null)
export function GameSessionProvider({
  mode,
  children,
}: {
  mode: "bootstrap" | "inspect"
  children: ReactNode
}) {
  const token = useSyncExternalStore(subscribeAccountChange, accountToken)
  const [attempt, setAttempt] = useState({ number: 0, mode, guest: false })
  const [state, setState] = useState<{
    token: string
    context: GameSessionPublic | null
    loading: boolean
    error: unknown
  }>({ token, context: null, loading: true, error: null })
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const inspectionOnly = useRef(false)
  const consumedGuestAttempt = useRef(-1)
  const activeController = useRef<AbortController | null>(null)
  const entryMode = useRef(mode)
  entryMode.current = mode
  useEffect(() => {
    const controller = new AbortController()
    const currentMode = entryMode.current
    activeController.current = controller
    let context: GameSessionPublic | undefined
    const current = () => !controller.signal.aborted && accountToken() === token
    const explicitGuestRetry =
      attempt.guest && consumedGuestAttempt.current !== attempt.number
    if (explicitGuestRetry) consumedGuestAttempt.current = attempt.number
    setState({ token, context: null, loading: true, error: null })
    async function setup() {
      try {
        context = await (explicitGuestRetry
          ? retryGuestBootstrap(controller.signal)
          : ensureGameSession(
              inspectionOnly.current || currentMode === "inspect"
                ? "inspect"
                : attempt.number
                  ? attempt.mode
                  : currentMode,
              controller.signal,
            ))
        if (!current()) return
        // Only a fresh bearer-authenticated profile identifies a legacy account.
        let accountId: string | undefined
        if (context.kind === "account") {
          const profile = (
            await UsersService.readUserMe({
              auth: token,
              signal: controller.signal,
              timeout: 15_000,
              throwOnError: true,
              requestValidator: async () => {
                if (!current()) throw new Error("Account changed")
              },
            })
          ).data
          if (!current()) return
          accountId = profile.id
        }
        if (!current()) return
        bindGameContext(context, token, current, accountId, controller.signal)
        for (const startMode of ["daily", "freeplay"] as const)
          adoptAccountStart(
            context,
            startStorageKey(context.context_id, startMode),
            startMode,
          )
        setState({ token, context, loading: false, error: null })
      } catch (error) {
        if (current()) {
          inspectionOnly.current = true
          setState({ token, context: null, loading: false, error })
        }
      }
    }
    setup()
    return () => {
      controller.abort()
      if (context) {
        const queryKey = gameQueryKey(context.context_id, "").slice(0, 2)
        queryClient.cancelQueries({ queryKey })
        queryClient.removeQueries({ queryKey })
      }
    }
  }, [token, attempt, queryClient])
  const failSession = useCallback(
    (error: unknown) => {
      if (token !== accountToken()) return
      inspectionOnly.current = true
      activeController.current?.abort()
      setState((old) => ({ ...old, loading: false, error }))
    },
    [token],
  )
  const value: SessionState = {
    context: state.token === token && !state.error ? state.context : null,
    loading: state.token !== token || state.loading,
    error: state.token === token ? state.error : null,
    retrySession: () =>
      setAttempt((old) => ({
        number: old.number + 1,
        mode: "inspect",
        guest: false,
      })),
    continueAsGuest: () => {
      activeController.current?.abort()
      inspectionOnly.current = false
      localStorage.removeItem("access_token")
      notifyAccountChange()
      setAttempt((old) => ({
        number: old.number + 1,
        mode: "bootstrap",
        guest: true,
      }))
      navigate({ to: "/" })
    },
    failSession,
  }
  return <Session.Provider value={value}>{children}</Session.Provider>
}
export function useGameSession() {
  const value = useContext(Session)
  if (!value) throw new Error("GameSessionProvider is required")
  return value
}

export function useGameSessionError(
  error: unknown,
  context: GameSessionPublic,
) {
  const { failSession } = useGameSession()
  useEffect(() => {
    if (sessionFailure(error) && isCurrentGameContext(context))
      failSession(error)
  }, [error, context, failSession])
}
