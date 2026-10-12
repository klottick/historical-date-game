import { Link } from "@tanstack/react-router"
import type { RevealedCard, RunPublic } from "@/client"
import { ContentIssueDialog } from "./ContentIssueDialog"
import { formatYear } from "./config"
import { DailyLeaderboard } from "./DailyPanel"

export function CardDetails({
  card,
}: {
  card: RevealedCard
}): React.JSX.Element {
  return (
    <>
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
    </>
  )
}

export function GameResults({ run }: { run: RunPublic }): React.JSX.Element {
  return (
    <section className="space-y-4" aria-label="Run result">
      <h2 className="font-serif text-2xl">
        {run.status === "won"
          ? "Victory — catalog exhausted"
          : "Mistake — run complete"}
      </h2>
      <p>Final streak: {run.streak}</p>
      {run.status === "won" ? (
        <p>
          You placed every eligible event in this frozen configuration (
          {formatYear(run.config.start)}–{formatYear(run.config.end)}, minimum
          gap {run.config.min_gap}; categories:{" "}
          {run.categories.map((category) => category.label).join(", ")}). No
          eligible unused event remains in catalog release{" "}
          {run.catalog_release_id}.
        </p>
      ) : (
        run.feedback && (
          <div className="rounded-xl border p-4 space-y-2">
            <CardDetails card={run.feedback.card} />
            <p>Correct slot: {run.feedback.correct_slot + 1}</p>
            <p>
              The mistaken card does not increase your final streak. The correct
              slot is numbered among the gaps in your timeline.
            </p>
            <ContentIssueDialog
              runId={run.run_id}
              eventId={run.feedback.card.event_id}
            />
          </div>
        )
      )}
      {run.mode === "daily" ? (
        <>
          <p>
            This Daily attempt is complete and cannot be replayed. The next
            challenge starts at the next UTC reset.
          </p>
          {run.daily_date && <DailyLeaderboard day={run.daily_date} />}
          <Link to="/daily" className="underline">
            Daily challenge
          </Link>
        </>
      ) : (
        <Link to="/freeplay" className="underline">
          New Freeplay
        </Link>
      )}
      {run.status === "won" && run.timeline.length > 0 && (
        <ContentIssueDialog
          runId={run.run_id}
          eventId={run.timeline[run.timeline.length - 1].event_id}
        />
      )}
    </section>
  )
}
