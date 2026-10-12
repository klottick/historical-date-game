import assert from "node:assert/strict"
import { test } from "node:test"
import { AxiosError, AxiosHeaders } from "axios"

import { handleError } from "../src/utils.ts"

for (const detail of [
  "Incorrect credentials",
  [{ msg: "Invalid email address", loc: ["body", "email"] }],
]) {
  test(`API error displays ${typeof detail === "string" ? "server detail" : "validation detail"}`, () => {
    const error = new AxiosError(
      "Request failed",
      "ERR_BAD_REQUEST",
      undefined,
      undefined,
      {
        data: { detail },
        status: 400,
        statusText: "Bad Request",
        headers: {},
        config: { headers: new AxiosHeaders() },
      },
    )
    let message = ""

    handleError.call((value) => {
      message = value
    }, error)

    assert.equal(
      message,
      typeof detail === "string"
        ? "Incorrect credentials"
        : "Invalid email address",
    )
  })
}

test("Network error displays its message", () => {
  let message = ""

  handleError.call((value) => {
    message = value
  }, new AxiosError("Network Error"))

  assert.equal(message, "Network Error")
})

test("Game errors display structured detail.message", () => {
  const error = new AxiosError(
    "Request failed",
    "ERR_BAD_REQUEST",
    undefined,
    undefined,
    {
      data: {
        detail: { code: "stale_revision", message: "Game command rejected" },
      },
      status: 409,
      statusText: "Conflict",
      headers: {},
      config: { headers: new AxiosHeaders() },
    },
  )
  let message = ""
  handleError.call((value) => {
    message = value
  }, error)
  assert.equal(message, "Game command rejected")
})

test("Malformed validation detail falls back to the error message", () => {
  const error = new AxiosError(
    "Request failed",
    undefined,
    undefined,
    undefined,
    {
      data: { detail: [{}] },
      status: 422,
      statusText: "Unprocessable Entity",
      headers: {},
      config: { headers: new AxiosHeaders() },
    },
  )
  let message = ""
  handleError.call((value) => {
    message = value
  }, error)
  assert.equal(message, "Request failed")
})
