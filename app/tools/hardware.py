import time

from app.tools.common import optional_import, powershell, resolve_path


def _wmi():
    return optional_import("wmi")


def register(registry):

    @registry.tool(
        "camera_list",
        "Список доступных камер.",
        {"type": "object", "properties": {}, "required": []},
        category="hardware",
    )
    def camera_list():
        cv2 = optional_import("cv2")
        if cv2 is None:
            return "Для работы с камерами установите opencv-python."
        found = []
        for index in range(10):
            capture = cv2.VideoCapture(index)
            if capture.isOpened():
                found.append(index)
            capture.release()
        return (
            "Индексы камер: " + ", ".join(map(str, found))
            if found
            else "Камеры не найдены."
        )

    @registry.tool(
        "camera_capture",
        "Сделать снимок с камеры.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "index": {"type": "integer"},
                "warmup": {"type": "number"},
            },
            "required": [],
        },
        category="hardware",
    )
    def camera_capture(path=None, index=0, warmup=0.5):
        cv2 = optional_import("cv2")
        if cv2 is None:
            return "Для работы с камерами установите opencv-python."
        capture = cv2.VideoCapture(int(index or 0))
        if not capture.isOpened():
            return f"Камера {index} недоступна."
        time.sleep(max(0, float(warmup or 0.5)))
        ok, frame = capture.read()
        capture.release()
        if not ok:
            return "Не удалось получить кадр."
        output = resolve_path(path or f"camera_{int(time.time())}.jpg")
        output.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(output), frame)
        return f"Снимок с камеры сохранён: {output}"

    @registry.tool(
        "camera_record",
        "Записать видео с камеры.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "index": {"type": "integer"},
                "duration": {"type": "number"},
                "fps": {"type": "number"},
            },
            "required": ["duration"],
        },
        category="hardware",
    )
    def camera_record(duration=5, path=None, index=0, fps=20):
        cv2 = optional_import("cv2")
        numpy = optional_import("numpy")
        if cv2 is None or numpy is None:
            return "Для записи видео установите opencv-python и numpy."
        capture = cv2.VideoCapture(int(index or 0))
        if not capture.isOpened():
            return f"Камера {index} недоступна."
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        output = resolve_path(path or f"camera_{int(time.time())}.mp4")
        output.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(
            str(output),
            cv2.VideoWriter_fourcc(*"mp4v"),
            float(fps or 20),
            (width, height),
        )
        frames = 0
        deadline = time.time() + max(1, float(duration or 5))
        while time.time() < deadline:
            ok, frame = capture.read()
            if not ok:
                break
            writer.write(frame)
            frames += 1
        capture.release()
        writer.release()
        return f"Видео с камеры: {output} ({frames} кадров)"

    @registry.tool(
        "serial_ports",
        "Список COM-портов.",
        {"type": "object", "properties": {}, "required": []},
        category="hardware",
    )
    def serial_ports():
        serial = optional_import("serial")
        if serial is None:
            return "Для работы с COM-портами установите pyserial."
        ports = []
        for port in serial.tools.list_ports.comports():
            ports.append(f"{port.device}: {port.description}")
        return "\n".join(ports) or "COM-порты не найдены."

    @registry.tool(
        "serial_send",
        "Отправить данные в COM-порт и прочитать ответ.",
        {
            "type": "object",
            "properties": {
                "port": {"type": "string"},
                "data": {"type": "string"},
                "baudrate": {"type": "integer"},
                "read": {"type": "boolean"},
                "timeout": {"type": "number"},
            },
            "required": ["port", "data"],
        },
        category="hardware",
        danger="confirm",
    )
    def serial_send(port, data, baudrate=9600, read=True, timeout=2):
        serial = optional_import("serial")
        if serial is None:
            return "Для работы с COM-портами установите pyserial."
        try:
            with serial.Serial(
                str(port),
                int(baudrate or 9600),
                timeout=float(timeout or 2),
            ) as connection:
                connection.write(str(data).encode("utf-8"))
                if not read:
                    return f"Отправлено в {port}."
                time.sleep(0.2)
                response = connection.read_all()
            return response.decode("utf-8", "replace") or "Ответа нет."
        except Exception as error:
            return f"Ошибка COM-порта: {error}"

    @registry.tool(
        "device_manager",
        "Список устройств Windows.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        category="hardware",
    )
    def device_manager(query=None, limit=100):
        output = powershell(
            "Get-PnpDevice | Select-Object Status, Class, FriendlyName, InstanceId | "
            "Format-Table -AutoSize | Out-String -Width 200",
            timeout=60,
        )
        if not query:
            return output[:12000]
        needle = str(query).lower()
        lines = [
            line
            for line in output.splitlines()
            if needle in line.lower()
        ]
        return "\n".join(lines[: int(limit or 100)]) or "Устройства не найдены."

    @registry.tool(
        "drivers_list",
        "Список драйверов.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        category="hardware",
    )
    def drivers_list(query=None, limit=100):
        script = (
            "Get-WmiObject Win32_PnPSignedDriver | "
            "Select-Object DeviceName, DriverVersion, DriverProviderName | "
            "Format-Table -AutoSize | Out-String -Width 200"
        )
        output = powershell(script, timeout=60)
        if not query:
            return output[:12000]
        needle = str(query).lower()
        return "\n".join(
            line
            for line in output.splitlines()
            if needle in line.lower()
        )[:12000] or "Драйверы не найдены."

    @registry.tool(
        "hardware_ids",
        "Идентификаторы оборудования (WMI).",
        {"type": "object", "properties": {}, "required": []},
        category="hardware",
    )
    def hardware_ids():
        wmi = _wmi()
        if wmi is None:
            return powershell(
                "Get-CimInstance Win32_ComputerSystemProduct | "
                "Select-Object UUID, IdentifyingNumber, Vendor, Name | "
                "Format-List | Out-String",
                timeout=30,
            )
        try:
            connection = wmi.WMI()
            product = connection.Win32_ComputerSystemProduct()[0]
            return (
                f"UUID: {product.UUID}\n"
                f"Серийный номер: {product.IdentifyingNumber}\n"
                f"Производитель: {product.Vendor}\n"
                f"Модель: {product.Name}"
            )
        except Exception as error:
            return f"Не удалось получить идентификаторы: {error}"

    @registry.tool(
        "motherboard_info",
        "Информация о материнской плате.",
        {"type": "object", "properties": {}, "required": []},
        category="hardware",
    )
    def motherboard_info():
        return powershell(
            "Get-CimInstance Win32_BaseBoard | "
            "Select-Object Manufacturer, Product, SerialNumber, Version | "
            "Format-List | Out-String",
            timeout=30,
        )

    @registry.tool(
        "bios_info",
        "Информация о BIOS.",
        {"type": "object", "properties": {}, "required": []},
        category="hardware",
    )
    def bios_info():
        return powershell(
            "Get-CimInstance Win32_BIOS | "
            "Select-Object Manufacturer, SMBIOSBIOSVersion, ReleaseDate, SerialNumber | "
            "Format-List | Out-String",
            timeout=30,
        )

    @registry.tool(
        "ram_modules",
        "Информация о модулях памяти.",
        {"type": "object", "properties": {}, "required": []},
        category="hardware",
    )
    def ram_modules():
        return powershell(
            "Get-CimInstance Win32_PhysicalMemory | "
            "Select-Object BankLabel, Capacity, Speed, Manufacturer, PartNumber | "
            "Format-Table -AutoSize | Out-String",
            timeout=30,
        )

    @registry.tool(
        "disk_drive_info",
        "Информация о физических дисках.",
        {"type": "object", "properties": {}, "required": []},
        category="hardware",
    )
    def disk_drive_info():
        return powershell(
            "Get-CimInstance Win32_DiskDrive | "
            "Select-Object Model, Size, MediaType, SerialNumber, InterfaceType, Status | "
            "Format-Table -AutoSize | Out-String",
            timeout=30,
        )

    @registry.tool(
        "pci_devices",
        "Список PCI-устройств.",
        {"type": "object", "properties": {}, "required": []},
        category="hardware",
    )
    def pci_devices():
        return powershell(
            "Get-CimInstance Win32_PnPEntity | "
            "Where-Object {$_.PNPClass -eq 'System' -or $_.PNPClass -eq 'Display'} | "
            "Select-Object Name, DeviceID, Status | "
            "Format-Table -AutoSize | Out-String",
            timeout=60,
        )

    @registry.tool(
        "fans_info",
        "Информация о вентиляторах.",
        {"type": "object", "properties": {}, "required": []},
        category="hardware",
    )
    def fans_info():
        return powershell(
            "Get-CimInstance Win32_Fan | "
            "Select-Object Name, DesiredSpeed, Status, ActiveCooling | "
            "Format-List | Out-String",
            timeout=30,
        )

    @registry.tool(
        "usb_eject",
        "Безопасно извлечь USB-устройство.",
        {
            "type": "object",
            "properties": {"drive": {"type": "string"}},
            "required": ["drive"],
        },
        category="hardware",
        danger="dangerous",
    )
    def usb_eject(drive):
        letter = str(drive).rstrip(":\\/")
        script = (
            "$drive = Get-WmiObject Win32_Volume -Filter \"DriveLetter='"
            + letter
            + ":'\"; "
            "$drive.Dismount($true, $false)"
        )
        return powershell(script, timeout=60)

    @registry.tool(
        "monitor_details",
        "Подробная информация о мониторах.",
        {"type": "object", "properties": {}, "required": []},
        category="hardware",
    )
    def monitor_details():
        return powershell(
            "Get-CimInstance Win32_DesktopMonitor | "
            "Select-Object Name, ScreenWidth, ScreenHeight, MonitorType, Availability | "
            "Format-Table -AutoSize | Out-String",
            timeout=30,
        )
