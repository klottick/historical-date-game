import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import { getGameOptions } from "@/features/game/api"
import { FreeplayForm } from "@/features/game/FreeplayForm"
import useAuth from "@/hooks/useAuth"
import { extractErrorMessage } from "@/utils"

export const Route = createFileRoute("/_layout/freeplay")({
  component: Freeplay,
  head: () => ({ meta: [{ title: "Freeplay - Historical Date Game" }] }),
})

function Freeplay() {
  const { user } = useAuth()
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
      {options.data && user && (
        <FreeplayForm key={user.id} options={options.data} ownerId={user.id} />
      )}
    </div>
  )
}
