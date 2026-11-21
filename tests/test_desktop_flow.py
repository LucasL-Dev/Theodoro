import os
import unittest
from threading import Event

from theodoro.daily import DailySummary


VALUES = {'gross': '100,00', 'fees': '-12,50', 'adjustments': '-2,50',
          'net': '85,00', 'payout': '80,00'}


class DailySummaryTests(unittest.TestCase):
    def test_payout_is_separate_from_net(self):
        summary = DailySummary.parse('2026-11-21', VALUES)
        self.assertEqual(summary.net, 8500)
        self.assertEqual(summary.payout, 8000)

    def test_inconsistent_net_is_rejected(self):
        with self.assertRaises(ValueError):
            DailySummary.parse('2026-11-21', dict(VALUES, net='84,99'))


@unittest.skipUnless(os.environ.get('THEODORO_BROWSER_TEST') == '1', 'Requer Chromium')
class BrowserTests(unittest.TestCase):
    def setUp(self):
        from theodoro.browser import Browser
        self.stop = Event()
        self.browser = Browser(self.stop, headless=True)
        self.addCleanup(self.browser.close)

    def test_demo_uses_browser_for_query_preview_and_receipt(self):
        summary = self.browser.prepare('2026-11-21', True, None, lambda *_: None)
        self.assertEqual(summary.payout, 8000)
        expected = ['2026-11-21', '2026-11-21', '85,00', '80,00']
        page = self.browser.pages[('premier', True)]
        self.assertFalse(page.locator('#receipt').is_visible())
        self.assertEqual(self.browser.save_demo(), expected)
        self.assertTrue(page.locator('#receipt').is_visible())

    def test_changed_form_cannot_be_saved(self):
        self.browser.prepare('2026-11-21', True, None, lambda *_: None)
        page = self.browser.pages[('premier', True)]
        page.locator('#payout').fill('1,00')
        with self.assertRaises(ValueError):
            self.browser.save_demo()
        self.assertFalse(page.locator('#receipt').is_visible())


@unittest.skipUnless(os.environ.get('THEODORO_BROWSER_TEST') == '1', 'Requer Chromium e PySide6')
class DesktopTests(unittest.TestCase):
    def test_approval_survives_separate_worker_commands(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QMessageBox
        from theodoro.desktop import Window

        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as temp:
            window = Window(Path(temp) / 'history.sqlite')
            window.worker.browser.headless = True
            poll = QTimer(window)
            timeout = QTimer(window)
            timeout.setSingleShot(True)

            def advance():
                if window.busy:
                    return
                if window.pending:
                    window.approve_test()
                else:
                    app.quit()

            poll.timeout.connect(advance)
            timeout.timeout.connect(app.quit)
            try:
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                    window.start()
                    poll.start(50)
                    timeout.start(20000)
                    app.exec()
                self.assertIn('80,00', window.preview.toPlainText())
                self.assertEqual(window.history.runs()[0].get('status'), 'confirmed')
            finally:
                window.close()
