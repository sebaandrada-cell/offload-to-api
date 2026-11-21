#!/usr/bin/env python3
"""
summarize_log.py - Summarise a large log or export (firewall, SD-WAN, proxy,
monitoring, CSV...) with the Claude API, in chunks, with hard spending caps.

Secrets (passwords, SNMP communities, PSKs, tokens) are always masked before
sending; --anonymize also masks IPs, emails and MACs.

Usage:
  summarize_log.py FILE [--model haiku|sonnet|opus] [--anonymize] [--lang LANG] [--dry-run] [--yes]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

MAX_OUTPUT_TOKENS = 4000      # per call, includes internal reasoning; only what is used is billed
CHARS_PER_CHUNK = 150_000     # ~40k tokens, below Haiku's 100k pricing threshold
MAX_CHUNKS = 15               # larger files are cut (and reported), never silently overspent

CHUNK_PROMPT = """You are a senior network and security engineer. Analyse this fragment \
({n}/{total}) of a log or export. Use only what appears in the text; do not invent anything:
- What kind of data it is (product, log type, date range if present)
- Errors, alerts and anomalous events, grouped, with occurrence counts
- Hosts, IPs, users, sites or links that repeat most in problematic events
- Time patterns (peaks, hours)
Be brief: lists, no filler. Write the answer in {lang}.

<data>
{text}
</data>"""

FINAL_PROMPT = """You are a senior network and security engineer. Below are partial summaries \
of one file. Merge them into a final report with these sections:
1. What the file is
2. Main problems, ordered by severity, with counts
3. Affected elements (hosts, IPs, sites, links)
4. Concrete next diagnostic steps
Mark as [inference] anything not literally in the data. Do not invent anything. \
Write the answer in {lang}.

{summaries}"""


def main():
    ap = argparse.ArgumentParser(description="Summarise a large log with the Claude API, with spending caps.")
    ap.add_argument("file", nargs="?", help="path to the file (on macOS, omit it to open a file picker)")
    ap.add_argument("--model", choices=common.MODELS, default="haiku")
    ap.add_argument("--anonymize", action="store_true", help="also mask IPs, emails and MACs (secrets are always masked)")
    ap.add_argument("--lang", default="English", help="language of the report (default: English)")
    ap.add_argument("--dry-run", action="store_true", help="estimate the cost only; nothing is sent")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = ap.parse_args()

    if not args.file:
        args.file = common.pick_files("Choose the log or export to summarise")[0]
    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        sys.exit(f"File not found: {path}")

    text = common.mask_secrets(path.read_text(errors="replace"))
    if args.anonymize:
        text = common.anonymize(text)

    chunks = [text[i:i + CHARS_PER_CHUNK] for i in range(0, len(text), CHARS_PER_CHUNK)]
    if not chunks:
        sys.exit("The file is empty.")
    truncated = len(chunks) > MAX_CHUNKS
    chunks = chunks[:MAX_CHUNKS]

    # Conservative estimate: ~3.5 characters per token
    tokens_in = sum(len(c) for c in chunks) / 3.5 + 500 * (len(chunks) + 1)
    tokens_out = MAX_OUTPUT_TOKENS * (len(chunks) + (1 if len(chunks) > 1 else 0))
    estimate = common.cost(args.model, tokens_in, tokens_out)

    print(f"File: {path}")
    print(f"Model: {common.MODELS[args.model][0]} | chunks: {len(chunks)}"
          + (f" (CUT to {MAX_CHUNKS}; the rest is not analysed)" if truncated else ""))
    common.print_summary(estimate=estimate)
    if args.dry_run:
        return
    common.check_budget(estimate, args.yes)

    client = common.make_client()
    total, summaries = 0.0, []
    try:
        for n, chunk in enumerate(chunks, 1):
            print(f"  Analysing chunk {n}/{len(chunks)}...", file=sys.stderr)
            prompt = CHUNK_PROMPT.format(n=n, total=len(chunks), text=chunk, lang=args.lang)
            reserve = common.cost(args.model, len(prompt) / 3.5, MAX_OUTPUT_TOKENS)
            summary, usd, _ = common.call(client, args.model, prompt, MAX_OUTPUT_TOKENS, reserve=reserve)
            summaries.append(summary)
            total += usd

        if len(summaries) == 1:
            report = summaries[0]
        else:
            blocks = "\n\n".join(f"--- Summary {i} ---\n{s}" for i, s in enumerate(summaries, 1))
            prompt = FINAL_PROMPT.format(summaries=blocks, lang=args.lang)
            reserve = common.cost(args.model, len(prompt) / 3.5, MAX_OUTPUT_TOKENS)
            report, usd, _ = common.call(client, args.model, prompt, MAX_OUTPUT_TOKENS, reserve=reserve)
            total += usd
    except common.BudgetExceeded as stop:
        # keep what was already paid for instead of losing it
        if summaries:
            body = "\n\n".join(f"## Chunk {i}\n{s}" for i, s in enumerate(summaries, 1))
            print(f"\n{stop}")
            try:
                partial = common.write_new(path.with_name(f"{path.stem}.{common.stamp()}.summary.partial.md"), body)
                print(f"The {len(summaries)} partial summaries already paid for are saved to: {partial}")
            except OSError as e:
                print(f"The partial summaries could not be saved ({e}); they are printed below.\n\n{body}")
            common.print_summary(real=total)
        raise

    # print first: if the folder is read-only the report is not lost after paying for it
    print("\n" + report)
    try:
        out = common.write_new(path.with_name(f"{path.stem}.{common.stamp()}.summary.md"), report)
        print(f"\nSaved to: {out}")
    except OSError as e:
        print(f"\nWARNING: the report could not be saved ({e}). It is printed above.")
    common.print_summary(real=total)


if __name__ == "__main__":
    main()
