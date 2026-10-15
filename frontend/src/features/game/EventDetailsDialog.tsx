import type { RevealedCard } from "@/client"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { formatYear } from "./config"

export function safeSourceURL(value: string): string | null {
  try {
    const url = new URL(value)
    return ["https:", "http:"].includes(url.protocol) &&
      !url.username &&
      !url.password
      ? value
      : null
  } catch {
    return null
  }
}
export function SourceLink({
  label,
  url,
}: {
  label: string
  url: string | null
}) {
  const href = url && safeSourceURL(url)
  return href ? (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {label}
    </a>
  ) : (
    <span>{label}</span>
  )
}
export function EventDetailsDialog({ card }: { card: RevealedCard }) {
  const link =
    card.learn_more && safeSourceURL(card.learn_more.url)
      ? card.learn_more
      : null
  const fallback = card.sources.find((source) => safeSourceURL(source.url))
  return (
    <Dialog>
      <DialogTrigger asChild>
        <button type="button">Learn more</button>
      </DialogTrigger>
      <DialogContent className="game-dialog">
        <DialogTitle>{card.prompt}</DialogTitle>
        <DialogDescription>
          {formatYear(card.year)} · Revealed event
        </DialogDescription>
        {link ? (
          <p>
            <SourceLink
              label={
                link.kind === "article"
                  ? link.label
                  : `Source page · ${link.label}`
              }
              url={link.url}
            />
          </p>
        ) : fallback ? (
          <p>
            <SourceLink
              label={`Source page · ${fallback.label}`}
              url={fallback.url}
            />
          </p>
        ) : (
          <p>No event article is available.</p>
        )}
        <details>
          <summary>Source/provenance details</summary>
          <p>{card.explanation}</p>
          <ul>
            {card.sources.map((source, index) => (
              <li key={`${source.url}:${index}`}>
                <SourceLink {...source} />
              </li>
            ))}
          </ul>
        </details>
      </DialogContent>
    </Dialog>
  )
}
