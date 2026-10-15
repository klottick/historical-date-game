import { Link } from "@tanstack/react-router"

import { History } from "lucide-react"
import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const content = (
    <span
      className={cn(
        "inline-flex items-center gap-2 font-serif font-semibold",
        className,
      )}
    >
      <History aria-hidden="true" className="size-6 shrink-0 text-[#dba64d]" />
      <span
        className={cn(
          variant === "icon" && "sr-only",
          variant === "responsive" && "group-data-[collapsible=icon]:sr-only",
        )}
      >
        Historical Date Game
      </span>
    </span>
  )

  if (!asLink) {
    return content
  }

  return <Link to="/">{content}</Link>
}
