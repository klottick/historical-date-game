import { createFileRoute } from "@tanstack/react-router"
import { GameBoard } from "@/features/game/GameBoard"
import { GameSessionGate } from "@/features/game/GameSessionGate"

export const Route = createFileRoute("/_layout/play/$runId")({
  component: PlayRun,
  head: () => ({ meta: [{ title: "Run - Historical Date Game" }] }),
})

function PlayRun() {
  const { runId } = Route.useParams()
  return (
    <GameSessionGate>
      {(context) => <GameBoard runId={runId} context={context} />}
    </GameSessionGate>
  )
}
