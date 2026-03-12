# VIKI Code 4.1.4

## Release focus

VIKI Code 4.1.4 is the public GitHub release finalization pass on top of 4.1.3. This release stayed narrow and practical: improve live execution speed where possible, widen real proof, harden install and isolation paths, and clean the public release surface.

## What changed

- Reduced small-task waste by using the coding model for localized refactors, retrying malformed structured outputs, and deduping repeated validation commands.
- Added deterministic runbook synthesis for docs-only tasks that ask what changed and what to run, so `CHANGE_RUNBOOK.md` includes explicit Python, TypeScript, and Go validation commands reliably.
- Improved generic migration localization so caller files are prioritized over API definition files for vague migration prompts.
- Added a Linux runtime fallback from `python` to `python3` when `python` is unavailable, which fixed real WSL isolated validation.
- Added container/runtime probing to `viki doctor` and strengthened the WSL isolation validator with safe env forwarding and force-reinstall behavior.
- Added real human-style install validation for the built wheel, including help, version, doctor, dry-run prep, a real task run, update, and uninstall checks.
- Expanded the public benchmark set to eight cases:
  - create-hello
  - generic bug-fix
  - generic migration
  - generic refactor
  - matrix bug-fix
  - monorepo rollout
  - repo overview
  - change runbook
- Cleaned packaging so the sdist no longer drags the entire historical `BENCHMARK_RESULTS`, `LIVE_RUN_RESULTS`, and workspace cache into the Python package.

## Validated outcome

- Full local regression suite: `59 passed`
- Human-style installed wheel validation: passed
- WSL isolation live validation: passed
- Broader live suite on fresh repos: `9/9 passed`
- Public offline benchmark: `8/8 passed`
- Public live benchmark: `8/8 passed`

## Live outcome summary

- API bug-fix with a generic prompt: passed
- API multi-agent refactor with a generic prompt: passed
- CLI generic bug-fix, refactor, migration, repo overview, matrix bug-fix, change runbook, and monorepo rollout: all passed
- Big realistic task: monorepo rollout passed with the requested cross-package auth rename plus green tests

## Remaining limitations

- VIKI is now a credible public release, but it is still much slower than the bundled baselines on time-to-green.
- Docker and Podman were unavailable on this Windows host, so container validation used the strongest feasible alternative: real WSL isolation.
- Messaging integrations remain harness-tested here rather than live-network validated end to end.

## Release artifacts

- `dist/viki_code-4.1.4.tar.gz`
- `dist/viki_code-4.1.4-py3-none-any.whl`
- `dist/viki_code-4.1.4-public-github-release-bundle.zip`
- `BENCHMARK_RESULTS/final_public_release_live_report.json`
- `BENCHMARK_RESULTS/final_public_release_live_comparison.json`
- `BENCHMARK_RESULTS/final_public_release_offline_report.json`
- `BENCHMARK_RESULTS/final_public_release_live_board/`
- `LIVE_RUN_RESULTS/public_release/`
- `LIVE_RUN_RESULTS/human_install/`
- `LIVE_RUN_RESULTS/isolation_validation/`
- `PROOF_REPORT.md`

## Public GitHub polish

This repository was then tightened for public presentation without changing the underlying 4.1.4 proof claims:

- rewrote the README for a stronger product-grade GitHub presentation
- added SVG branding assets for the logo, wordmark, and README banner
- added the MIT license plus concise public community docs
- removed stale release leftovers and older proof clutter from the public repo surface
- cleaned package metadata so the license and new public assets ship correctly
- revalidated the repo with `pytest`, the documented install bootstrap, and a fresh package build
- added a linked public product-page CTA so the GitHub repo and Rebootix website now point at the same VIKI Code launch surface
