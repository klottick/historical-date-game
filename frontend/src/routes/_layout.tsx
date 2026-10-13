import {
  createFileRoute,
  Link,
  Navigate,
  Outlet,
  useLocation,
} from "@tanstack/react-router"
import "@/features/game/game.css"

import { Footer } from "@/components/Common/Footer"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { GameSessionProvider } from "@/features/game/GameSessionProvider"
import useAuth, { isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout")({
  component: Layout,
})

function Layout() {
  const location = useLocation()
  const mode = /^\/(play|settings|admin|items)(\/|$)/.test(location.pathname)
    ? "inspect"
    : "bootstrap"
  return (
    <GameSessionProvider mode={mode}>
      <LayoutContent />
    </GameSessionProvider>
  )
}

function LayoutContent() {
  const location = useLocation()
  const { user } = useAuth()
  const protectedRoute = /^\/(settings|admin|items)(\/|$)/.test(
    location.pathname,
  )
  if (protectedRoute && !isLoggedIn()) return <Navigate to="/login" />
  if (protectedRoute && !user) return <p role="status">Checking account…</p>
  if (location.pathname === "/admin" && !user?.is_superuser)
    return <Navigate to="/" />
  if (/^\/play\/[\da-f-]+$/.test(location.pathname))
    return (
      <div className="play-layout">
        <nav className="play-nav" aria-label="Game navigation">
          <Link to="/">← Home</Link>
          <strong>Historical Date Game</strong>
          {isLoggedIn() ? (
            <Link to="/settings">Account</Link>
          ) : (
            <Link to="/login">Sign in</Link>
          )}
        </nav>
        <main className="play-main">
          <Outlet />
        </main>
      </div>
    )
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="sticky top-0 z-10 flex h-16 shrink-0 items-center gap-2 border-b px-4">
          <SidebarTrigger className="-ml-1 text-muted-foreground" />
        </header>
        <main className="flex-1 p-6 md:p-8">
          <div className="mx-auto max-w-7xl">
            <Outlet key={protectedRoute ? user?.id : "public"} />
          </div>
        </main>
        <Footer />
      </SidebarInset>
    </SidebarProvider>
  )
}

export default Layout
