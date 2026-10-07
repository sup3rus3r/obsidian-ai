export function LogoMark({ className = "h-5 w-5" }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <path
        d="M12 1.5 L21.5 7 V17 L12 22.5 L2.5 17 V7 Z"
        fill="currentColor"
        className="text-primary"
      />
      <path
        d="M12 7 L16.5 9.5 V14.5 L12 17 L7.5 14.5 V9.5 Z"
        fill="currentColor"
        className="text-sidebar"
      />
    </svg>
  )
}

export default function Logo({ className = "h-6 w-auto" }) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <LogoMark className="h-5 w-5 shrink-0" />
      <span className="font-medium text-[15px] tracking-[0.02em] uppercase text-foreground leading-none">
        OBSIDIAN<span className="font-bold text-muted-foreground">AI</span>
      </span>
    </div>
  )
}
