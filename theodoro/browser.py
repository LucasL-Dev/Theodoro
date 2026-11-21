import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Error, sync_playwright

from .daily import DailySummary, LABELS, format_amount

ASSETS = Path(__file__).with_name('assets')
URLS = {
    'ifood': 'https://portal.ifood.com.br/',
    'premier': 'https://inside.premierdelivery.com.br/login',
}


class Interrupted(Exception):
    pass


class ChromiumUnavailable(Exception):
    pass


def chromium_executable(default, bundled_root, override):
    path = Path(default if bundled_root or not override else override).resolve()
    if bundled_root:
        if not path.is_relative_to(bundled_root) or not path.is_file():
            raise ChromiumUnavailable(
                'Chromium não encontrado na distribuição. Extraia o ZIP completo e mantenha '
                'a pasta _internal/browsers na distribuição.'
            )
    elif not path.is_file():
        raise ChromiumUnavailable(
            'Executável do Chromium não encontrado. Confira THEODORO_CHROMIUM '
            'ou instale o Chromium do Playwright no ambiente de desenvolvimento.'
        )
    return path


class Browser:
    def __init__(self, stop, *, headless=False):
        self.stop = stop
        self.headless = headless
        self.playwright = None
        self.context = None
        self.pages = {}
        self.prepared = None
        self.executable = None

    def start(self):
        if self.context is not None:
            return

        bundled_root = None
        if getattr(sys, 'frozen', False):
            bundled_root = (Path(sys._MEIPASS) / 'browsers').resolve()
            os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(bundled_root)
        try:
            self.playwright = sync_playwright().start()
            chromium = self.playwright.chromium
            self.executable = chromium_executable(
                chromium.executable_path, bundled_root, os.environ.get('THEODORO_CHROMIUM'),
            )
            # Pass the full browser explicitly so even headless checks use the shipped executable.
            browser = chromium.launch(
                headless=self.headless, executable_path=str(self.executable), timeout=15000,
            )
            self.context = browser.new_context(accept_downloads=False)
            self.context.set_default_timeout(5000)
        except Error as error:
            self.close()
            raise ChromiumUnavailable(
                'O Chromium não conseguiu iniciar. Confira se o pacote foi extraído por completo '
                'e se o Windows permite executar os arquivos da distribuição.'
            ) from error
        except Exception:
            self.close()
            raise

    def check(self):
        if self.stop.is_set():
            raise Interrupted

    def page(self, portal, demo):
        self.check()
        self.start()
        key = (portal, demo)
        previous = self.pages.get(key)
        if previous is not None and not previous.is_closed() and not demo:
            return previous
        if previous is not None and not previous.is_closed():
            previous.close()
        page = self.context.new_page()
        self.pages[key] = page
        if demo:
            page.route('**/*', lambda route: route.abort())
            page.set_content((ASSETS / f'{portal}.html').read_text(encoding='utf-8'))
        else:
            page.goto(URLS[portal], wait_until='domcontentloaded', timeout=15000)
        return page

    def control(self, page, selector):
        self.check()
        return page.locator(selector)

    def inspect(self, portal):
        self.page(portal, False).pause()

    def connect(self, portal, profile, credentials=None):
        page = self.page(portal, False)
        if credentials:
            spec = profile[portal]
            login = spec['login']
            self.check_origin(page, portal)
            self.control(page, login['email']).fill(credentials[0])
            self.control(page, login['password']).fill(credentials[1])
            self.control(page, login['submit']).click()
        if not profile or not profile[portal].get('ready'):
            return False
        self.check_origin(page, portal)
        return self.control(page, profile[portal]['ready']).is_visible()

    @staticmethod
    def check_origin(page, portal):
        current = urlsplit(page.url)
        expected = urlsplit(URLS[portal])
        if (current.scheme, current.netloc) != (expected.scheme, expected.netloc):
            raise ValueError('A página atual está fora do domínio esperado. Revise a sessão.')

    def prepare(self, day, demo, profile_path, progress):
        self.prepared = None
        if not demo and not profile_path:
            raise ValueError('Selecione um perfil local verificado antes de ler os portais reais.')
        path = ASSETS / 'profile.demo.json' if demo else profile_path
        profile = json.loads(Path(path).read_text(encoding='utf-8'))
        for portal, step in (('ifood', 20), ('premier', 65)):
            progress(step, f'Abrindo área financeira de {portal}')
            page = self.page(portal, demo)
            spec = profile[portal]
            if not demo and not self.connect(portal, profile):
                raise ValueError('Confirme a autenticação no navegador e verifique o perfil local.')
            for selector in spec['open']:
                if not demo:
                    self.check_origin(page, portal)
                self.control(page, selector).click()
            if not demo:
                self.check_origin(page, portal)
            if portal == 'ifood':
                self.control(page, spec['sale_date']).fill(day)
                self.control(page, spec['receipt_date']).fill(day)
                self.control(page, spec['query']).click()
                for field in ('confirmed_sale_date', 'confirmed_receipt_date'):
                    if self.control(page, spec[field]).inner_text().strip() != day:
                        raise ValueError('A data exibida pelo iFood difere da data selecionada.')
                values = {
                    key: self.control(page, spec['totals'][key]).inner_text().strip()
                    for key in LABELS
                }
                summary = DailySummary.parse(
                    day, values, spec.get('fee_sign', 1), spec.get('adjustment_sign', 1),
                )
            else:
                if not demo:
                    if spec.get('allow_unsaved_fill') is not True:
                        progress(100, 'Resumo pronto. Perfil sem autorização de preenchimento.')
                        break
                    self.fill_preview(page, spec['fields'], summary)
                    progress(100, 'Prévia preenchida. Gravação real desabilitada.')
                    break
                selectors, expected = self.fill_preview(page, spec['fields'], summary)
                self.prepared = (page, selectors, expected)
                progress(90, 'Formulário fictício preenchido. Aguardando aprovação.')
        return summary

    def fill_preview(self, page, fields, summary):
        values = {field: format_amount(getattr(summary, field)) for field in LABELS}
        values.update(sale_date=summary.day, receipt_date=summary.day)
        if not fields or set(fields) - values.keys() or len(set(fields.values())) != len(fields):
            raise ValueError('Os campos do formulário precisam de um mapeamento sem duplicidades.')
        selectors, expected = tuple(fields.values()), [values[field] for field in fields]
        for selector, value in zip(selectors, expected, strict=True):
            if page.url != 'about:blank':
                self.check_origin(page, 'premier')
            control = self.control(page, selector)
            control.fill(value)
            if control.input_value() != value:
                raise ValueError('O formulário diverge do resumo financeiro.')
        return selectors, expected

    def save_demo(self):
        self.check()
        if self.prepared is None:
            raise ValueError('Não há formulário de teste aguardando aprovação.')
        page, selectors, expected = self.prepared
        self.prepared = None
        if [self.control(page, selector).input_value() for selector in selectors] != expected:
            raise ValueError('O formulário foi alterado após a prévia.')
        button = self.control(page, '#save')
        button.evaluate('button => { button.disabled = false; }')
        button.click()
        button.evaluate('button => { button.disabled = true; }')
        result = self.control(page, '#receipt')
        result.wait_for(state='visible')
        if json.loads(result.inner_text()) != expected:
            raise ValueError('Os valores salvos divergem da prévia.')
        return expected

    def close(self):
        self.context = None
        self.pages.clear()
        self.prepared = None
        if self.playwright:
            try:
                self.playwright.stop()
            finally:
                self.playwright = None
