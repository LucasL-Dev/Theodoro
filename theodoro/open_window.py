"""Windows UI Automation adapter for an explicitly chosen Chrome window."""
import ctypes
import sys
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
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


class AccessibilityUnavailable(ValueError):
    """Selected Chrome did not expose enough native accessibility information."""


def raw_children(control):
    from pywinauto.controls.uiawrapper import UIAWrapper
    from pywinauto.uia_defines import IUIA
    from pywinauto.uia_element_info import UIAElementInfo

    walker = IUIA().iuia.RawViewWalker
    element = walker.GetFirstChildElement(control.element_info.element)
    while element:
        yield UIAWrapper(UIAElementInfo(element))
        element = walker.GetNextSiblingElement(element)


def approved_address(address, demo):
    try:
        address = address.strip()
        if demo and PureWindowsPath(address).is_absolute() and not address.startswith(('//', '\\')):
            address = PureWindowsPath(address).as_uri()
        parsed = urlsplit(address)
        if demo:
            return (parsed.scheme == 'file' and not parsed.netloc and not parsed.query and not parsed.fragment
                    and unquote(parsed.path).replace('\\', '/').casefold()
                    == unquote(urlsplit(DEMO_PATH.resolve().as_uri()).path).casefold())
        return (parsed.scheme == 'https' and parsed.hostname == 'inside.premierdelivery.com.br'
                and parsed.port in {None, 443} and parsed.username is None and parsed.password is None)
    except ValueError:
        return False


@dataclass
class DocumentIdentity:
    control: object
    address: str
    title: str


def address_key(value, demo):
    if demo and PureWindowsPath(value).is_absolute():
        value = PureWindowsPath(value).as_uri()
    parts = urlsplit(value)
    if demo:
        return unquote(parts.path).casefold()
    return (parts.hostname, parts.port or 443, parts.path or '/', parts.query, parts.fragment)


def select_document(documents, address, tab_titles, demo):
    """Require committed URL evidence and reject competing active document candidates."""
    address = address.strip()
    if address and not approved_address(address, demo):
        # Chrome can omit https from the omnibox. Only corroborate an HTTPS
        # URL supplied independently by the document's accessibility provider.
        if demo or '://' in address or not approved_address('https://' + address, False):
            raise AccessibilityUnavailable('O endereço ativo do Chrome não corresponde ao destino esperado.')
        displayed = 'https://' + address
    else:
        displayed = address
    if not documents:
        raise AccessibilityUnavailable('O Chrome não expôs um documento principal visível na janela selecionada.')

    if isinstance(tab_titles, str):
        tab_titles = (tab_titles,)
    tab_titles = {title.strip() for title in tab_titles if title and title.strip()}
    titles = [doc for doc in documents if doc.title.strip() in tab_titles]
    matching = [
        doc for doc in documents
        if doc.address and approved_address(doc.address, demo)
        and (not displayed or address_key(doc.address, demo) == address_key(displayed, demo))
    ]
    if matching_titled := [doc for doc in matching if doc in titles]:
        matching = matching_titled
    if not address:
        matching = [doc for doc in matching if len(tab_titles) == 1 and doc in titles]
    if len(matching) > 1:
        raise AccessibilityUnavailable(f'Página ambígua: {len(matching)} documentos principais correspondem ao endereço da aba.')
    if matching:
        doc = matching[0]
        if titles and doc not in titles:
            raise AccessibilityUnavailable('O documento com o endereço esperado não corresponde à aba selecionada.')
        return doc, doc.address

    # Some Chrome providers omit the URL on the document. In that case,
    # require both a complete approved omnibox address and a unique selected
    # tab title matched to a root document; never accept a conflicting URL.
    if approved_address(address, demo) and titles:
        if len(tab_titles) == 1 and len(titles) == 1 and not titles[0].address:
            return titles[0], address
        if len(titles) > 1:
            raise AccessibilityUnavailable(f'Página ambígua: {len(titles)} documentos têm o título da aba selecionada.')
    raise AccessibilityUnavailable(
        f'A acessibilidade não confirmou o documento da aba ativa ({len(documents)} raízes visíveis, '
        f'barra confirmável: {bool(displayed)}, abas selecionadas reportadas: {len(tab_titles)}).'
    )


def read_document_url(control):
    from comtypes import COMError
    from pywinauto.uia_defines import NoPatternInterfaceError, get_elem_interface

    for pattern in ('Value', 'LegacyIAccessible'):
        try:
            value = get_elem_interface(control.element_info.element, pattern).CurrentValue
            if value and urlsplit(value).scheme in {'https', 'http', 'file', 'chrome', 'about', 'devtools'}:
                return value.strip()
        except (NoPatternInterfaceError, COMError, ValueError):
            continue
    return ''


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
        desktop = windows_api()
        from pywinauto.uia_defines import NoPatternInterfaceError

        handle, pid = selected
        window = desktop(backend='uia').window(handle=handle).wrapper_object()
        executable = channel_executable('chrome')
        if (window.element_info.process_id != pid or window.class_name() != 'Chrome_WidgetWin_1'
                or executable is None or native_process_path(pid) != executable.resolve()):
            raise ValueError('A janela selecionada mudou. Selecione novamente o Chrome.')
        # Walk the browser UI only. A page input must never stand in for Chrome’s address bar.
        waiting = list(raw_children(window))
        addresses, documents, tabs = [], [], []
        while waiting:
            self.check()
            control = waiting.pop()
            info = control.element_info
            if info.control_type == 'Document':
                if not info.element.CurrentIsOffscreen:
                    documents.append(DocumentIdentity(control, read_document_url(control), info.name or ''))
                continue
            if info.control_type == 'TabItem' and not info.element.CurrentIsOffscreen:
                try:
                    if control.iface_selection_item.CurrentIsSelected:
                        tabs.append(info.name)
                except NoPatternInterfaceError:
                    pass
            if info.control_type == 'Edit' and not info.element.CurrentIsOffscreen and (
                info.name.casefold() in ADDRESS_NAMES or info.automation_id.casefold() in ADDRESS_IDS
            ):
                if info.element.CurrentHasKeyboardFocus:
                    raise ValueError('Saia da barra de endereço e confira a página selecionada no Chrome.')
                if value := control.iface_value.CurrentValue:
                    addresses.append(value.strip())
            else:
                waiting.extend(raw_children(control))
        addresses = set(addresses)
        if len(addresses) > 1:
            raise AccessibilityUnavailable('Página ambígua: o Chrome expôs barras de endereço com valores diferentes.')
        identity, approved = select_document(documents, next(iter(addresses), ''), tabs, demo)
        document = identity.control
        token = (approved, tuple(document.element_info.element.GetRuntimeId()))
        return document, token

    def fields(self, document):
        fields = {}
        duplicates = set()
        waiting = list(raw_children(document))
        while waiting:
            self.check()
            field = waiting.pop()
            info = field.element_info
            if info.control_type == 'Document':
                continue
            if info.control_type != 'Edit':
                waiting.extend(raw_children(field))
                continue
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
            raise AccessibilityUnavailable('Nenhum campo editável com nome acessível único e suporte a ValuePattern. Use o fluxo existente.')
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
