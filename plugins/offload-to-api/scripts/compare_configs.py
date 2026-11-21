#!/usr/bin/env python3
"""
compare_configs.py - Compare two versions of a configuration (firewall, switch,
SD-WAN, proxy, JSON, YAML, XML, CLI) and explain the changes and their risks with
the Claude API.

Only the diff is sent (changed lines plus a little context), not the whole files.
If the files are identical, the API is not called.

Secrets are always masked with numbered placeholders that stay consistent across
both files (<SECRET_1>, <IP_2>...), so a change is still visible in the diff.
The placeholder -> real value map stays on your machine (NAME.map.json, mode 600).

Usage:
  compare_configs.py BEFORE AFTER [--model haiku|sonnet|opus] [--anonymize]
                     [--note "context"] [--context N] [--lang LANG] [--dry-run] [--yes]
"""
import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

MAX_OUTPUT_TOKENS = 4000
MAX_DIFF_CHARS = 200_000      # ~55k tokens; a bigger diff is refused, never silently cut
DEFAULT_CONTEXT = 5

PROMPT = """You are a senior network and security engineer. Below is the unified diff \
between two versions of a configuration ("-" lines = before, "+" lines = after).
{note}
Use only what follows from the diff. Mark as [inference] anything not literally in the \
text. Do not invent values. Write the answer in {lang}. Format:

## Summary
What product/kind of configuration it looks like and what changes, in 2-3 lines.

## Changes
Table: | Section | Before | After | Effect |

## Risks
List from highest to lowest: [HIGH], [MEDIUM] or [LOW], what can break or become \
exposed, and why. If you see no risks, say so.

## What to check after applying it
Concrete checks (commands, screens or tests) to validate the change.

## Rollback
What to revert if it fails, in order.

<diff>
{diff}
</diff>"""


def mask_pair(a, b, anonymize=False):
    """Mask sensitive values with numbered placeholders that are CONSISTENT across both
    files. Secrets are always masked; IPs, emails and MACs only with anonymize=True.
    Returns both texts and the placeholder -> real value map."""
    patterns = common.ANON_PATTERNS if anonymize else []
    inverse, counters = {}, {}

    def placeholder(label, value):
        if value not in inverse:
            counters[label] = counters.get(label, 0) + 1
            inverse[value] = f"<{label}_{counters[label]}>"
        return inverse[value]

    def substitute(text):
        text = common.mask_secrets(text, placeholder)
        for label, pattern in patterns:
            text = re.sub(pattern, lambda m, lb=label: placeholder(lb, m.group(0)), text)
        return text

    a2, b2 = substitute(a), substitute(b)
    return a2, b2, {v: k for k, v in inverse.items()}


def main():
    ap = argparse.ArgumentParser(description="Compare two configurations with the Claude API, with spending caps.")
    ap.add_argument("before", nargs="?", help="on macOS, omit to open a file picker")
    ap.add_argument("after", nargs="?", help="on macOS, omit to open a file picker")
    ap.add_argument("--model", choices=common.MODELS, default="sonnet",
                    help="sonnet by default: judging risk needs judgement; haiku for trivial diffs")
    ap.add_argument("--anonymize", action="store_true", help="also mask IPs, emails and MACs (secrets are always masked)")
    ap.add_argument("--note", default="", help='context for the model, e.g. "Edge firewall, new SSH rule"')
    ap.add_argument("--context", type=int, default=DEFAULT_CONTEXT, help="unchanged lines around each change")
    ap.add_argument("--lang", default="English", help="language of the report (default: English)")
    ap.add_argument("--dry-run", action="store_true", help="show the exact diff that would be sent; nothing is sent")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = ap.parse_args()

    if not args.before:
        args.before = common.pick_files("Step 1 of 2: choose the BEFORE configuration")[0]
    if not args.after:
        args.after = common.pick_files("Step 2 of 2: choose the AFTER configuration")[0]
    p_before = Path(args.before).expanduser().resolve()
    p_after = Path(args.after).expanduser().resolve()
    for p in (p_before, p_after):
        if not p.is_file():
            sys.exit(f"File not found: {p}")

    a, b, mapping = mask_pair(p_before.read_text(errors="replace"), p_after.read_text(errors="replace"),
                              anonymize=args.anonymize)
    diff = "".join(difflib.unified_diff(
        a.splitlines(keepends=True), b.splitlines(keepends=True),
        fromfile=f"before/{p_before.name}", tofile=f"after/{p_after.name}", n=args.context))
    if not diff:
        print("The two files are identical. The API was not called (cost 0).")
        return

    changed = sum(1 for l in diff.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---")))
    print(f"Before: {p_before}\nAfter:  {p_after}")
    print(f"Changed lines: {changed} | diff size: {len(diff):,} characters")
    if len(diff) > MAX_DIFF_CHARS:
        sys.exit(f"The diff is larger than {MAX_DIFF_CHARS:,} characters; it is not sent. "
                 "Try --context 1 or compare smaller sections.")

    note = f"User context: {args.note}\n" if args.note else ""
    prompt = PROMPT.format(note=note, diff=diff, lang=args.lang)
    estimate = common.cost(args.model, len(prompt) / 3.5, MAX_OUTPUT_TOKENS)
    print(f"Model: {common.MODELS[args.model][0]}")
    common.print_summary(estimate=estimate)
    if args.dry_run:
        print("\n--- This is what would be sent ---\n" + diff)
        return
    common.check_budget(estimate, args.yes)

    client = common.make_client()
    print("  Analysing changes...", file=sys.stderr)
    # Judging risk benefits from reasoning: use the model's default effort here.
    report, usd, stop = common.call(client, args.model, prompt, MAX_OUTPUT_TOKENS,
                                    output_config={"effort": "medium"}, reserve=estimate)
    if stop == "refusal":
        sys.exit(f"The model declined the request (cost {usd:.4f} USD). Try --anonymize or another model.")

    out = p_after.with_name(p_after.stem + ".changes.md")
    out.write_text(report)
    print("\n" + report)
    print(f"\nSaved to: {out}")
    if mapping:
        p_map = p_after.with_name(p_after.stem + ".map.json")
        # Created with mode 600 from the start, so there is no window in which others can read it
        fd = os.open(p_map, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(mapping, indent=2, ensure_ascii=False))
        os.chmod(p_map, 0o600)  # also fixes the mode if the file already existed
        print(f"Placeholder map (stays on this machine, never sent): {p_map}")
    common.print_summary(real=usd)


if __name__ == "__main__":
    main()
