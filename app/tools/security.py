import base64
import hashlib
import hmac
import os
import secrets
import string
import time

from app.tools.common import optional_import, resolve_path


def _fernet():
    module = optional_import("cryptography.fernet")
    return getattr(module, "Fernet", None) if module else None


def _derive_key(password, salt):
    cryptography = optional_import("cryptography.hazmat.primitives.kdf.pbkdf2")
    hashes = optional_import("cryptography.hazmat.primitives.hashes")
    if cryptography is None or hashes is None:
        return None
    kdf = cryptography.PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=390000,
    )
    return base64.urlsafe_b64encode(kdf.derive(str(password).encode("utf-8")))


def register(registry):

    @registry.tool(
        "password_generate",
        "Сгенерировать надёжный пароль.",
        {
            "type": "object",
            "properties": {
                "length": {"type": "integer"},
                "symbols": {"type": "boolean"},
                "count": {"type": "integer"},
            },
            "required": [],
        },
        category="security",
    )
    def password_generate(length=20, symbols=True, count=1):
        alphabet = string.ascii_letters + string.digits
        if symbols:
            alphabet += "!@#$%^&*()-_=+[]{};:,.?"
        length = max(8, min(int(length or 20), 256))
        return "\n".join(
            "".join(secrets.choice(alphabet) for _ in range(length))
            for _ in range(max(1, min(int(count or 1), 50)))
        )

    @registry.tool(
        "password_strength",
        "Оценить сложность пароля.",
        {
            "type": "object",
            "properties": {"password": {"type": "string"}},
            "required": ["password"],
        },
        category="security",
    )
    def password_strength(password):
        value = str(password or "")
        score = 0
        if len(value) >= 8:
            score += 1
        if len(value) >= 12:
            score += 1
        if len(value) >= 16:
            score += 1
        if any(character.islower() for character in value):
            score += 1
        if any(character.isupper() for character in value):
            score += 1
        if any(character.isdigit() for character in value):
            score += 1
        if any(not character.isalnum() for character in value):
            score += 1
        entropy = len(value) * (score + 1)
        labels = ["очень слабый", "слабый", "средний", "хороший", "сильный", "очень сильный"]
        index = min(len(labels) - 1, score // 2)
        return (
            f"Оценка: {score}/7 ({labels[index]})\n"
            f"Длина: {len(value)}\n"
            f"Примерная энтропия: {entropy} бит"
        )

    @registry.tool(
        "password_pwned",
        "Проверить пароль в утечках Have I Been Pwned.",
        {
            "type": "object",
            "properties": {"password": {"type": "string"}},
            "required": ["password"],
        },
        category="security",
    )
    def password_pwned(password):
        import requests

        digest = hashlib.sha1(str(password).encode("utf-8")).hexdigest().upper()
        prefix, suffix = digest[:5], digest[5:]
        try:
            response = requests.get(
                f"https://api.pwnedpasswords.com/range/{prefix}",
                timeout=15,
            )
            response.raise_for_status()
        except Exception as error:
            return f"Не удалось проверить: {error}"
        for line in response.text.splitlines():
            parts = line.split(":")
            if len(parts) == 2 and parts[0] == suffix:
                return f"Пароль найден в утечках: {parts[1]} раз."
        return "Пароль не найден в известных утечках."

    @registry.tool(
        "text_encrypt",
        "Зашифровать текст паролем.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "password": {"type": "string"},
            },
            "required": ["text", "password"],
        },
        category="security",
    )
    def text_encrypt(text, password):
        Fernet = _fernet()
        if Fernet is None:
            return "Для шифрования установите cryptography."
        salt = os.urandom(16)
        key = _derive_key(password, salt)
        if key is None:
            return "Для шифрования установите cryptography."
        token = Fernet(key).encrypt(str(text).encode("utf-8"))
        return base64.b64encode(salt).decode("ascii") + ":" + token.decode("ascii")

    @registry.tool(
        "text_decrypt",
        "Расшифровать текст паролем.",
        {
            "type": "object",
            "properties": {
                "token": {"type": "string"},
                "password": {"type": "string"},
            },
            "required": ["token", "password"],
        },
        category="security",
    )
    def text_decrypt(token, password):
        Fernet = _fernet()
        if Fernet is None:
            return "Для шифрования установите cryptography."
        try:
            salt_b64, payload = str(token).split(":", 1)
            salt = base64.b64decode(salt_b64)
            key = _derive_key(password, salt)
            return Fernet(key).decrypt(payload.encode("ascii")).decode("utf-8")
        except Exception as error:
            return f"Не удалось расшифровать: {error}"

    @registry.tool(
        "security_file_encrypt",
        "Зашифровать файл паролем.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "password": {"type": "string"},
                "target": {"type": "string"},
            },
            "required": ["path", "password"],
        },
        category="security",
        danger="confirm",
    )
    def file_encrypt(path, password, target=None):
        Fernet = _fernet()
        if Fernet is None:
            return "Для шифрования установите cryptography."
        source = resolve_path(path, must_exist=True)
        salt = os.urandom(16)
        key = _derive_key(password, salt)
        token = Fernet(key).encrypt(source.read_bytes())
        output = resolve_path(target or str(source) + ".enc")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(base64.b64encode(salt) + b"\n" + token)
        return f"Файл зашифрован: {output}"

    @registry.tool(
        "security_file_decrypt",
        "Расшифровать файл паролем.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "password": {"type": "string"},
                "target": {"type": "string"},
            },
            "required": ["path", "password"],
        },
        category="security",
        danger="confirm",
    )
    def file_decrypt(path, password, target=None):
        Fernet = _fernet()
        if Fernet is None:
            return "Для шифрования установите cryptography."
        source = resolve_path(path, must_exist=True)
        try:
            salt_b64, token = source.read_bytes().split(b"\n", 1)
            salt = base64.b64decode(salt_b64)
            key = _derive_key(password, salt)
            data = Fernet(key).decrypt(token)
        except Exception as error:
            return f"Не удалось расшифровать: {error}"
        default = str(source)
        if default.endswith(".enc"):
            default = default[:-4]
        output = resolve_path(target or default)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        return f"Файл расшифрован: {output}"

    @registry.tool(
        "keyring_store",
        "Сохранить секрет в хранилище Windows.",
        {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "username": {"type": "string"},
                "secret": {"type": "string"},
            },
            "required": ["service", "username", "secret"],
        },
        category="security",
        danger="confirm",
    )
    def keyring_store(service, username, secret):
        keyring = optional_import("keyring")
        if keyring is None:
            return "Для хранилища секретов установите keyring."
        keyring.set_password(str(service), str(username), str(secret))
        return "Секрет сохранён."

    @registry.tool(
        "keyring_get",
        "Получить секрет из хранилища Windows.",
        {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "username": {"type": "string"},
            },
            "required": ["service", "username"],
        },
        category="security",
    )
    def keyring_get(service, username):
        keyring = optional_import("keyring")
        if keyring is None:
            return "Для хранилища секретов установите keyring."
        value = keyring.get_password(str(service), str(username))
        return value or "Секрет не найден."

    @registry.tool(
        "keyring_delete",
        "Удалить секрет из хранилища Windows.",
        {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "username": {"type": "string"},
            },
            "required": ["service", "username"],
        },
        category="security",
        danger="dangerous",
    )
    def keyring_delete(service, username):
        keyring = optional_import("keyring")
        if keyring is None:
            return "Для хранилища секретов установите keyring."
        keyring.delete_password(str(service), str(username))
        return "Секрет удалён."

    @registry.tool(
        "totp_generate",
        "Сгенерировать код двухфакторной аутентификации.",
        {
            "type": "object",
            "properties": {"secret": {"type": "string"}},
            "required": ["secret"],
        },
        category="security",
    )
    def totp_generate(secret):
        pyotp = optional_import("pyotp")
        if pyotp is None:
            return "Для TOTP установите pyotp."
        try:
            totp = pyotp.TOTP(str(secret).replace(" ", ""))
            return f"Код: {totp.now()} (осталось {totp.interval - int(time.time()) % totp.interval} c)"
        except Exception as error:
            return f"Ошибка TOTP: {error}"

    @registry.tool(
        "qr_generate",
        "Создать QR-код.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["text"],
        },
        category="security",
    )
    def qr_generate(text, path=None):
        qrcode = optional_import("qrcode")
        if qrcode is None:
            return "Для QR-кодов установите qrcode."
        output = resolve_path(path or f"qr_{int(time.time())}.png")
        output.parent.mkdir(parents=True, exist_ok=True)
        image = qrcode.make(str(text))
        image.save(str(output))
        return f"QR-код сохранён: {output}"

    @registry.tool(
        "qr_read",
        "Распознать QR-код на изображении.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        category="security",
    )
    def qr_read(path):
        cv2 = optional_import("cv2")
        if cv2 is None:
            return "Для чтения QR установите opencv-python."
        image = cv2.imread(str(resolve_path(path, must_exist=True)))
        detector = cv2.QRCodeDetector()
        value, _, _ = detector.detectAndDecode(image)
        return value or "QR-код не найден."

    @registry.tool(
        "secure_random",
        "Сгенерировать криптостойкое случайное число.",
        {
            "type": "object",
            "properties": {
                "min": {"type": "integer"},
                "max": {"type": "integer"},
            },
            "required": [],
        },
        category="security",
    )
    def secure_random(**kwargs):
        low = int(kwargs.get("min", 0) or 0)
        high = int(kwargs.get("max", 1000000) or 1000000)
        return str(secrets.randbelow(max(1, high - low)) + low)

    @registry.tool(
        "file_integrity",
        "Проверить целостность файла по хешу.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "expected": {"type": "string"},
                "algorithm": {
                    "type": "string",
                    "enum": ["md5", "sha1", "sha256", "sha512"],
                },
            },
            "required": ["path"],
        },
        category="security",
    )
    def file_integrity(path, expected=None, algorithm="sha256"):
        target = resolve_path(path, must_exist=True)
        digest = hashlib.new(str(algorithm or "sha256"))
        with open(target, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if expected:
            return (
                f"Хеш совпадает: {actual}"
                if hmac.compare_digest(actual.lower(), str(expected).lower())
                else f"Хеш НЕ совпадает: {actual}"
            )
        return actual
