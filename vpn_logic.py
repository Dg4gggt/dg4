import requests
import base64
import json
import re
import time
import socket
import threading
from urllib.parse import urlparse, unquote
import logging

logger = logging.getLogger("CyberVPN.Logic")

# Какие схемы умеем распознавать
SCHEME_PROTOCOLS = {
    "vless://": "vless",
    "trojan://": "trojan",
    "ss://": "shadowsocks",
    "vmess://": "vmess",
}

PROTOCOL_PRIORITY = {
    "reality": 0,
    "vless": 1,
    "trojan": 2,
    "shadowsocks": 3,
    "vmess": 4,
}


def _detect_protocol(link):
    lower = link.lower()
    if "reality" in lower or "flow=xtls" in lower:
        return "reality"
    for prefix, proto in SCHEME_PROTOCOLS.items():
        if lower.startswith(prefix):
            return proto
    return None


class VPNLogic:
    def __init__(self, config):
        self.config = config
        self.refresh_from_config()

    # ── динамическая конфигурация ────────────────
    def refresh_from_config(self):
        """Перечитать sources/custom_sources/custom_keys/protocols из CONFIG."""
        cfg = self.config or {}
        sources = list(cfg.get("sources") or [])
        sources.extend(cfg.get("custom_sources") or [])
        # снять дубликаты с сохранением порядка
        seen = set()
        self.sources = []
        for s in sources:
            if s and s not in seen:
                seen.add(s)
                self.sources.append(s)

        protos = cfg.get("priority_protocols") or ["reality", "vless", "trojan"]
        self.allowed_protocols = {p.lower() for p in protos}
        self.custom_keys = list(cfg.get("custom_keys") or [])

    # ── получение ключей ─────────────────────────
    def scrape_keys(self, callback_log=None):
        all_keys = []
        lock = threading.Lock()

        def fetch_source(url):
            try:
                resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    raw = resp.text.strip()
                    try:
                        missing_padding = len(raw) % 4
                        if missing_padding:
                            raw += "=" * (4 - missing_padding)
                        decoded = base64.b64decode(raw).decode("utf-8", errors="ignore")
                        if any(p in decoded for p in SCHEME_PROTOCOLS):
                            raw = decoded
                    except Exception:
                        pass

                    lines = [l.strip() for l in raw.splitlines() if l.strip()]
                    valid = [l for l in lines if any(l.startswith(p) for p in SCHEME_PROTOCOLS)]

                    with lock:
                        all_keys.extend(valid)
            except Exception:
                pass

        if callback_log:
            callback_log("Скачиваю ключи...")

        threads = []
        for url in self.sources:
            t = threading.Thread(target=fetch_source, args=(url,))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

        # подмешиваем пользовательские ключи
        for k in self.custom_keys:
            if any(k.startswith(p) for p in SCHEME_PROTOCOLS):
                all_keys.append(k)

        seen = set()
        unique = []
        for k in all_keys:
            if k not in seen:
                seen.add(k)
                unique.append(k)

        return self.filter_and_parse(unique)

    def filter_and_parse(self, links):
        filtered = []
        for link in links:
            try:
                protocol = _detect_protocol(link)
                if protocol is None:
                    continue
                # фильтр по разрешённым протоколам (reality всегда пропускаем — это разновидность vless)
                check_proto = "vless" if protocol == "reality" else protocol
                if check_proto not in self.allowed_protocols and protocol not in self.allowed_protocols:
                    continue

                host, port = self._extract_host_port(link, protocol)
                if not host or not port:
                    continue

                name = unquote(link.split("#")[-1]) if "#" in link else "Unnamed"

                filtered.append({
                    "link": link,
                    "protocol": protocol,
                    "host": host,
                    "port": port,
                    "name": name,
                    "priority": PROTOCOL_PRIORITY.get(protocol, 9),
                })
            except Exception:
                continue

        filtered.sort(key=lambda x: x["priority"])
        return filtered[:300]

    def _extract_host_port(self, link, protocol):
        # vmess:// требует base64-декодирования JSON
        if protocol == "vmess":
            try:
                raw = link.split("://", 1)[1].split("#", 1)[0]
                missing = len(raw) % 4
                if missing:
                    raw += "=" * (4 - missing)
                data = json.loads(base64.b64decode(raw).decode("utf-8", errors="ignore"))
                host = data.get("add") or data.get("address") or ""
                port = int(data.get("port") or 0)
                return host, port
            except Exception:
                return None, None

        # ss:// форматы: ss://base64@host:port или ss://method:pass@host:port
        match = re.search(r"@([^:/?#]+):(\d+)", link)
        if match:
            return match.group(1), int(match.group(2))

        # ss://base64-of-everything?... — попробуем декодировать
        if protocol == "shadowsocks":
            try:
                body = link.split("://", 1)[1].split("#", 1)[0].split("?", 1)[0]
                missing = len(body) % 4
                if missing:
                    body += "=" * (4 - missing)
                decoded = base64.b64decode(body).decode("utf-8", errors="ignore")
                m = re.search(r"@([^:/?#]+):(\d+)", decoded) or re.search(r":(\d+)$", decoded)
                if m and "@" in decoded:
                    return m.group(1), int(m.group(2))
            except Exception:
                pass
        return None, None

    def test_key(self, key_data):
        try:
            sock = socket.create_connection((key_data["host"], key_data["port"]), timeout=2.0)
            sock.close()
            return key_data
        except Exception:
            return None

    def check_chatgpt_via_proxy(self, proxy_host="127.0.0.1", proxy_port=12334):
        """Обязательная проверка ChatGPT через прокси."""
        proxies = {
            "http": f"socks5h://{proxy_host}:{proxy_port}",
            "https": f"socks5h://{proxy_host}:{proxy_port}",
        }
        try:
            resp = requests.get(
                "https://chatgpt.com/",
                proxies=proxies,
                timeout=12,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                allow_redirects=True,
            )
            if resp.status_code == 403:
                return False, "403 Forbidden"

            text_lower = resp.text.lower()
            if "vpn" in text_lower and "turn" in text_lower:
                return False, "Detected VPN"

            return True, f"OK ({resp.status_code})"
        except Exception as e:
            return False, str(e)

    def get_best_keys(self, callback_log=None):
        raw_keys = self.scrape_keys(callback_log=callback_log)
        if not raw_keys:
            return []

        tested = []
        lock = threading.Lock()

        def worker(k):
            res = self.test_key(k)
            if res:
                with lock:
                    tested.append(res)

        threads = []
        for k in raw_keys[:120]:
            t = threading.Thread(target=worker, args=(k,))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

        # отсортируем по приоритету протоколов
        tested.sort(key=lambda x: x["priority"])
        # вернём всё проверенное + хвост с непроверенными (для фонового добивания)
        used = {k["link"] for k in tested}
        remaining = [k for k in raw_keys if k["link"] not in used]
        return tested + remaining
