import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useState } from "react"
import type { FreeplayStart, GameOptions, YearInput } from "@/client"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import { extractErrorMessage } from "@/utils"
import {
  isKnownFailure,
  readStartOperation,
  saveStartOperation,
  startFreeplay,
} from "./api"
import { defaultConfig, parseSafeInteger, validateConfig } from "./config"

export function FreeplayForm({
  options,
  ownerId,
}: {
  options: GameOptions
  ownerId: string
}) {
  const key = `game-start:${ownerId}:freeplay`
  const [operation, setOperation] = useState(() =>
    readStartOperation<FreeplayStart>(key),
  )
  const [config, setConfig] = useState(
    () => operation?.config ?? defaultConfig(options),
  )
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const errors = validateConfig(config, options)
  const mutation = useMutation({
    mutationFn: startFreeplay,
    retry: false,
    onSuccess: (run) => {
      sessionStorage.removeItem(key)
      setOperation(null)
      queryClient.invalidateQueries({ queryKey: ["game", "active-runs"] })
      navigate({ to: "/play/$runId", params: { runId: run.run_id } })
    },
    onError: (error) => {
      if (isKnownFailure(error)) {
        sessionStorage.removeItem(key)
        setOperation(null)
      }
    },
  })
  const locked = operation !== null || mutation.isPending

  const yearField = (bound: "start" | "end") => (
    <div className="grid grid-cols-[1fr_auto] gap-3">
      <label className="space-y-2" htmlFor={`freeplay-${bound}-year`}>
        <span>{bound === "start" ? "Start year" : "End year"}</span>
        <Input
          id={`freeplay-${bound}-year`}
          type="number"
          min="1"
          max={Number.MAX_SAFE_INTEGER}
          step="1"
          value={Number.isNaN(config[bound].value) ? "" : config[bound].value}
          onChange={(event) =>
            setConfig({
              ...config,
              [bound]: {
                ...config[bound],
                value: parseSafeInteger(event.target.value),
              },
            })
          }
        />
      </label>
      <label className="space-y-2">
        <span>{bound === "start" ? "Start era" : "End era"}</span>
        <select
          className="block h-9 rounded-md border bg-background px-3"
          value={config[bound].era}
          onChange={(event) =>
            setConfig({
              ...config,
              [bound]: {
                ...config[bound],
                era: event.target.value as YearInput["era"],
              },
            })
          }
        >
          <option value="BCE">BCE</option>
          <option value="CE">CE</option>
        </select>
      </label>
    </div>
  )

  return (
    <form
      className="max-w-2xl space-y-6 rounded-xl border border-[#426d73]/40 bg-card p-6"
      noValidate
      onSubmit={(event) => {
        event.preventDefault()
        if (mutation.isPending || (!operation && errors.length)) return
        const command = saveStartOperation(
          key,
          operation ?? {
            operation_id: crypto.randomUUID(),
            catalog_release_id: options.catalog_release_id,
            config: structuredClone(config),
          },
        )
        setOperation(command)
        mutation.mutate(command)
      }}
    >
      <fieldset disabled={locked} className="space-y-6">
        <legend className="font-semibold">Build your timeline</legend>
        <p className="text-sm text-muted-foreground">
          Categories are combined as a union, without duplicate events or years.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          {options.categories.map((category) => (
            <label key={category.id} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={config.category_ids.includes(category.id)}
                onChange={(event) =>
                  setConfig({
                    ...config,
                    category_ids: event.target.checked
                      ? [...config.category_ids, category.id]
                      : config.category_ids.filter((id) => id !== category.id),
                  })
                }
              />
              {category.label}
            </label>
          ))}
        </div>
        {yearField("start")}
        {yearField("end")}
        <label className="block space-y-2" htmlFor="freeplay-min-gap">
          <span>Minimum year gap</span>
          <Input
            id="freeplay-min-gap"
            type="number"
            min="1"
            max={Number.MAX_SAFE_INTEGER}
            step="1"
            value={Number.isNaN(config.min_gap) ? "" : config.min_gap}
            onChange={(event) =>
              setConfig({
                ...config,
                min_gap: parseSafeInteger(event.target.value),
              })
            }
          />
        </label>
        <p className="text-sm text-muted-foreground">
          Bounds are inclusive. No year zero. The gap applies between every pair
          of events. Sparse selections may not have enough events; starting
          checks availability before creating a run.
        </p>
      </fieldset>
      {errors.length > 0 && !operation && (
        <ul role="alert" className="text-destructive">
          {errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      )}
      {mutation.error && (
        <p role="alert" className="text-destructive">
          {extractErrorMessage(mutation.error)}
        </p>
      )}
      {operation && !mutation.isPending && (
        <p className="text-sm">
          This start is not yet confirmed. Retry the same request to recover it;
          your configuration is kept unchanged.
        </p>
      )}
      <LoadingButton
        type="submit"
        loading={mutation.isPending}
        disabled={!operation && errors.length > 0}
      >
        {operation && !mutation.isPending ? "Retry start" : "Start Freeplay"}
      </LoadingButton>
    </form>
  )
}
