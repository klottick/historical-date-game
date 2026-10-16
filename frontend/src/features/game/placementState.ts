import type { PlaceCommand, RunPublic } from "../../client/types.gen.ts"
import { GAME_PROTOCOL_VERSION } from "./gameProtocol.ts"

export type PlacementState = {
  run: RunPublic
  selectedSlot: number | null
  command: PlaceCommand | null
  phase: "idle" | "sending" | "uncertain" | "reconcile"
}

function validSlot(state: PlacementState, slot: number): boolean {
  return (
    Number.isInteger(slot) && slot >= 0 && slot <= state.run.timeline.length
  )
}

export function selectSlot(
  state: PlacementState,
  slot: number | null,
  reviewingMistake = false,
): PlacementState {
  if (
    reviewingMistake ||
    state.phase !== "idle" ||
    state.run.status !== "active" ||
    !state.run.pending ||
    (slot !== null && !validSlot(state, slot))
  )
    return state
  return { ...state, selectedSlot: slot }
}

export function beginPlacement(
  state: PlacementState,
  operationId: string,
  reviewingMistake = false,
): PlacementState {
  if (reviewingMistake) return state
  if (state.phase === "uncertain" && state.command)
    return { ...state, phase: "sending" }
  if (
    state.phase !== "idle" ||
    state.command ||
    state.run.status !== "active" ||
    !state.run.pending ||
    state.selectedSlot === null ||
    !validSlot(state, state.selectedSlot)
  )
    return state
  return {
    ...state,
    phase: "sending",
    command: {
      protocol_version: GAME_PROTOCOL_VERSION,
      operation_id: operationId,
      expected_revision: state.run.revision,
      event_id: state.run.pending.event_id,
      slot: state.selectedSlot,
    },
  }
}

export function acceptRun(
  state: PlacementState,
  run: RunPublic,
): PlacementState {
  // Equal-revision polling says nothing about an outstanding command's outcome.
  if (run.run_id !== state.run.run_id || run.revision <= state.run.revision)
    return state
  return { run, selectedSlot: null, command: null, phase: "idle" }
}

export function markUncertain(state: PlacementState): PlacementState {
  return state.phase === "sending" && state.command
    ? { ...state, phase: "uncertain" }
    : state
}
