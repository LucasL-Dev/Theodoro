import os
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from theodoro.browser import Browser
from theodoro.session_profile import protected_profile


class SessionTests(unittest.TestCase):
    def test_profiles_are_isolated_by_browser(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'sessions'
            chrome = protected_profile(root, 'chrome')
            edge = protected_profile(root, 'msedge')
            self.assertNotEqual(chrome, edge)
            with self.assertRaises(ValueError):
                protected_profile(root, '../personal')
            if os.name != 'nt':
                self.assertEqual(chrome.stat().st_mode & 0o777, 0o700)
                self.assertEqual(root.stat().st_mode & 0o777, 0o700)

    @unittest.skipUnless(os.environ.get('THEODORO_BROWSER_TEST') == '1', 'Requer Chromium')
    def test_premier_requires_the_authenticated_marker(self):
        browser = Browser(Event(), headless=True)
        self.addCleanup(browser.close)
        page = browser.page('premier', True)
        with patch.object(browser, 'configuration_page', return_value=page), patch.object(browser, 'check_origin'):
            self.assertTrue(browser.premier_session('h1')['ready'])
            status = browser.premier_session(None)
            self.assertFalse(status['ready'])
            self.assertIn('login manualmente', status['message'])
            with patch.object(browser, 'premier_session', return_value=status):
                with self.assertRaisesRegex(ValueError, 'login manualmente'):
                    browser.premier_preview(
                        {'net': 100}, {'ready': 'h1', 'form': 'form', 'fields': {'net': '#net'},
                                       'allow_unsaved_fill': True},
                    )
            self.assertEqual(page.locator('#net').input_value(), '')

    @unittest.skipUnless(os.environ.get('THEODORO_BROWSER_TEST') == '1', 'Requer Chromium')
    def test_persistent_cookie_survives_clean_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'sessions'
            original = Browser(Event(), headless=True, profile_root=root)
            try:
                self.assertTrue(original.diagnose())
                original.context.add_cookies([{
                    'name': 'sessao_ficticia', 'value': 'confirmada',
                    'url': 'https://example.test/', 'expires': int(time.time()) + 300,
                }])
            finally:
                original.close()
            reopened = Browser(Event(), headless=True, profile_root=root)
            try:
                self.assertTrue(reopened.diagnose())
                self.assertEqual(reopened.context.cookies('https://example.test/')[0]['value'], 'confirmada')
            finally:
                reopened.close()
