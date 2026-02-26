# Contributing to Obsidian AI

Thank you for your interest in contributing to Obsidian AI! Whether you're fixing a bug, proposing a new feature, improving documentation, or triaging issues — every contribution is valued and appreciated.

Please take a moment to read these guidelines before getting started.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Ways to Contribute](#ways-to-contribute)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Features](#suggesting-features)
- [Development Setup](#development-setup)
- [Branch & Commit Conventions](#branch--commit-conventions)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Code Style & Standards](#code-style--standards)
- [Security Vulnerabilities](#security-vulnerabilities)
- [License](#license)

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). By participating, you agree to uphold a welcoming and respectful environment for everyone. Please report unacceptable behavior to the project maintainer.

---

## Ways to Contribute

- **Bug reports** — Found something broken? Open an issue.
- **Feature requests** — Have an idea? Share it with the community.
- **Code contributions** — Fix bugs, implement features, improve performance.
- **Documentation** — Improve the README, add inline comments, write guides.
- **Testing** — Write tests, reproduce reported bugs, validate fixes.
- **Triage** — Help label and prioritize open issues.

---

## Reporting Bugs

Before opening a new issue, please [search existing issues](https://github.com/sup3rus3r/obsidian-ai/issues) to avoid duplicates.

When filing a bug report, include:

- **A clear and descriptive title**
- **Steps to reproduce** the problem
- **Expected behavior** vs. **actual behavior**
- **Environment details**: OS, Python version, Node.js version, browser (if frontend)
- **Relevant logs or error messages** (redact any secrets)
- **Screenshots or recordings** if applicable

> **Do not include API keys, passwords, or other sensitive information in issues.**

---

## Suggesting Features

Feature requests are welcome. To suggest a new feature:

1. [Search existing issues](https://github.com/sup3rus3r/obsidian-ai/issues) to see if it has already been proposed.
2. Open a new issue with the label `enhancement`.
3. Describe the problem your feature solves and your proposed solution.
4. Provide any relevant examples, mockups, or references.

For large or breaking changes, please open an issue to discuss before submitting a PR — this avoids wasted effort if the direction doesn't align with the project roadmap.

---

## Development Setup

### Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.12+ |
| Node.js | 18+ |
| npm | 9+ |
| [uv](https://docs.astral.sh/uv/) | latest |
| MongoDB | 6+ (optional, for Mongo backend) |

### 1. Fork and Clone

```bash
# Fork the repository via the GitHub UI, then:
git clone https://github.com/your-username/obsidian-ai.git
cd obsidian-ai
```

### 2. Backend Setup

```bash
cd backend
uv sync
cp .env.example .env   # fill in your environment variables
uv run uvicorn main:app --reload
```

### 3. Frontend Setup

```bash
cd frontend
npm install
cp .env.local.example .env.local   # fill in your environment variables
npm run dev
```

### 4. Run Both Together (from project root)

```bash
npm install
npm run dev
```

The API will be available at `http://localhost:8000` and the frontend at `http://localhost:3000`.

---

## Branch & Commit Conventions

### Branch Naming

Use descriptive branch names with the following prefixes:

| Prefix | Purpose |
|--------|---------|
| `feature/` | New features or enhancements |
| `fix/` | Bug fixes |
| `docs/` | Documentation-only changes |
| `refactor/` | Code refactoring without behavior change |
| `test/` | Adding or updating tests |
| `chore/` | Maintenance, dependency updates, tooling |

Examples:
```
feature/mcp-tool-editor
fix/agent-memory-leak
docs/rag-setup-guide
```

### Commit Messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

Examples:
```
feat(agents): add support for streaming tool call responses
fix(auth): resolve JWT expiry refresh race condition
docs(readme): update backend setup instructions
```

Keep the subject line under 72 characters. Use the body to explain *why*, not just *what*.

---

## Submitting a Pull Request

1. **Ensure your branch is up to date** with `main` before opening a PR:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. **Keep PRs focused** — one logical change per PR. Avoid bundling unrelated changes.

3. **Test your changes** locally before submitting.

4. **Open the PR against `main`** with:
   - A clear title following the commit convention above
   - A description explaining **what** changed and **why**
   - References to any related issues (e.g., `Closes #42`)
   - Screenshots or recordings for UI changes

5. **Be responsive** to review feedback. If a review requests changes, address them or explain your reasoning.

6. All checks must pass before a PR can be merged.

### PR Checklist

- [ ] Code follows the project's style guidelines
- [ ] No secrets, credentials, or personal data are included
- [ ] Backend changes include appropriate error handling
- [ ] Frontend changes have been tested in the browser
- [ ] Documentation has been updated where necessary
- [ ] Commit history is clean and follows conventions

---

## Code Style & Standards

### Python (Backend)

- **Formatter:** [Ruff](https://docs.astral.sh/ruff/) or Black — keep consistent with existing style
- **Type hints:** Use type annotations for all function signatures
- **Pydantic models:** Use for all request/response schemas
- **Async:** Prefer `async`/`await` patterns consistent with FastAPI conventions
- Do not commit unused imports or dead code

### TypeScript / JavaScript (Frontend)

- **Language:** TypeScript — avoid `any` types
- **Formatting:** Prettier — keep consistent with existing config
- **Components:** Functional React components with hooks
- **State management:** Follow existing Zustand store patterns
- **Styling:** Tailwind CSS utility classes — avoid inline styles

### General

- Write self-documenting code; add comments only where the logic is not immediately obvious
- Keep functions small and focused
- Do not introduce new dependencies without prior discussion in an issue

---

## Security Vulnerabilities

**Please do not report security vulnerabilities through public GitHub issues.**

If you discover a security vulnerability, disclose it responsibly by emailing the maintainer directly or using [GitHub's private vulnerability reporting](https://github.com/sup3rus3r/obsidian-ai/security/advisories/new).

Include:
- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested mitigations

You will receive a response as quickly as possible. Please allow time to patch the issue before any public disclosure.

---

## License

By contributing to Obsidian AI, you agree that your contributions will be licensed under the **PolyForm Noncommercial License 1.0.0** — the same license that governs the project.

See the [LICENSE](LICENSE) file for full terms.

---

*Thank you for helping make Obsidian AI better!*
