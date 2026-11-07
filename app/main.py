import queue
import threading
import time
import traceback

from dotenv import load_dotenv

from app import config as config_module
from app import persona
from app.commands import handle_command
from app.config import (
    code_backend_uses_copilot,
    get_code_backend,
    get_code_config,
    get_groq_config,
    get_llm_config,
    get_persona_config,
    get_tts_config,
    get_wake_config,
)
from app.listener import VoiceListener
from app.llm_client import LLMClient
from app.logging import get_logger
from app.memory import Memory
from app.observability import tracer
from app.paths import ensure_runtime_dirs
from app.pc_agent import PCAgent
from app.sessions import SessionStore
from app.status import set_status
from app.tts import TTS
from app.utils import safe_print
from app.voice_normalizer import process_voice_text

log = get_logger(__name__)

_COMMAND_QUEUE = queue.Queue()
_UI_EVENT_QUEUE = queue.Queue()
_STOP_EVENT = threading.Event()
_ACTIVE_AGENT = None
_LISTENER = None
_TRANSCRIPT_PREVIEW = False
_CHAT_MODE = "tasks"

CHAT_MODES = ("chat", "tasks", "code")


def submit_chat_message(text: str, mode: str = None) -> bool:
    text = str(text).strip()
    if not text:
        return False
    _COMMAND_QUEUE.put(("chat", text, get_chat_mode(mode)))
    return True


def get_chat_mode(mode: str = None) -> str:
    normalized = str(mode or _CHAT_MODE).strip().lower()
    return normalized if normalized in CHAT_MODES else "tasks"


def set_chat_mode(mode: str) -> str:
    global _CHAT_MODE
    _CHAT_MODE = get_chat_mode(mode)
    return _CHAT_MODE


def get_listener():
    return _LISTENER


def transcript_preview_enabled():
    return _TRANSCRIPT_PREVIEW


def set_transcript_preview(enabled: bool) -> None:
    global _TRANSCRIPT_PREVIEW
    _TRANSCRIPT_PREVIEW = bool(enabled)


def get_task_snapshot():
    if _ACTIVE_AGENT is None:
        return []
    try:
        return _ACTIVE_AGENT.tasks.list(limit=50)
    except Exception:
        return []


def cancel_task(task_id) -> bool:
    if _ACTIVE_AGENT is None:
        return False
    try:
        _ACTIVE_AGENT.tasks.cancel(task_id)
        return True
    except Exception:
        return False


def publish_ui_event(event_type: str, payload) -> None:
    _UI_EVENT_QUEUE.put((event_type, payload))


def drain_ui_events():
    events = []
    while True:
        try:
            events.append(_UI_EVENT_QUEUE.get_nowait())
        except queue.Empty:
            return events


def stop_assistant() -> None:
    _STOP_EVENT.set()
    if _ACTIVE_AGENT is not None:
        try:
            _ACTIVE_AGENT.safety.stop()
        except Exception:
            pass
        try:
            _ACTIVE_AGENT.tasks.cancel_all()
        except Exception:
            pass


def get_command_catalog(pc_agent: PCAgent) -> list[dict]:
    disabled = getattr(pc_agent, "_disabled_legacy_tools", set())
    catalog = [
        item
        for item in pc_agent.get_tools()
        if item.get("function", {}).get("name") not in disabled
    ]
    seen = {
        item.get("function", {}).get("name")
        for item in catalog
    }
    for item in pc_agent.registry.schemas():
        name = item.get("function", {}).get("name")
        if name and name not in seen:
            seen.add(name)
            catalog.append(item)

    local_commands = [
        ("local_time", "Сказать текущее время."),
        ("local_date", "Назвать сегодняшнюю дату."),
        ("remember_fact", "Запомнить факт: «запомни, что …»."),
        ("recall_memory", "Показать, что JARVIS помнит."),
        ("exit_assistant", "Завершить работу JARVIS."),
    ]
    catalog.extend(
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
            },
        }
        for name, description in local_commands
    )
    return catalog


# ============================================================
# CONFIG
# ============================================================

def load_config() -> dict:
    """Загружает конфигурацию через app.config (fallback на example)."""
    return config_module.load_config(dotenv_loader=load_dotenv)


# ============================================================
# VOICE NORMALIZATION
# ============================================================

def normalize_voice_text(text: str, wake_words=None):
    """
    Возвращает (текст без обращения, было ли обращение «Джарвис»).
    """

    if not text:
        return "", False

    try:
        result = process_voice_text(text, wake_words=wake_words)

        if isinstance(result, tuple):
            normalized = result[0] if result else ""
            has_wake_word = bool(result[1]) if len(result) > 1 else False
        else:
            normalized = result
            has_wake_word = False

        if normalized is None:
            return "", has_wake_word

        return str(normalized).strip(), has_wake_word

    except Exception as error:
        log.info(
            f"[NORMALIZER ERROR] "
            f"{type(error).__name__}: {error}"
        )

        return text.strip(), False


# ============================================================
# SPEECH
# ============================================================

def speak(tts: TTS, text: str) -> bool:
    """
    Озвучивает текст и обновляет статус анимации.
    Возвращает False, если облачная озвучка недоступна.
    """

    text = str(text).strip()

    if not text:
        return True

    set_status("speaking")

    try:
        ok = tts.speak(text)
        if not ok:
            publish_ui_event(
                "error",
                "Edge TTS недоступен. Проверьте подключение к сети, сэр.",
            )
        return bool(ok)

    except Exception as error:
        log.info(
            f"[SPEECH ERROR] "
            f"{type(error).__name__}: {error}"
        )
        publish_ui_event(
            "error",
            f"Ошибка озвучки: {error}",
        )
        return False

    finally:
        set_status("ready")


# ============================================================
# INITIALIZATION
# ============================================================

def initialize():
    """
    Создаёт необходимые компоненты JARVIS.
    """

    set_status("starting")
    ensure_runtime_dirs()

    config = load_config()
    set_chat_mode(str(config.get("chat_mode", "tasks")))
    groq_config = get_groq_config(config)
    llm_config = get_llm_config(config)
    tts_config = get_tts_config(config)
    persona_config = get_persona_config(config)
    wake_config = get_wake_config(config)

    api_key = groq_config["api_key"]
    stt_local_model = str(config.get("stt_local_model", "")).strip()

    if not api_key and not stt_local_model:
        log.info(
            "[JARVIS] Голосовой ввод отключён: нет GROQ_API_KEY "
            "и локальной STT-модели. Чат и режим кода остаются "
            "доступны."
        )

    if not llm_config["api_key"] and not llm_config["base_url"]:
        log.info(
            "[JARVIS] LLM отключена: укажите DEEPSEEK_API_KEY "
            "в .env."
        )

    log.info("[JARVIS] Инициализация компонентов...")
    log.info(
        f"[JARVIS] LLM: {llm_config['provider']} / "
        f"{llm_config['model']}"
    )

    # Распознавание речи
    listener = VoiceListener(
        api_key=api_key,
        sample_rate=groq_config["sample_rate"],
        silence_threshold=groq_config["silence_threshold"],
        min_speech_seconds=groq_config["min_speech_seconds"],
        max_speech_seconds=groq_config["max_speech_seconds"],
        silence_duration=groq_config["silence_duration"],
        initial_silence_seconds=groq_config[
            "initial_silence_seconds"
        ],
        noise_adapt_k=groq_config["noise_adapt_k"],
        noise_max_ratio=groq_config["noise_max_ratio"],
        language=groq_config["language"],
        model=groq_config["stt_model"],
        prompt=groq_config["stt_prompt"],
        local_model=stt_local_model,
        local_device=str(config.get("stt_local_device", "cpu")),
        local_compute_type=str(
            config.get("stt_local_compute_type", "int8")
        ),
    )

    global _LISTENER
    _LISTENER = listener
    set_transcript_preview(bool(config.get("transcript_preview", False)))

    # Синтез речи
    tts = TTS(
        rate=tts_config["rate"],
        voice=tts_config["voice"],
        pitch=tts_config["pitch"],
        voices=tts_config["voices"],
        offline_fallback=bool(
            config.get("tts_offline_fallback", False)
        ),
    )

    # Управление компьютером
    pc_agent = PCAgent(
        api_key=api_key,
        vision_model=groq_config["vision_model"],
        config=config,
    )

    # Долговременная память
    memory = Memory(
        max_facts=int(config.get("memory_size", 50)),
    )
    pc_agent.memory = memory
    pc_agent.registry.context.memory = memory
    pc_agent.registry.context.cancel_event = _STOP_EVENT
    pc_agent.safety.resume()

    global _ACTIVE_AGENT
    _ACTIVE_AGENT = pc_agent

    # Языковая модель
    agent_config = (
        config.get("agent", {})
        if isinstance(config.get("agent"), dict)
        else {}
    )
    session_store = SessionStore()
    session_id = (
        session_store.latest_session_id()
        or session_store.create_session("JARVIS")
    )
    llm_available = bool(
        llm_config["api_key"]
        or llm_config["base_url"]
        or llm_config["provider"] == "ollama"
    )
    llm = LLMClient(
        use_llm=llm_config["enabled"] and llm_available,
        api_key=llm_config["api_key"],
        model=llm_config["model"],
        max_history=int(llm_config["session_history"]),
        max_tokens=int(agent_config.get("max_tokens", 3000)),
        tool_result_limit=int(
            agent_config.get("tool_result_limit", 12000)
        ),
        on_event=lambda event, payload: publish_ui_event(
            f"llm_{event}",
            payload,
        ),
        cancel_event=_STOP_EVENT,
        max_retries=int(llm_config["max_retries"]),
        retry_backoff=float(llm_config["retry_backoff"]),
        session_store=session_store,
        session_id=session_id,
        provider=llm_config["provider"],
        base_url=llm_config["base_url"] or None,
        fallback_base_url=(
            llm_config["fallback_base_url"] or None
        ),
        fallback_model=llm_config["fallback_model"],
        fallback_api_key=llm_config["fallback_api_key"],
        parallel_tool_calls=bool(
            llm_config["parallel_tool_calls"]
            or agent_config.get("parallel_tool_calls", False)
        ),
        tracer=tracer(),
        untrusted_tool_names=pc_agent.untrusted_tools,
        request_timeout=llm_config["request_timeout"],
    )

    def announce(message: str) -> None:
        _COMMAND_QUEUE.put(("announce", message))

    pc_agent.set_announcer(announce)

    def emergency_stop():
        stop_assistant()
        announce("Аварийная остановка выполнена.")

    hotkey_status = pc_agent.safety.start_hotkey_listener(
        on_stop=emergency_stop
    )
    log.info(f"[JARVIS] {hotkey_status}")

    log.info("[JARVIS] Все компоненты инициализированы.")

    return (
        listener,
        tts,
        pc_agent,
        llm,
        memory,
        persona_config,
        wake_config,
    )


# ============================================================
# CODE MODE — DeepSeek coding agent / GitHub Copilot fallback
# ============================================================

def copilot_backend_available(backend: str) -> bool:
    backend = str(backend or "auto").strip().lower()
    if backend == "vscode":
        return True
    import shutil

    return bool(shutil.which("copilot") or shutil.which("copilot.exe"))


def run_copilot_backend(pc_agent: PCAgent, task: str, trace=None):
    """
    В режиме кода отправляет задачу напрямую GitHub Copilot.

    Возвращает текст результата или None, если нужно
    перейти к резервному ассистенту.
    """

    config = pc_agent.config if isinstance(pc_agent.config, dict) else {}
    code_config = get_code_config(config)

    if not code_config.get("enabled", True):
        return None

    backend = get_code_backend(config)

    if backend not in {"auto", "cli", "vscode"}:
        return None

    if not copilot_backend_available(backend):
        if backend != "cli":
            return None
        return (
            "Копилот CLI не установлен. "
            "Установите его командой npm install -g @github/copilot "
            "и выполните 'copilot' один раз для входа."
        )

    arguments = {
        "task": str(task or ""),
        "timeout": int(code_config.get("timeout", 900)),
        "cli_args": list(code_config.get("cli_args") or []),
    }
    project = str(code_config.get("project") or "").strip()
    if project:
        arguments["project"] = project

    tool = "copilot_vscode_task" if backend == "vscode" else "copilot_cli_task"

    log.info(f"[CODE MODE] Задание уходит в GitHub Copilot ({backend}).")
    if trace is not None:
        try:
            trace.event("copilot_dispatch", backend=backend, tool=tool)
        except Exception:
            pass

    result = pc_agent.registry.execute(tool, arguments)
    result_text = str(result or "").strip()

    failed = (
        result_text.startswith("Ошибка")
        or "не установлен" in result_text.lower()
    )

    if failed:
        message = result_text or "Копилот вернул пустой результат."
        if trace is not None:
            try:
                trace.event("copilot_failed", detail=message[:300])
            except Exception:
                pass
        if backend == "auto" and code_config.get("fallback", True):
            return None
        return message

    if trace is not None:
        try:
            trace.event("copilot_done", result=result_text[:300])
        except Exception:
            pass
    return result_text or "Копилот завершил задание."


# ============================================================
# COMMAND PROCESSING
# ============================================================

def process_command(
    text: str,
    tts: TTS,
    pc_agent: PCAgent,
    llm: LLMClient,
    memory: Memory = None,
    persona_config: dict = None,
    speak_output: bool = True,
    source: str = "chat",
    mode: str = "tasks",
) -> bool:
    """
    Обрабатывает команду.

    Возвращает False, если нужно завершить работу.
    Режимы: chat — просто беседа; tasks — по умолчанию;
    code — инженерный режим для проектов и VS Code.
    """

    mode = get_chat_mode(mode)
    text = text.strip()

    if not text:
        return True

    persona_config = persona_config or persona.normalize_config()
    address = persona_config["address"]
    trace = tracer().start(text, source=source, mode=mode)

    def finish_trace(answer, status="ok"):
        trace.finish(answer, status=status)

    safe_print(f"[USER] {text}")
    publish_ui_event("user", text)

    def respond(message: str) -> None:
        publish_ui_event("assistant", message)
        if speak_output:
            speak(tts, message)

    # --------------------------------------------------------
    # 1. Простые локальные команды (не в режимах chat/code)
    # --------------------------------------------------------

    if mode != "chat":
        try:
            result = handle_command(text, memory=memory)

            if result == "__EXIT__":
                line = persona.exit_line(persona_config)
                finish_trace(line, "exit")
                respond(line)
                return False

            if result == "__USER_CANCELLED__":
                finish_trace("cancel", "cancelled")
                respond(f"Действие отменено, {address}.")
                return True

            if result:
                log.info(f"[COMMAND] {result}")
                finish_trace(result, "local")
                respond(persona.address_result(result, persona_config))
                return True

        except Exception as error:
            trace.event(
                "error",
                stage="local_command",
                error=f"{type(error).__name__}: {error}",
            )
            log.info(
                f"[COMMAND ERROR] "
                f"{type(error).__name__}: {error}"
            )

    # --------------------------------------------------------
    # 2. Прямые команды управления компьютером (только tasks)
    # --------------------------------------------------------

    if mode == "tasks":
        try:
            result = pc_agent.handle(text)

            if result == "__EXIT__":
                line = persona.exit_line(persona_config)
                finish_trace(line, "exit")
                respond(line)
                return False

            if result == "__USER_CANCELLED__":
                finish_trace("cancel", "cancelled")
                respond(f"Действие отменено, {address}.")
                return True

            if result:
                log.info(f"[PC AGENT] {result}")
                finish_trace(result, "legacy")
                respond(persona.address_result(result, persona_config))
                return True

        except Exception as error:
            trace.event(
                "error",
                stage="legacy_command",
                error=f"{type(error).__name__}: {error}",
            )
            log.info(
                f"[PC AGENT ERROR] "
                f"{type(error).__name__}: {error}"
            )

    # --------------------------------------------------------
    # 3. Обработка через языковую модель
    # --------------------------------------------------------

    if not llm.use_llm:
        message = (
            "Не удалось обработать команду. Языковая модель "
            "отключена. Проверьте DEEPSEEK_API_KEY в .env."
        )
        finish_trace(message, "disabled")
        respond(message)
        return True

    set_status("thinking")

    pc_agent.current_trace = trace
    task_id = pc_agent.tasks.create(
        f"Запрос: {text}",
        kind="command",
        meta={"source": source},
    )
    pc_agent.tasks.start(task_id)
    answer = ""
    status = "ok"

    try:
        agent_config = (
            pc_agent.config.get("agent", {})
            if isinstance(pc_agent.config, dict)
            else {}
        )
        code_config = get_code_config(pc_agent.config)
        max_iterations = int(
            agent_config.get("max_iterations", 18)
        )
        if mode == "code":
            max_iterations = max(
                max_iterations,
                int(code_config.get("max_iterations", 30)),
            )

        copilot_answer = None
        if mode == "code" and code_backend_uses_copilot(
            pc_agent.config
        ):
            copilot_answer = run_copilot_backend(pc_agent, text, trace)
            if copilot_answer is not None:
                log.info(
                    "[CODE MODE] Ответ получен в GitHub Copilot."
                )
        elif mode == "code":
            log.info(
                "[CODE MODE] Работает DeepSeek-агент "
                f"({llm.model})."
            )

        categories = None
        if (
            copilot_answer is None
            and mode == "tasks"
            and agent_config.get("category_planning", True)
        ):
            categories = llm.plan_categories(
                text,
                pc_agent.registry.categories(),
            )
            if categories:
                log.info(f"[JARVIS] Категории инструментов: {categories}")
                trace.event(
                    "categories",
                    categories=", ".join(categories),
                )

        system = (
            persona.build_system_prompt(
                persona_config,
                persona.memory_summary(memory),
            )
            + persona.mode_system_appendix(mode)
        )
        if mode == "code" and copilot_answer is None:
            project = str(
                get_code_config(pc_agent.config).get("project") or ""
            ).strip()
            if project:
                system += (
                    f"\nПапка проекта по умолчанию: {project}. "
                    "Если пользователь не назвал другой проект — "
                    "работаешь с ним.\n"
                )

        if copilot_answer is not None:
            answer = copilot_answer
        elif mode == "chat":
            answer = llm.ask(text, system=system)
        else:
            if mode == "code":
                tools = pc_agent.get_code_llm_tools(text)
                log.info(f"[CODE MODE] Инструментов: {len(tools)}")
            else:
                tools = pc_agent.get_llm_tools(
                    text,
                    categories=categories,
                )

            answer = llm.ask_with_tools(
                prompt=text,
                system=system,
                tools=tools,
                tool_executor=pc_agent.execute_tool,
                max_iterations=max_iterations,
                task_manager=pc_agent.tasks,
                task_id=task_id,
                trace=trace,
                parallel_safe=pc_agent.is_tool_parallel_safe,
            )

        if answer:
            answer = str(answer).strip()

        if not answer:
            answer = "Не удалось получить ответ."
            reason = str(getattr(llm, "last_error", "")).strip()
            if reason:
                answer += f" Причина: {reason[:300]}"

        safe_print(f"[JARVIS] {answer}")

        respond(answer)

    except Exception as error:
        status = "error"
        log.info(
            f"[LLM ERROR] "
            f"{type(error).__name__}: {error}"
        )

        traceback.print_exc()
        trace.event(
            "error",
            error=f"{type(error).__name__}: {error}",
        )

        respond(
            f"Произошла ошибка при обработке запроса, {address}."
        )

    finally:
        pc_agent.current_trace = None
        task = pc_agent.tasks.get(task_id)
        if task is not None and task.get("status") in {
            "pending",
            "running",
        }:
            if status == "ok":
                pc_agent.tasks.complete(task_id, answer)
            else:
                pc_agent.tasks.fail(task_id, "Ошибка обработки запроса")
        trace.finish(answer, status=status)

    return True


# ============================================================
# MAIN LOOP
# ============================================================

def run_assistant(
    listener: VoiceListener,
    tts: TTS,
    pc_agent: PCAgent,
    llm: LLMClient,
    memory: Memory = None,
    persona_config: dict = None,
    wake_config: dict = None,
) -> None:
    """
    Основной цикл голосового помощника.
    """

    persona_config = persona_config or persona.normalize_config()
    wake_config = wake_config or {
        "enabled": False,
        "wake_words": ["джарвис"],
        "cooldown": 1.5,
        "ack": "",
        "follow_up_seconds": 8.0,
    }

    log.info("[JARVIS] Ассистент запущен.")

    startup = persona.startup_line(persona_config)
    speak(tts, startup)
    publish_ui_event("assistant", startup)
    publish_ui_event("command_catalog", get_command_catalog(pc_agent))

    voice_commands = queue.Queue()
    _STOP_EVENT.clear()
    pc_agent.safety.resume()
    stop_listening = _STOP_EVENT
    pause_listening = threading.Event()
    last_wake_ack = 0.0
    follow_up_until = 0.0

    def listen_for_voice_commands() -> None:
        nonlocal last_wake_ack, follow_up_until

        try:
            while not stop_listening.is_set():
                if pause_listening.wait(timeout=0.1):
                    continue
                try:
                    recognized_text = listener.listen_once()
                except Exception as error:
                    if stop_listening.is_set():
                        break
                    log.info(
                        f"[MIC ERROR] "
                        f"{type(error).__name__}: {error}"
                    )
                    publish_ui_event(
                        "error",
                        f"Ошибка микрофона: {error}",
                    )
                    time.sleep(1)
                    continue

                if pause_listening.is_set():
                    continue

                if not recognized_text:
                    continue

                log.info(f"[RECOGNIZED] {recognized_text}")
                text, has_wake_word = normalize_voice_text(
                    recognized_text,
                    wake_config["wake_words"],
                )

                if wake_config["enabled"] and not has_wake_word:
                    if time.monotonic() > follow_up_until:
                        log.info(
                            "[WAKE] Пропущено: нет обращения «Джарвис»."
                        )
                        continue

                if (
                    wake_config["enabled"]
                    and has_wake_word
                    and not text
                ):
                    now = time.monotonic()
                    if (
                        now - last_wake_ack
                        >= wake_config["cooldown"]
                    ):
                        last_wake_ack = now
                        follow_up_until = (
                            now
                            + wake_config["follow_up_seconds"]
                        )
                        voice_commands.put(("wake", ""))
                    continue

                if text:
                    if has_wake_word:
                        follow_up_until = (
                            time.monotonic()
                            + wake_config["follow_up_seconds"]
                        )
                    else:
                        follow_up_until = 0.0
                    log.info(f"[NORMALIZED] {text}")
                    if transcript_preview_enabled():
                        publish_ui_event("transcript_preview", text)
                        continue
                    voice_commands.put(("voice", text))
        except KeyboardInterrupt:
            log.info("[JARVIS] Получен сигнал остановки.")
            stop_listening.set()

    listener_thread = threading.Thread(
        target=listen_for_voice_commands,
        name="JARVIS-VoiceListener",
        daemon=True,
    )
    listener_thread.start()

    set_status("listening")

    try:
        while not stop_listening.is_set():
            mode = get_chat_mode()
            try:
                item = _COMMAND_QUEUE.get_nowait()
                source = item[0]
                text = item[1]
                mode = item[2] if len(item) > 2 else mode
            except queue.Empty:
                try:
                    source, text = voice_commands.get(timeout=0.1)
                except queue.Empty:
                    set_status("listening")
                    continue

            if source == "wake":
                pause_listening.set()
                try:
                    ack = (
                        wake_config["ack"]
                        or persona.wake_ack(persona_config)
                    )
                    publish_ui_event("assistant", ack)
                    speak(tts, ack)
                finally:
                    pause_listening.clear()
                    set_status("listening")
                continue

            if source == "announce":
                pause_listening.set()
                try:
                    publish_ui_event("assistant", text)
                    speak(tts, text)
                finally:
                    pause_listening.clear()
                    set_status("listening")
                continue

            pause_listening.set()
            try:
                should_continue = process_command(
                    text=text,
                    tts=tts,
                    pc_agent=pc_agent,
                    llm=llm,
                    memory=memory,
                    persona_config=persona_config,
                    speak_output=(source == "voice"),
                    source=source,
                    mode=mode,
                )
                if not should_continue:
                    stop_listening.set()
                    break
            except Exception as error:
                log.info(
                    f"[MAIN LOOP ERROR] "
                    f"{type(error).__name__}: {error}"
                )
                traceback.print_exc()
                publish_ui_event(
                    "error",
                    f"Ошибка выполнения команды: {error}",
                )
            finally:
                pause_listening.clear()
                set_status("listening")
    finally:
        stop_listening.set()
        try:
            pc_agent.safety.stop()
        except Exception:
            pass
        try:
            pc_agent.tasks.cancel_all()
        except Exception:
            pass
        try:
            pc_agent.registry.close()
        except Exception:
            pass
        global _ACTIVE_AGENT
        _ACTIVE_AGENT = None


# ============================================================
# ENTRY POINT
# ============================================================

def main() -> None:
    """
    Точка входа. Может вызываться непосредственно
    из launcher.py в отдельном потоке.
    """

    try:
        (
            listener,
            tts,
            pc_agent,
            llm,
            memory,
            persona_config,
            wake_config,
        ) = initialize()

        run_assistant(
            listener=listener,
            tts=tts,
            pc_agent=pc_agent,
            llm=llm,
            memory=memory,
            persona_config=persona_config,
            wake_config=wake_config,
        )

    except Exception as error:
        set_status("error")

        log.info(
            f"[FATAL ERROR] "
            f"{type(error).__name__}: {error}"
        )

        traceback.print_exc()

    finally:
        set_status("stopped")
        log.info("[JARVIS] Работа завершена.")


if __name__ == "__main__":
    main()