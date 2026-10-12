// Manual two-phase local probe: capture -> owned backend restart -> rehydrate.
// It is deliberately not a .spec.ts and never discovers the fixture suite.
import assert from "node:assert/strict"
import { randomUUID } from "node:crypto"
import { readFile, writeFile } from "node:fs/promises"
import { chromium, request } from "@playwright/test"
import type { RunPublic } from "../src/client/types.gen"
import { loadCatalog, slugs } from "./catalog.ts"

const origin = "http://localhost:5174"
const api = "http://localhost:8010/api/v1"
const evidence =
  "../.superpowers/sdd/2026-10-12-historical-date-game-beta-followup/F2-evidence"
const [player] = JSON.parse(
  await readFile("playwright/.auth/real-catalog-players.json", "utf8"),
)
const headers = { Authorization: `Bearer ${player.token}` }
const http = await request.newContext({ extraHTTPHeaders: headers })
try {
  assert.equal((await http.get(`${api}/utils/health-check/`)).status(), 200)
  const options = await (await http.get(`${api}/games/options`)).json()
  const catalog = loadCatalog(options.catalog_release_id)
  if (process.argv[2] === "before") {
    const runs: RunPublic[] = []
    for (const mode of ["daily", "freeplay"]) {
      const response = await http.post(`${api}/games/${mode}`, {
        data:
          mode === "daily"
            ? { operation_id: randomUUID() }
            : {
                operation_id: randomUUID(),
                catalog_release_id: catalog.manifest.release_id,
                config: {
                  category_ids: slugs,
                  start: options.start,
                  end: options.end,
                  min_gap: 1,
                },
              },
      })
      assert.equal(response.status(), 200)
      let run: RunPublic = await response.json()
      assert.equal(run.status, "active")
      assert.ok(run.pending)
      const answer = catalog.years.get(run.pending.event_id)
      assert.notEqual(answer, undefined)
      const slot = run.timeline.filter(
        (c) =>
          (c.year.era === "CE" ? c.year.value : 1 - c.year.value) < answer!,
      ).length
      const move = await http.post(
        `${api}/games/runs/${run.run_id}/placements`,
        {
          data: {
            operation_id: randomUUID(),
            expected_revision: run.revision,
            event_id: run.pending.event_id,
            slot,
          },
        },
      )
      assert.equal(move.status(), 200)
      run = await move.json()
      assert.equal(run.feedback!.correct, true)
      assert.equal(run.status, "active")
      runs.push(run)
    }
    await writeFile(
      `${evidence}/restart-before.json`,
      JSON.stringify(runs, null, 2),
      { mode: 0o600 },
    )
    console.log(
      JSON.stringify({
        phase: "before",
        runs: runs.map((r) => ({
          id: r.run_id,
          mode: r.mode,
          revision: r.revision,
          date: r.daily_date,
          release: r.catalog_release_id,
        })),
      }),
    )
  } else if (process.argv[2] === "after") {
    const runs: RunPublic[] = JSON.parse(
      await readFile(`${evidence}/restart-before.json`, "utf8"),
    )
    const browser = await chromium.launch()
    try {
      const context = await browser.newContext({
        baseURL: origin,
        storageState: {
          cookies: [],
          origins: [
            {
              origin,
              localStorage: [{ name: "access_token", value: player.token }],
            },
          ],
        },
      })
      const page = await context.newPage()
      const results = []
      for (const before of runs) {
        const response = await http.get(`${api}/games/runs/${before.run_id}`)
        assert.equal(response.status(), 200)
        const rehydrated: RunPublic = await response.json()
        assert.deepEqual(
          rehydrated,
          before,
          "all public state survives process restart byte-equivalently",
        )
        await page.goto(`/play/${before.run_id}`)
        await page
          .getByTestId("run-revision")
          .filter({ hasText: `Revision: ${before.revision}` })
          .waitFor()
        const answer = catalog.years.get(before.pending!.event_id)
        assert.notEqual(answer, undefined)
        const slot = before.timeline.filter(
          (c) =>
            (c.year.era === "CE" ? c.year.value : 1 - c.year.value) < answer!,
        ).length
        await page
          .getByRole("button", { name: `Slot ${slot + 1}`, exact: true })
          .click()
        const scored = page.waitForResponse(
          (r) =>
            r.request().method() === "POST" && r.url().endsWith("/placements"),
        )
        await page
          .getByRole("button", { name: "Lock it in", exact: true })
          .click()
        const move = await scored
        assert.equal(move.status(), 200)
        const after: RunPublic = await move.json()
        assert.equal(after.revision, before.revision + 1)
        assert.equal(after.streak, before.streak + 1)
        assert.equal(after.feedback!.correct, true)
        assert.equal(after.status, "active")
        assert.equal(after.catalog_release_id, before.catalog_release_id)
        assert.equal(after.daily_date, before.daily_date)
        await page
          .getByTestId("run-revision")
          .filter({ hasText: `Revision: ${after.revision}` })
          .waitFor()
        assert.deepEqual(
          await (await http.get(`${api}/games/runs/${before.run_id}`)).json(),
          after,
        )
        await page.screenshot({
          path: `${evidence}/restart-${before.mode}.png`,
          fullPage: true,
        })
        results.push({ before, rehydrated, after })
      }
      await writeFile(
        `${evidence}/restart-after.json`,
        JSON.stringify(results, null, 2),
        { mode: 0o600 },
      )
      console.log(
        JSON.stringify({
          phase: "after",
          identicalRehydration: true,
          nextScoredMoves: results.map((r) => ({
            mode: r.after.mode,
            revision: r.after.revision,
            streak: r.after.streak,
            status: r.after.status,
          })),
        }),
      )
      await context.close()
    } finally {
      await browser.close()
    }
  } else throw new Error("Expected before or after phase")
} finally {
  await http.dispose()
}
