"""
common.py - Shared helpers for the offload-to-api tools.

Pricing table, spending caps, the API client, secret masking, anonymisation,
the daily spend ledger and the macOS file picker.

Everything the tools keep between runs (spend ledger, optional .env) lives in
~/.offload-to-api/ (override with OFFLOAD_HOME), never inside the plugin folder.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HOME = Path(os.environ.get("OFFLOAD_HOME", Path.home() / ".offload-to-api")).expanduser()
ENV_FILE = HOME / ".env"
LEDGER = HOME / "usage.json"

# ---- Caps (USD, which is how Anthropic bills). Override with environment variables. ----
DAILY_CAP_USD = float(os.environ.get("OFFLOAD_DAILY_CAP_USD", "2.00"))      # all tools together
CONFIRM_ABOVE_USD = float(os.environ.get("OFFLOAD_CONFIRM_ABOVE_USD", "0.25"))  # ask unless --yes
EFFORT = "low"   # reading and extracting does not need deep reasoning; leaves room for the answer

# USD per million tokens (input, output). Check https://platform.claude.com/docs/en/about-claude/pricing
# Haiku prices apply to prompts up to 100k tokens; the tools keep requests below that.
MODELS = {
    "haiku": ("claude-haiku-5-5", 0.10, 0.50),
    "sonnet": ("claude-sonnet-5-5", 2.00, 10.00),
    "opus": ("claude-opus-5-5", 4.00, 20.00),
}

# Passwords, SNMP communities, pre-shared keys, tokens... are ALWAYS masked before sending
# (see masking.py for what is covered).
from masking import WEAK_SECRETS, mask_secrets  # noqa: E402,F401

ANON_PATTERNS = [
    ("IP", r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b"),
    ("EMAIL", r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    ("MAC", r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"),
]


def make_client():
    """API key from ~/.offload-to-api/.env if present; otherwise the SDK's default
    credential chain (ANTHROPIC_API_KEY, then the `ant auth login` profile)."""
    import anthropic
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key:
                    return anthropic.Anthropic(api_key=key, max_retries=1, timeout=120)
    return anthropic.Anthropic(max_retries=1, timeout=120)


def anonymize(text):
    for label, pattern in ANON_PATTERNS:
        text = re.sub(pattern, f"<{label}>", text)
    return text


def cost(model, tokens_in, tokens_out):
    _, p_in, p_out = MODELS[model]
    return tokens_in / 1e6 * p_in + tokens_out / 1e6 * p_out


def _read_ledger():
    today = dt.date.today().isoformat()
    data = {}
    if LEDGER.exists():
        try:
            data = json.loads(LEDGER.read_text())
        except json.JSONDecodeError:
            data = {}
    return today, data


def spent_today():
    today, data = _read_ledger()
    return data.get(today, 0.0)


def record_spend(usd):
    HOME.mkdir(parents=True, exist_ok=True)
    today, data = _read_ledger()
    data[today] = round(data.get(today, 0.0) + usd, 6)
    LEDGER.write_text(json.dumps(data, indent=2))


def check_budget(estimate, assume_yes):
    """Stop if the estimate would pass the daily cap; ask above the confirmation threshold."""
    if spent_today() + estimate > DAILY_CAP_USD:
        sys.exit(f"The estimate would pass the daily cap ({DAILY_CAP_USD} USD). "
                 "Use a cheaper model, a smaller input, or raise OFFLOAD_DAILY_CAP_USD.")
    if estimate > CONFIRM_ABOVE_USD and not assume_yes:
        if input(f"Estimated up to {estimate:.4f} USD. Continue? [y/N] ").strip().lower() not in ("y", "s"):
            sys.exit("Cancelled.")


def call(client, model, content, max_tokens, output_config=None):
    """One Messages API call with the daily cap enforced and the spend recorded.
    Returns (text, usd, stop_reason)."""
    if spent_today() >= DAILY_CAP_USD:
        sys.exit(f"Daily cap reached ({DAILY_CAP_USD} USD). Stopping.")
    config = {"effort": EFFORT}
    config.update(output_config or {})
    resp = client.messages.create(
        model=MODELS[model][0],
        max_tokens=max_tokens,
        output_config=config,
        messages=[{"role": "user", "content": content}],
    )
    usd = cost(model, resp.usage.input_tokens, resp.usage.output_tokens)
    record_spend(usd)
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    if resp.stop_reason == "max_tokens":
        text += "\n\n> Warning: the answer was cut by the output token cap."
    return text, usd, resp.stop_reason


def pick_files(prompt, multiple=False, pdf_only=False):
    """macOS only: open a Finder dialog when no path was given. Elsewhere, ask for a path."""
    if sys.platform != "darwin":
        sys.exit("Pass the file path as an argument (the file picker only exists on macOS).")
    of_type = ' of type {"com.adobe.pdf"}' if pdf_only else ""
    if multiple:
        script = (f'set fs to (choose file with prompt "{prompt}"{of_type} with multiple selections allowed)\n'
                  'set out to ""\nrepeat with f in fs\nset out to out & POSIX path of f & linefeed\nend repeat\n'
                  'return out')
    else:
        script = f'return POSIX path of (choose file with prompt "{prompt}"{of_type})'
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("Cancelled: no file chosen.")
    return [p for p in r.stdout.splitlines() if p.strip()]


def print_summary(estimate=None, real=None):
    if estimate is not None:
        print(f"Max estimated cost: {estimate:.4f} USD | spent today: {spent_today():.4f} / {DAILY_CAP_USD} USD")
    if real is not None:
        print(f"Actual cost: {real:.4f} USD | spent today: {spent_today():.4f} / {DAILY_CAP_USD} USD")
