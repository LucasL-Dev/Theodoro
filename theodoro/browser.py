import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Error, TimeoutError, expect, sync_playwright

from .assisted import (PICK, SAFE_FIELD, SAFE_NAVIGATION, amount_text, display_value, named_step, store_digest, validate_profile)
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
        self.preview_pages = set()

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
            self.context = browser.new_context(accept_downloads=False, service_workers="block")
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
            if portal == 'premier':
                page.route('**/*', lambda route: (
                    route.abort() if page in self.preview_pages
                    and route.request.method not in {'GET', 'HEAD', 'OPTIONS'}
                    else route.continue_()
                ))

                def manage_socket(socket):
                    upstream = socket.connect_to_server()
                    socket.on_message(lambda message: (
                        upstream.send(message) if page not in self.preview_pages else None
                    ))

                page.route_web_socket('**/*', manage_socket)
                page.on('close', lambda _: self.preview_pages.discard(page))
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

    def configuration_page(self, portal, demo):
        key = (portal, demo)
        page = self.pages.get(key)
        if page is None or page.is_closed():
            page = self.page(portal, demo)
        page.bring_to_front()
        return page

    def capture(self, portal, demo, key, timeout=45):
        page = self.configuration_page(portal, demo)
        if not demo:
            self.check_origin(page, portal)
        page.evaluate(PICK)
        try:
            for _ in range(timeout):
                self.check()
                try:
                    page.wait_for_function('window.__theodoroSelection != null', timeout=1000)
                except TimeoutError:
                    continue
                selector = page.evaluate('window.__theodoroSelection')
                if not selector:
                    raise ValueError('Seleção cancelada ou controle de autenticação protegido.')
                if not demo:
                    self.check_origin(page, portal)
                return selector, self.test_selector(portal, demo, key, selector)
            raise ValueError('Nenhum controle selecionado. Tente capturar novamente.')
        finally:
            if not page.is_closed():
                try:
                    page.evaluate('window.__theodoroCancelPick?.()')
                except Error:
                    pass

    def test_selector(self, portal, demo, key, selector):
        page = self.configuration_page(portal, demo)
        if not demo:
            self.check_origin(page, portal)
        with named_step(f'{portal}: {key}'):
            control = self.control(page, selector)
            control.wait_for(state='visible')
            if key == 'open' and not control.evaluate(SAFE_NAVIGATION):
                raise ValueError('Selecione apenas um controle de navegação fora de formulários.')
            if (key.startswith('fields.') or key in {'sale_date', 'receipt_date'}) and not control.evaluate(SAFE_FIELD):
                raise ValueError('Selecione um campo editável comum, sem credenciais.')
            if key == 'store':
                value = display_value(control)
                if not value:
                    raise ValueError('O estabelecimento não está visível no controle escolhido.')
                return store_digest(value)
        return None

    def assisted_preview(self, day, profile, progress, *, demo=False):
        self.prepared = None
        validate_profile(profile)
        date_style = profile['ifood'].get('result_date_format', 'iso')
        expected_day = '/'.join(reversed(day.split('-'))) if date_style == 'br' else day
        portal = 'ifood'
        progress(20, 'Executando configuração de iFood')
        spec = profile[portal]
        page = self.configuration_page(portal, demo)

        def control(selector):
            if not demo:
                self.check_origin(page, portal)
            return self.control(page, selector)

        with named_step(f'{portal}: tela inicial autenticada'):
            expect(control(spec['ready'])).to_be_visible(timeout=5000)
        for index, selector in enumerate(spec['open'], 1):
            with named_step(f'{portal}: navegação {index}'):
                step = control(selector)
                if not step.evaluate(SAFE_NAVIGATION):
                    raise ValueError(f'{portal}: navegação {index} não é um controle seguro.')
                step.click()
        def verify_store():
            with named_step('iFood: estabelecimento'):
                if store_digest(display_value(control(spec['store']))) != spec['store_digest']:
                    raise ValueError('iFood: estabelecimento diferente do selecionado na configuração.')

        verify_store()
        for field, label in (('sale_date', 'vendas'), ('receipt_date', 'recebimentos')):
            with named_step(f'iFood: filtro da data de {label}'):
                date_field = control(spec[field])
                if not date_field.evaluate(SAFE_FIELD):
                    raise ValueError(f'iFood: filtro da data de {label} inválido.')
                value = day
                if date_field.get_attribute('type') != 'date' and spec.get('input_date_format') == 'br':
                    value = '/'.join(reversed(day.split('-')))
                date_field.fill(value)
                expect(date_field).to_have_value(value)
        with named_step('iFood: consultar'):
            control(spec['query']).click()
        for field, label in (('confirmed_sale_date', 'vendas'), ('confirmed_receipt_date', 'recebimentos')):
            with named_step(f'iFood: data de {label} no resultado'):
                expect(control(spec[field])).to_have_text(expected_day, timeout=10000)
        verify_store()
        values = {}
        for key, label in LABELS.items():
            with named_step(f'iFood: {label}'):
                value = control(spec['totals'][key])
                value.wait_for(state='visible')
                values[key] = amount_text(value.inner_text().strip())
        summary = DailySummary.parse(day, values, spec.get('fee_sign', 1), spec.get('adjustment_sign', 1))
        progress(65, 'Executando configuração do Premier')
        self.premier_preview(self.summary_values(summary), profile['premier'], demo)
        progress(100, 'Prévia conferida. Nenhum lançamento foi salvo.')
        return summary

    def premier_preview(self, values, spec, demo=False):
        self.prepared = None
        if not all(spec.get(key) for key in ('ready', 'form', 'fields')) or spec.get('allow_unsaved_fill') is not True:
            raise ValueError('Configure o formulário novo do Premier e confirme o preenchimento sem gravação.')
        self.check_values(spec['fields'], values)
        portal = 'premier'
        page = self.configuration_page(portal, demo)
        if not demo:
            self.preview_pages.add(page)
        def control(selector):
            if not demo:
                self.check_origin(page, portal)
            return self.control(page, selector)

        with named_step(f'{portal}: tela inicial autenticada'):
            expect(control(spec['ready'])).to_be_visible(timeout=5000)
        for index, selector in enumerate(spec.get('open', []), 1):
            with named_step(f'{portal}: navegação {index}'):
                step = control(selector)
                if not step.evaluate(SAFE_NAVIGATION):
                    raise ValueError(f'{portal}: navegação {index} não é um controle seguro.')
                step.click()
        with named_step('Premier: formulário financeiro'):
            expect(control(spec['form'])).to_be_visible(timeout=5000)
        form = control(spec['form'])
        with named_step('Premier: mapeamento do formulário'):
            if not form.evaluate(
                '(form, selectors) => selectors.every(selector => form.contains(document.querySelector(selector)))',
                list(spec['fields'].values()),
            ):
                raise ValueError('Premier: recapture os campos dentro do formulário configurado.')
        self.fill_values(page, spec['fields'], values, date_format=spec.get('input_date_format'), empty_only=not demo)
        with named_step('Premier: campos obrigatórios'):
            if not form.evaluate("""element =>
                [...element.querySelectorAll('input,select,textarea')]
                .every(field => !field.willValidate || field.validity.valid)"""):
                raise ValueError('Premier: o formulário tem campos obrigatórios vazios ou inválidos.')

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

    @staticmethod
    def summary_values(summary):
        values = {field: getattr(summary, field) for field in LABELS}
        return dict(values, sale_date=summary.day, receipt_date=summary.day)

    @staticmethod
    def check_values(fields, values):
        if not fields or set(fields) - values.keys() or len(set(fields.values())) != len(fields):
            raise ValueError('Os campos do formulário precisam de um mapeamento válido e sem duplicidades.')
        missing = [LABELS.get(key, key) for key in fields if values[key] is None]
        if missing:
            raise ValueError('Campos indisponíveis no resumo: ' + ', '.join(missing) + '.')

    def fill_preview(self, page, fields, summary, *, date_format=None):
        return self.fill_values(page, fields, self.summary_values(summary), date_format=date_format)

    def fill_values(self, page, fields, values, *, date_format=None, empty_only=False):
        self.check_values(fields, values)
        values = {key: format_amount(value) if key in LABELS and value is not None else value
                  for key, value in values.items()}
        selectors, expected = tuple(fields.values()), [values[field] for field in fields]
        for index, (field, selector) in enumerate(fields.items()):
            if page.url != 'about:blank':
                self.check_origin(page, 'premier')
            with named_step(f'Premier: {LABELS.get(field, field)}'):
                control = self.control(page, selector)
                if not control.evaluate(SAFE_FIELD):
                    raise ValueError(f'Premier: campo inválido para {LABELS.get(field, field)}.')
                input_type = control.get_attribute('type')
                if field.endswith('_date') and date_format == 'br' and input_type != 'date':
                    expected[index] = '/'.join(reversed(expected[index].split('-')))
                if field in LABELS and input_type == 'number':
                    expected[index] = expected[index].replace(',', '.')
                if empty_only and control.input_value() not in {'', expected[index]}:
                    raise ValueError(f'Premier: {LABELS.get(field, field)} já tem outro valor. Abra um formulário novo.')
        for selector, value in zip(selectors, expected, strict=True):
            with named_step('Premier: preenchimento'):
                control = self.control(page, selector)
                if page.url != 'about:blank':
                    self.check_origin(page, 'premier')
                if control.input_value() != value:
                    control.fill(value)
        for field, (selector, value) in zip(fields, zip(selectors, expected), strict=True):
            with named_step(f'Premier: conferência de {LABELS.get(field, field)}'):
                expect(self.control(page, selector)).to_have_value(value)
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
        self.preview_pages.clear()
        self.prepared = None
        if self.playwright:
            try:
                self.playwright.stop()
            finally:
                self.playwright = None
