import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.dedup_seen import process

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/dedup_seen.py"


class LedgerTests(unittest.TestCase):
    def test_alias_chain_reaches_legacy_row(self):
        ledger = {"2501.12345": {"title": "Paper: Alpha"}}
        candidates = [{"title": "Other", "doi": "10.1234/ABC"},
                      {"url": "https://doi.org/10.1234/abc", "arxiv_id": "2501.12345v2"},
                      {"title": "ＰＡＰＥＲ alpha"}]
        self.assertEqual(process(ledger, candidates)["candidates"], [])

    def test_filter_record_roundtrip_and_retry(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "ledger.json"
            state.write_text('{"2301.12345":{"title":"Old","score":9}}')
            def run(op, items):
                return subprocess.run([sys.executable, str(SCRIPT), op, "--seen", str(state)],
                                      input=json.dumps(items), text=True, capture_output=True, check=True)
            rows = [{"title":"New", "url":"https://example.org/p?utm_source=test"},
                    {"title":"New", "doi":"10.1234/b"}]
            result = json.loads(run("filter",rows).stdout)
            self.assertEqual(result["stats"]["unseen"], 1)
            run("record", result)
            run("record", result)
            data = json.loads(state.read_text())
            self.assertEqual(data["2301.12345"]["score"], 9)
            self.assertEqual(len(data), 2)
            self.assertEqual(json.loads(run("filter",[{"doi":"10.1234/b"},{"url":"https://example.org/p"}]).stdout)["candidates"], [])

    def test_invalid_input_preserves_state(self):
        with self.assertRaises(ValueError):
            process({}, [{"abstract":"missing identity"}], True)
