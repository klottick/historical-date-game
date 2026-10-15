import { createFileRoute } from "@tanstack/react-router"
import { DailyPanel } from "@/features/game/DailyPanel"
import { GameSessionGate } from "@/features/game/GameSessionGate"

export const Route = createFileRoute("/_layout/daily")({
  component: Daily,
  head: () => ({ meta: [{ title: "Daily - Historical Date Game" }] }),
})
function Daily() {
  return (
    <div className="space-y-6">
      <h1 className="font-serif text-3xl">Daily challenge</h1>
      <GameSessionGate>
        {(context) => <DailyPanel context={context} />}
      </GameSessionGate>
    </div>
  )
}
