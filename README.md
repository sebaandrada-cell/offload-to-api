# offload-to-api

**Stop spending your Claude subscription quota on reading big files.**

A plugin for Claude Code and Claude Cowork. When you ask Claude to read a long PDF, a large log or two versions of a config, it hands the reading to small local scripts that use cheap Claude API calls (Haiku by default), billed to your API credits, and then works from a short result instead of the whole file.

*Versión en castellano más abajo.*

## What it does

| You ask | Script | Typical cost |
|---|---|---|
| "Summarize this 40-page contract" / "What is the notice period?" | `read_pdf.py` | < 0.001 USD per page (Haiku) |
| "Extract vendor, date and total from these invoices" | `read_pdf.py --fields` → `table.YYYY-MM-DD_HHMMSS.csv` | < 0.001 USD per page |
| "What's failing in this 50k-line firewall export?" | `summarize_log.py` | a few cents |
| "Compare these two configs and tell me the risks" | `compare_configs.py` | 0.01–0.04 USD (Sonnet) |

Built-in guardrails:
- **Spending caps:** 2 USD per day across all tools (configurable), confirmation above 0.25 USD, `--dry-run` to see the cost first, and caps on output tokens, PDF size and log chunks.
- **Secrets always masked** before sending: passwords, SNMP communities, PSKs and tokens. `--anonymize` also masks IPs, emails and MACs.
- **Personal identifiers** (ID numbers, IBANs, phones, emails, addresses, dates of birth) are not copied into PDF summaries and answers.
- **Config diffs send only the diff**, with consistent placeholders whose real values stay on your machine.

## Requirements

- Claude API credits at https://platform.claude.com (separate from a Claude Pro/Max subscription).
- Python 3.9 or later, and git.
- Claude Code or Claude Cowork.

## Install

1. Install the scripts on your computer:

   ```bash
   git clone https://github.com/sebaandrada-cell/offload-to-api.git ~/offload-to-api-src
   ```

   ```bash
   bash ~/offload-to-api-src/install.sh
   ```

2. Authenticate, with one of these:
   - **Recommended:** install the [Anthropic CLI](https://platform.claude.com/docs) and run `ant auth login`. No key is stored anywhere.
   - **Alternative:** create a key at https://platform.claude.com/settings/keys and put `ANTHROPIC_API_KEY=...` in `~/.offload-to-api/.env`.

   > ⚠️ Do **not** export `ANTHROPIC_API_KEY` in your shell profile. Claude Code would then use the API key instead of your subscription and bill your credits for everything.

3. Add the plugin:
   - **Claude Code:** `/plugin install offload-to-api --marketplace sebaandrada-cell/offload-to-api`
   - **Claude Cowork:** install the plugin from this repository through Cowork's plugin settings.

4. Set a monthly spend limit and turn off auto-reload at https://platform.claude.com/settings/limits and https://platform.claude.com/settings/billing. The scripts' caps are a second layer, not a replacement.

## Update

1. Pull the new version and run the installer again. It copies the new scripts and keeps your spend ledger and `.env`:

   ```bash
   git -C ~/offload-to-api-src pull
   ```

   ```bash
   bash ~/offload-to-api-src/install.sh
   ```

2. Update the plugin in Claude Code, then restart it:

   ```bash
   claude plugin marketplace update offload-to-api
   ```

   ```bash
   claude plugin update offload-to-api@offload-to-api
   ```

The plugin (the skill) and the scripts are separate: updating one does not update the other.

## Uninstall

```bash
claude plugin uninstall offload-to-api@offload-to-api
```

```bash
claude plugin marketplace remove offload-to-api
```

Then delete the scripts, the venv, the spend ledger and the optional `.env`, and the clone:

```bash
rm -rf ~/.offload-to-api ~/offload-to-api-src
```

If you created an API key just for this, revoke it at https://platform.claude.com/settings/keys. Summaries and reports the tools saved next to your files (`*.summary.md`, `*.answer.md`, `*.changes.md`, `*.map.json`, `table.*.csv`) stay where they are: delete the ones that contain personal data.

## Claude Code vs Cowork

- **Claude Code** runs on your computer, so Claude runs the scripts itself and only reads the short result.
- **Cowork** may run in a cloud workspace that cannot reach your computer. In that case Claude gives you one ready-to-copy command. You run it (on macOS, a file picker opens), then attach the result.

## Use the scripts without Claude

```bash
~/.offload-to-api/venv/bin/python ~/.offload-to-api/scripts/read_pdf.py contract.pdf --question "What is the notice period?" --dry-run
```

All options: `plugins/offload-to-api/skills/offload-to-api/references/tools.md`.

## Privacy, read this

- **PDFs are sent whole** to the Claude API, including for the cost estimate. Nothing inside a PDF can be masked.
- Masking is pattern-based and **will miss things** (what it covers is listed at the top of `plugins/offload-to-api/scripts/masking.py`; for example, `--anonymize` does not cover IPv6 addresses or host names). Run `--dry-run` on a sample first (for configs it shows the exact diff that would be sent).
- Sending employer or customer data to any external AI service may be against your organisation's policy. Check first.
- Results are saved next to the original files. Delete them if they contain personal data. Nothing is overwritten: every run creates a new file with a timestamp in its name (`NAME.2026-11-21_164137.summary.md`), readable only by you (mode 600), and a name that is already taken gets `-2`, `-3`... The tools never follow a symbolic link to write. If the folder is read-only, the result is still printed on screen.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `OFFLOAD_DAILY_CAP_USD` | `2.00` | Daily cap across all tools. Must be a finite positive number. |
| `OFFLOAD_CONFIRM_ABOVE_USD` | `0.25` | Ask before spending more than this (`0` always asks) |
| `OFFLOAD_HOME` | `~/.offload-to-api` | Scripts, venv, spend ledger and optional `.env` |

A value that is not a number (or is `nan`, `inf` or negative) stops the tool with a message instead of silently disabling the cap.

Prices are hard-coded in `scripts/common.py`. Check them against https://platform.claude.com/docs/en/about-claude/pricing.

## How the spend cap works, and its limits

Every call is added to a ledger, `~/.offload-to-api/usage.json` (one total per day, the last 60 days). Before each call the tools check that today's total plus that call's estimated cost stays under the cap, and they stop if it would not. Several runs at once share the ledger safely (it is locked and written atomically).

- **If the ledger is unreadable or damaged, the tools stop** and say so. They do not start from zero, because that would bypass the cap. Fix the file, or delete it to start counting from zero.
- **If the cap is reached halfway through a run,** results already paid for are kept: finished PDFs and the table are saved, and a log summary is saved as `NAME.summary.partial.md`.
- **It is a local protection, not a billing limit.** It only counts what these tools spend on this computer, in this user account. A call that fails after Anthropic has billed it (for example a timeout) cannot be recorded. Set a monthly spend limit in the Console as well.
- Cost estimates assume about 3.5 characters per token. Text with many numbers, hex or non-English characters uses more tokens, so a run can cost more than its estimate. The per-call check bounds the overrun to one call.

## Platforms and troubleshooting

Tested on macOS with the system Python 3.9. It should work on Linux. It is not tested on Windows (the ledger lock is not available there, and the file picker is macOS only).

| Problem | What to do |
|---|---|
| `python3 not found`, or a syntax error mentioning a newer Python | Install Python 3.9 or later and run `install.sh` again |
| `pip` cannot download the SDK | Check your network or proxy and run `install.sh` again. The SDK is pinned below 1.0 because 1.x needs Python 3.10 or later. |
| `Invalid API key` or an authentication error | Run `ant auth login` again. If you use a key in `~/.offload-to-api/.env`, check that it is valid and not expired. |
| `ant: command not found` | Install the Anthropic CLI, or use a key in `~/.offload-to-api/.env` instead |
| The tool says the spend ledger is unreadable | The file `~/.offload-to-api/usage.json` is damaged. Inspect it, or delete it to start counting from zero. |
| `Daily cap ... would be passed` | You reached today's cap. Wait until tomorrow, use a cheaper model, or raise `OFFLOAD_DAILY_CAP_USD`. |
| No file picker opens | The picker only exists on macOS. Pass the file path as an argument. |
| `SKIPPED` for a PDF | It is over 30 MB or 100,000 tokens, encrypted or damaged. Split it or remove the password first. |

## Reporting a security problem

See `SECURITY.md`.

## Not affiliated

This is a community project, not an official Anthropic product.

## License

MIT, see `LICENSE`.

---

## En castellano

Plugin para Claude Code y Claude Cowork. Cuando le pides a Claude leer un PDF largo, un log grande o dos versiones de una configuración, delega esa lectura en unos scripts locales que usan llamadas baratas a la Claude API (Haiku por defecto). Las paga tu crédito de la API, no la cuota de tu suscripción, y Claude trabaja después con un resultado corto.

**Instalación:** los mismos pasos de arriba (`git clone`, `bash install.sh`, `ant auth login` y añadir el plugin). Usa `--lang Spanish` para que los informes salgan en castellano.

**Importante:** no exportes `ANTHROPIC_API_KEY` en tu `.zshrc` o `.bashrc`. Claude Code dejaría de usar tu suscripción y lo cobraría todo a la API.
