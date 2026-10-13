import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"
import type { DailyStart, GameSessionPublic } from "@/client"
import { Button } from "@/components/ui/button"
import { LoadingButton } from "@/components/ui/loading-button"
import { extractErrorMessage } from "@/utils"
import {
  getDaily,
  getGameOptions,
  getLeaderboard,
  getRun,
  isCurrentGameContext,
  isKnownFailure,
  readStartOperation,
  saveStartOperation,
  startDaily,
} from "./api"
import { useGameSession, useGameSessionError } from "./GameSessionProvider"
import { gameQueryKey, sessionFailure, startStorageKey } from "./identityState"

export function DailyLeaderboard({
  day,
  context,
}: {
  day: string
  context: GameSessionPublic
}) {
  const board = useQuery({
    queryKey: gameQueryKey(context.context_id, "leaderboard", day),
    queryFn: ({ signal }) => getLeaderboard(day, context, signal),
    retry: false,
  })
  useGameSessionError(board.error, context)
  return (
    <section className="space-y-3">
      <h2 className="text-xl font-semibold">Leaderboard · {day} UTC</h2>
      <p className="text-sm text-muted-foreground">
        Completed runs only. Equal streaks share a rank.
      </p>
      {board.isPending && <p>Loading leaderboard…</p>}
      {board.error && (
        <p role="alert">
          Leaderboard unavailable: {extractErrorMessage(board.error)}{" "}
          <Button variant="outline" onClick={() => board.refetch()}>
            Retry leaderboard
          </Button>
        </p>
      )}
      {board.data && (
        <>
          <table className="w-full max-w-2xl text-left">
            <caption className="sr-only">
              Completed Daily results for {day} UTC
            </caption>
            <thead>
              <tr>
                <th scope="col">Rank</th>
                <th scope="col">Player</th>
                <th scope="col">Streak</th>
                <th scope="col">Result</th>
              </tr>
            </thead>
            <tbody>
              {board.data.entries.map((entry, index) => (
                <tr key={`${entry.rank}-${index}`} className="border-b">
                  <td className="py-2">{entry.rank}</td>
                  <td>{entry.display_name}</td>
                  <td>{entry.streak}</td>
                  <td>{entry.status === "won" ? "Won" : "Lost"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {board.data.entries.length === 0 && <p>No completed runs yet.</p>}
        </>
      )}
    </section>
  )
}

export function DailyPanel({ context }: { context: GameSessionPublic }) {
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const current = () => mounted.current && isCurrentGameContext(context)
  const { failSession } = useGameSession()
  const overview = useQuery({
    queryKey: gameQueryKey(context.context_id, "daily"),
    queryFn: ({ signal }) => getDaily(context, signal),
    retry: false,
  })
  const options = useQuery({
    queryKey: ["game", "options"],
    queryFn: getGameOptions,
    retry: false,
  })
  const runId = overview.data?.attempt_run_id
  const run = useQuery({
    queryKey: gameQueryKey(context.context_id, "run", runId ?? ""),
    queryFn: ({ signal }) => getRun(runId!, context, signal),
    enabled: !!runId,
    retry: false,
  })
  const key = startStorageKey(context.context_id, "daily")
  useGameSessionError(overview.error, context)
  useGameSessionError(run.error, context)
  const [operation, setOperation] = useState(() =>
    readStartOperation<DailyStart>(key),
  )
  const [now, setNow] = useState(Date.now)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: (input: DailyStart) => startDaily(input, context),
    retry: false,
    onSuccess: (result) => {
      if (!current()) return
      sessionStorage.removeItem(key)
      setOperation(null)
      queryClient.invalidateQueries({
        queryKey: gameQueryKey(context.context_id, "daily"),
      })
      queryClient.invalidateQueries({
        queryKey: gameQueryKey(context.context_id, "active-runs"),
      })
      navigate({ to: "/play/$runId", params: { runId: result.run_id } })
    },
    onError: (error) => {
      if (!current()) return
      if (sessionFailure(error)) {
        failSession(error)
        return
      }
      if (isKnownFailure(error)) {
        sessionStorage.removeItem(key)
        setOperation(null)
      }
    },
  })
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  // A GET-confirmed attempt resolves an uncertain start without another POST.
  useEffect(() => {
    if (
      isCurrentGameContext(context) &&
      run.data &&
      operation &&
      run.isFetchedAfterMount &&
      !run.isFetching &&
      !run.isError
    ) {
      sessionStorage.removeItem(key)
      setOperation(null)
    }
  }, [
    run.data,
    operation,
    key,
    context,
    run.isFetchedAfterMount,
    run.isFetching,
    run.isError,
  ])
  const reset = overview.data
    ? new Date(overview.data.reset_at).getTime()
    : Infinity
  const expired = reset <= now
  useEffect(() => {
    if (expired) overview.refetch()
  }, [expired, overview.refetch])
  const seconds = Math.max(0, Math.floor((reset - now) / 1000))
  const countdown = [
    Math.floor(seconds / 3600),
    Math.floor(seconds / 60) % 60,
    seconds % 60,
  ]
    .map((value) => String(value).padStart(2, "0"))
    .join(":")

  return (
    <div className="space-y-6">
      <section className="max-w-2xl space-y-4 rounded-xl border border-[#426d73]/40 bg-card p-6">
        <p>
          One scored attempt per{" "}
          {context.kind === "guest" ? "browser" : "account"} per UTC day.
          Everyone plays the same frozen challenge.
        </p>
        {overview.isPending && <p>Loading Daily…</p>}
        {overview.error && (
          <p role="alert">
            Daily unavailable: {extractErrorMessage(overview.error)}. Your saved
            runs remain accessible from Home.{" "}
            <Button variant="outline" onClick={() => overview.refetch()}>
              Retry Daily
            </Button>
          </p>
        )}
        {overview.data && (
          <>
            <p className="font-semibold">{overview.data.day} UTC</p>
            <p>
              Resets at {overview.data.reset_at} (UTC) ·{" "}
              {expired ? "Refreshing…" : countdown} remaining
            </p>
            <p>
              Fixed categories:{" "}
              {overview.data.category_ids
                .map(
                  (id) =>
                    options.data?.categories.find(
                      (category) => category.id === id,
                    )?.label ?? id,
                )
                .join(", ")}
            </p>
            {options.error && (
              <p className="text-sm">
                Current catalog unavailable; saved Daily results can still be
                opened.
              </p>
            )}
            {runId ? (
              <>
                {run.isPending && <p>Loading your attempt…</p>}
                {run.error && (
                  <p role="alert">
                    Attempt unavailable: {extractErrorMessage(run.error)}{" "}
                    <Button variant="outline" onClick={() => run.refetch()}>
                      Retry attempt
                    </Button>
                  </p>
                )}
                <Link
                  className="inline-block rounded-md bg-primary px-4 py-2 text-primary-foreground"
                  to="/play/$runId"
                  params={{ runId }}
                >
                  {run.data && run.data.status !== "active"
                    ? "View Result"
                    : "Resume Daily"}
                </Link>
              </>
            ) : (
              <LoadingButton
                loading={mutation.isPending}
                disabled={expired || overview.isFetching}
                onClick={() => {
                  if (!current() || mutation.isPending) return
                  const command = saveStartOperation(
                    key,
                    operation ?? { operation_id: crypto.randomUUID() },
                  )
                  setOperation(command)
                  mutation.mutate(command)
                }}
              >
                {operation && !mutation.isPending
                  ? "Retry start"
                  : "Start Daily"}
              </LoadingButton>
            )}
          </>
        )}
        {mutation.error && (
          <p role="alert">{extractErrorMessage(mutation.error)}</p>
        )}
        {operation && !mutation.isPending && (
          <p>
            This start is unconfirmed. Retry keeps the same operation;
            refreshing Daily can also recover a committed attempt.
          </p>
        )}
      </section>
      {run.data && run.data.status !== "active" && run.data.daily_date && (
        <DailyLeaderboard day={run.data.daily_date} context={context} />
      )}
    </div>
  )
}
