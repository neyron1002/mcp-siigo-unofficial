"""The Siigo approval window (plan section 5.1, decisions W1, W4, W6, W7).

One window per write request. It shows a summary, the full request on demand, and a
countdown; the answer goes back to :class:`ApprovalBroker`. Only a person's click
answers it: no MCP tool can reach it.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mcp_siigo_unofficial.app.icons import app_icon
from mcp_siigo_unofficial.i18n import Translator
from mcp_siigo_unofficial.server.approval import ApprovalRequest, Decision

AnswerCallback = Callable[[str, Decision], None]


def format_seconds(seconds: float) -> str:
    total = max(0, int(seconds + 0.999))
    return f"{total // 60}:{total % 60:02d}"


class ApprovalWindow(QDialog):
    """Approve / Reject / Approve similar writes for 10 minutes."""

    def __init__(
        self,
        request: ApprovalRequest,
        tr: Translator,
        on_answer: AnswerCallback,
        parent: QWidget | None = None,
        clock: Callable[[], float] = time.monotonic,
        seconds_left: float | None = None,
    ) -> None:
        super().__init__(parent)
        self.request = request
        self._tr = tr
        self._on_answer = on_answer
        self._clock = clock
        left = request.timeout_s if seconds_left is None else seconds_left
        self._total = max(0.0, left)
        self._deadline = clock() + self._total
        self.decision: Decision | None = None
        self._silent = False

        self.setWindowTitle(tr("approval.window_title"))
        self.setWindowIcon(app_icon(write_mode=True))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(520)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        headline = QLabel(tr("approval.headline", client=request.client, title=request.title))
        headline.setWordWrap(True)
        font = headline.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.15)
        headline.setFont(font)
        warning = QLabel(tr("approval.warning"))
        warning.setWordWrap(True)

        form = QFormLayout()
        form.addRow(tr("approval.field.action"), QLabel(request.title))
        for name, value in request.summary:
            label = QLabel(value)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(name, label)
        form.addRow(tr("approval.field.client"), QLabel(request.client))

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlainText(self._details_text())
        self.details.setMinimumHeight(180)
        self.details.setVisible(False)
        self.details_button = QPushButton(tr("approval.details.show"))
        self.details_button.setFlat(True)
        self.details_button.clicked.connect(self.toggle_details)

        self.countdown = QLabel()
        self.similar_hint = QLabel(tr("approval.similar_hint", title=request.title))
        self.similar_hint.setWordWrap(True)

        self.reject_button = QPushButton(tr("approval.reject"))
        self.similar_button = QPushButton(tr("approval.approve_similar"))
        self.approve_button = QPushButton(tr("approval.approve"))
        self.reject_button.setDefault(True)  # Enter never approves by accident
        self.reject_button.clicked.connect(lambda: self.answer(Decision.REJECT))
        self.similar_button.clicked.connect(lambda: self.answer(Decision.APPROVE_SIMILAR))
        self.approve_button.clicked.connect(lambda: self.answer(Decision.APPROVE))

        buttons = QHBoxLayout()
        buttons.addWidget(self.reject_button)
        buttons.addStretch(1)
        buttons.addWidget(self.similar_button)
        buttons.addWidget(self.approve_button)

        layout = QVBoxLayout(self)
        layout.addWidget(headline)
        layout.addWidget(warning)
        layout.addLayout(form)
        layout.addWidget(self.details_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.details)
        layout.addWidget(self.countdown)
        layout.addWidget(self.similar_hint)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()

    def _details_text(self) -> str:
        r = self.request
        lines = [f"{r.method} {r.url}"]
        if r.query:
            lines.append("Query: " + json.dumps(r.query, ensure_ascii=False))
        if r.body is not None:
            lines.append(json.dumps(r.body, ensure_ascii=False, indent=2, default=str))
        return "\n".join(lines)

    def seconds_left(self) -> float:
        # Capped at the total: with a large clock value, (now + t) - now can be a
        # rounding error above t (seen on Windows CI).
        return min(self._total, max(0.0, self._deadline - self._clock()))

    def _tick(self) -> None:
        left = self.seconds_left()
        self.countdown.setText(self._tr("approval.countdown", time=format_seconds(left)))
        if left <= 0:
            self._timer.stop()
            self.close_without_answer()

    def toggle_details(self) -> None:
        visible = not self.details.isVisible()
        self.details.setVisible(visible)
        self.details_button.setText(
            self._tr("approval.details.hide" if visible else "approval.details.show")
        )
        self.adjustSize()

    def answer(self, decision: Decision) -> None:
        if self.decision is not None:
            return
        self.decision = decision
        self._timer.stop()
        self._on_answer(self.request.id, decision)
        self.accept()

    def close_without_answer(self) -> None:
        """Closed by the broker (timeout) or by the time running out: no answer sent."""
        self._silent = True
        self._timer.stop()
        super().done(QDialog.DialogCode.Rejected)

    def _reject_by_person(self) -> None:
        if self.decision is None and not self._silent:
            self.decision = Decision.REJECT
            self._timer.stop()
            self._on_answer(self.request.id, Decision.REJECT)

    def reject(self) -> None:
        """Escape key: the same as Reject."""
        self._reject_by_person()
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        """The title bar's close button: the same as Reject."""
        self._reject_by_person()
        super().closeEvent(event)

    def bring_to_front(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
