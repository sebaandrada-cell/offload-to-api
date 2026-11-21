"""Offline tests for masking and helpers. No API calls, no network, no anthropic import needed."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "offload-to-api" / "scripts"))

import common  # noqa: E402
from compare_configs import mask_pair  # noqa: E402
from read_pdf import mask_personal  # noqa: E402


class SecretMasking(unittest.TestCase):
    def test_cli_json_and_key_value(self):
        text = 'snmp community r3ad0nly ro\n "psk": "Sup3rS3cret!",\n radius-key=abc123\npassword=hunter2'
        out = common.mask_secrets(text)
        for secret in ("r3ad0nly", "Sup3rS3cret!", "abc123", "hunter2"):
            self.assertNotIn(secret, out)

    def test_weak_secret_is_flagged(self):
        self.assertIn("<WEAK_SECRET>", common.mask_secrets("snmp community public rw"))

    # Regression tests for the gaps found in the 2026-11-21 audit
    def test_names_with_underscores_and_prefixes(self):
        for text, secret in (("db_password=Sup3rS3cret", "Sup3rS3cret"),
                             ("client_secret: abc123def", "abc123def"),
                             ("AWS_SECRET_ACCESS_KEY=AKIAEXAMPLE0000XXXX", "AKIAEXAMPLE0000XXXX"),
                             ("ssh_key=AAAAB3NzaC1yc2E", "AAAAB3NzaC1yc2E"),
                             ("pre-shared-key MiClaveVPN2026", "MiClaveVPN2026")):
            self.assertNotIn(secret, common.mask_secrets(text), text)

    def test_cisco_typed_secrets_hide_the_hash_not_the_type(self):
        for text, secret in (("enable secret 5 $1$mERr$hx5rVt7rPNoS4wqbXKX7m0", "$1$mERr$hx5rVt7rPNoS4wqbXKX7m0"),
                             ("username admin privilege 15 secret 9 $9$abcDEF123", "$9$abcDEF123"),
                             ("password 7 0822455D0A16", "0822455D0A16")):
            out = common.mask_secrets(text)
            self.assertNotIn(secret, out, text)
            self.assertIn("<SECRET>", out, text)

    def test_quoted_values_with_spaces(self):
        out = common.mask_secrets('password: "mi frase larga con espacios"')
        self.assertNotIn("frase", out)
        self.assertEqual(out, 'password: "<SECRET>"')

    def test_bearer_basic_url_credentials_and_tokens(self):
        for text, secret in (("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def", "eyJhbGci"),
                             # built in parts so secret scanners do not flag this fake value
                             ("curl -H 'Authorization: Basic " + "dXNlcjpw" + "YXNzd29yZA==" + "'", "dXNlcjpw"),
                             ("url = https://admin:S3cretPw@10.1.1.1/api", "S3cretPw"),
                             ("token=ghp_" + "a" * 36, "ghp_aaaa")):
            self.assertNotIn(secret, common.mask_secrets(text), text)

    def test_pem_block_is_masked(self):
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAK\n-----END RSA PRIVATE KEY-----"
        self.assertEqual(common.mask_secrets("before\n" + pem + "\nafter"), "before\n<SECRET>\nafter")

    def test_a_fake_placeholder_is_not_trusted(self):
        # only our own placeholders are skipped; a value in angle brackets is still a secret
        self.assertNotIn("hunter2", common.mask_secrets("password <hunter2>"))

    def test_normal_text_is_left_alone(self):
        for text in ("interface GE3", "ntp server 10.0.0.1", "hostname edge-bcn", "monkey=banana",
                     "keyboard layout us", "description WAN-MPLS", "username: admin", "primary_key id",
                     "firewall rule 10 allow tcp any 10.0.0.0/8 port 443"):
            self.assertEqual(common.mask_secrets(text), text)

    def test_masking_is_idempotent(self):
        once = common.mask_secrets("password=hunter2 and enable secret 5 $1$abc$def")
        self.assertEqual(common.mask_secrets(once), once)

    def test_anonymize(self):
        out = common.anonymize("from 10.1.1.2/30 by a@b.com mac aa:bb:cc:dd:ee:ff")
        self.assertEqual(out, "from <IP> by <EMAIL> mac <MAC>")


class SecondAudit(unittest.TestCase):
    """Regression tests for the second 2026-11-21 audit. Exact output, so a mask that eats text it
    should keep (such as the `=` or the rest of a log line) also fails."""

    EXACT = (
        ("password = my long pass phrase", "password = <SECRET>"),
        ("password=abc user=bob", "password=<SECRET> user=bob"),
        ("2026-11-21 ERROR login failed user=bob password=hunter2xx from 10.0.0.5",
         "2026-11-21 ERROR login failed user=bob password=<SECRET> from 10.0.0.5"),
        ("  db_password: another secret phrase", "  db_password: <SECRET>"),
        ("- password: phrase in a yaml list", "- password: <SECRET>"),
        ("password:\n  onTheNextLine", "password:\n  <SECRET>"),
        ('{"password": "a\\"b\\"c"}', '{"password": "<SECRET>"}'),
        ('signingKey: "k3y-SUPER"', 'signingKey: "<SECRET>"'),
        ("hmacKey=abcdef123", "hmacKey=<SECRET>"),
        ("sessionKey = ZZZ999", "sessionKey = <SECRET>"),
        ("pw=abc999 user=bob", "pw=<SECRET> user=bob"),
        ("cookie=SESSION123456", "cookie=<SECRET>"),
        ('clave = "ZZZ-fake"', 'clave = "<SECRET>"'),
        ("contraseña: hunter2xx", "contraseña: <SECRET>"),
        ("wpa-psk ascii 7 0822455D0A16544541", "wpa-psk ascii 7 <SECRET>"),
        ("postgres://admin:p@ss@db.internal:5432/x", "postgres://admin:<SECRET>@db.internal:5432/x"),
        ("radius-server key MyRadiusKey", "radius-server key <SECRET>"),
        # built in parts so secret scanners do not join it with the PEM test above
        ("-----BEGIN PGP PRIVATE KEY" + " BLOCK-----\nl1\nl2\n-----END PGP PRIVATE " + "KEY" + " BLOCK-----",
         "<SECRET>"),
    )

    def test_exact_output(self):
        for text, expected in self.EXACT:
            self.assertEqual(common.mask_secrets(text), expected, text)

    def test_tokens_with_no_name_in_front(self):
        # every fake token is built in parts so secret scanners do not flag the test file
        for token in ("github" + "_pat_" + "1" * 30, "gl" + "pat-" + "a" * 24, "sk-" + "proj-" + "a" * 36,
                      "rk" + "_live_" + "a" * 24, "AI" + "za" + "b" * 35, "hf" + "_" + "c" * 34,
                      "re" + "_AbCdEfGh_" + "d" * 24, "apify" + "_api_" + "e" * 24, "sb" + "_secret_" + "f" * 24,
                      "npm" + "_" + "g" * 36):
            self.assertEqual(common.mask_secrets("x " + token + " y"), "x <SECRET> y", token)

    def test_ordinary_sentences_are_left_alone(self):
        for text in ("pass the ball to me", "la clave de acceso es importante", "sig mismatch",
                     "foreign_key: user_id", "api_key: <SECRET>"):
            self.assertEqual(common.mask_secrets(text), text)

    def test_long_lines_stay_fast(self):
        import time
        for line in ("a." * 100000, "x-" * 100000, "key-" * 50000, "https://u:" + "p@" * 50000 + "host/x",
                     "password " * 22000):
            start = time.time()
            common.mask_secrets(line)
            self.assertLess(time.time() - start, 5, line[:20])


class ConfigPairMasking(unittest.TestCase):
    def test_placeholders_are_consistent_and_changes_visible(self):
        a = "ip address 10.0.0.1\nntp 10.0.0.9\nsnmp community s3cret ro\n"
        b = "ip address 10.0.0.2\nntp 10.0.0.9\nsnmp community public rw\n"
        a2, b2, mapping = mask_pair(a, b, anonymize=True)
        self.assertNotIn("10.0.0.1", a2 + b2)
        self.assertNotIn("s3cret", a2 + b2)
        # unchanged NTP server keeps the same placeholder in both files
        self.assertEqual(a2.splitlines()[1], b2.splitlines()[1])
        # changed IP gets a different placeholder, so the diff still shows it
        self.assertNotEqual(a2.splitlines()[0], b2.splitlines()[0])
        self.assertIn("<WEAK_SECRET_1>", b2)
        self.assertEqual(mapping["<SECRET_1>"], "s3cret")


class PersonalMasking(unittest.TestCase):
    def test_identifiers_masked(self):
        text = ("NIE X1234567L DNI 87654321X IBAN ES91 2100 0418 4502 0005 1332 "
                "card 4111 1111 1111 1111 ssn 123-45-6789 tel +34 612 345 678 and 612345678 mail j@x.com")
        out = mask_personal(text)
        for value in ("X1234567L", "87654321X", "ES91", "4111", "123-45-6789", "612", "j@x.com"):
            self.assertNotIn(value, out)

    def test_amounts_and_dates_untouched(self):
        for text in ("Total 29,900000 EUR/kW", "Price 12,9900 c/kWh", "Date 16/10/2026", "page 5",
                     "CUPS ES0031405447429023GB0F"):
            self.assertEqual(mask_personal(text), text)


class PersonalFormats(unittest.TestCase):
    """Regression tests for the gaps found in the 2026-11-21 audit (phones and ID formats)."""

    def check(self, texts, secret_parts):
        for text in texts:
            out = mask_personal(text)
            for part in secret_parts:
                self.assertNotIn(part, out, text)

    def test_spanish_dni_formats(self):
        self.check(["DNI 12345678Z", "DNI 12.345.678-Z", "DNI 12345678 z", "DNI 12.345.678 Z", "dni 12345678-Z"],
                   ["12345678", "12.345.678", "345.678"])

    def test_spanish_nie_formats(self):
        self.check(["NIE X1234567L", "NIE X-1234567-L", "NIE x1234567l", "NIE X 1234567 L"], ["1234567"])

    def test_a_mistyped_contiguous_id_is_still_masked(self):
        self.assertNotIn("1234567A", mask_personal("NIE X1234567A"))

    def test_iban_any_country_with_or_without_spaces(self):
        self.check(["IBAN ES91 2100 0418 4502 0005 1332", "iban ES9121000418450200051332",
                    "IBAN GB82 WEST 1234 5698 7654 32"], ["2100", "WEST", "4502"])
        self.assertEqual(mask_personal("cuenta es91 2100 0418 4502 0005 1332 para el recibo"),
                         "cuenta <IBAN> para el recibo")

    def test_cards_including_amex(self):
        self.check(["tarjeta 4111 1111 1111 1111", "amex 3782 822463 10005", "visa 4111-1111-1111-1111"],
                   ["4111", "3782", "822463"])

    def test_spanish_phone_formats(self):
        self.check(["tel 612345678", "tel 612 345 678", "tel 612 34 56 78", "tel 612-345-678", "tel 612.345.678",
                    "tel 91 234 56 78", "tel +34 612 345 678", "tel 0034 612345678", "tel (+34) 612 345 678"],
                   ["612", "345", "91 234"])

    def test_international_phone(self):
        self.assertNotIn("7946", mask_personal("tel +44 20 7946 0958"))

    def test_numbers_and_codes_that_are_not_personal_stay(self):
        for text in ("CUPS ES0031405447429023GB0F", "Total 29,900000 EUR/kW", "Referencia 9424410DF2892C0018HL",
                     "Fecha 16/10/2026", "Importe 1.234.567,89 EUR", "Importe 600.000,00 EUR",
                     "Plazo 2026-11-20 10:01:22", "Pagos 4 de 12 meses", "Total 123456789012 euros"):
            self.assertEqual(mask_personal(text), text)


class Costs(unittest.TestCase):
    def test_cost(self):
        self.assertAlmostEqual(common.cost("haiku", 1_000_000, 1_000_000), 0.60)


if __name__ == "__main__":
    unittest.main()
