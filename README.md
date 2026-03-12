# VIKI Code

<p align="center">
  <img src="assets/logo/viki-code-banner.svg" alt="VIKI Code banner" width="100%" />
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-4.1.4-0f172a?style=for-the-badge" />
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-2563eb?style=for-the-badge" />
  <img alt="License" src="https://img.shields.io/badge/license-MIT-059669?style=for-the-badge" />
  <img alt="Live suite" src="https://img.shields.io/badge/live%20suite-9%2F9-success?style=for-the-badge" />
  <img alt="Public benchmark" src="https://img.shields.io/badge/public%20live%20benchmark-8%2F8-success?style=for-the-badge" />
</p>

VIKI Code is governed coding infrastructure for teams that want an AI system to operate inside real repositories, under approvals, with rollback paths, live validation, and evidence-backed execution.

It is built for serious engineering workflows: bug-fixes, refactors, migrations, repo intelligence, local API control, IDE handoff, and chat-driven approvals across the same governed execution core.

<p align="center">
  <a href="https://rebootix-research.com/viki-code"><strong>Product Page</strong></a>
  ·
  <a href="https://github.com/rebootix-research/viki-code"><strong>GitHub</strong></a>
  ·
  <a href="./PROOF_REPORT.md"><strong>Proof Report</strong></a>
  ·
  <a href="./RELEASE_NOTES.md"><strong>Release Notes</strong></a>
</p>

## Why VIKI Code

- Real repo execution instead of chat-only suggestions.
- Approval-aware autonomy with diff preview, patch export, and rollback paths.
- Multi-agent execution designed for planning, implementation, validation, and review.
- Repo intelligence tuned for large codebases, monorepos, and targeted test selection.
- CLI, API, VS Code, Telegram, and WhatsApp surfaces over one execution model.

## Proof At A Glance

| Signal | Current 4.1.4 evidence |
| --- | --- |
| Local regression suite | `59 passed` |
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

VIKI Code now also lives on the Rebootix site:

- [https://rebootix-research.com/viki-code](https://rebootix-research.com/viki-code)

The site is positioned as the public product surface for VIKI Code, while this repository remains the full engineering source, proof base, and release home.

## Install

Clone the repository and bootstrap a local install inside the checkout:

```bash
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
