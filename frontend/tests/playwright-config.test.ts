import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { test } from "node:test"

for (const value of [undefined, "false", "true"]) {
  test(`Playwright uses ${value === "true" ? "CI" : "local"} settings when CI is ${value ?? "unset"}`, () => {
    const env = { ...process.env }
    if (value === undefined) {
      delete env.CI
    } else {
      env.CI = value
    }
    const result = spawnSync(
      process.execPath,
      [
        "--input-type=module",
        "-e",
        `const { default: config } = await import("./playwright.config.ts");
        console.log(JSON.stringify({
          forbidOnly: config.forbidOnly,
          retries: config.retries,
          workers: config.workers,
          reporter: config.reporter,
          reuseExistingServer: config.webServer.reuseExistingServer,
          testIgnore: config.testIgnore,
        }));`,
      ],
      { env, encoding: "utf8" },
    )
    assert.equal(result.status, 0, result.stderr)
    const actual = JSON.parse(result.stdout.trim().split("\n").pop()!)
    const isCI = value === "true"

    assert.deepEqual(actual, {
      forbidOnly: isCI,
      retries: isCI ? 2 : 0,
      ...(isCI ? { workers: 1 } : {}),
      reporter: isCI ? "blob" : "html",
      reuseExistingServer: !isCI,
      testIgnore: [
        "**/game-session-bootstrap.spec.ts",
        "**/game-identity-recovery.spec.ts",
        "**/board-navigation.spec.ts",
        "**/board-ux.spec.ts",
        "**/game-board-ux.spec.ts",
        "**/board-projection-focus.spec.ts",
      ],
    })
  })
}
