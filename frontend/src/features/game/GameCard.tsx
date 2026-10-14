import type { PendingCard, RevealedCard } from "@/client"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { formatYear } from "./config"
import { EventDetailsDialog } from "./EventDetailsDialog"
import { EventImage } from "./EventImage"

export function GameCard({
  card,
  revealed,
}: {
  card: PendingCard | RevealedCard
  revealed: boolean
}): React.JSX.Element {
  const answer = revealed && "year" in card ? card : null
  return (
    <article
      data-event-id={card.event_id}
      className={`game-card ${answer ? "game-card-revealed" : "game-card-pending"}`}
    >
      <div className="game-card-category">
        <span aria-hidden="true">◆</span>{" "}
        {card.category_ids.map((id) => id.replace(/[-_]/g, " ")).join(" · ")}
      </div>
      <EventImage media={card.media} />
      <div className="game-card-copy">
        <h3 title={card.prompt}>{card.prompt}</h3>
        <p className="game-card-year">
          {answer ? formatYear(answer.year) : "Year hidden · your move"}
        </p>
        {answer && <EventDetailsDialog card={answer} />}
        {!answer && card.prompt.length > 180 && (
          <Dialog>
            <DialogTrigger asChild>
              <button
                type="button"
                onPointerDown={(event) => event.stopPropagation()}
              >
                Read full prompt
              </button>
            </DialogTrigger>
            <DialogContent className="game-dialog">
              <DialogTitle>Full prompt</DialogTitle>
              <DialogDescription>
                Public event wording only. The year stays hidden.
              </DialogDescription>
              <p>{card.prompt}</p>
            </DialogContent>
          </Dialog>
        )}
      </div>
    </article>
  )
}
