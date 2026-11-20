---
name: offload-to-api
description: >
  This skill should be used whenever a task needs a large amount of text read or processed
  and a summary, a specific answer or extracted fields are enough: a PDF of more than about
  5 pages or several PDFs ("summarize this PDF", "what does this contract say", "extract the
  totals from these invoices", "resume este PDF", "saca los datos de estas facturas"), a log
  or export of more than about 1,000 lines ("check this log", "what is failing in this
  firewall export", "revisa este log"), or two versions of a configuration ("compare these
  two configs", "what changed and is it risky", "compara estas dos configuraciones"). It
  sends that work to local scripts that use cheap Claude API calls billed to the user's API
  credits instead of their Claude subscription quota. Apply it proactively, without being asked.
metadata:
  version: "0.1.0"
---

# Offload big reading to the Claude API

Reading a long PDF or log inside this conversation spends the user's subscription quota (Claude Pro/Max/Team). The `offload-to-api` scripts do that reading with Haiku through the Claude API, billed to the user's API credits, and return only a short result. Work from that result instead of the original.

Reply in the user's language. The scripts report costs in USD: give them in USD.

## 1. Decide whether to offload

Offload when a summary, an answer or extracted fields are enough:

| Case | Script |
|---|---|
| PDF of more than ~5 pages, or several PDFs | `read_pdf.py` (summary or `--question`) |
| Several invoices or similar documents, same fields from each | `read_pdf.py --fields "a,b,c"` |
| Log or export of more than ~1,000 lines | `summarize_log.py --anonymize` |
| Two versions of a configuration | `compare_configs.py --anonymize` |

Do not offload when the file is small (reading it costs less than a call), when the full content must be reasoned over closely (editing code, security review), when the document must be edited, or when the task is not about reading text.

## 2. Ask first when needed

Ask before sending if:
- the document holds sensitive personal data (health, banking, identity documents, children's data) and the user has not asked for this file explicitly;
- it is employer or customer data (their organisation may not allow sending it to an external service);
- the estimated cost is above 0.25 USD.

For PDFs, say that the whole document is sent, including for the cost estimate.

## 3. Check where the scripts can run

Run:

```bash
test -x ~/.offload-to-api/venv/bin/python && test -f ~/.offload-to-api/scripts/read_pdf.py && echo READY
```

- `READY`: go to step 4A.
- Not ready, and this is the user's own computer (for example in Claude Code): tell them the scripts are not installed and give the setup from `references/tools.md` (Install). Stop until they confirm.
- Not ready because this is a cloud or sandboxed workspace that is not the user's computer (usual in Cowork): go to step 4B.

## 4A. Run the script

Always pass absolute paths. Without a path the scripts open a file picker on macOS, which is useless here.

1. Estimate with `--dry-run`, for example:
   ```bash
   ~/.offload-to-api/venv/bin/python ~/.offload-to-api/scripts/read_pdf.py "/abs/path/file.pdf" --question "..." --lang Spanish --dry-run
   ```
2. If under 0.25 USD (or approved), run again without `--dry-run` and with `--yes`.
3. Read only the output: the printed text or the file on the "Saved to:" line. Do not read the original.
4. If the result is not enough, ask a narrower `--question` before falling back to the original.

Options, outputs and caps: `references/tools.md`.

## 4B. Ask the user to run it

Never show placeholder paths such as `/path/to/file.pdf`: users run them literally. Give one ready-to-copy command with the real question filled in. On macOS, omitting the path opens a file picker, which is the easiest option:

```bash
~/.offload-to-api/venv/bin/python ~/.offload-to-api/scripts/read_pdf.py --question "What is the notice period?" --lang Spanish
```

If they have not installed the scripts yet, give the setup from `references/tools.md` first. Then ask them to attach the generated `.md` or `.csv` (saved next to the original) and work from it.

## 5. Report

Say in one line that the reading was offloaded to the API and what it cost (the "Actual cost" line). If the result stores personal data next to the original, mention it.

## Fixed rules

- Default models: Haiku (`read_pdf.py`, `summarize_log.py`) and Sonnet (`compare_configs.py`). Use `--model sonnet` only if Haiku falls short.
- Never create API keys and never export `ANTHROPIC_API_KEY` in the shell: Claude Code would then bill the API instead of the subscription. Keys, if used, go in `~/.offload-to-api/.env`.
- Do not change caps or masking without asking.
- On an authentication error, ask the user to run `ant auth login` (or check `~/.offload-to-api/.env`).
- Never read or send `*.map.json` files: they hold the real values behind placeholders.
