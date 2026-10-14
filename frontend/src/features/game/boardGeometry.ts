export type BoardLayout = {
  count: number
  cardWidth: number
  gap: number
  viewportWidth: number
  offset: number
  previewSlot: number | null
}

function finite(value: number): void {
  if (!Number.isFinite(value)) throw new RangeError("Expected finite geometry")
}

function ordinal(value: number): void {
  if (!Number.isSafeInteger(value) || value < 0)
    throw new RangeError("Expected a nonnegative safe ordinal")
}

function stripWidth(layout: BoardLayout): number {
  ordinal(layout.count)
  for (const value of [
    layout.cardWidth,
    layout.gap,
    layout.viewportWidth,
    layout.offset,
  ])
    finite(value)
  if (layout.cardWidth <= 0 || layout.gap < 0 || layout.viewportWidth <= 0)
    throw new RangeError("Invalid card or viewport dimensions")
  if (layout.previewSlot !== null) {
    ordinal(layout.previewSlot)
    if (layout.previewSlot > layout.count)
      throw new RangeError("Preview outside timeline")
  }
  const cards = layout.count + (layout.previewSlot === null ? 0 : 1)
  const width =
    cards === 0 ? 0 : cards * layout.cardWidth + (cards - 1) * layout.gap
  finite(layout.cardWidth + layout.gap)
  finite(width)
  return width
}

export function clampOffset(offset: number, layout: BoardLayout): number {
  const width = stripWidth(layout)
  finite(offset)
  return Math.max(
    0,
    Math.min(offset, Math.max(0, width - layout.viewportWidth)),
  )
}

/** localX is viewport-local CSS pixels; offset is positive strip displacement.
 * Confirmed cards start at i * (cardWidth + gap). A preview inserts one stride
 * before card previewSlot. Collapse that space ONCE, never animated DOM rects.
 * Its entire expanded insertion region therefore retains the same ordinal at
 * a stationary pointer, including after the preview first opens or relocates.
 */
export function insertionIndex(localX: number, layout: BoardLayout): number {
  stripWidth(layout)
  finite(localX)
  const stride = layout.cardWidth + layout.gap
  let x = localX + clampOffset(layout.offset, layout)
  finite(x)
  if (layout.previewSlot !== null) {
    const start = layout.previewSlot * stride
    if (x >= start) x = x < start + stride ? start : x - stride
  }
  return Math.max(
    0,
    Math.min(layout.count, Math.floor((x - layout.cardWidth / 2) / stride) + 1),
  )
}

/** Reveal an ordinal boundary, or the whole preview when it occupies that slot.
 * If a preview is wider than the viewport, center it rather than flip edges.
 */
export function offsetToReveal(slot: number, layout: BoardLayout): number {
  const width = stripWidth(layout)
  ordinal(slot)
  if (slot > layout.count) throw new RangeError("Slot outside timeline")
  const stride = layout.cardWidth + layout.gap
  const preview = layout.previewSlot === slot
  let start = slot === 0 ? 0 : slot * stride - layout.gap / 2
  if (slot === layout.count) start = width
  if (preview) start = slot * stride
  else if (
    layout.previewSlot !== null &&
    slot > layout.previewSlot &&
    slot < layout.count
  )
    start += stride
  const end = preview ? start + layout.cardWidth : start
  const offset = clampOffset(layout.offset, layout)
  const next =
    end - start > layout.viewportWidth
      ? start + (end - start - layout.viewportWidth) / 2
      : start < offset
        ? start
        : end > offset + layout.viewportWidth
          ? end - layout.viewportWidth
          : offset
  return clampOffset(next, layout)
}

/** first/last are inclusive confirmed-card ordinals; off-sequence ranges are
 * allowed (e.g. a window containing only a preview). No event data is accepted.
 */
export function overviewMarks(
  count: number,
  first: number,
  last: number,
  maxMarks = 80,
): { start: number; end: number; visible: boolean }[] {
  ordinal(count)
  ordinal(maxMarks)
  if (
    maxMarks < 1 ||
    !Number.isSafeInteger(first) ||
    !Number.isSafeInteger(last) ||
    first > last
  )
    throw new RangeError("Invalid overview range or mark limit")
  const length = Math.min(count, maxMarks)
  return Array.from({ length }, (_, index) => {
    const start = Math.floor(index * (count / length))
    const end =
      index === length - 1
        ? count - 1
        : Math.floor((index + 1) * (count / length)) - 1
    return { start, end, visible: start <= last && end >= first }
  })
}
