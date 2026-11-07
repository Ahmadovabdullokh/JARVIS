import json


def _text(value):
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def register(registry):
    context = registry.context

    @registry.tool(
        "list_capabilities",
        "Показать каталог доступных инструментов JARVIS. "
        "Можно фильтровать по категории или поисковому запросу.",
        {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Категория инструментов, например files, system, network.",
                },
                "query": {
                    "type": "string",
                    "description": "Поиск по названию и описанию.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Сколько инструментов вернуть.",
                },
            },
            "required": [],
        },
        category="agent",
        danger="safe",
    )
    def list_capabilities(category=None, query=None, limit=200):
        items = registry.catalog(
            category=category,
            query=query,
            limit=limit or 200,
        )
        if not items:
            return "Инструменты не найдены."
        lines = [
            f"- {item['name']} [{item['category']}]: {item['description']}"
            for item in items
        ]
        return "\n".join(lines)

    @registry.tool(
        "describe_capability",
        "Показать полную JSON-схему аргументов инструмента.",
        {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Имя инструмента.",
                },
            },
            "required": ["name"],
        },
        category="agent",
        danger="safe",
    )
    def describe_capability(name):
        spec = registry.get(name)
        if spec is None:
            return f"Инструмент «{name}» не найден."
        return _text(
            {
                "name": spec.name,
                "category": spec.category,
                "danger": spec.danger,
                "description": spec.description,
                "parameters": spec.parameters,
            }
        )

    @registry.tool(
        "run_capability",
        "Выполнить любой инструмент JARVIS по имени. "
        "Используй describe_capability, чтобы узнать аргументы.",
        {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Имя инструмента.",
                },
                "arguments": {
                    "type": "object",
                    "description": "Аргументы инструмента.",
                },
            },
            "required": ["name"],
        },
        category="agent",
        danger="safe",
    )
    def run_capability(name, arguments=None):
        if name in {
            "run_capability",
            "list_capabilities",
            "describe_capability",
        }:
            return "Нельзя вызывать мета-инструмент рекурсивно."
        return registry.execute(name, arguments or {})

    @registry.tool(
        "list_tasks",
        "Показать фоновые задачи и их статусы.",
        {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Фильтр: pending, running, done, failed, cancelled.",
                },
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        category="agent",
        danger="safe",
    )
    def list_tasks(status=None, limit=30):
        tasks = context.tasks
        if tasks is None:
            return "Менеджер задач недоступен."
        return tasks.summary(limit=limit or 30)

    @registry.tool(
        "task_status",
        "Показать подробности задачи по ID.",
        {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
        category="agent",
        danger="safe",
    )
    def task_status(task_id):
        tasks = context.tasks
        if tasks is None:
            return "Менеджер задач недоступен."
        task = tasks.get(task_id)
        if task is None:
            return f"Задача {task_id} не найдена."
        return _text(task)

    @registry.tool(
        "cancel_task",
        "Отменить фоновую задачу по ID.",
        {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
        category="agent",
        danger="safe",
    )
    def cancel_task(task_id):
        tasks = context.tasks
        if tasks is None:
            return "Менеджер задач недоступен."
        task = tasks.cancel(task_id)
        if task is None:
            return f"Задача {task_id} не найдена."
        return f"Задача {task_id} отменена."

    @registry.tool(
        "audit_log",
        "Показать последние записи журнала аудита действий.",
        {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "required": [],
        },
        category="agent",
        danger="safe",
    )
    def audit_log(limit=50):
        safety = context.safety
        if safety is None:
            return "Аудит недоступен."
        return safety.tail_audit(limit=limit or 50)

    @registry.tool(
        "emergency_stop",
        "Немедленно остановить выполнение инструментов и фоновые задачи.",
        {
            "type": "object",
            "properties": {},
            "required": [],
        },
        category="agent",
        danger="safe",
    )
    def emergency_stop():
        if context.safety is not None:
            context.safety.stop()
        if context.tasks is not None:
            context.tasks.cancel_all()
        return "Аварийная остановка выполнена."
