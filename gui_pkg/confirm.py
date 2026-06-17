"""Подтверждения перед опасными операциями."""

from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox, QWidget


def confirm_dangerous_action(
    parent: QWidget | None,
    *,
    title: str,
    summary: str,
    details: str = "",
) -> bool:
    body = summary
    if details:
        body = f"{summary}\n\n{details}"
    answer = QMessageBox.question(
        parent,
        title,
        body,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes
