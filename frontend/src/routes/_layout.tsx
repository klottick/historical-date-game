import {
  createFileRoute,
  Link,
  Outlet,
  redirect,
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
import { isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async ({ location }) => {
    if (!isLoggedIn()) {
      if (/^\/play\/[\da-f-]+$/.test(location.pathname)) {
        sessionStorage.setItem("game-login-return", location.pathname)
      }
      throw redirect({
        to: "/login",
      })
    }
  },
})

function Layout() {
  const location = useLocation()
  if (/^\/play\/[\da-f-]+$/.test(location.pathname))
    return (
      <div className="play-layout">
        <nav className="play-nav" aria-label="Game navigation">
          <Link to="/">← Home</Link>
          <strong>Historical Date Game</strong>
          <Link to="/settings">Account</Link>
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
            <Outlet />
          </div>
        </main>
        <Footer />
      </SidebarInset>
    </SidebarProvider>
  )
}

export default Layout
