import {
  Accessibility,
  type DragEndEvent,
  type DragOverEvent,
  KeyboardSensor,
  PointerActivationConstraints,
  PointerSensor,
} from "@dnd-kit/dom"
import { DragDropProvider, DragOverlay, useDraggable } from "@dnd-kit/react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { useCallback, useEffect, useRef, useState } from "react"
import type { PendingCard, PlaceCommand, RunPublic } from "@/client"
import { Button } from "@/components/ui/button"
import useAuth from "@/hooks/useAuth"
import { extractErrorMessage } from "@/utils"
import { gameFailure, getRun, placeCard, renewRunLogin } from "./api"
import { ContentIssueDialog } from "./ContentIssueDialog"
import { formatYear } from "./config"
import { GameCard } from "./GameCard"
import { GameResults } from "./GameResults"
import { SlotLockContext } from "./InsertionSlot"
import { Timeline } from "./Timeline"
import "./game.css"
import {
  acceptRun,
  beginPlacement,
  markUncertain,
  type PlacementState,
  selectSlot,
} from "./placementState"

export function GameBoard({ runId }: { runId: string }): React.JSX.Element {
  const { user } = useAuth()
  return user ? (
    <OwnedBoard key={`${user.id}:${runId}`} runId={runId} ownerId={user.id} />
  ) : (
    <p role="status">Loading account…</p>
  )
}

function OwnedBoard({
  runId,
  ownerId,
}: {
  runId: string
  ownerId: string
}): React.JSX.Element {
  const [state, setState] = useState<PlacementState | null>(null)
  const current = useRef<PlacementState | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [dragMessage, setDragMessage] = useState("")
  const [dragging, setDragging] = useState(false)
  const mounted = useRef(true)
  const queryClient = useQueryClient()
  const storageKey = `game-placement:${ownerId}:${runId}`
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const update = useCallback(
    (next: PlacementState) => {
      current.current = next // Synchronous guard against duplicate click/late callbacks.
      setState(next)
      if (next.command)
        sessionStorage.setItem(storageKey, JSON.stringify(next.command))
      else sessionStorage.removeItem(storageKey)
    },
    [storageKey],
  )
  const query = useQuery({
    queryKey: ["game-run", ownerId, runId],
    queryFn: () => getRun(runId),
    retry: false,
    refetchOnMount: "always",
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
    structuralSharing: (previous, incoming) => {
      const cached = previous as RunPublic | undefined
      const run = incoming as RunPublic
      return cached?.run_id === run.run_id && cached.revision > run.revision
        ? cached
        : run
    },
  })
  function cacheRun(run: RunPublic) {
    if (run.run_id !== runId) return
    queryClient.setQueryData<RunPublic>(
      ["game-run", ownerId, runId],
      (cached) => (cached && cached.revision > run.revision ? cached : run),
    )
  }
  useEffect(() => {
    const run = query.data
    if (!run || run.run_id !== runId) return
    if (current.current) {
      const next = acceptRun(current.current, run)
      if (next !== current.current) {
        update(next)
        setMessage(null)
      }
      return
    }
    // Cached data is not a recovery decision. Wait for a successful owned GET
    // after this observer mounted, including when the returned DTO is unchanged.
    if (!query.isFetchedAfterMount || query.isFetching || query.isError) return
    let saved: PlaceCommand | null = null
    try {
      saved = JSON.parse(sessionStorage.getItem(storageKey) || "null")
    } catch {
      sessionStorage.removeItem(storageKey)
    }
    // A delayed read may even predate the saved command. Never destroy newer
    // recovery information; focus/reconnect or Retry run can obtain a newer read.
    if (saved && saved.expected_revision > run.revision) return
    const recoverable =
      saved &&
      typeof saved.operation_id === "string" &&
      saved.expected_revision === run.revision &&
      saved.event_id === run.pending?.event_id &&
      Number.isInteger(saved.slot) &&
      saved.slot >= 0 &&
      saved.slot <= run.timeline.length &&
      run.status === "active"
    update({
      run,
      selectedSlot: recoverable ? saved!.slot : null,
      command: recoverable ? saved : null,
      phase: recoverable ? "uncertain" : "idle",
    })
  }, [
    query.data,
    query.isFetchedAfterMount,
    query.isFetching,
    query.isError,
    runId,
    storageKey,
    update,
  ])

  async function reconcile() {
    const before = current.current
    if (!before || before.phase === "sending") return
    update({ ...before, phase: "reconcile" })
    try {
      const run = await getRun(runId)
      if (!mounted.current) return
      const latest = current.current
      if (
        latest?.phase !== "reconcile" ||
        latest.command?.operation_id !== before.command?.operation_id ||
        run.run_id !== runId ||
        run.revision < latest.run.revision
      )
        return
      const next = acceptRun(latest, run)
      cacheRun(run)
      // Explicit successful reconciliation (not background polling) permits a new guess.
      update(
        next === latest ? { ...latest, command: null, phase: "idle" } : next,
      )
      setMessage("Server progress checked. You can choose a new placement.")
    } catch (error) {
      if (!mounted.current) return
      if (gameFailure(error) === "auth") {
        renewRunLogin(runId)
        return
      }
      setMessage(
        "Unable to check server progress. Your run is not lost. Retry checking before another guess.",
      )
    }
  }

  async function submit() {
    const before = current.current
    if (!before) return
    const sending = beginPlacement(before, crypto.randomUUID())
    if (sending === before || !sending.command) return
    update(sending)
    setMessage(null)
    const command = sending.command
    try {
      const run = await placeCard(runId, command)
      if (!mounted.current) return
      const latest = current.current
      if (!latest || run.run_id !== runId) return
      cacheRun(run)
      const next = acceptRun(latest, run)
      if (next !== latest) update(next)
      else if (latest.command?.operation_id === command.operation_id)
        update(markUncertain(latest))
    } catch (error) {
      if (!mounted.current) return
      const latest = current.current
      if (!latest || latest.command?.operation_id !== command.operation_id)
        return
      const failure = gameFailure(error)
      if (failure === "auth") {
        update(markUncertain(latest))
        renewRunLogin(runId)
        return
      }
      if (failure === "conflict") {
        update({ ...latest, phase: "reconcile" })
        setMessage(
          "Another move changed this run. Checking authoritative progress…",
        )
        await reconcile()
      } else if (failure === "validation" || failure === "rejected") {
        update({ ...latest, phase: "idle", command: null })
        setMessage(
          `${failure === "validation" ? "Invalid placement" : "Placement rejected"}: ${extractErrorMessage(error instanceof Error ? error : new Error("Request rejected"))}. Your run is not lost; your preview is preserved.`,
        )
      } else {
        update(markUncertain(latest))
        setMessage(
          failure === "unavailable"
            ? "Game service unavailable. This move may have committed; your run is not lost. Retry the same move or check server progress."
            : "The move response was not received. It may have committed; your run is not lost. Retry the same move or check server progress.",
        )
      }
    }
  }

  if (!state)
    return (
      <div className="space-y-3">
        <h1 className="text-2xl">
          {query.error ? "Run unavailable" : "Loading run…"}
        </h1>
        {query.error && (
          <p role="alert">
            Unable to read this run. This does not erase your history.
          </p>
        )}
        {!query.isFetching && (
          <Button onClick={() => query.refetch()}>Retry run</Button>
        )}
      </div>
    )
  const run = state.run
  const locked = state.phase !== "idle" || run.status !== "active"
  function preview(slot: number | null, scroll = false) {
    if (!current.current) return
    update(selectSlot(current.current, slot))
    if (scroll && slot !== null)
      document.querySelector(`[data-slot="${slot}"]`)?.scrollIntoView({
        block: "nearest",
        inline: "nearest",
        behavior: "instant",
      })
  }
  return (
    <div className="game-table">
      <header className="game-heading">
        <div>
          <p className="game-eyebrow">A little history. A little instinct.</p>
          <h1>{run.mode === "daily" ? "Daily run" : "Freeplay run"}</h1>
          <p>
            {run.mode === "daily"
              ? `Daily · ${run.daily_date} UTC`
              : "Freeplay"}
          </p>
        </div>
        <div className="game-stats">
          <p>Streak: {run.streak}</p>
          <p>Status: {run.status}</p>
          <p data-testid="run-revision">Revision: {run.revision}</p>
        </div>
      </header>
      {(message || query.error) && (
        <p role="alert">
          {message ||
            "Server progress is temporarily unavailable. Your history has not been erased."}
        </p>
      )}
      {run.feedback && (
        <div
          key={run.revision}
          data-testid="move-feedback"
          role="status"
          aria-live="polite"
          className={`move-feedback move-feedback-${run.feedback.correct ? "correct" : "wrong"}`}
        >
          <strong>
            {run.feedback.correct
              ? "Correct — beautifully placed!"
              : `Correct slot ${run.feedback.correct_slot + 1} — this card belongs here.`}
          </strong>
          <p>
            {run.feedback.card.prompt} · {formatYear(run.feedback.card.year)}
          </p>
          <p>{run.feedback.card.explanation}</p>
          <p>
            {run.feedback.correct
              ? `Streak: ${run.streak}`
              : "Your final streak is preserved."}
          </p>
        </div>
      )}
      <DragDropProvider
        sensors={[
          PointerSensor.configure({
            activationConstraints: [
              new PointerActivationConstraints.Distance({ value: 6 }),
              new PointerActivationConstraints.Delay({
                value: 200,
                tolerance: 10,
              }),
            ],
          }),
          TimelineKeyboardSensor,
        ]}
        plugins={(defaults) => [
          ...defaults.filter((plugin) => plugin !== Accessibility),
          Accessibility.configure({
            announcements: {
              dragstart: () =>
                "Next card lifted. Choose a numbered slot. Escape cancels. Dropping only previews.",
              dragover: ({ operation }: DragOverEvent) =>
                operation.target
                  ? `Over slot ${Number(operation.target.data.slot) + 1}.`
                  : "Outside the timeline slots.",
              dragend: ({ operation, canceled }: DragEndEvent) =>
                canceled || !operation.target
                  ? "Drag canceled. No move submitted."
                  : `Preview slot ${Number(operation.target.data.slot) + 1}. Lock it in to submit.`,
            },
          }),
        ]}
        onDragStart={() => {
          setDragging(true)
          setDragMessage("Card lifted. Drop into a numbered slot to preview.")
        }}
        onDragEnd={({ operation, canceled }) => {
          setDragging(false)
          const latest = current.current
          if (
            latest?.phase !== "idle" ||
            operation.source?.id !== latest.run.pending?.event_id
          )
            return
          const slot =
            !canceled && operation.target ? operation.target.data.slot : null
          preview(typeof slot === "number" ? slot : null)
          setDragMessage(
            typeof slot === "number"
              ? "Drop previewed. No move submitted."
              : "Drag canceled. No move submitted.",
          )
        }}
      >
        <SlotLockContext.Provider value={locked}>
          <div className="game-workspace">
            {run.status === "active" && run.pending && (
              <section data-testid="pending-card" className="pending-panel">
                <h2>Next card</h2>
                <PendingDraggable card={run.pending} disabled={locked} />
                <p
                  className="placement-instructions"
                  id="placement-instructions"
                >
                  Drag or tap a numbered gap, then Lock it in. The year stays
                  hidden until the server scores your guess. Keyboard: Space to
                  lift, arrows to move, Space to drop, Escape to cancel.
                </p>
                <fieldset
                  className="slot-shortcuts"
                  aria-label="Placement shortcuts"
                >
                  <button
                    type="button"
                    disabled={locked || dragging}
                    onClick={() => preview(0, true)}
                  >
                    First slot
                  </button>
                  <button
                    type="button"
                    disabled={locked || dragging}
                    onClick={() =>
                      preview(Math.max(0, (state.selectedSlot ?? 1) - 1), true)
                    }
                  >
                    Previous slot
                  </button>
                  <button
                    type="button"
                    disabled={locked || dragging}
                    onClick={() =>
                      preview(
                        Math.min(
                          run.timeline.length,
                          (state.selectedSlot ?? -1) + 1,
                        ),
                        true,
                      )
                    }
                  >
                    Next slot
                  </button>
                  <button
                    type="button"
                    disabled={locked || dragging}
                    onClick={() => preview(run.timeline.length, true)}
                  >
                    Last slot
                  </button>
                </fieldset>
                <p role="status" className="preview-status">
                  {state.selectedSlot === null
                    ? "No slot selected."
                    : `Preview: slot ${state.selectedSlot + 1}.`}
                  {state.phase === "sending" && " Sending move…"}
                  {state.phase === "reconcile" && " Checking server progress…"}
                </p>
                <p className="sr-only" role="status">
                  {dragMessage}
                </p>
                <div className="placement-actions">
                  <Button
                    onClick={submit}
                    disabled={locked || dragging || state.selectedSlot === null}
                  >
                    Lock it in
                  </Button>
                  <Button
                    variant="outline"
                    disabled={locked || dragging || state.selectedSlot === null}
                    onClick={() => update(selectSlot(current.current!, null))}
                  >
                    Cancel preview
                  </Button>
                  {state.phase === "uncertain" && (
                    <Button onClick={submit}>Retry same move</Button>
                  )}
                  {(state.phase === "uncertain" ||
                    state.phase === "reconcile") && (
                    <Button variant="outline" onClick={reconcile}>
                      Check server progress
                    </Button>
                  )}
                </div>
                <ContentIssueDialog
                  runId={runId}
                  eventId={run.pending.event_id}
                />
              </section>
            )}
            <Timeline
              cards={run.timeline}
              selectedSlot={state.selectedSlot}
              onSelectSlot={(slot) => preview(slot)}
            />
          </div>
          <DragOverlay dropAnimation={null}>
            {run.pending && (
              <div className="game-drag-overlay" aria-hidden="true">
                <GameCard card={run.pending} revealed={false} />
              </div>
            )}
          </DragOverlay>
        </SlotLockContext.Provider>
      </DragDropProvider>
      {run.status !== "active" && (
        <div
          className={
            run.status === "won"
              ? "game-victory"
              : "move-feedback move-feedback-wrong"
          }
          aria-live="polite"
        >
          <GameResults run={run} />
        </div>
      )}
      <footer className="game-footer">
        {run.status === "active" && run.mode === "freeplay" && (
          <p>
            <Link to="/freeplay" className="underline">
              New Freeplay
            </Link>{" "}
            — this run stays resumable from Home.
          </p>
        )}
        <Link to="/" className="underline">
          Back to Home
        </Link>
      </footer>
    </div>
  )
}

function PendingDraggable({
  card,
  disabled,
}: {
  card: PendingCard
  disabled: boolean
}): React.JSX.Element {
  const { ref, handleRef, isDragging } = useDraggable({
    id: card.event_id,
    disabled,
  })
  return (
    <div ref={ref} className="pending-draggable" data-dragging={isDragging}>
      <GameCard card={card} revealed={false} />
      <button
        type="button"
        ref={handleRef}
        className="drag-handle"
        aria-label="Drag next card"
        aria-describedby="placement-instructions"
        disabled={disabled}
      >
        ⠿ Drag card <span aria-hidden="true">↔</span>
      </button>
    </div>
  )
}

// Stable 0.5.0's KeyboardSensor moves pixels and disables auto-scroll. Numbered
// gaps need discrete, reachable navigation instead, while its activation,
// cancellation, end handling and focus restoration remain intact.
class TimelineKeyboardSensor extends KeyboardSensor {
  private slotIndex: number | null = null
  private frame: number | null = null

  protected override cleanup(): void {
    this.slotIndex = null
    if (this.frame !== null) cancelAnimationFrame(this.frame)
    this.frame = null
    super.cleanup()
  }

  protected override handleMove(
    direction: "up" | "down" | "left" | "right",
    event: KeyboardEvent,
  ): void {
    const workspace =
      this.manager.dragOperation.source?.element?.closest(".game-workspace")
    const slots = workspace?.querySelectorAll<HTMLButtonElement>(
      ".insertion-slot[data-slot]:not(:disabled)",
    )
    if (!slots?.length) return
    event.preventDefault()
    const forward = direction === "right" || direction === "down"
    const currentSlot = this.slotIndex
    const next =
      typeof currentSlot === "number"
        ? currentSlot + (forward ? 1 : -1)
        : forward
          ? 0
          : slots.length - 1
    this.slotIndex = Math.max(0, Math.min(slots.length - 1, next))
    const slot = slots[this.slotIndex]
    slot.scrollIntoView({
      block: "nearest",
      inline: "nearest",
      behavior: "instant",
    })
    // Keyboard navigation is ordinal, not pixel collision: scrolling a clipped
    // horizontal table must not redirect the selected gap to another card.
    if (this.frame !== null) cancelAnimationFrame(this.frame)
    this.frame = requestAnimationFrame(() => {
      this.frame = null
      if (!this.manager.dragOperation.status.dragging) return
      void this.manager.actions.setDropTarget(`slot-${slot.dataset.slot}`)
    })
  }
}
