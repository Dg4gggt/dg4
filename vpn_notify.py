"""
Тонкая обёртка над winotify для тостов Windows.
Работает только на Windows. На других платформах — no-op + лог в stdout.
"""
import logging
import os
import sys

logger = logging.getLogger("dg4VPN.Notify")

try:
    from winotify import Notification, audio
    _WINOTIFY_OK = True
except Exception as _e:
    _WINOTIFY_OK = False
    Notification = None
    audio = None
    if sys.platform.startswith("win"):
        logger.warning(
            "winotify не установлена. Установите 'pip install winotify' для нативных уведомлений."
        )

_APP_ID = "dg4VPN"


def _flag(country):
    if not country or country == "??":
        return ""
    try:
        return "".join(chr(127397 + ord(c)) for c in country.upper())
    except Exception:
        return ""


_COUNTRY_NAMES = {
    "DE": "Германия", "NL": "Нидерланды", "US": "США", "GB": "Великобритания",
    "FR": "Франция", "FI": "Финляндия", "SE": "Швеция", "NO": "Норвегия",
    "PL": "Польша", "UA": "Украина", "TR": "Турция", "JP": "Япония",
    "SG": "Сингапур", "HK": "Гонконг", "KR": "Южная Корея", "CA": "Канада",
    "AU": "Австралия", "BR": "Бразилия", "AT": "Австрия", "CH": "Швейцария",
    "BE": "Бельгия", "DK": "Дания", "ES": "Испания", "IT": "Италия",
    "EE": "Эстония", "LV": "Латвия", "LT": "Литва", "CZ": "Чехия",
    "RO": "Румыния", "BG": "Болгария", "IL": "Израиль", "AE": "ОАЭ",
    "AM": "Армения", "KZ": "Казахстан", "MD": "Молдова", "RS": "Сербия",
    "IN": "Индия", "ID": "Индонезия", "MY": "Малайзия", "PH": "Филиппины",
    "VN": "Вьетнам", "MX": "Мексика", "AR": "Аргентина", "CL": "Чили",
    "ZA": "ЮАР", "EG": "Египет",
}


def country_name(code):
    if not code:
        return "—"
    return _COUNTRY_NAMES.get(code.upper(), code.upper())


class ToastNotifier:
    """Маленькая обёртка — никаких сложных колбэков, только текст + значки."""

    enabled = True  # глобальный переключатель из настроек

    @classmethod
    def set_enabled(cls, value: bool):
        cls.enabled = bool(value)

    @classmethod
    def _send(cls, title, msg, sound=None):
        if not cls.enabled:
            return
        if not _WINOTIFY_OK:
            logger.info(f"[toast skipped] {title} — {msg}")
            return
        try:
            n = Notification(app_id=_APP_ID, title=title, msg=msg, duration="short")
            if sound is not None:
                n.set_audio(sound, loop=False)
            n.show()
        except Exception as e:
            logger.debug(f"toast error: {e}")

    @classmethod
    def connected(cls, country, latency_ms):
        flag = _flag(country)
        name = country_name(country)
        title = "dg4VPN"
        latency_part = f" ({latency_ms} ms)" if latency_ms else ""
        msg = f"Успешно подключено к узлу {name} {flag}{latency_part}".strip()
        cls._send(title, msg, sound=audio.Default if audio else None)

    @classmethod
    def disconnected(cls):
        cls._send("dg4VPN", "Соединение разорвано")

    @classmethod
    def error(cls, text):
        cls._send("dg4VPN", f"Ошибка: {text}", sound=audio.Reminder if audio else None)

    @classmethod
    def paused(cls):
        cls._send("dg4VPN", "Поставлено на паузу")

    @classmethod
    def info(cls, text):
        cls._send("dg4VPN", text)
