# VIKI Code

<p align="center">
  <img src="assets/logo/viki-code-banner.png" alt="VIKI Code banner" width="100%" />
</p>

<p align="center">
  <a href="https://github.com/rebootix-research/viki-code/releases/latest">
    <img alt="Release" src="https://img.shields.io/github/v/release/rebootix-research/viki-code?display_name=tag&style=for-the-badge&color=0f172a" />
  </a>
  <a href="https://github.com/rebootix-research/viki-code/stargazers">
    <img alt="GitHub stars" src="https://img.shields.io/github/stars/rebootix-research/viki-code?style=for-the-badge&color=f59e0b" />
  </a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-2563eb?style=for-the-badge" />
  <img alt="License" src="https://img.shields.io/badge/license-MIT-059669?style=for-the-badge" />
  <img alt="Live suite" src="https://img.shields.io/badge/live%20suite-9%2F9-success?style=for-the-badge" />
  <img alt="Public benchmark" src="https://img.shields.io/badge/public%20live%20benchmark-8%2F8-success?style=for-the-badge" />
</p>

VIKI Code is governed coding infrastructure for teams that want an AI system to operate inside real repositories, under approvals, with rollback paths, live validation, and evidence-backed execution.

It is built for serious engineering workflows: bug-fixes, refactors, migrations, repo intelligence, local API control, IDE handoff, and chat-driven approvals across the same governed execution core.

<p align="center">
  <a href="https://rebootix-research.com/viki-code"><strong>Product Page</strong></a>
  |
  <a href="https://github.com/rebootix-research/viki-code"><strong>GitHub</strong></a>
  |
  <a href="./PROOF_REPORT.md"><strong>Proof Report</strong></a>
  |
  <a href="./RELEASE_NOTES.md"><strong>Release Notes</strong></a>
</p>

<p align="center">
  If VIKI Code is relevant to your stack, star the repo to follow releases, proof updates, and benchmark progress.
</p>

## Why VIKI Code

- Real repo execution instead of chat-only suggestions.
- Approval-aware autonomy with diff preview, patch export, and rollback paths.
- Multi-agent execution designed for planning, implementation, validation, and review.
- Repo intelligence tuned for large codebases, monorepos, and targeted test selection.
- CLI, API, VS Code, Telegram, and WhatsApp surfaces over one execution model.

## What You Can Do In Five Minutes

- Install locally and boot the governed runtime on a real repository.
- Ask VIKI to inspect a repo, localize likely impact, and suggest the right tests.
- Run a real bug-fix or refactor task and review the resulting diff before accepting it.
- Use the same session model across CLI, API, IDE, and approval workflows.

## Proof At A Glance

| Signal | Current 4.1.4 evidence |
| --- | --- |
| Local regression suite | `69 passed` |
| Live validation suite | `9/9 passed` on fresh repos |
| Generic CLI live wins | `7/7 passed` |
| Public live benchmark slice | `8/8 passed` |
| Public offline benchmark slice | `8/8 passed` |
| Human-style install validation | passed |
| Isolation validation | passed through real WSL-isolated execution |

The project is public-release ready for its niche. It is not positioned here as fastest-in-class or benchmark leader overall, because the current proof still shows that live time-to-green is slower than the bundled baselines.

## What Makes It Different

### Governed execution first

VIKI is built around controlled autonomy. Tasks run with worktree isolation, explicit validation, approval-aware flow control, reversible diffs, and artifacted evidence rather than optimistic "trust me" completion.

### Repo intelligence, not just prompt stuffing

The system indexes repository structure, symbols, imports, impacted areas, and likely test targets so it can localize work and keep context tight on real codebases.

### One runtime, multiple surfaces

The same execution stack powers:

- the CLI for direct operator use
- a local HTTP API for orchestration and integrations
- VS Code tooling for repo-aware interaction
- Telegram and WhatsApp command flows for approvals, status, diff, and patch visibility

## Who It Is For

- platform and infra teams that want governed AI execution inside repositories
- engineering teams working in larger repos or monorepos
- teams that need approvals, rollback, and proof artifacts alongside automation
- builders who want a serious local coding agent surface, not only a hosted chat UX

## Product Page

- [https://rebootix-research.com/viki-code](https://rebootix-research.com/viki-code)

The Rebootix website source now includes a dedicated `/viki-code` product route, while this repository remains the full engineering source, proof base, and release home.

## Install

Clone the repository and bootstrap a local install inside the checkout:

```bash
git clone https://github.com/rebootix-research/viki-code.git
cd viki-code
python scripts/install.py --path .
```

Start the local API immediately after install:

```bash
python scripts/install.py --path . --run
```

Upgrade an existing local install:

```bash
python scripts/install.py --path . --update
```

Remove the local install and launchers:

```bash
python scripts/install.py --path . --uninstall
```

If you prefer a built artifact flow, install from the release wheel:

```bash
pip install dist/viki_code-4.1.4-py3-none-any.whl
```

If you prefer a container package, pull the published GitHub Container Registry image:

```bash
docker pull ghcr.io/rebootix-research/viki-code:latest
docker run --rm ghcr.io/rebootix-research/viki-code:latest --help
```

## Provider Setup

VIKI is built around LiteLLM-backed provider routing. The current public surface is strongest with:

- OpenAI-compatible providers
- Alibaba Cloud Model Studio / DashScope / Qwen
- OpenRouter
- Anthropic
- local Ollama

Recommended environment variables:

```bash
# Optional: pin the preferred backend when more than one is configured
export VIKI_PROVIDER=dashscope

# Global routing overrides
export VIKI_REASONING_MODEL=openai/qwen3.5-plus
export VIKI_CODING_MODEL=openai/qwen3-coder-next
export VIKI_FAST_MODEL=openai/qwen3.5-plus

# DashScope / Qwen
export DASHSCOPE_API_KEY=...
export DASHSCOPE_API_BASE=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
```

OpenRouter example:

```bash
export VIKI_PROVIDER=openrouter
export OPENROUTER_API_KEY=...
export OPENROUTER_API_BASE=https://openrouter.ai/api/v1
export VIKI_CODING_MODEL=openrouter/deepseek/deepseek-chat
```

Generic OpenAI-compatible endpoint example:

```bash
export VIKI_PROVIDER=openai-compatible
export OPENAI_API_KEY=...
export OPENAI_API_BASE=https://your-compatible-endpoint.example/v1
export OPENAI_COMPAT_MODEL=openai/gpt-4o-mini
```

Anthropic example:

```bash
export VIKI_PROVIDER=anthropic
export ANTHROPIC_API_KEY=...
export VIKI_CODING_MODEL=claude-3-5-sonnet-latest
```

PowerShell example:

```powershell
$env:VIKI_PROVIDER = "dashscope"
$env:DASHSCOPE_API_KEY = "<temporary key>"
$env:DASHSCOPE_API_BASE = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
$env:VIKI_CODING_MODEL = "openai/qwen3-coder-next"
viki providers
viki doctor .
```

Use `viki providers` to inspect the selected backend, fallback order, required environment variables, and model routing before you run a live task.

## Quick Start

Installed launcher locations:

```text
Linux / macOS: .viki-workspace/bin/viki-local
Windows CMD:   .viki-workspace\bin\viki-local.cmd
PowerShell:    .viki-workspace\bin\viki-local.ps1
```

Typical first-run flow:

```bash
viki version
viki doctor .
viki up . --dry-run
viki run "Fix the broken calculation and run the relevant tests" --path .
```

PowerShell-friendly first run:

```powershell
git clone https://github.com/rebootix-research/viki-code.git
cd viki-code
python scripts/install.py --path .
.\.viki-workspace\bin\viki-local.ps1 providers
.\.viki-workspace\bin\viki-local.ps1 doctor .
.\.viki-workspace\bin\viki-local.ps1 run "Fix the broken calculation and make tests pass" --path .
```

## Terminal Experience

VIKI ships with a premium terminal presentation layer for interactive use. In a capable terminal it renders a branded banner, session header, repo and branch context, provider and model strip, agent activity tables, approval panels, and readable diff previews.

- Default interactive theme: `premium`
- Alternate high-contrast theme: `contrast`
- Plain fallback: automatic in CI, non-interactive shells, and minimal terminals
- Explicit plain mode: `viki --plain ...`
- Forced themed capture for transcripts or screenshots: `viki --force-rich ...`

Examples:

```bash
viki --theme premium doctor .
viki --theme premium providers
viki --theme premium run "Fix the broken calculation and make tests pass" --path .
viki --plain run "Inspect this repo and summarize the next safe step" --path .
viki --force-rich --theme premium doctor .
viki --theme premium diff <session_id> --path . --rendered
```

The themed layer is designed for PowerShell, macOS Terminal, Linux shells, and modern Windows terminals without requiring shell-specific setup.

## CLI

Repo intelligence and session tooling:

```bash
viki repo "auth migration" --path .
viki symbols "normalize_account" --path .
viki impact --changed-file viki/api/server.py --path .
viki diff <session_id> --path .
viki status . --session-id <session_id>
```

Live task examples:

```bash
viki run "Fix the broken calculation and make tests pass" --path .
viki run "Refactor auth naming consistently and keep behavior green" --path .
viki run "Migrate the old consumer to the new API and run the relevant tests" --path .
```

## API

Start the local API:

```bash
viki up . --host 0.0.0.0 --port 8787
```

Representative routes:

- `GET /healthz`
- `GET /protocol`
- `GET /runs`
- `POST /runs`
- `GET /runs/{id}`
- `GET /runs/{id}/events`
- `GET /runs/{id}/diff`
- `GET /runs/{id}/result`
- `GET /repo/profile`
- `GET /repo/context?q=...`
- `GET /repo/search?q=...`
- `GET /repo/symbols?q=...`
- `GET /repo/impact?path=...`
- `GET /approvals`
- `POST /approvals/{id}`

Example run request:

```bash
curl -X POST http://127.0.0.1:8787/runs ^
  -H "Content-Type: application/json" ^
  -d "{\"prompt\":\"Fix the broken calculation and make tests pass\",\"workspace_path\":\".\"}"
```

## IDE / VS Code

Generate workspace integration:

```bash
viki ide vscode .
viki ide vscode-extension .
```

The VS Code surface is built to expose task submission, status visibility, diff review, approvals, and repo-aware lookup against the same underlying session model.

## Messaging

Telegram and WhatsApp webhook handlers support a command-driven operational surface, including:

```text
/help
/latest
/sessions
/status <session_id>
/approvals
/approve <id>
/reject <id>
/diff <session_id>
/patch <session_id>
/symbols <query>
/repo <query>
/logs <session_id>
```

In the current public proof set, these messaging surfaces are harness-tested. They are not represented here as fully live-network validated end to end.

## Safety, Approvals, And Rollback

VIKI is designed to be useful under autonomy without pretending autonomy should be ungoverned.

- isolated task worktrees
- targeted validation before acceptance
- approval-aware action flow for risky operations
- diff preview and exported patch bundles
- redacted logs and proof artifacts
- rollback and revert paths preserved as first-class outputs

## Benchmarks And Live Validation

The current 4.1.4 evidence shows a credible, live-tested system:

- `9/9` broader live validation tasks passed on fresh repos
- `8/8` public live benchmark cases passed
- `8/8` public offline scripted benchmark cases passed
- real API bug-fix and API multi-agent refactor runs passed
- human-style install validation passed
- real WSL-isolated live execution passed

The honest limitation is speed: VIKI currently trails the bundled baselines on time-to-green even where it completes the task successfully.

## Project Structure

```text
viki/                 Core runtime, repo intelligence, orchestration, API, IDE, integrations
scripts/              Install, validation, live-run, and release helpers
tests/                Unit, integration, CLI, API, and regression coverage
BENCHMARK_RESULTS/    Curated machine-readable benchmark artifacts
LIVE_RUN_RESULTS/     Curated live validation artifacts
docs/                 Published benchmark board and supporting docs
assets/logo/          SVG brand assets for GitHub and release surfaces
```

## Community

- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [License](LICENSE)

## Built By Rebootix Artificial Intelligence Research And Development

Rebootix Artificial Intelligence Research and Development builds advanced AI systems, autonomous software infrastructure, and production-grade machine intelligence products.

Rebootix focuses on real-world execution, applied AI engineering, and high-performance intelligent systems. VIKI Code is part of that broader effort: practical AI software that operates inside real developer workflows and governed execution environments.
