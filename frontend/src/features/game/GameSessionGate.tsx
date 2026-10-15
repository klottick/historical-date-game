import { Link } from "@tanstack/react-router"
import type { ReactNode } from "react"
import type { GameSessionPublic } from "@/client"
import { Button } from "@/components/ui/button"
import { useGameSession } from "./GameSessionProvider"
import { notifyAccountChange } from "./identityState"

export function GameSessionGate({
  children,
}: {
  children: (context: GameSessionPublic) => ReactNode
}) {
  const { context, loading, error, retrySession, continueAsGuest } =
    useGameSession()
  if (context)
    return (
      <div key={`${context.kind}:${context.context_id}`}>
        {children(context)}
      </div>
    )
  if (loading) return <p role="status">Checking game session…</p>
  return (
    <section className="space-y-4">
      <h1 className="text-2xl">Game session unavailable</h1>
      <p role="alert">
        {error instanceof Error
          ? error.message
          : "Unable to confirm this player."}{" "}
        Your run is not lost. Saved commands stay with their original player.
      </p>
      <p>
        If a guest cookie expired or was removed, its old runs are no longer
        accessible. Continue as guest starts new play; it never transfers or
        retries an old move.
      </p>
      <Button onClick={retrySession}>Retry session</Button>{" "}
      <Button variant="outline" onClick={continueAsGuest}>
        Continue as guest
      </Button>{" "}
      <Link
        to="/login"
        onClick={() => {
          if (/^\/play\//.test(window.location.pathname))
            sessionStorage.setItem(
              "game-login-return",
              window.location.pathname,
            )
          localStorage.removeItem("access_token")
          notifyAccountChange()
        }}
        className="underline"
      >
        Sign in
      </Link>
    </section>
  )
}
