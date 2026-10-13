import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import type { GameSessionPublic } from "@/client"
import { Button } from "@/components/ui/button"
import { getActiveRuns } from "@/features/game/api"
import { GameSessionGate } from "@/features/game/GameSessionGate"
import { useGameSessionError } from "@/features/game/GameSessionProvider"
import { gameQueryKey } from "@/features/game/identityState"
import useAuth from "@/hooks/useAuth"
import { extractErrorMessage } from "@/utils"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({
    meta: [
      {
        title: "Home - Historical Date Game",
      },
    ],
  }),
})

function Dashboard() {
  return (
    <GameSessionGate>
      {(context) => <OwnedDashboard context={context} />}
    </GameSessionGate>
  )
}
function OwnedDashboard({ context }: { context: GameSessionPublic }) {
  const { user: currentUser } = useAuth()
  const runs = useQuery({
    queryKey: gameQueryKey(context.context_id, "active-runs"),
    queryFn: ({ signal }) => getActiveRuns(context, signal),
    retry: false,
  })
  useGameSessionError(runs.error, context)

  return (
    <div className="space-y-8">
      <section className="space-y-4 rounded-xl border border-[#426d73]/40 bg-card p-6 md:p-8">
        <p className="text-sm text-muted-foreground">
          {context.kind === "guest"
            ? "Welcome! Play without an account. Guest progress belongs to this browser; keep using the same site address."
            : `Welcome back, ${currentUser?.full_name || currentUser?.email || "player"}.`}
        </p>
        <h1 className="font-serif text-3xl md:text-4xl">
          Historical Date Game
        </h1>
        <p className="max-w-xl">
          Put history in order, one card at a time. Explore a subject in
          Freeplay or take on the shared Daily challenge.
        </p>
        <div className="flex flex-wrap gap-4">
          <Link
            to="/daily"
            className="rounded-md bg-[#426d73] px-5 py-3 font-semibold text-white"
          >
            Daily challenge
          </Link>
          <Link
            to="/freeplay"
            className="rounded-md bg-[#dba64d] px-5 py-3 font-semibold text-[#263f4a]"
          >
            Freeplay
          </Link>
        </div>
      </section>
      <section className="space-y-4">
        <h2 className="text-xl font-semibold">Resume your runs</h2>
        {runs.isPending && <p>Loading your runs…</p>}
        {runs.error && (
          <p role="alert">
            Saved runs unavailable: {extractErrorMessage(runs.error)}. Your
            history has not been erased.{" "}
            <Button variant="outline" onClick={() => runs.refetch()}>
              Retry runs
            </Button>
          </p>
        )}
        {runs.data?.length === 0 && (
          <p className="text-muted-foreground">
            No active runs yet. Choose a mode to begin.
          </p>
        )}
        <ul className="space-y-3">
          {runs.data?.map((run) => (
            <li key={run.run_id}>
              <Link
                to="/play/$runId"
                params={{ runId: run.run_id }}
                className="underline"
              >
                Resume{" "}
                {run.mode === "daily"
                  ? `Daily · ${run.daily_date} UTC`
                  : "Freeplay"}{" "}
                · Streak {run.streak} · {run.run_id.slice(0, 8)}
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
