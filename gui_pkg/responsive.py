from __future__ import annotations

from PyQt6.QtWidgets import QGridLayout, QWidget

# Панель модулей — три фиксированных режима (не непрерывный ресайз)
SIDEBAR_OPEN_WIDTH = 400
SIDEBAR_MODE_HIDDEN = "hidden"
SIDEBAR_MODE_OPEN = "open"
SIDEBAR_MODE_FULL = "full"
SIDEBAR_MODES = (SIDEBAR_MODE_HIDDEN, SIDEBAR_MODE_OPEN, SIDEBAR_MODE_FULL)
SIDEBAR_DEFAULT_MODE = SIDEBAR_MODE_OPEN

# Точки перелома (ширина контентной области)
BREAKPOINT_NARROW = 960
BREAKPOINT_COMPACT = 720
BREAKPOINT_SINGLE_COL = 520
BREAKPOINT_TWO_COL = 720


def normalize_sidebar_mode(mode: str | None) -> str:
    if mode in SIDEBAR_MODES:
        return mode
    return SIDEBAR_DEFAULT_MODE


def next_sidebar_mode(mode: str) -> str:
    order = list(SIDEBAR_MODES)
    try:
        idx = order.index(mode)
    except ValueError:
        idx = order.index(SIDEBAR_DEFAULT_MODE)
    return order[(idx + 1) % len(order)]


def sidebar_mode_button_icon(mode: str) -> str:
    return {
        SIDEBAR_MODE_HIDDEN: "☰",
        SIDEBAR_MODE_OPEN: "▤",
        SIDEBAR_MODE_FULL: "▥",
    }.get(mode, "▤")


def sidebar_mode_tooltip(mode: str) -> str:
    labels = {
        SIDEBAR_MODE_HIDDEN: "Модули скрыты",
        SIDEBAR_MODE_OPEN: "Модули открыты",
        SIDEBAR_MODE_FULL: "Только модули",
    }
    label = labels.get(mode, labels[SIDEBAR_DEFAULT_MODE])
    return f"{label} — нажмите, чтобы сменить режим"


def relayout_grid(
    grid: QGridLayout,
    widgets: list[QWidget],
    *,
    container_width: int,
    wide_columns: int,
    narrow_columns: int = 2,
    breakpoint: int = BREAKPOINT_NARROW,
) -> None:
    """Перестраивает сетку: на узком экране — меньше колонок."""
    if not widgets:
        return

    cols = wide_columns if container_width >= breakpoint else narrow_columns
    cols = max(1, min(cols, len(widgets)))

    for widget in widgets:
        grid.removeWidget(widget)

    for i, widget in enumerate(widgets):
        row, col = divmod(i, cols)
        grid.addWidget(widget, row, col)

    for c in range(cols):
        grid.setColumnStretch(c, 1)


def title_bar_compact(width: int) -> bool:
    return width < BREAKPOINT_COMPACT


def action_grid_columns(container_width: int, item_count: int, *, max_columns: int = 4) -> int:
    """Число колонок для сетки кнопок: 1 → 2 → 3 → 4 по ширине."""
    if item_count <= 1:
        return 1
    if container_width < BREAKPOINT_SINGLE_COL:
        return 1
    if container_width < BREAKPOINT_TWO_COL:
        return min(2, item_count)
    if container_width < BREAKPOINT_NARROW:
        return min(3, item_count)
    return min(max_columns, item_count)


def relayout_action_grid(
    grid: QGridLayout,
    buttons: list,
    *,
    container_width: int,
    max_columns: int = 4,
) -> None:
    """Сетка кнопок с динамическим числом колонок и подгонкой высоты под текст."""
    if not buttons:
        return

    cols = action_grid_columns(container_width, len(buttons), max_columns=max_columns)
    margins = grid.contentsMargins()
    inner_w = max(120, container_width - margins.left() - margins.right())
    spacing = grid.spacing()
    cell_w = max(120, (inner_w - spacing * max(0, cols - 1)) // cols)

    for btn in buttons:
        grid.removeWidget(btn)

    for i, btn in enumerate(buttons):
        row, col = divmod(i, cols)
        grid.addWidget(btn, row, col)

    for c in range(cols):
        grid.setColumnStretch(c, 1)

    for btn in buttons:
        fit = getattr(btn, "fit_cell_width", None)
        if callable(fit):
            fit(cell_w)
