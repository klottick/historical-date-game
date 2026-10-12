import { createFileRoute, Link, useRouter } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import { getRun } from "@/features/game/api"
import { formatYear } from "@/features/game/config"
import { DailyLeaderboard } from "@/features/game/DailyPanel"
import { extractErrorMessage } from "@/utils"

export const Route = createFileRoute("/_layout/play/$runId")({
  loader: ({ params }) => getRun(params.runId),
  staleTime: 0,
  component: RunSummary,
  errorComponent: RunError,
  head: () => ({ meta: [{ title: "Run - Historical Date Game" }] }),
})

function RunError({ error }: { error: unknown }) {
  const router = useRouter()
  return (
    <div className="space-y-4">
      <h1 className="text-2xl">Run unavailable</h1>
      <p role="alert">
        {extractErrorMessage(
          error instanceof Error ? error : new Error("Unable to load run"),
        )}
        . This does not erase your history.
      </p>
      <Button onClick={() => router.invalidate()}>Retry run</Button>{" "}
      <Link to="/">Home</Link>
    </div>
  )
}

function RunSummary() {
  const run = Route.useLoaderData()
  return (
    <div className="space-y-6">
      <h1 className="font-serif text-3xl">
        {run.mode === "daily" ? "Daily run" : "Freeplay run"}
      </h1>
      <p>
        {run.mode === "daily" ? `Daily · ${run.daily_date} UTC` : "Freeplay"}
      </p>
      <p>
        Status: {run.status} · Streak: {run.streak}
      </p>
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Your timeline</h2>
        <ol className="space-y-3">
          {run.timeline.map((card) => (
            <li
              key={card.event_id}
              className="rounded-xl border border-[#426d73]/40 bg-card p-4"
            >
              <h3 className="font-semibold">
                {card.prompt} · {formatYear(card.year)}
              </h3>
              <p>{card.explanation}</p>
              <ul>
                {card.sources.map((source) => (
                  <li key={source.url}>
                    <a
                      className="underline"
                      href={source.url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {source.label}
                    </a>
                  </li>
                ))}
              </ul>
              <ul className="text-sm text-muted-foreground">
                {card.media.credits.map((credit) => (
                  <li key={`${credit.label}:${credit.url}`}>
                    {credit.url ? (
                      <a
                        className="underline"
                        href={credit.url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {credit.label}
                      </a>
                    ) : (
                      credit.label
                    )}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      </section>
      {run.pending && (
        <section className="rounded-xl border border-[#dba64d]/60 bg-card p-4">
          <h2 className="text-xl font-semibold">Next card</h2>
          <p>{run.pending.prompt}</p>
          <p className="text-sm text-muted-foreground">
            Its year stays hidden until a guess is locked in. The playable
            timeline arrives in the next beta update.
          </p>
          <ul className="text-sm text-muted-foreground">
            {run.pending.media.credits.map((credit) => (
              <li key={`${credit.label}:${credit.url}`}>
                {credit.url ? (
                  <a
                    className="underline"
                    href={credit.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {credit.label}
                  </a>
                ) : (
                  credit.label
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {run.mode === "daily" && run.status !== "active" && run.daily_date && (
        <DailyLeaderboard day={run.daily_date} />
      )}
      <Link to="/" className="underline">
        Back to Home
      </Link>
    </div>
  )
}
