"use client"

import * as React from "react"
import { motion, type HTMLMotionProps } from "motion/react"
import { cn } from "@/lib/utils"

interface AnimatedListProps extends HTMLMotionProps<"div"> {
  staggerDelay?: number
  initialDelay?: number
  children: React.ReactNode
}

function AnimatedList({
  children,
  staggerDelay = 0.05,
  initialDelay = 0,
  className,
  ...props
}: AnimatedListProps) {
  return (
    <motion.div
      className={cn(className)}
      initial="hidden"
      animate="visible"
      variants={{
        hidden: {},
        visible: {
          transition: {
            staggerChildren: staggerDelay,
            delayChildren: initialDelay,
          },
        },
      }}
      {...props}
    >
      {children}
    </motion.div>
  )
}

interface AnimatedListItemProps extends HTMLMotionProps<"div"> {
  children: React.ReactNode
}

function AnimatedListItem({
  children,
  className,
  ...props
}: AnimatedListItemProps) {
  return (
    <motion.div
      className={cn(className)}
      initial={{ opacity: 0, y: 12, filter: "blur(4px)" }}
      animate={{
        opacity: 1,
        y: 0,
        filter: "blur(0px)",
        transition: { type: "spring", stiffness: 200, damping: 24 },
      }}
      variants={{
        hidden: { opacity: 0, y: 12, filter: "blur(4px)" },
        visible: {
          opacity: 1,
          y: 0,
          filter: "blur(0px)",
          transition: { type: "spring", stiffness: 200, damping: 24 },
        },
      }}
      {...props}
    >
      {children}
    </motion.div>
  )
}

export { AnimatedList, AnimatedListItem }
