# JARVIS — заметки для агентов

## Запуск

- Оконный HUD: `scripts\start.ps1` (вызывает `launcher_web.py` через pythonw).
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

## Проверки

- Логи: `data/logs/jarvis.log`.
- `python -m pytest tests/`.
