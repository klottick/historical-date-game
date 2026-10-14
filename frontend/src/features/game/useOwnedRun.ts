import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useRef, useState } from "react"
import type { GameSessionPublic, PlaceCommand, RunPublic } from "@/client"
import { extractErrorMessage } from "@/utils"
import {
  adoptAccountPlacement,
  gameFailure,
  getRun,
  isCurrentGameContext,
  placeCard,
} from "./api"
import { useGameSession, useGameSessionError } from "./GameSessionProvider"
import {
  gameQueryKey,
  placementStorageKey,
  sessionFailure,
} from "./identityState"
import { operationId } from "./operationId"
import {
  acceptRun,
  beginPlacement,
  markUncertain,
  type PlacementState,
  selectSlot,
} from "./placementState"

// Owned commands and recovery are deliberately independent of visual interaction.
export function useOwnedRun(runId: string, context: GameSessionPublic) {
  const [state, setState] = useState<PlacementState | null>(null)
  const current = useRef<PlacementState | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const mounted = useRef(true)
  const queryClient = useQueryClient()
  const { failSession } = useGameSession()
  const storageKey = placementStorageKey(context.context_id, runId)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const update = useCallback(
    (next: PlacementState) => {
      if (!isCurrentGameContext(context)) return
      current.current = next
      setState(next)
      if (next.command)
        sessionStorage.setItem(storageKey, JSON.stringify(next.command))
      else sessionStorage.removeItem(storageKey)
    },
    [storageKey, context],
  )
  const query = useQuery({
    queryKey: gameQueryKey(context.context_id, "run", runId),
    queryFn: ({ signal }) => getRun(runId, context, signal),
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
    if (run.run_id !== runId || !isCurrentGameContext(context)) return
    queryClient.setQueryData<RunPublic>(
      gameQueryKey(context.context_id, "run", runId),
      (cached) => (cached && cached.revision > run.revision ? cached : run),
    )
  }
  useGameSessionError(query.error, context)
  useEffect(() => {
    const run = query.data
    if (!run || run.run_id !== runId || !isCurrentGameContext(context)) return
    if (current.current) {
      const next = acceptRun(current.current, run)
      if (next !== current.current) {
        update(next)
        setMessage(null)
      }
      return
    }
    // Cached data is not a recovery decision: require a successful mounted GET.
    if (!query.isFetchedAfterMount || query.isFetching || query.isError) return
    try {
      adoptAccountPlacement(context, storageKey, runId)
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Recovery unavailable",
      )
      return
    }
    let saved: PlaceCommand | null = null
    try {
      saved = JSON.parse(sessionStorage.getItem(storageKey) || "null")
    } catch {
      sessionStorage.removeItem(storageKey)
    }
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
    context,
  ])
  async function reconcile() {
    const before = current.current
    if (!before || before.phase === "sending") return
    update({ ...before, phase: "reconcile" })
    try {
      const run = await getRun(runId, context)
      if (!mounted.current || !isCurrentGameContext(context)) return
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
      update(
        next === latest ? { ...latest, command: null, phase: "idle" } : next,
      )
      setMessage("Server progress checked. You can choose a new placement.")
    } catch (error) {
      if (!mounted.current || !isCurrentGameContext(context)) return
      if (sessionFailure(error)) {
        failSession(error)
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
    const sending = beginPlacement(
      before,
      before.command?.operation_id ?? operationId(),
    )
    if (sending === before || !sending.command) return
    update(sending)
    setMessage(null)
    const command = sending.command
    try {
      const run = await placeCard(runId, command, context)
      if (!mounted.current || !isCurrentGameContext(context)) return
      const latest = current.current
      if (!latest || run.run_id !== runId) return
      cacheRun(run)
      const next = acceptRun(latest, run)
      if (next !== latest) update(next)
      else if (latest.command?.operation_id === command.operation_id)
        update(markUncertain(latest))
    } catch (error) {
      if (!mounted.current || !isCurrentGameContext(context)) return
      const latest = current.current
      if (!latest || latest.command?.operation_id !== command.operation_id)
        return
      const failure = gameFailure(error)
      if (sessionFailure(error)) {
        update(markUncertain(latest))
        failSession(error)
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
  function select(slot: number | null) {
    if (current.current) update(selectSlot(current.current, slot))
  }
  return {
    state,
    message,
    loading: query.isFetching,
    readError: query.error,
    select,
    submit,
    reconcile,
    retryRead: () => {
      void query.refetch()
    },
  }
}
