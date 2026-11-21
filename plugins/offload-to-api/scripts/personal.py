"""
personal.py - Local safety net for personal identifiers in the text a model returns
(summaries and answers about PDFs). Pure Python, no dependencies.

mask_personal(text) masks:
  - Spanish DNI and NIE in any common format: 12345678Z, 12.345.678-Z, 12345678 z, X-1234567-L
  - IBANs of any country, with or without spaces (validated with the mod-97 check digits)
  - payment card numbers (validated with the Luhn check), including 15-digit Amex
  - Spanish phone numbers: 612345678, 612 345 678, 612 34 56 78, 612-345-678, 91 234 56 78,
    with +34, 0034 or (+34) prefixes; and other numbers in international +CC format
  - US-style SSNs and email addresses

Why validation: a DNI/NIE letter, an IBAN and a card number carry check digits. Requiring
them lets this module accept unusual formats (dots, spaces, lowercase) without masking
arbitrary numbers. A contiguous, uppercase DNI/NIE is masked even if its letter is wrong,
because a mistyped ID is still an ID.

Known limits: a 9-digit number starting with 6-9 is masked as a phone number even if it is a
reference; addresses and dates of birth are NOT detected here (they rely on the prompt rule);
the module only sees what the model wrote, never the PDF itself.
"""
import re

_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


def _dni_ok(number, letter):
    return _DNI_LETTERS[int(number) % 23] == letter.upper()


def _luhn_ok(digits):
    total, double = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if double:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        double = not double
    return total % 10 == 0


def _iban_ok(candidate):
    c = candidate.upper()
    if not 15 <= len(c) <= 34 or not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", c):
        return False
    moved = c[4:] + c[:4]
    return int("".join(str(int(ch, 36)) for ch in moved)) % 97 == 1


# 8 digits + letter, optional dots, optional space or hyphen before the letter
_DNI = re.compile(r"(?<![\d.,/\-])(\d{2}\.?\d{3}\.?\d{3})([ \-]?)([A-Za-z])(?![A-Za-z0-9])")
# X/Y/Z + 7 digits + letter, optional separators, any case
_NIE = re.compile(r"(?<![\w.])([XYZxyz])([ \-]?)(\d{7})([ \-]?)([A-Za-z])(?![A-Za-z0-9])")
_IBAN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2}\d{2}(?:[ ]?[A-Za-z0-9]{4}){2,7}(?:[ ]?[A-Za-z0-9]{1,3})?(?![A-Za-z0-9])")
_CARD = re.compile(r"(?<![\d.,/\-])(?:\d{4}[ \-]?\d{4}[ \-]?\d{4}[ \-]?\d{1,7}|\d{4}[ \-]?\d{6}[ \-]?\d{4,5})(?!\d)")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_ES = re.compile(
    r"(?<![\d.,/\-])(?:(?:\+|00)34[ .\-]?|\(\+?34\)[ ]?)?[6789](?:[ .\-]?\d){8}(?![.,/\-]?\d)")
_PHONE_INTL = re.compile(r"(?<![\w])\+\d{1,3}[ .\-]?\d{2,4}(?:[ .\-]?\d{2,4}){2,4}(?!\d)")


def _sub_iban(m):
    text = m.group(0)
    parts = text.split(" ")
    # the pattern may swallow a following 4-letter word: try the longest valid prefix
    for k in range(len(parts), 0, -1):
        head = " ".join(parts[:k])
        if _iban_ok("".join(parts[:k])):
            return "<IBAN>" + text[len(head):]
    return text


def _sub_card(m):
    digits = re.sub(r"\D", "", m.group(0))
    return "<CARD>" if 13 <= len(digits) <= 19 and _luhn_ok(digits) else m.group(0)


def _sub_nie(m):
    prefix, sep1, number, sep2, letter = m.groups()
    full = str("XYZ".index(prefix.upper())) + number
    compact_upper = not sep1 and not sep2 and prefix.isupper() and letter.isupper()
    return "<ID>" if _dni_ok(full, letter) or compact_upper else m.group(0)


def _sub_dni(m):
    number, sep, letter = m.groups()
    digits = number.replace(".", "")
    compact_upper = not sep and letter.isupper()
    return "<ID>" if _dni_ok(digits, letter) or compact_upper else m.group(0)


def mask_personal(text):
    text = _IBAN.sub(_sub_iban, text)
    text = _CARD.sub(_sub_card, text)
    text = _NIE.sub(_sub_nie, text)
    text = _DNI.sub(_sub_dni, text)
    text = _SSN.sub("<SSN>", text)
    text = _EMAIL.sub("<EMAIL>", text)
    text = _PHONE_ES.sub("<PHONE>", text)
    return _PHONE_INTL.sub("<PHONE>", text)
