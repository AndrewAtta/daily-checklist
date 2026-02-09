#!/usr/bin/env python3
"""Daily Checklist – a native Linux desktop calendar-checklist app."""

import fcntl
import json
import os
import signal
import sys
from datetime import date, timedelta
from pathlib import Path

from PyQt5.QtCore import Qt, QDate, QMimeData, QPoint, QRect, pyqtSignal
from PyQt5.QtGui import QColor, QDrag, QFont, QPainter, QPen, QPixmap, QTextCharFormat
from PyQt5.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

TASKS_PER_DAY = 5
DATA_DIR = Path.home() / ".local" / "share" / "daily-checklist"

# ── Ubuntu Yaru-inspired palette ──────────────────────────────────────
UBUNTU_BG = "#2c2c2c"
UBUNTU_SURFACE = "#3d3d3d"
UBUNTU_SURFACE_LIGHT = "#4a4a4a"
UBUNTU_BORDER = "#505050"
UBUNTU_TEXT = "#f0f0f0"
UBUNTU_TEXT_DIM = "#999999"
UBUNTU_ACCENT = "#e95420"  # Ubuntu orange
UBUNTU_GREEN = "#27ae60"

# Progress bar: left colour (incomplete) → right colour (complete)
BAR_BG = QColor("#4a4a4a")       # empty portion
BAR_RED = QColor("#c0392b")      # 0% fill colour
BAR_GREEN = QColor("#27ae60")    # 100% fill colour
NO_TASK_BG = QColor("#3d3d3d")   # no tasks entered


def _lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
    """Linearly interpolate between two colours (t in 0..1)."""
    return QColor(
        int(c1.red() + (c2.red() - c1.red()) * t),
        int(c1.green() + (c2.green() - c1.green()) * t),
        int(c1.blue() + (c2.blue() - c1.blue()) * t),
    )


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


def task_counts(day: date) -> tuple[int, int]:
    """Return (completed, total_with_text).  (-1,-1) if no tasks."""
    data = load_day(day)
    if data is None:
        return (-1, -1)
    total = sum(1 for t in data if t["text"].strip())
    if total == 0:
        return (-1, -1)
    done = sum(1 for t in data if t["done"] and t["text"].strip())
    return (done, total)


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
        return

    # Fill empty slots first
    slot = 0
    remaining = list(incomplete)
    for task in list(remaining):
        while slot < len(today_data) and today_data[slot]["text"].strip():
            slot += 1
        if slot >= len(today_data):
            break
        today_data[slot]["text"] = task["text"]
        today_data[slot]["done"] = False
        today_data[slot]["carried"] = True
        remaining.remove(task)
        slot += 1

    # Append any that didn't fit into existing slots
    for task in remaining:
        today_data.append({"text": task["text"], "done": False, "carried": True})

    save_day(today, today_data)


# ── Custom calendar widget ────────────────────────────────────────────
class ColouredCalendar(QCalendarWidget):
    """Calendar with progress-bar day cells and completion counts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(420)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFirstDayOfWeek(Qt.Monday)

        # Force weekday header text colours – Qt ignores stylesheet for these
        fmt = self.headerTextFormat()
        fmt.setForeground(QColor(UBUNTU_TEXT))
        fmt.setBackground(QColor(UBUNTU_SURFACE))
        self.setHeaderTextFormat(fmt)

        # Also override the per-day-of-week formats (Sun=red, Sat=blue by default)
        for day in range(1, 8):  # Qt::Monday=1 … Qt::Sunday=7
            wfmt = self.weekdayTextFormat(Qt.DayOfWeek(day))
            wfmt.setForeground(QColor(UBUNTU_TEXT))
            wfmt.setBackground(QColor(UBUNTU_SURFACE))
            self.setWeekdayTextFormat(Qt.DayOfWeek(day), wfmt)

    def paintCell(self, painter: QPainter, rect, qdate: QDate):
        day = date(qdate.year(), qdate.month(), qdate.day())

        # Dim out-of-month cells
        if qdate.month() != self.monthShown() or qdate.year() != self.yearShown():
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setBrush(QColor("#333333"))
            painter.setPen(Qt.NoPen)
            m = 2
            painter.drawRoundedRect(rect.adjusted(m, m, -m, -m), 6, 6)
            painter.setPen(QColor("#666666"))
            font = painter.font()
            font.setPointSize(10)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, str(qdate.day()))
            painter.restore()
            return

        done, total = task_counts(day)
        has_tasks = done >= 0

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        m = 2
        cell = rect.adjusted(m, m, -m, -m)

        if not has_tasks:
            # No tasks: plain dark cell
            painter.setBrush(NO_TASK_BG)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(cell, 6, 6)
        else:
            # Draw background: red if 0 completed, grey otherwise
            fraction = done / total if total > 0 else 0.0
            painter.setBrush(BAR_RED if fraction == 0 else BAR_BG)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(cell, 6, 6)

            # Draw filled portion left→right
            if fraction > 0:
                fill_color = _lerp_color(BAR_RED, BAR_GREEN, fraction)
                fill_width = int(cell.width() * fraction)
                fill_rect = QRect(cell.left(), cell.top(), fill_width, cell.height())

                # Clip to rounded shape
                from PyQt5.QtGui import QPainterPath
                clip_path = QPainterPath()
                clip_path.addRoundedRect(float(cell.left()), float(cell.top()),
                                         float(cell.width()), float(cell.height()), 6, 6)
                painter.setClipPath(clip_path)
                painter.setBrush(fill_color)
                painter.drawRect(fill_rect)
                painter.setClipping(False)

        # Today outline
        if day == date.today():
            painter.setPen(QPen(QColor(UBUNTU_ACCENT), 2.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(cell, 6, 6)

        # Day number (top-left area)
        painter.setPen(QColor(UBUNTU_TEXT))
        font = painter.font()
        font.setPointSize(11)
        font.setBold(day == date.today())
        painter.setFont(font)

        text_rect = QRect(cell.left() + 6, cell.top() + 2, cell.width() - 12, cell.height() // 2)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, str(qdate.day()))

        # Completion count (bottom portion, smaller)
        if has_tasks:
            count_font = QFont(painter.font())
            count_font.setPointSize(8)
            count_font.setBold(False)
            painter.setFont(count_font)
            count_color = QColor("#ffffff") if done == total else QColor("#cccccc")
            painter.setPen(count_color)
            count_rect = QRect(cell.left() + 6, cell.top() + cell.height() // 2,
                               cell.width() - 12, cell.height() // 2 - 2)
            painter.drawText(count_rect, Qt.AlignLeft | Qt.AlignVCenter, f"{done}/{total}")

        painter.restore()


# ── Drag handle label ─────────────────────────────────────────────────
class DragHandle(QLabel):
    """A small grip icon that initiates drag when clicked."""

    def __init__(self, parent=None):
        super().__init__("\u2630", parent)  # ☰ trigram
        self.setCursor(Qt.OpenHandCursor)
        self.setFixedWidth(20)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"color: {UBUNTU_TEXT_DIM}; font-size: 14px;")
        self._drag_start = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.pos()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._drag_start is None:
            return
        if (event.pos() - self._drag_start).manhattanLength() < QApplication.startDragDistance():
            return

        # Find the TaskRow parent
        task_row = self.parent()
        while task_row and not isinstance(task_row, TaskRow):
            task_row = task_row.parent()
        if not task_row:
            return

        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(str(task_row.index))
        drag.setMimeData(mime)

        # Create a snapshot of the row as drag pixmap
        pixmap = task_row.grab()
        drag.setPixmap(pixmap.scaled(pixmap.width(), pixmap.height()))
        drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))

        self.setCursor(Qt.OpenHandCursor)
        self._drag_start = None
        drag.exec_(Qt.MoveAction)

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        self.setCursor(Qt.OpenHandCursor)


# ── Task row widget ───────────────────────────────────────────────────
class TaskRow(QWidget):
    changed = pyqtSignal()
    removed = pyqtSignal()

    def __init__(self, index: int, task: dict, parent=None):
        super().__init__(parent)
        self.index = index
        self.task = task
        self.setAcceptDrops(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self.drag_handle = DragHandle(self)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(task["done"])
        self.checkbox.stateChanged.connect(self._on_toggle)

        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText(f"Task {index + 1}")
        self.text_edit.setText(task["text"])
        self.text_edit.textChanged.connect(self._on_text)
        self._apply_strike()

        remove_btn = QPushButton("\u00d7")
        remove_btn.setObjectName("removeTaskBtn")
        remove_btn.setFixedSize(24, 24)
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.setToolTip("Remove task")
        remove_btn.clicked.connect(self.removed.emit)

        layout.addWidget(self.drag_handle)
        layout.addWidget(self.checkbox)
        layout.addWidget(self.text_edit)

        if task.get("carried"):
            tag = QLabel("carried")
            tag.setStyleSheet(
                f"background: {UBUNTU_ACCENT}; color: white; border-radius: 6px;"
                "padding: 1px 6px; font-size: 11px;"
            )
            layout.addWidget(tag)

        layout.addWidget(remove_btn)

        self._drop_indicator_visible = False

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
            self.text_edit.setStyleSheet(f"color: {UBUNTU_TEXT_DIM};")
        else:
            self.text_edit.setStyleSheet(f"color: {UBUNTU_TEXT};")

    # ── Drop target ──
    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
            self._drop_indicator_visible = True
            self.update()

    def dragLeaveEvent(self, event):
        self._drop_indicator_visible = False
        self.update()

    def dropEvent(self, event):
        self._drop_indicator_visible = False
        self.update()
        source_index = int(event.mimeData().text())
        target_index = self.index
        if source_index != target_index:
            # Find MainWindow and call reorder
            w = self.window()
            if isinstance(w, MainWindow):
                w._reorder_task(source_index, target_index)
        event.acceptProposedAction()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drop_indicator_visible:
            p = QPainter(self)
            p.setPen(QPen(QColor(UBUNTU_ACCENT), 2))
            p.drawLine(0, 0, self.width(), 0)
            p.end()


# ── Main window ───────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Daily Checklist")
        self.resize(600, 820)

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
        root.addWidget(self.calendar, stretch=3)

        # ── Today button ──
        today_btn = QPushButton("Today")
        today_btn.setFixedHeight(32)
        today_btn.setCursor(Qt.PointingHandCursor)
        today_btn.clicked.connect(self._jump_to_today)
        root.addWidget(today_btn)

        # ── Legend ──
        legend_layout = QHBoxLayout()
        legend_layout.setSpacing(8)
        steps = [
            (BAR_BG, "no tasks"),
            (BAR_RED, "0%"),
            (_lerp_color(BAR_RED, BAR_GREEN, 0.5), "50%"),
            (BAR_GREEN, "100%"),
        ]
        for color, label_text in steps:
            swatch = QLabel()
            swatch.setFixedSize(16, 16)
            swatch.setStyleSheet(
                f"background: {color.name()}; border-radius: 3px;"
            )
            lbl = QLabel(label_text)
            lbl.setStyleSheet(f"color: {UBUNTU_TEXT_DIM}; font-size: 12px;")
            legend_layout.addWidget(swatch)
            legend_layout.addWidget(lbl)
        legend_layout.addStretch()
        root.addLayout(legend_layout)

        # ── Checklist header ──
        self.checklist_label = QLabel()
        self.checklist_label.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {UBUNTU_TEXT};"
        )
        root.addWidget(self.checklist_label)

        # ── Task rows container ──
        self.task_container = QVBoxLayout()
        self.task_container.setSpacing(4)
        root.addLayout(self.task_container)

        # ── Add Task button ──
        self.add_task_btn = QPushButton("+ Add Task")
        self.add_task_btn.setFixedHeight(30)
        self.add_task_btn.setCursor(Qt.PointingHandCursor)
        self.add_task_btn.setObjectName("addTaskBtn")
        self.add_task_btn.clicked.connect(self._add_task)
        root.addWidget(self.add_task_btn)

        root.addStretch()

        info = QLabel("Click a day to edit its checklist. Incomplete tasks carry over automatically.")
        info.setStyleSheet(f"color: {UBUNTU_TEXT_DIM}; font-size: 12px;")
        info.setAlignment(Qt.AlignCenter)
        root.addWidget(info)

        self.selected_date = date.today()
        self._render_checklist()

    def _jump_to_today(self):
        today = date.today()
        self.calendar.setSelectedDate(QDate(today.year, today.month, today.day))
        self.selected_date = today
        self._render_checklist()

    def _on_date_clicked(self, qdate: QDate):
        self.selected_date = date(qdate.year(), qdate.month(), qdate.day())
        self._render_checklist()

    def _render_checklist(self):
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

        self._current_data = data

        has_carried = any(t.get("carried") for t in data)
        suffix = "  (has carry-over tasks)" if has_carried else ""
        self.checklist_label.setText(day_label + suffix)

        for i in range(len(data)):
            row = TaskRow(i, data[i])
            row.changed.connect(lambda d=day, dt=data: self._on_task_changed(d, dt))
            row.removed.connect(lambda idx=i: self._remove_task(idx))
            self.task_container.addWidget(row)

    def _add_task(self):
        day = self.selected_date
        data = load_day(day)
        if data is None:
            data = blank_tasks()
        data.append({"text": "", "done": False, "carried": False})
        save_day(day, data)
        self._render_checklist()
        self.calendar.updateCells()

    def _remove_task(self, index: int):
        day = self.selected_date
        data = load_day(day)
        if data is None or index >= len(data):
            return
        data.pop(index)
        save_day(day, data)
        self._render_checklist()
        self.calendar.updateCells()

    def _reorder_task(self, from_index: int, to_index: int):
        day = self.selected_date
        data = load_day(day)
        if data is None or from_index >= len(data) or to_index >= len(data):
            return
        task = data.pop(from_index)
        data.insert(to_index, task)
        save_day(day, data)
        self._render_checklist()

    def _on_task_changed(self, day: date, tasks: list[dict]):
        save_day(day, tasks)
        self.calendar.updateCells()


# ── Ubuntu Yaru Dark stylesheet ───────────────────────────────────────
STYLESHEET = f"""
QMainWindow, QWidget {{
    background: {UBUNTU_BG};
    color: {UBUNTU_TEXT};
    font-family: 'Ubuntu', 'Cantarell', sans-serif;
}}
QCalendarWidget {{
    background: {UBUNTU_SURFACE};
    border: 1px solid {UBUNTU_BORDER};
    border-radius: 8px;
}}
QCalendarWidget QToolButton {{
    color: {UBUNTU_TEXT};
    background: {UBUNTU_SURFACE_LIGHT};
    border: none;
    border-radius: 4px;
    padding: 8px 14px;
    font-size: 14px;
    font-weight: bold;
}}
QCalendarWidget QToolButton:hover {{
    background: {UBUNTU_ACCENT};
}}
QCalendarWidget QMenu {{
    background: {UBUNTU_SURFACE};
    color: {UBUNTU_TEXT};
    border: 1px solid {UBUNTU_BORDER};
}}
QCalendarWidget QMenu::item:selected {{
    background: {UBUNTU_ACCENT};
}}
QCalendarWidget QSpinBox {{
    background: {UBUNTU_SURFACE_LIGHT};
    color: {UBUNTU_TEXT};
    border: none;
    padding: 4px;
}}
QCalendarWidget QAbstractItemView {{
    background: {UBUNTU_SURFACE};
    selection-background-color: {UBUNTU_ACCENT};
    selection-color: #ffffff;
    color: {UBUNTU_TEXT};
    outline: none;
}}
QCalendarWidget QWidget#qt_calendar_navigationbar {{
    background: {UBUNTU_SURFACE_LIGHT};
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 4px;
}}
QCalendarWidget QHeaderView {{
    background: {UBUNTU_SURFACE};
}}
QCalendarWidget QHeaderView::section {{
    background: {UBUNTU_SURFACE};
    color: {UBUNTU_TEXT};
    border: none;
    padding: 4px;
    font-weight: bold;
    font-size: 13px;
}}
QCheckBox::indicator {{
    width: 20px;
    height: 20px;
}}
QCheckBox::indicator:unchecked {{
    border: 2px solid {UBUNTU_BORDER};
    border-radius: 4px;
    background: transparent;
}}
QCheckBox::indicator:checked {{
    border: 2px solid {UBUNTU_GREEN};
    border-radius: 4px;
    background: {UBUNTU_GREEN};
}}
QLineEdit {{
    background: {UBUNTU_SURFACE_LIGHT};
    border: none;
    border-bottom: 1px solid {UBUNTU_BORDER};
    border-radius: 4px;
    padding: 6px 8px;
    color: {UBUNTU_TEXT};
    font-size: 14px;
}}
QLineEdit:focus {{
    border-bottom: 2px solid {UBUNTU_ACCENT};
}}
QPushButton {{
    background: {UBUNTU_ACCENT};
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 13px;
    font-weight: bold;
}}
QPushButton:hover {{
    background: #d14510;
}}
QPushButton:pressed {{
    background: #b83d0e;
}}
QPushButton#addTaskBtn {{
    background: {UBUNTU_SURFACE_LIGHT};
    border: 1px dashed {UBUNTU_BORDER};
    color: {UBUNTU_TEXT_DIM};
    font-weight: normal;
}}
QPushButton#addTaskBtn:hover {{
    background: {UBUNTU_BORDER};
    color: {UBUNTU_TEXT};
}}
QPushButton#removeTaskBtn {{
    background: transparent;
    border: none;
    color: {UBUNTU_TEXT_DIM};
    font-size: 16px;
    font-weight: bold;
    border-radius: 12px;
    padding: 0px;
}}
QPushButton#removeTaskBtn:hover {{
    background: #c0392b;
    color: #ffffff;
}}
DragHandle {{
    color: {UBUNTU_TEXT_DIM};
    font-size: 14px;
    padding: 0px;
    background: transparent;
}}
"""


LOCK_FILE = DATA_DIR / "daily-checklist.lock"
PID_FILE = DATA_DIR / "daily-checklist.pid"


def _raise_existing_instance() -> bool:
    """Try to raise an already-running instance. Return True if successful."""
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        # Check the process is alive
        os.kill(pid, 0)
        # Send SIGUSR1 to tell it to raise its window
        os.kill(pid, signal.SIGUSR1)
        return True
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        return False


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Try to raise an existing instance before creating QApplication
    if _raise_existing_instance():
        print("Raised existing instance.")
        sys.exit(0)

    # Acquire an exclusive lock (non-blocking)
    lock_fp = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Another instance grabbed the lock between our check and here
        if _raise_existing_instance():
            sys.exit(0)
        # Fall through and start anyway if we can't signal it
    PID_FILE.write_text(str(os.getpid()))

    app = QApplication(sys.argv)
    app.setApplicationName("Daily Checklist")
    app.setStyleSheet(STYLESHEET)

    window = MainWindow()
    window.show()

    # Handle SIGUSR1: raise & activate the window
    def _handle_raise(signum, frame):
        window.showNormal()
        window.activateWindow()
        window.raise_()

    signal.signal(signal.SIGUSR1, _handle_raise)

    # Make sure Python can process signals while Qt event loop runs
    import socket
    rsock, wsock = socket.socketpair()
    rsock.setblocking(False)
    wsock.setblocking(False)

    from PyQt5.QtCore import QSocketNotifier
    notifier = QSocketNotifier(rsock.fileno(), QSocketNotifier.Read)
    notifier.activated.connect(lambda: rsock.recv(1))

    old_wakeup = signal.set_wakeup_fd(wsock.fileno())

    ret = app.exec_()

    # Cleanup
    signal.set_wakeup_fd(old_wakeup)
    rsock.close()
    wsock.close()
    try:
        PID_FILE.unlink()
    except OSError:
        pass
    lock_fp.close()
    sys.exit(ret)


if __name__ == "__main__":
    main()
