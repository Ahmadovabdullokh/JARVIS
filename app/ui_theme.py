"""Палитра и шрифты HUD.

Тёмная «глубокий космос» схема с циановым и фиолетовым акцентами.
Здесь же лежат небольшие цветовые утилиты для мягкого свечения
арк-реактора и анимаций: Tkinter не умеет alpha, поэтому прозрачность
имитируется смешиванием цвета с фоном.
"""

BG = "#03060d"
BG_SOFT = "#060b16"
PANEL = "#0a1220"
PANEL_ALT = "#0e1a2c"
CARD = "#101d31"
CARD_ALT = "#14243c"
BORDER = "#1d3a5c"
BORDER_SOFT = "#12263d"
GRID = "#0b1929"
TEXT = "#e8f1fb"
MUTED = "#7b93ad"
DIM = "#3d5570"
ACCENT = "#2ee6ff"
ACCENT_SOFT = "#8bf3ff"
ACCENT_DARK = "#0e7490"
VIOLET = "#b18cff"
VIOLET_DARK = "#6d28d9"
ERROR = "#ff6b6b"
WARNING = "#ffc857"
SUCCESS = "#3df5a6"
USER_BG = "#0a2536"
ASSISTANT_BG = "#0a1626"
ERROR_BG = "#2a0f14"
GLASS = "#0b1626"

TITLE_FONT = ("Segoe UI", 24, "bold")
SUBTITLE_FONT = ("Segoe UI", 7)
STATUS_FONT = ("Segoe UI", 10, "bold")
INFO_FONT = ("Segoe UI", 8)
BODY_FONT = ("Segoe UI", 10)
SMALL_FONT = ("Segoe UI", 8)
LABEL_FONT = ("Segoe UI", 9, "bold")
MONO_FONT = ("Cascadia Mono", 9)
MONO_SMALL_FONT = ("Cascadia Mono", 8)
CHAT_FONT = ("Segoe UI", 11)
CHAT_TITLE_FONT = ("Segoe UI", 9, "bold")

STATUS_COLORS = {
    "starting": ACCENT_SOFT,
    "ready": SUCCESS,
    "listening": ACCENT,
    "processing": WARNING,
    "thinking": VIOLET,
    "speaking": ACCENT_SOFT,
    "error": ERROR,
    "stopped": MUTED,
}


def _to_rgb(color):
    color = str(color).strip().lstrip("#")
    if len(color) != 6:
        return (0, 0, 0)
    return tuple(int(color[index:index + 2], 16) for index in (0, 2, 4))


def _to_hex(rgb):
    return "#" + "".join(
        f"{max(0, min(255, int(channel))):02x}" for channel in rgb
    )


def mix(color_a, color_b, ratio=0.5):
    """Смешивает два цвета. ratio=0 — color_a, ratio=1 — color_b."""

    ratio = max(0.0, min(1.0, float(ratio)))
    first = _to_rgb(color_a)
    second = _to_rgb(color_b)
    return _to_hex(
        tuple(
            first[index] + (second[index] - first[index]) * ratio
            for index in range(3)
        )
    )


def with_alpha(color, ratio):
    """Имитация прозрачности поверх основного фона."""

    return mix(BG, color, ratio)
