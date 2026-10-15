// Test-runner only: product origins are configured independently.
export const fixtureAPIOrigin = (
  process.env.VITE_API_URL || "http://localhost:8000"
).replace(/\/$/, "")
export const fixtureAPI = `${fixtureAPIOrigin}/api/v1`
