"use client"

import * as React from "react"
import { XIcon, Maximize2, Minimize2 } from "lucide-react"
import { Dialog as DialogPrimitive } from "radix-ui"
import { AnimatePresence, motion, type HTMLMotionProps } from "motion/react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { useControlledState } from "@/hooks/use-controlled-state"
import { getStrictContext } from "@/lib/get-strict-context"

type DialogContextType = {
  isOpen: boolean
  setIsOpen: (open: boolean) => void
}

const [DialogProvider, useDialog] =
  getStrictContext<DialogContextType>("DialogContext")

function Dialog(props: React.ComponentProps<typeof DialogPrimitive.Root>) {
  const [isOpen, setIsOpen] = useControlledState({
    value: props?.open,
    defaultValue: props?.defaultOpen,
    onChange: props?.onOpenChange,
  })

  return (
    <DialogProvider value={{ isOpen, setIsOpen }}>
      <DialogPrimitive.Root
        data-slot="dialog"
        {...props}
        onOpenChange={setIsOpen}
      />
    </DialogProvider>
  )
}

function DialogTrigger({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Trigger>) {
  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />
}

function DialogPortal({
  ...props
}: Omit<React.ComponentProps<typeof DialogPrimitive.Portal>, "forceMount">) {
  const { isOpen } = useDialog()

  return (
    <AnimatePresence>
      {isOpen && (
        <DialogPrimitive.Portal
          data-slot="dialog-portal"
          forceMount
          {...props}
        />
      )}
    </AnimatePresence>
  )
}

function DialogClose({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Close>) {
  return <DialogPrimitive.Close data-slot="dialog-close" {...props} />
}

function DialogOverlay({
  className,
  transition = { duration: 0.2, ease: "easeInOut" },
  ...props
}: Omit<
  React.ComponentProps<typeof DialogPrimitive.Overlay>,
  "forceMount" | "asChild"
> &
  HTMLMotionProps<"div">) {
  return (
    <DialogPrimitive.Overlay data-slot="dialog-overlay" asChild forceMount>
      <motion.div
        key="dialog-overlay"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={transition}
        className={cn("fixed inset-0 z-50 bg-overlay", className)}
        {...props}
      />
    </DialogPrimitive.Overlay>
  )
}

function DialogContent({
  className,
  children,
  showCloseButton = true,
  showFullscreenButton = false,
  from = "top",
  onOpenAutoFocus,
  onCloseAutoFocus,
  onEscapeKeyDown,
  onPointerDownOutside,
  onInteractOutside,
  transition = { type: "spring", stiffness: 150, damping: 25 },
  ...props
}: Omit<
  React.ComponentProps<typeof DialogPrimitive.Content>,
  "forceMount" | "asChild"
> &
  HTMLMotionProps<"div"> & {
    showCloseButton?: boolean
    /** Adds a maximize/restore toggle next to the close button, letting the user
     *  expand the dialog to fill the viewport — useful for dialogs with long-form
     *  content (skill/prompt instructions, code, etc.) that outgrow the default size. */
    showFullscreenButton?: boolean
    from?: "top" | "bottom" | "left" | "right"
  }) {
  const initialRotation =
    from === "bottom" || from === "left" ? "20deg" : "-20deg"
  const isVertical = from === "top" || from === "bottom"
  const rotateAxis = isVertical ? "rotateX" : "rotateY"
  const [isFullscreen, setIsFullscreen] = React.useState(false)

  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Content
        asChild
        forceMount
        onOpenAutoFocus={onOpenAutoFocus}
        onCloseAutoFocus={onCloseAutoFocus}
        onEscapeKeyDown={onEscapeKeyDown}
        onPointerDownOutside={onPointerDownOutside}
        onInteractOutside={onInteractOutside}
      >
        <motion.div
          key="dialog-content"
          data-slot="dialog-content"
          data-fullscreen={isFullscreen || undefined}
          initial={{
            opacity: 0,
            filter: "blur(4px)",
            transform: `perspective(500px) ${rotateAxis}(${initialRotation}) scale(0.8)`,
          }}
          animate={{
            opacity: 1,
            filter: "blur(0px)",
            transform: `perspective(500px) ${rotateAxis}(0deg) scale(1)`,
          }}
          exit={{
            opacity: 0,
            filter: "blur(4px)",
            transform: `perspective(500px) ${rotateAxis}(${initialRotation}) scale(0.8)`,
          }}
          transition={transition}
          className={cn(
            "bg-background fixed top-[50%] left-[50%] z-50 grid w-full max-w-[calc(100%-2rem)] max-h-[calc(100vh-2rem)] translate-x-[-50%] translate-y-[-50%] gap-4 overflow-y-auto rounded-2xl border p-6 shadow-xl outline-none sm:max-w-lg",
            isFullscreen &&
              "top-4! left-4! translate-x-0! translate-y-0! max-w-none! w-[calc(100%-2rem)]! h-[calc(100vh-2rem)]! max-h-[calc(100vh-2rem)]! flex! flex-col!",
            className
          )}
          {...props}
        >
          {children}
          <div className="absolute top-4 right-4 flex items-center gap-1">
            {showFullscreenButton && (
              <button
                type="button"
                onClick={() => setIsFullscreen((v) => !v)}
                className="ring-offset-background focus:ring-ring text-muted-foreground rounded-lg p-1.5 opacity-70 cursor-pointer transition-all hover:opacity-100 hover:bg-accent hover:text-foreground focus:ring-2 focus:ring-offset-2 focus:outline-hidden [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4"
                title={isFullscreen ? "Restore" : "Expand to fullscreen"}
              >
                {isFullscreen ? <Minimize2 /> : <Maximize2 />}
                <span className="sr-only">{isFullscreen ? "Restore" : "Expand to fullscreen"}</span>
              </button>
            )}
            {showCloseButton && (
              <DialogPrimitive.Close
                data-slot="dialog-close"
                className="ring-offset-background focus:ring-ring data-[state=open]:bg-accent data-[state=open]:text-muted-foreground rounded-lg p-1.5 opacity-70 cursor-pointer transition-all hover:opacity-100 hover:bg-accent focus:ring-2 focus:ring-offset-2 focus:outline-hidden disabled:pointer-events-none [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4"
              >
                <XIcon />
                <span className="sr-only">Close</span>
              </DialogPrimitive.Close>
            )}
          </div>
        </motion.div>
      </DialogPrimitive.Content>
    </DialogPortal>
  )
}

function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-header"
      className={cn("flex flex-col gap-2 text-center sm:text-left shrink-0", className)}
      {...props}
    />
  )
}

function DialogFooter({
  className,
  showCloseButton = false,
  children,
  ...props
}: React.ComponentProps<"div"> & {
  showCloseButton?: boolean
}) {
  return (
    <div
      data-slot="dialog-footer"
      className={cn(
        "flex flex-col-reverse gap-2 sm:flex-row sm:justify-end shrink-0",
        className
      )}
      {...props}
    >
      {children}
      {showCloseButton && (
        <DialogPrimitive.Close asChild>
          <Button variant="outline">Close</Button>
        </DialogPrimitive.Close>
      )}
    </div>
  )
}

function DialogTitle({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      data-slot="dialog-title"
      className={cn("text-xl leading-none font-medium tracking-[-0.016em]", className)}
      {...props}
    />
  )
}

function DialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description
      data-slot="dialog-description"
      className={cn("text-muted-foreground text-sm", className)}
      {...props}
    />
  )
}

export {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
}
