import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import { getGameOptions } from "@/features/game/api"
import { FreeplayForm } from "@/features/game/FreeplayForm"
import { GameSessionGate } from "@/features/game/GameSessionGate"
import { extractErrorMessage } from "@/utils"

export const Route = createFileRoute("/_layout/freeplay")({
  component: Freeplay,
  head: () => ({ meta: [{ title: "Freeplay - Historical Date Game" }] }),
})

function Freeplay() {
  const options = useQuery({
    queryKey: ["game", "options"],
    queryFn: getGameOptions,
    retry: false,
  })
  return (
    <div className="space-y-6">
      <h1 className="font-serif text-3xl">Freeplay</h1>
      <p className="text-muted-foreground">
        Pick your eras and subjects. How far can you take your timeline?
      </p>
      {options.isPending && <p>Loading published categories…</p>}
      {options.error && (
        <p role="alert">
          {extractErrorMessage(options.error)}{" "}
          <Button variant="outline" onClick={() => options.refetch()}>
            Retry options
          </Button>
        </p>
      )}
      {options.data && (
        <GameSessionGate>
          {(context) => (
            <FreeplayForm options={options.data!} context={context} />
          )}
        </GameSessionGate>
      )}
    </div>
  )
}
