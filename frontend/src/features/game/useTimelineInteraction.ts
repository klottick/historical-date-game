import type { DragMoveEvent, DragStartEvent } from "@dnd-kit/dom"
import { type RefObject, useCallback, useEffect, useRef, useState } from "react"
import { type BoardLayout, clampOffset, insertionIndex } from "./boardGeometry"
import {
  createTimelineNavigator,
  type TimelineNavigator,
} from "./timelineNavigator"

export type TimelineInteraction = {
  dragging: boolean
  hoveredSlot: number | null
  viewportRef: RefObject<HTMLDivElement | null>
  offset: number
  layout: BoardLayout
  start(event: DragStartEvent): void
  move(event: DragMoveEvent): void
  end(canceled: boolean): void
  cancel(): void
  keyboard(event: KeyboardEvent): void
  reveal(slot: number): void
  centerCard(index: number): void
}
export function useTimelineInteraction(args: {
  count: number
  selectedSlot: number | null
  locked: boolean
  eventId: string | null
  contextId: string
  revision: number
  onPreview: (slot: number | null) => void
}): TimelineInteraction {
  const viewportRef = useRef<HTMLDivElement>(null)
  const latest = useRef(args)
  latest.current = args
  const [dragging, setDragging] = useState(false)
  const [hoveredSlot, setHoveredSlot] = useState<number | null>(null)
  const [, setOffset] = useState(0)
  const [dimensions, setDimensions] = useState({
    cardWidth: 230,
    gap: 16,
    viewportWidth: 1,
  })
  const active = useRef(false)
  const hover = useRef<number | null>(null)
  const pointer = useRef<{ x: number; y: number } | null>(null)
  const ordinal = useRef(false)
  const stopDrag = useRef<(() => void) | null>(null)
  const settleFrame = useRef<number | null>(null)
  const settleAnimation = useRef<Animation | null>(null)
  const centeredCard = useRef<number | null>(null)
  const navigator = useRef<TimelineNavigator | null>(null)
  const geometry = useRef<BoardLayout>({
    count: args.count,
    ...dimensions,
    offset: 0,
    previewSlot: args.selectedSlot,
  })
  // Ref publication is synchronous; RAF collision math must never read old offset.
  geometry.current = {
    ...geometry.current,
    count: args.count,
    ...dimensions,
    previewSlot: active.current ? hover.current : args.selectedSlot,
  }
  geometry.current.offset = clampOffset(
    geometry.current.offset,
    geometry.current,
  )
  const publishHover = useCallback((slot: number | null) => {
    hover.current = slot
    geometry.current.previewSlot = slot
    setHoveredSlot(slot)
  }, [])
  const target = useCallback(() => {
    const point = pointer.current
    const rect = viewportRef.current?.getBoundingClientRect()
    if (
      !point ||
      !rect ||
      point.x < rect.left ||
      point.x > rect.right ||
      point.y < rect.top ||
      point.y > rect.bottom
    )
      return null
    return insertionIndex(point.x - rect.left, geometry.current)
  }, [])
  const cancel = useCallback(() => {
    active.current = false
    pointer.current = null
    ordinal.current = false
    navigator.current?.stop()
    setDragging(false)
    publishHover(null)
    const stop = stopDrag.current
    stopDrag.current = null
    stop?.()
    if (settleFrame.current !== null) cancelAnimationFrame(settleFrame.current)
    settleFrame.current = null
    settleAnimation.current?.cancel()
    settleAnimation.current = null
  }, [publishHover])
  useEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) return
    const owner = {
      contextId: args.contextId,
      eventId: args.eventId,
      revision: args.revision,
      locked: args.locked,
    }
    let disposed = false
    const current = () =>
      !disposed &&
      viewport.isConnected &&
      viewportRef.current === viewport &&
      owner.contextId === latest.current.contextId &&
      owner.eventId === latest.current.eventId &&
      owner.revision === latest.current.revision &&
      owner.locked === latest.current.locked
    const measure = () => {
      if (!current()) return
      const style = getComputedStyle(viewport)
      const next = {
        cardWidth: Number.parseFloat(style.getPropertyValue("--card-width")),
        gap: Number.parseFloat(style.getPropertyValue("--card-gap")),
        viewportWidth: viewport.clientWidth,
      }
      // Detached/hidden views and unavailable CSS must not poison the last
      // valid layout used by rendering, collision math or navigator callbacks.
      if (
        !Number.isFinite(next.cardWidth) ||
        next.cardWidth <= 0 ||
        !Number.isFinite(next.gap) ||
        next.gap < 0 ||
        !Number.isFinite(next.viewportWidth) ||
        next.viewportWidth <= 0
      )
        return
      const measured = { ...geometry.current, ...next }
      const index = centeredCard.current
      if (index !== null)
        measured.offset =
          (index +
            (measured.previewSlot !== null && index >= measured.previewSlot
              ? 1
              : 0)) *
            (next.cardWidth + next.gap) +
          next.cardWidth / 2 -
          next.viewportWidth / 2
      const cards = measured.count + (measured.previewSlot === null ? 0 : 1)
      if (
        !Number.isFinite(next.cardWidth + next.gap) ||
        !Number.isFinite(
          cards * next.cardWidth + Math.max(0, cards - 1) * next.gap,
        ) ||
        !Number.isFinite(measured.offset)
      )
        return
      measured.offset = clampOffset(measured.offset, measured)
      geometry.current = measured
      setDimensions(next)
      setOffset(geometry.current.offset)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(viewport)
    const nav = createTimelineNavigator(
      viewport,
      () => geometry.current,
      (value) => {
        if (!current()) return
        geometry.current.offset = value
        setOffset(value)
        if (active.current && !ordinal.current) publishHover(target())
      },
    )
    navigator.current = nav
    const blur = () => cancel()
    const focusout = (event: FocusEvent) => {
      if (
        active.current &&
        !(
          event.relatedTarget instanceof Element &&
          event.relatedTarget.closest(".pending-draggable")
        )
      )
        cancel()
    }
    window.addEventListener("blur", blur)
    document.addEventListener("focusout", focusout)
    return () => {
      disposed = true
      cancel()
      nav.dispose()
      navigator.current = null
      observer.disconnect()
      window.removeEventListener("blur", blur)
      document.removeEventListener("focusout", focusout)
    }
  }, [
    args.contextId,
    args.eventId,
    args.revision,
    args.locked,
    cancel,
    target,
    publishHover,
  ])
  const reveal = useCallback((slot: number) => {
    if (latest.current.locked && latest.current.eventId !== null) return
    centeredCard.current = null
    navigator.current?.reveal(slot)
  }, [])
  // Boundary revelation is not full-card centering. Loss uses this display-only
  // adapter with the same measured layout; no phantom preview stride is added.
  const centerCard = useCallback((index: number) => {
    if (
      !Number.isInteger(index) ||
      index < 0 ||
      index >= geometry.current.count
    )
      return
    navigator.current?.stop()
    centeredCard.current = index
    const layout = geometry.current
    const next = clampOffset(
      (index +
        (layout.previewSlot !== null && index >= layout.previewSlot ? 1 : 0)) *
        (layout.cardWidth + layout.gap) +
        layout.cardWidth / 2 -
        layout.viewportWidth / 2,
      layout,
    )
    geometry.current.offset = next
    setOffset(next)
  }, [])
  function end(canceled: boolean) {
    if (!active.current) return
    const keyboardDrop = ordinal.current
    const slot = ordinal.current ? hover.current : target()
    active.current = false
    stopDrag.current = null
    pointer.current = null
    ordinal.current = false
    navigator.current?.stop()
    setDragging(false)
    publishHover(null)
    if (!canceled && !latest.current.locked && slot !== null) {
      geometry.current.previewSlot = slot
      latest.current.onPreview(slot)
      reveal(slot)
      // A settle is presentation only, never a command or state transition gate.
      settleFrame.current = requestAnimationFrame(() => {
        settleFrame.current = null
        const tile =
          viewportRef.current?.parentElement?.querySelector(
            ".pending-draggable",
          )
        // On narrow layouts the hand is docked below the stage. A keyboard
        // drop moves the same focused element upwards; native focus scrolling
        // does not follow that relayout. Reveal it vertically after publication,
        // without touching the transform-only horizontal navigator or scoring.
        if (keyboardDrop && tile && matchMedia("(max-width: 767px)").matches) {
          const rect = tile.getBoundingClientRect()
          // Native scrollIntoView rounds fractional CSS bounds inward. Round
          // outwards so even a fractional top edge is visible, and scroll only
          // the document vertically (never a second horizontal stage offset).
          const top =
            rect.top < 0
              ? Math.floor(rect.top)
              : Math.max(0, Math.ceil(rect.bottom - innerHeight))
          if (top) window.scrollBy({ top, left: 0, behavior: "instant" })
        }
        settleAnimation.current =
          tile?.animate(
            [{ transform: "translateY(-4px)" }, { transform: "translateY(0)" }],
            {
              duration: matchMedia("(prefers-reduced-motion: reduce)").matches
                ? 0
                : 180,
              easing: "ease-out",
            },
          ) ?? null
      })
    }
  }
  function keyboard(event: KeyboardEvent) {
    if (
      !(event.target instanceof HTMLElement) ||
      !event.target.classList.contains("pending-draggable") ||
      latest.current.locked
    )
      return
    if (
      ![
        " ",
        "Enter",
        "Escape",
        "ArrowLeft",
        "ArrowRight",
        "ArrowUp",
        "ArrowDown",
        "Home",
        "End",
      ].includes(event.key)
    )
      return
    event.preventDefault()
    event.stopPropagation()
    if (event.key === "Escape") {
      cancel()
      return
    }
    if (event.key === " " || event.key === "Enter") {
      if (active.current) {
        end(false)
        return
      }
      active.current = true
      ordinal.current = true
      setDragging(true)
      const slot = latest.current.selectedSlot ?? 0
      publishHover(slot)
      reveal(slot)
      return
    }
    if (!active.current || !ordinal.current) return
    const slot =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? latest.current.count
          : Math.max(
              0,
              Math.min(
                latest.current.count,
                (hover.current ?? 0) +
                  (["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : -1),
              ),
            )
    publishHover(slot)
    reveal(slot)
  }
  return {
    dragging,
    hoveredSlot,
    viewportRef,
    offset: geometry.current.offset,
    layout: { ...geometry.current },
    cancel,
    end,
    keyboard,
    reveal,
    centerCard,
    start(event) {
      if (
        latest.current.locked ||
        event.operation.source?.id !== latest.current.eventId
      )
        return
      active.current = true
      ordinal.current = false
      setDragging(true)
      stopDrag.current = () => {
        void event.operation.source?.manager?.actions.stop({ canceled: true })
      }
      pointer.current = event.operation.position.current
      publishHover(target())
      navigator.current?.track(pointer.current)
    },
    move(event) {
      if (!active.current || ordinal.current || latest.current.locked) return
      pointer.current =
        event.nativeEvent instanceof PointerEvent
          ? { x: event.nativeEvent.clientX, y: event.nativeEvent.clientY }
          : event.operation.position.current
      publishHover(target())
      navigator.current?.track(pointer.current)
    },
  }
}
