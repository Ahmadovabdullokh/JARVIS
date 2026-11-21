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

- `app/remote_server.py`: токен в query/`Authorization: Bearer`/cookie;
  rate-limit — 10 неудач → бан IP на 120 c; `GET /health` открыт;
  `POST /stt` принимает аудио и гоняет через ffmpeg → `VoiceListener._transcribe`.
- Политика методов: `remote.read_only` или `remote.allowed_methods`
  в `config/config.json` (см. `_remote_policy()`).
- Туннели: `scripts\start_tunnel_cf.ps1` (cloudflared, quick или named
  tunnel через `remote.tunnel_name`), `scripts\start_tunnel.ps1` — Pinggy.
- Android: `RemoteService` (foreground, /health-чек), WebView mic permission,
  автореконнект 10 c. Release-подпись — `android/keystore.properties` + `*.jks`
  (в .gitignore).
- UI — PWA: `ui/manifest.webmanifest`, `ui/sw.js`, иконки `ui/icon-*.png`.
- Push: `app/notifier.py` → Telegram о фоновых задачах
  (`notifications.telegram` в конфиге).

## Голос и LLM

- TTS (`app/tts.py`): стриминг по предложениям (`split_sentences`),
  `stop()` для barge-in, `output_device` по имени/индексу из
  `tts_output_device`.
- Barge-in: `voice_barge_in` в конфиге (default off — динамики
  попадают в микрофон, лучше с наушниками).
- `speak_text` — озвучка текстовых ответов (default on).
- `LLMClient.ask_stream()` — SSE-стриминг для режима чата;
  `assistant_partial` события → стрим-пузырь в `ui/js/app.js`.
- Circuit breaker в `LLMClient._circuit` (3 сбоя → 300 c паузы).
- Секреты: keyring-сервис `jarvis` — fallback после env/config
  (`_keyring_secret` в `app/config.py`).

## Проверки

- Логи: `data/logs/jarvis.log`.
- `python -m pytest tests/`.
