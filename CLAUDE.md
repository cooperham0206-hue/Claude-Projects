# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) and AI assistants working within this repository.

---

## Repository Overview

**Repository:** cooperham0206-hue/Claude-Projects
**Purpose:** A projects repository managed via Claude Code on the web, intended for AI-assisted software development workflows.

This repository is the working environment for Claude Code sessions. All development, experiments, and AI-assisted code live here.

---

## Repository Structure

The repository is currently in its initial state. As projects are added, the structure is expected to evolve. Follow these conventions when organizing new work:

```
Claude-Projects/
├── CLAUDE.md              # This file — AI assistant guidance
├── <project-name>/        # Individual project directories
│   ├── README.md          # Project-specific documentation
│   └── ...                # Project source files
└── ...
```

When adding new projects:
- Place each project in its own top-level directory named in `kebab-case`
- Include a `README.md` inside each project directory
- Keep project code self-contained within its directory

---

## Git Workflow

### Branch Naming Convention

All Claude Code feature branches follow this pattern:

```
claude/<short-description>-<session-id>
```

Example: `claude/add-claude-documentation-hefCN`

**Rules:**
- Branches MUST start with `claude/`
- Branches MUST end with the matching session ID suffix
- Never push to `main` or other protected branches directly
- Always develop on the designated feature branch for the current session

### Commit Practices

- Write clear, descriptive commit messages in the imperative mood (e.g., "Add authentication module", not "Added auth")
- Commit logical units of work — avoid bundling unrelated changes
- Each commit should leave the codebase in a working state

### Push Protocol

Always use:
```bash
git push -u origin <branch-name>
```

If push fails due to network errors, retry with exponential backoff: 2s, 4s, 8s, 16s (max 4 retries).

Do NOT retry on 403 errors — these indicate a branch naming issue (branch must start with `claude/` and end with the correct session ID).

---

## Development Workflows

### Starting a New Session

1. Verify the current branch matches the session's designated branch
2. Review `CLAUDE.md` for any updated conventions
3. Check `git status` and `git log --oneline -10` to understand the current state
4. Identify the task scope before making changes

### Making Changes

1. Read relevant files before modifying them — never edit code you haven't reviewed
2. Prefer editing existing files over creating new ones
3. Keep changes focused and minimal — avoid scope creep
4. Test changes before committing when a test suite exists

### Before Committing

- Ensure all modified files are intentional
- Do not commit secrets, credentials, or `.env` files
- Stage specific files rather than using `git add .` or `git add -A`
- Verify the commit message accurately describes the change

---

## AI Assistant Conventions

### General Principles

- **Read before writing:** Always read a file before editing it
- **Minimal changes:** Only make changes that are directly required by the task
- **No over-engineering:** Avoid adding abstractions, error handling, or features beyond what is asked
- **No unnecessary files:** Do not create documentation, README files, or helper scripts unless explicitly requested
- **No comments on unchanged code:** Only add comments where logic is genuinely non-obvious and in code you wrote or modified

### Code Style

Until project-specific style guides are established:
- Follow the conventions already present in existing files
- Use consistent indentation (match surrounding code)
- Prefer clarity over cleverness

### Security

- Never introduce: SQL injection, XSS, command injection, or other OWASP Top 10 vulnerabilities
- Validate input only at system boundaries (user input, external APIs)
- Do not store secrets in code or commit sensitive data

### Task Management

- Use the TodoWrite tool to plan multi-step tasks and track progress
- Mark todos as completed immediately upon finishing each step
- Only one task should be `in_progress` at a time

---

## Working with Claude Code on the Web

### Session Context

Each Claude Code session operates on a dedicated feature branch. The session ID is embedded in the branch name and must match for pushes to succeed.

### Hooks

If a `SessionStart` hook is configured, it runs automatically at the start of each session to set up the environment (e.g., install dependencies, run linters). Check `.claude/settings.json` for hook configuration if it exists.

### MCP Servers and Tools

If Model Context Protocol (MCP) servers are configured for this repository, their capabilities will be available as additional tools within the session. Check `.claude/` for any MCP configuration.

---

## Key Reminders for AI Assistants

1. **Branch safety:** Only push to the branch named `claude/<desc>-<session-id>`. A 403 on push means wrong branch name.
2. **Empty repo:** If no source files exist, the repo is in initial state — do not assume files are present without checking.
3. **No assumptions:** Run `git status`, `ls`, or read files to verify state before acting on assumptions.
4. **Commit signing:** This repository uses SSH-based commit signing. Do not skip signing (`--no-gpg-sign` is disallowed).
5. **Fetch before branching:** When starting work, fetch from origin to avoid stale branch state.
