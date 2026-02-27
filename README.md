<div align="center">

<img src="docs/images/obsidian.png" alt="Obsidian AI" width="320" />

### Open-Source AI Agent Management & Orchestration Platform

Build, deploy, and orchestrate AI agents, multi-agent teams, and automated workflows — all from one unified control plane. Supports OpenAI, Anthropic, Google Gemini, Ollama, OpenRouter, and any OpenAI-compatible endpoint.

[![License: PolyForm Noncommercial](https://img.shields.io/badge/License-PolyForm%20NC-blue.svg)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/sup3rus3r/obsidian-ai?style=social)](https://github.com/sup3rus3r/obsidian-ai/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/sup3rus3r/obsidian-ai?style=social)](https://github.com/sup3rus3r/obsidian-ai/network/members)
[![GitHub Issues](https://img.shields.io/github/issues/sup3rus3r/obsidian-ai)](https://github.com/sup3rus3r/obsidian-ai/issues)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=next.js&logoColor=white)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-4-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![MongoDB](https://img.shields.io/badge/MongoDB-47A248?logo=mongodb&logoColor=white)](https://www.mongodb.com/)

---

**If you find this project useful, please consider giving it a star!** It helps others discover the project and motivates continued development.

[**Give it a Star**](https://github.com/sup3rus3r/obsidian-ai) &#11088;

</div>

---


## Table of Contents

- [Why Obsidian AI?](#why-obsidian-ai)
- [Features](#features)
  - [Multi-Provider LLM Support](#multi-provider-llm-support)
  - [Agent Builder](#agent-builder)
  - [Multi-Agent Teams](#multi-agent-teams)
  - [Workflow Automation](#workflow-automation)
  - [Real-Time Chat Playground](#real-time-chat-playground)
  - [Artifacts](#artifacts)
  - [Tool Integration](#tool-integration)
  - [Dynamic Tool Creation](#dynamic-tool-creation)
  - [MCP Protocol Support](#mcp-protocol-support)
  - [Human-in-the-Loop (HITL)](#human-in-the-loop-hitl)
  - [Knowledge Bases & RAG](#knowledge-bases--rag)
  - [Long-Term Agent Memory](#long-term-agent-memory)
  - [Automatic Context Management](#automatic-context-management)
  - [Session History & Execution Traces](#session-history--execution-traces)
  - [Scheduled Workflows](#scheduled-workflows)
  - [Secrets Vault](#secrets-vault)
  - [Security & Authentication](#security--authentication)
  - [Admin Panel & RBAC](#admin-panel--rbac)
  - [Agent Import / Export](#agent-import--export)
  - [Dual Database Support](#dual-database-support)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
  - [Prerequisites](#prerequisites)
  - [Backend Setup](#backend-setup)
  - [Frontend Setup](#frontend-setup)
  - [Running Both Together](#running-both-together)
  - [Environment Variables](#environment-variables)
- [Usage Guide](#usage-guide)
- [API Reference](#api-reference)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Updates](#updates)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Why Obsidian AI?

Most AI agent frameworks are code-only libraries that require deep programming knowledge. **Obsidian AI** provides a complete visual interface for building, managing, and running AI agents — no SDK glue code required.

- **No vendor lock-in** — Swap between OpenAI, Anthropic, Google, Ollama, or any OpenAI-compatible provider without changing a single line of agent configuration.
- **Visual orchestration** — Create multi-agent teams and multi-step workflows from the dashboard. No YAML, no DAGs, no boilerplate.
- **Production-ready security** — JWT auth, TOTP 2FA, AES end-to-end encryption, Fernet secrets vault, role-based access control, and rate limiting out of the box.
- **Self-hosted & open-source** — Run entirely on your own infrastructure. Your data never leaves your servers.
- **MCP-native** — First-class Model Context Protocol support for connecting external tools and services to your agents.

---

## Features

### Multi-Provider LLM Support

Connect to any major LLM provider from a single interface. Add providers with encrypted API key storage, test connections, and switch models per-agent.

| Provider | Models | Type |
|----------|--------|------|
| **OpenAI** | GPT-4.1, GPT-4.1 mini, GPT-4.1 nano, o3, o4-mini, GPT-5, GPT-5 mini | Cloud |
| **Anthropic** | Claude Opus 4.6, Claude Sonnet 4.6, Claude Haiku 4.5 | Cloud |
| **Google** | Gemini 2.5 Pro, Gemini 2.5 Flash, Gemini 3 Flash (Preview) | Cloud |
| **Ollama** | Llama, Mistral, Qwen, Phi, DeepSeek — any local model | Local |
| **OpenRouter** | Access 100+ models through one API key | Cloud |
| **Custom** | Any OpenAI-compatible endpoint (LM Studio, vLLM, etc.) | Self-hosted |

---

### Agent Builder

Create AI agents with custom system prompts, model selection, tool attachments, and MCP server connections. Each agent is fully configurable and can be used standalone or as part of a team or workflow.

- **Custom system prompts** — Define agent behavior, personality, and instructions
- **Per-agent model selection** — Pick the right model for each agent's task
- **Tool attachment** — Equip agents with HTTP, Python, or built-in tools
- **MCP server binding** — Connect agents to external services via MCP
- **Knowledge base attachment** — Assign one or more knowledge bases for persistent RAG context
- **Long-term memory** — Each agent builds a persistent memory of each user across sessions
- **Dynamic tool creation** — Enable agents to propose and create new tools mid-conversation
- **Human-in-the-loop overrides** — Define per-agent tool approval requirements independently of tool-level flags
- **Import / Export** — Share agent configurations as portable JSON files across instances

---

### Multi-Agent Teams

Combine multiple agents into coordinated teams for complex tasks. Choose from three collaboration modes that determine how agents interact.

| Mode | Description | Best For |
|------|-------------|----------|
| **Coordinate** | A lead agent delegates tasks to team members | Task decomposition, project management |
| **Route** | Messages are routed to the most appropriate agent | Customer support, multi-domain Q&A |
| **Collaborate** | Agents build on each other's responses sequentially | Research, content creation, review chains |

---

### Workflow Automation

Define multi-step sequential workflows where each step is handled by a specific agent. Monitor execution in real-time with per-step status tracking.

- **Sequential pipeline** — Chain agents in order; each step receives the previous step's output
- **Per-step agent assignment** — Use different agents (and models) for each step
- **Real-time execution** — Watch workflow progress with live streaming per step
- **Run history** — Track past executions with status (pending, running, completed, failed)
- **Reusable definitions** — Save workflow templates and run them on demand or on a schedule
- **Cron scheduling** — Schedule workflows to run automatically using standard cron expressions

---

### Real-Time Chat Playground

A full-featured chat interface for interacting with agents, teams, and workflows. Powered by Server-Sent Events (SSE) for real-time streaming.

- **Live streaming responses** — Token-by-token output via SSE
- **Tool execution visualization** — See tool calls, parameters, and results inline
- **Chain-of-thought reasoning** — View agent thinking steps for supported models
- **File attachments** — Send images, PDFs, Word docs, markdown, and text files directly in chat
- **Prompt suggestions** — Quick-start prompts to get conversations going
- **Markdown rendering** — GitHub-flavored markdown with syntax highlighting (Shiki), math (KaTeX), and Mermaid diagrams
- **Agentic tool loops** — Agents can execute up to 10 rounds of tool calls per response

---

### Artifacts

When an agent produces substantial standalone content — an HTML page, a code file, an SVG diagram, a JSON payload — it wraps it in a named **artifact** instead of a code block. Artifacts open in a persistent side panel alongside the chat.

- **Rich preview** — HTML, JSX, TSX, SVG, and CSS artifacts render live in a sandboxed iframe
- **Syntax highlighting** — Code view uses Shiki (github-dark theme) for all supported languages
- **In-panel editing** — Switch to Edit mode to modify artifact content directly; changes reflect instantly in the preview
- **Multiple artifacts** — Each session can accumulate multiple artifacts shown as tabs in the panel
- **Copy & download** — One-click copy to clipboard or download with the correct file extension
- **Fullscreen mode** — Expand the artifact panel to fill the entire screen
- **Inline reference chips** — Each artifact appears as a clickable chip in the chat message; the raw XML tag is never shown to the user
- **Live streaming** — The panel opens as soon as the agent starts writing an artifact; an animated tab shows the title while it's being written
- **In-place editing** — When the agent modifies an existing artifact, the tab updates in place rather than opening a new one

**Artifact tag format:**

```
<artifact id="unique_snake_case_id" title="Human-readable title" type="html|jsx|tsx|css|javascript|typescript|python|markdown|json|svg|text">
...content...
</artifact>
```

---

### Tool Integration

Equip agents with tools using pre-built templates or custom definitions. Tools are defined with JSON Schema parameters and can call external APIs, run Python code, or use built-in functions.

| Template | Description |
|----------|-------------|
| **Weather Lookup** | Get current weather for any location |
| **Calculator** | Evaluate mathematical expressions |
| **Web Search** | Search the web for information |
| **Date & Time** | Get the current date and time |
| **API Request** | Call any external REST API endpoint |
| **Custom Python** | Write your own Python handler function |
| **Blank Tool** | Define a tool from scratch with full JSON Schema |

---

### Dynamic Tool Creation

Agents can propose and create new tools mid-conversation — no pre-configuration needed. Enable the **Allow Tool Creation** toggle on any agent, then ask it to build a capability it doesn't have. The agent designs the tool, and a review card appears inline in the chat.

- **Opt-in per agent** — Only agents with the toggle enabled can propose tools
- **Two handler types** — Pure-Python (stdlib only) or HTTP REST endpoint
- **Inline review card** — Shows tool name, description, handler type, collapsible parameter schema and code
- **Immediate availability** — Approved tools are usable by the agent in the same session without a page reload
- **Sidebar auto-refresh** — The tools list updates silently on approval with no disruption to the active chat
- **Safety timeout** — Proposals are auto-rejected after 10 minutes if left unreviewed

---

### MCP Protocol Support

Connect external services via the [Model Context Protocol](https://modelcontextprotocol.io/). MCP servers expose tools that agents can discover and use during conversations.

- **Stdio transport** — Run local MCP servers as child processes (Docker, npx, Python, etc.)
- **SSE transport** — Connect to remote MCP servers over HTTP
- **Connection testing** — Verify server connectivity and discover available tools before saving
- **Environment variables** — Pass API keys and configuration to MCP servers securely
- **Per-agent binding** — Attach specific MCP servers to specific agents

---

### Human-in-the-Loop (HITL)

Pause agent execution before sensitive tool calls and require explicit human approval before proceeding. The agent's streaming generator suspends at the flagged tool, surfaces an approval card in the chat, and only resumes based on the user's decision.

- **Tool-level flag** — Enable "Requires human approval" on any tool via the tool creation dialog
- **Agent-level overrides** — Independently mark tool names in the agent's "Require Approval For" list — triggers HITL even when the tool-level flag is off
- **MCP tool support** — MCP tools can also be flagged via the agent override list
- **Inline approval card** — An amber shield card appears in the streaming message with the tool name, formatted arguments, and Approve / Deny buttons
- **Reconnect safe** — Pending approvals are persisted to the database; reloading the page re-fetches and re-renders the card
- **Auto-deny on timeout** — Approvals left unanswered for 10 minutes are automatically denied
- **Server restart recovery** — All stale pending approvals are auto-denied on startup
- **Zero-polling** — Uses `asyncio.Event` to suspend the generator; the approve/reject HTTP request sets the event, resuming execution with zero busy-waiting

---

### Knowledge Bases & RAG

Persistent, reusable knowledge bases that can be attached to agents for retrieval-augmented generation. Unlike session-level file attachments, knowledge bases are indexed once and searched on every message.

**Knowledge Bases:**

- **Two document types** — Paste text directly, or upload files (PDF, DOCX, TXT, Markdown)
- **Automatic indexing** — Content is chunked and embedded into a FAISS vector store on upload
- **Per-agent attachment** — Assign one or more knowledge bases to an agent from the agent dialog
- **Shared KBs** — Admins can create shared knowledge bases visible to all users
- **Chat indicators** — A pill badge in the chat bubble shows which KB was used for each response

**Session-Level File Attachments:**

- **Supported formats** — PNG, JPG, GIF, WebP, PDF, Word (.docx), Markdown, plain text
- **Automatic chunking** — Documents are split and indexed for vector search
- **Per-session indexes** — Each conversation gets its own isolated vector store
- **Cross-platform** — FAISS on Windows, Leann HNSW on Linux/macOS

---

### Long-Term Agent Memory

Agents remember what matters across conversations. At the start of each new session, a background LLM reflection call distills the previous session into a compact set of durable facts — preferences, project context, decisions, and corrections — which are automatically injected into every future system prompt.

- **Model-driven extraction** — The agent's own LLM decides what to remember; no keyword rules or manual tagging required
- **Four memory categories** — `preference` (how the user likes things), `context` (project/background info), `decision` (agreed-upon choices), `correction` (feedback on agent behaviour)
- **Zero-latency trigger** — Reflection runs as a background task on the first message of a new session; the user's response is never delayed
- **Bounded storage** — Maximum 50 memories per agent/user pair; oldest low-confidence facts are evicted automatically when the cap is reached
- **Key-based deduplication** — If a new fact contradicts an existing memory, it replaces the old one rather than accumulating stale data
- **Transparent & editable** — Open any agent in edit mode to see all stored memories with category colour-coding; delete individual facts or clear everything with one click
- **Persistent across restarts** — Memories are stored in the database (`agent_memories` table / MongoDB collection)

---

### Automatic Context Management

When a conversation approaches a model's context limit, the platform automatically compresses older history so sessions can continue indefinitely without hitting token limits or requiring manual intervention.

- **Threshold-based trigger** — Compaction activates at 80% of the model's context window
- **Recent messages preserved** — The last 10 messages are always kept verbatim for continuity
- **LLM-driven summarization** — Older messages are summarized by the same LLM into a single compact summary message that replaces them
- **Transparent notification** — A `context_compacted` event is streamed to the frontend when compaction occurs
- **Audit trail** — Each compaction is recorded in the database with metadata about what was compressed
- **Model-aware limits** — Context limits are tracked per model family (Claude 200k, GPT-4 128k, etc.) with a safe fallback for unknown models

---

### Session History & Execution Traces

Browse, search, and manage past conversations. Sessions are organized by agent or team and can be filtered by type.

**Session History:**

- **Search** — Find conversations by content
- **Filter by type** — View agent, team, or workflow sessions
- **Resume conversations** — Click a session to continue where you left off
- **Delete sessions** — Remove conversations you no longer need

**Execution Traces:**

Every agent session and scheduled workflow run records a full execution trace — a sequence of spans capturing each LLM call and tool/MCP call with timing, token usage, and input/output previews.

- **Span types** — LLM calls (Brain icon), tool calls (Wrench), MCP calls (Server), workflow steps (GitBranch)
- **Round grouping** — Spans are grouped by tool-loop iteration ("Initial", "Round 1", "Round 2" ...)
- **Collapsible details** — Each span reveals input/output JSON previews (truncated at 500 chars)
- **Performance indicators** — Duration badge turns amber for spans taking > 5s; error indicator on failed spans
- **Token summary** — Total duration, total tokens, and span count shown in the trace header
- **Access** — Hover any session row in `/sessions` and click the Activity icon

---

### Scheduled Workflows

Run workflows automatically on a server-side cron schedule — no browser required. Scheduled runs are identical to manual runs: a `WorkflowRun` record is created, each step executes sequentially, and results appear in the workflow's run history.

- **Cron expressions** — Standard 5-field cron syntax (`minute hour day month weekday`) with a helper link to [crontab.guru](https://crontab.guru)
- **Fixed input text** — Optionally supply the input text that feeds into the first workflow step at schedule creation time
- **Active / paused toggle** — Pause and resume schedules without deleting them
- **Missed-run skipping** — If the server is down during a scheduled run, the missed run is skipped rather than queued
- **Restart persistence** — Active schedules are automatically re-registered when the server starts up
- **Per-user ownership** — Each user manages their own schedules; they are not visible to other users
- **Run history** — Each scheduled execution appears alongside manual runs in the workflow history dialog

---

### Secrets Vault

Store API keys, tokens, and sensitive credentials in an encrypted vault. Secrets are encrypted at rest and can be referenced when configuring providers — no need to paste raw API keys.

- **Fernet encryption at rest** — All secret values are encrypted before storage
- **AES encryption in transit** — Secrets are transmitted via encrypted payloads
- **Reference in providers** — Use stored secrets when adding LLM providers instead of entering keys directly
- **CRUD management** — Create, view, update, and delete secrets from the settings page

---

### Security & Authentication

Enterprise-grade security features built in from day one.

| Feature | Implementation |
|---------|---------------|
| **JWT Authentication** | HS256 signed tokens with configurable expiry |
| **Two-Factor Auth (2FA)** | TOTP-based with QR code enrollment (Google Authenticator, Authy) |
| **End-to-End Encryption** | AES-encrypted request payloads (CryptoJS client, PyCryptodome server) |
| **Secrets at Rest** | Fernet-encrypted storage for API keys and credentials |
| **Password Hashing** | Bcrypt with salt for all user passwords |
| **Rate Limiting** | Per-endpoint limits via SlowAPI (configurable per user and API client) |
| **API Client Credentials** | Generate client ID/secret pairs for programmatic access |

---

### Admin Panel & RBAC

Manage users, assign roles, and control permissions with a granular role-based access control system.

- **Admin & Guest roles** — Two built-in roles with configurable permissions
- **Six permission flags** — Create Agents, Create Teams, Create Workflows, Create Tools, Manage Providers, Manage MCP Servers
- **User management** — Create, edit, and delete user accounts
- **Statistics dashboard** — View total users, admin count, and guest count

---

### Agent Import / Export

Share agent configurations as portable JSON files across any Obsidian AI instance. The export resolves all internal IDs to human-readable names so the file is fully self-contained and shareable. On import, names are matched back to the importing user's resources; any that don't exist are skipped and reported as warnings.

**Export file format:**

```json
{
  "aios_export_version": "1",
  "exported_at": "2026-01-01T00:00:00Z",
  "agent": {
    "name": "Research Assistant",
    "description": "Searches the web for information",
    "system_prompt": "You are a research assistant...",
    "provider_model_id": "gpt-4o",
    "tools": ["web_search", "calculator"],
    "mcp_servers": ["brave-search"],
    "knowledge_bases": ["Company Docs"],
    "hitl_confirmation_tools": ["delete_file"],
    "config": { "temperature": 0.7, "max_tokens": 2000 }
  }
}
```

---

### Dual Database Support

Run with zero-config SQLite out of the box, or switch to MongoDB for production deployments. Every endpoint supports both databases with automatic branching.

| Database | Config | Use Case |
|----------|--------|----------|
| **SQLite** | Default — no setup required | Development, single-user, small teams |
| **MongoDB** | Set `DATABASE_TYPE=mongo` | Production, multi-user, horizontal scaling |

---

## Architecture

```
┌──────────────────────────────┐       ┌──────────────────────────────┐
│         Frontend             │       │          Backend             │
│    Next.js 16 + React 19     │──────>│     FastAPI + SQLAlchemy     │
│    Port 3000                 │ /api  │     Port 8000                │
│                              │proxy  │                              │
│  ┌────────┐ ┌─────────────┐ │       │  ┌──────────┐ ┌───────────┐ │
│  │NextAuth│ │ Zustand      │ │       │  │ JWT Auth │ │ LLM       │ │
│  │  v5    │ │ State Mgmt   │ │       │  │ + 2FA    │ │ Providers │ │
│  └────────┘ └─────────────┘ │       │  └──────────┘ └───────────┘ │
│  ┌────────┐ ┌─────────────┐ │       │  ┌──────────┐ ┌───────────┐ │
│  │Radix UI│ │ CryptoJS    │ │       │  │ MCP      │ │ RAG       │ │
│  │/shadcn │ │ Encryption  │ │       │  │ Client   │ │ Service   │ │
│  └────────┘ └─────────────┘ │       │  └──────────┘ └───────────┘ │
└──────────────────────────────┘       └──────────┬───────────────────┘
                                                  │
                                       ┌──────────▼───────────────────┐
                                       │   SQLite (default) / MongoDB │
                                       └──────────────────────────────┘
```

**How it works:**

1. The Next.js frontend proxies all `/api/*` requests to the FastAPI backend via `next.config.ts` rewrites
2. Authentication flows through NextAuth v5 on the frontend and JWT verification on the backend
3. All auth-sensitive payloads are AES-encrypted end-to-end (CryptoJS client-side, PyCryptodome server-side)
4. Chat responses stream via Server-Sent Events (SSE) for real-time token delivery
5. LLM providers are abstracted behind a factory pattern — agents reference a provider, not a specific SDK

---

## Quick Start

### Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| [Python](https://www.python.org/) | 3.12+ | Backend runtime |
| [Node.js](https://nodejs.org/) | 18+ | Frontend runtime |
| [uv](https://docs.astral.sh/uv/) | Latest | Python package manager |
| [npm](https://www.npmjs.com/) | 9+ | Node package manager |

### Backend Setup

```bash
# Navigate to the backend directory
cd backend

# Install Python dependencies
uv sync

# Configure environment variables (see Environment Variables section)
# Edit .env with your keys

# Start the FastAPI development server
uv run uvicorn main:app --reload
```

The backend API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### Frontend Setup

```bash
# Navigate to the frontend directory
cd frontend

# Install Node.js dependencies
npm install

# Configure environment variables
# Edit .env.local with your keys

# Start the Next.js development server
npm run dev
```

The frontend will be available at `http://localhost:3000`.

### Running Both Together

```bash
# From the project root directory
npm run dev
```

This starts both the frontend and backend concurrently.

### Environment Variables

#### Backend (`backend/.env`)

> **Important:** You must generate real secret keys before starting the backend. Placeholder values will cause startup errors.

```bash
# Generate ENCRYPTION_KEY and JWT_SECRET_KEY (any random string works):
openssl rand -hex 32

# Generate PROVIDER_KEY_SECRET (must be a valid Fernet key — 32 url-safe base64-encoded bytes):
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```env
# Encryption key for AES payload encryption (must match frontend NEXT_PUBLIC_ENCRYPTION_KEY)
ENCRYPTION_KEY=<output of: openssl rand -hex 32>

# JWT authentication
JWT_SECRET_KEY=<output of: openssl rand -hex 32>
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30

# Fernet key for encrypting provider API keys at rest (MUST be a valid Fernet key)
PROVIDER_KEY_SECRET=<output of: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">

# Rate limiting (requests per minute)
RATE_LIMIT_USER=60
RATE_LIMIT_API_CLIENT=100

# Database type: "sqlite" (default) or "mongo"
DATABASE_TYPE=sqlite
```

#### Frontend (`frontend/.env.local`)

```env
# NextAuth.js signing secret
AUTH_SECRET=your-auth-secret

# Application URL
AUTH_URL=http://localhost:3000

# Public encryption key (must match backend ENCRYPTION_KEY)
NEXT_PUBLIC_ENCRYPTION_KEY=your-encryption-key
```

---

## Usage Guide

### 1. Add an LLM Provider

Navigate to the **Chat** page sidebar and click **+** next to Endpoints. Select a provider type (OpenAI, Anthropic, Google, Ollama, etc.), enter your API key or reference one from the secrets vault, and specify the model ID.

### 2. Create an Agent

Click **+** next to Agents in the sidebar. Configure the agent with a name, system prompt, and model/provider selection. Optionally attach tools, MCP servers, and knowledge bases.

### 3. Start Chatting

Select your agent from the sidebar and start a conversation. Responses stream in real-time. Attach files, view tool executions, and explore chain-of-thought reasoning.

### 4. Build a Team

Switch to the **Teams** tab, click **+**, and combine multiple agents. Choose a coordination mode (Coordinate, Route, or Collaborate) and start a team chat.

### 5. Create a Workflow

From the **Dashboard**, click **Create Workflow**. Add sequential steps, each assigned to a specific agent with custom instructions. Run the workflow and watch each step execute in real-time.

### 6. Configure MCP Servers

In the sidebar, click **+** next to MCP Servers. Set up servers using stdio (local Docker/npx/python) or SSE (remote HTTP) transport. Test the connection to discover available tools, then bind servers to agents.

### 7. Manage Secrets

Go to **Settings > Secrets** to store API keys and tokens in the encrypted vault. Reference stored secrets when adding LLM providers.

### 8. Enable Two-Factor Authentication

In **Settings**, enable 2FA by scanning the QR code with an authenticator app (Google Authenticator, Authy, etc.). Enter the 6-digit code to verify setup.

### 9. Manage Users (Admin)

Navigate to the **Admin** panel to create users, assign roles (Admin/Guest), and configure granular resource permissions.

---

## API Reference

The backend exposes a RESTful API with interactive documentation:

- **Swagger UI** — `http://localhost:8000/docs`
- **ReDoc** — `http://localhost:8000/redoc`

### Key Endpoints

| Category | Endpoint | Method | Description |
|----------|----------|--------|-------------|
| **Auth** | `/auth/register` | POST | Create a new user account |
| **Auth** | `/auth/login` | POST | Authenticate and receive JWT token |
| **Agents** | `/agents` | GET | List all agents |
| **Agents** | `/agents` | POST | Create a new agent |
| **Agents** | `/agents/{id}` | PUT | Update an agent |
| **Agents** | `/agents/{id}` | DELETE | Delete an agent |
| **Agents** | `/agents/{id}/export` | GET | Export agent as JSON |
| **Agents** | `/agents/import` | POST | Import agent from JSON |
| **Teams** | `/teams` | GET | List all teams |
| **Teams** | `/teams` | POST | Create a new team |
| **Workflows** | `/workflows` | GET | List all workflows |
| **Workflows** | `/workflows` | POST | Create a new workflow |
| **Workflows** | `/workflows/{id}/run` | POST | Execute a workflow (SSE) |
| **Workflows** | `/workflows/{id}/runs` | GET | List workflow run history |
| **Schedules** | `/workflows/{id}/schedules` | GET | List schedules for a workflow |
| **Schedules** | `/workflows/{id}/schedules` | POST | Create a cron schedule |
| **Schedules** | `/schedules/{id}` | PUT | Update a schedule |
| **Schedules** | `/schedules/{id}` | DELETE | Delete a schedule |
| **Chat** | `/chat` | POST | Stream a chat response (SSE) |
| **Sessions** | `/sessions` | GET | List conversation sessions |
| **Sessions** | `/sessions/{id}/messages` | GET | Get session messages |
| **Traces** | `/traces/sessions/{id}` | GET | Get full execution trace for a session |
| **Traces** | `/traces/workflow-runs/{id}` | GET | Get execution trace for a workflow run |
| **Providers** | `/providers` | GET | List configured LLM providers |
| **Providers** | `/providers/{id}/test` | POST | Test provider connection |
| **Providers** | `/providers/{id}/models` | GET | List available models |
| **Tools** | `/tools` | GET | List available tool definitions |
| **Tools** | `/tools` | POST | Create a tool definition |
| **MCP** | `/mcp-servers` | GET | List MCP server configurations |
| **MCP** | `/mcp-servers/{id}/test` | POST | Test MCP server connection |
| **Knowledge** | `/knowledge` | GET | List knowledge bases |
| **Knowledge** | `/knowledge/{id}/documents` | POST | Add a document to a knowledge base |
| **Memory** | `/memory/agents/{id}` | GET | List agent memories |
| **Memory** | `/memory/agents/{id}` | DELETE | Clear all agent memories |
| **Secrets** | `/secrets` | GET | List user secrets (encrypted) |
| **Secrets** | `/secrets` | POST | Create a new secret |
| **Files** | `/files/upload` | POST | Upload a file attachment |
| **Dashboard** | `/dashboard/stats` | GET | Get dashboard statistics |
| **Admin** | `/admin/users` | GET | List all users (admin only) |
| **Admin** | `/admin/users` | POST | Create a user (admin only) |
| **Admin** | `/admin/users/{id}` | PUT | Update user role/permissions |
| **User** | `/user/2fa/setup` | POST | Set up TOTP two-factor auth |
| **User** | `/user/2fa/verify` | POST | Verify 2FA setup |
| **User** | `/user/api-clients` | POST | Generate API client credentials |
| **Health** | `/health` | GET | Health check |

### Programmatic Access

Generate API client credentials from **Settings** to access the API programmatically:

```bash
curl -H "X-API-Key: your-client-id" \
     -H "X-API-Secret: your-client-secret" \
     http://localhost:8000/agents
```

---

## Tech Stack

### Frontend

| Technology | Purpose |
|------------|---------|
| [Next.js 16](https://nextjs.org/) | React framework with App Router |
| [React 19](https://react.dev/) | UI component library |
| [NextAuth v5](https://authjs.dev/) | Authentication & session management |
| [Tailwind CSS 4](https://tailwindcss.com/) | Utility-first styling |
| [Radix UI](https://www.radix-ui.com/) / [shadcn/ui](https://ui.shadcn.com/) | Accessible component primitives |
| [Zustand](https://zustand.docs.pmnd.rs/) | Lightweight state management |
| [CryptoJS](https://github.com/brix/crypto-js) | Client-side AES encryption |
| [Lucide React](https://lucide.dev/) | Icon library |
| [Motion](https://motion.dev/) | Animation library |
| [Shiki](https://shiki.style/) | Syntax highlighting |
| [Sonner](https://sonner.emilkowal.dev/) | Toast notifications |

### Backend

| Technology | Purpose |
|------------|---------|
| [FastAPI](https://fastapi.tiangolo.com/) | Async Python web framework |
| [SQLAlchemy](https://www.sqlalchemy.org/) | SQL ORM (SQLite) |
| [Motor](https://motor.readthedocs.io/) | Async MongoDB driver |
| [Pydantic](https://docs.pydantic.dev/) | Data validation & serialization |
| [python-jose](https://github.com/mpdavis/python-jose) | JWT token handling |
| [bcrypt](https://github.com/pyca/bcrypt) | Password hashing |
| [PyCryptodome](https://www.pycryptodome.org/) | AES encryption |
| [PyOTP](https://github.com/pyauth/pyotp) | TOTP two-factor authentication |
| [SSE-Starlette](https://github.com/sysid/sse-starlette) | Server-Sent Events streaming |
| [MCP SDK](https://modelcontextprotocol.io/) | Model Context Protocol client |
| [FAISS](https://github.com/facebookresearch/faiss) | Vector similarity search |
| [APScheduler](https://apscheduler.readthedocs.io/) | Cron-based background job scheduling |
| [croniter](https://github.com/kiorky/croniter) | Cron expression validation |
| [SlowAPI](https://github.com/laurentS/slowapi) | Rate limiting |
| [uv](https://docs.astral.sh/uv/) | Fast Python package manager |

---

## Project Structure

```
obsidian-ai/
├── package.json                    # Root — runs frontend + backend concurrently
│
├── backend/                        # FastAPI Python backend
│   ├── main.py                     # App entrypoint, middleware, lifespan
│   ├── pyproject.toml              # Python dependencies (uv)
│   ├── .env                        # Backend environment config
│   │
│   ├── auth.py                     # JWT token generation & verification
│   ├── config.py                   # Database type configuration
│   ├── crypto_utils.py             # AES payload encryption/decryption
│   ├── encryption.py               # Fernet encryption for secrets at rest
│   ├── database.py                 # SQLAlchemy engine & session (SQLite)
│   ├── database_mongo.py           # Motor async MongoDB driver setup
│   ├── models.py                   # SQLAlchemy ORM models
│   ├── schemas.py                  # Pydantic request/response schemas
│   ├── rate_limiter.py             # Rate limiting middleware
│   ├── mcp_client.py               # MCP server connection & tool bridging
│   ├── rag_service.py              # Vector search & RAG pipeline
│   ├── file_storage.py             # File upload/download handling
│   ├── scheduler.py                # Global APScheduler instance + cron helpers
│   ├── scheduler_executor.py       # Background workflow execution functions
│   │
│   ├── llm/                        # LLM provider integrations
│   │   ├── base.py                 # Base provider interface
│   │   ├── provider_factory.py     # Factory pattern for provider selection
│   │   ├── anthropic_provider.py   # Anthropic (Claude) provider
│   │   ├── openai_provider.py      # OpenAI / OpenRouter provider
│   │   ├── google_provider.py      # Google Gemini provider
│   │   └── ollama_provider.py      # Local Ollama provider
│   │
│   └── routers/                    # API route handlers
│       ├── auth_router.py          # Login, register, 2FA/TOTP
│       ├── agents_router.py        # Agent CRUD + import/export
│       ├── teams_router.py         # Team coordination
│       ├── workflows_router.py     # Workflow definitions
│       ├── workflow_runs_router.py  # Workflow execution & tracking
│       ├── chat_router.py          # Real-time streaming chat
│       ├── sessions_router.py      # Conversation sessions
│       ├── providers_router.py     # LLM provider configuration
│       ├── tools_router.py         # Tool definitions
│       ├── mcp_servers_router.py   # MCP server configuration
│       ├── secrets_router.py       # Encrypted user secrets
│       ├── files_router.py         # File attachments
│       ├── knowledge_router.py     # Knowledge base CRUD + document indexing
│       ├── memory_router.py        # Agent long-term memory
│       ├── schedule_router.py      # Workflow schedule CRUD + APScheduler sync
│       ├── traces_router.py        # Execution trace read endpoints
│       ├── dashboard_router.py     # Dashboard statistics
│       └── admin_router.py         # System administration
│
└── frontend/                       # Next.js 16 React frontend
    ├── package.json                # Frontend dependencies
    ├── next.config.ts              # Next.js config (API rewrites)
    ├── auth.ts                     # NextAuth.js v5 configuration
    ├── .env.local                  # Frontend environment config
    │
    ├── app/                        # Next.js app directory
    │   ├── layout.tsx              # Root layout (toasts, providers)
    │   ├── page.tsx                # Landing page
    │   ├── login/page.tsx          # Login page with 2FA support
    │   ├── register/page.tsx       # User registration
    │   │
    │   └── (authenticated)/        # Protected routes
    │       ├── layout.tsx          # Sidebar & navigation
    │       ├── home/page.tsx       # Dashboard
    │       ├── playground/page.tsx # Chat interface
    │       ├── sessions/page.tsx   # Conversation history
    │       ├── settings/page.tsx   # User settings, 2FA, secrets
    │       ├── knowledge/page.tsx  # Knowledge base list
    │       ├── knowledge/[id]/page.tsx  # KB detail — add text/file documents
    │       └── admin/page.tsx      # Admin panel
    │
    ├── components/                 # React components
    │   ├── playground/             # Chat, sidebar, agent & team dialogs
    │   ├── dialogs/                # Modal dialogs (tools, workflows, MCP, admin)
    │   ├── ai-elements/            # Chat & streaming display components
    │   └── ui/                     # shadcn / Radix UI primitives
    │
    ├── lib/                        # Utility libraries
    │   ├── api-client.ts           # HTTP client with auth headers
    │   ├── crypto.ts               # Client-side AES encryption
    │   ├── stream.ts               # SSE streaming response handler
    │   └── utils.ts                # General utilities
    │
    ├── stores/                     # Zustand state management
    │   ├── playground-store.ts     # Agents, teams, workflows, artifacts state
    │   ├── dashboard-store.ts      # Dashboard state
    │   ├── permissions-store.ts    # User permissions state
    │   └── admin-store.ts          # Admin panel state
    │
    └── types/                      # TypeScript type definitions
        ├── playground.ts           # Agent, Team, Workflow, Artifact types
        └── api.ts                  # API response types
```

---

## Updates

Recent additions shipped to the platform.

---

### Provider Import / Export

Export and import LLM endpoint configurations as portable JSON files, making it easy to replicate your provider setup across instances or share it with teammates.

**How it works:**

- **Single export** — Download any individual provider as a JSON file from its row in the Endpoints panel (Download icon per row)
- **Bulk export** — Download all providers in a single JSON file via the header-level DownloadCloud button
- **Import** — Upload a previously exported JSON file using the Upload button; the importer auto-detects whether it's a single provider or a bulk envelope and calls the correct endpoint
- **API key handling** — API keys are **always excluded** from exports for security reasons; after import, each provider's key field is blank and must be re-entered by the user
- **Name deduplication** — On import, if a provider with the same name already exists it is updated in place; otherwise a new provider is created
- **Permission-gated** — Import is only available to users with the `manage_providers` permission

**Export file formats:**

Single provider:
```json
{
  "aios_export_version": "1",
  "exported_at": "2026-01-01T00:00:00Z",
  "provider": {
    "name": "My OpenAI",
    "provider_type": "openai",
    "model_id": "gpt-4o",
    "base_url": null,
    "config": {}
  }
}
```

Bulk (all providers):
```json
{
  "aios_export_version": "1",
  "exported_at": "2026-01-01T00:00:00Z",
  "providers": [
    { "name": "My OpenAI", "provider_type": "openai", "model_id": "gpt-4o", ... },
    { "name": "Local Ollama", "provider_type": "ollama", "model_id": "llama3.2", ... }
  ]
}
```

**New API endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/providers/export` | GET | Bulk export all providers |
| `/providers/{id}/export` | GET | Export a single provider |
| `/providers/import` | POST | Import a single or bulk provider JSON |

---

## Roadmap

> Planned features, not in any particular order of priority.

### Agent Orchestration

- [ ] **Multi-agent pipelines** — Chain agents together where the output of one becomes the input of another, with a visual DAG editor
- [ ] **Agent-as-tool** — Allow agents to call other agents as tools (hierarchical delegation)
- [ ] **Agent Supervision Trees** — Supervisor agents watch over worker agents in real-time; if a worker's output falls outside defined quality bounds, the supervisor automatically intervenes, corrects, retries, or escalates to HITL
- [ ] **Meta-Agent** — Describe a workflow or agent in plain English and have the platform auto-generate the full configuration: system prompt, tools, MCP servers, and workflow steps

### Intelligence & Learning

- [ ] **Prompt Auto-Optimizer** — Analyze an agent's execution trace history to automatically surface and apply improvements to its system prompt; reduces errors, verbosity, and failed tool calls without manual iteration
- [ ] **Memory Graph** — Upgrade agent memory from flat key-value facts to a typed relational graph; memories have explicit relationships (e.g. *"User works at [Company]"*, *"[Company] uses [Tool]"*) that agents can traverse for richer, multi-hop context

### Observability & Debugging

- [ ] **Cost tracking dashboard** — Token usage and estimated cost per agent, session, user, and time period
- [ ] **Prompt diffing** — Side-by-side comparison of how system prompt changes affect outputs

### Deployment & Scheduling

- [ ] **Webhook triggers** — Fire agent runs from external events (GitHub push, form submission, etc.)
- [ ] **Async job queue** — Long-running agent tasks run in the background with status polling

### Evaluation & Testing

- [ ] **Replay & Simulation Mode** — Re-run any past session through a different agent configuration side-by-side to see exactly how responses would have changed; makes prompt iteration grounded in real historical conversations
- [ ] **Eval harness** — Define test cases with expected outputs and get pass/fail scores
- [ ] **Regression testing** — Detect when a prompt or model change degrades quality on a golden dataset

### Security & Governance

- [ ] **Adversarial / Red Team Mode** — A dedicated red-team agent automatically probes your agents for prompt injection, jailbreaks, persona drift, and instruction-following failures, then generates a security report with specific vulnerabilities found
- [ ] **Audit logs** — Immutable record of all agent actions, tool calls, and data accessed

### Developer Experience

- [x] **Provider Import / Export** — Export endpoint configurations (name, type, model ID, base URL, config) as portable JSON and import them on any instance; API keys are intentionally excluded and must be re-entered on import
- [ ] **Agent versioning** — Snapshot agent configs and roll back to previous versions

### UX & Productivity

- [ ] **Agent templates** — Curated starter configs for common use cases (customer support, code review, research)
- [ ] **Collaborative sessions** — Multiple users in the same agent chat simultaneously

### Messaging Channels

- [ ] **Telegram** — Connect any agent to a Telegram bot (via `@BotFather` token); the agent responds to direct messages and group mentions, with full tool execution, RAG, HITL approval, and session history working natively
- [ ] **WhatsApp** — Connect any agent to a WhatsApp account via QR code scan; the agent handles direct messages and group chats using the WhatsApp Web multi-device protocol — no Meta Business account required
- [ ] **Channel session continuity** — Each external chat (Telegram chat ID, WhatsApp contact) maps to a persistent Obsidian AI session; the agent remembers previous conversations and applies long-term memory across channel interactions
- [ ] **Channel HITL** — When a channel-connected agent triggers a HITL-flagged tool, execution pauses; the approval card surfaces in the Obsidian AI web UI and the channel user receives a "waiting for approval" message until resolved
- [ ] **Additional channels** — Discord, Slack, Signal, and Matrix following the same channel plugin architecture once Telegram and WhatsApp are stable

---

## Contributing

Contributions are welcome! Whether it's bug reports, feature requests, or code contributions — all input is valued.

### How to Contribute

1. **Fork the repository**

   Click the [Fork](https://github.com/sup3rus3r/obsidian-ai/fork) button at the top right of this page.

2. **Clone your fork**

   ```bash
   git clone https://github.com/your-username/obsidian-ai.git
   cd obsidian-ai
   ```

3. **Create a feature branch**

   ```bash
   git checkout -b feature/your-feature-name
   ```

4. **Make your changes and commit**

   ```bash
   git commit -m "Add your feature description"
   ```

5. **Push and open a Pull Request**

   ```bash
   git push origin feature/your-feature-name
   ```

   Open a pull request against the `main` branch with a clear description of your changes.

### Reporting Issues

Found a bug or have a feature request? [Open an issue](https://github.com/sup3rus3r/obsidian-ai/issues) with as much detail as possible.

---

## License

This project is licensed under the **PolyForm Noncommercial License 1.0.0**.

- **Personal use** — Free to use for personal projects, research, experimentation, hobby projects, and non-commercial purposes.
- **Commercial use** — Not permitted. You may not sell this software, offer it as a paid service, or use it in a commercial product without explicit written permission from the author.

See the [LICENSE](LICENSE) file for the full terms.
