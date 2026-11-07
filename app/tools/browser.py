import time
import urllib.parse
import webbrowser

import pyautogui
import requests

from app.tools.common import optional_import, resolve_path

SEARCH_ENGINES = {
    "google": "https://www.google.com/search?q={}",
    "bing": "https://www.bing.com/search?q={}",
    "yandex": "https://yandex.ru/search/?text={}",
    "duckduckgo": "https://duckduckgo.com/?q={}",
}


def _open(url):
    webbrowser.open(str(url), new=2)
    return f"Открыто в браузере: {url}"


def _hotkey(*keys):
    pyautogui.hotkey(*keys)
    time.sleep(0.2)
    return "Готово: " + "+".join(keys)


def register(registry):

    @registry.tool(
        "browser_open",
        "Открыть URL в браузере по умолчанию.",
        {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        category="browser",
    )
    def browser_open(url):
        url = str(url or "").strip()
        if "://" not in url and not url.startswith("about:"):
            url = "https://" + url
        return _open(url)

    @registry.tool(
        "browser_search",
        "Найти запрос в поисковике.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "engine": {
                    "type": "string",
                    "enum": ["google", "bing", "yandex", "duckduckgo"],
                },
            },
            "required": ["query"],
        },
        category="browser",
    )
    def browser_search(query, engine="google"):
        template = SEARCH_ENGINES.get(engine, SEARCH_ENGINES["google"])
        return _open(template.format(urllib.parse.quote(str(query))))

    @registry.tool(
        "browser_tab",
        "Управление вкладками браузера.",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "new",
                        "close",
                        "next",
                        "previous",
                        "reopen",
                    ],
                }
            },
            "required": ["action"],
        },
        category="browser",
    )
    def browser_tab(action):
        mapping = {
            "new": ("ctrl", "t"),
            "close": ("ctrl", "w"),
            "next": ("ctrl", "tab"),
            "previous": ("ctrl", "shift", "tab"),
            "reopen": ("ctrl", "shift", "t"),
        }
        return _hotkey(*mapping[action])

    @registry.tool(
        "browser_navigate",
        "Навигация в браузере.",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "reload",
                        "back",
                        "forward",
                        "home",
                        "address",
                        "stop",
                    ],
                }
            },
            "required": ["action"],
        },
        category="browser",
    )
    def browser_navigate(action):
        mapping = {
            "reload": ("ctrl", "r"),
            "back": ("alt", "left"),
            "forward": ("alt", "right"),
            "home": ("alt", "home"),
            "address": ("ctrl", "l"),
            "stop": ("esc",),
        }
        return _hotkey(*mapping[action])

    @registry.tool(
        "browser_incognito",
        "Открыть приватное окно браузера.",
        {"type": "object", "properties": {}, "required": []},
        category="browser",
    )
    def browser_incognito():
        return _hotkey("ctrl", "shift", "n")

    @registry.tool(
        "browser_devtools",
        "Открыть инструменты разработчика.",
        {"type": "object", "properties": {}, "required": []},
        category="browser",
    )
    def browser_devtools():
        return _hotkey("f12")

    @registry.tool(
        "browser_fullscreen",
        "Полноэкранный режим браузера.",
        {"type": "object", "properties": {}, "required": []},
        category="browser",
    )
    def browser_fullscreen():
        return _hotkey("f11")

    @registry.tool(
        "browser_zoom",
        "Масштаб страницы в браузере.",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["in", "out", "reset"],
                }
            },
            "required": ["action"],
        },
        category="browser",
    )
    def browser_zoom(action):
        mapping = {
            "in": ("ctrl", "+"),
            "out": ("ctrl", "-"),
            "reset": ("ctrl", "0"),
        }
        return _hotkey(*mapping[action])

    @registry.tool(
        "browser_bookmark",
        "Добавить страницу в закладки.",
        {"type": "object", "properties": {}, "required": []},
        category="browser",
    )
    def browser_bookmark():
        return _hotkey("ctrl", "d")

    @registry.tool(
        "browser_find",
        "Найти текст на странице.",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        category="browser",
    )
    def browser_find(text):
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.2)
        pyautogui.write(str(text), interval=0.02)
        return f"Поиск на странице: {text}"

    @registry.tool(
        "browser_print",
        "Открыть печать страницы.",
        {"type": "object", "properties": {}, "required": []},
        category="browser",
    )
    def browser_print():
        return _hotkey("ctrl", "p")

    @registry.tool(
        "browser_save",
        "Сохранить страницу.",
        {"type": "object", "properties": {}, "required": []},
        category="browser",
    )
    def browser_save():
        return _hotkey("ctrl", "s")

    @registry.tool(
        "browser_downloads",
        "Открыть список загрузок браузера.",
        {"type": "object", "properties": {}, "required": []},
        category="browser",
    )
    def browser_downloads():
        return _hotkey("ctrl", "j")

    @registry.tool(
        "browser_history",
        "Открыть историю браузера.",
        {"type": "object", "properties": {}, "required": []},
        category="browser",
    )
    def browser_history():
        return _hotkey("ctrl", "h")

    @registry.tool(
        "browser_maps",
        "Открыть место на карте.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        category="browser",
    )
    def browser_maps(query):
        return _open(
            "https://www.google.com/maps/search/"
            + urllib.parse.quote(str(query))
        )

    @registry.tool(
        "browser_translate",
        "Открыть перевод текста в браузере.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "source": {"type": "string"},
                "target": {"type": "string"},
            },
            "required": ["text"],
        },
        category="browser",
    )
    def browser_translate(text, source="auto", target="ru"):
        return _open(
            "https://translate.google.com/?sl={}&tl={}&text={}&op=translate".format(
                urllib.parse.quote(source),
                urllib.parse.quote(target),
                urllib.parse.quote(str(text)),
            )
        )

    @registry.tool(
        "browser_youtube",
        "Найти видео на YouTube.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        category="browser",
    )
    def browser_youtube(query):
        return _open(
            "https://www.youtube.com/results?search_query="
            + urllib.parse.quote(str(query))
        )

    @registry.tool(
        "browser_fetch_text",
        "Скачать страницу и извлечь текст.",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["url"],
        },
        category="browser",
    )
    def browser_fetch_text(url, limit=8000):
        bs4 = optional_import("bs4")
        try:
            response = requests.get(
                str(url),
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 JARVIS"},
            )
            response.raise_for_status()
        except Exception as error:
            return f"Не удалось загрузить страницу: {error}"
        if bs4 is None:
            return response.text[: int(limit or 8000)]
        soup = bs4.BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = " ".join(soup.get_text(" ").split())
        return text[: int(limit or 8000)] or "Текст не найден."

    @registry.tool(
        "browser_fetch_links",
        "Скачать страницу и извлечь ссылки.",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["url"],
        },
        category="browser",
    )
    def browser_fetch_links(url, limit=100):
        bs4 = optional_import("bs4")
        try:
            response = requests.get(
                str(url),
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 JARVIS"},
            )
            response.raise_for_status()
        except Exception as error:
            return f"Не удалось загрузить страницу: {error}"
        if bs4 is None:
            return "Для извлечения ссылок установите beautifulsoup4."
        soup = bs4.BeautifulSoup(response.text, "html.parser")
        lines = []
        for link in soup.find_all("a", href=True):
            lines.append(f"{link.get_text(strip=True)} -> {link['href']}")
            if len(lines) >= int(limit or 100):
                break
        return "\n".join(lines) or "Ссылки не найдены."

    @registry.tool(
        "browser_playwright",
        "Автоматизация браузера через Playwright.",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": [
                        "text",
                        "title",
                        "screenshot",
                        "click",
                        "fill",
                        "html",
                    ],
                },
                "selector": {"type": "string"},
                "value": {"type": "string"},
                "path": {"type": "string"},
                "headless": {"type": "boolean"},
            },
            "required": ["url"],
        },
        category="browser",
        danger="confirm",
    )
    def browser_playwright(
        url,
        action="text",
        selector=None,
        value=None,
        path=None,
        headless=True,
    ):
        sync_api = optional_import("playwright.sync_api")
        if sync_api is None:
            return "Для автоматизации установите playwright и браузеры."
        try:
            with sync_api.sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=bool(headless))
                page = browser.new_page()
                page.goto(str(url), wait_until="domcontentloaded", timeout=60000)
                if action == "text":
                    result = page.inner_text("body")[:12000]
                elif action == "title":
                    result = page.title()
                elif action == "html":
                    result = page.content()[:12000]
                elif action == "screenshot":
                    output = resolve_path(
                        path or f"page_{int(time.time())}.png"
                    )
                    output.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(output), full_page=True)
                    result = f"Скриншот: {output}"
                elif action == "click":
                    page.click(str(selector), timeout=30000)
                    result = f"Клик по {selector}"
                elif action == "fill":
                    page.fill(str(selector), str(value or ""))
                    result = f"Заполнено {selector}"
                else:
                    result = "Неизвестное действие."
                browser.close()
                return result
        except Exception as error:
            return f"Playwright-ошибка: {error}"
