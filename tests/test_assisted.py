import json
import os
import tempfile
import unittest
from pathlib import Path
from threading import Event

from theodoro.assisted import save_profile, set_step


@unittest.skipUnless(os.environ.get('THEODORO_BROWSER_TEST') == '1', 'Requer Chromium')
class AssistedTests(unittest.TestCase):
    def test_capture_persist_replay_and_reject_wrong_store(self):
        from theodoro.browser import Browser

        browser = Browser(Event(), headless=True)
        self.addCleanup(browser.close)
        profile = {}
        for portal in ('ifood', 'premier'):
            page = browser.configuration_page(portal, True)

            def pick(key, target):
                page.evaluate(
                    'selector => setTimeout(() => document.querySelector(selector).click(), 150)', target,
                )
                selector, digest = browser.capture(portal, True, key, timeout=3)
                set_step(profile, portal, key, selector, digest)
                self.assertEqual(page.locator(selector).count(), 1)

            pick('ready', 'h1')
            pick('open', '#finance')
            page.click('#finance')
            if portal == 'ifood':
                for key, selector in {
                    'store': '#store', 'sale_date': '#sales', 'receipt_date': '#received',
                    'query': '#query',
                }.items():
                    pick(key, selector)
                page.fill('#sales', '2026-11-21')
                page.fill('#received', '2026-11-21')
                page.click('#query')
                for key, selector in {
                    'confirmed_sale_date': '#sales-result', 'confirmed_receipt_date': '#received-result',
                    'totals.gross': '#gross', 'totals.fees': '#fees', 'totals.adjustments': '#adjustments',
                    'totals.net': '#net', 'totals.payout': '#payout',
                }.items():
                    pick(key, selector)
            else:
                pick('form', 'form')
                for key, selector in {
                    'sale_date': '#sale-date', 'receipt_date': '#receipt-date',
                    'net': '#net', 'payout': '#payout',
                }.items():
                    pick(f'fields.{key}', selector)
                profile[portal]['allow_unsaved_fill'] = True
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'automation-demo.json'
            save_profile(path, profile)
            serialized = path.read_text(encoding='utf-8')
            self.assertNotIn('Loja de demonstração', serialized)
            self.assertNotIn('85,00', serialized)
            profile = json.loads(serialized)
        for portal in ('ifood', 'premier'):
            browser.page(portal, True)
        summary = browser.assisted_preview('2026-11-22', profile, lambda *_: None, demo=True)
        self.assertEqual((summary.net, summary.payout), (8500, 8000))
        premier = browser.configuration_page('premier', True)
        self.assertEqual(premier.locator('#payout').input_value(), '80,00')
        self.assertFalse(premier.locator('#receipt').is_visible())
        self.assertIsNone(browser.prepared)

        page = browser.configuration_page('ifood', True)
        page.locator('#store').select_option(index=1)
        with self.assertRaisesRegex(ValueError, 'estabelecimento diferente'):
            browser.assisted_preview('2026-11-22', profile, lambda *_: None, demo=True)
        profile['ifood']['open'][0] = '#missing'
        with self.assertRaisesRegex(ValueError, 'navegação 1'):
            browser.assisted_preview('2026-11-22', profile, lambda *_: None, demo=True)
