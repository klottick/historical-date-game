import { expect, type Page } from "@playwright/test"
import type {
  PlaceCommand,
  RevealedCard,
  RunPublic,
} from "../../src/client/types.gen"

export { dragTile, keyboardPreview } from "./boardInteraction"

export const boardRunId = "11111111-1111-4111-8111-111111111111"
export const media = {
  url: "/assets/game-fallback.svg",
  fallback_url: "/assets/game-fallback.svg",
  alt_text: "Historical illustration",
  fit: "contain",
  credits: [
    {
      label: "Illustrator · CC BY 4.0",
      url: "https://creativecommons.org/licenses/by/4.0/",
    },
    { label: "Fallback artwork · Historical Date Game", url: null },
  ],
}
export function revealed(index: number): RevealedCard {
  return {
    event_id: `confirmed-${index}`,
    prompt: `Confirmed event ${index}`,
    category_ids: ["history"],
    media,
    year: { value: index + 100, era: "CE" },
    explanation: "Retained chronology and category technical notes.",
    sources: [
      {
        label: "Wikipedia calendar lineage · CC BY-SA",
        url: "https://en.wikipedia.org/wiki/January_1",
      },
      { label: "Dataset provenance", url: "https://example.org/dataset" },
    ],
    learn_more:
      index === 0
        ? {
            kind: "article",
            label: "Wikipedia article",
            url: "https://en.wikipedia.org/wiki/History",
          }
        : null,
  }
}
export function controlledRun(count = 3): RunPublic {
  return {
    run_id: boardRunId,
    mode: "freeplay",
    daily_date: null,
    catalog_release_id: "controlled-ui",
    config: {
      category_ids: ["history"],
      start: { value: 1, era: "CE" },
      end: { value: 2000, era: "CE" },
      min_gap: 1,
    },
    categories: [{ id: "history", label: "History" }],
    status: "active",
    streak: 0,
    revision: 0,
    timeline: Array.from({ length: count }, (_, i) => revealed(i)),
    pending: {
      event_id: "pending",
      prompt: "Public pending prompt",
      category_ids: ["history"],
      media,
    },
    feedback: null,
  }
}
export async function controlledBoard(
  page: Page,
  initial = controlledRun(),
  open = true,
) {
  const state = {
    run: structuredClone(initial),
    moves: [] as PlaceCommand[],
    failMove: false,
    loseResponse: false,
    scoredOutcomes: 0,
    starts: 0,
  }
  const operations = new Map<
    string,
    { command: PlaceCommand; run: RunPublic }
  >()
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace("/api/v1", "")
    const json = (value: unknown, status = 200) =>
      route.fulfill({ status, json: value })
    if (path === "/users/me")
      return request.headers().authorization
        ? json({
            id: "controlled-account",
            email: "player@example.com",
            full_name: "Controlled player",
            is_active: true,
            is_superuser: false,
          })
        : json({ detail: "Not authenticated" }, 401)
    if (path === "/utils/public-config")
      return json({ registration_open: false })
    if (path === "/games/session")
      return json(
        request.headers().authorization
          ? { kind: "account", context_id: "controlled-account" }
          : { kind: "guest", context_id: "controlled-board" },
      )
    if (path === "/games/options")
      return json({
        catalog_release_id: "controlled-ui",
        categories: initial.categories,
        start: initial.config.start,
        end: initial.config.end,
        registration_open: false,
      })
    if (path === "/games/active-runs") return json([])
    if (path === "/games/daily") {
      if (request.method() === "POST") {
        state.starts++
        state.run = {
          ...structuredClone(initial),
          mode: "daily",
          daily_date: "2026-10-14",
        }
        return json(state.run)
      }
      return json({
        day: "2026-10-14",
        reset_at: "2099-10-15T00:00:00Z",
        category_ids: ["history"],
        attempt_run_id: state.starts ? state.run.run_id : null,
      })
    }
    if (path === "/games/daily/2026-10-14/leaderboard")
      return json({
        day: "2026-10-14",
        entries: Array.from({ length: 50 }, (_, index) => ({
          rank: index + 1,
          display_name: `Public player ${index}`,
          streak: 1,
          status: "lost",
        })),
      })
    if (path === "/games/freeplay") {
      state.starts++
      state.run = {
        ...structuredClone(initial),
        run_id:
          state.starts > 1
            ? "22222222-2222-4222-8222-222222222222"
            : boardRunId,
      }
      return json(state.run)
    }
    if (path === `/games/runs/${state.run.run_id}`) {
      if (request.headers().authorization)
        return json({ detail: "Not found" }, 404)
      return json(state.run)
    }
    if (path.endsWith("/placements")) {
      const command: PlaceCommand = request.postDataJSON()
      state.moves.push(command)
      const replay = operations.get(command.operation_id)
      if (replay) {
        expect(command).toEqual(replay.command)
        return json(replay.run)
      }
      if (state.failMove) return route.abort("failed")
      const card = {
        ...revealed(700),
        ...state.run.pending!,
        year: { value: 900, era: "CE" } as const,
      }
      const correct = state.run.revision === 0
      state.run = {
        ...state.run,
        revision: state.run.revision + 1,
        status: correct ? "active" : "lost",
        streak: correct ? 1 : state.run.streak,
        timeline: correct
          ? [
              ...state.run.timeline.slice(0, command.slot),
              card,
              ...state.run.timeline.slice(command.slot),
            ]
          : state.run.timeline,
        pending: correct
          ? {
              event_id: "next",
              prompt: "Next public prompt",
              category_ids: ["history"],
              media,
            }
          : null,
        feedback: {
          correct,
          card,
          attempted_slot: command.slot,
          correct_slot: correct ? command.slot : state.run.timeline.length,
        },
      }
      state.scoredOutcomes++
      operations.set(command.operation_id, {
        command: structuredClone(command),
        run: structuredClone(state.run),
      })
      if (state.loseResponse) return route.abort("failed")
      return json(state.run)
    }
    return json({ detail: `Unexpected controlled endpoint ${path}` }, 404)
  })
  if (open) {
    await page.goto(`/play/${boardRunId}`)
    await expect(page.locator(".pending-draggable")).toBeVisible()
  }
  return state
}
