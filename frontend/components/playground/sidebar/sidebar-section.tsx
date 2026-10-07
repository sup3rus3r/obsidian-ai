"use client"

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"

interface SidebarSectionProps {
  icon?: React.ReactNode
  title: string
  badge?: React.ReactNode
  action?: React.ReactNode
  defaultOpen?: boolean
  children: React.ReactNode
  className?: string
}

export function SidebarSection({
  icon,
  title,
  badge,
  action,
  defaultOpen = false,
  children,
  className,
}: SidebarSectionProps) {
  return (
    <Collapsible defaultOpen={defaultOpen} className={cn("space-y-2", className)}>
      <div className="flex items-center justify-between">
        <CollapsibleTrigger className="flex items-center gap-2 cursor-pointer group/section hover:text-foreground transition-colors">
          {icon}
          <span className="text-[11px] font-medium text-sidebar-foreground/50 uppercase tracking-[0.06em] group-hover/section:text-sidebar-foreground transition-colors">
            {title}
          </span>
          {badge}
          <ChevronDown className="h-3 w-3 text-muted-foreground transition-transform duration-200 group-data-[state=closed]/section:-rotate-90" />
        </CollapsibleTrigger>
        {action && (
          <div className="shrink-0" onClick={(e) => e.stopPropagation()}>
            {action}
          </div>
        )}
      </div>
      <CollapsibleContent>
        {children}
      </CollapsibleContent>
    </Collapsible>
  )
}
