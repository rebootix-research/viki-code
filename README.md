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

It is built for serious engineering workflows: bug-fixes, refactors, migrations, repo intelligence, local API control, IDE handoff, and chat-driven approvals across the same governed execution core. The current product flow is local-first, prompt-first, and designed to feel stable in a normal PowerShell or terminal session without requiring users to learn internal provider syntax.

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
- Local-first provider flow with Ollama as a first-class runtime when it is available.
- Approval-aware autonomy with diff preview, patch export, and rollback paths.
- Multi-agent execution designed for planning, implementation, validation, and review.
- Repo intelligence tuned for large codebases, monorepos, and targeted test selection.
- CLI, API, VS Code, Telegram, and WhatsApp surfaces over one execution model.

## What You Can Do In Five Minutes

- Install locally and launch directly into the guided VIKI setup flow.
- Use Ollama locally if it is installed, or choose another provider preset without learning LiteLLM routing syntax.
- Pick a provider preset, reuse a shell API key if one is already present, and save a user-level config outside the repo.
- Let VIKI initialize the current repository safely, then ask for a real bug-fix, refactor, or repo summary in the same terminal session.
- Carry the same session model across CLI, API, IDE, and approval workflows.

## Proof At A Glance

| Signal | Current 4.1.4 evidence |
| --- | --- |
| Local regression suite | `100 passed` |
| Live validation suite | `9/9 passed` on fresh repos |
| Generic CLI live wins | `7/7 passed` |
| Public live benchmark slice | `8/8 passed` |
| Public offline benchmark slice | `8/8 passed` |
| Human-style install validation | passed |
| Isolation validation | passed through real WSL-isolated execution |
| Local-first Ollama execution | passed locally on `qwen2.5-coder:7b` |

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

After install, launch the product entrypoint:

```bash
viki
```

VIKI now opens with a guided first-run experience. If setup is incomplete, it launches the setup wizard automatically. If setup is already complete, it drops you into a prompt-first console. If Ollama is installed and reachable, VIKI treats it as the preferred local-first runtime and will guide you toward the strongest practical local coding model it can detect.

Start VIKI immediately after install:

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

## First Launch

The intended first successful path is:

```bash
git clone https://github.com/rebootix-research/viki-code.git
cd viki-code
python scripts/install.py --path .
viki
```

On first launch VIKI:

- shows a premium welcome screen
- shows the active workspace, provider state, GitHub state, recent workspaces, and recent sessions when available
- detects whether provider setup is complete
- launches the setup wizard automatically if it is not
- saves configuration at the user level instead of writing secrets into the repo
- initializes the current workspace safely when needed
- drops you into a prompt-first task entry flow with connected product actions

If you want to revisit setup explicitly, run:

```bash
viki setup
viki setup --repair
```

## Setup Wizard And Provider Setup

The guided setup flow is the primary path for normal users. It hides provider prefix syntax and offers provider presets instead:

- Ollama
- DashScope / Qwen
- OpenAI
- OpenRouter
- Anthropic
- Azure OpenAI
- NVIDIA with a first-class Kimi 2.5 preset over the OpenAI-compatible transport
- Generic OpenAI-compatible endpoints

The wizard asks for the minimum needed values, lets you reuse an API key that is already present in your shell, offers a sensible model profile, and saves the resulting config to a user-level file outside the repository. Provider selection is isolated by default, so the provider you choose becomes the active runtime instead of silently inheriting stale cloud fallbacks from previous runs.

For Ollama users, VIKI:

- detects whether Ollama is installed and reachable
- detects installed local models
- picks the strongest practical coding-capable local model automatically
- offers to pull the recommended local model when the runtime is reachable but no coding model is installed yet
- shows the actual active local model in `viki providers`, `viki doctor`, and the home screen

For NVIDIA users, the wizard keeps the transport details out of the normal path: choose the `NVIDIA` preset, pick `Kimi 2.5`, paste the key, accept the default base URL, and start prompting.

On Windows PowerShell, VIKI now uses a safer secret-input path during setup. Optional Telegram or WhatsApp setup is clearly marked as optional and cannot corrupt the provider flow if you skip it.

Optional setup in the same flow:

- Telegram bot token and allowed chat IDs
- WhatsApp via Twilio
- default approval mode
- default session style
- default terminal theme

Advanced env-based setup is still available for operators who prefer it:

```bash
export VIKI_PROVIDER=ollama
export VIKI_PROVIDER_ALLOW_FALLBACKS=false
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export OLLAMA_MODEL=qwen2.5-coder:7b
viki providers
viki doctor .
```

PowerShell example:

```powershell
$env:VIKI_PROVIDER = "ollama"
$env:VIKI_PROVIDER_ALLOW_FALLBACKS = "false"
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "qwen2.5-coder:7b"
viki providers
viki doctor .
```

## Quick Start

Installed launcher locations:

```text
Linux / macOS: .viki-workspace/bin/viki-local
Windows CMD:   .viki-workspace\bin\viki-local.cmd
PowerShell:    .viki-workspace\bin\viki-local.ps1
```

Typical prompt-first flow after installation:

```bash
viki
# choose provider preset in the wizard if needed
# then use the home screen to open a repo, connect GitHub, resume a session, or type a task at `viki>`
```

Connected product commands are also available directly:

```bash
viki github status
viki github repos --limit 10
viki github clone rebootix-research/viki-code
viki workspaces list
viki workspaces use /path/to/repo
viki sessions list .
viki sessions continue <session_id> --path .
viki providers
```

Explicit task commands still work:

```bash
viki run "Fix the broken calculation and run the relevant tests" --path .
viki status .
viki diff <session_id> --path . --rendered
```

PowerShell-friendly first run:

```powershell
git clone https://github.com/rebootix-research/viki-code.git
cd viki-code
python scripts/install.py --path .
viki
```

## Terminal Experience

VIKI ships with a premium terminal presentation layer for interactive use. In a capable terminal it renders a branded banner, session header, repo and branch context, provider and model strip, setup summaries, agent activity tables, approval panels, and readable diff previews.

- Default interactive theme: `premium`
- Alternate high-contrast theme: `contrast`
- Plain fallback: automatic in CI, non-interactive shells, and minimal terminals
- Explicit plain mode: `viki --plain ...`
- Forced themed capture for transcripts or screenshots: `viki --force-rich ...`
- Guided first run: `viki`
- Connected home screen with primary actions for GitHub, workspaces, setup, approvals, diffs, and session resume
- Explicit onboarding: `viki setup`

Examples:

```bash
viki
viki setup
viki github status
viki workspaces list
viki sessions list .
viki --theme premium doctor .
viki --theme premium providers
viki --theme premium run "Fix the broken calculation and make tests pass" --path .
viki --plain run "Inspect this repo and summarize the next safe step" --path .
viki --force-rich --theme premium doctor .
viki --theme premium diff <session_id> --path . --rendered
```

The themed layer is designed for PowerShell, macOS Terminal, Linux shells, and modern Windows terminals without requiring shell-specific setup.

## Natural-Language Usage

You do not need rigid internal command phrasing to get useful work out of VIKI. The default shell is designed to accept normal human requests such as:

```text
fix this bug
make the tests pass
rename this helper everywhere
summarize this repo
continue the last task
show the last diff
set this up for me
```

When the request is actionable, VIKI uses repo context, recent session state, likely target files, and focused validation hints to shape the execution plan without forcing you to specify file paths up front.

## CLI

Connected product commands:

```bash
viki
viki home
viki github status
viki github repos --limit 10
viki github clone rebootix-research/viki-code --destination ~/viki-workspaces
viki workspaces list
viki workspaces use ~/viki-workspaces/viki-code
viki sessions list .
viki sessions continue <session_id> --path .
```

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

## Troubleshooting

### PowerShell setup input feels fragile

VIKI now uses a PowerShell-safe secure prompt path for secrets when it can. If the terminal cannot support hidden entry cleanly, VIKI falls back to a safer visible single-line prompt and never prints the value back in setup summaries.

### Ollama is installed but VIKI says no model is ready

Run:

```bash
ollama list
ollama pull qwen2.5-coder:7b
viki providers
viki doctor .
```

If `ollama list` works, VIKI should detect the local runtime and show the selected local model clearly.

### The wrong provider is being selected

Pin the provider explicitly:

```bash
export VIKI_PROVIDER=ollama
export VIKI_PROVIDER_ALLOW_FALLBACKS=false
```

Then run:

```bash
viki providers
viki doctor .
```

The selected provider and fallback chain should reflect the active runtime directly.

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
