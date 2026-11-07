import email
import imaplib
import os
import smtplib
import ssl
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from app.tools.common import optional_import, resolve_path


def _env(name, default=None):
    return os.environ.get(name) or default


def register(registry):

    @registry.tool(
        "email_send",
        "Отправить письмо через SMTP.",
        {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "attachments": {"type": "array"},
                "cc": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
        category="communication",
        danger="confirm",
        tags=("почта", "письмо", "email", "mail", "smtp"),
    )
    def email_send(to, subject, body, attachments=None, cc=None):
        host = _env("JARVIS_SMTP_HOST")
        user = _env("JARVIS_SMTP_USER")
        password = _env("JARVIS_SMTP_PASSWORD")
        if not host or not user or not password:
            return (
                "Задайте JARVIS_SMTP_HOST, JARVIS_SMTP_USER и "
                "JARVIS_SMTP_PASSWORD в окружении."
            )
        port = int(_env("JARVIS_SMTP_PORT", "587"))
        message = MIMEMultipart()
        message["From"] = user
        message["To"] = str(to)
        message["Subject"] = str(subject)
        if cc:
            message["Cc"] = str(cc)
        message.attach(MIMEText(str(body), "plain", "utf-8"))
        for item in attachments or []:
            path = resolve_path(item, must_exist=True)
            from email import encoders
            from email.mime.base import MIMEBase

            part = MIMEBase("application", "octet-stream")
            part.set_payload(path.read_bytes())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{path.name}"',
            )
            message.attach(part)
        recipients = [item.strip() for item in str(to).split(",") if item.strip()]
        if cc:
            recipients.extend(
                item.strip() for item in str(cc).split(",") if item.strip()
            )
        try:
            with smtplib.SMTP(str(host), port, timeout=30) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(str(user), str(password))
                server.sendmail(str(user), recipients, message.as_string())
        except Exception as error:
            return f"Не удалось отправить письмо: {error}"
        return f"Письмо отправлено: {', '.join(recipients)}"

    @registry.tool(
        "email_inbox",
        "Показать последние письма через IMAP.",
        {
            "type": "object",
            "properties": {
                "limit": {"type": "integer"},
                "mailbox": {"type": "string"},
            },
            "required": [],
        },
        category="communication",
        tags=("почта", "письма", "email", "mail", "imap"),
    )
    def email_inbox(limit=10, mailbox="INBOX"):
        host = _env("JARVIS_IMAP_HOST")
        user = _env("JARVIS_IMAP_USER") or _env("JARVIS_SMTP_USER")
        password = _env("JARVIS_IMAP_PASSWORD") or _env("JARVIS_SMTP_PASSWORD")
        if not host or not user or not password:
            return (
                "Задайте JARVIS_IMAP_HOST, JARVIS_IMAP_USER и "
                "JARVIS_IMAP_PASSWORD в окружении."
            )
        try:
            client = imaplib.IMAP4_SSL(str(host))
            client.login(str(user), str(password))
            client.select(str(mailbox or "INBOX"))
            _, data = client.search(None, "ALL")
            ids = data[0].split()[-int(limit or 10) :]
            lines = []
            for message_id in reversed(ids):
                _, payload = client.fetch(message_id, "(RFC822)")
                message = email.message_from_bytes(payload[0][1])
                subject = str(message.get("Subject", ""))
                decoded = decode_header(subject)
                subject = "".join(
                    part.decode(encoding or "utf-8", "replace")
                    if isinstance(part, bytes)
                    else part
                    for part, encoding in decoded
                )
                lines.append(
                    f"{message.get('From')} | {subject} | {message.get('Date')}"
                )
            client.logout()
            return "\n".join(lines) or "Писем нет."
        except Exception as error:
            return f"Не удалось прочитать почту: {error}"

    @registry.tool(
        "telegram_send",
        "Отправить сообщение в Telegram через бота.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "chat_id": {"type": "string"},
            },
            "required": ["text"],
        },
        category="communication",
    )
    def telegram_send(text, chat_id=None):
        token = _env("JARVIS_TELEGRAM_BOT_TOKEN")
        chat = chat_id or _env("JARVIS_TELEGRAM_CHAT_ID")
        if not token or not chat:
            return (
                "Задайте JARVIS_TELEGRAM_BOT_TOKEN и "
                "JARVIS_TELEGRAM_CHAT_ID."
            )
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": str(text)},
                timeout=15,
            )
            response.raise_for_status()
        except Exception as error:
            return f"Telegram-ошибка: {error}"
        return "Сообщение отправлено в Telegram."

    @registry.tool(
        "discord_send",
        "Отправить сообщение в Discord через вебхук.",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        category="communication",
    )
    def discord_send(text):
        webhook = _env("JARVIS_DISCORD_WEBHOOK")
        if not webhook:
            return "Задайте JARVIS_DISCORD_WEBHOOK."
        try:
            response = requests.post(
                webhook,
                json={"content": str(text)},
                timeout=15,
            )
            response.raise_for_status()
        except Exception as error:
            return f"Discord-ошибка: {error}"
        return "Сообщение отправлено в Discord."

    @registry.tool(
        "slack_send",
        "Отправить сообщение в Slack через вебхук.",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        category="communication",
    )
    def slack_send(text):
        webhook = _env("JARVIS_SLACK_WEBHOOK")
        if not webhook:
            return "Задайте JARVIS_SLACK_WEBHOOK."
        try:
            response = requests.post(
                webhook,
                json={"text": str(text)},
                timeout=15,
            )
            response.raise_for_status()
        except Exception as error:
            return f"Slack-ошибка: {error}"
        return "Сообщение отправлено в Slack."

    @registry.tool(
        "whatsapp_send",
        "Отправить сообщение в WhatsApp через WhatsApp Web.",
        {
            "type": "object",
            "properties": {
                "phone": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["phone", "text"],
        },
        category="communication",
        danger="confirm",
    )
    def whatsapp_send(phone, text):
        import urllib.parse
        import webbrowser

        number = "".join(character for character in str(phone) if character.isdigit())
        url = (
            f"https://wa.me/{number}?text="
            + urllib.parse.quote(str(text))
        )
        webbrowser.open(url, new=2)
        return f"Открыт WhatsApp Web для {number}."

    @registry.tool(
        "sms_send",
        "Открыть SMS-ссылку для отправки сообщения.",
        {
            "type": "object",
            "properties": {
                "phone": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["phone", "text"],
        },
        category="communication",
    )
    def sms_send(phone, text):
        import urllib.parse
        import webbrowser

        url = f"sms:{phone}?body={urllib.parse.quote(str(text))}"
        webbrowser.open(url)
        return f"Открыто SMS для {phone}."

    @registry.tool(
        "notification_send",
        "Показать уведомление Windows.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["message"],
        },
        category="communication",
    )
    def notification_send(message, title="JARVIS"):
        winotify = optional_import("winotify")
        if winotify is not None:
            try:
                toast = winotify.Notification(
                    app_id="JARVIS",
                    title=str(title),
                    msg=str(message),
                )
                toast.show()
                return "Уведомление показано."
            except Exception:
                pass
        from app.tools.common import notify

        notify(str(title), str(message))
        return "Уведомление показано."

    @registry.tool(
        "meeting_open",
        "Открыть ссылку на встречу.",
        {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "enum": ["zoom", "teams", "meet", "webex"],
                },
                "url": {"type": "string"},
            },
            "required": [],
        },
        category="communication",
    )
    def meeting_open(service="zoom", url=None):
        import webbrowser

        if url:
            webbrowser.open(str(url), new=2)
            return f"Открыта встреча: {url}"
        pages = {
            "zoom": "https://zoom.us/join",
            "teams": "https://teams.microsoft.com",
            "meet": "https://meet.google.com",
            "webex": "https://www.webex.com",
        }
        webbrowser.open(pages.get(service, pages["zoom"]), new=2)
        return f"Открыт сервис встреч: {service}"
