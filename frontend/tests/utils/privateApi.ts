// Note: the `PrivateService` is only available when generating the client
// for local environments

import { createClient } from "../../src/client/client/index.ts"
import { PrivateService } from "../../src/client/index.ts"

// This is Node-only account provisioning, not a browser guest-cookie request.
// Docker supplies the explicit internal backend target; local runs retain their
// existing API URL. Keep this client isolated from browser/shared configuration.
const internalTarget = process.env.PLAYWRIGHT_API_PROXY
const isCI = process.env.CI === "true" || process.env.CI === "1"
if (isCI && !internalTarget) {
  throw new Error(
    "Private Node CI setup requires an explicit internal backend target",
  )
}
const privateClient = createClient({
  baseURL: internalTarget || process.env.VITE_API_URL,
  throwOnError: true,
})

export const createUser = async ({
  email,
  password,
}: {
  email: string
  password: string
}) => {
  const response = await PrivateService.createUser({
    client: privateClient,
    throwOnError: true,
    body: {
      email,
      password,
      is_verified: true,
      full_name: "Test User",
    },
  })
  return response.data
}
