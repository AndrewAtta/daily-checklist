#!/usr/bin/env python3
"""Daily Checklist – a native Linux desktop calendar-checklist app."""

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from PyQt5.QtCore import Qt, QDate, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

TASKS_PER_DAY = 5
DATA_DIR = Path.home() / ".local" / "share" / "daily-checklist"

# ── Colour scale: 0/5 → red … 5/5 → green ────────────────────────────
COMPLETION_COLORS = [
    QColor("#c0392b"),  # 0 / 5  – red
    QColor("#d35400"),  # 1 / 5
    QColor("#d4a017"),  # 2 / 5
    QColor("#7dab3e"),  # 3 / 5
    QColor("#3d9b40"),  # 4 / 5
    QColor("#27ae60"),  # 5 / 5  – green
]
NO_TASK_COLOR = QColor("#2c3e6b")


# ── Data helpers ───────────────────────────────────────────────────────
def _data_path(day: date) -> Path:
    return DATA_DIR / f"{day.isoformat()}.json"


def load_day(day: date) -> list[dict] | None:
    p = _data_path(day)
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f)


def save_day(day: date, tasks: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(_data_path(day), "w") as f:
        json.dump(tasks, f)


def blank_tasks() -> list[dict]:
    return [{"text": "", "done": False, "carried": False} for _ in range(TASKS_PER_DAY)]


def completion_count(day: date) -> int:
    """Return 0-5 completed count, or -1 if no tasks entered."""
    data = load_day(day)
    if data is None:
        return -1
    if not any(t["text"].strip() for t in data):
        return -1
    return sum(1 for t in data if t["done"] and t["text"].strip())


def carry_over_tasks(today: date) -> None:
    """Copy incomplete tasks from yesterday into today's empty slots."""
    yesterday = today - timedelta(days=1)
    prev = load_day(yesterday)
    if prev is None:
        return

    incomplete = [t for t in prev if t["text"].strip() and not t["done"]]
    if not incomplete:
        return

    today_data = load_day(today)
    if today_data is None:
        today_data = blank_tasks()

    if any(t["carried"] for t in today_data):
        return  # already carried over

    slot = 0
    for task in incomplete:
        while slot < TASKS_PER_DAY and today_data[slot]["text"].strip():
            slot += 1
        if slot >= TASKS_PER_DAY:
            break
        today_data[slot]["text"] = task["text"]
        today_data[slot]["done"] = False
        today_data[slot]["carried"] = True
        slot += 1

    save_day(today, today_data)


# ── Custom calendar widget with coloured day cells ────────────────────
class ColouredCalendar(QCalendarWidget):
    def paintCell(self, painter: QPainter, rect, qdate: QDate):
        day = date(qdate.year(), qdate.month(), qdate.day())

        # Only colour cells that belong to the currently viewed month
        if qdate.month() != self.monthShown() or qdate.year() != self.yearShown():
            super().paintCell(painter, rect, qdate)
            return

        count = completion_count(day)

        if count == -1:
            bg = NO_TASK_COLOR
        else:
            bg = COMPLETION_COLORS[min(count, 5)]

        painter.save()

        # Background
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(bg)
        painter.setPen(Qt.NoPen)
        margin = 2
        painter.drawRoundedRect(rect.adjusted(margin, margin, -margin, -margin), 4, 4)

        # Today ring
        if day == date.today():
            pen = painter.pen()
            from PyQt5.QtGui import QPen
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(margin, margin, -margin, -margin), 4, 4)

        # Day number
        painter.setPen(QColor("#ffffff"))
        font = painter.font()
        font.setPointSize(10)
        font.setBold(day == date.today())
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, str(qdate.day()))

        painter.restore()


# ── Task row widget ───────────────────────────────────────────────────
class TaskRow(QWidget):
    changed = pyqtSignal()

    def __init__(self, index: int, task: dict, parent=None):
        super().__init__(parent)
        self.task = task
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(task["done"])
        self.checkbox.stateChanged.connect(self._on_toggle)

        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText(f"Task {index + 1}")
        self.text_edit.setText(task["text"])
        self.text_edit.textChanged.connect(self._on_text)
        self._apply_strike()

        layout.addWidget(self.checkbox)
        layout.addWidget(self.text_edit)

        if task.get("carried"):
            tag = QLabel("carried")
            tag.setStyleSheet(
                "background: #d35400; color: white; border-radius: 6px;"
                "padding: 1px 6px; font-size: 11px;"
            )
            layout.addWidget(tag)

    def _on_toggle(self, state):
        self.task["done"] = state == Qt.Checked
        self._apply_strike()
        self.changed.emit()

    def _on_text(self, text):
        self.task["text"] = text
        self.changed.emit()

    def _apply_strike(self):
        font = self.text_edit.font()
        font.setStrikeOut(self.task["done"])
        self.text_edit.setFont(font)
        if self.task["done"]:
            self.text_edit.setStyleSheet("color: #6a7a8a;")
        else:
            self.text_edit.setStyleSheet("color: #e0e0e0;")


# ── Main window ───────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Daily Checklist")
        self.resize(520, 680)

        carry_over_tasks(date.today())

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        # ── Calendar ──
        self.calendar = ColouredCalendar()
        self.calendar.setGridVisible(False)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.calendar.clicked.connect(self._on_date_clicked)
        root.addWidget(self.calendar)

        # ── Legend ──
        legend_layout = QHBoxLayout()
        legend_layout.setSpacing(10)
        legend_labels = ["0/5", "1/5", "2/5", "3/5", "4/5", "5/5"]
        for i, label_text in enumerate(legend_labels):
            swatch = QLabel("  ")
            swatch.setFixedSize(16, 16)
            swatch.setStyleSheet(
                f"background: {COMPLETION_COLORS[i].name()}; border-radius: 3px;"
            )
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color: #8899aa; font-size: 12px;")
            legend_layout.addWidget(swatch)
            legend_layout.addWidget(lbl)
        legend_layout.addStretch()
        root.addLayout(legend_layout)

        # ── Checklist header ──
        self.checklist_label = QLabel()
        self.checklist_label.setStyleSheet("font-size: 15px; font-weight: bold; color: white;")
        root.addWidget(self.checklist_label)

        # ── Task rows container ──
        self.task_container = QVBoxLayout()
        self.task_container.setSpacing(4)
        root.addLayout(self.task_container)

        root.addStretch()

        info = QLabel("Click a day to edit its checklist. Incomplete tasks carry over automatically.")
        info.setStyleSheet("color: #667788; font-size: 12px;")
        info.setAlignment(Qt.AlignCenter)
        root.addWidget(info)

        # Show today on launch
        self.selected_date = date.today()
        self._render_checklist()

    def _on_date_clicked(self, qdate: QDate):
        self.selected_date = date(qdate.year(), qdate.month(), qdate.day())
        self._render_checklist()

    def _render_checklist(self):
        # Clear existing task rows
        while self.task_container.count():
            item = self.task_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        day = self.selected_date
        day_label = day.strftime("%A, %B %-d, %Y")

        data = load_day(day)
        if data is None:
            data = blank_tasks()
            save_day(day, data)

        has_carried = any(t.get("carried") for t in data)
        suffix = "  (has carry-over tasks)" if has_carried else ""
        self.checklist_label.setText(day_label + suffix)

        for i in range(TASKS_PER_DAY):
            row = TaskRow(i, data[i])
            row.changed.connect(lambda d=day, dt=data: self._on_task_changed(d, dt))
            self.task_container.addWidget(row)

    def _on_task_changed(self, day: date, tasks: list[dict]):
        save_day(day, tasks)
        self.calendar.updateCells()


# ── Stylesheet ────────────────────────────────────────────────────────
STYLESHEET = """
QMainWindow, QWidget {
    background: #1a1a2e;
    color: #e0e0e0;
}
QCalendarWidget {
    background: #16213e;
    border: 1px solid #2c3e6b;
    border-radius: 8px;
}
QCalendarWidget QToolButton {
    color: #e0e0e0;
    background: #0f3460;
    border: none;
    border-radius: 4px;
    padding: 6px 12px;
    font-size: 14px;
    font-weight: bold;
}
QCalendarWidget QToolButton:hover {
    background: #1a5276;
}
QCalendarWidget QMenu {
    background: #16213e;
    color: #e0e0e0;
}
QCalendarWidget QSpinBox {
    background: #0f3460;
    color: #e0e0e0;
    border: none;
    padding: 4px;
}
QCalendarWidget QAbstractItemView {
    background: #16213e;
    selection-background-color: #0f3460;
    selection-color: #ffffff;
    color: #e0e0e0;
}
QCalendarWidget QWidget#qt_calendar_navigationbar {
    background: #0f3460;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}
QCheckBox::indicator {
    width: 20px;
    height: 20px;
}
QCheckBox::indicator:unchecked {
    border: 2px solid #2c3e6b;
    border-radius: 4px;
    background: transparent;
}
QCheckBox::indicator:checked {
    border: 2px solid #27ae60;
    border-radius: 4px;
    background: #27ae60;
}
QLineEdit {
    background: #0f3460;
    border: none;
    border-bottom: 1px solid #2c3e6b;
    border-radius: 4px;
    padding: 6px 8px;
    color: #e0e0e0;
    font-size: 14px;
}
QLineEdit:focus {
    border-bottom: 1px solid #53c7f0;
}
"""


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Daily Checklist")
    app.setStyleSheet(STYLESHEET)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
