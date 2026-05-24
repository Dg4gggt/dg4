"""
Управление настройками dg4VPN.

Хранит конфиг в settings.json рядом со скриптом. Если файла нет —
создаёт его из дефолтов. Любые правки делаются через UI, а не правкой
словаря CONFIG в коде.
"""
import json
import os
import logging

logger = logging.getLogger("dg4VPN.Settings")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(_BASE_DIR, "settings.json")

DEFAULT_SOURCES = [
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub1.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub2.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub3.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub4.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub5.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub6.txt",
    "https://raw.githubusercontent.com/MhdiTahmasbi/v2ray/main/sub.txt",
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/base64/mix",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge_base64.txt",
    "https://raw.githubusercontent.com/peasoft/NoMoreVPN/master/list.txt",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
    "https://raw.githubusercontent.com/resasetan/v2ray-collector/refs/heads/main/sub/mix",
    "https://raw.githubusercontent.com/coldwater-10/V2rayCollector/main/sub/base64/mix",
    "https://raw.githubusercontent.com/mahdibland/ShadowsocksAggregator/master/Eternity.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/All_Configs_Sub.txt",
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/base64/reality",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/splitted/vless.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/splitted/trojan.txt",
    "https://raw.githubusercontent.com/coldwater-10/V2rayCollector/main/sub/base64/vless",
    "https://raw.githubusercontent.com/coldwater-10/V2rayCollector/main/sub/base64/trojan",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Sub1.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Sub2.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Sub3.txt",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/splitted/vless",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/splitted/trojan",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/channels/protocols/vless",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/channels/protocols/trojan",
]

DEFAULTS = {
    "hotkey": "ctrl+alt+b",
    "pause_hotkey": "ctrl+alt+p",
    "regions_hotkey": "ctrl+alt+r",
    "excluded_countries": ["RU", "BY"],
    "priority_protocols": ["reality", "vless", "trojan", "shadowsocks"],
    "hiddify_cli": os.path.join(_BASE_DIR, "vpn_launcher", "HiddifyCli.exe"),
    "sources": DEFAULT_SOURCES,
    "custom_sources": [],
    "custom_keys": [],
    "notifications_enabled": True,
    "background_scan_enabled": True,
    "max_background_tests": 60,
}


class SettingsManager:
    """Загрузка/сохранение конфига и точечные обновления."""

    @staticmethod
    def load():
        config = json.loads(json.dumps(DEFAULTS))  # deep copy
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                for k, v in saved.items():
                    config[k] = v
            except Exception as e:
                logger.warning(f"Не удалось прочитать settings.json: {e}. Использую дефолты.")
        else:
            SettingsManager.save(config)
        return config

    @staticmethod
    def save(config):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Не удалось сохранить settings.json: {e}")
            return False

    @staticmethod
    def merge_and_save(current, updates):
        for k, v in updates.items():
            current[k] = v
        SettingsManager.save(current)
        return current
