import type { PendingCard, RevealedCard } from "@/client"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { SourceLink } from "./EventDetailsDialog"

export function GameCreditsDialog({
  cards,
}: {
  cards: (PendingCard | RevealedCard)[]
}) {
  const unique = [
    ...new Map(cards.map((card) => [card.event_id, card])).values(),
  ]
  const assets = new Map<string, { card: PendingCard; events: string[] }>()
  for (const card of unique) {
    const key = JSON.stringify(card.media)
    const group = assets.get(key)
    if (group) group.events.push(card.prompt)
    else assets.set(key, { card, events: [card.prompt] })
  }
  return (
    <Dialog>
      <DialogTrigger asChild>
        <button type="button">Credits/Sources</button>
      </DialogTrigger>
      <DialogContent className="game-dialog">
        <DialogTitle>Credits/Sources</DialogTitle>
        <DialogDescription>
          Retained media notices and event lineage. Pending event answers are
          not included.
        </DialogDescription>
        {[...assets.entries()].map(([key, { card, events }]) => (
          <section key={key}>
            <h3>Artwork for {events.join(" · ")}</h3>
            <p>Primary asset: {card.media.url}</p>
            <p>Fallback asset: {card.media.fallback_url}</p>
            <p>{card.media.alt_text}</p>
            <ul>
              {card.media.credits.map((credit, index) => (
                <li key={`${credit.label}:${index}`}>
                  <SourceLink {...credit} />
                </li>
              ))}
            </ul>
          </section>
        ))}
        {unique
          .filter((card): card is RevealedCard => "year" in card)
          .map((card) => (
            <section key={card.event_id}>
              <h3>{card.prompt} · Event sources</h3>
              <ul>
                {card.sources.map((source, index) => (
                  <li key={`${source.url}:${index}`}>
                    <SourceLink {...source} />
                  </li>
                ))}
              </ul>
              <details>
                <summary>Source/provenance notes</summary>
                <p>{card.explanation}</p>
              </details>
            </section>
          ))}
      </DialogContent>
    </Dialog>
  )
}
