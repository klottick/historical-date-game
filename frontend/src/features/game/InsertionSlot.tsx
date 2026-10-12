import { useDroppable } from "@dnd-kit/react"
import { createContext, useContext } from "react"

export const SlotLockContext = createContext(false)

export function InsertionSlot({
  index,
  selected,
  onSelect,
}: {
  index: number
  selected: boolean
  onSelect: () => void
}): React.JSX.Element {
  const disabled = useContext(SlotLockContext)
  const { ref, isDropTarget } = useDroppable({
    id: `slot-${index}`,
    data: { slot: index },
    disabled,
  })
  return (
    <button
      ref={ref}
      type="button"
      data-slot={index}
      className={`insertion-slot ${isDropTarget ? "insertion-slot-over" : ""}`}
      aria-label={`Slot ${index + 1}`}
      aria-pressed={selected}
      disabled={disabled}
      onClick={onSelect}
    >
      <span aria-hidden="true">{selected ? "✓" : "+"}</span>
      <span>Slot {index + 1}</span>
    </button>
  )
}
