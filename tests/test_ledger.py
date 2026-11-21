"""Offline tests for the spend ledger and the daily cap. No API calls and no network."""
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "offload-to-api" / "scripts"))

import common  # noqa: E402


class LedgerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = (common.HOME, common.LEDGER, common.DAILY_CAP_USD)
        common.HOME = Path(self._tmp.name)
        common.LEDGER = common.HOME / "usage.json"

    def tearDown(self):
        common.HOME, common.LEDGER, common.DAILY_CAP_USD = self._saved
        self._tmp.cleanup()


class LedgerFile(LedgerTestCase):
    def test_missing_ledger_counts_as_zero(self):
        self.assertEqual(common.spent_today(), 0.0)

    def test_spend_accumulates_and_leaves_no_temp_file(self):
        common.record_spend(0.25)
        common.record_spend(0.5)
        self.assertAlmostEqual(common.spent_today(), 0.75)
        self.assertEqual(sorted(p.name for p in common.HOME.iterdir() if p.name.startswith("usage.json")),
                         ["usage.json"])

    def test_a_corrupt_ledger_stops_the_tools_instead_of_resetting_the_cap(self):
        common.LEDGER.write_text("{not json")
        with self.assertRaises(SystemExit):
            common.spent_today()
        with self.assertRaises(SystemExit):
            common.record_spend(0.1)
        self.assertEqual(common.LEDGER.read_text(), "{not json")  # left untouched for the user to inspect

    def test_unexpected_content_also_fails_closed(self):
        for content in ('[1, 2]', '{"2026-01-01": "x"}', '{"2026-01-01": -1}', '{"2026-01-01": NaN}',
                        '{"2026-01-01": true}'):
            common.LEDGER.write_text(content)
            with self.assertRaises(SystemExit, msg=content):
                common.spent_today()

    def test_parallel_runs_do_not_lose_spend(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: common.record_spend(0.01), range(40)))
        self.assertAlmostEqual(common.spent_today(), 0.40, places=4)

    def test_old_days_are_dropped(self):
        common.LEDGER.write_text(json.dumps({"2000-01-01": 5.0}))
        common.record_spend(0.1)
        self.assertNotIn("2000-01-01", json.loads(common.LEDGER.read_text()))

    def test_a_bad_amount_never_reaches_the_file(self):
        common.record_spend(float("nan"))
        common.record_spend(-1.0)
        self.assertFalse(common.LEDGER.exists())


class EnvAmounts(unittest.TestCase):
    def check_rejected(self, value, **kwargs):
        with mock.patch.dict(os.environ, {"OFFLOAD_TEST_AMOUNT": value}):
            with self.assertRaises(SystemExit, msg=value):
                common._env_amount("OFFLOAD_TEST_AMOUNT", 2.0, **kwargs)

    def test_nan_inf_negative_zero_and_text_are_rejected(self):
        for value in ("nan", "inf", "-inf", "-1", "0", "abc"):
            self.check_rejected(value)

    def test_zero_is_allowed_only_when_asked(self):
        with mock.patch.dict(os.environ, {"OFFLOAD_TEST_AMOUNT": "0"}):
            self.assertEqual(common._env_amount("OFFLOAD_TEST_AMOUNT", 2.0, allow_zero=True), 0.0)

    def test_valid_value_and_default(self):
        with mock.patch.dict(os.environ, {"OFFLOAD_TEST_AMOUNT": "3.5"}):
            self.assertEqual(common._env_amount("OFFLOAD_TEST_AMOUNT", 2.0), 3.5)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OFFLOAD_TEST_AMOUNT", None)
            self.assertEqual(common._env_amount("OFFLOAD_TEST_AMOUNT", 2.0), 2.0)


class CallAndCap(LedgerTestCase):
    @staticmethod
    def fake_client(tokens_in=1000, tokens_out=500):
        response = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out),
            content=[SimpleNamespace(type="text", text="hello")], stop_reason="end_turn")
        return SimpleNamespace(messages=SimpleNamespace(create=mock.Mock(return_value=response)))

    def test_a_call_is_refused_before_it_could_pass_the_cap(self):
        common.DAILY_CAP_USD = 0.01
        common.record_spend(0.009)
        client = self.fake_client()
        with self.assertRaises(common.BudgetExceeded):
            common.call(client, "haiku", "hi", 100, reserve=0.005)
        client.messages.create.assert_not_called()

    def test_budget_exceeded_is_a_systemexit_so_untouched_tools_just_stop(self):
        self.assertTrue(issubclass(common.BudgetExceeded, SystemExit))

    def test_a_call_that_fits_is_made_and_recorded(self):
        common.DAILY_CAP_USD = 1.0
        client = self.fake_client(tokens_in=1_000_000, tokens_out=0)
        text, usd, stop = common.call(client, "haiku", "hi", 100)
        self.assertEqual((text, stop), ("hello", "end_turn"))
        self.assertAlmostEqual(usd, 0.10)
        self.assertAlmostEqual(common.spent_today(), 0.10)

    def test_without_a_reserve_the_worst_case_output_is_used(self):
        common.DAILY_CAP_USD = 0.0001
        client = self.fake_client()
        with self.assertRaises(common.BudgetExceeded):
            common.call(client, "opus", "hi", 8000)  # 8000 output tokens on opus cost far more than 0.0001
        client.messages.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
