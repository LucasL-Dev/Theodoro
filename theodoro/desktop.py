import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from queue import Queue
from threading import Event, Thread

from PySide6.QtCore import QDate, QObject, QStandardPaths, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateEdit, QHBoxLayout, QLabel,
    QInputDialog, QLineEdit, QListWidget, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)
from playwright.sync_api import Error as PlaywrightError

from financeiro.mapping import Entry
from financeiro.sync import History

from .assisted import STEPS, save_profile, scope_step, set_step
from .browser import Browser, ChromiumUnavailable, Interrupted
from .daily import LABELS, format_amount
from .import_tab import ImportTab


def vault():
    if sys.platform != 'win32':
        raise ValueError('O armazenamento de credenciais está disponível somente no Windows.')
    from keyring.backends.Windows import WinVaultKeyring
    return WinVaultKeyring()


class TestDestination:
    def __init__(self, browser):
        self.browser = browser
        self.persisted = None

    def create(self, key, payload):
        self.browser.save_demo()
        self.persisted = (key, payload)
        return key

    def read(self, receipt):
        return self.persisted


class Worker(QObject):
    progress = Signal(int, str)
    done = Signal(str, object)

    def __init__(self, stop, db_path):
        super().__init__()
        self.browser = Browser(stop)
        self.history = History(db_path)
        self.summary = None

    def serve(self, requests):
        try:
            while True:
                action, options = requests.get()
                if action == 'close':
                    break
                self.execute(action, options)
        finally:
            self.browser.close()

    def execute(self, action, options):
        try:
            result = self.run_action(action, options)
        except Interrupted:
            result = {'error': 'Operação interrompida pelo usuário.'}
        except ChromiumUnavailable as error:
            result = {'error': str(error)}
        except PlaywrightError:
            self.browser.close()
            result = {'error': 'Falha no Chromium, na conexão ou no controle da página. Confira o navegador e o perfil.'}
        except (KeyError, TypeError, OSError):
            result = {'error': 'Configuração, arquivo ou credencial indisponível.'}
        except ValueError as error:
            if isinstance(error, json.JSONDecodeError):
                result = {'error': 'O perfil deve ser um arquivo JSON válido.'}
            else:
                result = {'error': str(error)}
        except Exception:
            result = {'error': 'Erro inesperado ao executar a operação.'}
        if 'error' in result and action in {'start', 'save', 'real_test'}:
            self.summary = None
            self.browser.prepared = None
            try:
                self.history.record('desktop_erro', result)
            except Exception:
                result['error'] += ' O histórico também está indisponível.'
        self.done.emit(action, result)

    def run_action(self, action, options):
        if action == 'credentials':
            vault().set_password('Theodoro.Premier', 'operator', json.dumps(options))
            return {'message': 'Credencial armazenada no Gerenciador de Credenciais do Windows.'}
        if action in {'ifood', 'premier'}:
            path, use_vault = options
            profile = json.loads(Path(path).read_text(encoding='utf-8')) if path else None
            credentials = None
            if action == 'premier' and use_vault:
                if not profile or not profile.get('premier', {}).get('login'):
                    raise ValueError('O login automático requer um perfil local com campos de login verificados.')
                stored = vault().get_password('Theodoro.Premier', 'operator')
                if not stored:
                    raise ValueError('Cadastre a credencial do Premier no aplicativo.')
                credentials = json.loads(stored)
            ready = self.browser.connect(action, profile, credentials)
            return {'ready': ready, 'message': (
                'Sessão verificada.' if ready else
                'Conclua ou confira o login no Chromium. A sessão fica aberta durante o uso do aplicativo.'
            )}
        if action == 'config_open':
            self.browser.configuration_page(*options)
            return {'message': 'Faça login manualmente ou navegue até o controle a identificar.'}
        if action == 'config_pick':
            selector, fingerprint = self.browser.capture(*options)
            return {'selector': selector, 'fingerprint': fingerprint}
        if action == 'config_check':
            self.browser.test_selector(*options)
            return {'message': 'Controle único e visível na página atual.'}
        if action == 'import_connect':
            self.browser.configuration_page('premier', False)
            return {'message': 'Conclua o login manualmente no Chromium e volte à tela inicial autenticada.'}
        if action == 'import_fill':
            import_id, summary, spec, demo = options
            self.summary = None
            try:
                self.browser.premier_preview(summary, spec, demo)
            except Exception:
                self.history.record('ifood_premier', {
                    'importacao': import_id, 'estabelecimento': summary['store'],
                    'dia': summary['day'], 'simulacao': demo, 'premier': 'falha',
                })
                raise
            self.history.record('ifood_premier', {
                'importacao': import_id, 'estabelecimento': summary['store'],
                'dia': summary['day'], 'simulacao': demo, 'premier': 'preenchimento_conferido',
            })
            return {'message': 'Campos preenchidos e conferidos. Nenhum lançamento foi salvo.'}
        if action == 'real_test':
            day, profile, demo = options
            self.summary = None
            summary = self.browser.assisted_preview(day, profile, self.progress.emit, demo=demo)
            result = {'summary': asdict(summary), 'pending': False}
            self.history.record('desktop_integracao_teste', {
                'day': day, 'demo': demo, 'status': 'preview_verified',
            })
            return result
        if action == 'start':
            day, demo, profile = options
            self.summary = None
            summary = self.browser.prepare(day, demo, profile, self.progress.emit)
            self.browser.check()
            self.summary = summary if demo else None
            result = {'summary': asdict(summary), 'pending': demo}
            self.history.record('desktop_previa', result)
            return result
        if action == 'save':
            summary = self.summary
            self.summary = None
            if summary is None:
                raise ValueError('Gere a prévia antes de aprovar.')
            entry = Entry(
                'demo', summary.day, 'resumo-diario', summary.day, summary.day,
                summary.day, json.dumps(asdict(summary), sort_keys=True),
                'Teste local', 'aprovado', summary.net,
            )
            self.browser.check()
            status = self.history.send_to_test_destination(
                entry, TestDestination(self.browser), approved_payload=entry.payload(),
            )
            self.browser.prepared = None
            result = {'status': status, 'summary': asdict(summary)}
            self.history.record('desktop_teste', result)
            return result
        raise ValueError('Operação desconhecida.')


class Window(QMainWindow):
    def __init__(self, path):
        super().__init__()
        self.setWindowTitle('Theodoro | Automação financeira')
        self.resize(780, 565)
        self.history = History(path)
        self.stop = Event()
        self.busy = False
        self.pending = False
        self.config_dir = Path(path).parent
        self.profile_path = self.config_dir / 'automation.json'
        self.profiles = {}
        for demo, name in ((False, 'automation.json'), (True, 'automation-demo.json')):
            try:
                self.profiles[demo] = json.loads((self.config_dir / name).read_text(encoding='utf-8'))
            except (OSError, ValueError):
                self.profiles[demo] = {}
        self.capture_target = None
        self.requests = Queue()
        self.worker = Worker(self.stop, path)
        self.worker.progress.connect(self.update_progress, Qt.ConnectionType.QueuedConnection)
        self.worker.done.connect(self.completed, Qt.ConnectionType.QueuedConnection)
        self.thread = Thread(target=self.worker.serve, args=(self.requests,), name='TheodoroBrowser')
        self.thread.start()

        tabs = QTabWidget()
        self.setCentralWidget(tabs)
        operation, history = QWidget(), QWidget()
        self.import_tab = ImportTab(
            self.history, self.fill_import, lambda: self.dispatch('import_connect', None), self.refresh_history,
        )
        tabs.addTab(self.import_tab, 'Importar iFood')
        tabs.addTab(operation, 'Automação')
        self.config_tab = QWidget()
        tabs.addTab(self.config_tab, 'Configurar automação')
        tabs.addTab(history, 'Histórico e erros')
        layout = QVBoxLayout(operation)
        title = QLabel('Automação financeira')
        title.setStyleSheet('font-size: 24px; font-weight: 650')
        layout.addWidget(title)
        connections = QHBoxLayout()
        layout.addLayout(connections)
        self.connection_labels = {}
        self.controls = []
        for portal, name in [('ifood', 'iFood'), ('premier', 'Premier Delivery')]:
            card = QVBoxLayout()
            connections.addLayout(card)
            label = QLabel('Sessão a verificar')
            self.connection_labels[portal] = label
            self.add_button(card, f'Conectar ao {name}', lambda p=portal: self.connect_portal(p))
            card.addWidget(label)

        options = QHBoxLayout()
        layout.addLayout(options)
        options.addWidget(QLabel('Data de referência'))
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat('dd/MM/yyyy')
        options.addWidget(self.date)
        self.use_vault = QCheckBox('Usar credencial do Premier')
        options.addWidget(self.use_vault)
        settings = QHBoxLayout()
        layout.addLayout(settings)
        self.add_button(settings, 'Guardar credencial do Premier', self.set_credentials)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        self.add_button(actions, 'Iniciar simulação', self.start)
        self.add_button(actions, 'Testar integração real', lambda: self.test_integration(False))
        self.cancel_button = QPushButton('Parar automação')
        self.cancel_button.clicked.connect(self.cancel)
        actions.addWidget(self.cancel_button)
        self.approve = QPushButton('Aprovar e salvar teste')
        self.approve.clicked.connect(self.approve_test)
        actions.addWidget(self.approve)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.message = QLabel('Pronto para iniciar')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview)
        history_layout = QVBoxLayout(history)
        self.history_view = QPlainTextEdit()
        self.history_view.setReadOnly(True)
        history_layout.addWidget(self.history_view)
        self.setup_configuration()
        self.refresh_history()
        self.update_controls()

    def add_button(self, layout, name, callback):
        button = QPushButton(name)
        button.clicked.connect(callback)
        layout.addWidget(button)
        self.controls.append(button)

    def update_controls(self):
        for button in self.controls:
            button.setEnabled(not self.busy)
        for control in (self.date, self.use_vault, self.config_portal, self.config_demo, self.config_steps, self.config_format, self.config_input_format, self.config_no_save):
            control.setEnabled(not self.busy)
        self.config_format.setEnabled(not self.busy and self.config_portal.currentData() == 'ifood')
        self.config_input_format.setEnabled(not self.busy)
        self.config_no_save.setEnabled(not self.busy and self.config_portal.currentData() == 'premier')
        self.import_tab.set_busy(self.busy)
        self.cancel_button.setEnabled(self.busy or self.pending)
        self.approve.setEnabled(self.pending and not self.busy)

    def dispatch(self, action, options):
        if self.busy:
            return
        self.stop.clear()
        self.busy = True
        self.update_controls()
        self.requests.put((action, options))

    def start(self):
        self.pending = False
        self.preview.clear()
        self.update_progress(5, 'Abrindo Chromium')
        self.dispatch('start', (self.date.date().toString('yyyy-MM-dd'),
                                True, None))

    def cancel(self):
        self.stop.set()
        self.pending = False
        self.message.setText('Interrupção solicitada. Aguardando a etapa atual.')
        self.update_controls()

    def connect_portal(self, portal):
        self.message.setText('Abrindo portal autorizado no Chromium')
        self.dispatch(portal, (self.profile_path if self.profile_path.exists() else None, self.use_vault.isChecked()))

    def setup_configuration(self):
        layout = QVBoxLayout(self.config_tab)
        header = QHBoxLayout()
        layout.addLayout(header)
        self.config_portal = QComboBox()
        self.config_portal.addItem('iFood', 'ifood')
        self.config_portal.addItem('Premier Delivery', 'premier')
        header.addWidget(self.config_portal)
        self.config_demo = QCheckBox('Usar páginas fictícias')
        header.addWidget(self.config_demo)
        self.add_button(header, 'Abrir portal', lambda: self.dispatch('config_open', self.config_target()))
        note = QLabel('Faça login no Chromium. Selecione a etapa e capture o controle. '
                      'Para gravar uma sequência, capture cada clique e depois execute-o manualmente no navegador.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.config_steps = QListWidget()
        layout.addWidget(self.config_steps)
        buttons = QHBoxLayout()
        layout.addLayout(buttons)
        self.add_button(buttons, 'Capturar controle', self.pick_control)
        self.add_button(buttons, 'Testar seletor', self.check_control)
        self.add_button(buttons, 'Remover seleção', self.remove_control)
        self.add_button(buttons, 'Reproduzir páginas fictícias', lambda: self.test_integration(True))
        formats = QHBoxLayout()
        layout.addLayout(formats)
        self.config_input_format = QComboBox()
        self.config_format = QComboBox()
        for label, widget in (('Data digitada', self.config_input_format), ('Data no resultado', self.config_format)):
            formats.addWidget(QLabel(label))
            widget.addItem('AAAA-MM-DD', 'iso')
            widget.addItem('DD/MM/AAAA', 'br')
            formats.addWidget(widget)
            widget.currentIndexChanged.connect(self.update_profile_options)
        self.config_no_save = QCheckBox('Verifiquei que o formulário não grava ao digitar ou sair do campo')
        self.config_no_save.toggled.connect(self.update_profile_options)
        layout.addWidget(self.config_no_save)
        self.config_message = QLabel('')
        self.config_message.setWordWrap(True)
        layout.addWidget(self.config_message)
        self.config_portal.currentIndexChanged.connect(self.refresh_config)
        self.config_demo.toggled.connect(self.refresh_config)
        self.refresh_config()

    def config_target(self):
        return self.config_portal.currentData(), self.config_demo.isChecked()

    def refresh_config(self):
        portal, demo = self.config_target()
        profile = self.profiles[demo]
        self.config_steps.clear()
        for key, label in STEPS[portal].items():
            value = scope_step(profile, portal, key)
            if key == 'open':
                self.config_steps.addItem(label)
                self.config_steps.item(self.config_steps.count() - 1).setData(Qt.ItemDataRole.UserRole, (key, None))
                for index in range(len(value or [])):
                    self.config_steps.addItem(f'  Navegação {index + 1} configurada')
                    self.config_steps.item(self.config_steps.count() - 1).setData(Qt.ItemDataRole.UserRole, (key, index))
            else:
                self.config_steps.addItem(f"{label} {'✓' if value else ''}")
                self.config_steps.item(self.config_steps.count() - 1).setData(Qt.ItemDataRole.UserRole, (key, None))
        self.config_steps.setCurrentRow(0)
        for widget, prop in ((self.config_format, 'result_date_format'),
                             (self.config_input_format, 'input_date_format')):
            widget.blockSignals(True)
            widget.setCurrentIndex(widget.findData(profile.get(portal, {}).get(prop, 'iso')))
            widget.setEnabled((portal == 'ifood' or widget is self.config_input_format) and not self.busy)
            widget.blockSignals(False)
        self.config_no_save.blockSignals(True)
        self.config_no_save.setChecked(profile.get(portal, {}).get('allow_unsaved_fill') is True)
        self.config_no_save.setEnabled(portal == 'premier' and not self.busy)
        self.config_no_save.blockSignals(False)

    def persist_config(self, demo):
        path = self.config_dir / 'automation-demo.json' if demo else self.profile_path
        try:
            save_profile(path, self.profiles[demo])
            self.config_message.setText('Configuração salva neste computador.')
        except OSError:
            self.config_message.setText('Falha ao salvar a configuração local.')

    def update_profile_options(self, *_):
        portal, demo = self.config_target()
        spec = self.profiles[demo].setdefault(portal, {})
        spec['input_date_format'] = self.config_input_format.currentData()
        if portal == 'ifood':
            spec['result_date_format'] = self.config_format.currentData()
        else:
            spec['allow_unsaved_fill'] = self.config_no_save.isChecked()
        self.persist_config(demo)

    def chosen_step(self):
        item = self.config_steps.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else (None, None)

    def pick_control(self):
        key, index = self.chosen_step()
        if key is None:
            return
        portal, demo = self.config_target()
        self.capture_target = (portal, demo, key, index)
        self.config_message.setText('Clique no controle no Chromium. Esc cancela a captura.')
        self.dispatch('config_pick', (portal, demo, key))

    def check_control(self):
        key, index = self.chosen_step()
        portal, demo = self.config_target()
        value = scope_step(self.profiles[demo], portal, key) if key else None
        if key == 'open':
            value = value[index] if index is not None else None
        if value:
            self.dispatch('config_check', (portal, demo, key, value))
        else:
            self.config_message.setText('Capture este controle primeiro.')

    def remove_control(self):
        key, index = self.chosen_step()
        portal, demo = self.config_target()
        spec = self.profiles[demo].get(portal, {})
        if key == 'open' and index is not None:
            spec['open'].pop(index)
        elif key and '.' in key:
            group, field = key.split('.')
            spec.get(group, {}).pop(field, None)
        elif key and key != 'open':
            spec.pop(key, None)
            if key == 'store':
                spec.pop('store_digest', None)
        self.persist_config(demo)
        self.refresh_config()

    def fill_import(self, import_id, summary, demo):
        self.pending = False
        spec = self.profiles[False].get('premier', {})
        if demo:
            demo_profile = Path(__file__).with_name('assets') / 'profile.demo.json'
            spec = json.loads(demo_profile.read_text(encoding='utf-8'))['premier']
            spec.update(ready='h1', form='form', allow_unsaved_fill=True)
        self.import_tab.status.setText('Preenchendo e conferindo o formulário no Chromium…')
        self.dispatch('import_fill', (import_id, summary, spec, demo))

    def test_integration(self, demo):
        self.pending = False
        self.preview.clear()
        self.update_progress(5, 'Testando o fluxo configurado')
        self.config_message.setText('Executando o fluxo configurado. Confira o Chromium.')
        self.dispatch('real_test', (self.date.date().toString('yyyy-MM-dd'), self.profiles[demo], demo))

    def set_credentials(self):
        if sys.platform != 'win32':
            self.message.setText('A credencial pode ser armazenada somente no Windows.')
            return
        email, ok = QInputDialog.getText(self, 'Credencial do Premier', 'E-mail')
        if not ok or not email.strip():
            return
        password, ok = QInputDialog.getText(self, 'Credencial do Premier', 'Senha',
                                            QLineEdit.EchoMode.Password)
        if ok and password:
            self.dispatch('credentials', (email.strip(), password))

    def approve_test(self):
        approved = QMessageBox.question(self, 'Aprovar teste', 'Salvar a prévia no destino fictício?')
        if approved == QMessageBox.StandardButton.Yes:
            self.pending = False
            self.dispatch('save', None)

    @Slot(int, str)
    def update_progress(self, value, message):
        self.message.setText(message)
        self.progress.setValue(value)

    @Slot(str, object)
    def completed(self, action, result):
        self.busy = False
        if action in {'import_fill', 'import_connect'}:
            self.import_tab.status.setText(result.get('error') or result['message'])
        elif 'error' in result:
            if action.startswith('config_') or action == 'real_test':
                self.config_message.setText(result['error'])
            if action in self.connection_labels:
                self.connection_labels[action].setText('Falha ao verificar sessão')
            self.update_progress(0, result['error'])
        elif action == 'config_pick':
            portal, demo, key, index = self.capture_target
            profile = self.profiles[demo]
            if key == 'open' and index is not None:
                profile[portal]['open'][index] = result['selector']
            else:
                set_step(profile, portal, key, result['selector'], result['fingerprint'])
            self.persist_config(demo)
            self.refresh_config()
        elif action in {'config_open', 'config_check'}:
            self.config_message.setText(result['message'])
        elif action in {'start', 'real_test'}:
            if action == 'real_test':
                self.config_message.setText('Prévia disponível na aba Automação. Nenhum lançamento foi salvo.')
            self.pending = result['pending'] and not self.stop.is_set()
            summary = result['summary']
            self.preview.setPlainText(
                f"Data das vendas e dos recebimentos consultados: {summary['day']}\n\n"
                + '\n'.join(f'{label}   R$ {format_amount(summary[key])}' for key, label in LABELS.items())
            )
        elif action == 'save':
            messages = {
                'confirmed': 'Lançamento fictício confirmado.',
                'duplicate': 'O teste desta data já foi confirmado.',
                'review': 'Resultado incerto ou divergente. Revise o histórico.',
            }
            self.update_progress(100, messages[result['status']])
        else:
            if action in self.connection_labels:
                self.connection_labels[action].setText('Conectado' if result['ready'] else 'Sessão a verificar')
            self.message.setText(result['message'])
        self.refresh_history()
        self.update_controls()

    def refresh_history(self):
        try:
            self.history_view.setPlainText(json.dumps(self.history.runs(), ensure_ascii=False, indent=2))
        except Exception:
            self.history_view.setPlainText('Histórico indisponível.')

    def closeEvent(self, event):
        self.stop.set()
        self.requests.put(('close', None))
        self.thread.join()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Theodoro')
    app.setStyle('Fusion')
    data = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    old_history = Path('data/history.sqlite')
    db_path = Path(os.environ.get('THEODORO_DB', data / 'history.sqlite'))
    if 'THEODORO_DB' not in os.environ and old_history.is_file() and not db_path.exists():
        import sqlite3
        from contextlib import closing
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(old_history)) as source, closing(sqlite3.connect(db_path)) as target:
            source.backup(target)
    window = Window(db_path)
    window.show()
    return app.exec()
