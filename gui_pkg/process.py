from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QProcess, pyqtSignal

from gui_pkg.config import REPO_ROOT


class ProcessController(QObject):
    line_received = pyqtSignal(str, str)
    started = pyqtSignal(str)
    finished = pyqtSignal(int)
    status_changed = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_finished)
        self._queue: list[tuple[list[str], str, str | None, str | Path | None]] = []
        self._running = False
        self._current_label = ""
        self._last_lines: list[str] = []

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_label(self) -> str:
        return self._current_label

    def enqueue(self, args: list[str], label: str) -> None:
        self._queue.append((args, label, None, None))
        if not self._running:
            self._start_next()

    def run_single(self, args: list[str], label: str) -> None:
        self._queue = [(args, label, None, None)]
        if self._running:
            self.kill()
        else:
            self._start_next()

    def enqueue_program(
        self,
        program: str,
        args: list[str],
        label: str,
        *,
        cwd: str | Path | None = None,
    ) -> None:
        self._queue.append((args, label, program, cwd))
        if not self._running:
            self._start_next()

    def run_program(
        self,
        program: str,
        args: list[str],
        label: str,
        *,
        cwd: str | Path | None = None,
    ) -> None:
        self._queue = [(args, label, program, cwd)]
        if self._running:
            self.kill()
        else:
            self._start_next()

    def _start_next(self) -> None:
        if not self._queue:
            self._running = False
            self.status_changed.emit("Готово")
            return
        args, label, program, cwd = self._queue.pop(0)
        self._current_label = label
        self._last_lines = []
        self._running = True
        self.started.emit(label)
        self.status_changed.emit(f"Выполняется: {label}…")
        work_dir = str(cwd) if cwd else str(REPO_ROOT)
        self._process.setWorkingDirectory(work_dir)
        if program:
            self._process.start(program, args)
        else:
            self._process.start(sys.executable, args)

    def _on_stdout(self) -> None:
        data = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            self._last_lines.append(line)
            if len(self._last_lines) > 50:
                self._last_lines.pop(0)
            self.line_received.emit(line, "stdout")

    def _on_stderr(self) -> None:
        data = bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            self._last_lines.append(line)
            if len(self._last_lines) > 50:
                self._last_lines.pop(0)
            self.line_received.emit(line, "stderr")

    def _on_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        has_more = bool(self._queue)
        if not has_more:
            self._running = False
        self.finished.emit(exit_code)
        if has_more:
            self._start_next()
        elif exit_code == 0:
            self.status_changed.emit("Готово")
        else:
            self.status_changed.emit("Ошибка")

    def kill(self) -> None:
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
        self._queue.clear()
        self._running = False
        self.status_changed.emit("Прервано")

    def last_lines_text(self) -> str:
        return "\n".join(self._last_lines[-15:])
