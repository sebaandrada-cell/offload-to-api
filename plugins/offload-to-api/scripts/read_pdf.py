#!/usr/bin/env python3
"""
read_pdf.py - Read PDFs with the Claude API (text, tables and page images).
Three modes:
  summary   (default)    -> NAME.YYYY-MM-DD_HHMMSS.summary.md for each PDF
  question  (--question) -> NAME.YYYY-MM-DD_HHMMSS.answer.md
  table     (--fields)   -> table.csv with one row per PDF (opens in Excel/Numbers)

Accepts one or more PDFs, or a folder (reads the .pdf files in it, not subfolders).
Before spending, it counts the exact tokens of each PDF with the free
token-counting endpoint (the PDF is sent for that).

NOTE: each PDF is sent whole. Nothing inside a PDF can be anonymised. Summaries
and answers avoid copying personal identifiers (see PRIVACY_RULE); --with-ids
turns that off. Table mode copies exactly the fields you ask for.

Usage:
  read_pdf.py PATH [PATH ...] [--question "..."] [--fields "date,vendor,total"]
              [--model haiku|sonnet|opus] [--lang LANG] [--with-ids] [--dry-run] [--yes]
"""
import argparse
import base64
import csv
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

MAX_PDFS = 20                     # per run
MAX_MB = 30                       # the API accepts 32 MB per request
MAX_INPUT_TOKENS_PER_PDF = 100_000  # ~30-60 pages; larger PDFs are skipped (Haiku costs more above 100k)
MAX_OUTPUT_TOKENS = 8000          # includes internal reasoning; only what is used is billed

SUMMARY_PROMPT = """Summarise this document using only what appears in the PDF \
(do not invent anything):
## What it is
Document type, issuer, date and purpose, in 2-3 lines.
## Key points
List of what matters: figures, deadlines, obligations, decisions.
## Dates and amounts
Table | Item | Value | Page |, if any.
## Open or to review
What requires action or is ambiguous.
Cite the page in parentheses when you quote something. Write the answer in {lang}."""

QUESTION_PROMPT = """Answer this question using only the content of the PDF. Cite the \
page in parentheses. If the PDF does not contain the answer, say so clearly. \
Write the answer in {lang}.

Question: {question}"""

TABLE_PROMPT = """Extract these fields from the PDF: {fields}.
Copy values exactly as they appear (dates and amounts included, with currency).
If a field does not appear, leave an empty string. Do not invent or calculate values."""

PRIVACY_RULE = """
Do not copy personal identifiers: national ID or passport numbers, IBAN or account \
numbers, card numbers, phone numbers, emails, full postal addresses or dates of birth. \
Only say that they appear (for example: "the holder's ID number appears"). People's \
names and their role (holder, beneficiary...) may be included."""

# Local safety net: if the model copies a personal identifier anyway, it is masked before
# saving. The engine (with check-digit validation) is in personal.py.
from personal import mask_personal  # noqa: E402,F401


def list_pdfs(path):
    if path.is_dir():
        return sorted(p for p in path.iterdir() if p.suffix.lower() == ".pdf" and p.is_file())
    if path.is_file() and path.suffix.lower() == ".pdf":
        return [path]
    sys.exit(f"Not a PDF or a folder: {path}")


def pdf_block(path):
    data = base64.standard_b64encode(path.read_bytes()).decode()
    return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}


def schema(fields):
    return {"type": "json_schema",
            "schema": {"type": "object", "properties": {f: {"type": "string"} for f in fields},
                       "required": fields, "additionalProperties": False}}


def main():
    ap = argparse.ArgumentParser(description="Read PDFs with the Claude API, with spending caps.")
    ap.add_argument("paths", nargs="*", help="one or more PDFs, or a folder (on macOS, omit to open a file picker)")
    ap.add_argument("--question", help="a specific question about the content")
    ap.add_argument("--fields", help='table columns, comma-separated: "date,vendor,total"')
    ap.add_argument("--model", choices=common.MODELS, default="haiku",
                    help="haiku by default (summarise/extract); sonnet to analyse contracts or reports")
    ap.add_argument("--lang", default="English", help="language of the answer (default: English)")
    ap.add_argument("--with-ids", action="store_true",
                    help="allow copying ID numbers, IBANs, phones, emails, addresses and dates of birth")
    ap.add_argument("--dry-run", action="store_true", help="count tokens and estimate cost; the PDF is sent to count")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = ap.parse_args()
    if args.question and args.fields:
        sys.exit("Use --question or --fields, not both.")

    if len(args.paths) == 1:
        root = Path(args.paths[0]).expanduser().resolve()
        pdfs = list_pdfs(root)
    elif args.paths:
        pdfs = [p for r in args.paths for p in list_pdfs(Path(r).expanduser().resolve())]
        root = pdfs[0].parent
    else:
        pdfs = [Path(p) for p in common.pick_files("Choose one or more PDFs (Cmd+click for several)",
                                                   multiple=True, pdf_only=True)]
        root = pdfs[0].parent
    if not pdfs:
        sys.exit(f"No PDFs in {root}")
    if len(pdfs) > MAX_PDFS:
        print(f"{len(pdfs)} PDFs found; only the first {MAX_PDFS} are processed (MAX_PDFS).")
        pdfs = pdfs[:MAX_PDFS]

    fields = [f.strip() for f in args.fields.split(",") if f.strip()] if args.fields else []
    if fields:
        instruction = TABLE_PROMPT.format(fields=", ".join(fields))
    elif args.question:
        instruction = QUESTION_PROMPT.format(question=args.question, lang=args.lang)
    else:
        instruction = SUMMARY_PROMPT.format(lang=args.lang)
    private = not fields and not args.with_ids
    if private:
        instruction += PRIVACY_RULE
    model_id = common.MODELS[args.model][0]

    print("NOTE: each PDF is sent whole; nothing inside a PDF can be anonymised.")
    client = common.make_client()

    # 1) Count tokens (free) and skip what exceeds the caps
    plan, total_est = [], 0.0
    for p in pdfs:
        mb = p.stat().st_size / 1e6
        if mb > MAX_MB:
            print(f"  SKIPPED {p.name}: {mb:.1f} MB (cap {MAX_MB} MB)")
            continue
        content = [pdf_block(p), {"type": "text", "text": instruction}]
        try:
            tokens = client.messages.count_tokens(
                model=model_id, messages=[{"role": "user", "content": content}]).input_tokens
        except Exception as e:  # encrypted or damaged PDF: skip it and continue
            print(f"  SKIPPED {p.name}: the API cannot read it ({e.__class__.__name__})")
            continue
        if tokens > MAX_INPUT_TOKENS_PER_PDF:
            print(f"  SKIPPED {p.name}: {tokens:,} tokens (cap {MAX_INPUT_TOKENS_PER_PDF:,}). Split the PDF.")
            continue
        est = common.cost(args.model, tokens, MAX_OUTPUT_TOKENS)
        total_est += est
        plan.append((p, content))
        print(f"  {p.name}: {tokens:,} input tokens, up to {est:.4f} USD")

    if not plan:
        sys.exit("No PDFs left to process.")
    print(f"Model: {model_id} | PDFs: {len(plan)}")
    common.print_summary(estimate=total_est)
    if args.dry_run:
        return
    common.check_budget(total_est, args.yes)

    # 2) Process
    total, rows = 0.0, []
    for n, (p, content) in enumerate(plan, 1):
        print(f"  [{n}/{len(plan)}] {p.name}...", file=sys.stderr)
        extra = {"format": schema(fields)} if fields else None
        try:
            text, usd, stop = common.call(client, args.model, content, MAX_OUTPUT_TOKENS, output_config=extra)
        except Exception as e:
            print(f"  ERROR in {p.name}: {e.__class__.__name__}: {e}")
            continue
        total += usd
        if stop == "refusal":
            print(f"  {p.name}: the model declined the request.")
            continue

        if fields:
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                print(f"  {p.name}: incomplete answer, empty row")
                data = {}
            rows.append({"file": p.name, **{f: data.get(f, "") for f in fields}})
        else:
            if private:
                text = mask_personal(text)
            if args.question:
                text = f"**Question:** {args.question}\n\n{text}"
            stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")  # never overwrite earlier results
            out = p.with_name(f"{p.stem}.{stamp}{'.answer.md' if args.question else '.summary.md'}")
            out.write_text(text)
            print(f"\n===== {p.name} =====\n{text}\nSaved to: {out}")

    if fields and rows:
        folder = root if root.is_dir() else root.parent
        out_csv = folder / "table.csv"
        # utf-8-sig and ";" so Excel in most European locales opens it with a double click
        with out_csv.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["file", *fields], delimiter=";")
            w.writeheader()
            w.writerows(rows)
        print(f"\nTable with {len(rows)} rows saved to: {out_csv}")

    common.print_summary(real=total)


if __name__ == "__main__":
    main()
