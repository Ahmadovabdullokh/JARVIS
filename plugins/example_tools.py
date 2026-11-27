"""Демонстрационный плагин JARVIS.

Показывает минимальный контракт: манифест, регистрация инструментов и
хуки жизненного цикла. Скопируйте файл как основу для своего плагина:

* файл ``plugins/мой_плагин.py`` или пакет ``plugins/мой_плагин/plugin.py``;
* объявите ``PLUGIN`` (экземпляр ``JarvisPlugin``) либо модульные
  ``MANIFEST`` + ``register(registry)``;
* инструменты регистрируются через ``registry.tool(...)`` внутри
  ``register`` — они сразу доступны модели.

Права (``permissions``) декларативны: если в config.json задан
``plugins.allowed_permissions``, плагин с чужим правом не загрузится.
"""

from app.plugins import JarvisPlugin

MANIFEST = {
    "name": "example_tools",
    "version": "1.0.0",
    "author": "JARVIS",
    "description": "Демонстрационный плагин: проверка связи и эхо.",
    "permissions": ["data"],
    "api": 1,
}


class ExamplePlugin(JarvisPlugin):
    manifest_data = MANIFEST

    def register(self, registry):
        registry.tool(
            "plugin_ping",
            "Проверить, что плагинная подсистема работает. "
            "Возвращает «pong» или эхо переданного текста.",
            {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Необязательный текст для эха.",
                    }
                },
                "required": [],
            },
            category="general",
            danger="safe",
        )(self.ping)

    def ping(self, text=""):
        text = str(text or "").strip()
        return f"pong: {text}" if text else "pong"

    def on_start(self, context):
        pass


PLUGIN = ExamplePlugin()
