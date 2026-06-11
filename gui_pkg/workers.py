from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from gui_pkg.scanner import load_conflicts_cache, scan_module


class ModuleScanWorker(QThread):
    module_scanned = pyqtSignal(str, dict)
    finished_scan = pyqtSignal()

    def __init__(self, modules: list[Path], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._modules = modules

    def run(self) -> None:
        conflicts_cache = load_conflicts_cache()
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(scan_module, mod, conflicts_cache): mod for mod in self._modules
            }
            for fut in as_completed(futures):
                mod = futures[fut]
                try:
                    stats = fut.result()
                except Exception:
                    stats = scan_module(mod, conflicts_cache)
                self.module_scanned.emit(mod.name, stats)
        self.finished_scan.emit()
