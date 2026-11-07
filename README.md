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
- Синтез речи: Edge TTS (облако), опционально `pyttsx3` как офлайн-fallback.
- Управление компьютером: PyAutoGUI, PyGetWindow, psutil, pywin32,
  pynput, pywinauto.
- Инструменты: реестр из 403 операций в 22 категориях — файлы, процессы,
  окна, приложения, ввод, экран, медиа, сеть, браузер, Office, почта и
  мессенджеры, разработка, безопасность, продуктивность, знания,
  оборудование, память, RAG, отмена действий и автоматизация.
- Плюс 40 legacy-инструментов (39 уникальных имён; всего 442 доступных
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
- Инструменты кодинг-агента: `code_project_snapshot`, `code_tree`,
  `code_glob`, `code_grep`, `code_read`, `code_read_many`,
  `code_write`, `code_edit`, `code_multi_edit`, `code_apply_patch`,
  `code_diff`, `code_git_summary`, `code_run`, `code_test`,
  `code_lint`, `code_format`, `code_project_info`, `code_symbols`,
  `code_find_references`, `code_todos`, `code_dependencies`.
  `code_project_snapshot` и `code_read_many` уменьшают число шагов,
  а `code_edit` / `code_multi_edit` дают точечные правки, как в
  Codex, OpenCode и Claude Code.
- Для скорости агент читает файлы пакетно, использует до 60 шагов
  в режиме кода, а результаты инструментов не обрезаются до
  нескольких строк. При исчерпании шагов вместо пустой ошибки
  возвращается отчёт: что сделано, что осталось и следующий шаг.
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
- Интерфейс: современный Tkinter HUD с переиспользуемыми Canvas-элементами,
  мягким свечением арк-реактора, орбитальными частицами, плавной волной и
  VU-индикатором микрофона. Анимация идёт на 25 fps, останавливается в
  свёрнутом окне и не пересоздаёт объекты каждый кадр, поэтому не грузит
  CPU. Есть телеметрия, чат, вкладки ЗАДАЧИ/ЖУРНАЛ, быстрые действия,
  каталог инструментов, настройки, диагностика и tray-иконка.

Локальные модели не обязательны, но можно подключить Ollama. Папку
`models/vosk-model-small-ru-0.22` можно удалить: Vosk больше не
используется.

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

Модель не получает все 403 схем сразу: `get_llm_tools()` выбирает
релевантные запросу инструменты и всегда добавляет универсальные
`run_powershell` / `run_cmd` / `run_python` / `http_request` и
мета-инструменты `list_capabilities` / `describe_capability` /
`run_capability`.

## Установка

```powershell
cd C:\Users\ahmad\PycharmProjects\PythonProject9
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

`install.ps1` создаёт `.venv`, ставит зависимости, копирует
`config.example.json` в `config.json`, ставит Chromium для Playwright и
запускает диагностику. Автозапуск:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
```

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
.\.venv\Scripts\python.exe launcher.py
```

Появится HUD: арк-реактор, статус, телеметрия и вкладки «ЧАТ» и
«КОМАНДЫ».

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

По умолчанию используется `en-US-AndrewMultilingualNeural`, потому что
он корректно озвучивает русский текст. Голос и pitch меняются через
`tts.voice`, `tts.pitch`, `tts.rate` и `tts.voices` в конфиге.
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
`scripts\build.ps1` собирает `dist\JARVIS.exe` через PyInstaller;
`packaging\jarvis.iss` — заготовка установщика Inno Setup.

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
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m coverage run -m unittest discover -s tests
.\.venv\Scripts\python.exe -m coverage report
.\.venv\Scripts\python.exe -m ruff check app tests launcher.py
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
pre-commit install
```

Тесты покрывают реестр инструментов, safety-политики, undo, сессии,
RAG, retry/fallback LLM, диагностику, память, конфиг, таймауты
инструментов и голосовой пайплайн. CI гоняет Python 3.10/3.11/3.12,
ruff, mypy, coverage и `pip-audit`: `.github/workflows/tests.yml`.
Зависимости обновляет Dependabot (`.github/dependabot.yml`).

Конфигурация и пути теперь централизованы: `app/config.py` (загрузка,
валидация, атомарное сохранение) и `app/paths.py` (единый `BASE_DIR`
и каталоги данных).
