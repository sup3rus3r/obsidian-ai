"use client"

import { useState } from "react"
import { usePathname } from "next/navigation"
import { useSession, signOut } from "next-auth/react"
import { useTheme } from "next-themes"
import Link from "next/link"
import { motion } from "motion/react"
import {
  Home,
  MessageSquare,
  History,
  Settings,
  Shield,
  LogOut,
  ChevronDown,
  ChevronsLeft,
  ChevronsRight,
  BookOpen,
  FlaskConical,
  BarChart2,
  MessageCircle,
  Key,
  BookMarked,
  FileText,
  Sparkles,
  Moon,
  Sun,
  Bot,
} from "lucide-react"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { Routes } from "@/config/routes"
import { springTransition } from "@/lib/motion"
import Logo, { LogoMark } from "./ui/logo"

type NavItem = { label: string; icon: React.ElementType; path: string; chip: string }

// One muted chip style per section (not per item) using our own palette
// tokens, not saturated rainbow colors — a quiet visual grouping cue rather
// than decoration.
const CHIP_MAIN    = "bg-primary/10 text-primary"
const CHIP_VAULTS  = "bg-accent text-accent-foreground"
const CHIP_TOOLS   = "bg-secondary text-secondary-foreground"
const CHIP_SYSTEM  = "bg-muted text-muted-foreground"

const mainItems: NavItem[] = [
  { label: "Home",         icon: Home,          path: Routes.DASHBOARD,    chip: CHIP_MAIN },
  { label: "Chat",         icon: MessageSquare, path: Routes.PLAYGROUND,   chip: CHIP_MAIN },
  { label: "Sessions",     icon: History,       path: Routes.SESSIONS,     chip: CHIP_MAIN },
]

const vaultItems: NavItem[] = [
  { label: "Knowledge",    icon: BookOpen,      path: Routes.KNOWLEDGE,    chip: CHIP_VAULTS },
  { label: "Prompts",      icon: BookMarked,    path: Routes.PROMPTS,      chip: CHIP_VAULTS },
  { label: "Skills",       icon: Sparkles,      path: Routes.SKILLS,       chip: CHIP_VAULTS },
  { label: "Secrets",      icon: Key,           path: Routes.SECRETS,      chip: CHIP_VAULTS },
  { label: "Markdown",     icon: FileText,      path: Routes.VAULT,        chip: CHIP_VAULTS },
]

const toolItems: NavItem[] = [
  { label: "Evals",        icon: FlaskConical,  path: Routes.EVALS,         chip: CHIP_TOOLS },
  { label: "Observability",icon: BarChart2,     path: Routes.OBSERVABILITY, chip: CHIP_TOOLS },
  { label: "Channels",     icon: MessageCircle, path: Routes.CHANNELS,      chip: CHIP_TOOLS },
]

const systemItems: NavItem[] = [
  { label: "Settings",     icon: Settings,      path: Routes.SETTINGS,     chip: CHIP_SYSTEM },
]

const adminItems: NavItem[] = [
  { label: "Admin",        icon: Shield,        path: Routes.ADMIN_PANEL,  chip: CHIP_SYSTEM },
]

const groups: { label: string; items: NavItem[] }[] = [
  { label: "",        items: mainItems },
  { label: "Vaults",  items: vaultItems },
  { label: "Tools",   items: toolItems },
  { label: "System",  items: systemItems },
]

export function AppSidebar() {
  const pathname = usePathname()
  const { data: session } = useSession()
  const userRole = (session?.user as { role?: string })?.role
  const { resolvedTheme, setTheme } = useTheme()
  const [collapsed, setCollapsed] = useState(false)

  const isActive = (item: NavItem) =>
    pathname === item.path ||
    (item.path === Routes.PLAYGROUND && pathname.startsWith("/playground"))

  const displayName = session?.user?.name || session?.user?.email || "User"

  const renderItem = (item: NavItem) => {
    const active = isActive(item)
    const link = (
      <Link
        key={item.path}
        href={item.path}
        className={cn(
          "relative flex items-center gap-3 rounded-xl text-sm transition-colors",
          collapsed ? "justify-center h-11 w-11 mx-auto" : "px-2.5 py-2",
          active
            ? "text-sidebar-foreground font-medium"
            : "text-muted-foreground hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
        )}
      >
        {active && (
          <motion.div
            layoutId="sidebar-active-pill"
            className="absolute inset-0 bg-sidebar-accent rounded-xl shadow-sm"
            transition={springTransition}
          />
        )}
        <span className={cn("relative flex items-center justify-center h-7 w-7 rounded-lg shrink-0", item.chip)}>
          <item.icon className="h-3.5 w-3.5" />
        </span>
        {!collapsed && <span className="relative">{item.label}</span>}
      </Link>
    )

    if (!collapsed) return link

    return (
      <Tooltip key={item.path} delayDuration={200}>
        <TooltipTrigger asChild>{link}</TooltipTrigger>
        <TooltipContent side="right">{item.label}</TooltipContent>
      </Tooltip>
    )
  }

  return (
    <TooltipProvider>
      <motion.div
        animate={{ width: collapsed ? 76 : 288 }}
        transition={{ type: "spring", stiffness: 300, damping: 30 }}
        className="flex flex-col h-full bg-sidebar text-sidebar-foreground border-r border-sidebar-border shrink-0 overflow-hidden"
      >
        {/* Logo */}
        <div className={cn(
          "flex items-center h-14 border-b border-sidebar-border shrink-0",
          collapsed ? "justify-center px-2" : "justify-between px-5"
        )}>
          {collapsed ? (
            <LogoMark className="h-5 w-5" />
          ) : (
            <Logo className="h-5" />
          )}
          {!collapsed && (
            <button
              onClick={() => setCollapsed(true)}
              className="h-7 w-7 flex items-center justify-center rounded-md text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-foreground transition-colors shrink-0"
              aria-label="Collapse sidebar"
            >
              <ChevronsLeft className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Profile card */}
        <div className={cn("shrink-0", collapsed ? "px-2 pt-4" : "px-4 pt-5")}>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              {collapsed ? (
                <button className="flex items-center justify-center w-full h-11 rounded-xl hover:bg-sidebar-accent/50 transition-colors" aria-label="Account menu">
                  <Avatar className="h-9 w-9">
                    <AvatarFallback className="bg-primary/10 text-primary text-sm font-medium">
                      {displayName[0]?.toUpperCase() || "U"}
                    </AvatarFallback>
                  </Avatar>
                </button>
              ) : (
                <button className="flex flex-col items-center w-full rounded-xl px-3 py-4 hover:bg-sidebar-accent/40 transition-colors text-center">
                  <Avatar className="h-14 w-14 mb-2">
                    <AvatarFallback className="bg-primary/10 text-primary text-lg font-medium">
                      {displayName[0]?.toUpperCase() || "U"}
                    </AvatarFallback>
                  </Avatar>
                  <p className="text-sm font-medium truncate max-w-full">{displayName}</p>
                  <p className="text-xs text-muted-foreground truncate max-w-full">
                    {userRole === "admin" ? "Administrator" : "Member"}
                  </p>
                </button>
              )}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" side={collapsed ? "right" : "bottom"} className="w-48">
              <div className="px-2 py-1.5">
                <p className="text-xs text-muted-foreground">Signed in as</p>
                <p className="text-sm font-medium truncate">{session?.user?.email}</p>
              </div>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="cursor-pointer"
                onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
              >
                {resolvedTheme === "dark" ? (
                  <Sun className="h-4 w-4 mr-2" />
                ) : (
                  <Moon className="h-4 w-4 mr-2" />
                )}
                {resolvedTheme === "dark" ? "Light mode" : "Dark mode"}
              </DropdownMenuItem>
              {collapsed && (
                <DropdownMenuItem className="cursor-pointer" onClick={() => setCollapsed(false)}>
                  <ChevronsRight className="h-4 w-4 mr-2" />
                  Expand sidebar
                </DropdownMenuItem>
              )}
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

        {/* Navigation */}
        <nav className={cn("flex-1 overflow-y-auto", collapsed ? "px-2 py-3" : "px-3 py-3")}>
          {groups.map((group, gi) => (
            <div key={gi} className={gi > 0 ? "mt-4" : ""}>
              {group.label && !collapsed && (
                <p className="px-2.5 mb-1.5 text-[11px] font-medium uppercase tracking-[0.06em] text-sidebar-foreground/50">
                  {group.label}
                </p>
              )}
              {group.label && collapsed && (
                <div className="my-3 h-px bg-sidebar-border mx-2" />
              )}
              <div className={cn(collapsed ? "space-y-1.5" : "space-y-0.5")}>
                {group.items.map(renderItem)}
                {/* Inject admin item after System group */}
                {group.label === "System" && userRole === "admin" && adminItems.map(renderItem)}
              </div>
            </div>
          ))}
        </nav>

        {/* Promo / CTA card */}
        {!collapsed && (
          <div className="px-4 pb-4 shrink-0">
            <Link
              href={Routes.DASHBOARD}
              className="group relative block overflow-hidden rounded-xl bg-sidebar-accent px-4 py-4 transition-colors hover:bg-sidebar-accent/80"
            >
              <Bot className="h-5 w-5 text-sidebar-primary mb-2" />
              <p className="text-sm font-medium text-sidebar-foreground">Create an agent</p>
              <p className="text-xs text-muted-foreground mt-0.5 leading-snug">
                Set up a new AI agent from your dashboard.
              </p>
            </Link>
          </div>
        )}

        {collapsed && (
          <div className="px-2 py-2 border-t border-sidebar-border flex justify-center shrink-0">
            <Tooltip delayDuration={200}>
              <TooltipTrigger asChild>
                <button
                  onClick={() => setCollapsed(false)}
                  className="h-9 w-9 flex items-center justify-center rounded-md text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-foreground transition-colors"
                  aria-label="Expand sidebar"
                >
                  <ChevronsRight className="h-4 w-4" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="right">Expand sidebar</TooltipContent>
            </Tooltip>
          </div>
        )}
      </motion.div>
    </TooltipProvider>
  )
}
