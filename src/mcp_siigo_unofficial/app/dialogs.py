"""Dialogs: the write-actions warning, Settings, and About (plan sections 1.1 and 5.1)."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mcp_siigo_unofficial import __version__
from mcp_siigo_unofficial.app.icons import app_icon
from mcp_siigo_unofficial.app.runtime import AppRuntime
from mcp_siigo_unofficial.i18n import (
    LINKEDIN_URL,
    REPOSITORY_URL,
    SETTING_LANGUAGE,
    WEBSITE_URL,
    Language,
    Translator,
)
from mcp_siigo_unofficial.siigo import DEFAULT_PARTNER_ID, SiigoCredentials, is_valid_partner_id


class WriteActionsDialog(QDialog):
    """Modal warning. "Enable" stays disabled until the user ticks the acceptance box."""

    def __init__(self, tr: Translator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("write.title"))
        self.setWindowIcon(app_icon(write_mode=True))
        self.setModal(True)
        self.setMinimumWidth(480)

        body = QLabel(tr("write.body"))
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)

        self.accept_box = QCheckBox(tr("write.accept"))
        buttons = QDialogButtonBox()
        self.enable_button = buttons.addButton(
            tr("write.enable"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.cancel_button = buttons.addButton(
            tr("write.cancel"), QDialogButtonBox.ButtonRole.RejectRole
        )
        self.enable_button.setEnabled(False)
        self.cancel_button.setDefault(True)
        self.accept_box.toggled.connect(self.enable_button.setEnabled)
        buttons.accepted.connect(self._accept_if_ticked)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(body)
        layout.addWidget(self.accept_box)
        layout.addWidget(buttons)

    def _accept_if_ticked(self) -> None:
        if self.accept_box.isChecked():
            self.accept()

    @property
    def accepted_responsibility(self) -> bool:
        return self.result() == QDialog.DialogCode.Accepted and self.accept_box.isChecked()


class _TestResult(QObject):
    finished = Signal(object)  # str | None


class SettingsDialog(QDialog):
    """Siigo credentials, Partner-Id, language, port, and the write switch."""

    language_changed = Signal()

    def __init__(self, runtime: AppRuntime, tr: Translator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.tr_ = tr
        self.setWindowTitle(tr("settings.title"))
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(460)

        saved = runtime.credentials()
        self._has_saved_key = saved is not None

        self.username = QLineEdit(saved.username if saved else "")
        self.access_key = QLineEdit()
        self.access_key.setEchoMode(QLineEdit.EchoMode.Password)
        if saved is not None:
            self.access_key.setPlaceholderText(tr("settings.access_key.saved"))
        self.partner_id = QLineEdit(saved.partner_id if saved else DEFAULT_PARTNER_ID)
        self.partner_id.setMaxLength(100)

        self.language = QComboBox()
        self.language.addItem(tr("settings.language.system"), None)
        self.language.addItem("English", "en")
        self.language.addItem("Español", "es")
        current = runtime.vault.get_setting(SETTING_LANGUAGE)
        self.language.setCurrentIndex(max(0, self.language.findData(current)))

        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(runtime.port)

        self.write_box = QCheckBox(tr("settings.write"))
        self.write_box.setChecked(runtime.write_switch.enabled)
        self.write_box.clicked.connect(self._write_clicked)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.test_button = QPushButton(tr("settings.test"))
        self.test_button.clicked.connect(self._test)
        self.clear_button = QPushButton(tr("settings.clear"))
        self.clear_button.clicked.connect(self._clear)
        self._test_result = _TestResult()
        self._test_result.finished.connect(self._test_finished)

        siigo_box = QGroupBox(tr("settings.siigo"))
        form = QFormLayout(siigo_box)
        help_label = QLabel(tr("settings.help"))
        help_label.setWordWrap(True)
        form.addRow(help_label)
        form.addRow(tr("settings.username"), self.username)
        form.addRow(tr("settings.access_key"), self.access_key)
        form.addRow(tr("settings.partner_id"), self.partner_id)
        row = QHBoxLayout()
        row.addWidget(self.test_button)
        row.addWidget(self.clear_button)
        row.addStretch(1)
        form.addRow(row)
        form.addRow(self.status)

        app_form = QFormLayout()
        app_form.addRow(tr("settings.language"), self.language)
        app_form.addRow(tr("settings.port"), self.port)
        app_form.addRow(self.write_box)

        buttons = QDialogButtonBox()
        self.save_button = buttons.addButton(
            tr("settings.save"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        buttons.addButton(tr("settings.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(siigo_box)
        layout.addLayout(app_form)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ helpers
    def _show_error(self, message: str) -> None:
        self.status.setStyleSheet("color: #D32F2F;")
        self.status.setText(message)

    def _show_ok(self, message: str) -> None:
        self.status.setStyleSheet("color: #2E7D32;")
        self.status.setText(message)

    def credentials_from_form(self) -> SiigoCredentials | None:
        """Validated credentials, or None (with an error shown)."""
        tr = self.tr_
        username = self.username.text().strip()
        access_key = self.access_key.text().strip()
        partner_id = self.partner_id.text().strip() or DEFAULT_PARTNER_ID
        if not username:
            self._show_error(tr("settings.error.username"))
            return None
        if not access_key:
            saved = self.runtime.credentials()
            if saved is None:
                self._show_error(tr("settings.error.access_key"))
                return None
            access_key = saved.access_key
        if not is_valid_partner_id(partner_id):
            self._show_error(tr("settings.error.partner_id"))
            return None
        return SiigoCredentials(username, access_key, partner_id)

    # ------------------------------------------------------------------ actions
    def _write_clicked(self, checked: bool) -> None:
        switch = self.runtime.write_switch
        if checked:
            dialog = WriteActionsDialog(self.tr_, self)
            dialog.exec()
            if dialog.accepted_responsibility:
                switch.enable(accepted_responsibility=True)
        else:
            switch.disable()
        self.write_box.setChecked(switch.enabled)

    def _test(self) -> None:
        credentials = self.credentials_from_form()
        if credentials is None:
            return
        self.test_button.setEnabled(False)
        self.status.setStyleSheet("")
        self.status.setText(self.tr_("settings.test.running"))

        def work() -> None:
            self._test_result.finished.emit(self.runtime.test_credentials(credentials))

        threading.Thread(target=work, name="siigo-test", daemon=True).start()

    def _test_finished(self, error: object) -> None:
        self.test_button.setEnabled(True)
        if error is None:
            self._show_ok(self.tr_("settings.test.ok"))
        else:
            self._show_error(self.tr_("settings.test.fail", error=error))

    def _clear(self) -> None:
        self.runtime.clear_credentials()
        self.username.clear()
        self.access_key.clear()
        self.access_key.setPlaceholderText("")
        self.partner_id.setText(DEFAULT_PARTNER_ID)
        self._has_saved_key = False
        self.status.clear()

    def _save(self) -> None:
        if self.username.text().strip() or self.access_key.text().strip() or self._has_saved_key:
            credentials = self.credentials_from_form()
            if credentials is None:
                return
            self.runtime.save_credentials(credentials)
        language: Language | None = self.language.currentData()
        if language != self.runtime.vault.get_setting(SETTING_LANGUAGE):
            self.runtime.vault.set_setting(SETTING_LANGUAGE, language)
            self.tr_.set_language(language)
            self.language_changed.emit()
        if self.port.value() != self.runtime.port:
            self.runtime.set_port(self.port.value())
            QMessageBox.information(self, self.tr_("settings.title"), self.tr_("settings.restart"))
        self.access_key.clear()
        self.accept()


class AboutDialog(QDialog):
    """The About text from plan section 1.1, with LinkedIn and website buttons (P8)."""

    def __init__(self, tr: Translator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("about.title"))
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(480)

        title = QLabel(f"<h2>{tr('app.name')}</h2>{tr('about.version', version=__version__)}")
        body = QLabel(tr("about.body"))
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)

        self.linkedin_button = QPushButton(tr("about.linkedin"))
        self.linkedin_button.setDefault(True)
        self.linkedin_button.clicked.connect(lambda: _open(LINKEDIN_URL))
        website = QPushButton(tr("about.website"))
        website.clicked.connect(lambda: _open(WEBSITE_URL))
        source = QPushButton(tr("about.source"))
        source.clicked.connect(lambda: _open(REPOSITORY_URL))
        close = QPushButton(tr("about.close"))
        close.clicked.connect(self.accept)

        row = QHBoxLayout()
        row.addWidget(self.linkedin_button)
        row.addWidget(website)
        row.addWidget(source)
        row.addStretch(1)
        row.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addLayout(row)


def _open(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))
