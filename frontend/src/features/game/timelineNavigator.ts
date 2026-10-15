import {
  type BoardLayout,
  clampOffset,
  offsetToReveal,
} from "./boardGeometry.ts"

export type TimelineNavigator = {
  track(point: { x: number; y: number } | null): void
  reveal(slot: number): void
  stop(): void
  dispose(): void
}

/** Owns only window displacement, never scoring, collision state or page scroll.
 * getLayout returns current CSS-pixel geometry; onOffset must synchronously
 * publish the new offset to that layout. The caller owns previewSlot and can
 * recompute it with insertionIndex after each pan. stop ends this operation;
 * dispose permanently releases its resources (safe to call more than once).
 */
export function createTimelineNavigator(
  viewport: HTMLElement,
  getLayout: () => BoardLayout,
  onOffset: (offset: number) => void,
): TimelineNavigator {
  const document = viewport.ownerDocument
  const view = document.defaultView
  if (!view) throw new Error("Timeline viewport has no browser window")
  // Validate up front rather than schedule frames with poisoned geometry.
  const initial = getLayout()
  clampOffset(initial.offset, initial)
  let point: { x: number; y: number } | null = null
  let revealSlot: number | null = null
  let frame: number | null = null
  let lastTime = 0
  let active = false
  let disposed = false
  let size = { width: 0, height: 0 }

  function publish(offset: number, layout: BoardLayout): void {
    if (offset !== layout.offset) onOffset(offset)
  }

  function velocity(): number {
    if (!point) return 0
    const rect = viewport.getBoundingClientRect()
    if (
      point.y < rect.top ||
      point.y > rect.bottom ||
      point.x < rect.left ||
      point.x > rect.right ||
      rect.width <= 0
    )
      return 0
    const left = point.x - rect.left
    const right = rect.right - point.x
    const distance = Math.min(left, right)
    return distance >= 48
      ? 0
      : (left < right ? -1 : 1) * Math.min(420, (420 * (48 - distance)) / 48)
  }

  function cancelFrame(): void {
    if (frame !== null) view!.cancelAnimationFrame(frame)
    frame = null
  }

  function schedule(): void {
    if (
      !disposed &&
      point &&
      frame === null &&
      velocity() !== 0 &&
      !document.hidden
    )
      frame = view!.requestAnimationFrame(tick)
  }

  function tick(time: number): void {
    frame = null
    if (disposed || !point || document.hidden) {
      stop()
      return
    }
    const elapsed = Math.max(0, Math.min(50, time - lastTime)) / 1000
    lastTime = time
    try {
      const layout = getLayout()
      const offset = clampOffset(layout.offset, layout)
      const next = clampOffset(offset + velocity() * elapsed, layout)
      publish(next, layout)
      // At an end, leave no busy RAF loop. A new point/resize can restart it.
      // A RAF timestamp can precede track()'s performance.now() in the same
      // repaint. Zero elapsed time is not a sequence end: keep the next frame.
      if (clampOffset(next + velocity(), layout) !== next) schedule()
    } catch (error) {
      stop()
      throw error
    }
  }

  function resize(): void {
    if (!active || disposed) return
    const rect = viewport.getBoundingClientRect()
    if (rect.width === size.width && rect.height === size.height) return
    size = { width: rect.width, height: rect.height }
    try {
      const layout = getLayout()
      const target = revealSlot ?? layout.previewSlot
      const next =
        target === null
          ? clampOffset(layout.offset, layout)
          : offsetToReveal(target, layout)
      publish(next, layout)
      lastTime = view!.performance.now()
      schedule()
    } catch (error) {
      stop()
      throw error
    }
  }

  const observer = new ResizeObserver(resize)
  function visibility(): void {
    if (document.hidden) stop()
  }
  function focusout(event: FocusEvent): void {
    if (!event.relatedTarget || !viewport.contains(event.relatedTarget as Node))
      stop()
  }
  function attach(): void {
    if (active) return
    active = true
    const rect = viewport.getBoundingClientRect()
    size = { width: rect.width, height: rect.height }
    observer.observe(viewport)
    document.addEventListener("pointerup", stop)
    document.addEventListener("pointercancel", stop)
    document.addEventListener("visibilitychange", visibility)
    viewport.addEventListener("lostpointercapture", stop)
    // The focused pending-card hand can be outside the timeline viewport.
    document.addEventListener("focusout", focusout)
    view!.addEventListener("blur", stop)
  }

  function stop(): void {
    point = null
    revealSlot = null
    cancelFrame()
    observer.disconnect()
    active = false
    document.removeEventListener("pointerup", stop)
    document.removeEventListener("pointercancel", stop)
    document.removeEventListener("visibilitychange", visibility)
    viewport.removeEventListener("lostpointercapture", stop)
    document.removeEventListener("focusout", focusout)
    view!.removeEventListener("blur", stop)
  }

  return {
    track(next) {
      if (disposed) return
      if (next === null || document.hidden) {
        stop()
        return
      }
      if (!Number.isFinite(next.x) || !Number.isFinite(next.y)) {
        stop()
        throw new RangeError("Expected finite client coordinates")
      }
      point = { ...next }
      revealSlot = null
      attach()
      if (frame === null) lastTime = view.performance.now()
      if (velocity() === 0) cancelFrame()
      else schedule()
    },
    reveal(slot) {
      if (disposed) return
      const layout = getLayout()
      const offset = offsetToReveal(slot, layout)
      stop()
      revealSlot = slot
      attach()
      publish(offset, layout)
    },
    stop,
    dispose() {
      stop()
      disposed = true
    },
  }
}
