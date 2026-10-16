import {
  Accessibility,
  AutoScroller,
  type DragEndEvent,
  Feedback,
  PointerActivationConstraints,
  PointerSensor,
} from "@dnd-kit/dom"
import { DragDropProvider } from "@dnd-kit/react"
import { Link } from "@tanstack/react-router"
import { useEffect, useRef } from "react"
import type { GameSessionPublic } from "@/client"
import { Button } from "@/components/ui/button"
import { overviewMarks, visibleConfirmedRange } from "./boardGeometry"
import { ContentIssueDialog } from "./ContentIssueDialog"
import { GameCreditsDialog } from "./GameCreditsDialog"
import { GameResults } from "./GameResults"
import { isProtocolUpgradeError, protocolUpgradeMessage } from "./gameProtocol"
import { lossTimeline } from "./lossTimeline"
import { TimelineLockContext } from "./PendingTile"
import { TimelineOverview } from "./TimelineOverview"
import { TimelineStage } from "./TimelineStage"
import { useOwnedRun } from "./useOwnedRun"
import { useTimelineInteraction } from "./useTimelineInteraction"
import "./game.css"

export function GameBoard({
  runId,
  context,
}: {
  runId: string
  context: GameSessionPublic
}) {
  return (
    <OwnedBoard
      key={`${context.context_id}:${runId}`}
      runId={runId}
      context={context}
    />
  )
}
function OwnedBoard({
  runId,
  context,
}: {
  runId: string
  context: GameSessionPublic
}) {
  const owned = useOwnedRun(runId, context)
  // Mount the measured interaction only once an authoritative owned read exists.
  if (!owned.state)
    return (
      <div className="space-y-3">
        <h1 className="text-2xl">
          {owned.readError || owned.message
            ? "Run unavailable"
            : "Loading run…"}
        </h1>
        {(owned.readError || owned.message) && (
          <p role="alert">
            {owned.message ||
              (isProtocolUpgradeError(owned.readError)
                ? protocolUpgradeMessage
                : "Unable to read this run. This does not erase your history.")}
          </p>
        )}
        {!owned.loading && <Button onClick={owned.retryRead}>Retry run</Button>}
      </div>
    )
  return <BoardSurface owned={owned} runId={runId} context={context} />
}
function BoardSurface({
  owned,
  runId,
  context,
}: {
  owned: ReturnType<typeof useOwnedRun>
  runId: string
  context: GameSessionPublic
}) {
  const state = owned.state!
  const run = state.run
  const locked =
    state.phase !== "idle" || run.status !== "active" || owned.reviewingMistake
  const display = lossTimeline(run, owned.reviewingMistake)
  const continueRef = useRef<HTMLButtonElement>(null)
  const interaction = useTimelineInteraction({
    count: display.items.length,
    selectedSlot: state.selectedSlot,
    locked,
    eventId: run.pending?.event_id ?? null,
    contextId: context.context_id,
    revision: run.revision,
    onPreview: owned.select,
  })
  const { layout } = interaction
  useEffect(() => {
    if (display.attemptedSlot !== null)
      interaction.centerCard(display.attemptedSlot)
    else if (run.feedback?.correct)
      interaction.reveal(run.feedback.correct_slot)
  }, [
    display.attemptedSlot,
    run.feedback,
    interaction.reveal,
    interaction.centerCard,
  ])
  useEffect(() => {
    if (owned.reviewingMistake) continueRef.current?.focus()
    else if (run.status === "active")
      document.querySelector<HTMLElement>(".pending-draggable")?.focus()
    else document.querySelector<HTMLElement>(".game-results h2")?.focus()
  }, [owned.reviewingMistake, run.status])
  const visible = visibleConfirmedRange(layout)
  const cards = [
    ...run.timeline,
    ...(run.pending ? [run.pending] : []),
    ...(run.feedback ? [run.feedback.card] : []),
  ]
  return (
    <div className="game-table">
      <header className="game-heading">
        <div>
          <h1>{run.mode === "daily" ? "Daily run" : "Freeplay run"}</h1>
          {run.mode === "daily" && <p>Daily · {run.daily_date} UTC</p>}
        </div>
        <div className="game-stats">
          <p>
            <span className="game-lives">
              <span className="game-life-indicators" aria-hidden="true">
                {Array.from({ length: run.initial_lives }, (_, index) => (
                  <span
                    key={index}
                    className="game-life"
                    data-state={
                      index < run.lives_remaining ? "remaining" : "spent"
                    }
                  >
                    {index < run.lives_remaining ? "♥" : "♡"}
                  </span>
                ))}
              </span>
              <span>
                Lives: {run.lives_remaining} of {run.initial_lives}
              </span>
            </span>
            {" · Score: "}
            {run.score}
          </p>
          <p>Streak: {run.streak}</p>
          <p>Status: {run.status}</p>
          <p data-testid="run-revision">Revision: {run.revision}</p>
        </div>
      </header>
      {(owned.message || owned.readError) && (
        <p role="alert" className="game-alert">
          {owned.message ||
            "Server progress is temporarily unavailable. Your history has not been erased."}
        </p>
      )}
      {run.feedback && (
        <p
          data-testid="move-feedback"
          role="status"
          className={`move-feedback ${run.feedback.correct ? "move-feedback-correct" : "move-feedback-wrong"}`}
        >
          {run.feedback.correct
            ? "Correct — beautifully placed!"
            : `Incorrect — ${run.lives_remaining} ${run.lives_remaining === 1 ? "life" : "lives"} left. The correct location is marked.`}
        </p>
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
        ]}
        plugins={(defaults) => [
          ...defaults.filter(
            (plugin) =>
              plugin !== AutoScroller &&
              plugin !== Accessibility &&
              plugin !== Feedback,
          ),
          Feedback.configure({ feedback: "move", dropAnimation: null }),
          Accessibility.configure({
            screenReaderInstructions: {
              draggable:
                "Space or Enter lifts this card. Arrows choose a position, Space or Enter drops, Escape cancels. Activate Confirm to submit.",
            },
            announcements: {
              dragstart: () =>
                "Card lifted. Drop only previews; Confirm submits.",
              dragmove: () =>
                interaction.hoveredSlot === null
                  ? "Outside the timeline. Your prior preview is preserved."
                  : `Position ${interaction.hoveredSlot + 1} of ${run.timeline.length + 1}.`,
              dragend: ({ canceled }: DragEndEvent) =>
                canceled
                  ? "Canceled. No move submitted."
                  : "Preview ready. Confirm to submit.",
            },
          }),
        ]}
        onDragStart={interaction.start}
        onDragMove={interaction.move}
        onDragEnd={({ canceled }: DragEndEvent) => interaction.end(canceled)}
      >
        <TimelineLockContext.Provider value={locked}>
          <TimelineStage
            items={display.items}
            pending={
              run.status === "active" && !owned.reviewingMistake
                ? run.pending
                : null
            }
            previewSlot={state.selectedSlot}
            correctDisplaySlot={display.correctDisplaySlot}
            onConfirm={owned.submit}
            canConfirm={
              !locked &&
              !interaction.dragging &&
              state.selectedSlot !== null &&
              state.phase === "idle"
            }
            interaction={interaction}
          />
        </TimelineLockContext.Provider>
      </DragDropProvider>
      <TimelineOverview
        marks={overviewMarks(
          display.items.length,
          visible?.first ?? -1,
          visible?.last ?? -1,
        )}
        previewSlot={state.selectedSlot}
        correctSlot={display.correctDisplaySlot}
        onNavigate={interaction.reveal}
      />
      {owned.reviewingMistake ? (
        <section className="game-controls" aria-label="Mistake review">
          <Button ref={continueRef} onClick={owned.continueAfterMistake}>
            Continue
          </Button>
        </section>
      ) : run.status === "active" && run.pending ? (
        <section className="game-controls" aria-label="Placement controls">
          <p id="placement-instructions">
            Move the card into the timeline, then use its Confirm button.
            Space/Enter and arrows choose a position.
          </p>
          <p role="status" className="preview-status">
            {interaction.dragging
              ? `Card lifted${interaction.hoveredSlot === null ? " — outside timeline" : ` · position ${interaction.hoveredSlot + 1}`}.`
              : state.selectedSlot === null
                ? "No placement selected."
                : "Unlocked preview — ready to place."}
            {state.phase === "sending" && " Sending move…"}
            {state.phase === "reconcile" && " Checking server progress…"}
          </p>
          <div className="placement-actions">
            <Button
              variant="outline"
              disabled={
                locked || interaction.dragging || state.selectedSlot === null
              }
              onClick={() => owned.select(null)}
            >
              Return to hand
            </Button>
            {state.phase === "uncertain" && (
              <Button onClick={owned.submit}>Retry same move</Button>
            )}
            {(state.phase === "uncertain" || state.phase === "reconcile") && (
              <Button variant="outline" onClick={owned.reconcile}>
                Check server progress
              </Button>
            )}
          </div>
        </section>
      ) : (
        <GameResults run={run} context={context} />
      )}
      <footer className="game-footer">
        <GameCreditsDialog cards={cards} />
        <ContentIssueDialog
          runId={runId}
          eventId={
            run.pending?.event_id ??
            run.feedback?.card.event_id ??
            run.timeline[run.timeline.length - 1].event_id
          }
        />
        {run.status === "active" && run.mode === "freeplay" && (
          <Link to="/freeplay">New Freeplay</Link>
        )}
        <Link to="/">Back to Home</Link>
      </footer>
    </div>
  )
}
