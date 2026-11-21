"""Exercise the distributed full Chromium with the application's browser controller."""
import json
import sys
from io import BytesIO
from pathlib import Path
from threading import Event
from traceback import format_exc

from openpyxl import Workbook, load_workbook

from .browser import Browser
from .browser_choices import installed_channel


def smoke_test(report_path):
    browser = Browser(Event(), headless=True)
    result = {'status': 'failed'}
    try:
        try:
            version = browser.diagnose()
            page = browser.page('ifood', demo=True)
            if page.title() != 'iFood fictício':
                raise RuntimeError('A página de demonstração não foi carregada.')
            executable = browser.executable
            if getattr(sys, 'frozen', False):
                executable = executable.relative_to(Path(sys._MEIPASS).resolve())
            workbook = Workbook()
            workbook.active.append(['Estabelecimento', 'Vendas brutas'])
            spreadsheet = BytesIO()
            workbook.save(spreadsheet)
            loaded = load_workbook(spreadsheet, read_only=True)
            try:
                if next(loaded.active.values) != ('Estabelecimento', 'Vendas brutas'):
                    raise RuntimeError('Não foi possível conferir o suporte a XLSX no pacote.')
            finally:
                loaded.close()
            result = {'status': 'passed', 'chromium': str(executable), 'page': page.title(), 'xlsx': 'passed',
                      'navegadores': {'chromium': {'status': 'passed', 'versao': version}}}
        finally:
            browser.close()
        for channel in ('chrome', 'msedge'):
            if not installed_channel(channel):
                result['navegadores'][channel] = {'status': 'indisponível'}
                continue
            candidate = Browser(Event(), headless=True, choice=channel)
            try:
                result['navegadores'][channel] = {'status': 'passed', 'versao': candidate.diagnose()}
            finally:
                candidate.close()
    except Exception:
        result = {'status': 'failed', 'diagnostic': format_exc()}
    Path(report_path).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return int(result['status'] != 'passed')
