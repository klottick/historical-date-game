import { Fragment } from "react"
import type { RevealedCard } from "@/client"
import { GameCard } from "./GameCard"
import { InsertionSlot } from "./InsertionSlot"

export function Timeline({
  cards,
  selectedSlot,
  onSelectSlot,
}: {
  cards: RevealedCard[]
  selectedSlot: number | null
  onSelectSlot: (slot: number | null) => void
}): React.JSX.Element {
  return (
    <section className="timeline-panel" aria-label="Your timeline">
      <h2>
        Your timeline{" "}
        <span>
          {cards.length} revealed {cards.length === 1 ? "event" : "events"}
        </span>
      </h2>
      <p className="timeline-hint">
        Choose a numbered gap. Drag or scroll to explore the table.
      </p>
      <fieldset
        className="game-timeline"
        aria-label="Timeline slots and revealed cards"
      >
        {cards.map((card, index) => (
          <Fragment key={card.event_id}>
            <InsertionSlot
              index={index}
              selected={selectedSlot === index}
              onSelect={() => onSelectSlot(index)}
            />
            <GameCard card={card} revealed />
          </Fragment>
        ))}
        <InsertionSlot
          index={cards.length}
          selected={selectedSlot === cards.length}
          onSelect={() => onSelectSlot(cards.length)}
        />
      </fieldset>
    </section>
  )
}
