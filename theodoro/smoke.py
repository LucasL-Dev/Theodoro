"""Exercise the distributed full Chromium with the application's browser controller."""
import json
import sys
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import time
from traceback import format_exc

from openpyxl import Workbook, load_workbook

from .browser import Browser
from .browser_choices import installed_channel
from .browser_ui_smoke import verify_worker_browser
from .window_smoke import verify_open_chrome


def check_persistent_session(channel):
    # Use only disposable application-owned profiles and a synthetic cookie.
    with TemporaryDirectory() as temporary:
        root = Path(temporary) / 'sessions'
        browser = Browser(Event(), headless=True, choice=channel, profile_root=root)
        try:
            version = browser.diagnose()
            browser.context.add_cookies([{
                'name': 'theodoro_test', 'value': 'session', 'url': 'https://example.test/',
                'expires': int(time()) + 300,
            }])
        finally:
            browser.close()
        restarted = Browser(Event(), headless=True, choice=channel, profile_root=root)
        try:
            restarted.start()
            if not any(cookie['name'] == 'theodoro_test' and cookie['value'] == 'session'
                       for cookie in restarted.context.cookies('https://example.test/')):
                raise RuntimeError(f'A sessão fictícia de {channel} não persistiu.')
        finally:
            restarted.close()
    return {'status': 'passed', 'versao': version, 'sessao_persistente': 'passed'}


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
        for channel in ('chromium', 'chrome', 'msedge'):
            if channel != 'chromium' and not installed_channel(channel):
                result['navegadores'][channel] = {'status': 'indisponível'}
                continue
            result['navegadores'][channel] = check_persistent_session(channel)
        if sys.platform == 'win32' and installed_channel('chrome'):
            verify_worker_browser('chrome', headless=False)
            result['chrome_janela_apos_retorno_qt'] = 'passed'
            verify_open_chrome()
            result['chrome_janela_externa_uia'] = 'passed'
        else:
            result['chrome_janela_apos_retorno_qt'] = 'indisponível'
            result['chrome_janela_externa_uia'] = 'indisponível'
    except Exception:
        result = {'status': 'failed', 'diagnostic': format_exc()}
    Path(report_path).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return int(result['status'] != 'passed')
