import type { RunPublic } from "../../src/client/types.gen"

// Layout only: wholly synthetic, already-revealed civil years and public DTOs.
// Never used to score a backend run or bundled into the application.
export function hundredCardRun(): RunPublic {
  const media = {
    url: "/u4-slow-primary.svg",
    fallback_url: "/u4-broken-fallback.svg",
    alt_text: "Synthetic representative timeline artwork",
    fit: "contain",
    credits: [
      {
        label:
          "Synthetic layout artwork / Original geometric illustration; CC0 1.0 — long attribution retained without overlapping controls",
        url: "https://example.com/layout-credit",
      },
    ],
  }
  return {
    run_id: "40000000-0000-4000-8000-000000000004",
    mode: "freeplay",
    daily_date: null,
    catalog_release_id: "synthetic-public-layout-only",
    config: {
      category_ids: ["exploration"],
      start: { value: 50, era: "BCE" },
      end: { value: 100, era: "CE" },
      min_gap: 1,
    },
    categories: [{ id: "exploration", label: "Exploration" }],
    status: "active",
    streak: 99,
    revision: 99,
    timeline: Array.from({ length: 100 }, (_, i) => ({
      event_id: `40000000-0000-4000-8000-${String(i).padStart(12, "0")}`,
      prompt: `Synthetic revealed milestone ${i + 1}: a long title to exercise wrapping`,
      category_ids: ["exploration"],
      media,
      year:
        i < 50 ? { value: 50 - i, era: "BCE" } : { value: i - 49, era: "CE" },
      explanation: "Synthetic layout explanation, not a historical claim.",
      sources: [
        {
          label: "Synthetic public source",
          url: "https://example.com/layout-source",
        },
      ],
    })),
    pending: {
      event_id: "40000000-0000-4000-9000-000000000004",
      prompt:
        "Synthetic unanswered card — no year or citation in this public DTO",
      category_ids: ["exploration"],
      media,
    },
    feedback: null,
  }
}
