import os
import platform
import socket
import time
from pathlib import Path

import psutil

from app.tools.common import (
    human_size,
    optional_import,
    powershell,
    ps_quote,
    run_command,
)


def _wmi():
    return optional_import("wmi")


def _wmi_query(query):
    wmi = _wmi()
    if wmi is None:
        return []
    try:
        connection = wmi.WMI()
        return list(connection.query(query))
    except Exception:
        return []


def _get_registry_value(root, path, name):
    import winreg

    with winreg.OpenKey(root, path) as key:
        value, kind = winreg.QueryValueEx(key, name)
        return value, kind


def register(registry):

    @registry.tool(
        "system_info",
        "Подробная информация об ОС, процессоре, памяти и компьютере.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def system_info():
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(Path.home().anchor)
        boot = time.time() - psutil.boot_time()
        return (
            f"Компьютер: {platform.node()}\n"
            f"Пользователь: {os.environ.get('USERNAME', '—')}\n"
            f"ОС: {platform.system()} {platform.release()} "
            f"({platform.version()})\n"
            f"Архитектура: {platform.machine()}\n"
            f"Процессор: {platform.processor() or '—'} "
            f"({psutil.cpu_count(logical=False)} ядер / "
            f"{psutil.cpu_count(logical=True)} потоков)\n"
            f"Память: {human_size(memory.used)} из {human_size(memory.total)} "
            f"({memory.percent:.0f}%)\n"
            f"Диск {Path.home().anchor}: "
            f"{human_size(disk.used)} из {human_size(disk.total)} "
            f"({disk.percent:.0f}%)\n"
            f"Время работы: {int(boot // 3600)} ч "
            f"{int((boot % 3600) // 60)} мин\n"
            f"Python: {platform.python_version()}"
        )

    @registry.tool(
        "hardware_info",
        "Информация о материнской плате, BIOS и серийных номерах.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def hardware_info():
        items = []
        for query, fields in (
            (
                "SELECT Manufacturer, Product, SerialNumber FROM Win32_BaseBoard",
                ("Manufacturer", "Product", "SerialNumber"),
            ),
            (
                "SELECT Manufacturer, SMBIOSBIOSVersion, ReleaseDate FROM Win32_BIOS",
                ("Manufacturer", "SMBIOSBIOSVersion", "ReleaseDate"),
            ),
            (
                "SELECT Manufacturer, Model FROM Win32_ComputerSystem",
                ("Manufacturer", "Model"),
            ),
        ):
            for row in _wmi_query(query):
                values = [
                    f"{field}={getattr(row, field, '—')}"
                    for field in fields
                ]
                items.append("; ".join(values))
        if not items:
            return "WMI недоступен. Установите пакет wmi для подробностей."
        return "\n".join(items)

    @registry.tool(
        "cpu_info",
        "Загрузка и частота процессора.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def cpu_info():
        frequency = psutil.cpu_freq()
        return (
            f"Загрузка CPU: {psutil.cpu_percent(interval=0.2):.0f}%\n"
            f"Частота: {frequency.current:.0f} МГц "
            f"(макс. {frequency.max:.0f} МГц)\n"
            f"Ядра: {psutil.cpu_count(logical=False)}, "
            f"потоки: {psutil.cpu_count(logical=True)}"
        )

    @registry.tool(
        "memory_info",
        "Подробная информация о памяти и файле подкачки.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def memory_info():
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        return (
            f"RAM: {human_size(memory.used)} / {human_size(memory.total)} "
            f"({memory.percent:.0f}%), свободно {human_size(memory.available)}\n"
            f"Swap: {human_size(swap.used)} / {human_size(swap.total)} "
            f"({swap.percent:.0f}%)"
        )

    @registry.tool(
        "disk_partitions",
        "Список разделов, файловых систем и свободного места.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def disk_partitions():
        lines = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                lines.append(
                    f"{part.device} {part.fstype} "
                    f"{human_size(usage.free)} свободно из "
                    f"{human_size(usage.total)}"
                )
            except OSError:
                lines.append(f"{part.device} {part.fstype}")
        return "\n".join(lines) or "Разделы не найдены."

    @registry.tool(
        "disk_smart",
        "Показать состояние дисков и SMART через PowerShell.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def disk_smart():
        return powershell(
            "Get-PhysicalDisk | Select-Object FriendlyName, MediaType, "
            "HealthStatus, OperationalStatus, Size | Format-Table -AutoSize | Out-String",
            timeout=60,
        )

    @registry.tool(
        "battery_info",
        "Состояние батареи: заряд, питание, время автономной работы.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def battery_info():
        battery = psutil.sensors_battery()
        if battery is None:
            return "Батарея не обнаружена."
        remaining = ""
        if battery.secsleft not in (
            psutil.POWER_TIME_UNLIMITED,
            psutil.POWER_TIME_UNKNOWN,
        ):
            remaining = (
                f", осталось {battery.secsleft // 3600} ч "
                f"{(battery.secsleft % 3600) // 60} мин"
            )
        return (
            f"Заряд {battery.percent:.0f}%"
            f"{', питание от сети' if battery.power_plugged else ''}"
            f"{remaining}."
        )

    @registry.tool(
        "temperature_info",
        "Показать доступные датчики температуры.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def temperature_info():
        try:
            temperatures = psutil.sensors_temperatures()
        except Exception:
            temperatures = {}
        if not temperatures:
            return (
                "Датчики температуры недоступны через psutil. "
                "Можно установить OpenHardwareMonitor или LibreHardwareMonitor."
            )
        lines = []
        for name, entries in temperatures.items():
            for entry in entries:
                lines.append(
                    f"{name} {entry.label or ''}: "
                    f"{entry.current:.1f}°C"
                )
        return "\n".join(lines)

    @registry.tool(
        "gpu_info",
        "Информация о видеокартах.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def gpu_info():
        rows = _wmi_query(
            "SELECT Name, AdapterRAM, DriverVersion FROM Win32_VideoController"
        )
        if not rows:
            return powershell(
                "Get-CimInstance Win32_VideoController | "
                "Select-Object Name, DriverVersion | Format-Table -AutoSize | Out-String",
                timeout=30,
            )
        return "\n".join(
            f"{getattr(row, 'Name', '—')} | "
            f"{human_size(getattr(row, 'AdapterRAM', 0) or 0)} | "
            f"драйвер {getattr(row, 'DriverVersion', '—')}"
            for row in rows
        )

    @registry.tool(
        "network_adapters",
        "Список сетевых адаптеров и их IP-адресов.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def network_adapters():
        lines = []
        for name, addresses in psutil.net_if_addrs().items():
            ips = [
                addr.address
                for addr in addresses
                if addr.family == socket.AF_INET
            ]
            lines.append(f"{name}: {', '.join(ips) or 'нет IPv4'}")
        return "\n".join(lines) or "Адаптеры не найдены."

    @registry.tool(
        "services_list",
        "Список служб Windows.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        category="system",
    )
    def services_list(query=None, limit=100):
        query = str(query or "").lower()
        lines = []
        for service in psutil.win_service_iter():
            try:
                info = service.as_dict()
            except Exception:
                continue
            name = info.get("name", "")
            display = info.get("display_name", "")
            if query and query not in name.lower() and query not in display.lower():
                continue
            lines.append(
                f"{name} | {display} | {info.get('status')} | "
                f"start={info.get('start_type')}"
            )
            if len(lines) >= max(1, int(limit or 100)):
                break
        return "\n".join(lines) or "Службы не найдены."

    @registry.tool(
        "service_control",
        "Запустить, остановить или перезапустить службу Windows.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "restart", "status"],
                },
            },
            "required": ["name", "action"],
        },
        category="system",
        danger="dangerous",
    )
    def service_control(name, action):
        name = str(name or "").strip()
        if not name:
            return "Не указано имя службы."
        if action == "status":
            return powershell(
                f"Get-Service -Name {ps_quote(name)} | "
                "Select-Object Name, Status, StartType | Format-List | Out-String",
                timeout=30,
            )
        commands = {
            "start": f"Start-Service -Name {ps_quote(name)}",
            "stop": f"Stop-Service -Name {ps_quote(name)} -Force",
            "restart": (
                f"Restart-Service -Name {ps_quote(name)} -Force"
            ),
        }
        return powershell(commands[action], timeout=60)

    @registry.tool(
        "startup_apps_list",
        "Список приложений в автозагрузке.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def startup_apps_list():
        script = (
            "Get-CimInstance Win32_StartupCommand | "
            "Select-Object Name, Command, Location, User | "
            "Format-Table -AutoSize | Out-String"
        )
        return powershell(script, timeout=60)

    @registry.tool(
        "startup_app_set",
        "Включить или отключить приложение в автозагрузке по имени.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "enabled": {"type": "boolean"},
            },
            "required": ["name", "enabled"],
        },
        category="system",
        danger="dangerous",
    )
    def startup_app_set(name, enabled):
        import winreg

        paths = [
            (
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
            ),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
            ),
        ]
        for root, path in paths:
            try:
                with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as key:
                    try:
                        value, _ = winreg.QueryValueEx(key, name)
                    except FileNotFoundError:
                        continue
                    if enabled:
                        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
                    else:
                        winreg.DeleteValue(key, name)
                    return (
                        f"Автозагрузка «{name}» "
                        f"{'включена' if enabled else 'отключена'}."
                    )
            except OSError:
                continue
        return f"Приложение «{name}» не найдено в автозагрузке."

    @registry.tool(
        "installed_apps_list",
        "Список установленных программ.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        category="system",
    )
    def installed_apps_list(query=None, limit=200):
        import winreg

        query = str(query or "").lower()
        keys = [
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
            ),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
            ),
            (
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
            ),
        ]
        items = []
        for root, path in keys:
            try:
                with winreg.OpenKey(root, path) as key:
                    for index in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            sub_name = winreg.EnumKey(key, index)
                            with winreg.OpenKey(key, sub_name) as sub:
                                name = winreg.QueryValueEx(sub, "DisplayName")[0]
                                version = ""
                                try:
                                    version = winreg.QueryValueEx(sub, "DisplayVersion")[0]
                                except OSError:
                                    pass
                                if query and query not in str(name).lower():
                                    continue
                                items.append(f"{name} {version}".strip())
                        except OSError:
                            continue
            except OSError:
                continue
        items = sorted(set(items))
        if not items:
            return "Программы не найдены."
        return "\n".join(items[: max(1, int(limit or 200))])

    @registry.tool(
        "windows_updates",
        "Список установленных обновлений Windows.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def windows_updates():
        return powershell(
            "Get-HotFix | Sort-Object InstalledOn -Descending | "
            "Select-Object HotFixID, Description, InstalledOn | "
            "Format-Table -AutoSize | Out-String",
            timeout=60,
        )

    @registry.tool(
        "environment_variables",
        "Показать переменные окружения.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "scope": {
                    "type": "string",
                    "enum": ["process", "user", "machine"],
                },
            },
            "required": [],
        },
        category="system",
    )
    def environment_variables(name=None, scope="process"):
        if name:
            if scope == "user":
                import winreg

                try:
                    value, _ = _get_registry_value(
                        winreg.HKEY_CURRENT_USER,
                        "Environment",
                        name,
                    )
                    return f"{name}={value}"
                except OSError:
                    return f"Переменная {name} не найдена."
            if scope == "machine":
                import winreg

                try:
                    value, _ = _get_registry_value(
                        winreg.HKEY_LOCAL_MACHINE,
                        r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
                        name,
                    )
                    return f"{name}={value}"
                except OSError:
                    return f"Переменная {name} не найдена."
            return f"{name}={os.environ.get(name, '—')}"
        return "\n".join(
            f"{key}={value}"
            for key, value in sorted(os.environ.items())
        )

    @registry.tool(
        "environment_set",
        "Установить переменную окружения пользователя.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["name", "value"],
        },
        category="system",
        danger="dangerous",
    )
    def environment_set(name, value):
        result = run_command(
            ["setx", str(name), str(value)],
            timeout=30,
        )
        return result["stdout"] or result["stderr"]

    @registry.tool(
        "registry_read",
        "Прочитать значение реестра Windows.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "name": {"type": "string"},
                "hive": {
                    "type": "string",
                    "enum": ["HKCU", "HKLM", "HKCR", "HKU"],
                },
            },
            "required": ["path", "name"],
        },
        category="system",
    )
    def registry_read(path, name, hive="HKCU"):
        import winreg

        roots = {
            "HKCU": winreg.HKEY_CURRENT_USER,
            "HKLM": winreg.HKEY_LOCAL_MACHINE,
            "HKCR": winreg.HKEY_CLASSES_ROOT,
            "HKU": winreg.HKEY_USERS,
        }
        value, kind = _get_registry_value(roots[hive], path, name)
        return f"{name} = {value} (тип {kind})"

    @registry.tool(
        "registry_write",
        "Записать значение реестра Windows. Перед записью делается .reg-бэкап.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "name": {"type": "string"},
                "value": {"type": "string"},
                "hive": {
                    "type": "string",
                    "enum": ["HKCU", "HKLM", "HKCR", "HKU"],
                },
            },
            "required": ["path", "name", "value"],
        },
        category="system",
        danger="dangerous",
    )
    def registry_write(path, name, value, hive="HKCU"):
        import winreg

        roots = {
            "HKCU": winreg.HKEY_CURRENT_USER,
            "HKLM": winreg.HKEY_LOCAL_MACHINE,
            "HKCR": winreg.HKEY_CLASSES_ROOT,
            "HKU": winreg.HKEY_USERS,
        }
        backup = (
            Path.home()
            / "AppData"
            / "Local"
            / "JARVIS"
            / "registry_backup"
        )
        backup.mkdir(parents=True, exist_ok=True)
        run_command(
            [
                "reg",
                "export",
                f"{hive}\\{path}",
                str(backup / f"{int(time.time())}.reg"),
                "/y",
            ],
            timeout=30,
        )
        with winreg.OpenKey(
            roots[hive],
            path,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))
        return f"Реестр обновлён: {hive}\\{path}\\{name}"

    @registry.tool(
        "registry_delete",
        "Удалить значение реестра Windows.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "name": {"type": "string"},
                "hive": {
                    "type": "string",
                    "enum": ["HKCU", "HKLM", "HKCR", "HKU"],
                },
            },
            "required": ["path", "name"],
        },
        category="system",
        danger="dangerous",
    )
    def registry_delete(path, name, hive="HKCU"):
        import winreg

        roots = {
            "HKCU": winreg.HKEY_CURRENT_USER,
            "HKLM": winreg.HKEY_LOCAL_MACHINE,
            "HKCR": winreg.HKEY_CLASSES_ROOT,
            "HKU": winreg.HKEY_USERS,
        }
        with winreg.OpenKey(
            roots[hive],
            path,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, name)
        return f"Удалено значение {hive}\\{path}\\{name}"

    @registry.tool(
        "event_log",
        "Прочитать журнал событий Windows.",
        {
            "type": "object",
            "properties": {
                "log": {"type": "string"},
                "limit": {"type": "integer"},
                "level": {"type": "string"},
            },
            "required": [],
        },
        category="system",
    )
    def event_log(log="System", limit=30, level=None):
        level_filter = (
            f" | Where-Object {{$_.LevelDisplayName -eq {ps_quote(level)}}}"
            if level
            else ""
        )
        script = (
            f"Get-WinEvent -LogName {ps_quote(log)} -MaxEvents "
            f"{max(1, int(limit or 30))} -ErrorAction SilentlyContinue"
            f"{level_filter} | Select-Object TimeCreated, Id, "
            "LevelDisplayName, ProviderName, Message | "
            "Format-List | Out-String"
        )
        return powershell(script, timeout=60)

    @registry.tool(
        "scheduled_tasks_list",
        "Список заданий планировщика Windows.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        category="system",
    )
    def scheduled_tasks_list(query=None, limit=100):
        query = str(query or "")
        filter_text = (
            f" | Where-Object {{$_.TaskName -like '*{query}*'}}"
            if query
            else ""
        )
        script = (
            "Get-ScheduledTask"
            f"{filter_text} | Select-Object TaskName, State, TaskPath | "
            f"Select-Object -First {max(1, int(limit or 100))} | "
            "Format-Table -AutoSize | Out-String"
        )
        return powershell(script, timeout=60)

    @registry.tool(
        "scheduled_task_control",
        "Запустить, включить, отключить или удалить задание планировщика.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["run", "enable", "disable", "delete", "info"],
                },
            },
            "required": ["name", "action"],
        },
        category="system",
        danger="dangerous",
    )
    def scheduled_task_control(name, action):
        commands = {
            "run": f"Start-ScheduledTask -TaskName {ps_quote(name)}",
            "enable": f"Enable-ScheduledTask -TaskName {ps_quote(name)}",
            "disable": f"Disable-ScheduledTask -TaskName {ps_quote(name)}",
            "delete": f"Unregister-ScheduledTask -TaskName {ps_quote(name)} -Confirm:$false",
            "info": (
                f"Get-ScheduledTask -TaskName {ps_quote(name)} | "
                "Format-List | Out-String"
            ),
        }
        return powershell(commands[action], timeout=60)

    @registry.tool(
        "scheduled_task_create",
        "Создать ежедневное задание планировщика.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "command": {"type": "string"},
                "time": {"type": "string"},
            },
            "required": ["name", "command", "time"],
        },
        category="system",
        danger="dangerous",
    )
    def scheduled_task_create(name, command, time):
        script = (
            f"$action = New-ScheduledTaskAction -Execute 'powershell.exe' "
            f"-Argument {ps_quote('-NoProfile -Command ' + command)}; "
            f"$trigger = New-ScheduledTaskTrigger -Daily -At {ps_quote(time)}; "
            f"Register-ScheduledTask -TaskName {ps_quote(name)} "
            "-Action $action -Trigger $trigger -Force | Out-Null; "
            f"'Задание {name} создано.'"
        )
        return powershell(script, timeout=60)

    @registry.tool(
        "power_plans_list",
        "Список схем электропитания.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def power_plans_list():
        return powershell("powercfg /list", timeout=30)

    @registry.tool(
        "power_plan_set",
        "Включить схему электропитания по GUID.",
        {
            "type": "object",
            "properties": {"guid": {"type": "string"}},
            "required": ["guid"],
        },
        category="system",
        danger="confirm",
    )
    def power_plan_set(guid):
        return powershell(
            f"powercfg /setactive {ps_quote(guid)}; powercfg /getactivescheme",
            timeout=30,
        )

    @registry.tool(
        "brightness_get",
        "Показать текущую яркость экрана.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def brightness_get():
        script = (
            "(Get-CimInstance -Namespace root/WMI -ClassName "
            "WmiMonitorBrightness -ErrorAction SilentlyContinue).CurrentBrightness"
        )
        return powershell(script, timeout=30)

    @registry.tool(
        "brightness_set",
        "Установить яркость экрана в процентах.",
        {
            "type": "object",
            "properties": {"percent": {"type": "integer"}},
            "required": ["percent"],
        },
        category="system",
        danger="confirm",
    )
    def brightness_set(percent):
        percent = max(0, min(int(percent), 100))
        script = (
            "(Get-CimInstance -Namespace root/WMI -ClassName "
            "WmiMonitorBrightnessMethods).WmiSetBrightness(1, "
            f"{percent})"
        )
        return powershell(script, timeout=30)

    @registry.tool(
        "audio_devices_list",
        "Список аудиоустройств Windows.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def audio_devices_list():
        script = (
            "Get-CimInstance Win32_SoundDevice | "
            "Select-Object Name, Manufacturer, Status | "
            "Format-Table -AutoSize | Out-String"
        )
        return powershell(script, timeout=30)

    @registry.tool(
        "printers_list",
        "Список принтеров.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def printers_list():
        return powershell(
            "Get-Printer | Select-Object Name, PrinterStatus, "
            "DriverName, PortName | Format-Table -AutoSize | Out-String",
            timeout=30,
        )

    @registry.tool(
        "print_file",
        "Отправить файл на печать.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "printer": {"type": "string"},
            },
            "required": ["path"],
        },
        category="system",
        danger="confirm",
    )
    def print_file(path, printer=None):
        from app.tools.common import resolve_path

        target = resolve_path(path, must_exist=True)
        if printer:
            result = run_command(
                ["powershell", "-NoProfile", "-Command",
                 f"Start-Process -FilePath {ps_quote(str(target))} "
                 f"-Verb PrintTo -ArgumentList {ps_quote(printer)}"],
                timeout=30,
            )
        else:
            os.startfile(str(target), "print")
            result = {"stdout": "", "stderr": ""}
        return result["stdout"] or "Файл отправлен на печать."

    @registry.tool(
        "usb_devices_list",
        "Список USB-устройств.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def usb_devices_list():
        return powershell(
            "Get-PnpDevice -PresentOnly | Where-Object "
            "{$_.InstanceId -like 'USB*'} | Select-Object "
            "FriendlyName, Status, Class | Format-Table -AutoSize | Out-String",
            timeout=30,
        )

    @registry.tool(
        "bluetooth_status",
        "Состояние Bluetooth-адаптера.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def bluetooth_status():
        return powershell(
            "Get-PnpDevice -Class Bluetooth -PresentOnly | "
            "Select-Object FriendlyName, Status | "
            "Format-Table -AutoSize | Out-String",
            timeout=30,
        )

    @registry.tool(
        "wifi_status",
        "Показать текущее WiFi-подключение.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def wifi_status():
        return powershell("netsh wlan show interfaces", timeout=30)

    @registry.tool(
        "wifi_list",
        "Список доступных WiFi-сетей.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def wifi_list():
        return powershell("netsh wlan show networks mode=bssid", timeout=30)

    @registry.tool(
        "wifi_connect",
        "Подключиться к WiFi-сети.",
        {
            "type": "object",
            "properties": {
                "ssid": {"type": "string"},
                "password": {"type": "string"},
            },
            "required": ["ssid"],
        },
        category="system",
        danger="confirm",
    )
    def wifi_connect(ssid, password=None):
        if password:
            profile = (
                '<?xml version="1.0"?>'
                '<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">'
                f"<name>{ssid}</name>"
                "<SSIDConfig><SSID><name>" + ssid + "</name></SSID></SSIDConfig>"
                "<connectionType>ESS</connectionType>"
                "<connectionMode>auto</connectionMode>"
                "<MSM><security><authEncryption>"
                "<authentication>WPA2PSK</authentication>"
                "<encryption>AES</encryption><useOneX>false</useOneX>"
                "</authEncryption><sharedKey><keyType>passPhrase</keyType>"
                "<protected>false</protected><keyMaterial>"
                + str(password)
                + "</keyMaterial></sharedKey></security></MSM></WLANProfile>"
            )
            import tempfile

            temp = Path(tempfile.gettempdir()) / "jarvis_wifi.xml"
            temp.write_text(profile, encoding="utf-8")
            powershell(
                f"netsh wlan add profile filename={ps_quote(str(temp))}",
                timeout=30,
            )
        return powershell(
            f"netsh wlan connect name={ps_quote(ssid)}",
            timeout=30,
        )

    @registry.tool(
        "wifi_disconnect",
        "Отключиться от WiFi.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
        danger="confirm",
    )
    def wifi_disconnect():
        return powershell("netsh wlan disconnect", timeout=30)

    @registry.tool(
        "firewall_status",
        "Показать состояние брандмауэра Windows.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def firewall_status():
        return powershell(
            "Get-NetFirewallProfile | Select-Object Name, Enabled | "
            "Format-Table -AutoSize | Out-String",
            timeout=30,
        )

    @registry.tool(
        "firewall_rules",
        "Показать правила брандмауэра.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        category="system",
    )
    def firewall_rules(query=None, limit=50):
        filter_text = (
            f" | Where-Object {{$_.DisplayName -like '*{query}*'}}"
            if query
            else ""
        )
        return powershell(
            "Get-NetFirewallRule"
            f"{filter_text} | Select-Object DisplayName, Direction, Action, Enabled | "
            f"Select-Object -First {max(1, int(limit or 50))} | "
            "Format-Table -AutoSize | Out-String",
            timeout=60,
        )

    @registry.tool(
        "defender_status",
        "Показать состояние Microsoft Defender.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def defender_status():
        return powershell(
            "Get-MpComputerStatus | Select-Object "
            "AntivirusEnabled, RealTimeProtectionEnabled, "
            "AntivirusSignatureLastUpdated, QuickScanStartTime | "
            "Format-List | Out-String",
            timeout=60,
        )

    @registry.tool(
        "defender_scan",
        "Запустить проверку Microsoft Defender.",
        {
            "type": "object",
            "properties": {
                "scan_type": {
                    "type": "string",
                    "enum": ["QuickScan", "FullScan"],
                }
            },
            "required": [],
        },
        category="system",
        danger="confirm",
    )
    def defender_scan(scan_type="QuickScan"):
        return powershell(
            f"Start-MpScan -ScanType {ps_quote(scan_type or 'QuickScan')}",
            timeout=3600,
        )

    @registry.tool(
        "restore_points_list",
        "Список точек восстановления Windows.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def restore_points_list():
        return powershell(
            "Get-ComputerRestorePoint | Select-Object "
            "SequenceNumber, Description, CreationTime | "
            "Format-Table -AutoSize | Out-String",
            timeout=60,
        )

    @registry.tool(
        "restore_point_create",
        "Создать точку восстановления Windows.",
        {
            "type": "object",
            "properties": {"description": {"type": "string"}},
            "required": ["description"],
        },
        category="system",
        danger="confirm",
    )
    def restore_point_create(description):
        return powershell(
            "Enable-ComputerRestore -Drive 'C:\\'; "
            f"Checkpoint-Computer -Description {ps_quote(description)} "
            "-RestorePointType 'MODIFY_SETTINGS'",
            timeout=300,
        )

    @registry.tool(
        "users_list",
        "Список локальных пользователей.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def users_list():
        return powershell(
            "Get-LocalUser | Select-Object Name, Enabled, "
            "LastLogon, Description | Format-Table -AutoSize | Out-String",
            timeout=30,
        )

    @registry.tool(
        "time_info",
        "Показать дату, время, часовой пояс и аптайм.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def time_info():
        boot = time.time() - psutil.boot_time()
        return (
            f"Сейчас: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Часовой пояс: {time.tzname[0]}\n"
            f"Аптайм: {int(boot // 3600)} ч "
            f"{int((boot % 3600) // 60)} мин"
        )

    @registry.tool(
        "timezone_set",
        "Установить часовой пояс Windows по имени, например Russian Standard Time.",
        {
            "type": "object",
            "properties": {"timezone": {"type": "string"}},
            "required": ["timezone"],
        },
        category="system",
        danger="confirm",
    )
    def timezone_set(timezone):
        return powershell(
            f"Set-TimeZone -Id {ps_quote(timezone)}; Get-TimeZone | Out-String",
            timeout=30,
        )

    @registry.tool(
        "hosts_read",
        "Прочитать файл hosts.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def hosts_read():
        hosts = Path(os.environ.get("WINDIR", "C:\\Windows")) / "System32" / "drivers" / "etc" / "hosts"
        return hosts.read_text(encoding="utf-8", errors="replace")

    @registry.tool(
        "hosts_write",
        "Перезаписать файл hosts.",
        {
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
        },
        category="system",
        danger="dangerous",
    )
    def hosts_write(content):
        hosts = Path(os.environ.get("WINDIR", "C:\\Windows")) / "System32" / "drivers" / "etc" / "hosts"
        backup = hosts.with_suffix(".jarvis.bak")
        if hosts.exists() and not backup.exists():
            backup.write_bytes(hosts.read_bytes())
        hosts.write_text(str(content), encoding="utf-8")
        return f"Файл hosts обновлён. Резервная копия: {backup}"

    @registry.tool(
        "dns_cache_flush",
        "Очистить кэш DNS.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def dns_cache_flush():
        return powershell("Clear-DnsClientCache; 'DNS-кэш очищен.'", timeout=30)

    @registry.tool(
        "arp_table",
        "Показать ARP-таблицу.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def arp_table():
        return run_command(["arp", "-a"], timeout=30)["stdout"]

    @registry.tool(
        "route_table",
        "Показать таблицу маршрутизации.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def route_table():
        return run_command(["route", "print"], timeout=30)["stdout"]

    @registry.tool(
        "power_action",
        "Выполнить действие с питанием: shutdown, restart, sleep, hibernate, lock.",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["shutdown", "restart", "sleep", "hibernate", "lock"],
                },
                "delay": {"type": "integer"},
            },
            "required": ["action"],
        },
        category="system",
        danger="dangerous",
    )
    def power_action(action, delay=0):
        delay = max(0, int(delay or 0))
        if action == "lock":
            import ctypes

            ctypes.windll.user32.LockWorkStation()
            return "Компьютер заблокирован."
        if action == "sleep":
            return powershell("Add-Type -AssemblyName System.Windows.Forms; "
                              "[System.Windows.Forms.Application]::SetSuspendState("
                              "'Suspend', $false, $false)", timeout=30)
        if action == "hibernate":
            return run_command(["shutdown", "/h"], timeout=30)["stdout"] or "Гибернация запущена."
        flags = {"shutdown": "/s", "restart": "/r"}
        return run_command(
            ["shutdown", flags[action], "/t", str(delay)],
            timeout=30,
        )["stdout"] or f"{action} запланирован через {delay} c."

    @registry.tool(
        "performance_snapshot",
        "Снимок производительности: CPU, память, диск, сеть, топ процессов.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def performance_snapshot():
        cpu = psutil.cpu_percent(interval=0.2)
        memory = psutil.virtual_memory()
        disk = psutil.disk_io_counters()
        net = psutil.net_io_counters()
        processes = []
        for process in psutil.process_iter(["name", "cpu_percent", "memory_percent"]):
            try:
                processes.append(
                    (
                        process.info.get("name") or "?",
                        process.info.get("cpu_percent") or 0,
                        process.info.get("memory_percent") or 0,
                    )
                )
            except Exception:
                continue
        processes.sort(key=lambda item: (item[1], item[2]), reverse=True)
        top = "\n".join(
            f"{name}: CPU {cpu:.1f}%, RAM {mem:.1f}%"
            for name, cpu, mem in processes[:5]
        )
        return (
            f"CPU: {cpu:.0f}%\n"
            f"RAM: {memory.percent:.0f}%\n"
            f"Диск: чтение {human_size(disk.read_bytes)}, "
            f"запись {human_size(disk.write_bytes)}\n"
            f"Сеть: отправлено {human_size(net.bytes_sent)}, "
            f"получено {human_size(net.bytes_recv)}\n"
            f"Топ процессов:\n{top}"
        )

    @registry.tool(
        "os_info",
        "Краткая информация об операционной системе.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def os_info():
        return (
            f"{platform.system()} {platform.release()} "
            f"build {platform.version()} "
            f"({platform.machine()})"
        )

    @registry.tool(
        "uptime",
        "Показать время работы компьютера.",
        {"type": "object", "properties": {}, "required": []},
        category="system",
    )
    def uptime():
        boot = time.time() - psutil.boot_time()
        return (
            f"Компьютер работает {int(boot // 86400)} д "
            f"{int((boot % 86400) // 3600)} ч "
            f"{int((boot % 3600) // 60)} мин."
        )
