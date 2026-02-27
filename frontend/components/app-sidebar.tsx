"use client"

import { usePathname } from "next/navigation"
import { useSession, signOut } from "next-auth/react"
import Link from "next/link"
import {
  Home,
  MessageSquare,
  History,
  Settings,
  Shield,
  LogOut,
  ChevronDown,
  BookOpen,
} from "lucide-react"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"
import { Routes } from "@/config/routes"
import Logo from "./ui/logo"

const navItems = [
  { label: "Home", icon: Home, path: Routes.DASHBOARD },
  { label: "Chat", icon: MessageSquare, path: Routes.PLAYGROUND },
  { label: "Sessions", icon: History, path: Routes.SESSIONS },
  { label: "Knowledge", icon: BookOpen, path: Routes.KNOWLEDGE },
  { label: "Settings", icon: Settings, path: Routes.SETTINGS },
]

const adminItems = [
  { label: "Admin", icon: Shield, path: Routes.ADMIN_PANEL },
]

export function AppSidebar() {
  const pathname = usePathname()
  const { data: session } = useSession()
  const userRole = (session?.user as { role?: string })?.role

  const allItems = userRole === "admin"
    ? [...navItems.slice(0, 3), ...adminItems, ...navItems.slice(3)]
    : navItems

  return (
    <div className="flex flex-col h-full w-54 bg-sidebar text-sidebar-foreground border-r border-sidebar-border shrink-0">
      {/* Logo / Brand */}
      <div className="flex items-center justify-center h-12 px-4 border-b border-sidebar-border">
        <Logo className={'h-5'}/>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-3 space-y-1">
        {allItems.map((item) => {
          const isActive = pathname === item.path ||
            (item.path === Routes.PLAYGROUND && pathname.startsWith("/playground"))
          return (
            <Link
              key={item.path}
              href={item.path}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                  : "text-muted-foreground hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
              )}
            >
              <item.icon className="h-4 w-4 shrink-0" />
              <span>{item.label}</span>
            </Link>
          )
        })}
      </nav>

      {/* User section */}
      <div className="px-3 py-3 border-t border-sidebar-border">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="flex items-center gap-2 w-full px-2 py-1.5 rounded-md hover:bg-sidebar-accent/50 transition-colors">
              <Avatar className="h-7 w-7">
                <AvatarFallback className="bg-primary/10 text-primary text-xs font-semibold">
                  {session?.user?.name?.[0]?.toUpperCase() || session?.user?.email?.[0]?.toUpperCase() || "U"}
                </AvatarFallback>
              </Avatar>
              <div className="flex-1 min-w-0 text-left">
                <p className="text-xs font-semibold uppercase truncate">
                  {(session?.user?.name || session?.user?.email || "User").charAt(0).toUpperCase() + (session?.user?.name || session?.user?.email || "User").slice(1)}
                </p>
              </div>
              <ChevronDown className="h-3 w-3 text-muted-foreground" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" side="top" className="w-48">
            <div className="px-2 py-1.5">
              <p className="text-xs text-muted-foreground">Signed in as</p>
              <p className="text-sm font-medium truncate">{session?.user?.email}</p>
            </div>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive cursor-pointer"
              onClick={() => signOut({ callbackUrl: "/login" })}
            >
              <LogOut className="h-4 w-4 mr-2" />
              Sign Out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  )
}
