import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from .assisted import save_profile
from .open_window import DEMO_PATH, FIELDS


class OpenWindowTab(QWidget):
    def __init__(self, profile_path, dispatch, stop, approved_summary):
        super().__init__()
        self.profile_path = Path(profile_path)
        self.dispatch = dispatch
        self.stop = stop
        self.approved_summary = approved_summary
        try:
            self.profiles = json.loads(self.profile_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.profiles = {}
        self.inspected = None
        self.active = False

        layout = QVBoxLayout(self)
        guide = QLabel('Abra o Chrome manualmente e deixe visível a aba do formulário novo. '
                       'Selecione a janela, inspecione os campos e confira a prévia.')
        guide.setWordWrap(True)
        layout.addWidget(guide)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.demo = QCheckBox('Formulário fictício')
        self.demo.setChecked(True)
        self.demo.toggled.connect(self.invalidate)
        row.addWidget(self.demo)
        self.demo_path = self.button(row, 'Copiar caminho do HTML fictício', self.copy_demo_path)
        self.refresh = self.button(row, 'Listar janelas do Chrome', lambda: self.dispatch('window_list', None))
        self.windows = QComboBox()
        self.windows.currentIndexChanged.connect(self.invalidate)
        layout.addWidget(self.windows)
        self.inspect = self.button(layout, 'Inspecionar campos da janela', self.inspect_window)
        self.form = QWidget()
        form = QFormLayout(self.form)
        layout.addWidget(self.form)
        self.fields = {}
        for key, label in FIELDS.items():
            picker = QComboBox()
            picker.currentIndexChanged.connect(self.clear_preview)
            self.fields[key] = picker
            form.addRow(label, picker)
        self.date = QComboBox()
        self.date.addItem('DD/MM/AAAA', 'br')
        self.date.addItem('AAAA-MM-DD', 'iso')
        self.date.currentIndexChanged.connect(self.clear_preview)
        form.addRow('Formato das datas', self.date)
        self.confirm = QCheckBox('Conferi que é um formulário novo, do estabelecimento correto e sem gravação automática')
        self.confirm.toggled.connect(self.clear_preview)
        layout.addWidget(self.confirm)
        buttons = QHBoxLayout()
        layout.addLayout(buttons)
        self.prepare = self.button(buttons, 'Conferir prévia', self.preview)
        self.apply = self.button(buttons, 'Preencher janela', self.fill)
        self.cancel = self.button(buttons, 'Interromper', self.interrupt)
        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        layout.addWidget(self.preview_text)
        self.status = QLabel('Comece pelo formulário fictício.')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.snapshot = None
        self.set_busy(False)

    @staticmethod
    def button(layout, label, callback):
        button = QPushButton(label)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def copy_demo_path(self):
        QApplication.clipboard().setText(str(DEMO_PATH.resolve()))
        self.status.setText('Caminho copiado. Abra esse arquivo no Chrome (Ctrl+O).')

    def interrupt(self):
        self.stop.set()
        self.status.setText('Interrupção solicitada. Nenhum campo adicional será iniciado.')

    def invalidate(self, *_):
        self.inspected = None
        self.clear_preview()

    def clear_preview(self, *_):
        self.snapshot = None
        self.preview_text.clear()
        self.apply.setEnabled(False)

    def inspect_window(self):
        target = self.windows.currentData()
        if target is None:
            self.status.setText('Selecione explicitamente uma janela do Chrome.')
            return
        self.invalidate()
        self.dispatch('window_inspect', (target, self.demo.isChecked()))

    def set_busy(self, busy, active=False):
        self.active = active
        for widget in (self.demo, self.demo_path, self.refresh, self.windows, self.inspect,
                       self.form, self.confirm, self.prepare):
            widget.setEnabled(not busy)
        self.apply.setEnabled(not busy and self.snapshot is not None)
        self.cancel.setEnabled(active)

    def complete(self, action, result):
        if 'error' in result:
            self.status.setText(result['error'])
            return
        if action == 'window_list':
            self.windows.clear()
            self.windows.addItem('Selecione uma janela…', None)
            for handle, pid, title in result['windows']:
                self.windows.addItem(f'{title or "Google Chrome"} · janela {handle}', (handle, pid))
            self.status.setText(f'{len(result["windows"])} janela(s) do Google Chrome encontrada(s).')
        elif action == 'window_inspect':
            mode = 'demo' if self.demo.isChecked() else 'premier'
            saved = self.profiles.get(mode, {})
            for key, picker in self.fields.items():
                picker.clear()
                picker.addItem('Não preencher', None)
                picker.addItems(result['fields'])
                picker.setCurrentIndex(max(0, picker.findData(saved.get('mapping', {}).get(key), Qt.ItemDataRole.DisplayRole)))
            self.date.setCurrentIndex(max(0, self.date.findData(saved.get('date_format', 'br'))))
            self.inspected = (self.windows.currentData(), self.demo.isChecked())
            self.status.setText('Campos disponíveis. Relacione cada valor ao campo de destino.')
        else:
            self.preview_text.setPlainText('\n'.join(f'{FIELDS[key]}: {value}' for key, value in result['values'].items()))
            self.status.setText('Campos relidos e conferidos. Nenhum comando de salvamento foi enviado.')
            self.snapshot = None

    def preview(self):
        self.clear_preview()
        approved = self.approved_summary()
        target = (self.windows.currentData(), self.demo.isChecked())
        if target[0] is None or self.inspected != target:
            self.status.setText('Selecione e inspecione a janela antes de preparar a prévia.')
            return
        if not approved:
            self.status.setText('Aprove um resumo na aba Importar iFood.')
            return
        if not self.demo.isChecked() and not self.confirm.isChecked():
            self.status.setText('Confirme o formulário novo, o estabelecimento e a ausência de gravação automática.')
            return
        mapping = {key: picker.currentText() for key, picker in self.fields.items() if picker.currentIndex() > 0}
        if not mapping or len(set(mapping.values())) != len(mapping):
            self.status.setText('Mapeie pelo menos um campo e use destinos distintos.')
            return
        import_id, summary = approved
        if any(summary.get(key) is None for key in mapping):
            self.status.setText('O resumo não fornece todos os valores mapeados.')
            return
        date_format = self.date.currentData()
        mode = 'demo' if target[1] else 'premier'
        self.profiles[mode] = {'mapping': mapping, 'date_format': date_format}
        try:
            save_profile(self.profile_path, self.profiles)
        except OSError:
            self.status.setText('Não foi possível salvar o mapeamento local.')
            return
        from .daily import LABELS, format_amount

        lines = [f'{summary["store"]} · {summary["day"]}']
        for key, name in mapping.items():
            value = format_amount(summary[key]) if key in LABELS else (
                '/'.join(reversed(summary[key].split('-'))) if date_format == 'br' else summary[key]
            )
            lines.append(f'{FIELDS[key]} → {name}: {value}')
        self.preview_text.setPlainText('\n'.join(lines))
        self.snapshot = (import_id, dict(summary), *target, mapping, date_format)
        self.status.setText('Confira a prévia e a aba ativa no Chrome antes de preencher.')
        self.apply.setEnabled(True)

    def fill(self):
        if self.snapshot is None or self.approved_summary() != self.snapshot[:2]:
            self.clear_preview()
            self.status.setText('A aprovação mudou. Confira e prepare uma nova prévia.')
            return
        self.dispatch('window_fill', self.snapshot)
