import { Link } from "@tanstack/react-router"
import type { GameSessionPublic, RunPublic } from "@/client"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { formatYear } from "./config"
import { DailyLeaderboard } from "./DailyPanel"

export function GameResults({
  run,
  context,
}: {
  run: RunPublic
  context: GameSessionPublic
}) {
  return (
    <section className="game-results" aria-label="Run result">
      <h2 tabIndex={-1}>
        {run.status === "won"
          ? "Victory — catalog exhausted"
          : "Mistake — run complete"}
      </h2>
      <p>Final streak: {run.streak}</p>
      {run.status === "won" && (
        <p>
          You placed every eligible event in this frozen configuration. No
          eligible unused event remains.
        </p>
      )}
      <Dialog>
        <DialogTrigger asChild>
          <button type="button">
            Run details{run.mode === "daily" ? " & leaderboard" : ""}
          </button>
        </DialogTrigger>
        <DialogContent className="game-dialog">
          <DialogTitle>Run details</DialogTitle>
          <DialogDescription>
            Frozen run configuration and outcome.
          </DialogDescription>
          <p>
            {formatYear(run.config.start)}–{formatYear(run.config.end)} ·
            minimum gap {run.config.min_gap}
          </p>
          <p>
            Categories:{" "}
            {run.categories
              .filter((category) =>
                run.config.category_ids.includes(category.id),
              )
              .map((category) => category.label)
              .join(", ")}
          </p>
          <p>Catalog release: {run.catalog_release_id}</p>
          {run.mode === "daily" && run.daily_date && (
            <DailyLeaderboard day={run.daily_date} context={context} />
          )}
        </DialogContent>
      </Dialog>
      {run.mode === "daily" ? (
        <>
          <p>
            This Daily attempt is complete and cannot be replayed. Next
            challenge at the next UTC reset.
          </p>
          <Link to="/daily">Daily challenge</Link>
        </>
      ) : (
        <Link to="/freeplay">New Freeplay</Link>
      )}
    </section>
  )
}
