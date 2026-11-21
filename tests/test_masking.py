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


class Costs(unittest.TestCase):
    def test_cost(self):
        self.assertAlmostEqual(common.cost("haiku", 1_000_000, 1_000_000), 0.60)


if __name__ == "__main__":
    unittest.main()
