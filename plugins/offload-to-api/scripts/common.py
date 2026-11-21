"""
common.py - Shared helpers for the offload-to-api tools.

Pricing table, spending caps, the API client, secret masking, anonymisation,
the daily spend ledger and the macOS file picker.

Everything the tools keep between runs (spend ledger, optional .env) lives in
~/.offload-to-api/ (override with OFFLOAD_HOME), never inside the plugin folder.
"""
import contextlib
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows has no fcntl: the ledger then works without the lock
    fcntl = None

HOME = Path(os.environ.get("OFFLOAD_HOME", Path.home() / ".offload-to-api")).expanduser()
ENV_FILE = HOME / ".env"
LEDGER = HOME / "usage.json"
LEDGER_KEEP_DAYS = 60   # older days are dropped from the ledger


def _env_amount(name, default, allow_zero=False):
    """Read a USD amount from the environment. Rejects nan, inf, negative and non-numeric values:
    float() accepts "nan", and a cap of nan would silently disable every comparison."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        sys.exit(f"{name} must be a number, got {raw!r}.")
    if not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
        sys.exit(f"{name} must be a finite positive number, got {raw!r}.")
    return value


# ---- Caps (USD, which is how Anthropic bills). Override with environment variables. ----
DAILY_CAP_USD = _env_amount("OFFLOAD_DAILY_CAP_USD", 2.00)                              # all tools together
CONFIRM_ABOVE_USD = _env_amount("OFFLOAD_CONFIRM_ABOVE_USD", 0.25, allow_zero=True)     # ask unless --yes
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


class BudgetExceeded(SystemExit):
    """Raised before an API call that would pass the daily cap. It is a SystemExit, so a tool
    that does not catch it simply stops with the message; tools holding partial results catch it."""


def _read_ledger():
    """Return (today, data). Fails closed: if the ledger exists but cannot be read, stop instead
    of starting from zero, because that would silently bypass the daily cap."""
    today = dt.date.today().isoformat()
    if not LEDGER.exists():
        return today, {}
    try:
        raw = json.loads(LEDGER.read_text())
        if not isinstance(raw, dict):
            raise ValueError("expected a JSON object")
        data = {}
        for day, value in raw.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0:
                raise ValueError("invalid amount for " + str(day))
            data[str(day)] = float(value)
    except (OSError, ValueError) as e:
        raise SystemExit(
            f"The spend ledger {LEDGER} is unreadable ({e}).\n"
            "Stopping so the daily cap cannot be bypassed. Check the file, or delete it to start "
            "counting from zero, and run again.")
    return today, data


@contextlib.contextmanager
def _ledger_lock():
    """Exclusive lock, so two runs in parallel cannot overwrite each other's spend."""
    HOME.mkdir(parents=True, exist_ok=True)
    with open(HOME / "usage.lock", "a") as handle:
        if fcntl:
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(handle, fcntl.LOCK_UN)


def spent_today():
    today, data = _read_ledger()
    return data.get(today, 0.0)


def record_spend(usd):
    if not math.isfinite(usd) or usd < 0:
        return  # never let a bad number corrupt the ledger
    with _ledger_lock():
        today, data = _read_ledger()
        data[today] = round(data.get(today, 0.0) + usd, 6)
        cutoff = (dt.date.today() - dt.timedelta(days=LEDGER_KEEP_DAYS)).isoformat()
        data = {day: value for day, value in data.items() if day >= cutoff}
        # a temp name unique per process and thread, so even without the lock two writers never share one
        tmp = LEDGER.with_name(f"{LEDGER.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, LEDGER)  # atomic: a crash never leaves a half-written ledger


def check_budget(estimate, assume_yes):
    """Stop if the estimate would pass the daily cap; ask above the confirmation threshold."""
    if spent_today() + estimate > DAILY_CAP_USD:
        sys.exit(f"The estimate would pass the daily cap ({DAILY_CAP_USD} USD). "
                 "Use a cheaper model, a smaller input, or raise OFFLOAD_DAILY_CAP_USD.")
    if estimate > CONFIRM_ABOVE_USD and not assume_yes:
        if input(f"Estimated up to {estimate:.4f} USD. Continue? [y/N] ").strip().lower() not in ("y", "s"):
            sys.exit("Cancelled.")


def call(client, model, content, max_tokens, output_config=None, reserve=None):
    """One Messages API call with the daily cap enforced and the spend recorded.
    `reserve` is the estimated cost of THIS call (input + output); without it, the worst-case
    output cost (max_tokens) is used. The call is refused if spent today plus the reserve would
    pass the cap, so a run cannot go over the cap by a whole call. Returns (text, usd, stop_reason)."""
    if reserve is None:
        reserve = cost(model, 0, max_tokens)
    spent = spent_today()
    if spent + reserve > DAILY_CAP_USD:
        raise BudgetExceeded(f"Daily cap ({DAILY_CAP_USD} USD) would be passed: {spent:.4f} USD spent today "
                             f"and this call may cost up to {reserve:.4f} USD. Stopping.")
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


def stamp():
    """Timestamp used in output file names, e.g. 2026-11-21_164137."""
    return dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")


def open_new(path, encoding="utf-8", newline=None):
    """Create a NEW file with mode 600 and return (handle, final_path).
    It never overwrites an existing file (a taken name gets -2, -3...) and never follows a
    symbolic link, because O_EXCL fails on any existing path, links included."""
    path = Path(path)
    for n in range(1, 100):
        candidate = path if n == 1 else path.with_name(f"{path.stem}-{n}{path.suffix}")
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        return os.fdopen(fd, "w", encoding=encoding, newline=newline), candidate
    raise SystemExit(f"Could not find a free file name for {path}")


def write_new(path, text):
    """Write text to a new file (see open_new) and return its final path."""
    handle, final = open_new(path)
    with handle:
        handle.write(text)
    return final


def print_summary(estimate=None, real=None):
    if estimate is not None:
        print(f"Max estimated cost: {estimate:.4f} USD | spent today: {spent_today():.4f} / {DAILY_CAP_USD} USD")
    if real is not None:
        print(f"Actual cost: {real:.4f} USD | spent today: {spent_today():.4f} / {DAILY_CAP_USD} USD")
