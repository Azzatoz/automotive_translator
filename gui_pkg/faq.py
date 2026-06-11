"""Справка (FAQ) для GUI Automotive Translator."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

FAQ_HTML = """
<h2>Перевод APK и словарь — в чём разница</h2>
<p><b>Перевести приложение</b> — заполняет <code>res/values-ru</code> в модулях APK
(словарь, при необходимости Google). Это основной сценарий для готового проекта.</p>
<p><b>Пополнить общий словарь</b> — режим «заглушки»: новые строки из APK попадают
в <code>data/dictionaries/</code> с ru = « » (пробел), чтобы потом перевести пакетно.
Google не вызывается. Кнопка <b>«Заглушки в словарь»</b> делает то же самое одним кликом.</p>
<p><b>Собрать словарь из APK (Collect)</b> — читает уже переведённые values-ru со всех
модулей и обновляет общий словарь. Может показать <b>конфликты</b>: одна фраза переведена
по-разному в разных APK. На сами APK это не влияет, меняется только отчёт и бейджи в GUI.</p>

<h2>Заглушки — как добавить</h2>
<ol>
<li>Укажите папку проекта (например <code>Translated</code>).</li>
<li>На вкладке <b>Обзор</b> нажмите <b>«Заглушки в словарь»</b>
    <i>или</i> выберите задачу «Пополнить общий словарь» → «Дополнить словарь заглушками».</li>
<li>Выберите модули (все или один слева).</li>
<li>После этого переводите: «Словарь + Google» или вручную в словаре / вкладке Конфликты.</li>
</ol>

<h2>Шаблон конфликтов</h2>
<p>Создаёт файлы <code>data/resolutions/*_resolutions.json</code> из отчётов
<code>reports/*_conflicts.json</code>. В каждой записи поле <code>chosen</code> —
выбранный русский вариант (по умолчанию — тот, что встречается в большинстве модулей).</p>
<p>Дальше: отредактировать <code>chosen</code> при необходимости → на вкладке
<b>Конфликты</b> сохранить решения → при желании снова Collect.</p>
<p>Это <b>не</b> переводит APK напрямую — только выравнивает общий словарь.</p>

<h2>Формат дат</h2>
<p>Правит в словарях ru-переводы <b>шаблонов дат</b> (китайские 月/年/日 → европейский
<code>dd.MM.yyyy</code>, плейсхолдеры <code>%d</code> и т.д.) и типичные латинские аббревиатуры
вроде MIDI. Запускать после массового перевода или collect, если в UI даты отображаются «криво».</p>

<h2>Конфликты на модулях</h2>
<p>Красный бейдж «N конфликтов» у модуля — это не битый APK, а строки, где этот модуль
участвует в расхождении переводов в <b>общем словаре</b>. Решать на вкладке Конфликты
или игнорировать, если APK вас устраивает.</p>

<h2>Полезные галки при переводе APK</h2>
<ul>
<li><b>Не трогать готовые строки</b> — не перезаписывать уже переведённое (рекомендуется).</li>
<li><b>Только словарь</b> — без Google; для доводки готового проекта.</li>
<li><b>После — собрать словарь из APK</b> — обычно выключать для уже переведённых проектов.</li>
</ul>
"""


def show_faq(parent: QWidget | None = None) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle("Справка — Automotive Translator")
    dlg.setMinimumSize(520, 420)
    dlg.resize(640, 520)

    root = QVBoxLayout(dlg)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    body = QWidget()
    body_layout = QVBoxLayout(body)
    label = QLabel(FAQ_HTML)
    label.setObjectName("hintLabel")
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    body_layout.addWidget(label)
    body_layout.addStretch()
    scroll.setWidget(body)
    root.addWidget(scroll)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dlg.reject)
    buttons.accepted.connect(dlg.accept)
    close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
    if close_btn:
        close_btn.clicked.connect(dlg.accept)
    root.addWidget(buttons)

    dlg.exec()
