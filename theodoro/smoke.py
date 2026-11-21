"""Exercise the distributed full Chromium with the application's browser controller."""
import json
import sys
from pathlib import Path
from threading import Event
from traceback import format_exc

from .browser import Browser


def smoke_test(report_path):
    browser = Browser(Event(), headless=True)
    result = {'status': 'failed'}
    try:
        try:
            page = browser.page('ifood', demo=True)
            if page.title() != 'iFood fictício':
                raise RuntimeError('A página de demonstração não foi carregada.')
            executable = browser.executable
            if getattr(sys, 'frozen', False):
                executable = executable.relative_to(Path(sys._MEIPASS).resolve())
            result = {'status': 'passed', 'chromium': str(executable), 'page': page.title()}
        finally:
            browser.close()
    except Exception:
        result = {'status': 'failed', 'diagnostic': format_exc()}
    Path(report_path).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return int(result['status'] != 'passed')
