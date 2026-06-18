"""Справка (инструкция + FAQ) для GUI Automotive Translator."""

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
<h2>Быстрый старт</h2>
<ol>
<li>Укажите <b>папку проекта</b> — каталог с модулями <code>*_src</code> (например <code>Translated</code>).</li>
<li>Нажмите <b>Обновить</b> — слева появятся модули и бейджи (заглушки, конфликты, готов).</li>
<li>Выберите модуль или «все модули» и запустите нужную задачу на вкладке <b>Словарь / APK</b>.</li>
<li>После правок снова <b>Обновить</b> — статус модулей перечитается из APK.</li>
</ol>

<h2>Словарь и APK — что куда пишется</h2>
<ul>
<li><b>Общий словарь</b> — <code>data/dictionaries/translation_library_ru_en.json</code>
    и <code>translation_library_ru_zh-rCN.json</code>. Один раз на все проекты.</li>
<li><b>APK модуля</b> — <code>res/values-ru/*.xml</code> внутри каждого <code>*_src</code>.
    Именно это видит машина после сборки.</li>
<li>Заполнить словарь ≠ перевести APK. Пока не сделан <b>fill</b> или ручное сохранение
    в окне заглушек, в APK могут остаться пробелы-заглушки <code> </code>.</li>
</ul>

<h2>Режимы на вкладке «Словарь / APK»</h2>
<p><b>Перевести APK</b> (основной)</p>
<ul>
<li>Берёт переводы из словарей <b>en и zh</b> и пишет в <code>values-ru</code>.</li>
<li>С Google — <b>два прохода</b>: сначала английские строки (en→ru), затем китайские (zh→ru).</li>
<li><b>Только словарь</b> — подстановка из словарей en/zh; пропуски без перевода дают ошибку, Google не вызывается.</li>
<li><b>Словарь + создать заглушки</b> — словарь в APK; для пропусков заглушка <code> </code> в словарь и values-ru, без Google.</li>
<li>Рекомендуется галка <b>«Не трогать готовые строки»</b> — не затирать уже переведённое.</li>
</ul>
<p><b>Заглушки в словарь</b> (кнопка «Заглушки в словарь» внизу на Обзоре)</p>
<ul>
<li>Только <code>fill --ensure-dictionary</code>: новые строки в словарь с ru = <code> </code>, обновляет values-ru.</li>
<li>Google <b>не</b> вызывается. Collect <b>не</b> запускается.</li>
<li>Область: переключатель <b>«Все в папке»</b> / <b>«Только выбранный»</b> в панели перевода.</li>
</ul>
<p><b>Заглушки только JSON</b> (кнопка на Обзоре или в режиме «Пополнить общий словарь»)</p>
<ul>
<li><code>collect --add-missing-placeholders</code> — пропуски в словарь en/zh с ru = <code> </code>.</li>
<li>Файлы <code>values-ru</code> в APK <b>не</b> меняются.</li>
<li>Та же область: все модули или только выбранный слева.</li>
</ul>
<p><b>Собрать словарь из APK</b> (режим «Пополнить общий словарь» в панели перевода)</p>
<ul>
<li>Сначала заглушки (ensure-dictionary), затем <b>collect</b> по выбранной области (все модули или один).</li>
<li>Читает переводы из <code>values-ru</code> и обновляет общий словарь; может выявить <b>конфликты</b>.</li>
<li>На сами APK collect <b>не</b> влияет — только словарь и отчёты в <code>reports/</code>.</li>
<li>Галку <b>«После — собрать словарь»</b> при переводе APK (режим «Перевести приложение») обычно лучше выключать.</li>
</ul>

<h2>Вкладка «Словарь»</h2>
<ul>
<li><b>Заглушки в словаре</b> — ключи в en/zh JSON, где ru ещё « ».</li>
<li><b>Pending</b> — очередь в <code>data/pending/</code> перед переносом в основной словарь.</li>
<li><b>Переведено Google</b> — строки из отчёта <code>reports/fill_values_ru_google_report.json</code>.</li>
<li><b>Открыть словарь</b> — открыть JSON в редакторе по умолчанию (en или zh).</li>
<li>Фильтр модулей слева: <b>С Google (отчёт)</b> — модули из последнего fill с Google.</li>
<li>В окне заглушек APK: галка <b>Только из отчёта Google</b> — довести строки, уже переведённые Google.</li>
</ul>

<h2>Окно заглушек (двойной щелчок по модулю)</h2>
<p>Открывает заглушки <b>в APK</b> выбранного модуля, не весь словарь.</p>
<ul>
<li>В списке — строки, где в <code>values-ru</code> пусто или стоит заглушка <code> </code>.</li>
<li><b>Исходник</b> — канонический текст для ключа. Берётся не всегда из <code>values/strings.xml</code>:
    приоритет у <code>values-en</code>, иначе <code>values</code> / <code>values-zh*</code>
    (в шапке строки: трек EN или ZH).</li>
<li><b>Подставить в APK</b> — записать перевод из словаря (◆) в модуль; строка исчезает из списка.
    Для «оставить как оригинал» (map13 → map13) — эта кнопка.</li>
<li><b>Подставить всё из словаря</b> — то же для всех строк, где перевод уже есть в словаре.</li>
<li><b>В APK и словарь</b> — только для ручных правок (●): пишет в APK <b>и</b> обновляет общий словарь.</li>
<li><b>Отменить</b> (Ctrl+Z) / <b>Отменить всё</b> — откат записей в APK за эту сессию
    (последний шаг или все сразу).</li>
<li><b>Найти похожие…</b> — поиск в общем словаре по исходнику.</li>
<li><b>Следующий модуль →</b> — перейти к следующему модулю с заглушками.</li>
<li>Маркеры: <b>◆</b> — есть в словаре, <b>●</b> — правка вручную, ещё не в APK.</li>
</ul>

<h2>Конфликты</h2>
<ul>
<li>Красный бейдж у модуля — строка участвует в расхождении в <b>общем словаре</b>,
    APK при этом может быть в порядке.</li>
<li><b>Сохранить выделенные / все на экране</b> пишет в:
    <code>data/resolutions/</code> и <code>data/dictionaries/</code>.</li>
<li>В APK конфликты <b>сами не попадают</b> — на вкладке «Конфликты» есть <b>Записать в APK</b>
    (только затронутые исходники) или галка при сохранении в словарь.</li>
<li><b>Большинство</b> — создать шаблон resolutions с вариантом, который чаще встречается в APK.</li>
</ul>

<h2>Бейджи модулей</h2>
<ul>
<li><b>N заглушек</b> — в APK есть переводимые строки с пустым ru или <code> </code>.</li>
<li><b>N конфликтов</b> — модуль фигурирует в отчёте конфликтов словаря.</li>
<li><b>✓ готов</b> — переводимых заглушек нет (конфликты словаря могут остаться).</li>
<li><b>Обновить</b> перечитывает APK; счётчики смотрят на файлы модулей, не на словарь.</li>
</ul>

<h2>APK: распаковка, сборка, push</h2>
<ul>
<li>Инструменты в <code>vendor/apktools</code> внутри репозитория — не зависят от <code>/usr/local/bin</code>.
    Первый раз: кнопка <b>Установить инструменты</b> или <code>python3 scripts/setup_apk_tools.py</code>.</li>
<li>При <b>Обновить</b> в списке слева показываются и <code>*_src</code>, и <code>.apk</code> без пары —
    бейдж <b>не распакован</b>. Если есть и APK, и <code>Имя_src</code> — одна строка (распакованный модуль).</li>
<li>Двойной щелчок по нераспакованному APK — распаковка в папку проекта.</li>
<li><b>Собрать модуль</b> — apktool b + zipalign + подпись → <code>Имя_src-signed.apk</code> в папке проекта.
    По умолчанию исходники <b>не удаляются</b> (в отличие от <code>build-apk.sh</code>).</li>
<li><b>Push</b> — adb root, remount, push по пути <code>pm path</code>, очистка dalvik-кэша (как <code>push_common.sh</code>).
    Нужны <b>java</b> и <b>adb</b> в PATH; устройство с root/remount.</li>
<li>Подпись: <b>Deepal</b> (системные APK) или свои <code>.pk8</code> + <code>.x509.pem</code>.</li>
</ul>

<h2>Прочие действия</h2>
<ul>
<li><b>Формат дат</b> — правит шаблоны дат в словарях (月/年/日 → <code>dd.MM.yyyy</code> и т.п.).</li>
<li><b>Сортировать словари</b> — ключи A–Z, заглушки в конец.</li>
<li><b>Аудит</b> — проверка словаря на подозрительные переводы.</li>
</ul>

<h2>ПКМ по модулю</h2>
<ul>
<li><b>Открыть заглушки</b> — то же, что двойной щелчок.</li>
<li><b>Перевести модуль…</b> — fill для выбранного <code>*_src</code> с настройкой режима и галок.</li>
<li><b>Подставить из словаря в APK</b> — расхождения между values-ru и словарём.
    <b>Оставить</b> — не менять APK; <b>Из словаря</b> — записать из словаря; <b>Записать новую</b> — свой текст в APK;
    <b>Новая + словарь</b> — APK и обновление JSON en/zh.
    <b>Отменить</b> (Ctrl+Z) — откат последней записи в APK.</li>
<li><b>Редактировать values-ru…</b> — окно: исходник из <code>values-en</code> (если есть), правка перевода в APK.</li>
<li><b>Собрать APK…</b> — сборка и подпись выбранного <code>*_src</code>.</li>
<li><b>Push APK на устройство…</b> — установка signed APK через adb (package из AndroidManifest).</li>
<li><b>Открыть values</b> / <b>values-ru</b> / <b>в проводнике</b> — папки в системе.</li>
</ul>

<h2>FAQ</h2>

<p><b>Перевёл словарь, а модуль всё ещё «с заглушками»?</b><br>
Словарь и APK — разные файлы. Запустите <b>Перевести APK</b> (без «Только словарь»)
или подставьте из словаря через двойной щелчок по модулю.</p>

<p><b>Нажал «Сохранить» в конфликтах — почему в APK ничего не изменилось?</b><br>
Конфликты обновляют только словарь и <code>resolutions</code>. Для APK — fill по модулям.</p>

<p><b>Collect вернул старый перевод после моего выбора в конфликтах?</b><br>
Collect голосует по APK; ручной <code>chosen</code> в resolutions должен перебивать это.
Если сомневаетесь — снова сохраните конфликт и проверьте <code>data/resolutions/</code>.</p>

<p><b>Исходник в окне заглушек не совпадает с values/strings.xml?</b><br>
Это нормально: показывается канонический исходник (часто из <code>values-en</code>).
Поиск в словаре идёт по всем вариантам ключа, не только по тексту в поле.</p>

<p><b>Подставил перевод, а в поле остался текст прошлой строки?</b><br>
После «Подставить в APK» список и поля должны обновиться. Если нет — нажмите другую строку
в списке или закройте и откройте окно снова; сообщите, если повторится.</p>

<p><b>Что не переводить через Google?</b><br>
Шаблоны (<code>%s</code>, <code>%d</code>), технические имена, API-ключи, dialpad — их лучше
копировать как есть или править вручную. Массовый Google по всему словарю не запускается.</p>

<p><b>Когда жать «Заглушки в словарь», а когда «Собрать словарь из APK»?</b></p>
<ul>
<li><b>Заглушки в словарь</b> (быстрая кнопка) — только завести пропуски заглушкой, без collect.</li>
<li><b>Собрать словарь из APK</b> (режим «Пополнить общий словарь») — полный цикл: заглушки + collect после правок в APK.</li>
</ul>
"""


def show_faq(parent: QWidget | None = None) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle("Справка — Automotive Translator")
    dlg.setMinimumSize(560, 480)
    dlg.resize(720, 640)

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
    label.setOpenExternalLinks(True)
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
