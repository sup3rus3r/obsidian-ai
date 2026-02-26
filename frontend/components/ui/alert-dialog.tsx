"use client"

import * as React from "react"
import { AlertDialog as AlertDialogPrimitive } from "radix-ui"
import { AnimatePresence, motion } from "motion/react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { useControlledState } from "@/hooks/use-controlled-state"
import { getStrictContext } from "@/lib/get-strict-context"

type AlertDialogContextType = {
  isOpen: boolean
  setIsOpen: (open: boolean) => void
}

const [AlertDialogProvider, useAlertDialog] =
  getStrictContext<AlertDialogContextType>("AlertDialogContext")

function AlertDialog(
  props: React.ComponentProps<typeof AlertDialogPrimitive.Root>,
) {
  const [isOpen, setIsOpen] = useControlledState({
    value: props?.open,
    defaultValue: props?.defaultOpen,
    onChange: props?.onOpenChange,
  })

  return (
    <AlertDialogProvider value={{ isOpen, setIsOpen }}>
      <AlertDialogPrimitive.Root
        data-slot="alert-dialog"
        {...props}
        open={isOpen}
        onOpenChange={setIsOpen}
      />
    </AlertDialogProvider>
  )
}

function AlertDialogTrigger({
  ...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Trigger>) {
  return (
    <AlertDialogPrimitive.Trigger data-slot="alert-dialog-trigger" {...props} />
  )
}

function AlertDialogContent({
  className,
  children,
  ...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Content>) {
  const { isOpen } = useAlertDialog()

  return (
    <AnimatePresence>
      {isOpen && (
        <AlertDialogPrimitive.Portal forceMount>
          <AlertDialogPrimitive.Overlay forceMount asChild>
            <motion.div
              key="alert-dialog-overlay"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2, ease: "easeInOut" }}
              className="fixed inset-0 z-50 bg-black/50"
            />
          </AlertDialogPrimitive.Overlay>
          <AlertDialogPrimitive.Content
            forceMount
            {...props}
            className="fixed top-[50%] left-[50%] z-50 translate-x-[-50%] translate-y-[-50%] outline-none bg-transparent! border-none! p-0! shadow-none!"
          >
            <motion.div
              key="alert-dialog-content"
              data-slot="alert-dialog-content"
              initial={{
                opacity: 0,
                scale: 0.95,
                y: -10,
              }}
              animate={{
                opacity: 1,
                scale: 1,
                y: 0,
              }}
              exit={{
                opacity: 0,
                scale: 0.95,
                y: -10,
              }}
              transition={{ type: "spring", stiffness: 150, damping: 25 }}
              className={cn(
                "bg-background grid w-full max-w-[calc(100vw-2rem)] gap-4 rounded-lg border p-6 shadow-lg sm:max-w-md",
                className,
              )}
            >
              {children}
            </motion.div>
          </AlertDialogPrimitive.Content>
        </AlertDialogPrimitive.Portal>
      )}
    </AnimatePresence>
  )
}

function AlertDialogHeader({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-dialog-header"
      className={cn("flex flex-col gap-2 text-center sm:text-left", className)}
      {...props}
    />
  )
}

function AlertDialogFooter({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-dialog-footer"
      className={cn(
        "flex flex-col-reverse gap-2 sm:flex-row sm:justify-end",
        className,
      )}
      {...props}
    />
  )
}

function AlertDialogTitle({
  className,
  ...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Title>) {
  return (
    <AlertDialogPrimitive.Title
      data-slot="alert-dialog-title"
      className={cn("text-lg leading-none font-semibold", className)}
      {...props}
    />
  )
}

function AlertDialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Description>) {
  return (
    <AlertDialogPrimitive.Description
      data-slot="alert-dialog-description"
      className={cn("text-muted-foreground text-sm", className)}
      {...props}
    />
  )
}

function AlertDialogAction({
  className,
  variant,
  ...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Action> &
  Pick<React.ComponentProps<typeof Button>, "variant">) {
  return (
    <AlertDialogPrimitive.Action asChild>
      <Button variant={variant} className={cn(className)} {...props} />
    </AlertDialogPrimitive.Action>
  )
}

function AlertDialogCancel({
  className,
  ...props
}: React.ComponentProps<typeof AlertDialogPrimitive.Cancel>) {
  return (
    <AlertDialogPrimitive.Cancel asChild>
      <Button variant="outline" className={cn(className)} {...props} />
    </AlertDialogPrimitive.Cancel>
  )
}

export {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
}
