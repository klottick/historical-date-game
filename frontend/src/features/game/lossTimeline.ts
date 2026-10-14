import type { RevealedCard, RunPublic } from "../../client/types.gen.ts"

export type TimelineDisplayItem = { card: RevealedCard; wrong: boolean }

export function lossTimeline(run: RunPublic): {
  items: TimelineDisplayItem[]
  attemptedSlot: number | null
  correctSlot: number | null
  correctDisplaySlot: number | null
  legacyWrongCard: RevealedCard | null
} {
  const items = run.timeline.map((card) => ({ card, wrong: false }))
  const feedback =
    run.status === "lost" && run.feedback && !run.feedback.correct
      ? run.feedback
      : null
  const valid = (slot: number | null | undefined): slot is number =>
    typeof slot === "number" &&
    Number.isInteger(slot) &&
    slot >= 0 &&
    slot <= run.timeline.length
  const attemptedSlot =
    feedback && valid(feedback.attempted_slot) ? feedback.attempted_slot : null
  const correctSlot =
    feedback && valid(feedback.correct_slot) ? feedback.correct_slot : null
  if (feedback && attemptedSlot !== null)
    items.splice(attemptedSlot, 0, { card: feedback.card, wrong: true })
  return {
    items,
    attemptedSlot,
    correctSlot,
    correctDisplaySlot:
      correctSlot === null
        ? null
        : correctSlot +
          (attemptedSlot !== null && attemptedSlot <= correctSlot ? 1 : 0),
    legacyWrongCard: feedback && attemptedSlot === null ? feedback.card : null,
  }
}
