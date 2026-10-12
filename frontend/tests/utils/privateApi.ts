// Note: the `PrivateService` is only available when generating the client
// for local environments

import { client } from "../../src/client/client.gen.ts"
import { PrivateService } from "../../src/client/index.ts"

client.setConfig({ baseURL: process.env.VITE_API_URL, throwOnError: true })

export const createUser = async ({
  email,
  password,
}: {
  email: string
  password: string
}) => {
  const response = await PrivateService.createUser({
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
