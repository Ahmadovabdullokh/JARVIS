# J.A.R.V.I.S.

Голосовой ассистент для Windows в стиле JARVIS из «Мстителей».
Работает в облаке и рассчитан на ноутбук без видеокарты: языковая
модель и агент по коду работают через DeepSeek, распознавание речи —
через Groq или локальный `faster-whisper`, локально остаются только
микрофон, воспроизведение звука и лёгкий HUD.

## Что используется

- Распознавание речи: Groq `whisper-large-v3-turbo` или локальная
  `faster-whisper`.
- Языковая модель и инструменты: DeepSeek `deepseek-chat`.
- Агент по коду: DeepSeek с инструментами чтения/записи файлов,
  git, запуска Python/PowerShell и тестов.
- Синтез речи: Edge TTS (облако) с потоковой озвучкой по предложениям
  (первая фраза звучит сразу), выбором устройства вывода
  (`tts_output_device`) и прерыванием речи голосом
  (`voice_barge_in`, для наушников), опционально `pyttsx3` как
  офлайн-fallback. Ответы на текст тоже озвучиваются
  (`speak_text`, отключается в настройках).
- Управление компьютером: PyAutoGUI, PyGetWindow, psutil, pywin32,
  pynput, pywinauto.
- Инструменты: реестр из 404 операции в 22 категориях: system, files,
  processes, windows, apps, input, screen, media, network, browser,
  office, communication, dev, code, security, productivity, knowledge,
  hardware, memory, automation, agent, generic. Внутри `knowledge` — RAG,
  внутри `agent` — undo, аудит и диагностика.
- Плюс 40 legacy-инструментов (40 уникальных имён; всего 448 доступных
  вызовов).
- Универсальный доступ: `run_powershell`, `run_cmd`, `run_python`,
  `run_executable`, `http_request`, `batch_run`, `workflow_run`.
- Режимы чата (вкладка ЧАТ): «Просто чат» — беседа без действий,
  «Простые задачи» — обычный агент с инструментами, «Код» — автономный
  DeepSeek-агент: сам читает проект, правит файлы, запускает тесты и
  проверки. По умолчанию используется `backend: "deepseek"`.
  GitHub Copilot остаётся опциональным: `backend: "auto"` (CLI или
  VS Code, если установлен), `"cli"` или `"vscode"`. Настройки в блоке
  `code` конфига: `project`, `backend`, `max_iterations`, `cli_args`,
  `timeout`, `fallback`. Режим применяется к тексту и голосу,
  сохраняется в конфиге (`chat_mode`).
- Инструменты кодинг-агента: `code_plan`, `code_plan_update`,
  `code_project_snapshot`, `code_tree`, `code_glob`, `code_grep`,
  `code_read`, `code_read_many`, `code_write`, `code_edit`,
  `code_multi_edit`, `code_apply_patch`, `code_verify`, `code_diff`,
  `code_git_summary`, `code_run`, `code_test`, `code_lint`,
  `code_project_info`, `code_symbols`, `code_find_references`,
  `code_todos`, `code_dependencies`, `code_checkpoint`, `code_rollback`.
- Агент сначала строит план, читает файл перед правкой, блокирует
  повторные одинаковые вызовы, делает транзакционные multi-edit и
  автоматически запускает `code_verify` (compileall/ruff/тесты).
- `code_project_snapshot` добавляет правила проекта (`AGENTS.md`,
  `CLAUDE.md`), git-состояние и команды тестов; `code_read_many` и
  `code_edit` уменьшают число шагов.
- Для скорости агент читает файлы пакетно, использует до 80 шагов
  в режиме кода, а результаты инструментов не обрезаются до
  нескольких строк. При исчерпании шагов или отсутствии прогресса
  вместо пустой ошибки возвращается отчёт.
- Автопилот кода включается через `code.autopilot` (по умолчанию
  true): правки внутри проекта не требуют подтверждений. Секреты,
  запись вне проекта, `git reset --hard`, force push и массовое
  удаление блокируются; commit/push отключены до `code.allow_git_write`.
- `code_checkpoint` / `code_rollback` откатывают изменения текущей
  задачи. Состояние плана и проверок сохраняется в `data/code_state.json`.
- Вкладка «АГЕНТ»: карточка проекта, модель/провайдер, кнопки
  проверки проекта, тестов, линта, карты проекта и git, а также
  каталог доступных кодинг-инструментов.
- Мета-агент: сложные задачи вроде «напиши в VS Code Copilot, чтобы
  исправил ошибку» выполняются цепочкой инструментов: `app_launch` →
  `window_activate` → `keyboard_hotkey` → `text_type` → `keyboard_press` →
  `screen_ocr` (проверка). Есть готовый рецепт `automation_copilot_fix`;
  динамический выбор инструментов — синонимический слой + выбор категорий
  у LLM.
- Распознавание: адаптивный порог шума (калибровка тишины), длинные фразы
  до 12 секунд, пауза 0.7 c, STT-подсказка с ключевыми терминами;
  режим «показать команду перед отправкой» в конфиге (`transcript_preview`)
  и на вкладке НАСТРОЙКИ.
- Интерфейс: по умолчанию новый HUD на WebView2 через `pywebview`
  (EdgeChromium-бэкенд) — frameless-окно, арк-реактор на Canvas с
  анимацией 60 fps, HUD-стилизация, телеметрия, чат со стримингом
  ответов LLM, разделы ЧАТ, АГЕНТ, ЗАДАЧИ, КОМАНДЫ, ЖУРНАЛ и
  НАСТРОЙКИ, поиск команд (`Ctrl+K`), tray-иконка и быстрые действия.
  Старый Tkinter HUD сохранён как fallback: `scripts\start.ps1 -Tk`.
- LLM: circuit breaker — после серии сбоев провайдер отключается
  на 5 минут и трафик идёт на резервный эндпоинт.
  WebView2 уже есть в Windows 11; на Windows 10 может потребоваться
  Evergreen WebView2 Runtime. Для моста используется `pywebview` +
  `pythonnet` (CoreCLR); `launcher_web.py` генерирует
  `data/dotnet.runtimeconfig.json` под установленный .NET.

Локальные модели не обязательны, но можно подключить Ollama. Папку
`models/vosk-model-small-ru-0.22` можно удалить: Vosk больше не
используется.

## Новый интерфейс

Новый HUD использует нативный WebView2 через `pywebview` (бэкенд
EdgeChromium, JS↔Python — единый метод `rpc()` в `JarvisBridgeApi`,
`app/ui_bridge.py`) и локальные HTML/CSS/JS-ассеты из `ui/`. Методы:
`bootstrap`, `poll`, `send_message`, `stop`, `cancel_task`,
`save_settings`, `get_journal`, `run_doctor` и `window_action`. Ответы
приходят пакетом, поэтому UI не зависит от медленных операций агента.

Запуск:

```powershell
scripts\start.ps1        # новый WebView2 HUD
scripts\start.ps1 -Tk    # старый Tkinter HUD
```

Если WebView2 Runtime недоступен, `launcher_web.py` автоматически
переключается на Tkinter. Сборка EXE: `scripts\build.ps1`; в
`jarvis.spec` уже включены `ui/`, `pywebview`, `pythonnet` и
`clr_loader`. Для pythonnet при первом запуске создаётся
`data/dotnet.runtimeconfig.json` (CoreCLR, .NET 10); на .NET 10 в
`.venv` может потребоваться точечный патч
`webview/platforms/winforms.py` — см. `AGENTS.md`.

## Расширенные возможности

JARVIS умеет не только открывать приложения и управлять окнами, но и:

- читать, создавать, искать, архивировать, шифровать и сравнивать файлы;
- работать с Word, Excel, PowerPoint и PDF;
- управлять процессами, службами, автозагрузкой, реестром, событиями,
  планировщиком, питанием, яркостью, звуком, принтерами, USB, Wi-Fi,
  Bluetooth, firewall и Defender;
- делать снимки экрана, OCR, запись видео, поиск изображения на экране;
- работать с сетью: ping, DNS, порты, HTTP, SSL, speedtest, SSH/SFTP,
  Wake-on-LAN;
- автоматизировать браузер через Playwright, скачивать и разбирать
  страницы;
- отправлять почту, сообщения Telegram/Discord/Slack и уведомления;
- вести заметки, задачи, напоминания, таймеры и сценарии;
- запрашивать погоду, новости, курсы, время в городах, Википедию и
  веб-поиск;
- работать с камерой, COM-портами и оборудованием;
- хранить факты, профиль и сессии диалогов; искать по прошлым разговорам;
- индексировать локальные документы и искать по ним (`rag_index`,
  `rag_search`);
- отменять последние изменения файлов (`undo_last`, `undo_list`);
- вести локальные контакты и ICS-календарь;
- работать с локальной LLM через Ollama или другой OpenAI-совместимый
  эндпоинт, с резервным провайдером;
- проходить самодиагностику (`doctor_check`) и смотреть трассировку
  запросов (`trace_tail`);
- управлять разрешениями: allow/confirm/deny на уровне инструмента,
  allow/deny на уровне сессии, защита от prompt injection;
- искать текст на экране через OCR и кликать по нему
  (`screen_click_text`).

Модель не получает все 448 схемы сразу: `get_llm_tools()` выбирает
релевантные запросу инструменты и всегда добавляет универсальные
`run_powershell` / `run_cmd` / `run_python` / `http_request` и
мета-инструменты `list_capabilities` / `describe_capability` /
`run_capability`.

## Расширение плагинами

Инструменты и интеграции можно добавлять без правки ядра — через каталог
`plugins/`. Плагин — это файл `plugins/имя.py` (или пакет
`plugins/имя/plugin.py`), который объявляет манифест и регистрирует
инструменты:

```python
from app.plugins import JarvisPlugin

MANIFEST = {
    "name": "my_plugin",
    "version": "1.0.0",
    "permissions": ["network"],
    "api": 1,
}

class MyPlugin(JarvisPlugin):
    manifest_data = MANIFEST

    def register(self, registry):
        registry.tool(
            "my_tool",
            "Что делает инструмент.",
            {"type": "object", "properties": {}, "required": []},
            category="general",
        )(lambda: "готово")

PLUGIN = MyPlugin()
```

- Плагины загружаются автоматически при старте (`app/plugins.py`),
  каждый — в изоляции: сбой одного не роняет остальные, а частично
  зарегистрированные инструменты откатываются.
- Манифест содержит `name`, `version`, `permissions`, `api`; если в
  `config.json` задан `plugins.allowed_permissions`, плагин с чужим
  правом не загрузится. Отключить отдельные — `plugins.disabled`,
  целиком — `plugins.enabled: false`.
- Хуки жизненного цикла: `on_start(context)`, `on_stop()`,
  `on_message(text)`, `on_tool_call(name, arguments, result)`.
- Готовый пример — `plugins/example_tools.py` (инструмент `plugin_ping`).
- В UI доступны `list_plugins` и `reload_plugins` (перезагрузка без
  перезапуска приложения).

## Язык и профили

- Интерфейсные строки вынесены в `app/locales/{ru,en}.json`;
  `language` в `config.json` переключает язык (или RPC `set_language`).
  Механизм — `app/i18n.py`, без внешних зависимостей.
- Профили — частичные наборы настроек в `config.profiles`. RPC
  `set_profile` накладывает профиль поверх базового конфига (глубокое
  слияние) и сохраняет результат; активный профиль — `active_profile`.
  Удобно для режимов «дом / работа / ночь».

## Производительность

- LLM-запросы идут через общий `requests.Session` с keep-alive
  (переиспользование TLS-соединения), что заметно ускоряет агентский
  цикл из десятков шагов.
- Схемы инструментов кэшируются (`ToolSpec.schema()`), а отдельный
  LLM-вызов планировщика категорий выполняется только для длинных или
  составных запросов (`needs_category_planning`).
- Поиск по истории диалогов и RAG использует встроенный SQLite FTS5
  (`app/sessions.py`, `app/rag.py`) вместо перебора в Python; при
  отсутствии FTS5 автоматически включается прежний fallback.
- SQLite работает в режиме WAL с `synchronous=NORMAL`.
- «Умный контекст» (`app/context.py`) подмешивает к промпту только
  релевантные факты памяти, прошлые реплики и найденные документы.

## Надёжный запуск приложений и сайтов

- Браузер запускается напрямую через exe браузера по умолчанию, а его окно
  выводится на передний план. Если окно было свёрнуто или скрыто, JARVIS
  восстанавливает его.
- Store-приложения (например, Telegram) находятся через AppX-манифест,
  запускаются напрямую и затем активируются; запуск не зависит от
  `shell:AppsFolder` и протокола `tg://`.
- Сайты открываются по алиасу или домену через `open_website`: 43 алиаса,
  включая Google, YouTube, VK, GitHub, Wikipedia, Avito, Ozon и Steam.

## Установка

```powershell
cd C:\Users\ahmad\PycharmProjects\PythonProject9
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

`install.ps1` создаёт `.venv`, ставит зависимости, копирует
`config.example.json` в `config.json`, ставит Chromium для Playwright и
запускает диагностику. Он также выставляет Medium integrity для
`.venv\Scripts\python.exe` и `.venv\Scripts\pythonw.exe` — без этого
браузер и Store-приложения могут запускаться без видимого окна.
Автозапуск:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
```

Ярлыки на рабочем столе и в автозапуске запускают приложение
напрямую (`pythonw launcher_web.py` или `JARVIS.exe`). Приложение
само поднимает HUD, remote-сервер для телефона и Telegram-бота,
поэтому отдельный `start_all.ps1` при входе в Windows не нужен.
Если ярлык с именем `JARVIS.lnk` блокируется антивирусом, скрипт
создаёт `JARVIS App.lnk`; при необходимости добавьте исключение.

Создайте `.env` в корне проекта:

```text
DEEPSEEK_API_KEY=ваш_ключ_deepseek
GROQ_API_KEY=ваш_ключ_groq
```

`DEEPSEEK_API_KEY` нужен для чата и режима кода. `GROQ_API_KEY` нужен
только для распознавания речи и анализа экрана; без него можно
указать локальную STT-модель в `stt_local_model`.

Ключи также можно задать переменными окружения PowerShell:

```powershell
$env:DEEPSEEK_API_KEY = "ваш_ключ_deepseek"
$env:GROQ_API_KEY = "ваш_ключ_groq"
```

`config/config.json` в репозиторий не попадает: он в `.gitignore`.
Шаблон настроек — `config/config.example.json`. Если ключ когда-либо
попадал в git или в переписку, перевыпустите его в консоли провайдера.

## Запуск

```powershell
scripts\start.ps1
```

По умолчанию открывается новый WebView2 HUD: арк-реактор, статус,
телеметрия и разделы «ЧАТ», «АГЕНТ», «ЗАДАЧИ», «КОМАНДЫ», «ЖУРНАЛ» и
«НАСТРОЙКИ». Старый Tkinter HUD: `scripts\start.ps1 -Tk` или
`.\.venv\Scripts\python.exe launcher.py`.

## Режим работы

По умолчанию обращение «Джарвис» не требуется: говорите команду сразу,
и она будет выполнена. Например, «открой Telegram» или «который час».

Если фразу всё же начать с «Джарвис», обращение будет распознано и
убрано из команды, а сама команда выполнится как обычно.

Чтобы вернуть обязательное обращение, установите
`"require_wake_word": true` в `config/config.json`. Тогда:

- «Джарвис, который час» — команда выполняется сразу.
- «Джарвис» — Джарвис ответит «Слушаю, сэр», после чего следующую
  фразу можно говорить без повторного обращения в течение 8 секунд.
- Фразы без обращения игнорируются.

В режиме обращения распознаются варианты «джарвис», «jarvis»,
«джарвиз», «дарвис», «равис», «арвис», «джавис» и похожие искажения
Whisper. Для подсказки распознавателю используется `stt_prompt` в
`config/config.json`. Настройки: `require_wake_word`,
`wake_word_cooldown`, `follow_up_seconds`, `wake_ack`.

Если Whisper упорно слышит «равис» или «арвис»:

- убедитесь, что в `config.json` заполнен `stt_prompt`;
- добавьте своё искажение в `wake_words`;
- для большей точности смените `groq_model` на
  `whisper-large-v3` — он медленнее, но точнее для русской речи.

Примеры команд:

- «Открой Telegram».
- «Открой YouTube».
- «Открой github.com».
- «Открой вконтакте».
- «Статус систем».
- «Заряд батареи».
- «Протокол домовой».
- «Запомни, что я предпочитаю тёмную тему».
- «Что ты помнишь».
- «Найди на экране Telegram и напиши сообщение …».

## Характер

В `config/config.json` есть секция `persona`:

```json
"persona": {
    "name": "JARVIS",
    "address": "сэр",
    "humor": "subtle",
    "verbosity": "concise",
    "language": "ru"
}
```

Системный промпт задаёт сдержанный формальный тон, обращение «сэр»
и краткие ответы. Markdown и эмодзи вычищаются перед озвучкой.

## Голос

По умолчанию используется `en-US-BrianMultilingualNeural`, потому что
он корректно озвучивает русский текст. Голос и pitch меняются через
`tts.voice`, `tts.pitch`, `tts.rate` и `tts.voices` в конфиге.
Используются только мужские голоса: женские fallback отключены.
При недоступности Edge TTS JARVIS сообщит об ошибке в HUD и продолжит
работу без озвучки.

## Память

Факты и профиль пользователя хранятся в `data/memory.json` и
подмешиваются в системный промпт. Файл создаётся автоматически.
`memory_size` ограничивает количество запоминаемых фактов.

## Анализ экрана

Снимок экрана отправляется в Groq только по прямому запросу.
Модель задаётся параметром `vision_model` (по умолчанию
`qwen/qwen3.8-27b`). Перед визуальными действиями JARVIS сначала
анализирует экран, а отправка сообщений требует подтверждения Windows.

## Автономность и безопасность

В новом `config.example.json` по умолчанию включён безопасный режим
`agent.autonomy = "balanced"` и `confirm_destructive = true`: опасные
операции требуют подтверждения. Режим `"full"` (без подтверждений)
остаётся доступен как осознанный выбор для персонального агента.
Пример безопасной настройки:

```json
"agent": {
  "autonomy": "balanced",
  "tool_timeout_seconds": 120,
  "max_tools_per_request": 80
},
"safety": {
  "autonomy": "balanced",
  "confirm_destructive": true,
  "taint_tracking": true,
  "audit_max_bytes": 2097152,
  "tool_policies": {
    "run_powershell": "confirm",
    "registry_delete": "deny"
  },
  "session_allow": [],
  "session_deny": []
},
"tools": {
  "enabled_categories": [],
  "disabled_tools": []
},
"llm": {
  "max_retries": 2,
  "retry_backoff": 0.8,
  "parallel_tool_calls": false
}
```

`enabled_categories` — белый список категорий (пустой список = все),
`disabled_tools` — имена отдельных инструментов, которые нужно скрыть
от модели и запретить к запуску. `max_tools_per_request` ограничивает
число схем, передаваемых модели за один запрос.

`tool_policies` задаёт политику на инструмент или категорию:
`allow`, `confirm`, `deny`. `session_allow` / `session_deny` действуют
до перезапуска. Режимы автономности: `safe` (подтверждать всё),
`balanced` (подтверждать опасное) и `full` (не подтверждать).

Дополнительно:

- все вызовы инструментов пишутся в `data/audit.log` (JSONL), секреты
  в журнале маскируются, файл ротируется по `audit_max_bytes`;
- `safety.dry_run = true` показывает, что было бы выполнено, без запуска;
- `taint_tracking` помечает результаты браузера, почты, OCR, веб-поиска,
  RAG и чтения файлов как недоверенные и требует подтверждения перед
  опасным действием;
- вывод инструментов ограничивается `tool_result_limit` / `max_output_chars`;
- у каждого инструмента есть таймаут; отмена доходит до реестра и
  фоновых задач;
- аварийная остановка — `Ctrl+Alt+J`; она останавливает инструменты и
  фоновые задачи. То же доступно инструментом `emergency_stop`;
- `undo_last` / `undo_list` отменяют последние изменения файлов
  (запись, перемещение, удаление через журнал; корзина Windows
  восстанавливается отдельно);
- все запросы и вызовы инструментов пишутся в `data/traces.jsonl`
  (`trace_tail`);
- ключи и пароли не храните в `config/config.json` и не коммитьте `.env`.

## Сессии, память и RAG

История диалога хранится в `data/sessions.db` (SQLite), поэтому
контекст переживает перезапуск. `memory_search` и `session_search`
ищут по фактам и прошлым сообщениям, `memory_stats` показывает размер
памяти. `rag_index` индексирует локальные текстовые файлы, `rag_search`
ищет по ним, `rag_clear` очищает индекс.

## Локальная LLM и офлайн-речь

По умолчанию используется DeepSeek (`provider: "deepseek"`,
`model: "deepseek-chat"`). Ключ берётся из `DEEPSEEK_API_KEY`,
`llm.api_key` или `deepseek_api_key`. Для локального
OpenAI-совместимого эндпоинта (например, Ollama):

```json
"llm": {
  "provider": "ollama",
  "base_url": "http://localhost:11434/v1/chat/completions",
  "model": "qwen2.5:7b",
  "fallback_base_url": "",
  "fallback_model": "",
  "fallback_api_key": ""
}
```

Можно указать `fallback_base_url` / `fallback_model` — JARVIS
переключится на резервный провайдер после retry-ошибок. При
`auto_fallback: true` и наличии `GROQ_API_KEY` резервным
эндпоинтом автоматически становится Groq, если ключ DeepSeek
отклонён. Таймаут запроса задаётся через `llm.request_timeout`.

Для офлайн-TTS установите `pyttsx3` и включите
`tts_offline_fallback: true`. Для офлайн-STT:

```powershell
pip install -r requirements-optional.txt
```

и укажите в конфиге:

```json
"stt_local_model": "small",
"stt_local_device": "cpu",
"stt_local_compute_type": "int8"
```

Имя модели может быть именем `faster-whisper` или путём к локальной
модели. Если модель не загрузится, JARVIS вернётся к Groq Whisper.

## Диагностика и сборка

```powershell
.\.venv\Scripts\python.exe -m app.doctor
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

`doctor_check` проверяет Python, конфиг, ключи DeepSeek и Groq,
зависимости, Tesseract, ffmpeg, Playwright, права на `data/` и
свободное место.
`scripts\build.ps1` собирает `dist\JARVIS\JARVIS.exe` через PyInstaller
(onedir, без распаковки во временную папку);
`packaging\jarvis.iss` — заготовка установщика Inno Setup.

## Если команда сообщает «Открыл», а окна не видно

1. Полностью закройте JARVIS и запустите заново: старый процесс держит
   старый код в памяти.
2. Проверьте целостность интерпретатора: `icacls .venv\Scripts\python.exe` —
   уровень должен быть «Средний» (Medium).
3. Если уровень низкий, выполните `scripts\install.ps1` или
   `icacls .venv\Scripts\python.exe .venv\Scripts\pythonw.exe /setintegritylevel Medium`.
4. Команда «открой …» сама выводит окно браузера или Telegram на передний
   план и восстанавливает его из трея.

## Интеграции

Почта, Telegram, Discord и Slack настраиваются переменными окружения
(или одноимёнными полями `integrations` в конфиге):

```text
JARVIS_SMTP_HOST, JARVIS_SMTP_PORT, JARVIS_SMTP_USER,
JARVIS_SMTP_PASSWORD
JARVIS_IMAP_HOST, JARVIS_IMAP_USER, JARVIS_IMAP_PASSWORD
JARVIS_TELEGRAM_BOT_TOKEN, JARVIS_TELEGRAM_CHAT_ID
JARVIS_DISCORD_WEBHOOK
JARVIS_SLACK_WEBHOOK
```

Для OCR нужен установленный Tesseract-OCR (и `pytesseract` уже в
зависимостях). Для конвертации медиа используется ffmpeg из
`imageio-ffmpeg` или системный `ffmpeg`. Playwright после установки
зависимостей требует однократного `python -m playwright install chromium`.

## Логирование

Все сообщения пишутся в `data/logs/jarvis.log` (ротация по 2 МБ,
3 архива). В интерактивной консоли дублируется вывод, в оконном режиме
консоль не подключается — это убирает лишние блокировки UI. Аудит
инструментов по-прежнему хранится отдельно в `data/audit.log`.

## Тесты и разработка

```powershell
.\.venv\Scripts\python.exe -m pytest tests -v
.\.venv\Scripts\python.exe -m pytest tests --cov=app --cov-report=term-missing
.\.venv\Scripts\python.exe -m ruff check app tests launcher.py launcher_web.py launcher_remote.py scripts
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
pre-commit install
```

Тесты покрывают реестр инструментов, safety-политики, undo, сессии,
RAG, retry/fallback LLM, диагностику, память, конфиг, таймауты
инструментов, голосовой пайплайн, запуск приложений и сайтов, фокус
окон, удалённый доступ и Telegram AppX, плагины, локализацию, профили,
FTS5-поиск, умный контекст, камеру и жесты (сейчас 300 тестов). CI гоняет
Python 3.10/3.11/3.12/3.13, ruff, mypy, coverage (порог 50%) и
`pip-audit`: `.github/workflows/tests.yml`.
Зависимости обновляет Dependabot (`.github/dependabot.yml`).

Конфигурация и пути теперь централизованы: `app/config.py` (загрузка,
валидация, атомарное сохранение) и `app/paths.py` (единый `BASE_DIR`
и каталоги данных).

## Быстрый запуск всего

Одна команда из корня проекта запускает backend, HUD, локальный
remote-сервер для телефона по Wi-Fi и Telegram-бота, а при
подключённом по USB телефоне ещё и обновляет/открывает APK:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_all.ps1
```

Полезные варианты: `-NoHud` (без окна на ПК), `-NoPhone` (не трогать
телефон), `-Tunnel` (дополнительно поднять Cloudflare-туннель),
`-NoWindow` (без окна консоли, для автозапуска). Адрес для телефона
и токен скрипт печатает в конце; остановить — `Stop-Process -Id <PID>`.

## Мобильный доступ (APK-пульт)

JARVIS можно использовать с телефона: Android-приложение
(`android/`) — это отдельный нативный пульт (чат, голосовой ввод,
задачи, журнал), а не WebView-ссылка на HUD. Оно подключается к
тому же backend по HTTPS-туннелю, ПК-версия работает как обычно.

При обычном запуске ПК-приложения (`JARVIS.exe`, `scripts\start.ps1`
или автозапуск) remote-сервер, Telegram-бот и HTTPS-туннель Cloudflare
поднимаются сами, поэтому телефон работает сразу, из любой сети.
Отключить автозапуск сервера и туннеля:
`remote.auto_start: false` и `remote.auto_tunnel: false` в
`config/config.json`.

```powershell
scripts\start_all.ps1         # всё сразу: backend + HUD + remote + бот
scripts\start_remote.ps1      # только backend + HTTP-сервер на 127.0.0.1:8765
scripts\start_tunnel_cf.ps1   # HTTPS-туннель через Cloudflare
scripts\remote_info.ps1       # покажет адрес и токен для приложения
```

- `app/remote_server.py` отдаёт статику `ui/` и RPC `POST /rpc` —
  тот же протокол, что у pywebview. Адрес прослушивания задаётся
  `remote.host` (`127.0.0.1` — только ПК/туннель, `0.0.0.0` — ещё
  и телефон по Wi-Fi).
- Токен доступа хранится в `config.json` → `remote.token`
  (создаётся автоматически, `secrets.token_urlsafe(24)`)
  или задаётся `JARVIS_REMOTE_TOKEN`. Клиент обменивает токен на
  HttpOnly-cookie через `POST /login`; для совместимости
  `GET /?token=...` один раз ставит cookie и редиректит на `/`.
  После входа RPC-запросы идут без токена в URL, токен не пишется
  в логи и не хранится в localStorage браузера.
- Защита: после 10 неудачных попыток авторизации IP блокируется
  на 2 минуты; `X-Forwarded-For` учитывается только от доверенных
  прокси (`JARVIS_TRUSTED_PROXIES`). По умолчанию удалённый доступ
  read-only: полный набор методов включается `remote.read_only: false`
  или явным `remote.allowed_methods` в config.json.
- Только локально (даже если разрешены политикой): `get_pairing`,
  `save_settings`, `open_path`, `reload_plugins` — удалённый RPC
  получает 403. Так секреты и файловая система ПК не доступны
  из браузера/туннеля.
- `GET /health` — открытый healthcheck (статус и uptime, без данных).
- `POST /stt` — распознавание аудио с телефона (webm/ogg/wav/mp3
  через ffmpeg → Groq Whisper), для кнопки MIC в веб-интерфейсе.
- Туннель: при запуске JARVIS **сам** поднимает cloudflared, если
  включён `remote.auto_tunnel` (в этом проекте он включён; в
  `config/config.example.json` по умолчанию `false` — публичный
  доступ нужно включать осознанно). Используется `tools/cloudflared.exe`
  (quick tunnel) или named tunnel с постоянным адресом
  (`remote.tunnel_name` + `remote.public_url`). Публичный URL пишется
  в `data/remote_url.json` **только после проверки `GET /health`** —
  телефон не получает мёртвый адрес. Транспорт задаётся
  `remote.tunnel_protocol` (`http2` по умолчанию, `quic` — если UDP
  не блокируется). Отключить автоподъём:
  `remote.auto_tunnel: false`; ручной запуск —
  `scripts/start_tunnel_cf.ps1` (не запускайте одновременно с
  автоподъёмом — будет два туннеля).
- **Разные города и смена адреса.** Quick tunnel выдаёт новый URL при
  каждом запуске, поэтому JARVIS дополнительно публикует актуальный
  адрес в секретный случайный топик ntfy (`remote.rendezvous: true`,
  `remote.rendezvous_url: "https://ntfy.sh"`). Адрес шифруется
  AES-GCM ключом, выведенным из токена доступа (`SHA-256`), в открытом
  виде не публикуется. Телефон получает из QR адрес ntfy и топик и сам
  обновляет `server_url`, когда старый адрес перестал отвечать —
  переподключение происходит автоматически даже через сутки.
  Топик создаётся при первом показе QR и хранится в `remote.rendezvous_topic`.
- Подключение по QR: на ПК откройте **«Настройки» → «Показать QR
  для телефона»**. QR содержит ссылку `jarvis://pair?...` с адресом,
  токеном, запасным адресом домашней Wi-Fi сети и параметрами
  rendezvous (`rdvu`/`rdvt`). На телефоне откройте меню **«⋮» →
  «Сканировать QR»** (или «Настройки подключения» → «Сканировать QR
  камерой») — встроенный сканер на CameraX + ZXing распознаёт код и
  предлагает подключиться. В сканере есть зум 1×/2×/3×, фокус по
  касанию и счётчик кадров — если код мелкий, нажмите на QR на ПК
  (откроется крупный оверлей) и увеличьте масштаб. Ссылку можно
  скопировать и вставить в настройках приложения — поле адреса
  понимает и полную ссылку `jarvis://pair?...`. QR показывается только
  в локальном окне JARVIS и не отдаётся по сети.
- Приложение само выбирает рабочий адрес: публичный туннель →
  запасной LAN-адрес → свежий адрес из rendezvous; при смене адреса
  сохраняет его и переподключается без действий пользователя.
  Foreground-служба телефона проверяет `/health` и обновляет адрес
  даже при закрытом приложении, а после перезагрузки телефона
  поднимается автоматически (BootReceiver).
- Ручной вариант: ввести «Адрес сервера» (из remote_info.ps1) и
  «Токен» — открывается нативный экран JARVIS с чатом.
- Для чата с телефона нужен доступ к `send_message`: пропишите
  `remote.allowed_methods` (безопасный вариант, `read_only` при этом
  игнорируется) или `remote.read_only: false`:
  ```json
  "remote": {
      "read_only": true,
      "allowed_methods": [
          "bootstrap", "client_ready", "client_error", "poll",
          "send_message", "stop", "set_mode", "get_catalog",
          "get_journal", "get_audit", "cancel_task", "run_doctor",
          "set_microphone"
      ]
  }
  ```
  Политика перечитывается на каждом RPC-запросе, перезапуск не нужен.
- Голосовой ввод: кнопка MIC пишет звук с микрофона телефона и
  отправляет его на `/stt` (ffmpeg → Groq Whisper); распознанный
  текст попадает в поле ввода.
- В Android-приложении: foreground-сервис держит уведомление
  «JARVIS: онлайн» и проверяет `/health`, чат автоматически
  переподключается при обрыве (баннер сверху), долгое нажатие на
  сообщение копирует текст, меню «⋮» — задачи, журнал, диагностика.
- UI — PWA: `ui/manifest.webmanifest` + `ui/sw.js` кэшируют
  app-shell, поэтому HUD можно «добавить на главный экран»
  браузера и использовать без APK.
- Уведомления в Telegram: `notifications.telegram` в config.json
  (креды — `JARVIS_TELEGRAM_BOT_TOKEN` / `JARVIS_TELEGRAM_CHAT_ID`
  или `integrations.telegram_*`). Если `chat_id` пуст, JARVIS
  определит его сам после первого `/start` у бота. Проверка:
  ```powershell
  .\.venv\Scripts\python.exe -m app.notifier --enable --test
  ```

## Камера, жесты и IP Webcam

В интерфейсе есть страница **«Камера»**: полноэкранный кинематографичный
HUD, поток, жесты, качество и HUD-панель. Обработка идёт локально
(MediaPipe HandLandmarker), кадры никуда не отправляются, пока вы
явно не включите описание предметов.

### Камера ПК и качество

- По умолчанию используется камера с индексом `0`. На этой USB-камере
  физический максимум — **640×480**; 720p/1080p появятся только с другой
  камерой, камерой телефона в приложении JARVIS или IP Webcam.
- Windows-захват идёт через **MSMF-first + MJPG**: это даёт ~30 fps
  захвата вместо 8–14 fps через DSHOW.
- Пресеты качества:
  - `performance` — 12 fps, JPEG 74, лёгкая резкость;
  - `balanced` — 20 fps, JPEG 82, резкость 0.35;
  - `quality` — 30 fps, JPEG 88, резкость 0.5 (по умолчанию).
- Кнопка **«Проверить камеры»** перебирает индексы 0–3 и показывает
  реальное разрешение/FPS; почти чёрные виртуальные камеры помечаются.
- Камера может быть **фоном всего приложения** (кнопка «ФОН») и
  включать **кинематографичный режим** (кнопка «HUD»): скрываются
  боковые панели, сверху/снизу остаются HUD-панели, работает fullscreen
  по кнопке или клавише `F`.

### Камера телефона в приложении JARVIS (без IP Webcam)

Приложение JARVIS само передаёт камеру телефона на ПК — отдельный
IP Webcam не нужен.

1. Соберите и установите APK (см. «Сборка APK» ниже), подключите
   телефон к JARVIS по QR или вручную.
2. В приложении откройте **«Камера»**, выберите объектив, разрешение
   (480p / 720p / 1080p) и FPS (5–20), нажмите **«Начать трансляцию»**.
3. Первый кадр автоматически переключает источник камеры на ПК на
   `phone` и перезапускает жесты, если они включены. Политика
   `remote.allowed_methods` при этом не мешает: переключение делает
   сам сервер, а не удалённый RPC.
4. Кадры идут по HTTPS-туннелю или Wi-Fi на `POST /camera/frame`;
   HUD, жесты и «Что видно?» используют их как обычную камеру.
5. Если кадры перестали приходить дольше `camera.phone_timeout`
   (по умолчанию 5 с), сервер помечает поток как `stale` и перестаёт
   отдавать устаревший кадр в vision и снимки. Приложение показывает
   «ПК: кадры не доходят» и повторяет переключение с backoff.
6. Остановка трансляции выключает камеру; вернуть камеру ПК можно
   в настройках камеры на ПК.

Включить/выключить автоматическое переключение можно через
`camera.phone_auto_switch` (по умолчанию `true`).

### Камера телефона через IP Webcam

1. Установите **IP Webcam** на рабочий телефон (TECNO POVA 6 Neo).
2. Подключите телефон и ПК к одной Wi-Fi-сети.
3. В приложении включите «Работать в фоне» и запустите сервер.
4. В JARVIS откройте «Камера» → источник **IP Webcam / сеть** →
   вставьте URL вида `http://192.168.1.23:8080/video` → «Подключить».
5. На телефоне откройте `http://IP-ПК:8765/` (адрес и токен см.
   `scripts\remote_info.ps1`) — там тот же поток и статус жестов.

Если IP Webcam останавливает камеру при открытии браузера, включите
фоновый режим в приложении или используйте второе устройство для
просмотра. Для Spark 20 Pro с неработающим тачем камера недоступна,
пока не получится включить USB-отладку или запустить приложение.

### Профили жестов

Профиль выбирается в настройках камеры; по умолчанию — `media`.

| Профиль | Основные действия |
| --- | --- |
| `media` | Микрофон, стоп речи, скриншот, громкость, треки, play/pause |
| `jarvis` | Режимы chat/tasks/code, микрофон, стоп, скриншот, команда описания |
| `windows` | Назад/вперёд в браузере, Alt+Tab, Ctrl+Tab |
| `presentation` | Слайды, чёрный экран, указатель, старт/стоп |
| `pointer` | Курсор, щипок/двойной щипок, drag, скролл; **opt-in** |

`pointer` включается отдельным чекбоксом: пока он выключен, курсор не
двигается. Аварийный выход — кулак или открытая ладонь; используйте
`pyautogui` FAILSAFE (увести курсор в угол экрана).

Поддерживаются статические жесты (open palm, fist, peace, thumbs,
OK, point, pinch, L, rock, shaka, call me, 3/4/5 пальцев), динамические
(свайпы, круги, push/pull) и двумя руками (рамка, зум, поворот, хлопок).
Классификатор работает на уменьшенном кадре (`detection_width: 256`),
чтобы на слабом CPU держать ~8 fps распознавания и ~30 fps камеры.

Команды можно переназначить в `config/config.json` → `gestures.profiles`
(или legacy `gestures.actions`): запись вида
`{"kind": "command", "text": "открой браузер"}` отправит жест в JARVIS,
`{"kind": "action", "action": "key", "key": "volumeup"}` нажмёт клавишу.
Опасные действия по умолчанию не назначены.

### Настройки

```json
"camera": {
    "enabled": false,
    "source": "pc",
    "index": 0,
    "url": "",
    "width": 640,
    "height": 480,
    "fps": 30,
    "stream_fps": 30,
    "analyze_fps": 12,
    "jpeg_quality": 88,
    "mirror": true,
    "backend": "auto",
    "fourcc": "MJPG",
    "quality": "quality",
    "sharpness": 0.5,
    "background": true,
    "immersive": true,
    "fit": "cover"
},
"gestures": {
    "enabled": false,
    "num_hands": 2,
    "detection_width": 256,
    "profile": "media",
    "cooldown_ms": 900,
    "pointer": {"enabled": false, "smoothing": 0.35,
                "dead_zone": 0.012, "optical_flow": true},
    "dynamic": {"swipe_distance": 0.17, "window_ms": 450,
                "circle_min_angle": 300, "push_pull_ratio": 0.25},
    "two_hands": {"enabled": true, "zoom_ratio": 0.12,
                  "rotate_degrees": 18},
    "profiles": {}
}
```

Камера выключена в `config.example.json`; включение сохраняется в
конфиг. `set_camera`, `set_camera_quality`, `set_camera_background`,
`probe_cameras`, `set_gestures`, `set_gestures_profile`, `set_pointer`
доступны и с телефона, если добавить их в `remote.allowed_methods`.
Приём кадров с камеры телефона работает и при read-only: сервер сам
переключает источник на `phone`, когда приходит первый кадр
(`camera.phone_auto_switch`).

### Установка MediaPipe и модели

```powershell
.\.venv\Scripts\python.exe -m pip install --no-deps "mediapipe==1.2.3"
.\.venv\Scripts\python.exe -m pip install "absl-py~=2.3" "flatbuffers~=25.9"
```

`scripts\install.ps1` ставит MediaPipe и скачивает модель
`models/hand_landmarker.task` автоматически. Если модели нет, скачайте
`hand_landmarker.task` (float16, версия 1) с
`storage.googleapis.com/mediapipe-models` в `models/`.
Диагностика: `.\.venv\Scripts\python.exe -m app.doctor`.

Сборка APK:

```powershell
cd android
& "$env:USERPROFILE\gradle-8.9\bin\gradle.bat" assembleDebug
# результат: app\build\outputs\apk\debug\app-debug.apk
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

Нужны JDK 17 и Android SDK (platform 34, build-tools 34.0.0);
`sdk.dir` указывается в `android/local.properties`. Диагностика
голосов Edge TTS: `.\.venv\Scripts\python.exe scripts\tts_test.py`.
