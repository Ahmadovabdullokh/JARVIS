import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from app.tools.common import optional_import


def _get_json(url, params=None, timeout=15):
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def register(registry):

    @registry.tool(
        "weather_current",
        "Текущая погода в городе.",
        {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "language": {"type": "string"},
            },
            "required": ["city"],
        },
        category="knowledge",
    )
    def weather_current(city, language="ru"):
        try:
            response = requests.get(
                f"https://wttr.in/{urllib.parse.quote(str(city))}",
                params={"format": "j1", "lang": language},
                timeout=20,
                headers={"User-Agent": "curl/8.0"},
            )
            data = response.json()
            current = data["current_condition"][0]
            description = current.get("lang_ru", [{}])[0].get("value") or current.get(
                "weatherDesc", [{}]
            )[0].get("value", "")
            return (
                f"{city}: {description}\n"
                f"Температура: {current.get('temp_C')} °C "
                f"(ощущается {current.get('FeelsLikeC')} °C)\n"
                f"Влажность: {current.get('humidity')}%\n"
                f"Ветер: {current.get('windspeedKmph')} км/ч\n"
                f"Давление: {current.get('pressure')} гПа"
            )
        except Exception as error:
            return f"Не удалось получить погоду: {error}"

    @registry.tool(
        "weather_forecast",
        "Прогноз погоды на несколько дней.",
        {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "days": {"type": "integer"},
                "language": {"type": "string"},
            },
            "required": ["city"],
        },
        category="knowledge",
    )
    def weather_forecast(city, days=3, language="ru"):
        try:
            response = requests.get(
                f"https://wttr.in/{urllib.parse.quote(str(city))}",
                params={"format": "j1", "lang": language},
                timeout=20,
                headers={"User-Agent": "curl/8.0"},
            )
            data = response.json()
            lines = []
            for day in data.get("weather", [])[: int(days or 3)]:
                lines.append(
                    f"{day.get('date')}: "
                    f"{day.get('mintempC')}..{day.get('maxtempC')} °C, "
                    f"осадки {day.get('hourly', [{}])[0].get('chanceofrain', '?')}%"
                )
            return "\n".join(lines) or "Прогноз недоступен."
        except Exception as error:
            return f"Не удалось получить прогноз: {error}"

    @registry.tool(
        "news_headlines",
        "Последние новости по теме.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "language": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        category="knowledge",
    )
    def news_headlines(query=None, language="ru", limit=10):
        bs4 = optional_import("bs4")
        if bs4 is None:
            return "Для новостей установите beautifulsoup4."
        url = (
            f"https://news.google.com/rss/search?"
            f"q={urllib.parse.quote(str(query or ''))}"
            f"&hl={language}&gl={language.upper()}&ceid={language.upper()}:{language}"
        )
        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
        except Exception as error:
            return f"Не удалось получить новости: {error}"
        soup = bs4.BeautifulSoup(response.text, "xml")
        lines = []
        for item in soup.find_all("item")[: int(limit or 10)]:
            lines.append(
                f"{item.title.get_text()} ({item.pubDate.get_text()})"
            )
        return "\n".join(lines) or "Новости не найдены."

    @registry.tool(
        "news_rss",
        "Прочитать RSS-ленту.",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["url"],
        },
        category="knowledge",
    )
    def news_rss(url, limit=10):
        bs4 = optional_import("bs4")
        if bs4 is None:
            return "Для RSS установите beautifulsoup4."
        try:
            response = requests.get(str(url), timeout=20)
            response.raise_for_status()
        except Exception as error:
            return f"Не удалось прочитать RSS: {error}"
        soup = bs4.BeautifulSoup(response.text, "xml")
        lines = []
        for item in soup.find_all("item")[: int(limit or 10)]:
            title = item.title.get_text() if item.title else ""
            link = item.link.get_text() if item.link else ""
            lines.append(f"{title}\n{link}")
        return "\n\n".join(lines) or "Записей нет."

    @registry.tool(
        "time_in_city",
        "Текущее время в городе или часовом поясе.",
        {
            "type": "object",
            "properties": {
                "zone": {"type": "string"},
            },
            "required": ["zone"],
        },
        category="knowledge",
    )
    def time_in_city(zone):
        try:
            current = datetime.now(ZoneInfo(str(zone)))
            return current.strftime("%Y-%m-%d %H:%M:%S %Z (%A)")
        except Exception as error:
            return f"Неизвестный часовой пояс «{zone}»: {error}"

    @registry.tool(
        "time_convert",
        "Перевести время между часовыми поясами.",
        {
            "type": "object",
            "properties": {
                "time": {"type": "string"},
                "from_zone": {"type": "string"},
                "to_zone": {"type": "string"},
            },
            "required": ["time", "from_zone", "to_zone"],
        },
        category="knowledge",
    )
    def time_convert(time, from_zone, to_zone):
        try:
            value = datetime.fromisoformat(str(time))
            source = value.replace(tzinfo=ZoneInfo(str(from_zone)))
            target = source.astimezone(ZoneInfo(str(to_zone)))
            return target.strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception as error:
            return f"Ошибка преобразования времени: {error}"

    @registry.tool(
        "sun_times",
        "Время восхода и заката.",
        {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
                "date": {"type": "string"},
            },
            "required": ["latitude", "longitude"],
        },
        category="knowledge",
    )
    def sun_times(latitude, longitude, date=None):
        try:
            data = _get_json(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "daily": "sunrise,sunset",
                    "timezone": "auto",
                    "start_date": date or datetime.now().date().isoformat(),
                    "end_date": date or datetime.now().date().isoformat(),
                },
            )
            daily = data.get("daily", {})
            return (
                f"Восход: {daily.get('sunrise', ['?'])[0]}\n"
                f"Закат: {daily.get('sunset', ['?'])[0]}"
            )
        except Exception as error:
            return f"Не удалось получить данные: {error}"

    @registry.tool(
        "web_search",
        "Поиск в интернете без открытия браузера.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
        category="knowledge",
    )
    def web_search(query, limit=8):
        duckduckgo = optional_import("duckduckgo_search")
        if duckduckgo is None:
            return "Для поиска установите duckduckgo-search."
        try:
            results = list(
                duckduckgo.DDGS().text(
                    str(query), max_results=int(limit or 8)
                )
            )
            return "\n\n".join(
                f"{item.get('title')}\n{item.get('href')}\n{item.get('body')}"
                for item in results
            ) or "Ничего не найдено."
        except Exception as error:
            return f"Ошибка поиска: {error}"

    @registry.tool(
        "stock_price",
        "Котировка акции.",
        {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
        category="knowledge",
    )
    def stock_price(symbol):
        try:
            response = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                params={"interval": "1d", "range": "5d"},
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            data = response.json()
            result = data["chart"]["result"][0]
            meta = result["meta"]
            return (
                f"{meta.get('symbol')}: {meta.get('regularMarketPrice')} "
                f"{meta.get('currency')}\n"
                f"Предыдущее закрытие: {meta.get('chartPreviousClose')}"
            )
        except Exception as error:
            return f"Не удалось получить котировку: {error}"

    @registry.tool(
        "crypto_price",
        "Курс криптовалюты.",
        {
            "type": "object",
            "properties": {
                "coins": {"type": "array"},
                "currency": {"type": "string"},
            },
            "required": [],
        },
        category="knowledge",
    )
    def crypto_price(coins=None, currency="usd"):
        try:
            ids = ",".join(coins or ["bitcoin", "ethereum"])
            data = _get_json(
                "https://api.coingecko.com/api/v3/simple/price",
                params={
                    "ids": ids,
                    "vs_currencies": currency,
                    "include_24hr_change": "true",
                },
            )
            lines = []
            for name, values in data.items():
                lines.append(
                    f"{name}: {values.get(currency)} {currency.upper()} "
                    f"({values.get(currency + '_24h_change', 0):.2f}% за 24ч)"
                )
            return "\n".join(lines)
        except Exception as error:
            return f"Не удалось получить курс: {error}"

    @registry.tool(
        "country_info",
        "Информация о стране.",
        {
            "type": "object",
            "properties": {"country": {"type": "string"}},
            "required": ["country"],
        },
        category="knowledge",
    )
    def country_info(country):
        try:
            data = _get_json(
                f"https://restcountries.com/v3.1/name/{urllib.parse.quote(str(country))}"
            )
            item = data[0]
            return (
                f"Название: {item.get('name', {}).get('common')}\n"
                f"Столица: {', '.join(item.get('capital', []))}\n"
                f"Регион: {item.get('region')}\n"
                f"Население: {item.get('population')}\n"
                f"Валюта: {', '.join(item.get('currencies', {}).keys())}\n"
                f"Языки: {', '.join(item.get('languages', {}).values())}"
            )
        except Exception as error:
            return f"Не удалось получить данные: {error}"

    @registry.tool(
        "holidays",
        "Праздники страны.",
        {
            "type": "object",
            "properties": {
                "country": {"type": "string"},
                "year": {"type": "integer"},
            },
            "required": ["country"],
        },
        category="knowledge",
    )
    def holidays(country, year=None):
        try:
            data = _get_json(
                "https://date.nager.at/api/v3/PublicHolidays/"
                f"{year or datetime.now().year}/{country}"
            )
            return "\n".join(
                f"{item.get('date')}: {item.get('localName')} "
                f"({item.get('name')})"
                for item in data
            ) or "Праздники не найдены."
        except Exception as error:
            return f"Не удалось получить праздники: {error}"

    @registry.tool(
        "quote_of_day",
        "Случайная мотивирующая цитата.",
        {"type": "object", "properties": {}, "required": []},
        category="knowledge",
    )
    def quote_of_day():
        try:
            data = _get_json("https://zenquotes.io/api/random")
            item = data[0]
            return f"«{item.get('q')}» — {item.get('a')}"
        except Exception as error:
            return f"Не удалось получить цитату: {error}"

    @registry.tool(
        "joke_random",
        "Случайная шутка.",
        {"type": "object", "properties": {}, "required": []},
        category="knowledge",
    )
    def joke_random():
        try:
            data = _get_json("https://official-joke-api.appspot.com/random_joke")
            return f"{data.get('setup')}\n{data.get('punchline')}"
        except Exception as error:
            return f"Не удалось получить шутку: {error}"

    @registry.tool(
        "fact_random",
        "Случайный интересный факт.",
        {"type": "object", "properties": {}, "required": []},
        category="knowledge",
    )
    def fact_random():
        try:
            data = _get_json("https://uselessfacts.jsph.pl/api/v2/facts/random")
            return data.get("text", "Факт не найден.")
        except Exception as error:
            return f"Не удалось получить факт: {error}"
