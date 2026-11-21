"""Windows UI Automation adapter for an explicitly chosen Chrome window."""
import ctypes
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .browser_choices import channel_executable
from .daily import LABELS, format_amount

DEMO_PATH = Path(__file__).with_name('assets') / 'window_demo.html'
FIELDS = {
    'sale_date': 'Data da venda', 'competence_date': 'Data de competência',
    'receipt_date': 'Data de recebimento', **LABELS,
}
ADDRESS_NAMES = {
    'address and search bar', 'barra de endereço e pesquisa', 'barra de endereços e pesquisa',
}
ADDRESS_IDS = {'address and search bar', 'address edit', 'omnibox'}


def approved_address(address, demo):
    try:
        parsed = urlsplit(address)
        if demo:
            return (parsed.scheme == 'file' and not parsed.netloc and not parsed.query and not parsed.fragment
                    and unquote(parsed.path).replace('\\', '/').casefold()
                    == unquote(urlsplit(DEMO_PATH.resolve().as_uri()).path).casefold())
        return (parsed.scheme == 'https' and parsed.hostname == 'inside.premierdelivery.com.br'
                and parsed.port in {None, 443} and parsed.username is None and parsed.password is None)
    except ValueError:
        return False


def native_process_path(pid):
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    )
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    process = kernel.OpenProcess(0x1000, False, pid)
    if process:
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                return Path(buffer.value).resolve()
        finally:
            kernel.CloseHandle(process)
    return None


def windows_api():
    if sys.platform != 'win32':
        raise ValueError('Preenchimento em janela aberta requer Windows e o Google Chrome instalado.')
    from pywinauto import Desktop
    return Desktop


class OpenChrome:
    def __init__(self, stop):
        self.stop = stop

    def check(self):
        if self.stop.is_set():
            raise ValueError('Operação interrompida. Confira os campos que já foram preenchidos.')

    def windows(self):
        desktop = windows_api()
        executable = channel_executable('chrome')
        if executable is None:
            raise ValueError('Instalação estável do Google Chrome não encontrada.')
        allowed = executable.resolve()
        return [(int(window.handle), int(window.process_id()), window.window_text())
                for window in desktop(backend='win32').windows(class_name='Chrome_WidgetWin_1')
                if native_process_path(window.process_id()) == allowed]

    def target(self, selected, demo):
        self.check()
        handle, pid = selected
        window = windows_api()(backend='uia').window(handle=handle).wrapper_object()
        executable = channel_executable('chrome')
        if (window.element_info.process_id != pid or window.class_name() != 'Chrome_WidgetWin_1'
                or executable is None or native_process_path(pid) != executable.resolve()):
            raise ValueError('A janela selecionada mudou. Selecione novamente o Chrome.')
        # Walk the browser UI only. A page input must never stand in for Chrome’s address bar.
        waiting = list(window.children())
        addresses, documents = [], []
        while waiting:
            self.check()
            control = waiting.pop()
            info = control.element_info
            if not control.is_visible():
                continue
            if info.control_type == 'Document':
                if not info.element.CurrentIsOffscreen:
                    documents.append(control)
                continue
            if info.control_type == 'Edit' and (
                info.name.casefold() in ADDRESS_NAMES or info.automation_id.casefold() in ADDRESS_IDS
            ):
                if info.element.CurrentHasKeyboardFocus:
                    raise ValueError('Saia da barra de endereço e confira a página selecionada no Chrome.')
                addresses.append(control.iface_value.CurrentValue)
            else:
                waiting.extend(control.children())
        if len(addresses) != 1 or not approved_address(addresses[0], demo):
            raise ValueError('A barra de endereço do Chrome não confirmou o destino esperado. Abra a página correta e selecione a janela novamente.')
        if len(documents) != 1:
            raise ValueError('O Chrome não expôs um documento ativo único à API de acessibilidade.')
        document = documents[0]
        token = (addresses[0], tuple(document.element_info.element.GetRuntimeId()))
        return document, token

    def fields(self, document):
        fields = {}
        duplicates = set()
        for field in document.descendants(control_type='Edit'):
            self.check()
            info = field.element_info
            if (not info.name or not field.is_visible() or not field.is_enabled()
                    or info.element.CurrentIsPassword or info.element.CurrentIsOffscreen):
                continue
            if not info.element.GetCurrentPropertyValue(30043):
                continue
            if field.iface_value.CurrentIsReadOnly:
                continue
            if info.name in fields:
                duplicates.add(info.name)
            fields[info.name] = field
        return {name: field for name, field in fields.items() if name not in duplicates}

    def inspect(self, selected, demo):
        document, token = self.target(selected, demo)
        fields = sorted(self.fields(document))
        if not fields:
            raise ValueError('Nenhum campo editável com nome acessível único e suporte a ValuePattern. Use o fluxo existente.')
        return fields, token

    def fill(self, selected, demo, mapping, summary, date_format, expected_target=None):
        if not mapping or set(mapping) - FIELDS.keys() or len(set(mapping.values())) != len(mapping):
            raise ValueError('Selecione campos distintos no mapeamento assistido.')
        missing = [FIELDS[key] for key in mapping if summary.get(key) is None]
        if missing:
            raise ValueError('Valores indisponíveis no resumo: ' + ', '.join(missing))
        values = {
            key: format_amount(summary[key]) if key in LABELS else
            ('/'.join(reversed(summary[key].split('-'))) if date_format == 'br' else summary[key])
            for key in mapping
        }

        document, original = self.target(selected, demo)
        if expected_target is not None and original != expected_target:
            raise ValueError('A aba ou página mudou desde a inspeção. Inspecione novamente.')

        def verified_fields():
            current, token = self.target(selected, demo)
            if token != original:
                raise ValueError('A aba ou página mudou. Operação interrompida antes de continuar.')
            return self.fields(current)

        fields = self.fields(document)
        for key, name in mapping.items():
            self.check()
            if name not in fields:
                raise ValueError(f'Campo ausente, duplicado ou somente leitura: {FIELDS[key]}.')
            if fields[name].iface_value.CurrentValue not in {'', values[key]}:
                raise ValueError(f'O campo {FIELDS[key]} já tem outro valor. Abra um formulário novo.')

        completed = 0
        for key, name in mapping.items():
            try:
                field = verified_fields().get(name)
                if field is None:
                    raise ValueError
                self.check()
                value = field.iface_value
                if value.CurrentValue not in {'', values[key]}:
                    raise ValueError
                if value.CurrentValue != values[key]:
                    value.SetValue(values[key])
                self.check()
                if value.CurrentValue != values[key]:
                    raise ValueError
                completed += 1
            except Exception as error:
                raise ValueError(
                    f'Preenchimento interrompido em {FIELDS[key]}. '
                    f'Campos confirmados até então: {completed}. Confira a página manualmente.'
                ) from error
        final = verified_fields()
        self.check()
        if any(name not in final or final[name].iface_value.CurrentValue != values[key]
               for key, name in mapping.items()):
            raise ValueError('Os valores mudaram durante a conferência. Confira a página manualmente.')
        return values
