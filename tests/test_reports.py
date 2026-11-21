import os
import unittest
from pathlib import Path
from threading import Event

from theodoro.reports import cents, detect_columns, detect_header, read_file, summarize

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'


class ReportTests(unittest.TestCase):
    def load(self, suffix='csv'):
        sheets, rows, fingerprint = read_file(EXAMPLES / f'ifood-financeiro.{suffix}')
        self.assertEqual(len(fingerprint), 64)
        header = detect_header(rows)
        self.assertEqual(header, 1)
        return sheets, rows, header, detect_columns(rows[header])

    def test_csv_and_xlsx_produce_the_same_totals(self):
        results = []
        for suffix in ('csv', 'xlsx'):
            sheets, rows, header, mapping = self.load(suffix)
            if suffix == 'xlsx':
                self.assertEqual(sheets, ['Financeiro', 'Sobre'])
                self.assertEqual(read_file(EXAMPLES / 'ifood-financeiro.xlsx', 'Sobre')[1], [('Relatório fictício',)])
            daily, errors, controls = summarize(rows, header, mapping, 'sale_date', ',', 1, 1)
            self.assertFalse(errors)
            self.assertEqual(len(controls), 5)
            results.append(daily)
        self.assertEqual(*results)
        store = results[0][0]
        self.assertEqual((store['gross'], store['net'], store['payout']), (15000, 13000, 8000))
        self.assertEqual(store['competence_date'], '2026-11-21')

    def test_competence_and_payout_do_not_mix(self):
        _, rows, header, mapping = self.load()
        daily, errors, _ = summarize(rows, header, mapping, 'competence_date', ',', 1, 1)
        self.assertFalse(errors)
        self.assertEqual((daily[0]['net'], daily[0]['payout']), (None, 8000))
        self.assertEqual((daily[1]['net'], daily[1]['payout']), (13000, None))

    def test_duplicate_and_control_mismatch(self):
        _, rows, header, mapping = self.load()
        modified = list(rows)
        modified.insert(3, rows[2])
        modified[-1] = (*rows[-1][:-1], '100,00')
        _, errors, _ = summarize(modified, header, mapping, 'sale_date', ',', 1, 1)
        self.assertTrue(any('duplicidade' in error for error in errors))
        self.assertTrue(any('controle divergente' in error for error in errors))

    def test_missing_money_and_invalid_dates(self):
        rows = [('qualquer', 'data customizada', 'valor customizado'), ('loja', '2026-11-20', '1.234,56'),
                ('loja', '31/02/2026', '10,00')]
        mapping = {'store': 0, 'sale_date': 1, 'gross': 2}
        daily, errors, _ = summarize(rows, 0, mapping, 'sale_date', ',', 1, 1)
        self.assertEqual(daily[0]['gross'], 123456)
        self.assertIsNone(daily[0]['net'])
        self.assertEqual(len(errors), 1)
        with self.assertRaisesRegex(ValueError, 'data'):
            summarize(rows, 0, {'store': 0, 'gross': 2}, 'sale_date', ',', 1, 1)
        self.assertEqual(cents('(R$ 1.234,56)', ','), -123456)
        with self.assertRaises(ValueError):
            cents('1,005', ',')

    @unittest.skipUnless(os.environ.get('THEODORO_BROWSER_TEST') == '1', 'Requer Chromium')
    def test_imported_summary_fills_premier_demo_without_save(self):
        from theodoro.browser import Browser
        _, rows, header, mapping = self.load()
        daily, _, _ = summarize(rows, header, mapping, 'sale_date', ',', 1, 1)
        browser = Browser(Event(), headless=True)
        self.addCleanup(browser.close)
        spec = {
            'ready': 'h1', 'open': ['#finance'], 'form': 'form', 'allow_unsaved_fill': True,
            'fields': {'sale_date': '#sale-date', 'receipt_date': '#receipt-date',
                       'net': '#net', 'payout': '#payout'},
        }
        browser.premier_preview(daily[0], spec, demo=True)
        page = browser.configuration_page('premier', True)
        self.assertEqual(page.locator('#net').input_value(), '130,00')
        self.assertEqual(page.locator('#payout').input_value(), '80,00')
        self.assertFalse(page.locator('#receipt').is_visible())
        self.assertIsNone(browser.prepared)
        with self.assertRaisesRegex(ValueError, 'indisponíveis'):
            browser.premier_preview(daily[1], spec, demo=True)
