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

class VPNLogic:
    def __init__(self, config):
        self.config = config
        # Твои рабочие источники
        self.sources = [
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
            "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/channels/protocols/trojan"
        ]

    def scrape_keys(self, callback_log=None):
        all_keys = []
        lock = threading.Lock()
        
        def fetch_source(url):
            try:
                resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    raw = resp.text.strip()
                    try:
                        # Твой метод декодирования Base64
                        missing_padding = len(raw) % 4
                        if missing_padding:
                            raw += "=" * (4 - missing_padding)
                        decoded = base64.b64decode(raw).decode("utf-8", errors="ignore")
                        if any(p in decoded for p in ("vless://", "trojan://")):
                            raw = decoded
                    except: pass
                    
                    lines = [l.strip() for l in raw.splitlines() if l.strip()]
                    valid = [l for l in lines if l.startswith("vless://") or l.startswith("trojan://")]
                    
                    with lock:
                        all_keys.extend(valid)
            except: pass

        if callback_log: callback_log(f"Скачиваю ключи...")
        threads = []
        for url in self.sources:
            t = threading.Thread(target=fetch_source, args=(url,))
            t.start()
            threads.append(t)
        for t in threads: t.join()
            
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
                # Твой метод парсинга через регулярку
                match = re.search(r"@([^:/?#]+):(\d+)", link)
                if not match: continue
                host, port = match.group(1), int(match.group(2))
                name = unquote(link.split("#")[-1]) if "#" in link else "Unnamed"
                
                is_reality = "reality" in link.lower() or "flow=xtls" in link.lower()
                
                filtered.append({
                    "link": link,
                    "protocol": "reality" if is_reality else ("vless" if "vless" in link else "trojan"),
                    "host": host, "port": port, "name": name,
                    "priority": 0 if is_reality else (1 if "vless" in link else 2)
                })
            except: continue
        
        # Твоя сортировка: Reality > VLESS > Trojan
        filtered.sort(key=lambda x: x["priority"])
        return filtered[:200]

    def test_key(self, key_data):
        try:
            sock = socket.create_connection((key_data["host"], key_data["port"]), timeout=2.0)
            sock.close()
            return key_data
        except: return None

    def check_chatgpt_via_proxy(self, proxy_host="127.0.0.1", proxy_port=12334):
        """ТВОЯ ОБЯЗАТЕЛЬНАЯ ПРОВЕРКА CHATGPT"""
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
                allow_redirects=True
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
        if not raw_keys: return []
        
        tested = []
        lock = threading.Lock()
        def worker(k):
            res = self.test_key(k)
            if res:
                with lock: tested.append(res)
        
        threads = []
        # Проверяем первые 100 ключей на пинг
        for k in raw_keys[:100]:
            t = threading.Thread(target=worker, args=(k,))
            t.start()
            threads.append(t)
        for t in threads: t.join()
        
        # Твоя сортировка по приоритету протоколов
        tested.sort(key=lambda x: x["priority"])
        return tested
