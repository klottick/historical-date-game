import { createFileRoute } from "@tanstack/react-router"
import { DailyPanel } from "@/features/game/DailyPanel"
import useAuth from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout/daily")({
  component: Daily,
  head: () => ({ meta: [{ title: "Daily - Historical Date Game" }] }),
})
function Daily() {
  const { user } = useAuth()
  return (
    <div className="space-y-6">
      <h1 className="font-serif text-3xl">Daily challenge</h1>
      {user && <DailyPanel key={user.id} ownerId={user.id} />}
    </div>
  )
}
