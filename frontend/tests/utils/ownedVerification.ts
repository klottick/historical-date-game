// Node-only lifecycle: the backend helper verifies exact DB and process ownership.
import { execFileSync } from "node:child_process"
import { appendFileSync } from "node:fs"
import { resolve } from "node:path"
import { boardEvidence, verificationDatabase } from "./boardEvidence.ts"

export function ownedBackend(command: "launch" | "stop") {
  const backend = resolve("../backend")
  const output = execFileSync(
    resolve(backend, ".venv/bin/python"),
    [
      "-m",
      "tests.browser.guest_test_environment",
      command,
      "--target",
      "real",
      "--component",
      "backend",
    ],
    {
      cwd: backend,
      env: {
        ...process.env,
        POSTGRES_DB: verificationDatabase,
        POSTGRES_SERVER: "127.0.0.1",
        POSTGRES_PORT: "5433",
        ENVIRONMENT: "local",
      },
      timeout: 60_000,
      encoding: "utf8",
    },
  )
  appendFileSync(`${boardEvidence}/browser-restarts.log`, output, {
    mode: 0o600,
  })
}
