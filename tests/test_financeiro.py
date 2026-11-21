import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from financeiro.mapping import load, money
from financeiro.sync import History

ROOT = Path(__file__).resolve().parents[1]


class Destination:
    def __init__(self, fail=False):
        self.rows = {}
        self.fail = fail

    def create(self, key, payload):
        self.rows[key] = (key, payload)
        if self.fail:
            raise TimeoutError
        return key

    def read(self, receipt):
        return self.rows[receipt]


class FinanceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'history.sqlite'
        self.history = History(self.path)
        self.entries, self.errors = load(
            ROOT / 'examples/report.csv', ROOT / 'examples/mapping.json',
            date(2026, 11, 1), date(2026, 11, 30),
        )

    def test_values_dates_and_persistent_history(self):
        self.assertEqual([entry.amount_cents for entry in self.entries], [10000, -1250, -250, 8500])
        self.assertEqual(self.entries[-1].reference_date, '2026-11-01')
        self.assertEqual(self.entries[-1].payout_date, '2026-11-07')
        self.assertEqual(self.errors, [])
        result = self.history.simulate(self.entries, self.errors)
        self.assertEqual(result['sent'], 0)
        self.assertEqual(len(History(self.path).runs()[0]['preview']), 4)

    def test_duplicate_and_conflicting_rows(self):
        entry = self.entries[0]
        duplicate = replace(entry)
        conflict = replace(entry, amount_cents=1)
        result = self.history.simulate([entry, duplicate, conflict], [])
        self.assertEqual(result['duplicates'], 1)
        self.assertEqual(result['preview'], [])
        self.assertEqual(result['review'], [entry.key])

    def test_money_rejects_ambiguous_values(self):
        for value in ('1.000,00', '1e2', '12,345', '0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                money(value, ',')

    def test_test_destination_requires_matching_approval_and_confirms(self):
        entry = self.entries[0]
        destination = Destination()
        with self.assertRaises(ValueError):
            self.history.send_to_test_destination(entry, destination, approved_payload='')
        self.assertEqual(destination.rows, {})
        result = self.history.send_to_test_destination(entry, destination, approved_payload=entry.payload())
        self.assertEqual(result, 'confirmed')
        result = History(self.path).send_to_test_destination(entry, destination, approved_payload=entry.payload())
        self.assertEqual(result, 'duplicate')

    def test_unknown_outcome_is_never_retried(self):
        entry = self.entries[0]
        first, second = Destination(fail=True), Destination()
        result = self.history.send_to_test_destination(entry, first, approved_payload=entry.payload())
        self.assertEqual(result, 'review')
        self.assertIn(entry.key, first.rows)
        result = History(self.path).send_to_test_destination(entry, second, approved_payload=entry.payload())
        self.assertEqual(result, 'review')
        self.assertEqual(second.rows, {})
