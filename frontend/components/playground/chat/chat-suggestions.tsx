"use client"

import { useMemo } from "react"
import { PromptSuggestion } from "@/components/ai-elements/prompt-suggestion"
import { Bot, Users } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import type { Agent, Team } from "@/types/playground"

interface ChatSuggestionsProps {
  agent?: Agent
  team?: Team
  teamAgents?: Agent[]
  mode: "agent" | "team"
  onSelect: (prompt: string) => void
}

interface Suggestion {
  label: string
  prompt: string
}

const TOOL_SUGGESTIONS: Record<string, Suggestion[]> = {
  web_search: [
    { label: "Research & summarize", prompt: "Search the web and write a comprehensive summary artifact on the current state of AI agents in 2025 — cover key players, capabilities, and trends." },
    { label: "Competitive analysis", prompt: "Search the web and create a competitive analysis artifact comparing the top 5 players in" },
  ],
  file_read: [
    { label: "Analyze a file", prompt: "Read the file at this path and produce a structured summary artifact with key findings:" },
  ],
  file_write: [
    { label: "Generate & save a file", prompt: "Write a well-structured markdown document about the following topic and save it to disk:" },
  ],
  code_interpreter: [
    { label: "Build & run a script", prompt: "Write and run a Python script that generates a bar chart of monthly revenue from this data, then show me the output:" },
    { label: "Data analysis", prompt: "Analyze this dataset, find patterns and anomalies, and produce a clean summary report:" },
  ],
  sql_query: [
    { label: "Explore the database", prompt: "Inspect the database schema, list all tables with row counts, and write a query to surface the most interesting insights." },
  ],
  api_call: [
    { label: "Hit an API", prompt: "Call this API endpoint and present the response in a clean formatted artifact:" },
  ],
  calculator: [
    { label: "Complex calculation", prompt: "Calculate the compound growth rate and produce a year-by-year projection table for an investment of $10,000 at 8% annual return over 20 years." },
  ],
  email: [
    { label: "Draft a polished email", prompt: "Draft a professional email artifact that I can copy — subject: project update, tone: confident but collaborative." },
  ],
  slack: [
    { label: "Write a Slack update", prompt: "Draft a concise Slack message announcing a new feature launch to the engineering team." },
  ],
}

const KEYWORD_SUGGESTIONS: { keywords: string[]; suggestions: Suggestion[] }[] = [
  {
    keywords: ["code", "coding", "developer", "programming", "engineer", "software"],
    suggestions: [
      { label: "Build a landing page", prompt: "Build a modern, responsive HTML landing page for a SaaS product called 'Nexus' — dark theme, hero section, features grid, and a CTA button." },
      { label: "Create a component", prompt: "Write a reusable React component for a data table with sorting and pagination. Include the full TypeScript code as an artifact." },
      { label: "Debug my code", prompt: "Review this code, identify bugs and performance issues, and return a corrected version as an artifact:\n\n```\n\n```" },
    ],
  },
  {
    keywords: ["write", "writing", "content", "copywriter", "blog", "article"],
    suggestions: [
      { label: "Write a blog post", prompt: "Write a full blog post artifact (800 words) about the future of AI agents — include a compelling intro, 3 key sections, and a strong conclusion." },
      { label: "Craft a pitch deck outline", prompt: "Create a pitch deck outline artifact for a startup idea I'll describe — include slide titles, bullet points, and speaker notes." },
      { label: "Rewrite & improve", prompt: "Rewrite the following text to be clearer, more engaging, and professional. Return the improved version as an artifact:\n\n" },
    ],
  },
  {
    keywords: ["data", "analyst", "analytics", "metrics", "dashboard"],
    suggestions: [
      { label: "Build a dashboard", prompt: "Create an interactive HTML dashboard artifact showing mock KPIs — revenue, DAU, churn rate — with colored cards and a simple chart." },
      { label: "Analyze & report", prompt: "Analyze this data and produce a structured report artifact with key insights, trends, and recommended actions:" },
      { label: "Design a schema", prompt: "Design a database schema for an analytics platform tracking user events. Return the SQL CREATE TABLE statements as an artifact." },
    ],
  },
  {
    keywords: ["customer", "support", "help", "service", "ticket"],
    suggestions: [
      { label: "Build a FAQ page", prompt: "Create a styled HTML FAQ page artifact for a SaaS product — include 8 common questions with clear answers and a clean accordion layout." },
      { label: "Draft a response template", prompt: "Write a set of 5 reusable customer support response templates as a markdown artifact — cover: billing, bug reports, feature requests, onboarding, and cancellation." },
    ],
  },
  {
    keywords: ["research", "academic", "paper", "study", "literature"],
    suggestions: [
      { label: "Literature summary", prompt: "Write a structured literature review artifact on the topic of retrieval-augmented generation (RAG) — cover key papers, findings, and open problems." },
      { label: "Compare approaches", prompt: "Compare and contrast these two approaches in a side-by-side markdown artifact with a recommendation section:" },
    ],
  },
  {
    keywords: ["plan", "project", "manage", "strategy", "roadmap"],
    suggestions: [
      { label: "Build a roadmap", prompt: "Create a 90-day product roadmap artifact in markdown — organize by weeks, include milestones, deliverables, and owners." },
      { label: "Write a PRD", prompt: "Write a Product Requirements Document artifact for the following feature — include problem statement, user stories, acceptance criteria, and out-of-scope items:" },
    ],
  },
  {
    keywords: ["sql", "database", "query", "postgres", "mysql", "sqlite"],
    suggestions: [
      { label: "Design a schema", prompt: "Design a normalized database schema for a multi-tenant SaaS app. Return the full SQL as an artifact with comments explaining each table." },
      { label: "Optimize a query", prompt: "Analyze and optimize this slow SQL query. Return the improved version with an explanation of each change:\n\n```sql\n\n```" },
    ],
  },
  {
    keywords: ["ui", "ux", "design", "frontend", "css", "tailwind", "html"],
    suggestions: [
      { label: "Build a UI component", prompt: "Build a polished HTML + Tailwind CSS pricing table artifact with 3 tiers (Free, Pro, Enterprise) — include feature lists and highlighted recommended plan." },
      { label: "Create a style guide", prompt: "Create an HTML style guide artifact showcasing a design system — typography, color palette, buttons, form inputs, and card components." },
    ],
  },
]

const TEAM_MODE_SUGGESTIONS: Record<string, Suggestion[]> = {
  coordinate: [
    { label: "Full-stack feature", prompt: "Coordinate the team to plan, design, and implement a user authentication feature — assign backend API, frontend UI, and testing to the right agents." },
    { label: "Research & write", prompt: "Have the team research a topic thoroughly and produce a polished long-form artifact — one agent gathers facts, another writes the final piece." },
  ],
  route: [
    { label: "Route to the right expert", prompt: "I need help with a complex problem — route me to the right agent and have them solve it end to end:" },
    { label: "Best agent for this task", prompt: "Which agent in this team is best suited to build a responsive landing page? Have them do it." },
  ],
  collaborate: [
    { label: "Multi-perspective review", prompt: "Have each agent review this proposal from their area of expertise and compile a joint feedback artifact:" },
    { label: "Collaborative document", prompt: "Have the team collaborate to write a comprehensive technical specification artifact for the following system:" },
  ],
}

const DEFAULT_SUGGESTIONS: Suggestion[] = [
  { label: "Build a landing page", prompt: "Build me a beautiful, modern HTML landing page for a product called 'Alos' — dark theme, hero with a gradient headline, features section, and a get-started CTA." },
  { label: "Create a dashboard", prompt: "Create an interactive HTML dashboard artifact with mock analytics data — revenue trend, user growth, and top events displayed in a clean dark-themed layout." },
  { label: "Write a PRD", prompt: "Write a Product Requirements Document artifact for an AI-powered note-taking app — include problem statement, user stories, and acceptance criteria." },
  { label: "What can you do?", prompt: "Show me what you can do — give me an impressive demo of your most powerful capability." },
]

function buildSuggestions(
  agent?: Agent,
  team?: Team,
  teamAgents?: Agent[],
  mode?: "agent" | "team"
): Suggestion[] {
  const suggestions: Suggestion[] = []
  const seen = new Set<string>()

  const add = (s: Suggestion) => {
    if (!seen.has(s.prompt)) {
      seen.add(s.prompt)
      suggestions.push(s)
    }
  }

  if (mode === "team" && team) {
    // Team-mode specific suggestions
    const modeSuggestions = TEAM_MODE_SUGGESTIONS[team.mode]
    if (modeSuggestions) {
      modeSuggestions.forEach(add)
    }

    // If team has agents with tools, gather tool suggestions
    if (teamAgents) {
      const allTools = new Set(teamAgents.flatMap((a) => a.tools || []))
      for (const tool of allTools) {
        const toolKey = Object.keys(TOOL_SUGGESTIONS).find(
          (k) => tool.toLowerCase().includes(k) || k.includes(tool.toLowerCase())
        )
        if (toolKey) {
          TOOL_SUGGESTIONS[toolKey].forEach(add)
        }
      }

      // Agent-name based suggestions for teams
      if (teamAgents.length > 1) {
        add({
          label: "Compare agent outputs",
          prompt: `Ask each agent (${teamAgents.map((a) => a.name).join(", ")}) to give their take on`,
        })
      }
    }
  }

  if (mode === "agent" && agent) {
    // Tool-based suggestions
    if (agent.tools && agent.tools.length > 0) {
      for (const tool of agent.tools) {
        const toolKey = Object.keys(TOOL_SUGGESTIONS).find(
          (k) => tool.toLowerCase().includes(k) || k.includes(tool.toLowerCase())
        )
        if (toolKey) {
          TOOL_SUGGESTIONS[toolKey].forEach(add)
        }
      }
    }

    // Keyword matching from name, description, and system prompt
    const searchText = [
      agent.name,
      agent.description,
      agent.system_prompt,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()

    for (const entry of KEYWORD_SUGGESTIONS) {
      if (entry.keywords.some((kw) => searchText.includes(kw))) {
        entry.suggestions.forEach(add)
      }
    }

    // MCP server hints
    if (agent.mcp_server_ids && agent.mcp_server_ids.length > 0) {
      add({
        label: "List available tools",
        prompt: "List all the tools and integrations you have access to, with a brief description of each",
      })
    }
  }

  // Always add some defaults if we don't have enough
  if (suggestions.length < 2) {
    DEFAULT_SUGGESTIONS.forEach(add)
  }

  // Cap at 4 suggestions
  return suggestions.slice(0, 4)
}

export function ChatSuggestions({
  agent,
  team,
  teamAgents,
  mode,
  onSelect,
}: ChatSuggestionsProps) {
  const name = mode === "agent" ? agent?.name : team?.name
  const description = mode === "agent" ? agent?.description : team?.description

  const suggestions = useMemo(
    () => buildSuggestions(agent, team, teamAgents, mode),
    [agent, team, teamAgents, mode]
  )

  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-6 px-4">
      {/* Header */}
      <div className="flex flex-col items-center gap-3">
        <div className="flex items-center justify-center h-14 w-14 rounded-2xl bg-muted">
          <Bot className="h-7 w-7 text-muted-foreground" />
        </div>
        <div className="text-center space-y-1.5">
          <h2 className="text-lg font-semibold">
            {name || "Start a conversation"}
          </h2>
          {description && (
            <p className="text-sm text-muted-foreground max-w-md">
              {description}
            </p>
          )}
        </div>
      </div>

      {/* Team members */}
      {mode === "team" && teamAgents && teamAgents.length > 0 && (
        <div className="flex flex-col items-center gap-2 max-w-md">
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Users className="h-3 w-3" />
            <span>{teamAgents.length} agent{teamAgents.length !== 1 ? "s" : ""} &middot; {team?.mode}</span>
          </div>
          <div className="flex flex-wrap justify-center gap-1.5">
            {teamAgents.map((a) => (
              <Badge key={a.id} variant="outline" className="text-[11px]">
                {a.name}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Contextual suggestions */}
      <div className="flex flex-wrap justify-center gap-2 max-w-lg">
        {suggestions.map((s) => (
          <PromptSuggestion
            key={s.prompt}
            onClick={() => onSelect(s.prompt)}
            className="text-xs h-auto py-2 px-4"
          >
            {s.label}
          </PromptSuggestion>
        ))}
      </div>
    </div>
  )
}
