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
- Туннель: `app/tunnel.py` (`TunnelManager`) поднимает cloudflared
  при старте JARVIS (`remote.auto_tunnel`; в примере `false`, в живом
  конфиге проекта включён):
  named tunnel (`remote.tunnel_name` + `remote.public_url`) или quick
  tunnel `--url http://127.0.0.1:8765`. Транспорт —
  `remote.tunnel_protocol` (по умолчанию `http2`: QUIC/UDP часто
  блокируется и туннель не регистрируется; `quic` — если UDP открыт).
  Адрес пишется в `data/remote_url.json` и публикуется в rendezvous
  только после успешного `GET <url>/health` (до 90 c); heartbeat
  раз в 5 минут тоже проверяет адрес. PID — `data/tunnel.pid`,
  адрес — `data/remote_url.json`; `launcher_web`/`launcher_remote`
  останавливают только свой процесс. Ручной вариант —
  `scripts\start_tunnel_cf.ps1` (не вместе с автоподъёмом; скрипт
  тоже передаёт `--protocol` и проверяет `/health`).
- Rendezvous: `app/tunnel.py` шифрует публичный URL AES-GCM
  (ключ = SHA-256(token)) и публикует в секретный ntfy-топик
  (`remote.rendezvous`, `remote.rendezvous_url`, `remote.rendezvous_topic`,
  heartbeat каждые 5 минут). Телефон узнаёт адрес из QR (`rdvu`/`rdvt`)
  и обновляет `server_url`, когда старый URL перестал отвечать.
  Токен и URL в открытом виде на ntfy не попадают.
- Сопряжение: `app/pairing.py` собирает deep link
  `jarvis://pair?url=...&token=...&lan=...&rdvu=...&rdvt=...` и
  PNG-DataURL QR. RPC `get_pairing` доступен только локальному UI
  (входит в `LOCAL_ONLY_METHODS`, проверяется до политики методов),
  поэтому токен не уходит в браузер по сети. `remote_info.ps1`
  дублирует адреса/токен в консоли.
- Доступ в любой сети — **Tailscale** (рекомендуемый путь):
  `app.remote_server._tailscale_ip()` спрашивает `tailscale ip -4`
  (PATH или `C:\Program Files\Tailscale\tailscale.exe`, кэш 30 c)
  и берёт адрес из `100.64.0.0/10`. Сервер слушает `0.0.0.0`, adapter
  Tailscale в Windows — профиль Private, а у `python.exe`/`pythonw.exe`
  проекта уже есть inbound-allow для Private, поэтому отдельное правило
  под порт 8765 не нужно. На телефоне должен быть тот же аккаунт
  Tailscale и включённый VPN-режим. `RemoteServer.tailscale_url`
  попадает в `data/remote_status.json` и лог при старте;
  `scripts\remote_info.ps1` печатает адрес первым.
- Публичный адрес резолвится по приоритету (для QR/сопряжения):
  Tailscale (`100.x`) → `JARVIS_PUBLIC_URL` → `remote.public_url` →
  `data/remote_url.json` → LAN из `data/remote_status.json` →
  локальный URL. `tailscale ip -4` вызывается только когда Tailscale
  есть на ПК; если он выключен — приоритет переходит к туннелю.
  Rendezvous (`rdvu`/`rdvt`) в ссылку попадает только когда основным
  адресом выбран публичный туннель: Tailscale-адрес стабилен, и
  «автообновление» на резервный домен телефону не нужно.
- Android: нативный пульт `android/app/src/main/java/.../MainActivity.java`
  (без WebView): чат через Bearer + `POST /rpc`, MIC → `POST /stt`,
  экраны задач/журнала в меню, автореконнект. `QrScanActivity` —
  встроенный сканер QR (CameraX + ZXing core 3.5.3, YUV→яркость,
  1080p, поворот по `rotationDegrees`, Hybrid + GlobalHistogram,
  зум 1×/2×/3×, AF по касанию/центру, счётчик кадров), меню
  «⋮ → Сканировать QR» и кнопка в настройках; результат
  валидируется `PairLink.parseText`. Поле адреса в настройках
  принимает и целую ссылку `jarvis://pair?...`.
  `Rendezvous.java` читает `ntfy/<topic>/json?poll=1&since=all`,
  расшифровывает AES-GCM и обновляет `server_url`.
  `RemoteService` держит foreground-уведомление `/health` и при
  обрыве раз в минуту обновляет адрес через rendezvous (проверка
  здоровья вынесена в отдельный поток). `BootReceiver` поднимает
  службу после перезагрузки телефона. Версия 2.4 (versionCode 6).
  Сборка:
  `& "$env:USERPROFILE\gradle-8.9\bin\gradle.bat" -p android assembleDebug`;
  release-подпись — `android/keystore.properties` + `*.jks` (.gitignore).
- UI — PWA: `ui/manifest.webmanifest`, `ui/sw.js`, иконки `ui/icon-*.png`.
- Камера: `app/camera_service.py` — один поток захвата (ПК-камера index,
  сетевой MJPEG-URL IP Webcam или источник `phone`), последний кадр/JPEG
  и подписчики. Windows: **MSMF-first + MJPG**, 640×480, ~30 fps захвата,
  пресеты `performance`/`balanced`/`quality`, лёгкая резкость,
  `probe_cameras` с отсевом чёрных/виртуальных источников.
  `GET /camera.mjpg` отдаёт MJPEG по cookie или `stream_token`.
- Камера телефона: приложение шлёт уже повёрнутый и зеркалённый JPEG
  на `POST /camera/frame?rotate=0&mirror=0` (Bearer,
  `X-Jarvis-Device`), сервер держит HTTP/1.1 keep-alive и принимает
  кадры только при `camera.source == "phone"` (иначе 409).
  `submit_external_jpeg()` в этом случае не декодирует кадр, а
  пересылает байты в MJPEG — приём ограничен `camera.ingest_fps`
  (по умолчанию 30), а жестам кадр уходит не чаще `analyze_fps`.
  Если `rotate`/`camera.mirror` всё же требуют преобразования,
  кадр декодируется и кодируется заново на ПК; `status()` отдаёт
  `phone_state` (`idle`/`live`/`stale`),
  `phone_device`, `phone_frames`. Если ответ 409/503, сервер сам
  переключает источник на `phone` (внутренний `bridge.handle`,
  consumer `phone`, не проходит через RPC-политику) — троттлинг
  `PHONE_SWITCH_MIN_INTERVAL = 3 c`, отключается
  `camera.phone_auto_switch`. При переключении перезапускаются жесты,
  если `gestures.enabled`. На старте ПК источник `phone` не
  автостартует (`ui_bridge._autostart_media`); устаревшие кадры
  (`phone_timeout`) не отдаются в `latest_jpeg`/`snapshot_jpeg`.
- Android-камера: `CameraActivity` (превью, объектив, фонарик,
  480p/720p/1080p, 5–30 fps, статус ПК через `get_camera`) +
  `CameraStreamService` (foreground `type=camera`, CameraX 1.3.4
  `ImageAnalysis` YUV→NV21→JPEG, поворот и зеркало на телефоне,
  три потока отправки, keep-alive, `EXTRA_LENS/FPS/WIDTH/HEIGHT`).
  Служба сама вызывает `set_camera {source:"phone", mirror:false}`
  при старте/смене объектива с backoff (3→30 c) и `{enabled:false}`
  при остановке; на 401/403/409/503/IO сбрасывает `sourceReady`
  и повторяет. После смены объектива кадры идут с
  `rotate=0&mirror=0`: ПК не должен повторять преобразования.
  CameraX требует `android.useAndroidX=true`; версия 1.3.4 выбрана
  под compileSdk 34 (JPEG-выход `OUTPUT_IMAGE_FORMAT_JPEG` появился
  только в 1.4).
- Android-сопряжение: `MainActivity` принимает `jarvis://pair` (VIEW,
  `singleTop`), показывает подтверждение с хостом, сохраняет
  `server_url`/`server_token`/`server_fallback` и сразу подключается.
  `connect()` при недоступности основного адреса пробует запасной
  LAN-адрес и меняет их местами; ручной ввод адреса очищает fallback.
  `allowBackup=false`, чтобы токен не попадал в бэкапы.
- Vision камеры: инструмент `look_at_camera` (`app/pc_agent.py`) +
  RPC `camera_look` → Groq Vision по `camera.snapshot_jpeg()`;
  выключается `camera.vision_enabled`.
- UI камеры: один body-level `<img id="camera-stream">`; камера может
  быть фоном всех страниц (`body.camera-bg`) с переключателем «ФОН»;
  кинематографичный HUD (`body.camera-immersive`) скрывает sidebar,
  context-panel и statusbar, fullscreen по `F`. Настройки — в drawer,
  легенда — в отдельной панели. Service worker не кэширует MJPEG.
  В селекторе источника есть «Камера телефона (JARVIS)»: поля URL/индекса
  блокируются, бейдж показывает WAIT, пока `phone_state != live`.
- Жесты: `app/gestures.py` — MediaPipe Tasks HandLandmarker
  (`models/hand_landmarker.task`), `detection_width=256`,
  `num_hands=2`, стабильность/cooldown, статические/динамические/
  двуручные жесты, профили `media`/`jarvis`/`pointer`/`windows`/
  `presentation`. Pointer — opt-in, EMA + optical flow + drag/click;
  аварийный выход кулаком/ладонью. Действия идут через
  `app.main.announce/submit_chat_message/stop_speaking` и pyautogui.
  Настройки — `camera`/`gestures` в `config/config.json`.
- MediaPipe ставится без зависимостей:
  `pip install --no-deps mediapipe==1.2.3` +
  `pip install absl-py~=2.3 flatbuffers~=25.9`, чтобы не менять версии
  OpenCV/SoundDevice. Модель кладётся в `models/` и включается в
  `jarvis.spec` (`datas`, hidden imports).
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

## Плагины, i18n, профили и поиск

- Плагины: `app/plugins.py` (`JarvisPlugin`, `PluginManager`), каталог
  `plugins/`. `register_all_tools()` после ядра загружает их через
  `PluginManager` (изоляция + откат частичных регистраций). Доступ к
  менеджеру: `app.tools.get_plugin_manager()`. Пример —
  `plugins/example_tools.py`. Конфиг: `plugins.{enabled,dir,disabled,allowed_permissions}`.
- RPC-методы UI: `list_plugins`, `reload_plugins`, `get_profiles`,
  `set_profile`, `set_language` (`app/ui_bridge.py`).
- Локализация: `app/i18n.py` + `app/locales/{ru,en}.json`, ключи
  `status.<name>.label`. Переключение — `language` в config или RPC.
- Профили: `app/config.py` (`get_profiles`, `apply_profile`,
  `get_active_profile`), глубокое слияние поверх базового конфига.
- Умный контекст: `app/context.py` (`build_context`) — память + сессии
  (FTS5) + RAG, подмешивается к системному промпту в
  `main.process_command`.
- Поиск: FTS5 в `app/sessions.py` и `app/rag.py` с fallback; SQLite в
  режиме WAL. LLM ходит через keep-alive `requests.Session`
  (`app/llm_client._http_session`).

## Профиль производительности

- `app/performance.py` определяет tier (`low`/`standard`/`high`) по
  числу физических ядер и RAM; `performance.tier` в config.json или
  `JARVIS_TIER` задают вручную, `performance.auto: false` отключает
  автопрофиль. Значения применяются как clamps при чтении настроек и
  не перезаписывают config.json.
- Low-профиль: камера 12 fps / JPEG 78 / sharpness 0.25 / 2 клиента,
  одна рука для жестов, overlay 6 fps, 3 потока инструментов, 2 потока
  задач, 40 схем на запрос, без category planning, polling 250 мс,
  micro-meter 500 мс, лёгкий UI по умолчанию. `camera.ingest_fps`
  профиль не урезает: сырой JPEG с телефона не декодируется и
  остаётся на 30 fps.

## Проверки

- План развития: `docs/IMPROVEMENT_PLAN.md`.
- Логи: `data/logs/jarvis.log`.
- `python -m pytest tests/`.
- `python scripts/perf_check.py --compare` — импорт, event bus,
  журнал задач, JPEG, диск; baseline в `data/perf_baseline.json`
  (gitignored), обновление — `--save`.
- Версия EXE и установщика — `MyAppVersion` в `packaging/jarvis.iss`.
