# offload-to-api (public repository)

Public plugin (Claude Code and Cowork) and marketplace. It offloads reading of long PDFs, logs and config diffs to local scripts that call the Claude API with Haiku. This repository is public: never add personal data, local paths or names.

## State

- v0.1.0. Publishing, pushing and releases require the maintainer's explicit OK.

## Layout

- `.claude-plugin/marketplace.json`: marketplace (owner `sebaandrada-cell`).
- `plugins/offload-to-api/`: the plugin, with `skills/offload-to-api/` (SKILL.md + references/tools.md) and `scripts/` (`common.py` is the shared library).
- `install.sh`: copies the scripts to `~/.offload-to-api` and creates the venv. It does not touch shell profiles and does not create keys.
- `tests/`: offline tests (no API calls), run in CI together with gitleaks.

## Rules

- One change = new branch + PR. No commit, push, merge or release without asking.
- Python 3.9 compatible.
- Never add real personal data, even in tests: use obviously fake values.
- Calls that spend money only with `--dry-run` or Haiku on fake data, and say what they cost.
- If a script's output lines change, update SKILL.md and references/tools.md.
