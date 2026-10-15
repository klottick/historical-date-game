import { randomUUID } from "node:crypto"
import { existsSync } from "node:fs"
import { chmod, mkdir, writeFile } from "node:fs/promises"
import { expect, test as setup } from "@playwright/test"
import {
  realCatalogAPI as api,
  realCatalogAuthFile,
  realCatalogUIOrigin,
} from "../playwright.real-catalog.config"
import { loadCatalog } from "./catalog"

setup("restricted real-catalog player authentication", async ({ request }) => {
  // Fail before authentication if the private release setting is missing.
  expect(
    process.env.REAL_CATALOG_RELEASE_DIR,
    "REAL_CATALOG_RELEASE_DIR is required",
  ).toBeTruthy()
  const username = process.env.FIRST_SUPERUSER
  const password = process.env.FIRST_SUPERUSER_PASSWORD
  expect(
    username,
    "supply local admin credentials through environment",
  ).toBeTruthy()
  expect(password).toBeTruthy()
  const login = await request.post(`${api}/login/access-token`, {
    form: { username: username!, password: password! },
  })
  expect(login.ok()).toBeTruthy()
  const admin = (await login.json()).access_token
  const headers = { Authorization: `Bearer ${admin}` }
  const optionsResponse = await request.get(`${api}/games/options`, { headers })
  expect(optionsResponse.ok()).toBeTruthy()
  const options = await optionsResponse.json()
  expect(options.registration_open).toBe(false)
  loadCatalog(options.catalog_release_id)
  const players = []
  for (let i = 0; i < 2; i++) {
    const email = `f2-${randomUUID()}@example.com`
    const playerPassword = `${randomUUID()}Aa!`
    const created = await request.post(`${api}/users/`, {
      headers,
      data: {
        email,
        password: playerPassword,
        full_name: `F2 local player ${i + 1}`,
      },
    })
    expect(created.ok()).toBeTruthy()
    const tokenResponse = await request.post(`${api}/login/access-token`, {
      form: { username: email, password: playerPassword },
    })
    expect(tokenResponse.ok()).toBeTruthy()
    players.push({
      email,
      password: playerPassword,
      token: (await tokenResponse.json()).access_token,
      id: (await created.json()).id,
    })
  }
  await mkdir("playwright/.auth", { recursive: true, mode: 0o700 })
  await chmod("playwright/.auth", 0o700)
  // The private-file denial check must target a real artifact, not SPA fallback.
  const denialProbe = "playwright/.auth/real-catalog-restart-players.json"
  if (!existsSync(denialProbe))
    await writeFile(denialProbe, JSON.stringify({ privateDenialProbe: true }), {
      mode: 0o600,
      flag: "wx",
    })
  await writeFile(
    "playwright/.auth/real-catalog-players.json",
    JSON.stringify(players),
    { mode: 0o600 },
  )
  await chmod("playwright/.auth/real-catalog-players.json", 0o600)
  await writeFile(
    realCatalogAuthFile,
    JSON.stringify({
      cookies: [],
      origins: [
        {
          origin: realCatalogUIOrigin,
          localStorage: [{ name: "access_token", value: players[0].token }],
        },
      ],
    }),
    { mode: 0o600 },
  )
  await chmod(realCatalogAuthFile, 0o600)
})
