import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import type { DailyStart } from "@/client"
import { Button } from "@/components/ui/button"
import { LoadingButton } from "@/components/ui/loading-button"
import { extractErrorMessage } from "@/utils"
import {
  getDaily,
  getGameOptions,
  getLeaderboard,
  getRun,
  isKnownFailure,
  readStartOperation,
  saveStartOperation,
  startDaily,
} from "./api"

export function DailyLeaderboard({ day }: { day: string }) {
  const board = useQuery({
    queryKey: ["game", "leaderboard", day],
    queryFn: () => getLeaderboard(day),
    retry: false,
  })
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

export function DailyPanel({ ownerId }: { ownerId: string }) {
  const overview = useQuery({
    queryKey: ["game", "daily", ownerId],
    queryFn: getDaily,
    retry: false,
  })
  const options = useQuery({
    queryKey: ["game", "options"],
    queryFn: getGameOptions,
    retry: false,
  })
  const runId = overview.data?.attempt_run_id
  const run = useQuery({
    queryKey: ["game", "run", runId],
    queryFn: () => getRun(runId!),
    enabled: !!runId,
    retry: false,
  })
  const key = `game-start:${ownerId}:daily`
  const [operation, setOperation] = useState(() =>
    readStartOperation<DailyStart>(key),
  )
  const [now, setNow] = useState(Date.now)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: startDaily,
    retry: false,
    onSuccess: (result) => {
      sessionStorage.removeItem(key)
      setOperation(null)
      queryClient.invalidateQueries({ queryKey: ["game", "daily"] })
      queryClient.invalidateQueries({ queryKey: ["game", "active-runs"] })
      navigate({ to: "/play/$runId", params: { runId: result.run_id } })
    },
    onError: (error) => {
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
    if (run.data && operation) {
      sessionStorage.removeItem(key)
      setOperation(null)
    }
  }, [run.data, operation, key])
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
          One scored attempt per account per UTC day. Everyone plays the same
          frozen challenge.
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
                  if (mutation.isPending) return
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
        <DailyLeaderboard day={run.data.daily_date} />
      )}
    </div>
  )
}
