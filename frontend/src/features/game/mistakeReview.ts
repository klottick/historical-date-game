import type { RunPublic } from "../../client/types.gen.ts"

const ACKNOWLEDGEMENT = "acknowledged"

export function mistakeReviewKey(
  contextId: string,
  runId: string,
  revision: number,
): string {
  return `game-mistake-review:v1:${encodeURIComponent(contextId)}:${encodeURIComponent(runId)}:${revision}`
}

export function needsMistakeReview(
  run: RunPublic,
  acknowledged: boolean,
): boolean {
  return Boolean(
    !acknowledged && run.feedback?.correct === false && run.lives_remaining > 0,
  )
}

export function isMistakeReviewAcknowledgement(value: unknown): boolean {
  return value === ACKNOWLEDGEMENT
}

export function mistakeReviewAcknowledgement(): string {
  return ACKNOWLEDGEMENT
}
