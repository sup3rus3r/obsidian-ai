"use client"

import { Collapsible as CollapsiblePrimitive } from "radix-ui"
import { cn } from "@/lib/utils"
import { ChevronDown, Circle } from "lucide-react"
import React from "react"

export type ChainOfThoughtItemProps = React.ComponentProps<"div">

export const ChainOfThoughtItem = ({
  children,
  className,
  ...props
}: ChainOfThoughtItemProps) => (
  <div className={cn("text-muted-foreground text-sm", className)} {...props}>
    {children}
  </div>
)

export type ChainOfThoughtTriggerProps = React.ComponentProps<
  typeof CollapsiblePrimitive.Trigger
> & {
  leftIcon?: React.ReactNode
  swapIconOnHover?: boolean
}

export const ChainOfThoughtTrigger = ({
  children,
  className,
  leftIcon,
  swapIconOnHover = true,
  ...props
}: ChainOfThoughtTriggerProps) => (
  <CollapsiblePrimitive.Trigger
    className={cn(
      "group/trigger text-muted-foreground hover:text-foreground flex cursor-pointer items-center justify-start gap-1 text-left text-sm transition-colors",
      className
    )}
    {...props}
  >
    <div className="flex items-center gap-2">
      {leftIcon ? (
        <span className="relative inline-flex size-4 items-center justify-center">
          <span
            className={cn(
              "transition-opacity",
              swapIconOnHover && "group-hover/trigger:opacity-0"
            )}
          >
            {leftIcon}
          </span>
          {swapIconOnHover && (
            <ChevronDown className="absolute size-4 opacity-0 transition-opacity group-hover/trigger:opacity-100 group-data-[state=open]/trigger:rotate-180" />
          )}
        </span>
      ) : (
        <span className="relative inline-flex size-4 items-center justify-center">
          <Circle className="size-2 fill-current" />
        </span>
      )}
      <span>{children}</span>
    </div>
    {!leftIcon && (
      <ChevronDown className="size-4 transition-transform group-data-[state=open]/trigger:rotate-180" />
    )}
  </CollapsiblePrimitive.Trigger>
)

export type ChainOfThoughtContentProps = React.ComponentProps<
  typeof CollapsiblePrimitive.Content
>

export const ChainOfThoughtContent = ({
  children,
  className,
  ...props
}: ChainOfThoughtContentProps) => {
  return (
    <CollapsiblePrimitive.Content
      className={cn(
        "text-popover-foreground data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down overflow-hidden",
        className
      )}
      {...props}
    >
      <div className="ml-1.75 border-l border-primary/20 pl-4 group-data-[last=true]:border-transparent">
        <div className="mt-2 space-y-2">{children}</div>
      </div>
    </CollapsiblePrimitive.Content>
  )
}

export type ChainOfThoughtProps = {
  children: React.ReactNode
  className?: string
}

export function ChainOfThought({ children, className }: ChainOfThoughtProps) {
  const childrenArray = React.Children.toArray(children)

  return (
    <div className={cn("space-y-0", className)}>
      {childrenArray.map((child, index) => (
        <React.Fragment key={index}>
          {React.isValidElement(child) &&
            React.cloneElement(
              child as React.ReactElement<ChainOfThoughtStepProps>,
              {
                isLast: index === childrenArray.length - 1,
              }
            )}
        </React.Fragment>
      ))}
    </div>
  )
}

export type ChainOfThoughtStepProps = {
  children: React.ReactNode
  className?: string
  isLast?: boolean
}

export const ChainOfThoughtStep = ({
  children,
  className,
  isLast = false,
  ...props
}: ChainOfThoughtStepProps & React.ComponentProps<typeof CollapsiblePrimitive.Root>) => {
  return (
    <CollapsiblePrimitive.Root
      className={cn("group", className)}
      data-last={isLast}
      {...props}
    >
      {children}
      <div className="flex justify-start group-data-[last=true]:hidden">
        <div className="bg-primary/20 ml-1.75 h-4 w-px" />
      </div>
    </CollapsiblePrimitive.Root>
  )
}
