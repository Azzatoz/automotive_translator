"""Стек отмены для окна заглушек."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UndoRecord:
    """Снимок values-ru до одной операции записи."""

    snapshots: dict[str, str] = field(default_factory=dict)


class PlaceholderUndoStack:
    def __init__(self) -> None:
        self._stack: list[UndoRecord] = []

    def push(self, snapshots: dict[str, str]) -> None:
        if snapshots:
            self._stack.append(UndoRecord(snapshots=dict(snapshots)))

    def can_undo(self) -> bool:
        return bool(self._stack)

    def pop(self) -> UndoRecord | None:
        if not self._stack:
            return None
        return self._stack.pop()

    def drain_merged(self) -> dict[str, str]:
        """Снять весь стек; для каждой строки — значение до первой записи в сессии."""
        merged: dict[str, str] = {}
        for record in self._stack:
            for row_id, old_ru in record.snapshots.items():
                if row_id not in merged:
                    merged[row_id] = old_ru
        self._stack.clear()
        return merged

    def clear(self) -> None:
        self._stack.clear()

    def depth(self) -> int:
        return len(self._stack)
