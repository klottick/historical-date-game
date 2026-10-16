import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { resolve } from "node:path"
import { test } from "node:test"

for (const profile of ["board", "guest", "lives"]) {
  test(`private runtime probes retain the ${profile} verification profile`, () => {
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      HDG_VERIFICATION_PROFILE: profile,
    }
    delete env.BOARD_TEST_EVIDENCE_DIR
    const result = spawnSync(
      process.execPath,
      [
        "--input-type=module",
        "-e",
        `
      const e = await import('./tests/utils/boardEvidence.ts');
      console.log(JSON.stringify({evidence:e.boardEvidence,database:e.verificationDatabase,runtime:e.verificationRuntime}));
    `,
      ],
      { env, encoding: "utf8" },
    )
    assert.equal(result.status, 0, result.stderr)
    const actual = JSON.parse(result.stdout)
    assert.equal(
      actual.evidence,
      resolve(
        profile === "lives"
          ? "../.superpowers/board-polish-three-lives/verification"
          : "../.superpowers/sdd/2026-10-14-game-board-redesign/integration",
      ),
    )
    assert.equal(
      actual.database,
      profile === "lives"
        ? "historical_date_game_lives_test"
        : `historical_date_game_${profile}_test`,
    )
    assert.equal(
      actual.runtime,
      resolve(
        profile === "lives"
          ? "../.superpowers/board-polish-three-lives/verification/real-runtime"
          : profile === "board"
            ? "../.superpowers/sdd/2026-10-14-game-board-redesign/integration/real-runtime"
            : "../.superpowers/sdd/2026-10-13-historical-date-game-guest-play/task-5-evidence/real-runtime",
      ),
    )
  })
}
