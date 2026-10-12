import { defineConfig } from "@hey-api/openapi-ts"

export default defineConfig({
  input: "./openapi.json",
  output: {
    path: "./src/client",
    module: {
      extension: ".ts",
    },
    postProcess: [
      {
        command: "biome",
        args: [
          "format",
          "--write",
          "--config-path",
          "biome.codegen.json",
          "{{path}}",
        ],
      },
    ],
  },

  plugins: [
    "@hey-api/typescript",
    "@hey-api/client-axios",
    {
      name: "@hey-api/sdk",
      operations: {
        strategy: "byTags",
        containerName: "{{name}}Service",
        nesting: "operationId",
        methodName: (name) => {
          const method = name.replace(
            /^(items|users|login|private|utils)[-_]?/i,
            "",
          )
          return method.charAt(0).toLowerCase() + method.slice(1)
        },
      },
    },
    {
      name: "@hey-api/schemas",
      type: "json",
    },
  ],
})
