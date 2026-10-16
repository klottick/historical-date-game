import { useEffect, useRef, useState } from "react"
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
  const title = useRef<HTMLHeadingElement>(null)
  const [truncated, setTruncated] = useState(false)
  useEffect(() => {
    const element = title.current
    if (!element) return
    let active = true
    const measure = () => {
      if (active) setTruncated(element.scrollHeight > element.clientHeight + 1)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    const fonts = document.fonts
    void fonts?.ready.then(measure)
    return () => {
      active = false
      observer.disconnect()
    }
  }, [])
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
        <h3 ref={title}>{card.prompt}</h3>
        <div className="game-card-footer">
          <p className="game-card-year">
            {answer ? formatYear(answer.year) : "Year hidden · your move"}
          </p>
          {answer && <EventDetailsDialog card={answer} />}
          {!answer && truncated && (
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
      </div>
    </article>
  )
}
