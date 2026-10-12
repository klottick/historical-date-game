import type { PendingCard, RevealedCard } from "@/client"
import { formatYear } from "./config"
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
      className={`game-card ${answer ? "game-card-revealed" : "game-card-pending"}`}
    >
      <div className="game-card-category">
        <span aria-hidden="true">◆</span>{" "}
        {card.category_ids.map((id) => id.replace(/[-_]/g, " ")).join(" · ")}
      </div>
      <EventImage media={card.media} />
      <div className="game-card-copy">
        <h3>{card.prompt}</h3>
        <p className="game-card-year">
          {answer ? formatYear(answer.year) : "Year hidden · your move"}
        </p>
        {answer && (
          <details>
            <summary>Event details & sources</summary>
            <p>{answer.explanation}</p>
            <ul>
              {answer.sources.map((source) => (
                <li key={source.url}>
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {source.label}
                  </a>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </article>
  )
}
