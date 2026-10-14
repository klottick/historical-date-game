import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import test from "node:test"

// Exercise the real helper and generated Axios request without accounts, sockets,
// dotenv, a web server, or browser state. Only the network adapter is replaced.
function probe(env: Record<string, string>, fail = false) {
  const script = `
    import axios from "axios";
    const requests = [];
    axios.defaults.adapter = async (config) => {
      requests.push({
        url: axios.getUri(config), method: config.method,
        body: JSON.parse(config.data), headers: config.headers.toJSON(),
        withCredentials: config.withCredentials ?? false,
      });
      if (${fail}) throw new axios.AxiosError("synthetic refusal", "ECONNREFUSED", config);
      return { data: { id: "synthetic-user" }, status: 200, statusText: "OK", headers: {}, config };
    };
    const { client } = await import("./src/client/client.gen.ts");
    client.setConfig({ baseURL: "http://localhost:5173", auth: "synthetic-browser-token", throwOnError: false });
    const before = client.getConfig();
    const { createUser } = await import("./tests/utils/privateApi.ts");
    const after = client.getConfig();
    let response, error;
    try {
      response = await createUser({ email: "synthetic@example.invalid", password: "synthetic-password" });
      client.setConfig({ baseURL: "http://unrelated-client.invalid", auth: "other-token" });
      await createUser({ email: "synthetic@example.invalid", password: "synthetic-password" });
    } catch (e) { error = e.code; }
    console.log(JSON.stringify({ before, after, requests, response, error }));
  `
  const result = spawnSync(
    process.execPath,
    ["--input-type=module", "-e", script],
    {
      cwd: process.cwd(),
      // Deliberately do not inherit any real runtime environment or proxy secrets.
      env,
      encoding: "utf8",
    },
  )
  assert.equal(result.status, 0, result.stderr)
  return JSON.parse(result.stdout)
}

const ciEnv = {
  CI: "true",
  VITE_API_URL: "http://localhost:5173",
  PLAYWRIGHT_API_PROXY: "http://backend:8000",
}

test("private Node account setup uses the explicit internal target before browser navigation", () => {
  const result = probe(ciEnv)
  assert.deepEqual(
    result.requests.map((request: { url: string }) => request.url),
    [
      "http://backend:8000/api/v1/private/users/",
      "http://backend:8000/api/v1/private/users/",
    ],
  )
  assert.deepEqual(result.response, { id: "synthetic-user" })
  for (const request of result.requests) {
    assert.equal(request.method, "post")
    assert.deepEqual(request.body, {
      email: "synthetic@example.invalid",
      password: "synthetic-password",
      is_verified: true,
      full_name: "Test User",
    })
    assert.equal(request.headers.Cookie, undefined)
    assert.equal(request.headers.Authorization, undefined)
    assert.equal(request.withCredentials, false)
  }
})

test("private Node helper does not mutate the shared browser client configuration", () => {
  const result = probe(ciEnv)
  assert.deepEqual(result.after, result.before)
})

test("private Node setup retains the existing local API fallback without an internal target", () => {
  const result = probe({ CI: "false", VITE_API_URL: "http://localhost:8000" })
  assert.deepEqual(
    result.requests.map((request: { url: string }) => request.url),
    [
      "http://localhost:8000/api/v1/private/users/",
      "http://localhost:8000/api/v1/private/users/",
    ],
  )
})

test("private Node setup propagates transport failure without retries", () => {
  const result = probe(ciEnv, true)
  assert.equal(result.error, "ECONNREFUSED")
  assert.equal(result.requests.length, 1)
})

test("private Node CI setup refuses a missing explicit internal target", () => {
  const result = spawnSync(
    process.execPath,
    [
      "--input-type=module",
      "-e",
      `import assert from "node:assert/strict";
       await assert.rejects(import("./tests/utils/privateApi.ts"), /explicit internal backend target/);`,
    ],
    {
      cwd: process.cwd(),
      env: { CI: "true", VITE_API_URL: "http://localhost:5173" },
      encoding: "utf8",
    },
  )
  assert.equal(result.status, 0, result.stderr)
})
