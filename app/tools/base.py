import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

_QUERY_STOPWORDS = {
    "а", "без", "бы", "в", "во", "вот", "для", "до", "его", "ее", "если",
    "есть", "же", "за", "и", "из", "или", "как", "ко", "к", "ли", "мне",
    "мы", "на", "над", "не", "ни", "но", "ну", "о", "об", "от", "по",
    "под", "при", "с", "со", "так", "то", "у", "что", "это", "я",
    "a", "an", "and", "for", "in", "is", "of", "on", "or", "the", "to",
    "with",
}

_QUERY_SUFFIXES = (
    "ами", "ями", "ого", "его", "ому", "ему", "ыми", "ими", "ая", "яя",
    "ое", "ее", "ые", "ие", "ый", "ий", "ой", "ей", "ов", "ев", "ью",
    "ия", "ию", "ии", "ам", "ям", "ах", "ях", "ом", "ем", "у", "ю",
    "ы", "и", "а", "я", "о", "е", "ь",
)


def _contains_term(haystack: str, variant: str) -> bool:
    pattern = rf"(?<![a-zа-я0-9]){re.escape(variant)}"
    return re.search(pattern, haystack) is not None


def _query_terms(query: str):
    terms = []
    for raw in str(query or "").lower().replace("ё", "е").split():
        word = raw.strip(".,!?;:()[]{}\"'«»—–-")
        if len(word) < 3 or word in _QUERY_STOPWORDS:
            continue
        variants = {word}
        for suffix in _QUERY_SUFFIXES:
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                variants.add(word[: -len(suffix)])
        if len(word) >= 4:
            variants.add(word[:4])
        if len(word) >= 5:
            variants.add(word[:5])
        terms.append(variants)
    return terms


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[..., Any]
    category: str = "general"
    danger: str = "safe"
    timeout: float = 120.0
    tags: tuple = ()
    enabled: bool = True

    def schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def catalog_item(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "danger": self.danger,
        }


@dataclass
class ToolResult:
    status: str = "ok"
    text: str = ""
    data: Any = None
    error: str = ""
    retryable: bool = False
    elapsed: float = 0.0

    def to_text(self):
        if self.status == "cancelled":
            return self.text or "__USER_CANCELLED__"
        if self.status == "error":
            return self.text or f"Ошибка: {self.error}"
        return self.text or "Готово."

    @classmethod
    def from_value(cls, value, elapsed=0.0):
        if isinstance(value, cls):
            if not value.elapsed:
                value.elapsed = elapsed
            return value
        if value is None:
            return cls(text="Готово.", elapsed=elapsed)
        if isinstance(value, str):
            return cls(text=value, elapsed=elapsed)
        try:
            text = json.dumps(
                value,
                ensure_ascii=False,
                default=str,
            )
        except (TypeError, ValueError):
            text = str(value)
        return cls(text=text, data=value, elapsed=elapsed)


@dataclass
class ToolContext:
    agent: Any = None
    config: Dict[str, Any] = field(default_factory=dict)
    memory: Any = None
    safety: Any = None
    tasks: Any = None
    notifier: Any = None
    publish: Any = None
    cancel_event: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


MAX_STRING_LENGTH = 1_000_000
MAX_ARRAY_ITEMS = 10_000
MAX_OBJECT_KEYS = 2_000


def validate_arguments(parameters: Dict[str, Any], arguments: Dict[str, Any]):
    if not isinstance(arguments, dict):
        return "Аргументы должны быть JSON-объектом."

    parameters = parameters or {}
    properties = parameters.get("properties", {})
    required = parameters.get("required", [])

    for key in required:
        if key not in arguments:
            return f"Не хватает обязательного аргумента «{key}»."

    if parameters.get("additionalProperties") is False:
        unknown = [
            key for key in arguments if key not in properties
        ]
        if unknown:
            return (
                "Неизвестные аргументы: "
                + ", ".join(sorted(str(item) for item in unknown))
                + "."
            )

    for key, value in arguments.items():
        schema = properties.get(key)
        if not isinstance(schema, dict):
            continue

        expected = schema.get("type")
        if expected and not _type_matches(value, expected):
            return (
                f"Аргумент «{key}» должен иметь тип {expected}, "
                f"получено {type(value).__name__}."
            )

        if expected == "string" and len(value) > MAX_STRING_LENGTH:
            return (
                f"Аргумент «{key}» слишком длинный "
                f"(максимум {MAX_STRING_LENGTH} символов)."
            )
        if expected == "array" and len(value) > MAX_ARRAY_ITEMS:
            return (
                f"Аргумент «{key}» содержит слишком много элементов "
                f"(максимум {MAX_ARRAY_ITEMS})."
            )
        if expected == "object" and len(value) > MAX_OBJECT_KEYS:
            return (
                f"Аргумент «{key}» содержит слишком много ключей "
                f"(максимум {MAX_OBJECT_KEYS})."
            )

        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if minimum is not None and value < minimum:
                return f"Аргумент «{key}» должен быть >= {minimum}."
            if maximum is not None and value > maximum:
                return f"Аргумент «{key}» должен быть <= {maximum}."

        allowed = schema.get("enum")
        if allowed and value not in allowed:
            return (
                f"Аргумент «{key}» должен быть одним из: "
                f"{', '.join(str(item) for item in allowed)}."
            )

    return None


class ToolRegistry:

    def __init__(
        self,
        context: Optional[ToolContext] = None,
        safety=None,
        max_workers: int = 8,
    ):
        self.context = context or ToolContext()
        self.safety = safety or self.context.safety
        self._tools: Dict[str, ToolSpec] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="JARVIS-Tool",
        )
        self._futures = set()
        self._futures_lock = threading.Lock()
        self._closed = False

    def close(self):
        """Останавливает пул потоков и отменяет невыполненные задачи."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
        with self._futures_lock:
            futures = list(self._futures)
        for future in futures:
            try:
                future.cancel()
            except Exception:
                pass
        self._executor.shutdown(wait=False, cancel_futures=True)

    shutdown = close

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def register(self, spec: ToolSpec) -> ToolSpec:
        if not spec.name:
            raise ValueError("У инструмента должно быть имя.")
        if not callable(spec.handler):
            raise ValueError(f"Обработчик {spec.name} не вызываемый.")
        with self._lock:
            self._tools[spec.name] = spec
        return spec

    def tool(
        self,
        name: str,
        description: str,
        parameters: Optional[Dict[str, Any]] = None,
        category: str = "general",
        danger: str = "safe",
        timeout: float = 120.0,
        tags: tuple = (),
    ):
        def decorator(handler):
            self.register(
                ToolSpec(
                    name=name,
                    description=description,
                    parameters=parameters or {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                    handler=handler,
                    category=category,
                    danger=danger,
                    timeout=timeout,
                    tags=tags,
                )
            )
            return handler

        return decorator

    def get(self, name: str) -> Optional[ToolSpec]:
        with self._lock:
            return self._tools.get(str(name or "").strip())

    def all(self, category: Optional[str] = None) -> List[ToolSpec]:
        with self._lock:
            items = list(self._tools.values())
        if category:
            category = str(category).strip().lower()
            items = [
                item
                for item in items
                if item.category.lower() == category
            ]
        return items

    def categories(self) -> List[str]:
        return sorted({item.category for item in self.all()})

    def schemas(
        self,
        names: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if names:
            items = [
                self._tools[name]
                for name in names
                if name in self._tools
            ]
        else:
            items = self.all()
            if categories:
                wanted = {
                    str(item).strip().lower()
                    for item in categories
                }
                items = [
                    item
                    for item in items
                    if item.category.lower() in wanted
                ]
        items = [item for item in items if item.enabled]
        if limit:
            items = items[:limit]
        return [item.schema() for item in items]

    def catalog(
        self,
        category: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        items = [
            item
            for item in self.all(category=category)
            if item.enabled
        ]
        terms = _query_terms(query)
        if terms:
            scored = []
            for item in items:
                haystack = (
                    f"{item.name} {item.description} "
                    f"{item.category} {' '.join(item.tags)}"
                ).lower().replace("ё", "е")
                score = sum(
                    1
                    for variants in terms
                    if any(
                        _contains_term(haystack, variant)
                        for variant in variants
                    )
                )
                if score:
                    scored.append((score, item))
            scored.sort(key=lambda pair: (-pair[0], pair[1].name))
            items = [item for _, item in scored]
        else:
            items = sorted(items, key=lambda item: (item.category, item.name))
        return [item.catalog_item() for item in items[:limit]]

    def _cancelled(self):
        event = getattr(self.context, "cancel_event", None)
        return event is not None and event.is_set()

    def execute(self, name: str, arguments: Optional[Dict[str, Any]] = None):
        return self.execute_result(name, arguments).to_text()

    def execute_result(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        spec = self.get(name)
        if spec is None:
            return ToolResult(
                status="error",
                text=f"Неизвестный инструмент: {name}",
            )

        if not spec.enabled:
            return ToolResult(
                status="denied",
                text=f"Инструмент {name} отключён.",
            )

        arguments = arguments or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                return ToolResult(
                    status="error",
                    text=(
                        f"Некорректные аргументы для {name}: "
                        f"ожидался JSON."
                    ),
                )

        error = validate_arguments(spec.parameters, arguments)
        if error:
            return ToolResult(
                status="error",
                text=f"Ошибка аргументов {name}: {error}",
            )

        if self._cancelled():
            return ToolResult(
                status="cancelled",
                text="Выполнение остановлено пользователем.",
            )

        if self.safety is not None:
            verdict = self.safety.before_tool(spec, arguments)
            if verdict is False:
                return ToolResult(
                    status="cancelled",
                    text="__USER_CANCELLED__",
                )
            if isinstance(verdict, str):
                return ToolResult(status="denied", text=verdict)

        started = time.time()
        try:
            future = self._executor.submit(spec.handler, **arguments)
            with self._futures_lock:
                self._futures.add(future)

            def _discard(done, registry=self):
                with registry._futures_lock:
                    registry._futures.discard(done)

            future.add_done_callback(_discard)
            result = future.result(timeout=spec.timeout)
        except FutureTimeout:
            future.cancel()
            result = ToolResult(
                status="timeout",
                text=(
                    f"Таймаут инструмента {name} "
                    f"({spec.timeout:.0f} c). "
                    "Операция могла продолжиться в фоне — "
                    "проверьте результат перед повтором."
                ),
                retryable=True,
                elapsed=time.time() - started,
            )
        except Exception as error:
            result = ToolResult(
                status="error",
                text=(
                    f"Ошибка инструмента {name}: "
                    f"{type(error).__name__}: {error}"
                ),
                error=f"{type(error).__name__}: {error}",
                retryable=True,
                elapsed=time.time() - started,
            )
        else:
            result = ToolResult.from_value(
                result,
                elapsed=time.time() - started,
            )

        if self._cancelled() and result.status == "ok":
            result = ToolResult(
                status="cancelled",
                text="Выполнение остановлено пользователем.",
                elapsed=result.elapsed,
            )

        if self.safety is not None:
            result.text = self.safety.after_tool(
                spec,
                arguments,
                result.to_text(),
                result.elapsed,
            )

        return result
