# Tools reference

The scripts live in `~/.offload-to-api/scripts/` and run with `~/.offload-to-api/venv/bin/python`. They share a daily cap (2 USD by default, `OFFLOAD_DAILY_CAP_USD`) tracked in `~/.offload-to-api/usage.json`, and ask for confirmation above 0.25 USD (`OFFLOAD_CONFIRM_ABOVE_USD`) unless `--yes` is given.

Common options: `--model haiku|sonnet|opus`, `--lang LANG` (default English), `--dry-run`, `--yes`.

## Install (the user runs this once, on their own computer)

Requires Python 3.9+ and git.

```bash
git clone https://github.com/sebaandrada-cell/offload-to-api.git ~/offload-to-api-src
```

```bash
bash ~/offload-to-api-src/install.sh
```

Authentication, one of:
- **Recommended:** the Anthropic CLI login (`ant auth login`), with no key stored anywhere.
- **Alternative:** an API key from https://platform.claude.com/settings/keys in `~/.offload-to-api/.env` as `ANTHROPIC_API_KEY=...` (the installer creates the file with mode 600). Do **not** export it in the shell profile.

## read_pdf.py: PDFs

```bash
~/.offload-to-api/venv/bin/python ~/.offload-to-api/scripts/read_pdf.py PATH [PATH ...] [--question "..."] [--fields "a,b,c"] [--with-ids] [--lang LANG] [--dry-run] [--yes]
```

- `PATH`: one or more PDFs, or a folder (non-recursive). On macOS, no path opens a file picker.
- No mode flag: summary, saved as `NAME.YYYY-MM-DD_HHMMSS.summary.md` next to the PDF.
- `--question`: answer citing pages, saved as `NAME.YYYY-MM-DD_HHMMSS.answer.md`.
- `--fields`: `table.csv` in the PDFs' folder, one row per PDF (`;` separator, UTF-8 with BOM).
- Privacy: the PDF is sent whole, also for `--dry-run` (token counting). Summaries and answers avoid copying ID numbers, IBANs, card numbers, phones, emails, addresses and dates of birth, and a local filter masks common formats before saving. `--with-ids` disables both. `--fields` copies exactly what is requested.
- Caps: 20 PDFs, 30 MB and 100,000 tokens per PDF; larger ones are reported as `SKIPPED`.
- Typical cost with Haiku: under 0.001 USD per page.

## summarize_log.py: logs and exports

```bash
~/.offload-to-api/venv/bin/python ~/.offload-to-api/scripts/summarize_log.py FILE --anonymize [--lang LANG] [--dry-run] [--yes]
```

- Splits the file into chunks, summarises each and merges the summaries, saved as `NAME.summary.md`.
- Passwords, SNMP communities, PSKs and tokens are always masked. `--anonymize` also masks IPs, emails and MACs.
- Cap: 15 chunks of ~150,000 characters; beyond that, it reports that the rest was not analysed.

## compare_configs.py: configuration diffs

```bash
~/.offload-to-api/venv/bin/python ~/.offload-to-api/scripts/compare_configs.py BEFORE AFTER --anonymize [--note "context"] [--lang LANG] [--dry-run] [--yes]
```

- Sends only the diff. The result, saved as `AFTER.changes.md`, has a summary, a change table, HIGH/MEDIUM/LOW risks, checks to run and rollback steps.
- Identical files: no API call, cost 0.
- Placeholders are numbered and consistent across both files (`<IP_1>`). The real-value map is saved as `AFTER.map.json` (mode 600) and must never be read or sent.
- `--dry-run` prints the exact diff that would be sent, and sends nothing.
