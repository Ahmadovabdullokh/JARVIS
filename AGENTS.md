# JARVIS — заметки для агентов

## Запуск

- Оконный HUD: `scripts\start.ps1` (вызывает `launcher_web.py` через pythonw).
- Автозапуск: `scripts\install_autostart.ps1` создаёт ярлык в папке автозагрузки
  (предпочитает `dist\JARVIS\JARVIS.exe`), `scripts\remove_autostart.ps1` — убирает.
  Планировщик задач с триггером на разблокировку требует прав администратора,
  поэтому вместо него `launcher_web.py` сам следит за десктопом
  (`JarvisBridgeApi._unlock_watch_loop`, Winlogon→Default) и показывает окно
  при разблокировке. В приложении есть single-instance mutex
  (`Local\JARVIS-SingleInstance`).
- Tk-фолбэк: `scripts\start.ps1 -Tk` или `python launcher.py`.
- Отладка WebView2: `python launcher_web.py --debug` (CDP на :9222), `--smoke` — автозакрытие через 3 с.

## Веб-интерфейс (ui/ + launcher_web.py)

- Окно хостится через **pywebview** (EdgeChromium/WebView2), НЕ через пакет `webview2` —
  у `webview2==0.0.4` сломан канал Python→JS (`dll.post`/`dll.evaluate` не доставляют
  сообщения в страницу), поэтому он удалён из requirements.
- JS↔Python: единый метод `rpc(jsonString)` в `JarvisBridgeApi` (js_api pywebview),
  протокол `{"type":"jarvis_request","id","method","payload"}` →
  `{"type":"jarvis_response","id","ok","data"}`. Все вызовы сериализованы очередью
  в `ui/js/api.js` (общий shared buffer старого транспорта не используется, но
  сериализация оставлена как защита).
- `pythonnet` грузится через `pythonnet.load("coreclr", runtime_config=...)` —
  netfx-путь сломан; runtimeconfig генерируется в `data/dotnet.runtimeconfig.json`
  и требует `Microsoft.WindowsDesktop.App` (WinForms-бэкенд pywebview).

## Патч site-packages (ВАЖНО)

В `.venv/Lib/site-packages/webview/platforms/winforms.py` пропатчен
`OpenFolderDialog`: на .NET 10 тип `FileDialogNative+IFileDialog` удалён из
WinForms, из-за чего импорт модуля падал. Патч оборачивает reflection в try/except
и добавляет fallback на `FolderBrowserDialog`. При переустановке pywebview патч
теряется — нужно применить заново (или обновить pywebview, если баг исправлен).

## Удалённый доступ и мобильный клиент

- `app/remote_server.py`: токен обменивается на HttpOnly-cookie через
  `POST /login` (совместимость: `GET /?token=` один раз редиректит);
  rate-limit — 10 неудач → бан IP на 120 c, `X-Forwarded-For` только от
  доверенных прокси (`JARVIS_TRUSTED_PROXIES`); `GET /health` открыт;
  `POST /stt` принимает аудио и гоняет через ffmpeg → `VoiceListener._transcribe`.
- Политика методов: `remote.allowed_methods` (приоритет) или
  `remote.read_only` в `config/config.json`; `_remote_policy()` читается
  на каждом запросе. Для чата с телефона нужен `send_message`.
- `RemoteServer` автозапускается из `launcher_web.main()` вместе с
  обычным ПК-приложением (`remote.auto_start`, по умолчанию `true`),
  адрес `remote.host` (`0.0.0.0` — Wi-Fi).
- Туннель: `scripts\start_tunnel_cf.ps1` (cloudflared, quick или named
  tunnel через `remote.tunnel_name`).
- Android: нативный пульт `android/app/src/main/java/.../MainActivity.java`
  (без WebView): чат через Bearer + `POST /rpc`, MIC → `POST /stt`,
  экраны задач/журнала в меню, автореконнект. `RemoteService` держит
  foreground-уведомление `/health`. Сборка:
  `& "$env:USERPROFILE\gradle-8.9\bin\gradle.bat" -p android assembleDebug`;
  release-подпись — `android/keystore.properties` + `*.jks` (.gitignore).
- UI — PWA: `ui/manifest.webmanifest`, `ui/sw.js`, иконки `ui/icon-*.png`.
- Push: `app/notifier.py` → Telegram (`notifications.telegram`); chat_id
  определяется сам через getUpdates после `/start`. Проверка:
  `python -m app.notifier --enable --test`.

## Голос и LLM

- TTS (`app/tts.py`): один Edge-стрим на весь текст, `stop()` для
  barge-in, `output_device` по имени/индексу из `tts_output_device`.
  Только мужские голоса (`FALLBACK_VOICES` — Brian/Andrew); женские
  и Dmitry заблокированы. Одна попытка на голос, неудачные голоса
  кешируются на 10 минут. Диагностика:
  `python scripts/tts_test.py [--speak|--offline]`.
- Barge-in: `voice_barge_in` в конфиге (default off — динамики
  попадают в микрофон, лучше с наушниками).
- `speak_text` — озвучка текстовых ответов (default on).
- `LLMClient.ask_stream()` — SSE-стриминг для режима чата;
  `assistant_partial` события → стрим-пузырь в `ui/js/app.js`.
- Circuit breaker в `LLMClient._circuit` (3 сбоя → 300 c паузы).
- Секреты: keyring-сервис `jarvis` — fallback после env/config
  (`_keyring_secret` в `app/config.py`).

## Кодовый агент

- Кодовая задача хранится в `app/code_state.py` и `data/code_state.json`:
  план, изменённые файлы, проверки, checkpoint/rollback.
- Перед правкой нужен `code_plan` и `code_read`; `run_python` /
  `run_powershell` не входят в набор code-режима.
- `LLMClient.ask_with_tools(code_state=...)` блокирует повторные
  вызовы, следит за отсутствием прогресса и автоматически запускает
  `code_verify` перед финальным ответом.
- Автопилот включается `code.autopilot`; вне проекта писать нельзя
  (`code.allow_outside_project`), commit/push — только при
  `code.allow_git_write`.
- Секреты вырезаются из логов/аргументов; `code_write` и `code_edit`
  блокируют вставку токенов.

## Проверки

- Логи: `data/logs/jarvis.log`.
- `python -m pytest tests/`.
