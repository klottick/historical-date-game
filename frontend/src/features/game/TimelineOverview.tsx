import type { overviewMarks } from "./boardGeometry"

export function TimelineOverview({
  marks,
  previewSlot,
  correctSlot,
  onNavigate,
}: {
  marks: ReturnType<typeof overviewMarks>
  previewSlot: number | null
  correctSlot: number | null
  onNavigate: (slot: number) => void
}) {
  const count = marks.length ? marks[marks.length - 1].end + 1 : 0
  return (
    <nav className="timeline-overview" aria-label="Timeline overview">
      <button
        type="button"
        aria-label="Show beginning"
        onClick={() => onNavigate(0)}
      >
        ‹
      </button>
      <div className="overview-marks">
        {marks.map((mark) => (
          <button
            type="button"
            key={mark.start}
            className="overview-mark"
            data-visible={mark.visible}
            aria-label={`Show events ${mark.start + 1} to ${mark.end + 1}`}
            onClick={() => onNavigate(mark.start)}
          />
        ))}
        {previewSlot !== null && (
          <span
            role="img"
            className="overview-preview"
            aria-label="Unlocked preview"
            style={{ left: `${(100 * previewSlot) / Math.max(1, count)}%` }}
          />
        )}
        {correctSlot !== null && (
          <span
            role="img"
            className="overview-correct"
            aria-label="Correct location"
            style={{ left: `${(100 * correctSlot) / Math.max(1, count)}%` }}
          />
        )}
      </div>
      <button
        type="button"
        aria-label="Show end"
        onClick={() => onNavigate(count)}
      >
        ›
      </button>
    </nav>
  )
}
