import { expect, test } from "@playwright/test"

import { firstSuperuser } from "./config"
import { createUser } from "./utils/privateApi"
import { randomEmail, randomPassword } from "./utils/random"
import { logInUser } from "./utils/user"

test("Admin table renders user data", async ({ page }) => {
  await page.goto("/admin")

  await expect(
    page.getByRole("heading", { name: "Users", exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("row").filter({ hasText: firstSuperuser }),
  ).toBeVisible()
})

test.describe("Item table pagination", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("Rows and page-size controls stay in sync", async ({
    page,
    request,
  }) => {
    const email = randomEmail()
    const password = randomPassword()
    await createUser({ email, password })
    await logInUser(page, email, password)
    const token = await page.evaluate(() =>
      localStorage.getItem("access_token"),
    )
    const headers = { Authorization: `Bearer ${token}` }
    const api = process.env.VITE_API_URL

    try {
      for (let index = 0; index < 12; index++) {
        const response = await request.post(`${api}/api/v1/items/`, {
          headers,
          data: { title: `Pagination item ${index}` },
        })
        expect(response.ok()).toBeTruthy()
      }

      await page.goto("/items")
      await expect(page.getByRole("row")).toHaveCount(11)
      await page
        .getByRole("button", { name: "Go to next page", exact: true })
        .click()
      await expect(page.getByRole("row")).toHaveCount(3)
      await expect(
        page.getByRole("button", { name: "Go to next page", exact: true }),
      ).toBeDisabled()

      await page.getByRole("button", { name: "Go to first page" }).click()
      await expect(page.getByRole("row")).toHaveCount(11)
      await page.getByRole("combobox").click()
      await page.getByRole("option", { name: "5", exact: true }).click()
      await expect(page.getByRole("row")).toHaveCount(6)
      await page.getByRole("button", { name: "Go to last page" }).click()
      await expect(page.getByRole("row")).toHaveCount(3)
    } finally {
      const response = await request.delete(`${api}/api/v1/users/me`, {
        headers,
      })
      expect(response.ok()).toBeTruthy()
    }
  })
})
