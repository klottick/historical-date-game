import { useDraggable } from "@dnd-kit/react"
import { createContext } from "react"
import type { PendingCard } from "@/client"
import { GameCard } from "./GameCard"

export const TimelineLockContext = createContext(false)

export function PendingTile({
  card,
  disabled,
}: {
  card: PendingCard
  disabled: boolean
}) {
  const { ref, isDragging } = useDraggable({ id: card.event_id, disabled })
  return (
    // biome-ignore lint/a11y/useSemanticElements: A full-card drag surface contains article content, which cannot be nested in a native button. Accessibility also supplies the drag instructions.
    <div
      ref={ref}
      className="pending-draggable"
      data-testid="pending-card"
      data-dragging={isDragging}
      tabIndex={disabled ? -1 : 0}
      role="button"
      aria-label={`Place card: ${card.prompt}`}
      aria-disabled={disabled}
      aria-describedby="placement-instructions"
    >
      <span className="tile-grip" aria-hidden="true">
        ⠿
      </span>
      <GameCard card={card} revealed={false} />
    </div>
  )
}
