"""
masking.py - Secret masking for the offload-to-api tools. Pure Python, no dependencies.

mask_secrets(text, placeholder=None) replaces secret VALUES (never the names around
them) with <SECRET>, or <WEAK_SECRET> when the value is a well-known default such as
"public" or "admin", so a model can still warn about it without seeing it.

What it covers:
  - names containing password, passwd, pwd, passphrase, secret, psk, pre-shared-key,
    api key, access key, private key, token, community, credential(s) or key, including
    prefixes and suffixes (db_password, client_secret, AWS_SECRET_ACCESS_KEY, radius-key)
  - `name=value`, `name: value`, `name value` and JSON/YAML forms, quoted values with spaces
  - Cisco-style typed secrets (`enable secret 5 <hash>`, `password 7 <hash>`)
  - Authorization headers and `Bearer` tokens, credentials inside URLs (user:pw@host)
  - PEM private key blocks and a few well-known token formats (AWS access key ids,
    Anthropic, GitHub and Slack tokens, JWTs)

Masking is pattern-based and will miss things. Always review with --dry-run first.
"""
import re

WEAK_SECRETS = {"public", "private", "admin", "password", "cisco", "changeme", "123456"}

# Values that are already placeholders (from this module or from --anonymize)
ALREADY_MASKED = re.compile(r"^<(?:WEAK_SECRET|SECRET|IP|EMAIL|MAC)(?:_\d+)?>$")

_PEM = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.S)
_AUTH_HEADER = re.compile(
    r"(?i)\b(authorization[\"']?[ \t]*[:=][ \t]*[\"']?(?:(?:bearer|basic|token|digest)[ \t]+)?)([^\s\"']+)")
_BEARER = re.compile(r"(?i)\b(bearer[ \t]+)([A-Za-z0-9._~+/=\-]{8,})")
_URL_CREDENTIALS = re.compile(r"(?i)(\b[a-z][a-z0-9+.\-]*://[^\s/:@\"'<>]+:)([^\s/@\"'<>]+)(@)")
_TYPED = re.compile(r"(?i)\b((?:enable[ \t]+)?(?:secret|password|key-string)[ \t]+[0-9][ \t]+)(\S+)")
_KNOWN_TOKENS = re.compile(
    r"\b(?:(?:AKIA|ASIA)[0-9A-Z]{16}|sk-ant-[A-Za-z0-9_\-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}"
    r"|xox[baprs]-[A-Za-z0-9\-]{10,}|eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{2,}\.[A-Za-z0-9_\-]{2,})")

_NAME = (r"(?:[\w.\-]*(?:password|passwd|pwd|passphrase|secret|psk|pre-?shared-?key|api[-_]?key|apikey|"
         r"access[-_]?key|private[-_]?key|token|community|credentials?)[\w.\-]*"
         r"|(?:[\w.\-]*[-_])?key)")
_GENERIC = re.compile(
    r"(?i)(?<![\w])(?P<name>" + _NAME + r")(?P<nq>[\"']?)(?P<sep>[ \t]*[=:][ \t]*|[ \t]+)"
    r"(?:\"(?P<dq>[^\"\n]*)\"|'(?P<sq>[^'\n]*)'|(?P<raw>[^\s\"']+))")


# Names that contain "key" but are database or data-structure keys, not secrets
_NOT_SECRET_NAMES = re.compile(r"(?i)^(?:primary|foreign|sort|partition|hash|range|cache|shard|routing|group|order)[-_.]?key$")


def _default_placeholder(label, value):
    return "<%s>" % label


def mask_secrets(text, placeholder=None):
    """Mask secrets in `text`. `placeholder(label, value)` may return a custom (for example
    numbered) replacement; label is "SECRET" or "WEAK_SECRET"."""
    ph = placeholder or _default_placeholder

    def mk(value):
        label = "WEAK_SECRET" if value.strip("\"'").lower() in WEAK_SECRETS else "SECRET"
        return ph(label, value)

    def sub_group(pattern, source, group):
        def repl(m):
            value = m.group(group)
            if ALREADY_MASKED.match(value):
                return m.group(0)
            start, end = m.span(group)
            base = m.start(0)
            return m.group(0)[:start - base] + mk(value) + m.group(0)[end - base:]
        return pattern.sub(repl, source)

    def generic(m):
        quote = ""
        if m.group("dq") is not None:
            value, quote = m.group("dq"), '"'
        elif m.group("sq") is not None:
            value, quote = m.group("sq"), "'"
        else:
            value = m.group("raw")
        if not value.strip() or ALREADY_MASKED.match(value) or _NOT_SECRET_NAMES.match(m.group("name")):
            return m.group(0)
        # Cisco-style type digit (`secret 5 <hash>`): the typed pass handles the hash
        if not quote and re.fullmatch(r"[0-9]", value) and re.match(r"[ \t]+\S", m.string[m.end():]):
            return m.group(0)
        return m.group("name") + m.group("nq") + m.group("sep") + quote + mk(value) + quote

    text = _PEM.sub(lambda m: mk(m.group(0)), text)
    text = sub_group(_AUTH_HEADER, text, 2)
    text = sub_group(_BEARER, text, 2)
    text = sub_group(_URL_CREDENTIALS, text, 2)
    text = sub_group(_TYPED, text, 2)
    text = _KNOWN_TOKENS.sub(lambda m: mk(m.group(0)), text)
    return _GENERIC.sub(generic, text)
