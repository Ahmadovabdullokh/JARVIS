import ctypes
import math
import os
import threading
import time
import tkinter as tk
import traceback
from tkinter import messagebox, scrolledtext, ttk

from app import config as config_module
from app import persona, telemetry, ui_theme
from app.doctor import format_report, run_checks
from app.logging import get_logger
from app.main import (
    cancel_task,
    drain_ui_events,
    get_listener,
    get_task_snapshot,
    main,
    set_chat_mode,
    set_transcript_preview,
    stop_assistant,
    submit_chat_message,
    transcript_preview_enabled,
)
from app.observability import tracer
from app.paths import BASE_DIR, CONFIG_FILE, DATA_DIR, ensure_runtime_dirs
from app.status import get_status, set_status

log = get_logger(__name__)
ensure_runtime_dirs()


class JarvisWindow:

    WIDTH = 1440
    HEIGHT = 920
    SIDEBAR_WIDTH = 390
    FPS_MS = 40
    TELEMETRY_MS = 2000
    TASKS_MS = 1500

    def __init__(self, root: tk.Tk):
        self.root = root

        self.root.title(
            "J.A.R.V.I.S. — Just A Rather Very Intelligent System"
        )
        self.root.geometry(f"{self.WIDTH}x{self.HEIGHT}")
        self.root.minsize(1120, 720)
        self.root.resizable(True, True)

        self.bg = ui_theme.BG
        self.panel = ui_theme.PANEL
        self.text_color = ui_theme.TEXT
        self.muted = ui_theme.MUTED
        self.accent = ui_theme.ACCENT
        self.accent2 = ui_theme.ACCENT_SOFT

        self.root.configure(bg=self.bg)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.layout = tk.Frame(self.root, bg=self.bg)
        self.layout.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(
            self.layout,
            bg=self.bg,
            width=self.SIDEBAR_WIDTH,
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.canvas = tk.Canvas(
            self.sidebar,
            width=self.SIDEBAR_WIDTH,
            height=430,
            bg=self.bg,
            highlightthickness=0,
        )
        self.canvas.pack(fill="x", pady=(12, 0))

        self.content = tk.Frame(
            self.layout,
            bg=self.bg,
            padx=16,
            pady=16,
        )
        self.content.pack(side="left", fill="both", expand=True)

        self.running = True
        self.jarvis_dead = False
        self.time = 0.0
        self.current_status = None
        self.mic_level = 0.0
        self.mic_target = 0.0
        self._reactor = {}
        self._mic_items = {}
        self._last_tick = time.monotonic()
        self._particles = []
        self._waves = []

        self.center_x = self.SIDEBAR_WIDTH // 2
        self.center_y = 205

        self._style_root()
        self._draw_interface()
        self._draw_telemetry()
        self._draw_content_header()
        self._draw_chat_and_commands()
        self._polish_widgets()
        self._boot_sequence()

        self.jarvis_thread = threading.Thread(
            target=self.run_jarvis,
            name="JARVIS-Main",
            daemon=True,
        )
        self.jarvis_thread.start()

        self._start_tray()

        self.animate()
        self.update_telemetry()
        self.update_tasks()
        self.check_jarvis()
        self.poll_ui_events()

        threading.Thread(
            target=self.mic_meter_loop,
            name="JARVIS-MicMeter",
            daemon=True,
        ).start()

    def _style_root(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "Jarvis.TNotebook",
            background=self.bg,
            borderwidth=0,
            tabmargins=(0, 0, 0, 0),
        )
        style.configure(
            "Jarvis.TNotebook.Tab",
            background=ui_theme.PANEL_ALT,
            foreground=self.muted,
            padding=(18, 9),
            font=("Segoe UI", 9, "bold"),
            borderwidth=0,
        )
        style.map(
            "Jarvis.TNotebook.Tab",
            background=[("selected", self.panel)],
            foreground=[("selected", self.accent)],
        )
        style.configure(
            "Jarvis.Treeview",
            background=ui_theme.PANEL,
            fieldbackground=ui_theme.PANEL,
            foreground=self.text_color,
            rowheight=30,
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        style.map(
            "Jarvis.Treeview",
            background=[("selected", ui_theme.ACCENT_DARK)],
            foreground=[("selected", "white")],
        )
        style.configure(
            "Jarvis.Treeview.Heading",
            background=ui_theme.PANEL_ALT,
            foreground=self.accent,
            font=("Segoe UI", 9, "bold"),
            borderwidth=0,
        )
        style.configure(
            "Jarvis.Vertical.TScrollbar",
            background=ui_theme.PANEL_ALT,
            troughcolor=self.bg,
            bordercolor=self.bg,
            arrowcolor=self.muted,
        )
        style.configure(
            "TCombobox",
            fieldbackground=ui_theme.PANEL_ALT,
            background=ui_theme.PANEL_ALT,
            foreground=self.text_color,
            arrowcolor=self.accent,
            bordercolor=ui_theme.BORDER,
            lightcolor=ui_theme.PANEL_ALT,
            darkcolor=ui_theme.PANEL_ALT,
            padding=6,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", ui_theme.PANEL_ALT)],
            foreground=[("readonly", self.text_color)],
            selectbackground=[("readonly", ui_theme.PANEL_ALT)],
            selectforeground=[("readonly", self.text_color)],
            background=[("active", ui_theme.CARD_ALT)],
        )
        style.configure(
            "TCheckbutton",
            background=self.bg,
            foreground=self.text_color,
            font=("Segoe UI", 8),
            focuscolor=self.bg,
        )
        style.map(
            "TCheckbutton",
            background=[("active", self.bg)],
            foreground=[("active", self.accent)],
        )
        style.configure(
            "TEntry",
            fieldbackground=ui_theme.PANEL_ALT,
            foreground=self.text_color,
            insertcolor=self.accent,
            bordercolor=ui_theme.BORDER,
        )
        try:
            self.root.option_add(
                "*TCombobox*Listbox.background",
                ui_theme.PANEL_ALT,
            )
            self.root.option_add(
                "*TCombobox*Listbox.foreground",
                self.text_color,
            )
            self.root.option_add(
                "*TCombobox*Listbox.selectBackground",
                ui_theme.ACCENT_DARK,
            )
            self.root.option_add(
                "*TCombobox*Listbox.selectForeground",
                "white",
            )
        except tk.TclError:
            pass

    def _polish_widgets(self):
        """Добавляет мягкий hover к обычным Tk-кнопкам.

        Делается одним проходом после построения интерфейса, чтобы не
        дублировать bind-и в каждом обработчике.
        """

        def apply(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Button):
                    try:
                        normal = child.cget("bg")
                        hover = ui_theme.mix(normal, self.accent, 0.16)
                        child.configure(cursor="hand2")
                        child.bind(
                            "<Enter>",
                            lambda _event, item=child, color=hover: item.configure(
                                bg=color
                            ),
                        )
                        child.bind(
                            "<Leave>",
                            lambda _event, item=child, color=normal: item.configure(
                                bg=color
                            ),
                        )
                    except tk.TclError:
                        pass
                apply(child)

        apply(self.layout)

    def _draw_interface(self):
        self._draw_background()

        self.canvas.create_text(
            self.center_x,
            28,
            text="J.A.R.V.I.S.",
            fill=self.text_color,
            font=ui_theme.TITLE_FONT,
        )
        self.canvas.create_text(
            self.center_x,
            56,
            text="JUST A RATHER VERY INTELLIGENT SYSTEM",
            fill=self.muted,
            font=ui_theme.SUBTITLE_FONT,
        )
        self.canvas.create_text(
            self.center_x,
            78,
            text=f"{persona.get_time_greeting()}, сэр",
            fill=self.accent,
            font=ui_theme.LABEL_FONT,
        )
        self.canvas.create_line(
            70,
            92,
            self.SIDEBAR_WIDTH - 70,
            92,
            fill=ui_theme.with_alpha(self.accent, 0.28),
            width=1,
        )

        self._build_reactor()

        self.canvas.create_text(
            self.center_x,
            366,
            text="STARK INDUSTRIES // ARC REACTOR",
            fill=ui_theme.DIM,
            font=ui_theme.SUBTITLE_FONT,
        )

        self.status_text = self.canvas.create_text(
            self.center_x,
            390,
            text="STARTING",
            fill=self.accent2,
            font=ui_theme.STATUS_FONT,
        )
        self.info_text = self.canvas.create_text(
            self.center_x,
            411,
            text="Запуск подсистем…",
            fill=self.muted,
            font=ui_theme.INFO_FONT,
        )

    def _draw_background(self):
        """Статичный градиент и HUD-уголки. Рисуем один раз."""

        height = 430
        steps = 40
        for index in range(steps):
            ratio = index / max(1, steps - 1)
            color = ui_theme.mix(
                ui_theme.BG_SOFT,
                ui_theme.PANEL,
                ratio * 0.85,
            )
            y0 = int(height * index / steps)
            y1 = int(height * (index + 1) / steps) + 1
            self.canvas.create_rectangle(
                0,
                y0,
                self.SIDEBAR_WIDTH,
                y1,
                fill=color,
                outline="",
            )

        bracket = ui_theme.with_alpha(self.accent, 0.35)
        margin = 18
        arm = 22
        for x_sign, y_sign in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            x = margin if x_sign > 0 else self.SIDEBAR_WIDTH - margin
            y = margin if y_sign > 0 else height - margin
            self.canvas.create_line(
                x,
                y,
                x + arm * x_sign,
                y,
                fill=bracket,
                width=1,
            )
            self.canvas.create_line(
                x,
                y,
                x,
                y + arm * y_sign,
                fill=bracket,
                width=1,
            )

    def _build_reactor(self):
        """Создаёт элементы реактора один раз.

        Раньше animate() каждый кадр удалял и создавал десятки объектов
        Canvas — именно это вызывало подтормаживание. Теперь элементы
        переиспользуются, а кадр лишь меняет координаты и цвета.
        """

        cx = self.center_x
        cy = self.center_y

        for radius, alpha in ((172, 0.18), (160, 0.26), (140, 0.3), (118, 0.22)):
            self.canvas.create_oval(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                outline=ui_theme.with_alpha(self.accent, alpha),
                width=1,
            )

        arcs = []
        for radius, extent, width, direction, color in (
            (148, 96, 2, 1, ui_theme.ACCENT_DARK),
            (124, 58, 2, -1, ui_theme.ACCENT),
            (98, 130, 1, 1, ui_theme.BORDER),
            (74, 44, 3, -1, ui_theme.VIOLET),
        ):
            item = self.canvas.create_arc(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                start=0,
                extent=extent,
                style="arc",
                outline=color,
                width=width,
            )
            arcs.append((item, radius, extent, direction))
        self._reactor["arcs"] = arcs

        glows = []
        for alpha in (0.14, 0.22, 0.34):
            item = self.canvas.create_oval(
                cx - 30,
                cy - 30,
                cx + 30,
                cy + 30,
                outline=ui_theme.with_alpha(self.accent, alpha),
                width=6,
            )
            glows.append(item)
        self._reactor["glows"] = glows

        self._reactor["core"] = self.canvas.create_oval(
            cx - 26,
            cy - 26,
            cx + 26,
            cy + 26,
            outline=self.accent,
            width=2,
        )
        self._reactor["core_fill"] = self.canvas.create_oval(
            cx - 13,
            cy - 13,
            cx + 13,
            cy + 13,
            fill=ui_theme.with_alpha(self.accent, 0.75),
            outline="",
        )
        self._reactor["marker"] = self.canvas.create_oval(
            cx - 3,
            cy - 3,
            cx + 3,
            cy + 3,
            fill=self.accent,
            outline="",
        )

        self._particles = []
        for index in range(7):
            item = self.canvas.create_oval(
                cx - 2,
                cy - 2,
                cx + 2,
                cy + 2,
                fill=ui_theme.VIOLET if index % 2 else self.accent,
                outline="",
            )
            self._particles.append(
                (
                    index * (math.pi * 2 / 7),
                    150 - index * 9,
                    0.35 + index * 0.06,
                    1.6 + (index % 3) * 0.5,
                    item,
                )
            )

        self._reactor["wave_base"] = self.canvas.create_line(
            0,
            0,
            0,
            0,
            fill=ui_theme.BORDER,
            width=1,
        )
        self._waves = []
        for _ in range(21):
            item = self.canvas.create_oval(
                0,
                0,
                0,
                0,
                fill=ui_theme.with_alpha(self.accent, 0.8),
                outline="",
            )
            self._waves.append(item)

    def _style_scrollbar(self, bar):
        try:
            bar.configure(
                bg=ui_theme.CARD,
                troughcolor=ui_theme.PANEL,
                activebackground=ui_theme.ACCENT_DARK,
                highlightbackground=ui_theme.BG,
                relief="flat",
                borderwidth=0,
                width=10,
            )
        except tk.TclError:
            pass

    def _read_config_safe(self):
        return config_module.read_config_file()

    def _code_settings(self):
        config = self._read_config_safe()
        code = config.get("code", {})
        llm = config.get("llm", {})
        if not isinstance(code, dict):
            code = {}
        if not isinstance(llm, dict):
            llm = {}
        return {
            "project": str(code.get("project") or BASE_DIR),
            "provider": str(llm.get("provider") or "deepseek"),
            "model": str(
                llm.get("model")
                or config.get("deepseek_model")
                or "deepseek-chat"
            ),
            "backend": str(code.get("backend") or "deepseek"),
        }

    def _draw_content_header(self):
        header = tk.Frame(self.content, bg=self.bg)
        header.pack(fill="x", pady=(0, 12))

        left = tk.Frame(header, bg=self.bg)
        left.pack(side="left", fill="x", expand=True)

        tk.Label(
            left,
            text="COMMAND CENTER",
            bg=self.bg,
            fg=self.text_color,
            font=("Segoe UI", 16, "bold"),
            anchor="w",
        ).pack(anchor="w")

        tk.Label(
            left,
            text="J.A.R.V.I.S. // CODING & AUTOMATION WORKSPACE",
            bg=self.bg,
            fg=self.muted,
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        right = tk.Frame(header, bg=self.bg)
        right.pack(side="right")

        code = self._code_settings()
        tk.Label(
            right,
            text=f" {code['provider'].upper()} · {code['model']} ",
            bg=ui_theme.CARD,
            fg=ui_theme.VIOLET,
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=6,
        ).pack(side="left", padx=(0, 8))

        self.header_status = tk.Label(
            right,
            text=" STARTING ",
            bg=ui_theme.CARD,
            fg=self.accent,
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=6,
        )
        self.header_status.pack(side="left")

    def _draw_telemetry(self):
        frame = tk.Frame(
            self.sidebar,
            bg=self.bg,
            padx=28,
            pady=4,
        )
        frame.pack(fill="x")

        self.cpu_var = tk.StringVar(value="CPU  —")
        self.ram_var = tk.StringVar(value="RAM  —")
        self.disk_var = tk.StringVar(value="DISK —")
        self.battery_var = tk.StringVar(value="BAT  —")
        self.uptime_var = tk.StringVar(value="UPTIME —")

        rows = (
            (self.cpu_var, self.ram_var),
            (self.disk_var, self.battery_var),
        )

        for row_index, row in enumerate(rows):
            for column_index, variable in enumerate(row):
                tk.Label(
                    frame,
                    textvariable=variable,
                    bg=self.bg,
                    fg=self.muted,
                    anchor="w",
                    font=("Segoe UI", 8),
                ).grid(
                    row=row_index,
                    column=column_index,
                    sticky="w",
                    padx=(0, 22),
                    pady=2,
                )

        tk.Label(
            frame,
            textvariable=self.uptime_var,
            bg=self.bg,
            fg=ui_theme.DIM,
            anchor="w",
            font=("Segoe UI", 8),
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))

        mic_frame = tk.Frame(self.sidebar, bg=self.bg, padx=28, pady=6)
        mic_frame.pack(fill="x")

        tk.Label(
            mic_frame,
            text="MIC",
            bg=self.bg,
            fg=self.muted,
            anchor="w",
            font=("Segoe UI", 8),
        ).pack(side="left")

        self.mic_canvas = tk.Canvas(
            mic_frame,
            width=246,
            height=12,
            bg=ui_theme.PANEL,
            highlightthickness=0,
        )
        self.mic_canvas.pack(side="left", fill="x", expand=True, padx=(10, 0))
        self._draw_mic_bar()

        code = self._code_settings()
        core = tk.Frame(self.sidebar, bg=self.bg, padx=28, pady=10)
        core.pack(fill="x", pady=(14, 0))

        tk.Label(
            core,
            text="CORE SYSTEMS",
            bg=self.bg,
            fg=self.accent,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        for label, value, color in (
            ("LLM", f"{code['provider']} / {code['model']}", ui_theme.VIOLET),
            ("CODE", "agent ready", ui_theme.SUCCESS),
            ("TOOLS", "400+ tools", ui_theme.ACCENT_SOFT),
            ("MEMORY", "active", ui_theme.SUCCESS),
        ):
            row = tk.Frame(core, bg=ui_theme.CARD, padx=10, pady=6)
            row.pack(fill="x", pady=(0, 4))
            tk.Label(
                row,
                text=label,
                bg=ui_theme.CARD,
                fg=self.muted,
                font=("Segoe UI", 7, "bold"),
            ).pack(side="left")
            tk.Label(
                row,
                text=value,
                bg=ui_theme.CARD,
                fg=color,
                font=("Segoe UI", 8),
                anchor="e",
                justify="right",
                wraplength=200,
            ).pack(side="right")

        tk.Label(
            self.sidebar,
            text="Обращение не требуется — просто говорите команду.",
            bg=self.bg,
            fg=ui_theme.DIM,
            font=("Segoe UI", 8),
        ).pack(side="bottom", pady=12)

    def _build_mic_bar(self):
        width = max(1, self.mic_canvas.winfo_width() or 246)
        self.mic_canvas.delete("mic")
        count = 30
        gap = 2
        seg_width = max(1.0, (width - gap * (count - 1)) / count)
        segments = []
        for index in range(count):
            x0 = index * (seg_width + gap)
            item = self.mic_canvas.create_rectangle(
                x0,
                0,
                x0 + seg_width,
                12,
                fill=ui_theme.mix(ui_theme.PANEL, self.accent, 0.12),
                outline="",
                tags="mic",
            )
            segments.append(item)
        peak_x = int(width * 0.62)
        peak = self.mic_canvas.create_rectangle(
            peak_x,
            0,
            peak_x + 2,
            12,
            fill=ui_theme.with_alpha(self.accent, 0.9),
            outline="",
            tags="mic",
        )
        self._mic_items = {
            "segments": segments,
            "peak": peak,
            "count": count,
        }

    def _draw_mic_bar(self):
        if not self._mic_items:
            self._build_mic_bar()
        segments = self._mic_items.get("segments", [])
        if not segments:
            return
        cap = 0.03
        fraction = max(0.0, min(1.0, self.mic_level / cap))
        count = len(segments)
        lit = int(round(fraction * count))
        for index, item in enumerate(segments):
            if index < lit:
                if index < count * 0.55:
                    color = ui_theme.SUCCESS
                elif index < count * 0.8:
                    color = ui_theme.ACCENT
                else:
                    color = ui_theme.WARNING
            else:
                color = ui_theme.mix(ui_theme.PANEL, self.accent, 0.12)
            self.mic_canvas.itemconfig(item, fill=color)

    def _set_mic_level(self, level):
        self.mic_target = max(0.0, float(level))

    def mic_meter_loop(self):
        while self.running:
            level = 0.0
            listener = get_listener()
            if listener is not None and get_status() in {
                "listening",
                "ready",
            }:
                try:
                    level = listener.measure_level(0.15)
                except Exception:
                    level = 0.0
            try:
                self.root.after(0, self._set_mic_level, level)
            except tk.TclError:
                return
            time.sleep(0.3)

    def _draw_chat_and_commands(self):
        self.notebook = ttk.Notebook(
            self.content,
            style="Jarvis.TNotebook",
        )
        self.notebook.pack(fill="both", expand=True)

        self.chat_page = tk.Frame(self.notebook, bg=self.bg)
        self.code_page = tk.Frame(self.notebook, bg=self.bg)
        self.tasks_page = tk.Frame(self.notebook, bg=self.bg)
        self.commands_page = tk.Frame(self.notebook, bg=self.bg)
        self.journal_page = tk.Frame(self.notebook, bg=self.bg)
        self.settings_page = tk.Frame(self.notebook, bg=self.bg)
        self.notebook.add(self.chat_page, text="ЧАТ")
        self.notebook.add(self.code_page, text="АГЕНТ")
        self.notebook.add(self.tasks_page, text="ЗАДАЧИ")
        self.notebook.add(self.commands_page, text="КОМАНДЫ")
        self.notebook.add(self.journal_page, text="ЖУРНАЛ")
        self.notebook.add(self.settings_page, text="НАСТРОЙКИ")

        self.chat_history = scrolledtext.ScrolledText(
            self.chat_page,
            wrap="word",
            state="disabled",
            bg=ui_theme.PANEL,
            fg=self.text_color,
            insertbackground=self.accent,
            selectbackground=ui_theme.ACCENT_DARK,
            relief="flat",
            padx=16,
            pady=14,
            font=("Segoe UI", 12),
            spacing1=2,
            spacing3=6,
        )
        self._style_scrollbar(self.chat_history.vbar)

        self.chat_history.tag_configure(
            "user",
            foreground=self.accent,
            font=("Segoe UI", 10, "bold"),
            spacing1=12,
        )
        self.chat_history.tag_configure(
            "assistant",
            foreground="#bae6fd",
            font=("Segoe UI", 10, "bold"),
            spacing1=12,
        )
        self.chat_history.tag_configure(
            "error",
            foreground=ui_theme.ERROR,
            font=("Segoe UI", 10, "bold"),
            spacing1=12,
        )
        self.chat_history.tag_configure(
            "system",
            foreground=ui_theme.SUCCESS,
            font=("Segoe UI", 9),
        )
        self.chat_history.tag_configure(
            "message_user",
            foreground="#dff8ff",
            background=ui_theme.USER_BG,
            font=("Segoe UI", 11),
            lmargin1=14,
            lmargin2=14,
            rmargin=14,
            spacing3=8,
        )
        self.chat_history.tag_configure(
            "message_assistant",
            foreground=ui_theme.TEXT,
            background=ui_theme.ASSISTANT_BG,
            font=("Segoe UI", 11),
            lmargin1=14,
            lmargin2=14,
            rmargin=14,
            spacing3=8,
        )
        self.chat_history.tag_configure(
            "message_error",
            foreground="#fecaca",
            background=ui_theme.ERROR_BG,
            font=("Segoe UI", 11),
            lmargin1=14,
            lmargin2=14,
            rmargin=14,
            spacing3=8,
        )
        self._append_chat_message(
            "assistant",
            "Все системы в норме, сэр. Пиши задачу словами в поле внизу "
            "или говори голосом — режим подскажу рядом.",
        )

        mode_frame = tk.Frame(self.chat_page, bg=self.bg)

        self.mode_labels = {
            "Просто чат": "chat",
            "Простые задачи": "tasks",
            "Код": "code",
        }
        self.mode_descriptions = {
            "chat": "Разговор без действий на компьютере.",
            "tasks": "Обычный режим: команды, приложения, окна.",
            "code": "DeepSeek-агент: читает код, правит файлы и тестирует.",
        }

        self.mode_var = tk.StringVar(value="Простые задачи")

        tk.Label(
            mode_frame,
            text="РЕЖИМ:",
            bg=self.bg,
            fg=self.accent,
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")

        self.mode_combo = ttk.Combobox(
            mode_frame,
            textvariable=self.mode_var,
            values=tuple(self.mode_labels),
            state="readonly",
            width=16,
        )
        self.mode_combo.pack(side="left", padx=(10, 12))
        self.mode_combo.bind("<<ComboboxSelected>>", self.chat_mode_changed)

        self.mode_hint = tk.Label(
            mode_frame,
            text=self.mode_descriptions["tasks"],
            bg=self.bg,
            fg=self.muted,
            font=("Segoe UI", 8),
        )
        self.mode_hint.pack(side="left")

        self.mode_chip = tk.Label(
            mode_frame,
            text=" TASKS ",
            bg=ui_theme.ACCENT_DARK,
            fg="white",
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=4,
        )
        self.mode_chip.pack(side="right")

        quick = tk.Frame(self.chat_page, bg=self.bg)

        self.var_preview = tk.BooleanVar(
            value=transcript_preview_enabled()
        )

        for text, prompt in (
            ("VS CODE", (
                "Открой PythonProject9 в VS Code и проверь проект "
                "на ошибки"
            )),
            ("АГЕНТ КОДА", (
                "Проверь код проекта PythonProject9, исправь "
                "найденные ошибки и запусти тесты"
            )),
            ("ЧТО ТЫ УМЕЕШЬ", "Что ты умеешь? Перечисли коротко."),
            ("ЭКРАН", "Сделай скриншот и опиши, что на экране."),
        ):
            tk.Button(
                quick,
                text=text,
                command=lambda prompt=prompt: self.quick_action(prompt),
                bg=ui_theme.PANEL_ALT,
                fg=self.text_color,
                activebackground=ui_theme.ACCENT_DARK,
                activeforeground="white",
                relief="flat",
                padx=10,
                pady=4,
                font=("Segoe UI", 8, "bold"),
            ).pack(side="left", padx=(0, 8))

        ttk.Checkbutton(
            quick,
            text="Показывать команду",
            variable=self.var_preview,
            command=self.preview_toggled,
        ).pack(side="right")

        composer = tk.Frame(self.chat_page, bg=self.bg)

        self.chat_input = tk.Text(
            composer,
            height=3,
            width=10,
            wrap="word",
            bg=ui_theme.PANEL_ALT,
            fg=self.text_color,
            insertbackground=self.accent,
            relief="flat",
            font=("Segoe UI", 14),
            highlightthickness=2,
            highlightbackground=ui_theme.BORDER,
            highlightcolor=self.accent,
            padx=14,
            pady=12,
        )
        self.chat_input.bind("<Return>", self.send_chat_message)
        self.chat_input.bind(
            "<Shift-Return>",
            lambda event: None,
        )

        self._chat_placeholder_text = (
            "Напиши задачу словами и нажми Enter — режим выбирай рядом."
        )
        self._chat_placeholder_active = True
        self.chat_input.insert("1.0", self._chat_placeholder_text)
        self.chat_input.configure(fg=self.muted)
        self.chat_input.bind("<FocusIn>", self._chat_focus_in)
        self.chat_input.bind("<FocusOut>", self._chat_focus_out)

        buttons = tk.Frame(composer, bg=self.bg)
        buttons.pack(side="right", fill="y")

        self.send_button = tk.Button(
            buttons,
            text="ОТПРАВИТЬ",
            command=self.send_chat_message,
            bg=ui_theme.ACCENT_DARK,
            fg="white",
            activebackground=self.accent,
            activeforeground=ui_theme.BG,
            relief="flat",
            padx=18,
            pady=10,
            font=("Segoe UI", 11, "bold"),
        )
        self.send_button.pack(fill="x")

        self.stop_button = tk.Button(
            buttons,
            text="СТОП",
            command=self.stop_from_ui,
            bg=ui_theme.ERROR,
            fg="white",
            activebackground="#7f1d1d",
            activeforeground="white",
            relief="flat",
            padx=14,
            pady=10,
            font=("Segoe UI", 11, "bold"),
        )
        self.stop_button.pack(fill="x", pady=(6, 0))
        self.chat_input.pack(
            side="left",
            fill="both",
            expand=True,
            padx=(0, 10),
        )

        composer.pack(side="bottom", fill="x", pady=(10, 0))
        quick.pack(side="bottom", fill="x", pady=(12, 6))
        mode_frame.pack(side="bottom", fill="x", pady=(0, 6))
        self.chat_history.pack(fill="both", expand=True)

        command_header = tk.Label(
            self.commands_page,
            text=(
                "Доступные функции JARVIS. "
                "Дважды нажмите на команду, чтобы вставить её в чат."
            ),
            bg=self.bg,
            fg=self.muted,
            anchor="w",
            font=("Segoe UI", 9),
        )
        command_header.pack(fill="x", pady=(4, 10))

        table_frame = tk.Frame(self.commands_page, bg=self.bg)
        table_frame.pack(fill="both", expand=True)

        self.commands_tree = ttk.Treeview(
            table_frame,
            columns=("command", "description"),
            show="headings",
            style="Jarvis.Treeview",
        )
        self.commands_tree.heading("command", text="КОМАНДА")
        self.commands_tree.heading("description", text="ОПИСАНИЕ")
        self.commands_tree.column(
            "command",
            width=200,
            minwidth=130,
            stretch=False,
        )
        self.commands_tree.column(
            "description",
            width=520,
            minwidth=260,
            stretch=True,
        )

        command_scroll = tk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self.commands_tree.yview,
        )
        self._style_scrollbar(command_scroll)
        self.commands_tree.configure(
            yscrollcommand=command_scroll.set,
        )
        self.commands_tree.pack(
            side="left",
            fill="both",
            expand=True,
        )
        command_scroll.pack(side="right", fill="y")
        self.commands_tree.bind(
            "<Double-1>",
            self.insert_selected_command,
        )

        self._draw_code_page()
        self._draw_tasks_page()
        self._draw_journal_page()
        self._draw_settings_page()

    def _draw_code_page(self):
        code = self._code_settings()

        hero = tk.Frame(
            self.code_page,
            bg=ui_theme.CARD,
            padx=18,
            pady=16,
        )
        hero.pack(fill="x", pady=(4, 12))

        tk.Label(
            hero,
            text="DEEPSEEK CODING AGENT",
            bg=ui_theme.CARD,
            fg=ui_theme.VIOLET,
            font=("Segoe UI", 13, "bold"),
            anchor="w",
        ).pack(anchor="w")

        tk.Label(
            hero,
            text=(
                "Автономный агент: читает проект, правит файлы, "
                "запускает тесты, линт и git-команды."
            ),
            bg=ui_theme.CARD,
            fg=self.text_color,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(anchor="w", pady=(4, 10))

        info = tk.Frame(hero, bg=ui_theme.CARD)
        info.pack(fill="x")
        for label, value in (
            ("PROJECT", code["project"]),
            ("MODEL", f"{code['provider']} / {code['model']}"),
            ("BACKEND", code["backend"]),
        ):
            card = tk.Frame(info, bg=ui_theme.CARD_ALT, padx=12, pady=8)
            card.pack(side="left", fill="x", expand=True, padx=(0, 8))
            tk.Label(
                card,
                text=label,
                bg=ui_theme.CARD_ALT,
                fg=self.muted,
                font=("Segoe UI", 7, "bold"),
                anchor="w",
            ).pack(anchor="w")
            tk.Label(
                card,
                text=value,
                bg=ui_theme.CARD_ALT,
                fg=self.text_color,
                font=("Segoe UI", 9, "bold"),
                anchor="w",
                wraplength=360,
                justify="left",
            ).pack(anchor="w")

        actions = tk.Frame(self.code_page, bg=self.bg)
        actions.pack(fill="x", pady=(0, 12))

        def make_button(text, command, accent=False):
            return tk.Button(
                actions,
                text=text,
                command=command,
                bg=ui_theme.VIOLET_DARK if accent else ui_theme.PANEL_ALT,
                fg="white" if accent else self.text_color,
                activebackground=ui_theme.VIOLET,
                activeforeground="white",
                relief="flat",
                padx=14,
                pady=8,
                font=("Segoe UI", 8, "bold"),
            )

        for text, prompt in (
            (
                "ПРОВЕРИТЬ ПРОЕКТ",
                "Проверь проект на ошибки, запусти тесты и линт. "
                "Сам исправь найденные проблемы и повтори проверку.",
            ),
            (
                "ТЕСТЫ",
                "Запусти тесты проекта через code_test и покажи итог.",
            ),
            (
                "ЛИНТ",
                "Запусти code_lint для проекта и исправь замечания.",
            ),
            (
                "КАРТА ПРОЕКТА",
                "Покажи дерево проекта через code_tree и кратко "
                "объясни структуру.",
            ),
            (
                "GIT",
                "Покажи code_git_summary: ветку, статус и последние "
                "коммиты.",
            ),
        ):
            make_button(
                text,
                lambda value=prompt: self.code_action(value),
                accent=(text == "ПРОВЕРИТЬ ПРОЕКТ"),
            ).pack(side="left", padx=(0, 8))

        make_button(
            "ОТКРЫТЬ ПАПКУ",
            self.open_code_project,
        ).pack(side="left", padx=(0, 8))

        tools_header = tk.Frame(self.code_page, bg=self.bg)
        tools_header.pack(fill="x", pady=(4, 6))
        tk.Label(
            tools_header,
            text="ИНСТРУМЕНТЫ АГЕНТА",
            bg=self.bg,
            fg=self.accent,
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")
        self.code_tool_count = tk.Label(
            tools_header,
            text="0",
            bg=ui_theme.CARD,
            fg=self.muted,
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=2,
        )
        self.code_tool_count.pack(side="right")

        table = tk.Frame(self.code_page, bg=self.bg)
        table.pack(fill="both", expand=True)

        self.code_tools_tree = ttk.Treeview(
            table,
            columns=("tool", "description"),
            show="headings",
            style="Jarvis.Treeview",
        )
        self.code_tools_tree.heading("tool", text="ИНСТРУМЕНТ")
        self.code_tools_tree.heading("description", text="НАЗНАЧЕНИЕ")
        self.code_tools_tree.column("tool", width=240, stretch=False)
        self.code_tools_tree.column(
            "description",
            width=640,
            stretch=True,
        )
        scroll = tk.Scrollbar(
            table,
            orient="vertical",
            command=self.code_tools_tree.yview,
        )
        self._style_scrollbar(scroll)
        self.code_tools_tree.configure(yscrollcommand=scroll.set)
        self.code_tools_tree.pack(
            side="left",
            fill="both",
            expand=True,
        )
        scroll.pack(side="right", fill="y")

        tk.Label(
            self.code_page,
            text=(
                "Агент работает в выбранной папке проекта. "
                "Необратимые команды требуют подтверждения."
            ),
            bg=self.bg,
            fg=ui_theme.DIM,
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(fill="x", pady=(8, 0))

    def code_action(self, prompt):
        self.mode_var.set("Код")
        set_chat_mode("code")
        self.chat_mode_changed()
        self.notebook.select(self.chat_page)
        self.quick_action(prompt)

    def open_code_project(self):
        code = self._code_settings()
        try:
            os.startfile(code["project"])
        except Exception as error:
            self._append_journal(
                f"Не удалось открыть проект: {error}"
            )

    def update_code_tools(self, catalog):
        tree = getattr(self, "code_tools_tree", None)
        if tree is None:
            return
        try:
            tree.delete(*tree.get_children())
        except tk.TclError:
            return
        count = 0
        names = []
        for tool in catalog:
            function = tool.get("function", {})
            name = str(function.get("name", ""))
            if not (
                name.startswith("code_")
                or name in {
                    "run_powershell",
                    "run_python",
                    "run_cmd",
                    "list_capabilities",
                    "describe_capability",
                    "run_capability",
                    "undo_last",
                }
            ):
                continue
            names.append(name)
            tree.insert(
                "",
                "end",
                values=(name, function.get("description", "")),
            )
            count += 1
        if hasattr(self, "code_tool_count"):
            self.code_tool_count.configure(text=str(count))

    def quick_action(self, prompt):
        self._chat_focus_in(None)
        self.chat_input.delete("1.0", "end")
        self.chat_input.insert("1.0", prompt)
        self.send_chat_message()

    def chat_mode_changed(self, event=None):
        del event
        label = self.mode_var.get()
        mode = self.mode_labels.get(label, "tasks")
        set_chat_mode(mode)
        self.mode_hint.configure(
            text=self.mode_descriptions.get(mode, ""),
        )
        chip = getattr(self, "mode_chip", None)
        if chip is not None:
            chip.configure(
                text=f" {mode.upper()} ",
                bg=(
                    ui_theme.VIOLET_DARK
                    if mode == "code"
                    else ui_theme.ACCENT_DARK
                    if mode == "tasks"
                    else ui_theme.CARD_ALT
                ),
                fg=(
                    "white"
                    if mode in {"code", "tasks"}
                    else ui_theme.SUCCESS
                ),
            )
        self._append_system_log(
            f"Режим чата: {label}. "
            f"{self.mode_descriptions.get(mode, '')}"
        )

    def preview_toggled(self):
        set_transcript_preview(self.var_preview.get())
        self._append_system_log(
            "Команды будут показываться перед отправкой."
            if self.var_preview.get()
            else "Команды будут отправляться сразу после распознавания."
        )

    def _draw_tasks_page(self):
        toolbar = tk.Frame(self.tasks_page, bg=self.bg)
        toolbar.pack(fill="x", pady=(4, 8))

        for text, command in (
            ("ОБНОВИТЬ", self.update_tasks),
            ("ОТМЕНИТЬ ЗАДАЧУ", self.cancel_selected_task),
        ):
            tk.Button(
                toolbar,
                text=text,
                command=command,
                bg=ui_theme.PANEL_ALT,
                fg=self.text_color,
                activebackground=ui_theme.ACCENT_DARK,
                activeforeground="white",
                relief="flat",
                padx=12,
                pady=6,
                font=("Segoe UI", 8, "bold"),
            ).pack(side="left", padx=(0, 8))

        self.tasks_tree = ttk.Treeview(
            self.tasks_page,
            columns=("task", "status", "title", "result"),
            show="headings",
            style="Jarvis.Treeview",
        )
        self.tasks_tree.heading("task", text="ID")
        self.tasks_tree.heading("status", text="СТАТУС")
        self.tasks_tree.heading("title", text="ЗАДАЧА")
        self.tasks_tree.heading("result", text="РЕЗУЛЬТАТ")
        self.tasks_tree.column("task", width=90, stretch=False)
        self.tasks_tree.column("status", width=110, stretch=False)
        self.tasks_tree.column("title", width=340, stretch=True)
        self.tasks_tree.column("result", width=320, stretch=True)
        self.tasks_tree.pack(fill="both", expand=True)

    def update_tasks(self):
        if not self.running:
            return
        tasks = get_task_snapshot()
        try:
            self.tasks_tree.delete(*self.tasks_tree.get_children())
        except tk.TclError:
            return
        for task in tasks:
            task_id = task.get("id", "")
            self.tasks_tree.insert(
                "",
                "end",
                iid=str(task_id),
                values=(
                    task_id,
                    task.get("status", ""),
                    task.get("title", ""),
                    str(task.get("result") or task.get("error") or "")[:160],
                ),
            )
        self.root.after(self.TASKS_MS, self.update_tasks)

    def cancel_selected_task(self):
        selected = self.tasks_tree.selection()
        if not selected:
            return
        try:
            task_id = int(selected[0])
        except ValueError:
            return
        if cancel_task(task_id):
            self._append_journal(f"Задача {task_id} отменена.")
        else:
            self._append_journal(
                f"Задачу {task_id} не удалось отменить."
            )

    def _draw_journal_page(self):
        toolbar = tk.Frame(self.journal_page, bg=self.bg)
        toolbar.pack(fill="x", pady=(4, 8))

        for text, command in (
            ("ОБНОВИТЬ", self.refresh_journal),
            ("АУДИТ", self.show_audit),
            ("ДИАГНОСТИКА", self.run_doctor_async),
            ("ОЧИСТИТЬ", self.clear_journal_view),
        ):
            tk.Button(
                toolbar,
                text=text,
                command=command,
                bg=ui_theme.PANEL_ALT,
                fg=self.text_color,
                activebackground=ui_theme.ACCENT_DARK,
                activeforeground="white",
                relief="flat",
                padx=12,
                pady=6,
                font=("Segoe UI", 8, "bold"),
            ).pack(side="left", padx=(0, 8))

        self.journal_text = scrolledtext.ScrolledText(
            self.journal_page,
            wrap="word",
            state="disabled",
            bg=ui_theme.PANEL,
            fg=self.text_color,
            insertbackground=self.accent,
            relief="flat",
            padx=14,
            pady=12,
            font=("Segoe UI", 9),
        )
        self._style_scrollbar(self.journal_text.vbar)
        self.journal_text.pack(fill="both", expand=True)
        self.refresh_journal()

    def _draw_settings_page(self):
        form = tk.Frame(self.settings_page, bg=self.bg, padx=8, pady=8)
        form.pack(fill="both", expand=True)

        self.var_autonomy = tk.StringVar(value="full")
        self.var_confirm = tk.BooleanVar(value=False)
        self.var_dry_run = tk.BooleanVar(value=False)
        self.var_taint = tk.BooleanVar(value=True)
        self.var_preview_cfg = tk.BooleanVar(value=False)
        self.var_cat_planning = tk.BooleanVar(value=True)
        self.var_max_tools = tk.StringVar(value="100")
        self.var_code_tools = tk.StringVar(value="28")
        self.var_max_iterations = tk.StringVar(value="12")
        self.var_max_tokens = tk.StringVar(value="3000")
        self.var_tool_timeout = tk.StringVar(value="120")
        self.var_noise_k = tk.StringVar(value="3.0")
        self.var_max_speech = tk.StringVar(value="12.0")
        self.var_silence = tk.StringVar(value="0.7")

        tk.Label(
            form,
            text="Автономность",
            bg=self.bg,
            fg=self.accent,
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(
            form,
            textvariable=self.var_autonomy,
            values=("safe", "balanced", "full"),
            state="readonly",
            width=18,
        ).grid(row=0, column=1, sticky="w", pady=4, padx=(12, 0))

        ttk.Checkbutton(
            form,
            text="Подтверждать опасные действия",
            variable=self.var_confirm,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Checkbutton(
            form,
            text="Dry-run для опасных действий",
            variable=self.var_dry_run,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Checkbutton(
            form,
            text="Учитывать недоверенный контент (prompt injection)",
            variable=self.var_taint,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Checkbutton(
            form,
            text="Показывать голосовую команду перед отправкой",
            variable=self.var_preview_cfg,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Checkbutton(
            form,
            text="Предварительный выбор категорий (planner)",
            variable=self.var_cat_planning,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=4)

        fields = (
            ("max_tools_per_request", self.var_max_tools),
            ("code_tools_per_request", self.var_code_tools),
            ("max_iterations", self.var_max_iterations),
            ("max_tokens", self.var_max_tokens),
            ("tool_timeout_seconds", self.var_tool_timeout),
            ("stt_noise_adapt_k", self.var_noise_k),
            ("max_speech_seconds", self.var_max_speech),
            ("silence_duration", self.var_silence),
        )
        for index, (label, variable) in enumerate(fields, start=6):
            tk.Label(
                form,
                text=label,
                bg=self.bg,
                fg=self.muted,
                font=("Segoe UI", 9),
            ).grid(row=index, column=0, sticky="w", pady=4)
            tk.Entry(
                form,
                textvariable=variable,
                bg=ui_theme.PANEL_ALT,
                fg=self.text_color,
                insertbackground=self.accent,
                relief="flat",
                width=12,
                font=("Segoe UI", 9),
            ).grid(row=index, column=1, sticky="w", pady=4, padx=(12, 0))

        actions = tk.Frame(form, bg=self.bg)
        actions.grid(
            row=14,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(16, 4),
        )
        for text, command in (
            ("СОХРАНИТЬ", self.save_settings),
            ("ОТКРЫТЬ CONFIG", self.open_config),
            ("ОТКРЫТЬ АУДИТ", self.open_audit_file),
        ):
            tk.Button(
                actions,
                text=text,
                command=command,
                bg=ui_theme.ACCENT_DARK,
                fg="white",
                activebackground=self.accent,
                activeforeground=ui_theme.BG,
                relief="flat",
                padx=14,
                pady=7,
                font=("Segoe UI", 8, "bold"),
            ).pack(side="left", padx=(0, 8))

        tk.Label(
            form,
            text="Изменения применяются после перезапуска JARVIS.",
            bg=self.bg,
            fg=ui_theme.DIM,
            font=("Segoe UI", 8),
        ).grid(row=15, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.load_settings()

    def _append_journal(self, text):
        stamp = time.strftime("%H:%M:%S")
        self.journal_text.configure(state="normal")
        self.journal_text.insert("end", f"[{stamp}] {text}\n")
        self.journal_text.configure(state="disabled")
        self.journal_text.see("end")

    def refresh_journal(self):
        self.journal_text.configure(state="normal")
        self.journal_text.delete("1.0", "end")
        self.journal_text.insert("end", tracer().tail(300))
        self.journal_text.configure(state="disabled")
        self.journal_text.see("end")

    def show_audit(self):
        path = DATA_DIR / "audit.log"
        if not path.exists():
            self._append_journal("Журнал аудита пуст.")
            return
        lines = path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
        self._append_journal("\n".join(lines[-200:]))

    def clear_journal_view(self):
        self.journal_text.configure(state="normal")
        self.journal_text.delete("1.0", "end")
        self.journal_text.configure(state="disabled")

    def run_doctor_async(self):
        self._append_journal("Запуск диагностики…")

        def worker():
            text = format_report(run_checks())
            self.root.after(0, lambda: self._append_journal(text))

        threading.Thread(target=worker, daemon=True).start()

    def load_settings(self):
        config = config_module.read_config_file()
        if not config:
            self._append_journal("Не удалось прочитать config.")
            return
        agent = config.get("agent", {})
        safety = config.get("safety", {})
        if not isinstance(agent, dict):
            agent = {}
        if not isinstance(safety, dict):
            safety = {}
        self.var_autonomy.set(
            str(agent.get("autonomy", "full"))
        )
        self.var_confirm.set(bool(safety.get("confirm_destructive", False)))
        self.var_dry_run.set(bool(safety.get("dry_run", False)))
        self.var_taint.set(bool(safety.get("taint_tracking", True)))
        self.var_preview_cfg.set(
            bool(config.get("transcript_preview", False))
        )
        self.var_cat_planning.set(
            bool(agent.get("category_planning", True))
        )
        self.var_max_tools.set(
            str(agent.get("max_tools_per_request", 100))
        )
        self.var_code_tools.set(
            str(agent.get("code_tools_per_request", 28))
        )
        self.var_max_iterations.set(
            str(agent.get("max_iterations", 12))
        )
        self.var_max_tokens.set(str(agent.get("max_tokens", 3000)))
        self.var_tool_timeout.set(
            str(agent.get("tool_timeout_seconds", 120))
        )
        self.var_noise_k.set(
            str(config.get("stt_noise_adapt_k", 3.0))
        )
        self.var_max_speech.set(
            str(config.get("max_speech_seconds", 12.0))
        )
        self.var_silence.set(
            str(config.get("silence_duration", 0.7))
        )
        mode = str(config.get("chat_mode", "tasks"))
        labels = {
            key: label
            for label, key in self.mode_labels.items()
        }
        self.mode_var.set(labels.get(mode, "Простые задачи"))
        self.mode_hint.configure(
            text=self.mode_descriptions.get(mode, ""),
        )
        chip = getattr(self, "mode_chip", None)
        if chip is not None:
            chip.configure(
                text=f" {mode.upper()} ",
                bg=(
                    ui_theme.VIOLET_DARK
                    if mode == "code"
                    else ui_theme.ACCENT_DARK
                    if mode == "tasks"
                    else ui_theme.CARD_ALT
                ),
                fg=(
                    "white"
                    if mode in {"code", "tasks"}
                    else ui_theme.SUCCESS
                ),
            )

    def save_settings(self):
        config = config_module.read_config_file()
        if not config:
            messagebox.showerror("JARVIS", "Не удалось прочитать config.")
            return
        agent = config.setdefault("agent", {})
        safety = config.setdefault("safety", {})
        if not isinstance(agent, dict):
            agent = {}
            config["agent"] = agent
        if not isinstance(safety, dict):
            safety = {}
            config["safety"] = safety
        try:
            agent["autonomy"] = self.var_autonomy.get()
            safety["autonomy"] = self.var_autonomy.get()
            safety["confirm_destructive"] = bool(self.var_confirm.get())
            safety["dry_run"] = bool(self.var_dry_run.get())
            safety["taint_tracking"] = bool(self.var_taint.get())
            config["transcript_preview"] = bool(
                self.var_preview_cfg.get()
            )
            agent["category_planning"] = bool(
                self.var_cat_planning.get()
            )
            agent["max_tools_per_request"] = int(self.var_max_tools.get())
            agent["code_tools_per_request"] = int(
                self.var_code_tools.get()
            )
            agent["max_iterations"] = int(self.var_max_iterations.get())
            agent["max_tokens"] = int(self.var_max_tokens.get())
            agent["tool_timeout_seconds"] = int(self.var_tool_timeout.get())
            config["stt_noise_adapt_k"] = float(self.var_noise_k.get())
            config["max_speech_seconds"] = float(self.var_max_speech.get())
            config["silence_duration"] = float(self.var_silence.get())
            config["chat_mode"] = self.mode_labels.get(
                self.mode_var.get(),
                "tasks",
            )
        except ValueError as error:
            messagebox.showerror("JARVIS", f"Некорректное значение: {error}")
            return
        config_module.save_config(config)
        self._append_journal("Настройки сохранены. Перезапустите JARVIS.")
        messagebox.showinfo(
            "JARVIS",
            "Настройки сохранены. Перезапустите JARVIS.",
        )

    def open_config(self):
        try:
            os.startfile(str(CONFIG_FILE))
        except Exception as error:
            self._append_journal(f"Не удалось открыть config: {error}")

    def open_audit_file(self):
        path = DATA_DIR / "audit.log"
        try:
            os.startfile(str(path))
        except Exception as error:
            self._append_journal(f"Не удалось открыть аудит: {error}")

    def stop_from_ui(self):
        stop_assistant()
        self._append_journal("Отправлена команда аварийной остановки.")
        self._append_system_log(
            "Аварийная остановка: инструменты и фоновые задачи остановлены."
        )

    def _start_tray(self):
        try:
            import pystray
            from PIL import Image, ImageDraw
        except Exception:
            return
        try:
            image = Image.new("RGB", (64, 64), ui_theme.BG)
            draw = ImageDraw.Draw(image)
            draw.ellipse((8, 8, 56, 56), outline=ui_theme.ACCENT, width=3)
            draw.ellipse((22, 22, 42, 42), fill=ui_theme.ACCENT)
            menu = pystray.Menu(
                pystray.MenuItem(
                    "Показать",
                    lambda: self.root.after(0, self.root.deiconify),
                ),
                pystray.MenuItem(
                    "Стоп",
                    lambda: self.root.after(0, self.stop_from_ui),
                ),
                pystray.MenuItem(
                    "Выход",
                    lambda: self.root.after(0, self.close),
                ),
            )
            self.tray = pystray.Icon(
                "JARVIS",
                image,
                "JARVIS",
                menu,
            )
            threading.Thread(
                target=self.tray.run,
                name="JARVIS-Tray",
                daemon=True,
            ).start()
        except Exception as error:
            log.info(f"[TRAY] {error}")

    def _boot_sequence(self):
        lines = [
            "J.A.R.V.I.S. MK IX // ЗАГРУЗКА",
            "[OK] Распознавание речи: Groq Whisper / локальная STT",
            "[OK] Языковая модель: DeepSeek",
            "[OK] Синтез речи: Edge TTS",
            "[OK] Управление компьютером: активно",
            "[OK] Долговременная память: активна",
        ]

        def show_line(index):
            if not self.running or index >= len(lines):
                return
            self._append_system_log(lines[index])
            self.root.after(
                140,
                lambda: show_line(index + 1),
            )

        show_line(0)

    def _append_system_log(self, text):
        self.chat_history.configure(state="normal")
        self.chat_history.insert("end", f"{text}\n", "system")
        self.chat_history.configure(state="disabled")
        self.chat_history.see("end")

    def _append_chat_message(self, role, text):
        labels = {
            "user": "ВЫ",
            "assistant": "JARVIS",
            "error": "ОШИБКА",
        }
        body_tags = {
            "user": "message_user",
            "assistant": "message_assistant",
            "error": "message_error",
        }
        normalized = role if role in labels else "assistant"
        stamp = time.strftime("%H:%M")
        self.chat_history.configure(state="normal")
        self.chat_history.insert(
            "end",
            f"  {labels[normalized]}   ·   {stamp}\n",
            normalized,
        )
        self.chat_history.insert(
            "end",
            f"{str(text).strip()}\n\n",
            body_tags[normalized],
        )
        self.chat_history.configure(state="disabled")
        self.chat_history.see("end")

    def send_chat_message(self, event=None):
        if event is not None and int(event.state) & 0x0001:
            return None

        text = self.chat_input.get("1.0", "end-1c").strip()
        if self._chat_placeholder_active or not text:
            return "break"

        jarvis_thread = getattr(self, "jarvis_thread", None)
        if (
            not self.running
            or jarvis_thread is None
            or not jarvis_thread.is_alive()
        ):
            self._append_chat_message(
                "error",
                "JARVIS сейчас не запущен. Дождитесь загрузки "
                "или перезапустите приложение.",
            )
            return "break"

        mode = self.mode_labels.get(self.mode_var.get(), "tasks")
        self.send_button.configure(state="disabled")

        try:
            submitted = submit_chat_message(text, mode=mode)
        except Exception as error:
            log.info(
                f"[LAUNCHER ERROR] submit_chat_message: "
                f"{type(error).__name__}: {error}"
            )
            self.send_button.configure(state="normal")
            self._append_chat_message(
                "error",
                f"Не удалось отправить сообщение: {error}",
            )
            return "break"

        if not submitted:
            self.send_button.configure(state="normal")
            self._append_chat_message(
                "error",
                "Сообщение пустое и не было отправлено.",
            )
            return "break"

        self.chat_input.delete("1.0", "end")
        self.chat_input.focus_set()
        return "break"

    def _chat_focus_in(self, _event=None):
        if self._chat_placeholder_active:
            self._chat_placeholder_active = False
            self.chat_input.delete("1.0", "end")
            self.chat_input.configure(fg=self.text_color)

    def _chat_focus_out(self, _event=None):
        if not self.chat_input.get("1.0", "end-1c").strip():
            self._chat_placeholder_active = True
            self.chat_input.delete("1.0", "end")
            self.chat_input.insert("1.0", self._chat_placeholder_text)
            self.chat_input.configure(fg=self.muted)

    def insert_selected_command(self, _event=None):
        del _event
        selected = self.commands_tree.selection()
        if not selected:
            return

        values = self.commands_tree.item(selected[0], "values")
        if len(values) < 2:
            return

        self.notebook.select(self.chat_page)
        self._chat_focus_in(None)
        self.chat_input.delete("1.0", "end")
        self.chat_input.insert("1.0", f"Помоги выполнить: {values[1]}")
        self.chat_input.focus_set()

    def poll_ui_events(self):
        if not self.running:
            return

        for event_type, payload in drain_ui_events():
            if event_type in {"user", "assistant", "error"}:
                self._append_chat_message(event_type, str(payload))
                if event_type != "user":
                    self.send_button.configure(state="normal")
            elif event_type == "command_catalog":
                self.commands_tree.delete(
                    *self.commands_tree.get_children(),
                )
                for tool in payload:
                    function = tool.get("function", {})
                    self.commands_tree.insert(
                        "",
                        "end",
                        values=(
                            function.get("name", ""),
                            function.get("description", ""),
                        ),
                    )
                self.update_code_tools(payload)
            elif event_type == "transcript_preview":
                self.notebook.select(self.chat_page)
                self._chat_focus_in(None)
                self.chat_input.delete("1.0", "end")
                self.chat_input.insert("1.0", str(payload))
                self.chat_input.focus_set()
                self._append_system_log(
                    "Голос распознан — проверьте текст и нажмите ОТПРАВИТЬ."
                )
            elif event_type == "system":
                self._append_system_log(str(payload))
            elif event_type == "llm_iteration":
                self._append_journal(
                    f"LLM шаг {payload.get('iteration')}/"
                    f"{payload.get('max_iterations')}"
                )
            elif event_type == "llm_tool_call":
                self._append_journal(
                    f"TOOL {payload.get('name')} "
                    f"{payload.get('arguments')}"
                )
            elif event_type == "llm_tool_result":
                self._append_journal(
                    f"RESULT {payload.get('name')} "
                    f"({payload.get('elapsed', 0)} c): "
                    f"{str(payload.get('result', ''))[:500]}"
                )
            elif event_type == "llm_answer":
                self._append_journal(
                    f"ANSWER {str(payload.get('text', ''))[:500]}"
                )

        self.root.after(100, self.poll_ui_events)

    def run_jarvis(self):
        try:
            main()
        except Exception as error:
            log.info(
                f"[LAUNCHER ERROR] "
                f"{type(error).__name__}: {error}"
            )
            traceback.print_exc()
            set_status("error")
        finally:
            try:
                self.root.after(0, self.jarvis_finished)
            except tk.TclError:
                pass

    def jarvis_finished(self):
        if not self.running or self.jarvis_dead:
            return

        self.jarvis_dead = True
        status = get_status()

        if status == "error":
            self._append_chat_message(
                "error",
                "JARVIS не смог запуститься. "
                "Проверьте DEEPSEEK_API_KEY и GROQ_API_KEY в .env, "
                "а также лог в консоли, сэр.",
            )
            try:
                self.canvas.itemconfig(
                    self.status_text,
                    text="ERROR",
                    fill=ui_theme.ERROR,
                )
                self.canvas.itemconfig(
                    self.info_text,
                    text="Проверьте конфигурацию и лог.",
                )
            except tk.TclError:
                pass
            return

        self.running = False
        set_status("stopped")

        log.info("[LAUNCHER] JARVIS завершил работу.")

        try:
            self.canvas.itemconfig(
                self.status_text,
                text="OFFLINE",
                fill=ui_theme.MUTED,
            )
            self.canvas.itemconfig(
                self.info_text,
                text="Система остановлена.",
            )
            self.root.after(1200, self.close_window)
        except tk.TclError:
            pass

    def check_jarvis(self):
        if not self.running or self.jarvis_dead:
            return

        if not self.jarvis_thread.is_alive():
            self.jarvis_finished()
            return

        self.root.after(200, self.check_jarvis)

    def get_status_text(self):
        status = get_status()

        states = {
            "starting": ("STARTING", "Запуск подсистем…"),
            "ready": ("READY", "Ожидаю команду…"),
            "listening": ("LISTENING", "Слушаю команду…"),
            "processing": ("PROCESSING", "Распознаю речь…"),
            "thinking": ("THINKING", "Анализирую запрос…"),
            "speaking": ("SPEAKING", "Говорю…"),
            "error": ("ERROR", "Требуется внимание."),
            "stopped": ("OFFLINE", "Система остановлена."),
        }

        return states.get(status, ("ONLINE", "Активен."))

    def update_telemetry(self):
        if not self.running:
            return

        data = telemetry.snapshot()

        if data["available"]:
            self.cpu_var.set(f"CPU  {data['cpu']:>3}%")
            self.ram_var.set(f"RAM  {data['memory']:>3}%")
            self.disk_var.set(f"DISK {data['disk']:>3}%")

            battery = data.get("battery")
            if battery:
                suffix = "+" if battery["plugged"] else ""
                self.battery_var.set(
                    f"BAT  {battery['percent']:>3}%{suffix}"
                )
            else:
                self.battery_var.set("BAT  —")

            self.uptime_var.set(f"UPTIME {data['uptime']}")
        else:
            for variable in (
                self.cpu_var,
                self.ram_var,
                self.disk_var,
                self.battery_var,
            ):
                variable.set("—")

            self.uptime_var.set("UPTIME —")

        self.root.after(self.TELEMETRY_MS, self.update_telemetry)

    def animate(self):
        if not self.running:
            return

        try:
            if self.root.state() in {"iconic", "withdrawn"}:
                self.root.after(500, self.animate)
                return
        except tk.TclError:
            return

        status = get_status()
        status_name, status_description = self.get_status_text()
        color = ui_theme.STATUS_COLORS.get(status, self.accent)

        if status != self.current_status:
            self.canvas.itemconfig(
                self.status_text,
                text=status_name,
                fill=color,
            )
            self.canvas.itemconfig(
                self.info_text,
                text=status_description,
            )
            header_status = getattr(self, "header_status", None)
            if header_status is not None:
                try:
                    header_status.configure(
                        text=(
                            f" {status_name} · "
                            f"{status_description} "
                        ),
                        fg=color,
                    )
                except tk.TclError:
                    pass
            self.canvas.itemconfig(
                self._reactor.get("core"),
                outline=color,
            )
            self.canvas.itemconfig(
                self._reactor.get("core_fill"),
                fill=ui_theme.with_alpha(color, 0.75),
            )
            self.canvas.itemconfig(
                self._reactor.get("marker"),
                fill=color,
            )
            self.current_status = status

        speeds = {
            "listening": 0.16,
            "processing": 0.10,
            "thinking": 0.07,
            "speaking": 0.22,
            "error": 0.04,
            "stopped": 0.02,
        }
        amplitudes = {
            "listening": 18,
            "processing": 13,
            "thinking": 10,
            "speaking": 24,
            "error": 4,
            "stopped": 2,
        }

        self.time += speeds.get(status, 0.09)

        center_x = self.center_x
        center_y = self.center_y

        for item, _radius, _extent, direction in self._reactor.get(
            "arcs",
            (),
        ):
            start = (math.degrees(self.time * 42 * direction)) % 360
            self.canvas.itemconfig(item, start=start)

        pulse = 22 + math.sin(self.time * 1.8) * 4
        for item, radius in zip(
            self._reactor.get("glows", ()),
            (pulse + 26, pulse + 16, pulse + 7),
        ):
            self.canvas.coords(
                item,
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius,
            )

        core_radius = 22 + math.sin(self.time * 1.8) * 1.5
        self.canvas.coords(
            self._reactor.get("core"),
            center_x - core_radius,
            center_y - core_radius,
            center_x + core_radius,
            center_y + core_radius,
        )

        marker_angle = self.time * 2.2
        marker_x = center_x + math.cos(marker_angle) * 148
        marker_y = center_y + math.sin(marker_angle) * 148
        self.canvas.coords(
            self._reactor.get("marker"),
            marker_x - 3,
            marker_y - 3,
            marker_x + 3,
            marker_y + 3,
        )

        for angle, radius, speed, size, item in self._particles:
            position = angle + self.time * speed
            x = center_x + math.cos(position) * radius
            y = center_y + math.sin(position) * radius
            self.canvas.coords(
                item,
                x - size,
                y - size,
                x + size,
                y + size,
            )

        points = 21
        spacing = 9
        start_x = center_x - ((points - 1) * spacing) / 2
        base_y = 335
        self.canvas.coords(
            self._reactor.get("wave_base"),
            start_x,
            base_y,
            start_x + (points - 1) * spacing,
            base_y,
        )

        amplitude = amplitudes.get(status, 13)
        if getattr(self, "_wave_color", None) != color:
            for item in self._waves:
                self.canvas.itemconfig(item, fill=color)
            self._wave_color = color

        for index, item in enumerate(self._waves):
            x = start_x + index * spacing
            wave = math.sin(self.time * 2.0 + index * 0.55)
            y = base_y + wave * amplitude * 0.5
            size = 1.5 + ((wave + 1) / 2) * 1.8
            self.canvas.coords(
                item,
                x - size,
                y - size,
                x + size,
                y + size,
            )

        target = min(1.0, self.mic_target / 0.03)
        self.mic_level += (target - self.mic_level) * 0.22
        if abs(target - self.mic_level) < 0.004:
            self.mic_level = target
        try:
            self._draw_mic_bar()
        except tk.TclError:
            return

        self.root.after(self.FPS_MS, self.animate)

    def close_window(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def close(self):
        self.running = False
        stop_assistant()
        set_status("stopped")
        tray = getattr(self, "tray", None)
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                pass

        try:
            self.root.destroy()
        except tk.TclError:
            pass


def _enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _center_window(root):
    root.update_idletasks()
    width = JarvisWindow.WIDTH
    height = JarvisWindow.HEIGHT
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 2 - 24)
    root.geometry(f"{width}x{height}+{x}+{y}")


if __name__ == "__main__":
    _enable_dpi_awareness()
    root = tk.Tk()
    app = JarvisWindow(root)
    _center_window(root)
    root.mainloop()
