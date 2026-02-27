

export default function Logo({ className = "h-6 w-auto" }) {
    return (
    <svg viewBox="0 0 170 28" className={className} aria-label="Obsidian AI">
          <defs>
            <linearGradient id="silver" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#d0d4db" />
              <stop offset="40%" stopColor="#f0f2f5" />
              <stop offset="60%" stopColor="#c8cdd6" />
              <stop offset="100%" stopColor="#9aa0aa" />
            </linearGradient>
            <linearGradient id="blue" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#4a90d9" />
              <stop offset="50%" stopColor="#1e6fbf" />
              <stop offset="100%" stopColor="#0d4f9e" />
            </linearGradient>
          </defs>
          <text
            x="0"
            y="22"
            fontFamily="Arial Black, Arial, sans-serif"
            fontWeight="900"
            fontSize="22"
            letterSpacing="1"
            fill="url(#silver)"
          >
            OBSIDIAN
          </text>
          <text
            x="136"
            y="22"
            fontFamily="Arial Black, Arial, sans-serif"
            fontWeight="900"
            fontSize="22"
            letterSpacing="1"
            fill="url(#blue)"
          >
            AI
          </text>
    </svg>
        )
}