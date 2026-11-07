
import psutil


def _find_processes(identifier):
    identifier = str(identifier or "").strip()
    if not identifier:
        return []
    if identifier.isdigit():
        try:
            return [psutil.Process(int(identifier))]
        except psutil.Error:
            return []
    found = []
    for process in psutil.process_iter(["pid", "name"]):
        try:
            name = (process.info.get("name") or "").lower()
            if identifier.lower() in name:
                found.append(process)
        except psutil.Error:
            continue
    return found


def register(registry):

    @registry.tool(
        "processes_list",
        "Список процессов с PID, CPU и памятью.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "sort": {
                    "type": "string",
                    "enum": ["cpu", "memory", "name", "pid"],
                },
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        category="processes",
    )
    def processes_list(query=None, sort="cpu", limit=50):
        query = str(query or "").lower()
        items = []
        for process in psutil.process_iter(
            ["pid", "name", "cpu_percent", "memory_percent", "status"]
        ):
            try:
                info = process.info
                name = info.get("name") or "?"
                if query and query not in name.lower():
                    continue
                items.append(
                    (
                        info.get("pid"),
                        name,
                        float(info.get("cpu_percent") or 0),
                        float(info.get("memory_percent") or 0),
                        info.get("status") or "",
                    )
                )
            except psutil.Error:
                continue
        keys = {
            "cpu": lambda item: item[2],
            "memory": lambda item: item[3],
            "name": lambda item: item[1].lower(),
            "pid": lambda item: item[0],
        }
        items.sort(key=keys.get(sort, keys["cpu"]), reverse=sort != "name")
        limit = max(1, min(int(limit or 50), 500))
        lines = [
            f"PID {pid} | {name} | CPU {cpu:.1f}% | "
            f"RAM {mem:.1f}% | {status}"
            for pid, name, cpu, mem, status in items[:limit]
        ]
        return "\n".join(lines) or "Процессы не найдены."

    @registry.tool(
        "process_info",
        "Подробная информация о процессе по PID или имени.",
        {
            "type": "object",
            "properties": {"identifier": {"type": "string"}},
            "required": ["identifier"],
        },
        category="processes",
    )
    def process_info(identifier):
        processes = _find_processes(identifier)
        if not processes:
            return f"Процесс «{identifier}» не найден."
        process = processes[0]
        try:
            with process.oneshot():
                info = process.as_dict(
                    attrs=[
                        "pid",
                        "name",
                        "exe",
                        "cmdline",
                        "cwd",
                        "username",
                        "status",
                        "create_time",
                        "cpu_percent",
                        "memory_percent",
                        "num_threads",
                        "ppid",
                    ]
                )
        except psutil.Error as error:
            return f"Не удалось прочитать процесс: {error}"
        return (
            f"PID: {info.get('pid')}\n"
            f"Имя: {info.get('name')}\n"
            f"Путь: {info.get('exe')}\n"
            f"Команда: {' '.join(info.get('cmdline') or [])}\n"
            f"Рабочая папка: {info.get('cwd')}\n"
            f"Пользователь: {info.get('username')}\n"
            f"Статус: {info.get('status')}\n"
            f"Родитель: {info.get('ppid')}\n"
            f"Потоков: {info.get('num_threads')}\n"
            f"CPU: {float(info.get('cpu_percent') or 0):.1f}%\n"
            f"RAM: {float(info.get('memory_percent') or 0):.1f}%"
        )

    @registry.tool(
        "process_tree",
        "Показать дерево процессов.",
        {
            "type": "object",
            "properties": {"root": {"type": "string"}},
            "required": [],
        },
        category="processes",
    )
    def process_tree(root=None):
        processes = []
        for process in psutil.process_iter(["pid", "name", "ppid"]):
            try:
                info = process.info
                processes.append(
                    (
                        info.get("pid"),
                        info.get("name") or "?",
                        info.get("ppid"),
                    )
                )
            except psutil.Error:
                continue
        by_parent = {}
        for pid, name, ppid in processes:
            by_parent.setdefault(ppid, []).append((pid, name))
        lines = []

        def walk(pid, depth=0):
            for child_pid, child_name in sorted(by_parent.get(pid, [])):
                lines.append(
                    "  " * depth + f"{child_pid} {child_name}"
                )
                if depth < 5:
                    walk(child_pid, depth + 1)

        if root:
            matches = _find_processes(root)
            if not matches:
                return f"Процесс «{root}» не найден."
            walk(matches[0].pid, 0)
        else:
            walk(0, 0)
        return "\n".join(lines[:500]) or "Дерево процессов пусто."

    @registry.tool(
        "process_start",
        "Запустить программу с аргументами.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "args": {"type": "array"},
                "cwd": {"type": "string"},
                "wait": {"type": "boolean"},
            },
            "required": ["path"],
        },
        category="processes",
        danger="confirm",
    )
    def process_start(path, args=None, cwd=None, wait=False):
        import subprocess

        command = [str(path)] + [str(item) for item in (args or [])]
        if wait:
            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return result.stdout or result.stderr or "Программа завершена."
        process = subprocess.Popen(command, cwd=cwd)
        return f"Запущен процесс PID {process.pid}: {path}"

    @registry.tool(
        "process_kill",
        "Завершить процесс по PID или имени.",
        {
            "type": "object",
            "properties": {
                "identifier": {"type": "string"},
                "force": {"type": "boolean"},
            },
            "required": ["identifier"],
        },
        category="processes",
        danger="dangerous",
    )
    def process_kill(identifier, force=True):
        processes = _find_processes(identifier)
        if not processes:
            return f"Процесс «{identifier}» не найден."
        killed = []
        for process in processes:
            try:
                name = process.name()
                process.kill() if force else process.terminate()
                killed.append(f"{name} ({process.pid})")
            except psutil.Error as error:
                killed.append(f"ошибка: {error}")
        return "Завершено: " + ", ".join(killed)

    @registry.tool(
        "process_suspend",
        "Приостановить процесс.",
        {
            "type": "object",
            "properties": {"identifier": {"type": "string"}},
            "required": ["identifier"],
        },
        category="processes",
        danger="confirm",
    )
    def process_suspend(identifier):
        processes = _find_processes(identifier)
        if not processes:
            return f"Процесс «{identifier}» не найден."
        for process in processes:
            process.suspend()
        return f"Приостановлено процессов: {len(processes)}."

    @registry.tool(
        "process_resume",
        "Возобновить процесс.",
        {
            "type": "object",
            "properties": {"identifier": {"type": "string"}},
            "required": ["identifier"],
        },
        category="processes",
        danger="confirm",
    )
    def process_resume(identifier):
        processes = _find_processes(identifier)
        if not processes:
            return f"Процесс «{identifier}» не найден."
        for process in processes:
            process.resume()
        return f"Возобновлено процессов: {len(processes)}."

    @registry.tool(
        "process_priority",
        "Установить приоритет процесса.",
        {
            "type": "object",
            "properties": {
                "identifier": {"type": "string"},
                "priority": {
                    "type": "string",
                    "enum": [
                        "low",
                        "below_normal",
                        "normal",
                        "above_normal",
                        "high",
                        "realtime",
                    ],
                },
            },
            "required": ["identifier", "priority"],
        },
        category="processes",
        danger="confirm",
    )
    def process_priority(identifier, priority):
        values = {
            "low": psutil.IDLE_PRIORITY_CLASS,
            "below_normal": psutil.BELOW_NORMAL_PRIORITY_CLASS,
            "normal": psutil.NORMAL_PRIORITY_CLASS,
            "above_normal": psutil.ABOVE_NORMAL_PRIORITY_CLASS,
            "high": psutil.HIGH_PRIORITY_CLASS,
            "realtime": psutil.REALTIME_PRIORITY_CLASS,
        }
        processes = _find_processes(identifier)
        if not processes:
            return f"Процесс «{identifier}» не найден."
        for process in processes:
            process.nice(values[priority])
        return f"Приоритет {priority} установлен."

    @registry.tool(
        "process_connections",
        "Сетевые соединения процесса.",
        {
            "type": "object",
            "properties": {"identifier": {"type": "string"}},
            "required": ["identifier"],
        },
        category="processes",
    )
    def process_connections(identifier):
        processes = _find_processes(identifier)
        if not processes:
            return f"Процесс «{identifier}» не найден."
        lines = []
        for process in processes:
            try:
                for connection in process.net_connections(kind="inet"):
                    lines.append(
                        f"{connection.laddr} -> {connection.raddr} "
                        f"[{connection.status}]"
                    )
            except (psutil.Error, AttributeError):
                continue
        return "\n".join(lines) or "Соединений не найдено."

    @registry.tool(
        "process_open_files",
        "Открытые файлы процесса.",
        {
            "type": "object",
            "properties": {"identifier": {"type": "string"}},
            "required": ["identifier"],
        },
        category="processes",
    )
    def process_open_files(identifier):
        processes = _find_processes(identifier)
        if not processes:
            return f"Процесс «{identifier}» не найден."
        lines = []
        for process in processes:
            try:
                for item in process.open_files():
                    lines.append(item.path)
            except psutil.Error:
                continue
        return "\n".join(lines[:200]) or "Открытых файлов не найдено."

    @registry.tool(
        "process_wait",
        "Дождаться завершения процесса.",
        {
            "type": "object",
            "properties": {
                "identifier": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["identifier"],
        },
        category="processes",
    )
    def process_wait(identifier, timeout=60):
        processes = _find_processes(identifier)
        if not processes:
            return f"Процесс «{identifier}» не найден."
        process = processes[0]
        try:
            process.wait(timeout=max(1, int(timeout or 60)))
            return f"Процесс {identifier} завершён."
        except psutil.TimeoutExpired:
            return f"Процесс {identifier} ещё работает."
