import { CalendarDays, Home, Layers, Settings, Users } from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { type Item, Main } from "./Main"
import { User } from "./User"

const baseItems: Item[] = [
  { icon: Home, title: "Home", path: "/" },
  { icon: CalendarDays, title: "Daily", path: "/daily" },
  { icon: Layers, title: "Freeplay", path: "/freeplay" },
]

export function AppSidebar() {
  const { user: currentUser } = useAuth()

  const accountItems: Item[] = [
    { icon: Settings, title: "Settings", path: "/settings" },
    ...(currentUser?.is_superuser
      ? [{ icon: Users, title: "Admin", path: "/admin" as const }]
      : []),
  ]

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main items={baseItems} />
      </SidebarContent>
      <SidebarFooter>
        <Main items={accountItems} />
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
