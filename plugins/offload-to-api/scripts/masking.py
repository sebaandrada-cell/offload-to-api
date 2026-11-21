"""
masking.py - Secret masking for the offload-to-api tools. Pure Python, no dependencies.

mask_secrets(text, placeholder=None) replaces secret VALUES (never the names around
them) with <SECRET>, or <WEAK_SECRET> when the value is a well-known default such as
"public" or "admin", so a model can still warn about it without seeing it.

What it covers:
  - names containing password, passwd, pwd, passphrase, secret, psk, pre-shared-key,
    api key, access key, private key, token, community, credential(s) or key, including
    prefixes and suffixes (db_password, client_secret, AWS_SECRET_ACCESS_KEY, radius-key)
    and camelCase (signingKey, hmacKey, sessionKey)
  - short names (pass, pw, cookie, sig) and Spanish names (clave, contraseña, secreto,
    llave), only with `=` or `:` so ordinary sentences are left alone
  - `name=value`, `name: value`, `name value` and JSON/YAML forms; quoted values (with spaces
    and escaped quotes); unquoted values with spaces up to the end of a config line; and the
    value on the next line (YAML `password:` with the value indented below)
  - Cisco-style typed secrets (`enable secret 5 <hash>`, `password 7 <hash>`, `wpa-psk ascii 7 <hash>`)
  - Authorization headers and `Bearer` tokens, credentials inside URLs (user:pw@host, also
    when the password contains @)
  - PEM and PGP private key blocks and well-known token formats with no name in front (AWS,
    Anthropic, GitHub, GitLab, Slack, Stripe, Google, Hugging Face, OpenAI, Resend, Apify,
    Supabase, npm, JWT)

Masking is pattern-based and will miss things. Always review with --dry-run first.
"""
import re

WEAK_SECRETS = {"public", "private", "admin", "password", "cisco", "changeme", "123456"}

# Values that are already placeholders (from this module or from --anonymize)
ALREADY_MASKED = re.compile(r"^<(?:WEAK_SECRET|SECRET|IP|EMAIL|MAC)(?:_\d+)?>$")

_PEM = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----.*?-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----", re.S)
_AUTH_HEADER = re.compile(
    r"(?i)\b(authorization[\"']?[ \t]*[:=][ \t]*[\"']?(?:(?:bearer|basic|token|digest)[ \t]+)?)([^\s\"']+)")
_BEARER = re.compile(r"(?i)\b(bearer[ \t]+)([A-Za-z0-9._~+/=\-]{8,})")
# The password runs to the LAST @ before the path: user:p@ss@host masks p@ss. The scheme must start a
# word and is at most 30 characters long: without that bound, a long line of dots or dashes
# (a.a.a.a...) took quadratic time (ReDoS).
_URL_CREDENTIALS = re.compile(
    r"(?i)((?<![a-z0-9+.\-])[a-z][a-z0-9+.\-]{0,30}://[^\s/:@\"'<>]+:)([^\s/\"'<>]+)(@)(?=[\w.\-\[])")
_TYPED = re.compile(
    r"(?i)\b((?:enable[ \t]+)?(?:secret|password|key-string)[ \t]+[0-9][ \t]+"
    r"|wpa-psk[ \t]+(?:ascii|hex)[ \t]+[0-9][ \t]+)(\S+)")
_KNOWN_TOKENS = re.compile(
    r"(?<![\w])(?:(?:AKIA|ASIA)[0-9A-Z]{16}|sk-ant-[A-Za-z0-9_\-]{20,}"
    r"|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,}|glpat-[A-Za-z0-9_\-]{20,}"
    r"|xox[baprs]-[A-Za-z0-9\-]{10,}|xapp-[A-Za-z0-9\-]{10,}"
    r"|sk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{30,}|[sr]k_(?:live|test)_[A-Za-z0-9]{16,}"
    r"|AIza[0-9A-Za-z_\-]{30,}|hf_[A-Za-z0-9]{30,}|re_[A-Za-z0-9]{8}_[A-Za-z0-9]{20,}"
    r"|apify_api_[A-Za-z0-9]{20,}|sb_secret_[A-Za-z0-9_\-]{20,}|npm_[A-Za-z0-9]{30,}"
    r"|eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{2,}\.[A-Za-z0-9_\-]{2,})")

# Secret names taken with any separator (`name value` too). A name always starts at the beginning of a
# word (lookbehind (?<![\w.\-])), which keeps the search linear on long lines of dots or dashes.
_NAME = (r"(?:[\w.\-]*(?:password|passwd|pwd|passphrase|secret|psk|pre-?shared-?key|api[-_]?key|apikey|"
         r"access[-_]?key|private[-_]?key|token|community|credentials?)[\w.\-]*"
         r"|(?:[\w.\-]*[-_])?key"
         r"|[\w.\-]*(?-i:[a-z0-9]Key))")                     # camelCase: signingKey, hmacKey, sessionKey
# Names taken only with `=` or `:` (with a space as separator they would mask ordinary sentences)
_NAME_STRICT = (r"(?:[\w.\-]*(?:clave|contrase[nñ]a|secreto|llave)[\w.\-]*"
                r"|(?:[\w.\-]*[-_.])?(?:pass|pw|cookie|sig))")
_QUOTED_VALUE = r"\"(?P<dq>(?:[^\"\\\n]|\\.)*)\"|'(?P<sq>(?:[^'\\\n]|\\.)*)'"

# name=value / name: value. An unquoted value may contain spaces when it runs to the end of the line
# (password = my long phrase); if another field follows (= or :), only the first word is taken.
_EXPLICIT = re.compile(
    r"(?im)(?<![\w.\-])(?P<name>" + _NAME + "|" + _NAME_STRICT + r")(?P<nq>[\"']?)(?P<sep>[ \t]*[=:][ \t]*)"
    r"(?:" + _QUOTED_VALUE + r"|(?P<raw>[^\s\"']+(?:[ \t]+[^\s\"'=:,;{}\[\]()&|<>#]+)*(?=[ \t]*$))"
    r"|(?P<one>[^\s\"']+))")
# name value (strong names only, a single token; never starting with = or :, which is _EXPLICIT's job)
_SPACED = re.compile(
    r"(?i)(?<![\w.\-])(?P<name>" + _NAME + r")(?P<nq>[\"']?)(?P<sep>[ \t]+)"
    r"(?:" + _QUOTED_VALUE + r"|(?P<raw>[^\s\"'=:][^\s\"']*))")
# YAML: `password:` with the value indented on the next line
_NEXT_LINE = re.compile(
    r"(?im)^(?P<pre>[ \t\-]*(?P<name>" + _NAME + "|" + _NAME_STRICT + r")[\"']?[ \t]*:[ \t]*\r?\n[ \t]+)"
    r"(?P<val>(?![^\n]*:(?:\s|$))[^\s#\"'][^\n#]*?)(?P<end>[ \t]*)$")

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
        g = m.groupdict()
        quote = ""
        if g.get("dq") is not None:
            value, quote = g["dq"], '"'
        elif g.get("sq") is not None:
            value, quote = g["sq"], "'"
        else:
            value = g.get("raw") or g.get("one")
        if (not value or not value.strip() or ALREADY_MASKED.match(value)
                or _NOT_SECRET_NAMES.match(g["name"]) or value.lower() in ("ascii", "hex")):
            return m.group(0)
        # Cisco-style type digit (`secret 5 <hash>`): the typed pass handles the hash
        if not quote and re.fullmatch(r"[0-9]", value) and re.match(r"[ \t]+\S", m.string[m.end():]):
            return m.group(0)
        rest = ""
        if g.get("raw") and re.search(r"[ \t]", value):
            # A value with spaces up to the end of the line is taken whole only on config lines, which
            # start with the name (`password = my phrase`). In the middle of a log line
            # (`password=x from 10.0.0.5`) only the first word is masked: the rest is usually useful.
            line_start = m.string.rfind("\n", 0, m.start()) + 1
            if m.string[line_start:m.start()].strip(" \t-"):
                first = re.match(r"\S+", value).group(0)
                value, rest = first, value[len(first):]
        return g["name"] + g["nq"] + g["sep"] + quote + mk(value) + quote + rest

    def next_line(m):
        value = m.group("val")
        if ALREADY_MASKED.match(value) or _NOT_SECRET_NAMES.match(m.group("name")):
            return m.group(0)
        return m.group("pre") + mk(value) + m.group("end")

    text = _PEM.sub(lambda m: mk(m.group(0)), text)
    text = sub_group(_AUTH_HEADER, text, 2)
    text = sub_group(_BEARER, text, 2)
    text = sub_group(_URL_CREDENTIALS, text, 2)
    text = sub_group(_TYPED, text, 2)
    text = _KNOWN_TOKENS.sub(lambda m: mk(m.group(0)), text)
    text = _EXPLICIT.sub(generic, text)
    text = _SPACED.sub(generic, text)
    return _NEXT_LINE.sub(next_line, text)
