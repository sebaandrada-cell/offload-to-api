# offload-to-api

Offloads the reading of long PDFs, large logs and configuration diffs to small local scripts that call the Claude API with Haiku (Sonnet for config risk reviews). They are billed to your API credits, so your Claude subscription quota is not spent reading big files. Claude then works from a short summary, an answer or a CSV table instead of the original.

The skill `offload-to-api` activates on its own when a task needs a lot of reading and a summary, answer or extracted fields are enough. It asks before sending sensitive or employer data, or when a run would cost more than 0.25 USD.

## Setup

Install the plugin in Claude Code:

```
/plugin install offload-to-api --marketplace sebaandrada-cell/offload-to-api
```

1. Install the scripts: `bash install.sh` from the repository root. It creates `~/.offload-to-api` with a private Python venv.
2. Authenticate with `ant auth login`, or put `ANTHROPIC_API_KEY=...` in `~/.offload-to-api/.env`. Never export the key in your shell profile.
3. Set a spend limit at https://platform.claude.com/settings/limits.

Full documentation, privacy notes and caps: see the repository README and `skills/offload-to-api/references/tools.md`.
