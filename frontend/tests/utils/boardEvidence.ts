// Node-only paths; never import into the application bundle.
import { mkdirSync } from "node:fs"
import { resolve } from "node:path"

export const boardEvidence = resolve(
  process.env.BOARD_TEST_EVIDENCE_DIR ||
    "../.superpowers/sdd/2026-10-14-game-board-redesign/integration",
)
mkdirSync(boardEvidence, { recursive: true, mode: 0o700 })

export const verificationDatabase =
  process.env.HDG_VERIFICATION_PROFILE === "board"
    ? "historical_date_game_board_test"
    : "historical_date_game_guest_test"

// Runtime ownership evidence is chosen by the Python launcher's finite profile,
// independently of an output-directory override for one test invocation.
export const verificationRuntime = resolve(
  process.env.HDG_VERIFICATION_PROFILE === "board"
    ? "../.superpowers/sdd/2026-10-14-game-board-redesign/integration/real-runtime"
    : "../.superpowers/sdd/2026-10-13-historical-date-game-guest-play/task-5-evidence/real-runtime",
)
