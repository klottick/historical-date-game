import { test as setup } from "@playwright/test"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"
import { fixtureAPI } from "./utils/apiOrigin"
import { readGameOptions } from "./utils/gameOptions"

const authFile = "playwright/.auth/user.json"

setup("authenticate", async ({ page }) => {
  await readGameOptions(await page.request.get(`${fixtureAPI}/games/options`))
  await page.goto("/login")
  await page.getByTestId("email-input").fill(firstSuperuser)
  await page.getByTestId("password-input").fill(firstSuperuserPassword)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/")
  await page.context().storageState({ path: authFile })
})
