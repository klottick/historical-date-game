import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { useCallback, useEffect, useRef, useState } from "react"
import type { PlaceCommand } from "@/client"
import { Button } from "@/components/ui/button"
import useAuth from "@/hooks/useAuth"
import { extractErrorMessage } from "@/utils"
import { gameFailure, getRun, placeCard, renewRunLogin } from "./api"
import { ContentIssueDialog } from "./ContentIssueDialog"
import { CardDetails, GameResults } from "./GameResults"
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
  const storageKey = `game-placement:${ownerId}:${runId}`
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
  })
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
    let saved: PlaceCommand | null = null
    try {
      saved = JSON.parse(sessionStorage.getItem(storageKey) || "null")
    } catch {
      sessionStorage.removeItem(storageKey)
    }
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
  }, [query.data, runId, storageKey, update])

  async function reconcile() {
    const before = current.current
    if (!before || before.phase === "sending") return
    update({ ...before, phase: "reconcile" })
    try {
      const run = await getRun(runId)
      const latest = current.current
      if (
        latest?.phase !== "reconcile" ||
        latest.command?.operation_id !== before.command?.operation_id ||
        run.run_id !== runId ||
        run.revision < latest.run.revision
      )
        return
      const next = acceptRun(latest, run)
      // Explicit successful reconciliation (not background polling) permits a new guess.
      update(
        next === latest ? { ...latest, command: null, phase: "idle" } : next,
      )
      setMessage("Server progress checked. You can choose a new placement.")
    } catch (error) {
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
      const latest = current.current
      if (!latest || run.run_id !== runId) return
      const next = acceptRun(latest, run)
      if (next !== latest) update(next)
      else if (latest.command?.operation_id === command.operation_id)
        update(markUncertain(latest))
    } catch (error) {
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
          <>
            <p role="alert">
              Unable to read this run. This does not erase your history.
            </p>
            <Button onClick={() => query.refetch()}>Retry run</Button>
          </>
        )}
      </div>
    )
  const run = state.run
  return (
    <div className="space-y-6">
      <h1 className="font-serif text-3xl">
        {run.mode === "daily" ? "Daily run" : "Freeplay run"}
      </h1>
      <p>
        {run.mode === "daily" ? `Daily · ${run.daily_date} UTC` : "Freeplay"}
      </p>
      <p>Status: {run.status}</p>
      <p>Streak: {run.streak}</p>
      <p data-testid="run-revision">Revision: {run.revision}</p>
      {(message || query.error) && (
        <p role="alert">
          {message ||
            "Server progress is temporarily unavailable. Your history has not been erased."}
        </p>
      )}
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Your timeline</h2>
        <ol className="space-y-3">
          {run.timeline.map((card) => (
            <li key={card.event_id} className="rounded-xl border p-4">
              <CardDetails card={card} />
            </li>
          ))}
        </ol>
      </section>
      {run.status === "active" && run.pending && (
        <section
          data-testid="pending-card"
          className="space-y-4 rounded-xl border border-[#dba64d]/60 p-4"
        >
          <h2 className="text-xl font-semibold">Next card</h2>
          <p>{run.pending.prompt}</p>
          <p>
            Choose a gap, then Lock it in. Selecting a slot only previews your
            guess; its year stays hidden until the server scores it.
          </p>
          <ul className="text-sm text-muted-foreground">
            {run.pending.media.credits.map((credit) => (
              <li key={`${credit.label}:${credit.url}`}>
                {credit.url ? (
                  <a
                    className="underline"
                    href={credit.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {credit.label}
                  </a>
                ) : (
                  credit.label
                )}
              </li>
            ))}
          </ul>
          <fieldset
            className="flex flex-wrap gap-2"
            aria-label="Timeline slots"
          >
            {Array.from({ length: run.timeline.length + 1 }, (_, slot) => (
              <Button
                key={slot}
                aria-label={`Slot ${slot + 1}`}
                aria-pressed={state.selectedSlot === slot}
                disabled={state.phase !== "idle"}
                variant={state.selectedSlot === slot ? "default" : "outline"}
                onClick={() => update(selectSlot(current.current!, slot))}
              >
                Slot {slot + 1} ·{" "}
                {slot === 0
                  ? "before the first event"
                  : slot === run.timeline.length
                    ? "after the last event"
                    : `between events ${slot} and ${slot + 1}`}
              </Button>
            ))}
          </fieldset>
          <p role="status">
            {state.selectedSlot === null
              ? "No slot selected."
              : `Preview: slot ${state.selectedSlot + 1}.`}
            {state.phase === "sending" && " Sending move…"}
            {state.phase === "reconcile" && " Checking server progress…"}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={submit}
              disabled={state.phase !== "idle" || state.selectedSlot === null}
            >
              Lock it in
            </Button>
            <Button
              variant="outline"
              disabled={state.phase !== "idle" || state.selectedSlot === null}
              onClick={() => update(selectSlot(current.current!, null))}
            >
              Cancel preview
            </Button>
            {state.phase === "uncertain" && (
              <Button onClick={submit}>Retry same move</Button>
            )}
            {(state.phase === "uncertain" || state.phase === "reconcile") && (
              <Button variant="outline" onClick={reconcile}>
                Check server progress
              </Button>
            )}
          </div>
          <ContentIssueDialog runId={runId} eventId={run.pending.event_id} />
        </section>
      )}
      {run.status !== "active" && <GameResults run={run} />}
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
    </div>
  )
}
