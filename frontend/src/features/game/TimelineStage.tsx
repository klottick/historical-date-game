import { useDroppable } from "@dnd-kit/react"
import { useContext } from "react"
import type { PendingCard } from "@/client"
import { GameCard } from "./GameCard"
import type { TimelineDisplayItem } from "./lossTimeline"
import { PendingTile, TimelineLockContext } from "./PendingTile"
import type { TimelineInteraction } from "./useTimelineInteraction"

export function TimelineStage({
  items,
  pending,
  previewSlot,
  correctDisplaySlot,
  interaction,
}: {
  items: TimelineDisplayItem[]
  pending: PendingCard | null
  previewSlot: number | null
  correctDisplaySlot: number | null
  interaction: TimelineInteraction
}) {
  const { ref } = useDroppable({ id: "timeline", disabled: !pending })
  const locked = useContext(TimelineLockContext)
  const { layout, offset } = interaction
  const visibleSlot = interaction.dragging
    ? interaction.hoveredSlot
    : previewSlot
  const tileSlot = interaction.dragging
    ? (interaction.hoveredSlot ?? previewSlot)
    : previewSlot
  const stride = layout.cardWidth + layout.gap
  return (
    <section
      className="timeline-stage"
      data-has-pending={pending !== null}
      aria-label="Event timeline"
      onKeyDown={(event) => interaction.keyboard(event.nativeEvent)}
    >
      {pending && (
        <h2 className="hand-label">
          {previewSlot === null ? "Next card" : "Unlocked preview"}
        </h2>
      )}
      <div
        ref={(element) => {
          ref(element)
          interaction.viewportRef.current = element
        }}
        className="timeline-viewport"
        style={{ marginLeft: pending ? "var(--hand-reserve)" : 0 }}
        data-offset={offset}
        data-hovered-slot={interaction.hoveredSlot ?? ""}
      >
        <div
          className="timeline-strip"
          style={{ transform: `translateX(${-offset}px)` }}
        >
          {items.map((item, index) => (
            <div
              key={item.card.event_id}
              className="timeline-item"
              data-display-index={index}
              data-wrong={item.wrong}
              style={{
                width: layout.cardWidth,
                left:
                  index * stride +
                  (visibleSlot !== null && index >= visibleSlot ? stride : 0),
              }}
            >
              {item.wrong && <strong className="wrong-marker">Wrong</strong>}
              <GameCard card={item.card} revealed />
            </div>
          ))}
          {interaction.dragging && visibleSlot !== null && (
            <div
              className="insertion-preview"
              aria-hidden="true"
              style={{
                width: layout.cardWidth,
                left: visibleSlot * stride,
              }}
            >
              Your card here
            </div>
          )}
          {correctDisplaySlot !== null && (
            <div
              className="correct-location"
              data-correct-slot={correctDisplaySlot}
              data-at-end={correctDisplaySlot === items.length}
              style={{
                left:
                  correctDisplaySlot === 0
                    ? 0
                    : correctDisplaySlot === items.length
                      ? items.length * stride - layout.gap
                      : correctDisplaySlot * stride - layout.gap / 2,
              }}
            >
              Correct location
            </div>
          )}
        </div>
      </div>
      {pending && (
        <div
          className="pending-position"
          data-preview-slot={previewSlot ?? undefined}
          data-in-hand={tileSlot === null}
          style={{
            width:
              tileSlot === null
                ? "var(--hand-card-width, var(--card-width))"
                : layout.cardWidth,
            left:
              tileSlot === null
                ? 0
                : `calc(var(--hand-reserve) + ${tileSlot * stride}px)`,
            transform:
              tileSlot === null ? undefined : `translateX(${-offset}px)`,
          }}
        >
          <PendingTile card={pending} disabled={locked} />
        </div>
      )}
    </section>
  )
}
