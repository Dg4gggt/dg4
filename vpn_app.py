import sys
import os
import threading
import time
import socket
import signal
import atexit
import logging
import subprocess
import ctypes
import math
import json
import requests

try:
    import psutil
except ImportError:
    psutil = None

# ──────────────────────────────────────────────
#  УПРАВЛЕНИЕ СИСТЕМОЙ (ПРОКСИ И ПРОЦЕССЫ)
# ──────────────────────────────────────────────
class SystemManager:
    @staticmethod
    def enable_blur(hwnd, color=0x20100A32):
        """Включает нативный эффект размытия Windows (Acrylic/BlurBehind)."""
        try:
            from ctypes import windll, c_int, byref, Structure, sizeof, POINTER

            class AccentPolicy(Structure):
                _fields_ = [
                    ('AccentState', c_int),
                    ('AccentFlags', c_int),
                    ('GradientColor', c_int),
                    ('AnimationId', c_int),
                ]

            class WindowCompositionAttributeData(Structure):
                _fields_ = [
                    ('Attribute', c_int),
                    ('Data', POINTER(AccentPolicy)),
                    ('SizeOfData', c_int),
                ]

            accent = AccentPolicy()
            accent.AccentState = 3
            accent.GradientColor = color

            data = WindowCompositionAttributeData()
            data.Attribute = 19
            data.SizeOfData = sizeof(accent)
            data.Data = byref(accent)

            windll.user32.SetWindowCompositionAttribute(int(hwnd), byref(data))
        except Exception as e:
            logger.debug(f"enable_blur error: {e}")

    @staticmethod
    def set_proxy(enable=True, host="127.0.0.1", port=12334):
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1 if enable else 0)
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{host}:{port}")

            ctypes.windll.Wininet.InternetSetOptionW(0, 39, 0, 0)
            ctypes.windll.Wininet.InternetSetOptionW(0, 37, 0, 0)
            logger.info(f"Системный прокси {'включен' if enable else 'выключен'}")
        except Exception as e:
            logger.error(f"Ошибка при настройке прокси: {e}")

    @staticmethod
    def kill_hiddify():
        try:
            subprocess.run(["taskkill", "/F", "/IM", "HiddifyCli.exe"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


def _emergency_proxy_off():
    SystemManager.set_proxy(False)
    SystemManager.kill_hiddify()


atexit.register(_emergency_proxy_off)
for _sig in (signal.SIGTERM, signal.SIGINT, signal.SIGABRT):
    try:
        signal.signal(_sig, lambda s, f: (_emergency_proxy_off(), sys.exit(0)))
    except (OSError, ValueError):
        pass


def set_system_proxy(enable=True, host="127.0.0.1", port=12334):
    SystemManager.set_proxy(enable, host, port)


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ──────────────────────────────────────────────
#  ЛОГИРОВАНИЕ
# ──────────────────────────────────────────────
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vpn.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(log_file, encoding='utf-8'), logging.StreamHandler()]
)
logger = logging.getLogger("dg4VPN")

try:
    import keyboard
except ImportError:
    keyboard = None

try:
    from PIL import Image, ImageDraw
    import pystray
    from pystray import MenuItem as item
except ImportError:
    pystray = None

from vpn_logic import VPNLogic
from vpn_settings import SettingsManager
from vpn_notify import ToastNotifier, country_name

# ──────────────────────────────────────────────
#  PyQt6
# ──────────────────────────────────────────────
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QTextEdit, QFrame,
    QDialog, QListWidget, QListWidgetItem, QTabWidget,
    QLineEdit, QCheckBox, QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QRect,
    QPropertyAnimation, QVariantAnimation, QEasingCurve, QPoint,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient,
    QRadialGradient, QFont, QPainterPath, QConicalGradient,
    QRegion, QFontDatabase,
)

# ──────────────────────────────────────────────
#  КОНФИГ — загружается из settings.json
# ──────────────────────────────────────────────
CONFIG = SettingsManager.load()
ToastNotifier.set_enabled(bool(CONFIG.get("notifications_enabled", True)))

_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".last_key.json")
_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.json")
_LOG_MAX_LINES = 200


# ──────────────────────────────────────────────
#  ИСТОРИЯ КЛЮЧЕЙ
# ──────────────────────────────────────────────
class HistoryManager:
    @staticmethod
    def save_key(key_data):
        try:
            history = HistoryManager.load_history()
            key_data = dict(key_data)
            key_data["timestamp"] = time.time()
            history = [k for k in history if k.get('link') != key_data.get('link')]
            history.insert(0, key_data)
            history = history[:50]
            with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"HistoryManager.save_key: {e}")

    @staticmethod
    def load_history():
        try:
            if os.path.exists(_HISTORY_FILE):
                with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
                    now = time.time()
                    history = [k for k in history if now - k.get("timestamp", 0) < 86400]
                    return history
        except Exception:
            pass
        return []

    @staticmethod
    def format_time_ago(ts):
        diff = int(time.time() - ts)
        hours = diff // 3600
        minutes = (diff % 3600) // 60
        if hours > 0:
            return f"{hours}ч {minutes}м назад"
        return f"{minutes}м назад"

    @staticmethod
    def get_flag(country_code):
        if not country_code or country_code == "??":
            return "🏳"
        try:
            return "".join(chr(127397 + ord(c)) for c in country_code.upper())
        except Exception:
            return "🏳"


C = {
    "bg":       QColor(8,   10,  26),
    "bg2":      QColor(12,  15,  38),
    "card":     QColor(16,  20,  52,  210),
    "border":   QColor(0,   200, 255, 70),
    "accent":   QColor(0,   210, 255),
    "accent2":  QColor(160, 60,  255),
    "text":     QColor(220, 240, 255),
    "subtext":  QColor(120, 160, 200),
    "red":      QColor(255, 70,  120),
    "green":    QColor(50,  240, 160),
    "yellow":   QColor(255, 200, 40),
    "blue":     QColor(0,   200, 255),
}


# ──────────────────────────────────────────────
#  WORKER — поиск + продолжение в фоне
# ──────────────────────────────────────────────
class VPNWorker(QThread):
    log_signal          = pyqtSignal(str)
    connected_signal    = pyqtSignal(dict)
    disconnected_signal = pyqtSignal()
    status_signal       = pyqtSignal(str, str)
    new_key_signal      = pyqtSignal(dict)
    scan_done_signal    = pyqtSignal()

    def __init__(self, logic, action, key=None, use_cache=True, config=None, strict=False):
        super().__init__()
        self.logic = logic
        self.action = action
        self.key = key
        self.use_cache = use_cache
        self.strict = strict   # если True — _resume не падает на _connect/кэш
        self.config = config or {}
        self._lock = threading.Lock()
        self.vpn_process = None
        self._stop_flag = False
        self._bg_thread = None
        self._all_candidates = []   # все распарсенные ключи (для фонового продолжения)

    # ── публичный API ──
    def stop(self):
        self._stop_flag = True

    def run(self):
        if self.action == "connect":
            self._connect()
        elif self.action == "resume":
            self._resume()

    # ── основной цикл ──
    def _connect(self):
        self.status_signal.emit("...", "yellow")
        self.log_signal.emit("Поиск лучших узлов...")

        if self.use_cache:
            cached = self._load_cache()
            if cached:
                self.log_signal.emit("Пробую последний рабочий ключ...")
                if self._try_key(cached):
                    self._save_cache(cached)
                    self.connected_signal.emit(cached)
                    self._start_background_scan()
                    return
                self.log_signal.emit("Кэш устарел, ищу новые...")
        else:
            self.log_signal.emit("Сканирую свежие ключи из источников...")

        best_keys = self.logic.get_best_keys(callback_log=self.log_signal.emit)
        if not best_keys:
            self.log_signal.emit("Ключи не найдены")
            self.disconnected_signal.emit()
            return
        self._all_candidates = list(best_keys)

        for i, key_data in enumerate(best_keys[:20]):
            if self._stop_flag:
                return
            self.log_signal.emit(f"Тест узла {i+1}...")
            self._kill_hiddify()
            if self._try_key(key_data):
                self._save_cache(key_data)
                self.connected_signal.emit(key_data)
                # после первого успеха запускаем фоновое сканирование остальных
                self._start_background_scan(skip_link=key_data.get("link"))
                return

        self.log_signal.emit("Нет рабочих узлов")
        self.disconnected_signal.emit()

    def _resume(self):
        self.status_signal.emit("...", "yellow")
        if self.key and self._try_key(self.key):
            self._save_cache(self.key)
            self.connected_signal.emit(self.key)
            self._start_background_scan(skip_link=self.key.get("link"))
            return
        if self.strict:
            # пользователь явно выбрал узел — не подменяем его кэшем
            self.log_signal.emit("Выбранный узел недоступен")
            self.disconnected_signal.emit()
            return
        self.log_signal.emit("Сбой возобновления, ищу новый...")
        self._connect()

    # ── фоновое сканирование после первого успеха ──
    def _start_background_scan(self, skip_link=None):
        if not self.config.get("background_scan_enabled", True):
            return
        if self._bg_thread and self._bg_thread.is_alive():
            return

        def runner():
            try:
                self._background_scan(skip_link=skip_link)
            except Exception as e:
                logger.debug(f"background scan crash: {e}")
            finally:
                try:
                    self.scan_done_signal.emit()
                except Exception:
                    pass

        self._bg_thread = threading.Thread(target=runner, daemon=True)
        self._bg_thread.start()

    def _background_scan(self, skip_link=None):
        """Лёгкий пинг + резолв страны для всех найденных ключей.
        Активному соединению не мешает — без перезапуска hiddify."""
        candidates = self._all_candidates
        if not candidates:
            # если зашли через cache/resume — сгребём с нуля
            self.log_signal.emit("Фоновый поиск регионов...")
            candidates = self.logic.scrape_keys()
        max_tests = int(self.config.get("max_background_tests") or 60)
        tested_total = 0
        for k in candidates:
            if self._stop_flag:
                return
            if tested_total >= max_tests:
                break
            link = k.get("link")
            if not link or link == skip_link:
                continue
            if not self.logic.test_key(k):
                continue
            tested_total += 1
            # пробуем определить страну через GeoIP (без прокси, по IP)
            country = self._resolve_country(k.get("host"))
            if country:
                k = dict(k)
                k["country"] = country
                try:
                    self.new_key_signal.emit(k)
                except Exception:
                    pass

    _GEO_CACHE = {}
    _GEO_LOCK = threading.Lock()

    def _resolve_country(self, host):
        if not host:
            return None
        with self._GEO_LOCK:
            if host in self._GEO_CACHE:
                return self._GEO_CACHE[host]
        try:
            ip = host
            try:
                ip = socket.gethostbyname(host)
            except Exception:
                pass
            res = requests.get(f"https://ipapi.co/{ip}/country/", timeout=4)
            if res.status_code == 200:
                code = (res.text or "").strip()[:2].upper()
                if code and code.isalpha():
                    with self._GEO_LOCK:
                        self._GEO_CACHE[host] = code
                    return code
        except Exception:
            pass
        return None

    # ── активация ключа (hiddify) ──
    def _try_key(self, key_data) -> bool:
        SystemManager.kill_hiddify()
        if not self._start_hiddify(key_data):
            return False
        SystemManager.set_proxy(True, "127.0.0.1", 12334)

        gpt_ok = False
        try:
            if hasattr(self.logic, 'check_chatgpt_via_proxy'):
                gpt_ok, _ = self.logic.check_chatgpt_via_proxy()
            else:
                proxies = {"http": "socks5h://127.0.0.1:12334", "https": "socks5h://127.0.0.1:12334"}
                requests.get("https://www.google.com", proxies=proxies, timeout=5)
                gpt_ok = True
        except Exception as e:
            logger.debug(f"Proxy test failed: {e}")
            gpt_ok = False

        if not gpt_ok:
            return False

        return self._fetch_ip_country(key_data)

    def _start_hiddify(self, key_data) -> bool:
        try:
            config_path = os.path.join(
                os.path.dirname(CONFIG["hiddify_cli"]), "current_config.txt")
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(key_data['link'])
            cmd = [CONFIG["hiddify_cli"], "run", "-c", config_path,
                   "--in-proxy-port", "12334", "--system-proxy",
                   "--fragment", "--log-level", "warn"]
            with self._lock:
                self.vpn_process = subprocess.Popen(
                    cmd, cwd=os.path.dirname(CONFIG["hiddify_cli"]),
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(12):
                time.sleep(1)
                try:
                    with socket.create_connection(("127.0.0.1", 12334), timeout=1):
                        return True
                except OSError:
                    pass
            return False
        except Exception as e:
            logger.debug(f"_start_hiddify: {e}")
            return False

    def _kill_hiddify(self):
        with self._lock:
            proc = self.vpn_process
            self.vpn_process = None
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                pass
        SystemManager.kill_hiddify()

    def _fetch_ip_country(self, key_data) -> bool:
        proxies = {"http": "socks5h://127.0.0.1:12334",
                   "https": "socks5h://127.0.0.1:12334"}
        try:
            t0 = time.time()
            res = requests.get("https://ipinfo.io/json", proxies=proxies, timeout=10).json()
            key_data["country"] = res.get("country", "??")
            key_data["latency"] = int((time.time() - t0) * 1000)
            return True
        except Exception as e:
            logger.debug(f"_fetch_ip_country: {e}")
            return False

    def _save_cache(self, key_data):
        try:
            with open(_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(key_data, f)
        except Exception:
            pass

    def _load_cache(self):
        try:
            if os.path.exists(_CACHE_FILE):
                with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return None


# ──────────────────────────────────────────────
#  КОЛЬЦО СТАТУСА
# ──────────────────────────────────────────────
class RingWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(220, 220)
        self._status_text = "OFF"
        self._status_color = C["red"]
        self._angle = 0
        self._orbit2 = 0
        self._spinning = False
        self._pulse = 0.0
        self._pulse_dir = 1
        self._particles = []
        self._border_pos = 0.0

        self._spin_timer = QTimer(self)
        self._spin_timer.timeout.connect(self._tick_spin)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._tick_pulse)
        self._pulse_timer.start(20)

        self._border_timer = QTimer(self)
        self._border_timer.timeout.connect(self._tick_border)
        self._border_timer.start(16)

    def set_status(self, text, color_name):
        self._status_text = text
        self._status_color = C.get(color_name, C["red"])
        self._spawn_burst()
        self.update()

    def set_spinning(self, val: bool):
        self._spinning = val
        if val:
            self._spin_timer.start(16)
        else:
            self._spin_timer.stop()
            self.update()

    def _spawn_burst(self):
        import random
        self._particles = [
            [random.uniform(0, 360), random.uniform(55, 85),
             255, random.uniform(1.5, 3.5)]
            for _ in range(18)
        ]

    def _tick_spin(self):
        self._angle = (self._angle + 4) % 360
        self._orbit2 = (self._orbit2 - 2.5) % 360
        alive = []
        for p in self._particles:
            p[1] += p[3]
            p[2] = max(0, p[2] - 8)
            if p[2] > 0:
                alive.append(p)
        self._particles = alive
        self.update()

    def _tick_pulse(self):
        self._pulse += 0.03 * self._pulse_dir
        if self._pulse >= 1.0:
            self._pulse = 1.0; self._pulse_dir = -1
        elif self._pulse <= 0.0:
            self._pulse = 0.0; self._pulse_dir = 1
        self.update()

    def _tick_border(self):
        self._border_pos = (self._border_pos + 1.2) % 360
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        cx, cy, r = self.width() // 2, self.height() // 2, 80

        for pt in self._particles:
            ang, rad, alpha, _ = pt
            px = cx + rad * math.cos(math.radians(ang))
            py = cy + rad * math.sin(math.radians(ang))
            pc = QColor(self._status_color); pc.setAlpha(int(alpha * 0.8))
            p.setBrush(QBrush(pc)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(int(px-3), int(py-3), 6, 6)

        glow_r = r + 28 + int(self._pulse * 14)
        glow = QRadialGradient(cx, cy, glow_r)
        gc = QColor(self._status_color)
        gc.setAlpha(int(30 + self._pulse * 25))
        glow.setColorAt(0, gc)
        glow.setColorAt(0.6, QColor(gc.red(), gc.green(), gc.blue(), int(gc.alpha()*0.3)))
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(glow)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(cx - glow_r, cy - glow_r, glow_r * 2, glow_r * 2)

        bg_grad = QRadialGradient(cx, cy, r)
        bg_grad.setColorAt(0, QColor(20, 30, 70, 210))
        bg_grad.setColorAt(0.6, QColor(10, 16, 45, 220))
        bg_grad.setColorAt(1, QColor(6, 8, 24, 240))
        p.setBrush(QBrush(bg_grad)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        hi_grad = QLinearGradient(cx - r, cy - r, cx + r, cy)
        hi_grad.setColorAt(0, QColor(255, 255, 255, 18))
        hi_grad.setColorAt(1, QColor(255, 255, 255, 0))
        hi_path = QPainterPath()
        hi_path.addEllipse(cx - r + 2, cy - r + 2, r * 2 - 4, r - 4)
        p.fillPath(hi_path, QBrush(hi_grad))

        pen1 = QPen(C["accent"]); pen1.setWidth(2)
        pen1.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen1); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(cx-r-6, cy-r-6, (r+6)*2, (r+6)*2,
                  int(self._border_pos * 16), 80 * 16)

        pen2 = QPen(C["accent2"]); pen2.setWidth(2)
        pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen2); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(cx-r-6, cy-r-6, (r+6)*2, (r+6)*2,
                  int(self._orbit2 * 16), 50 * 16)

        for radius, width, alpha in [(r, 2, 220), (r-16, 4, 160), (r-26, 1, 60)]:
            col = QColor(self._status_color); col.setAlpha(alpha)
            p.setPen(QPen(col, width)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(cx-radius, cy-radius, radius*2, radius*2)

        if self._spinning:
            for offset, size, alpha in [(0, 10, 240), (-18, 7, 140), (-36, 5, 70)]:
                ang = self._angle + offset
                sx = cx + (r - 10) * math.cos(math.radians(ang))
                sy = cy + (r - 10) * math.sin(math.radians(ang))
                sc = QColor(C["accent"]); sc.setAlpha(alpha)
                p.setBrush(QBrush(sc)); p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(int(sx-size//2), int(sy-size//2), size, size)
            for offset, size, alpha in [(0, 8, 180), (-22, 5, 100)]:
                ang = self._orbit2 + offset
                sx = cx + (r - 10) * math.cos(math.radians(ang))
                sy = cy + (r - 10) * math.sin(math.radians(ang))
                sc = QColor(C["accent2"]); sc.setAlpha(alpha)
                p.setBrush(QBrush(sc)); p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(int(sx-size//2), int(sy-size//2), size, size)

        p.setPen(QPen(self._status_color))
        font = QFont("Lexend", 22, QFont.Weight.Bold)
        p.setFont(font)
        p.drawText(QRect(cx-70, cy-22, 140, 44),
                   Qt.AlignmentFlag.AlignCenter, self._status_text)

        p.end()


# ──────────────────────────────────────────────
#  ГРАФИК СКОРОСТИ (psutil)
# ──────────────────────────────────────────────
class SpeedGraphWidget(QWidget):
    """Линейный график download/upload за последние 60 секунд."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(72)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._max_points = 60
        self._down = [0.0] * self._max_points
        self._up = [0.0] * self._max_points
        self._cur_down = 0.0
        self._cur_up = 0.0
        self._last_recv = None
        self._last_sent = None
        self._last_ts = None

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._sample)
        self._poll.start(1000)

        self._anim = QTimer(self)
        self._anim.timeout.connect(self.update)
        self._anim.start(60)

    def reset(self):
        self._down = [0.0] * self._max_points
        self._up = [0.0] * self._max_points
        self._cur_down = 0.0
        self._cur_up = 0.0
        self._last_recv = None
        self._last_sent = None
        self._last_ts = None
        self.update()

    def _sample(self):
        if psutil is None:
            return
        try:
            io = psutil.net_io_counters()
            now = time.time()
            if self._last_recv is None:
                self._last_recv = io.bytes_recv
                self._last_sent = io.bytes_sent
                self._last_ts = now
                return
            dt = max(1e-3, now - self._last_ts)
            d_recv = max(0, io.bytes_recv - self._last_recv) / dt
            d_sent = max(0, io.bytes_sent - self._last_sent) / dt
            self._last_recv = io.bytes_recv
            self._last_sent = io.bytes_sent
            self._last_ts = now
            self._cur_down = d_recv
            self._cur_up = d_sent
            self._down.append(d_recv); self._down = self._down[-self._max_points:]
            self._up.append(d_sent); self._up = self._up[-self._max_points:]
        except Exception:
            pass

    @staticmethod
    def _fmt(rate):
        # rate в байтах/сек
        units = [("B/s", 1), ("KB/s", 1024), ("MB/s", 1024**2), ("GB/s", 1024**3)]
        for unit, scale in reversed(units):
            if rate >= scale or unit == "B/s":
                val = rate / scale
                return f"{val:.1f} {unit}"
        return "0 B/s"

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()
        # фон
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, 12, 12)
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor(10, 18, 50, 200))
        bg.setColorAt(1, QColor(6, 10, 30, 210))
        p.fillPath(path, QBrush(bg))

        # рамка
        p.setPen(QPen(QColor(0, 200, 255, 60), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # сетка
        p.setPen(QPen(QColor(0, 200, 255, 20), 1, Qt.PenStyle.DotLine))
        for i in range(1, 4):
            y = int(h * i / 4)
            p.drawLine(8, y, w - 8, y)

        # данные
        if psutil is None:
            p.setPen(QColor(255, 200, 80, 200))
            p.setFont(QFont("Lexend", 9))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "psutil не установлен — pip install psutil")
            p.end()
            return

        max_val = max(self._down + self._up + [1.0])
        # лёгкое сглаживание шкалы
        max_val = max_val * 1.1

        def build_path(series, base_offset_y=0):
            pth = QPainterPath()
            n = len(series)
            if n == 0:
                return pth
            usable_w = w - 16
            usable_h = h - 22
            x0 = 8
            y0 = 18
            for i, v in enumerate(series):
                x = x0 + (i * usable_w / (self._max_points - 1))
                y = y0 + usable_h - (v / max_val) * usable_h
                if i == 0:
                    pth.moveTo(x, y)
                else:
                    pth.lineTo(x, y)
            return pth

        # download (cyan)
        pen_dl = QPen(C["accent"], 1.8)
        pen_dl.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen_dl.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen_dl)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(build_path(self._down))

        # заливка под линией скачивания
        fill = QPainterPath(build_path(self._down))
        fill.lineTo(w - 8, h - 4)
        fill.lineTo(8, h - 4)
        fill.closeSubpath()
        grad = QLinearGradient(0, 18, 0, h)
        grad.setColorAt(0, QColor(0, 210, 255, 90))
        grad.setColorAt(1, QColor(0, 210, 255, 0))
        p.fillPath(fill, QBrush(grad))

        # upload (purple)
        pen_up = QPen(C["accent2"], 1.6)
        pen_up.setStyle(Qt.PenStyle.SolidLine)
        pen_up.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen_up)
        p.drawPath(build_path(self._up))

        # тексты сверху
        p.setPen(QColor(120, 200, 255))
        p.setFont(QFont("Lexend", 8, QFont.Weight.Bold))
        p.drawText(10, 12, f"▼ {self._fmt(self._cur_down)}")
        p.setPen(QColor(170, 130, 255))
        right_text = f"▲ {self._fmt(self._cur_up)}"
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(right_text)
        p.drawText(w - tw - 10, 12, right_text)
        p.end()


# ──────────────────────────────────────────────
#  ИНФО-КАРТОЧКА
# ──────────────────────────────────────────────
class InfoCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(82)
        self._hover = False
        self._hover_alpha = 0
        self._shimmer = 0.0
        self._shimmer_dir = 1
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.rows = {}
        configs = [
            ("status",  "СТАТУС",  "ОТКЛЮЧЕН",   "#ff4678"),
            ("country", "ЛОКАЦИЯ", "—",           "#e2f0ff"),
            ("ping",    "ПИНГ",    "—",           "#e2f0ff"),
        ]
        for key, label, value, color in configs:
            tile = QWidget()
            tile.setStyleSheet("background: transparent;")
            tl = QVBoxLayout(tile)
            tl.setContentsMargins(14, 8, 14, 8)
            tl.setSpacing(3)
            lbl = QLabel(label)
            lbl.setStyleSheet("color: rgba(130,165,210,200); font-family: Lexend; font-size: 8px; font-weight: bold; letter-spacing: 1px; background: transparent;")
            val = QLabel(value)
            val.setStyleSheet(f"color: {color}; font-family: Lexend; font-size: 13px; font-weight: bold; background: transparent;")
            tl.addWidget(lbl)
            tl.addWidget(val)
            layout.addWidget(tile, 1)
            self.rows[key] = val

    def set_row(self, key, text, color=None):
        if key in self.rows:
            self.rows[key].setText(text)
            if color:
                self.rows[key].setStyleSheet(
                    f"color: {color}; font-family: Lexend; font-size: 13px; font-weight: bold; background: transparent;")

    def _tick(self):
        step = 15 if self._hover else -15
        self._hover_alpha = max(0, min(255, self._hover_alpha + step))
        self._shimmer += 0.04 * self._shimmer_dir
        if self._shimmer >= 1.2: self._shimmer_dir = -1
        if self._shimmer <= 0.0: self._shimmer_dir = 1
        self.update()
        if not self._hover and self._hover_alpha <= 0:
            self._timer.stop()

    def enterEvent(self, e):
        self._hover = True
        self._timer.start(16)

    def leaveEvent(self, e):
        self._hover = False
        self._timer.start(16)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, 16, 16)

        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0, QColor(18, 26, 72, 200 + self._hover_alpha // 6))
        grad.setColorAt(0.5, QColor(12, 20, 58, 185))
        grad.setColorAt(1, QColor(8, 14, 40, 195))
        p.fillPath(path, QBrush(grad))

        if self._hover_alpha > 0 and self._shimmer > 0:
            sx = int(self._shimmer * (w + 80)) - 80
            shimmer_grad = QLinearGradient(sx, 0, sx + 80, 0)
            shimmer_grad.setColorAt(0,   QColor(255, 255, 255, 0))
            shimmer_grad.setColorAt(0.5, QColor(255, 255, 255, int(14 * self._hover_alpha / 255)))
            shimmer_grad.setColorAt(1,   QColor(255, 255, 255, 0))
            p.fillPath(path, QBrush(shimmer_grad))

        p.setPen(QPen(QColor(0, 180, 255, 30), 1))
        tile_w = w // 3
        for i in (1, 2):
            p.drawLine(tile_w * i, 12, tile_w * i, h - 12)

        border_alpha = 55 + int(self._hover_alpha * 0.7)
        pen = QPen(QColor(0, 200, 255, border_alpha), 1)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        hi = QPainterPath()
        hi.addRoundedRect(1, 1, w - 2, h // 2, 14, 14)
        p.fillPath(hi, QColor(255, 255, 255, 10 + self._hover_alpha // 14))
        p.end()


# ──────────────────────────────────────────────
#  КНОПКИ
# ──────────────────────────────────────────────
class ConnectButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(50)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._text = "ПОДКЛЮЧИТЬ"
        self._hover = False
        self._press = False
        self._glow = 0.0
        self._ripple_r = 0.0
        self._ripple_alpha = 0.0
        self._ripple_x = 0
        self._ripple_y = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_text(self, t):
        self._text = t; self.update()

    def _tick(self):
        self._glow += 0.07 if self._hover else -0.07
        self._glow = max(0.0, min(1.0, self._glow))
        if self._ripple_r > 0:
            self._ripple_r += 6
            self._ripple_alpha = max(0.0, self._ripple_alpha - 8)
        self.update()
        if not self._hover and self._glow <= 0 and self._ripple_alpha <= 0:
            self._timer.stop()

    def enterEvent(self, e): self._hover = True; self._timer.start(16)
    def leaveEvent(self, e): self._hover = False; self._timer.start(16)

    def mousePressEvent(self, e):
        self._press = True
        self._ripple_x = e.pos().x()
        self._ripple_y = e.pos().y()
        self._ripple_r = 4.0
        self._ripple_alpha = 180.0
        self._timer.start(16)
        self.update()

    def mouseReleaseEvent(self, e):
        self._press = False; self.update()
        if self.rect().contains(e.pos()):
            self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, h // 2, h // 2)

        g = QLinearGradient(0, 0, w, h)
        if self._press:
            g.setColorAt(0, QColor(0,  140, 200))
            g.setColorAt(1, QColor(100, 20, 180))
        else:
            t = self._glow
            g.setColorAt(0, QColor(int(0   + 20*t),  int(170 + 30*t), int(240 + 10*t)))
            g.setColorAt(1, QColor(int(100 + 40*t),  int(20  + 10*t), int(200 + 30*t)))
        p.fillPath(path, QBrush(g))

        if self._ripple_r > 0 and self._ripple_alpha > 0:
            p.setClipPath(path)
            rc = QColor(255, 255, 255, int(self._ripple_alpha))
            p.setBrush(QBrush(rc)); p.setPen(Qt.PenStyle.NoPen)
            rr = int(self._ripple_r)
            p.drawEllipse(self._ripple_x - rr, self._ripple_y - rr, rr*2, rr*2)
            p.setClipping(False)

        if self._glow > 0:
            for i in range(1, 4):
                gp = QPainterPath()
                gp.addRoundedRect(-i*2, -i*2, w+i*4, h+i*4, h//2+i*2, h//2+i*2)
                gc2 = QColor(0, 200, 255, int(28 * self._glow / i))
                p.setPen(QPen(gc2, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(gp)

        hi = QPainterPath()
        hi.addRoundedRect(4, 2, w-8, h//2-2, h//2-2, h//2-2)
        p.fillPath(hi, QColor(255, 255, 255, int(28 + 12*self._glow)))

        p.setPen(QColor(255, 255, 255))
        font = QFont("Lexend", 11, QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        p.setFont(font)
        p.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, self._text)
        p.end()


class SmallButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, icon_text, parent=None):
        super().__init__(parent)
        self.setFixedSize(86, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._text = icon_text
        self._hover = False
        self._press = False
        self._fill = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_text(self, t): self._text = t; self.update()

    def _tick(self):
        target = 1.0 if self._hover else 0.0
        self._fill += 0.08 if self._hover else -0.08
        self._fill = max(0.0, min(1.0, self._fill))
        self.update()
        if abs(self._fill - target) < 0.01:
            self._fill = target; self._timer.stop()

    def enterEvent(self, e): self._hover = True; self._timer.start(16)
    def leaveEvent(self, e): self._hover = False; self._timer.start(16)
    def mousePressEvent(self, e): self._press = True; self.update()
    def mouseReleaseEvent(self, e):
        self._press = False; self.update()
        if self.rect().contains(e.pos()): self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, 10, 10)

        bg = QLinearGradient(0, 0, w, h)
        bg.setColorAt(0, QColor(16, 24, 60, int(160 + 60*self._fill)))
        bg.setColorAt(1, QColor(8,  16, 45, int(150 + 50*self._fill)))
        p.fillPath(path, QBrush(bg))

        if self._fill > 0:
            fill_h = int(h * self._fill)
            clip = QPainterPath()
            clip.addRoundedRect(0, h - fill_h, w, fill_h, 10 if fill_h >= h else 0, 10 if fill_h >= h else 0)
            fill_grad = QLinearGradient(0, h, 0, h - fill_h)
            fill_grad.setColorAt(0, QColor(0, 180, 255, int(80 * self._fill)))
            fill_grad.setColorAt(1, QColor(120, 40, 255, int(60 * self._fill)))
            p.fillPath(clip, QBrush(fill_grad))

        bc = QColor(0, 200, 255, int(50 + 130 * self._fill))
        if self._press: bc = QColor(0, 220, 255, 220)
        p.setPen(QPen(bc, 1.2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        tc = QColor(int(200 + 55*self._fill), int(230 + 25*self._fill), 255)
        p.setPen(tc)
        p.setFont(QFont("Lexend", 8, QFont.Weight.Bold))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)
        p.end()


# ──────────────────────────────────────────────
#  ВЫЕЗЖАЮЩИЕ ПАНЕЛИ (slide-out)
# ──────────────────────────────────────────────
_active_animations = []  # удерживаем ссылки, чтобы анимации не собирались GC


def _gc_anim(anim):
    try:
        _active_animations.remove(anim)
    except ValueError:
        pass


_PANEL_HIDDEN_REVEAL = 8   # ширина «спрятанной» зоны панели (под правым краем main)


def slide_panel_in(panel, anchor, target_w=None, target_h=None, duration=260):
    """Выезд панели «из-под» правого края anchor.

    Панель сразу позиционируется в финальной точке и финальным размером —
    layout рассчитывается один раз, текст не сплющивается и не пересчитывается
    в каждом кадре. Анимируется только видимая область через setMask:
    маска растёт слева направо, имитируя выезжающую из-под главного окна
    шторку.
    """
    if target_w is None:
        target_w = panel.width() or 380
    if target_h is None:
        target_h = anchor.height()
    final_x = anchor.x() + anchor.width() - 8
    target_y = anchor.y()

    panel.setGeometry(final_x, target_y, target_w, target_h)
    panel._slide_target = (final_x, target_y, target_w, target_h)

    def _apply(reveal):
        try:
            reveal = int(reveal)
        except (TypeError, ValueError):
            return
        if reveal < _PANEL_HIDDEN_REVEAL:
            reveal = _PANEL_HIDDEN_REVEAL
        if reveal > target_w:
            reveal = target_w
        panel.setMask(QRegion(0, 0, reveal, target_h))

    _apply(_PANEL_HIDDEN_REVEAL)
    panel.show()
    panel.raise_()
    panel.activateWindow()

    anim = QVariantAnimation()
    anim.setDuration(duration)
    anim.setStartValue(_PANEL_HIDDEN_REVEAL)
    anim.setEndValue(target_w)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.valueChanged.connect(_apply)

    def _finished():
        _gc_anim(anim)
        try:
            panel.clearMask()
        except Exception:
            pass

    anim.finished.connect(_finished)
    _active_animations.append(anim)
    anim.start()
    return anim


def slide_panel_out(panel, duration=200):
    """Уезд панели обратно за правый край anchor (маска сжимается налево)."""
    target = getattr(panel, "_slide_target", None)
    if target is None:
        try:
            panel.hide()
        except Exception:
            pass
        return None
    _x, _y, target_w, target_h = target

    def _apply(reveal):
        try:
            reveal = int(reveal)
        except (TypeError, ValueError):
            return
        if reveal < _PANEL_HIDDEN_REVEAL:
            reveal = _PANEL_HIDDEN_REVEAL
        if reveal > target_w:
            reveal = target_w
        panel.setMask(QRegion(0, 0, reveal, target_h))

    anim = QVariantAnimation()
    anim.setDuration(duration)
    anim.setStartValue(target_w)
    anim.setEndValue(_PANEL_HIDDEN_REVEAL)
    anim.setEasingCurve(QEasingCurve.Type.InCubic)
    anim.valueChanged.connect(_apply)

    def _done():
        _gc_anim(anim)
        try:
            panel.clearMask()
            panel.hide()
        except Exception:
            pass

    anim.finished.connect(_done)
    _active_animations.append(anim)
    anim.start()
    return anim


# ──────────────────────────────────────────────
#  ОБЩАЯ СТИЛИЗАЦИЯ ДИАЛОГОВ
# ──────────────────────────────────────────────
_DIALOG_CONTAINER_QSS = """
#DialogContainer {
    background: rgba(6, 10, 28, 215);
    border: 1px solid rgba(0, 180, 255, 90);
    border-radius: 20px;
}
QLabel { color: #dce8ff; font-family: Lexend; }
QLineEdit {
    background: rgba(8, 14, 38, 230);
    color: #e2f0ff;
    border: 1px solid rgba(0, 180, 255, 60);
    border-radius: 8px;
    padding: 6px 10px;
    font-family: Lexend; font-size: 11px;
}
QLineEdit:focus { border-color: rgba(0, 210, 255, 200); }
QCheckBox { color: #dce8ff; font-family: Lexend; font-size: 11px; spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid rgba(0, 180, 255, 90);
    background: rgba(8, 14, 38, 200);
}
QCheckBox::indicator:checked {
    background: #00d2ff;
    border-color: #00d2ff;
}
QPushButton {
    color: #dce8ff;
    background: rgba(0, 180, 255, 40);
    border: 1px solid rgba(0, 200, 255, 100);
    border-radius: 8px;
    padding: 5px 12px;
    font-family: Lexend; font-size: 10px; font-weight: bold;
}
QPushButton:hover { background: rgba(0, 200, 255, 80); color: #fff; }
QPushButton:pressed { background: rgba(0, 160, 220, 130); }
QListWidget {
    background: transparent;
    border: 1px solid rgba(0, 180, 255, 30);
    border-radius: 12px;
    outline: none;
    padding: 4px;
}
QListWidget::item {
    background: rgba(10, 16, 48, 180);
    border-radius: 10px;
    margin-bottom: 6px;
    padding: 8px;
    border: 1px solid rgba(0, 160, 255, 30);
    color: #dce8ff;
}
QListWidget::item:hover {
    background: rgba(0, 40, 80, 200);
    border-color: rgba(0, 200, 255, 80);
}
QListWidget::item:selected {
    background: rgba(0, 140, 220, 160);
    border-color: rgba(0, 220, 255, 200);
    color: #fff;
}
QTabWidget::pane {
    border: 1px solid rgba(0, 180, 255, 60);
    border-radius: 12px;
    top: -1px;
    background: rgba(8, 14, 38, 180);
}
QTabBar::tab {
    background: rgba(10, 18, 50, 200);
    color: #94a3b8;
    padding: 8px 14px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-family: Lexend; font-size: 10px; font-weight: bold;
    letter-spacing: 1px;
}
QTabBar::tab:selected {
    background: rgba(0, 140, 220, 130);
    color: #fff;
}
QScrollBar:vertical { background: transparent; width: 6px; }
QScrollBar::handle:vertical { background: rgba(0,180,255,90); border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QTextEdit {
    background: rgba(8, 14, 38, 230);
    color: #e2f0ff;
    border: 1px solid rgba(0, 180, 255, 60);
    border-radius: 8px;
    padding: 6px;
    font-family: 'Consolas','JetBrains Mono', monospace; font-size: 10px;
}
"""


# ──────────────────────────────────────────────
#  ОКНО ИСТОРИИ
# ──────────────────────────────────────────────
class HistoryWindow(QDialog):
    key_selected = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("История ключей")
        self.resize(360, 540)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)

        self.container = QFrame()
        self.container.setObjectName("DialogContainer")
        self.container.setStyleSheet(_DIALOG_CONTAINER_QSS)
        container_layout = QVBoxLayout(self.container)

        title_row = QHBoxLayout()
        title = QLabel("ИСТОРИЯ УЗЛОВ")
        title.setStyleSheet("color: #00d2ff; font-family: Lexend; font-size: 14px; font-weight: bold; letter-spacing: 1px;")
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setStyleSheet("color: #94a3b8; background: transparent; border: none; font-size: 16px;")
        close_btn.clicked.connect(self._animated_close)
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(close_btn)
        container_layout.addLayout(title_row)

        self.list = QListWidget()
        self.list.itemClicked.connect(self._on_item_clicked)
        container_layout.addWidget(self.list)

        layout.addWidget(self.container)
        self.refresh()

    def _animated_close(self):
        slide_panel_out(self)

    def refresh(self):
        self.list.clear()
        history = HistoryManager.load_history()
        for key in history:
            item = QListWidgetItem()
            widget = QWidget()
            w_layout = QVBoxLayout(widget)
            w_layout.setContentsMargins(5, 5, 5, 5)
            w_layout.setSpacing(2)

            top_row = QHBoxLayout()
            flag = HistoryManager.get_flag(key.get("country", "??"))
            name = QLabel(f"{flag} {key.get('name', 'Unnamed')[:25]}")
            name.setStyleSheet("color: #e2e8f0; font-family: Lexend; font-size: 11px; font-weight: bold;")

            ping = QLabel(f"{key.get('latency', 0)} ms")
            ping.setStyleSheet("color: #4ade80; font-family: Lexend; font-size: 10px;")
            top_row.addWidget(name)
            top_row.addStretch()
            top_row.addWidget(ping)

            bottom_row = QHBoxLayout()
            time_ago = QLabel(HistoryManager.format_time_ago(key.get("timestamp", 0)))
            time_ago.setStyleSheet("color: #94a3b8; font-family: Lexend; font-size: 9px;")
            protocol = QLabel(key.get("protocol", "vless").upper())
            protocol.setStyleSheet("color: #8b5cf6; font-family: Lexend; font-size: 9px; font-weight: bold;")
            bottom_row.addWidget(time_ago)
            bottom_row.addStretch()
            bottom_row.addWidget(protocol)

            w_layout.addLayout(top_row)
            w_layout.addLayout(bottom_row)

            item.setSizeHint(widget.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.list.addItem(item)
            self.list.setItemWidget(item, widget)

    def _on_item_clicked(self, item):
        key = item.data(Qt.ItemDataRole.UserRole)
        self.key_selected.emit(key)
        slide_panel_out(self)


# ──────────────────────────────────────────────
#  ОКНО ВЫБОРА РЕГИОНА
# ──────────────────────────────────────────────
class RegionWindow(QDialog):
    """Список регионов с рабочими ключами. Заполняется по мере поиска."""
    key_selected = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Регионы")
        self.resize(380, 620)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)

        self.container = QFrame()
        self.container.setObjectName("DialogContainer")
        self.container.setStyleSheet(_DIALOG_CONTAINER_QSS)
        container_layout = QVBoxLayout(self.container)
        container_layout.setSpacing(8)

        # шапка
        title_row = QHBoxLayout()
        title = QLabel("РЕГИОНЫ")
        title.setStyleSheet("color: #00d2ff; font-family: Lexend; font-size: 14px; font-weight: bold; letter-spacing: 1px;")
        self.status_label = QLabel("Найдено: 0")
        self.status_label.setStyleSheet("color: #94a3b8; font-family: Lexend; font-size: 10px;")
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setStyleSheet("color: #94a3b8; background: transparent; border: none; font-size: 16px;")
        close_btn.clicked.connect(self._animated_close)
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(self.status_label)
        title_row.addWidget(close_btn)
        container_layout.addLayout(title_row)

        hint = QLabel("Кликните по узлу, чтобы переключиться на него.\nСписок пополняется по мере фонового сканирования.")
        hint.setStyleSheet("color: #7ab8e0; font-family: Lexend; font-size: 9px;")
        hint.setWordWrap(True)
        container_layout.addWidget(hint)

        self.list = QListWidget()
        self.list.itemClicked.connect(self._on_item_clicked)
        container_layout.addWidget(self.list, 1)

        layout.addWidget(self.container)

        # ключи, известные на данный момент: (link -> data)
        self._known = {}

    def _animated_close(self):
        slide_panel_out(self)

    def reset(self):
        self._known.clear()
        self.list.clear()
        self._update_status()

    def add_key(self, key_data):
        link = key_data.get("link")
        if not link:
            return
        if link in self._known:
            # обновим страну если стала известна
            self._known[link].update(key_data)
        else:
            self._known[link] = dict(key_data)
            self._add_row(self._known[link])
        self._update_status()

    def mark_active(self, link):
        for i in range(self.list.count()):
            it = self.list.item(i)
            data = it.data(Qt.ItemDataRole.UserRole)
            if data and data.get("link") == link:
                self.list.setCurrentItem(it)
                break

    def _add_row(self, key_data):
        item = QListWidgetItem()
        widget = QWidget()
        wl = QHBoxLayout(widget)
        wl.setContentsMargins(6, 4, 6, 4)

        flag = HistoryManager.get_flag(key_data.get("country", "??"))
        country = (key_data.get("country") or "??").upper()
        full_name = country_name(country) if country != "??" else "Неизвестно"

        left = QVBoxLayout()
        title_lbl = QLabel(f"{flag}  {full_name}")
        title_lbl.setStyleSheet("color: #e2f0ff; font-family: Lexend; font-size: 11px; font-weight: bold;")
        sub = QLabel(key_data.get("name", "Unnamed")[:30])
        sub.setStyleSheet("color: #7ab8e0; font-family: Lexend; font-size: 9px;")
        left.addWidget(title_lbl)
        left.addWidget(sub)

        right = QVBoxLayout()
        proto = QLabel(key_data.get("protocol", "vless").upper())
        proto.setStyleSheet("color: #a78bfa; font-family: Lexend; font-size: 9px; font-weight: bold;")
        proto.setAlignment(Qt.AlignmentFlag.AlignRight)
        latency = key_data.get("latency")
        ping_text = f"{latency} ms" if latency else f"{country}"
        ping = QLabel(ping_text)
        ping.setStyleSheet("color: #4ade80; font-family: Lexend; font-size: 10px;")
        ping.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(proto)
        right.addWidget(ping)

        wl.addLayout(left, 1)
        wl.addLayout(right)

        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, key_data)
        self.list.addItem(item)
        self.list.setItemWidget(item, widget)

    def _update_status(self):
        n = len(self._known)
        countries = {(k.get("country") or "??") for k in self._known.values()}
        self.status_label.setText(f"Узлов: {n} • Стран: {len(countries)}")

    def _on_item_clicked(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self.key_selected.emit(data)


# ──────────────────────────────────────────────
#  ОКНО НАСТРОЕК
# ──────────────────────────────────────────────
class SettingsWindow(QDialog):
    settings_changed = pyqtSignal(dict)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.resize(440, 680)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._config = dict(config)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)

        self.container = QFrame()
        self.container.setObjectName("DialogContainer")
        self.container.setStyleSheet(_DIALOG_CONTAINER_QSS)
        cl = QVBoxLayout(self.container)
        cl.setSpacing(8)

        # шапка
        title_row = QHBoxLayout()
        title = QLabel("НАСТРОЙКИ")
        title.setStyleSheet("color: #00d2ff; font-family: Lexend; font-size: 14px; font-weight: bold; letter-spacing: 1px;")
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setStyleSheet("color: #94a3b8; background: transparent; border: none; font-size: 16px;")
        close_btn.clicked.connect(self._animated_close)
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(close_btn)
        cl.addLayout(title_row)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_hotkeys_tab(), "Горячие клавиши")
        self.tabs.addTab(self._build_protocols_tab(), "Протоколы")
        self.tabs.addTab(self._build_sources_tab(), "Источники")
        self.tabs.addTab(self._build_misc_tab(), "Прочее")
        cl.addWidget(self.tabs, 1)

        # нижние кнопки
        btn_row = QHBoxLayout()
        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self._animated_close)
        reset_btn = QPushButton("По умолчанию")
        reset_btn.clicked.connect(self._reset_defaults)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        cl.addLayout(btn_row)

        layout.addWidget(self.container)

    # ── вкладки ──
    def _build_hotkeys_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(10)

        v.addWidget(QLabel("Введите комбинации в виде «ctrl+alt+B»."))

        def row(label_text, key):
            h = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setFixedWidth(170)
            edit = QLineEdit(self._config.get(key, ""))
            edit.setPlaceholderText("например, ctrl+alt+b")
            h.addWidget(lbl)
            h.addWidget(edit, 1)
            return h, edit

        h1, self.ed_hotkey = row("Подключение / отключение:", "hotkey")
        h2, self.ed_pause = row("Пауза / возобновление:", "pause_hotkey")
        h3, self.ed_regions = row("Окно регионов:", "regions_hotkey")
        v.addLayout(h1)
        v.addLayout(h2)
        v.addLayout(h3)
        v.addStretch()
        return w

    def _build_protocols_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        v.addWidget(QLabel("Выберите протоколы, которые скрипт будет искать и тестировать:"))

        current = {p.lower() for p in (self._config.get("priority_protocols") or [])}
        self._proto_checks = {}
        for code, label in [
            ("reality", "Reality (приоритет)"),
            ("vless",   "VLESS"),
            ("trojan",  "Trojan"),
            ("shadowsocks", "Shadowsocks (ss://)"),
            ("vmess",   "VMess"),
        ]:
            cb = QCheckBox(label)
            cb.setChecked(code in current)
            v.addWidget(cb)
            self._proto_checks[code] = cb

        v.addSpacing(10)
        v.addWidget(QLabel("Исключённые страны (через запятую, ISO коды):"))
        self.ed_excluded = QLineEdit(",".join(self._config.get("excluded_countries") or []))
        v.addWidget(self.ed_excluded)
        v.addStretch()
        return w

    def _build_sources_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)

        v.addWidget(QLabel("Свои подписки (каждая ссылка с новой строки):"))
        self.txt_sources = QTextEdit()
        self.txt_sources.setPlainText("\n".join(self._config.get("custom_sources") or []))
        v.addWidget(self.txt_sources, 1)

        v.addWidget(QLabel("Свои одиночные ключи (vless://, trojan://, ss://… по одному в строке):"))
        self.txt_keys = QTextEdit()
        self.txt_keys.setPlainText("\n".join(self._config.get("custom_keys") or []))
        v.addWidget(self.txt_keys, 1)
        return w

    def _build_misc_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(10)

        self.cb_notify = QCheckBox("Уведомления Windows (toast)")
        self.cb_notify.setChecked(bool(self._config.get("notifications_enabled", True)))
        v.addWidget(self.cb_notify)

        self.cb_bg_scan = QCheckBox("Фоновый поиск других регионов после подключения")
        self.cb_bg_scan.setChecked(bool(self._config.get("background_scan_enabled", True)))
        v.addWidget(self.cb_bg_scan)

        h = QHBoxLayout()
        h.addWidget(QLabel("Максимум фоновых проверок:"))
        self.ed_max_bg = QLineEdit(str(self._config.get("max_background_tests", 60)))
        self.ed_max_bg.setFixedWidth(80)
        h.addWidget(self.ed_max_bg)
        h.addStretch()
        v.addLayout(h)

        h2 = QHBoxLayout()
        h2.addWidget(QLabel("Путь к HiddifyCli.exe:"))
        self.ed_hiddify = QLineEdit(self._config.get("hiddify_cli", ""))
        h2.addWidget(self.ed_hiddify, 1)
        v.addLayout(h2)

        v.addStretch()
        return w

    # ── обработчики ──
    def _save(self):
        updates = {}
        updates["hotkey"] = self.ed_hotkey.text().strip() or "ctrl+alt+b"
        updates["pause_hotkey"] = self.ed_pause.text().strip() or "ctrl+alt+p"
        updates["regions_hotkey"] = self.ed_regions.text().strip() or "ctrl+alt+r"

        protos = [code for code, cb in self._proto_checks.items() if cb.isChecked()]
        if not protos:
            protos = ["vless", "trojan"]
        updates["priority_protocols"] = protos

        excluded = [s.strip().upper() for s in self.ed_excluded.text().split(",") if s.strip()]
        updates["excluded_countries"] = excluded

        updates["custom_sources"] = [
            l.strip() for l in self.txt_sources.toPlainText().splitlines() if l.strip()
        ]
        updates["custom_keys"] = [
            l.strip() for l in self.txt_keys.toPlainText().splitlines() if l.strip()
        ]

        updates["notifications_enabled"] = self.cb_notify.isChecked()
        updates["background_scan_enabled"] = self.cb_bg_scan.isChecked()
        try:
            updates["max_background_tests"] = max(1, int(self.ed_max_bg.text().strip() or "60"))
        except ValueError:
            updates["max_background_tests"] = 60

        hiddify_path = self.ed_hiddify.text().strip()
        if hiddify_path:
            updates["hiddify_cli"] = hiddify_path

        self.settings_changed.emit(updates)
        self._animated_close()

    def _animated_close(self):
        slide_panel_out(self)

    def _reset_defaults(self):
        from vpn_settings import DEFAULTS
        self._config = dict(DEFAULTS)
        # перезагрузим UI: проще пересоздать вкладки
        self.tabs.clear()
        self.tabs.addTab(self._build_hotkeys_tab(), "Горячие клавиши")
        self.tabs.addTab(self._build_protocols_tab(), "Протоколы")
        self.tabs.addTab(self._build_sources_tab(), "Источники")
        self.tabs.addTab(self._build_misc_tab(), "Прочее")


# ──────────────────────────────────────────────
#  ГЛАВНОЕ ОКНО
# ──────────────────────────────────────────────
class dg4VPNApp(QWidget):
    _log_signal          = pyqtSignal(str)
    _connected_signal    = pyqtSignal(dict)
    _disconnected_signal = pyqtSignal()
    _status_signal       = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.logic       = VPNLogic(CONFIG)
        self._lock       = threading.Lock()
        self.vpn_process = None
        self.is_paused   = False
        self.is_connected = False
        self.current_key = None
        self.start_time  = None
        self._worker     = None
        self._drag_pos   = None
        self._hotkeys_registered = []
        self.region_win = None
        self.settings_win = None
        self.history_win = None

        self._setup_window()
        self._setup_ui()
        self._connect_signals()

        if pystray:
            self._setup_tray()
        if keyboard:
            self._setup_hotkeys()

        if not is_admin():
            self._log("⚠ ЗАПУСТИТЕ ОТ АДМИНА!")
        if psutil is None:
            self._log("psutil не установлен — график скорости отключён")

    # ── Окно ──────────────────────────────────
    def _center(self):
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2,
                  (screen.height() - self.height()) // 2)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def _setup_window(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(420, 760)
        self._center()

    def _apply_mask(self):
        from PyQt6.QtGui import QBitmap, QPainter as QP
        bmp = QBitmap(self.size())
        bmp.fill(Qt.GlobalColor.color0)
        p = QP(bmp)
        p.setRenderHint(QP.RenderHint.Antialiasing)
        p.setBrush(Qt.GlobalColor.color1)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, self.width(), self.height(), 24, 24)
        p.end()
        self.setMask(bmp)

    def showEvent(self, e):
        super().showEvent(e)
        self._apply_mask()
        # системный Acrylic-blur выключен: на некоторых билдах Windows он
        # мажет содержимое окна, а не только фон → весь UI выглядит размытым.

    def moveEvent(self, e):
        super().moveEvent(e)
        self._reposition_panels()

    def _reposition_panels(self):
        # держим выезжающие панели приклеенными к правому краю главного окна
        anchor_x = self.x() + self.width() - 8
        anchor_y = self.y()
        for panel in (self.settings_win, self.region_win, self.history_win):
            if panel and panel.isVisible():
                panel.move(anchor_x, anchor_y)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_mask()
        try:
            self._reposition_panels()
        except Exception:
            pass

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, 24, 24)
        p.setClipPath(path)

        overlay = QLinearGradient(0, 0, 0, h)
        overlay.setColorAt(0.0, QColor(8,  12, 34, 215))
        overlay.setColorAt(0.5, QColor(6,  10, 28, 220))
        overlay.setColorAt(1.0, QColor(4,  8,  22, 225))
        p.fillRect(0, 0, w, h, QBrush(overlay))

        radial = QRadialGradient(w / 2, 0, w * 0.8)
        radial.setColorAt(0,   QColor(0, 180, 255, 22))
        radial.setColorAt(0.5, QColor(0, 120, 200, 10))
        radial.setColorAt(1,   QColor(0,   0,   0,  0))
        p.fillRect(0, 0, w, h, QBrush(radial))

        p.setClipping(False)

        pen_grad = QConicalGradient(w / 2, h / 2, self._border_angle)
        pen_grad.setColorAt(0.00, QColor(0,   210, 255, 220))
        pen_grad.setColorAt(0.25, QColor(120,  50, 255, 120))
        pen_grad.setColorAt(0.50, QColor(0,   160, 220,  60))
        pen_grad.setColorAt(0.75, QColor(160,  60, 255, 130))
        pen_grad.setColorAt(1.00, QColor(0,   210, 255, 220))
        p.setPen(QPen(QBrush(pen_grad), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        p.end()

    # ── UI ────────────────────────────────────
    def _setup_ui(self):
        self._border_angle = 0
        self._border_timer = QTimer(self)
        self._border_timer.timeout.connect(self._tick_border)
        self._border_timer.start(20)

        main = QVBoxLayout(self)
        main.setContentsMargins(16, 8, 16, 14)
        main.setSpacing(8)

        # шапка
        hdr = QHBoxLayout()
        hdr.setContentsMargins(8, 2, 4, 2)

        logo_w = QWidget(); logo_w.setFixedSize(100, 32)
        logo_w.setStyleSheet("background: transparent;")
        dot = QLabel("◉")
        dot.setStyleSheet("color: #00d2ff; font-size: 13px; background: transparent; padding-right: 2px;")
        title = QLabel("dg4VPN")
        title.setStyleSheet("color: #dce8ff; font-family: Lexend; font-size: 14px; font-weight: bold; letter-spacing: 1px; background: transparent;")
        logo_row = QHBoxLayout(logo_w)
        logo_row.setContentsMargins(0,0,0,0); logo_row.setSpacing(4)
        logo_row.addWidget(dot); logo_row.addWidget(title)

        hdr.addWidget(logo_w)
        hdr.addStretch()

        for txt, col, cmd in [("⚙", "#9ad4ff", self._show_settings),
                              ("—", "#60a0c0", self.hide),
                              ("✕", "#ff4678", self._quit)]:
            btn = QPushButton(txt)
            btn.setFixedSize(30, 26)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    color: {col}; background: transparent;
                    border: 1px solid transparent; font-size: 13px; border-radius: 7px;
                }}
                QPushButton:hover {{
                    background: {col}22; border-color: {col}88; color: white;
                }}
                QPushButton:pressed {{ background: {col}44; }}
            """)
            btn.clicked.connect(cmd)
            hdr.addWidget(btn)

        hdr_w = QWidget()
        hdr_w.setLayout(hdr); hdr_w.setStyleSheet("background: transparent;")
        hdr_w.setFixedHeight(38)
        main.addWidget(hdr_w)

        # кольцо
        ring_container = QWidget()
        ring_container.setStyleSheet("background: transparent;")
        rl = QHBoxLayout(ring_container)
        rl.setContentsMargins(0, 4, 0, 4)
        self.ring = RingWidget()
        rl.addWidget(self.ring, alignment=Qt.AlignmentFlag.AlignCenter)
        main.addWidget(ring_container)

        # график скорости — сразу под кольцом
        self.speed_graph = SpeedGraphWidget()
        main.addWidget(self.speed_graph)

        # инфо-карточка
        self.card = InfoCard()
        main.addWidget(self.card)

        # главная кнопка
        self.btn = ConnectButton()
        self.btn.clicked.connect(self._toggle_vpn)
        main.addWidget(self.btn)

        # ряд 1: ПАУЗА · ПОИСК · РЕГИОН · ИСТОРИЯ
        controls = QHBoxLayout()
        controls.setSpacing(6)

        self.btn_pause = SmallButton("⏸ ПАУЗА")
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_search = SmallButton("⟳ ПОИСК")
        self.btn_search.clicked.connect(lambda: self._start_connect(use_cache=False))
        self.btn_region = SmallButton("◎ РЕГИОН")
        self.btn_region.clicked.connect(self._show_regions)
        self.btn_history = SmallButton("☰ ИСТОРИЯ")
        self.btn_history.clicked.connect(self._show_history)

        controls.addWidget(self.btn_pause)
        controls.addWidget(self.btn_search)
        controls.addWidget(self.btn_region)
        controls.addWidget(self.btn_history)
        main.addLayout(controls)

        # консоль логов
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFixedHeight(80)
        self.console.setStyleSheet("""
            QTextEdit {
                background: rgba(6, 10, 30, 200);
                color: #7ab8e0;
                font-family: 'JetBrains Mono', 'Consolas', monospace;
                font-size: 10px;
                border: 1px solid rgba(0, 180, 255, 45);
                border-radius: 12px;
                padding: 8px 12px;
            }
            QScrollBar:vertical { background: transparent; width: 4px; }
            QScrollBar::handle:vertical { background: rgba(0,180,255,80); border-radius: 2px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        main.addWidget(self.console)

    def _tick_border(self):
        self._border_angle = (self._border_angle + 1) % 360
        self.update()

    def _connect_signals(self):
        self._log_signal.connect(self._log)
        self._connected_signal.connect(self._on_connected)
        self._disconnected_signal.connect(self._on_disconnected)
        self._status_signal.connect(lambda t, c: self.ring.set_status(t, c))

    # ── Логирование ───────────────────────────
    def _log(self, msg):
        self.console.append(f"• {msg}")
        if self.console.document().lineCount() > _LOG_MAX_LINES:
            cursor = self.console.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.select(cursor.SelectionType.LineUnderCursor)
            cursor.removeSelectedText()
        logger.info(msg)

    # ── Трей ──────────────────────────────────
    def _setup_tray(self):
        def mk(color):
            img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
            ImageDraw.Draw(img).ellipse((4, 4, 60, 60), fill=color, outline="white", width=4)
            return img

        self._tray_icons = {
            "off":   mk("#ff3333"),
            "work":  mk("#ffcc00"),
            "on":    mk("#00ff00"),
            "pause": mk("#3366ff"),
        }
        menu = (item('Развернуть', self._show_window, default=True),
                item('Регионы',    self._show_regions),
                item('Настройки',  self._show_settings),
                item('Выход',      self._quit))
        self._tray = pystray.Icon("dg4VPN", self._tray_icons["off"], "dg4VPN", menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _update_tray(self, state):
        def _do():
            if not hasattr(self, '_tray'): return
            labels = {"off":"dg4VPN: Отключен 🔴","work":"dg4VPN: В работе... 🟡",
                      "on":"dg4VPN: Подключен 🟢","pause":"dg4VPN: На паузе 🔵"}
            try:
                self._tray.icon  = self._tray_icons.get(state, self._tray_icons["off"])
                self._tray.title = labels.get(state, "dg4VPN")
                self._tray.update_menu()
            except Exception as e:
                logger.debug(f"tray: {e}")
        threading.Thread(target=_do, daemon=True).start()

    def _show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    # ── Окна-диалоги (slide-out панели) ───────
    def _panels(self):
        return [self.settings_win, self.region_win, self.history_win]

    def _close_other_panels(self, keep=None):
        for p in self._panels():
            if p is None or p is keep:
                continue
            if p.isVisible():
                slide_panel_out(p)

    def _show_history(self):
        if self.history_win is None:
            self.history_win = HistoryWindow(self)
            self.history_win.key_selected.connect(self._on_key_selected_from_history)
        if self.history_win.isVisible():
            slide_panel_out(self.history_win)
            return
        self._close_other_panels(keep=self.history_win)
        self.history_win.refresh()
        slide_panel_in(self.history_win, self, target_w=360, target_h=self.height())

    def _show_regions(self):
        if self.region_win is None:
            self.region_win = RegionWindow(self)
            self.region_win.key_selected.connect(self._on_region_selected)
        if self.region_win.isVisible():
            slide_panel_out(self.region_win)
            return
        self._close_other_panels(keep=self.region_win)
        slide_panel_in(self.region_win, self, target_w=380, target_h=self.height())
        if self.current_key:
            self.region_win.mark_active(self.current_key.get("link"))

    def _show_settings(self):
        # настройки всегда пересоздаём с актуальным CONFIG
        if self.settings_win is not None and self.settings_win.isVisible():
            slide_panel_out(self.settings_win)
            return
        self._close_other_panels(keep=None)
        self.settings_win = SettingsWindow(CONFIG, self)
        self.settings_win.settings_changed.connect(self._apply_settings_update)
        slide_panel_in(self.settings_win, self, target_w=440, target_h=self.height())

    def _apply_settings_update(self, updates):
        SettingsManager.merge_and_save(CONFIG, updates)
        self.logic.refresh_from_config()
        ToastNotifier.set_enabled(bool(CONFIG.get("notifications_enabled", True)))
        # перепривязать горячие клавиши
        if keyboard:
            self._setup_hotkeys()
        self._log("Настройки сохранены")
        ToastNotifier.info("Настройки сохранены")

    # ── Region/History callbacks ──────────────
    def _on_key_selected_from_history(self, key_data):
        self._log(f"Выбран ключ из истории: {key_data.get('name')}")
        self._start_connect_with_key(key_data)

    def _on_region_selected(self, key_data):
        if self.current_key and key_data.get("link") == self.current_key.get("link"):
            self._log("Этот узел уже активен")
            return
        flag = HistoryManager.get_flag(key_data.get("country", "??"))
        self._log(f"Переключаюсь на {flag} {key_data.get('country','??')} — {key_data.get('name','')[:25]}")
        self._start_connect_with_key(key_data)

    def _start_connect_with_key(self, key_data):
        # остановим текущий worker
        if self._worker:
            try: self._worker.stop()
            except Exception: pass
        self.ring.set_spinning(True)
        self.ring.set_status("...", "yellow")
        self.btn.set_text("ЗАПУСК...")
        self._update_tray("work")

        # strict=True — пользователь явно выбрал ключ, не подменять кэшем
        self._worker = VPNWorker(self.logic, "resume", key=key_data,
                                 use_cache=False, config=CONFIG, strict=True)
        self._wire_worker(self._worker)
        self._worker.start()

    # ── Горячие клавиши ───────────────────────
    def _setup_hotkeys(self):
        if not keyboard:
            self._log("Горячие клавиши недоступны (нужны права админа)")
            return
        # снимем старые
        for hk in self._hotkeys_registered:
            try: keyboard.remove_hotkey(hk)
            except Exception: pass
        self._hotkeys_registered = []
        try:
            if CONFIG.get("hotkey"):
                self._hotkeys_registered.append(
                    keyboard.add_hotkey(CONFIG["hotkey"], self._toggle_vpn))
            if CONFIG.get("pause_hotkey"):
                self._hotkeys_registered.append(
                    keyboard.add_hotkey(CONFIG["pause_hotkey"], self._toggle_pause))
            if CONFIG.get("regions_hotkey"):
                self._hotkeys_registered.append(
                    keyboard.add_hotkey(CONFIG["regions_hotkey"], self._show_regions))
            self._log("Горячие клавиши активны")
        except Exception as e:
            logger.warning(f"Не удалось настроить горячие клавиши: {e}")
            self._log(f"Ошибка горячих клавиш: {e}")

    # ── VPN логика ────────────────────────────
    def _toggle_vpn(self):
        if self.is_connected or self.is_paused:
            self._on_disconnected()
        else:
            self._start_connect()

    def _wire_worker(self, worker):
        worker.log_signal.connect(self._log_signal)
        worker.connected_signal.connect(self._on_worker_connected)
        worker.disconnected_signal.connect(self._on_worker_disconnected)
        worker.new_key_signal.connect(self._on_new_working_key)
        worker.scan_done_signal.connect(self._on_scan_done)

    def _start_connect(self, use_cache=True):
        self.ring.set_spinning(True)
        self.ring.set_status("...", "yellow")
        self.btn.set_text("ПОИСК...")
        self._update_tray("work")
        if not use_cache:
            self._log("Запущен полный поиск новых ключей...")

        # обнулим список регионов
        if self.region_win is not None:
            self.region_win.reset()

        self._worker = VPNWorker(self.logic, "connect", use_cache=use_cache, config=CONFIG)
        self._wire_worker(self._worker)
        self._worker.start()

    def _toggle_pause(self):
        if not self.current_key:
            return
        if not self.is_paused:
            self._log("Пауза (ключ сохранен)")
            if self._worker:
                self._worker._kill_hiddify()
            SystemManager.set_proxy(False)
            with self._lock:
                self.is_paused    = True
                self.is_connected = False
            self.ring.set_status("||", "yellow")
            self.ring.set_spinning(False)
            self.card.set_row("status", "ПАУЗА", "#00c8ff")
            self.btn.set_text("ВОЗОБНОВИТЬ")
            self.btn_pause.set_text("▶ ПУСК")
            self._update_tray("pause")
            ToastNotifier.paused()
        else:
            with self._lock:
                self.is_paused = False
            self._log("Возобновление...")
            self.ring.set_spinning(True)
            self.ring.set_status("...", "yellow")
            self.btn.set_text("ЗАПУСК...")
            self.btn_pause.set_text("⏸ ПАУЗА")
            self._update_tray("work")

            with self._lock:
                key = self.current_key
            self._worker = VPNWorker(self.logic, "resume", key=key, config=CONFIG)
            self._wire_worker(self._worker)
            self._worker.start()

    def _on_worker_connected(self, key_data):
        self._connected_signal.emit(key_data)

    def _on_worker_disconnected(self):
        self._disconnected_signal.emit()

    def _on_new_working_key(self, key_data):
        """Прилетел рабочий ключ из фонового сканирования."""
        if self.region_win is not None:
            self.region_win.add_key(key_data)

    def _on_scan_done(self):
        if self.region_win is not None:
            # пометить, что фоновый поиск завершён
            self.region_win.status_label.setText(
                self.region_win.status_label.text() + " ✓")

    def _on_connected(self, key_data):
        with self._lock:
            self.current_key  = key_data
            self.is_connected = True

        HistoryManager.save_key(key_data)

        # добавим активный ключ в окно регионов (если открыто)
        if self.region_win is not None:
            self.region_win.add_key(key_data)
            self.region_win.mark_active(key_data.get("link"))

        self.ring.set_spinning(False)
        self.ring.set_status("ON", "green")
        self.card.set_row("status",  "ЗАЩИЩЕНО", "#32f0a0")
        flag = HistoryManager.get_flag(key_data.get("country", "??"))
        self.card.set_row("country", f"{flag} {key_data.get('country','??').upper()}")
        ping = key_data.get("latency")
        self.card.set_row("ping",    f"{ping} МС" if ping else "< 2000 МС", "#32f0a0")
        self.btn.set_text("ОТКЛЮЧИТЬ")
        self._update_tray("on")
        self.start_time = time.time()
        self.speed_graph.reset()

        ToastNotifier.connected(key_data.get("country", "??"), ping)

    def _on_disconnected(self):
        was_connected = self.is_connected or self.is_paused
        with self._lock:
            self.is_connected = False
            self.is_paused    = False
        self.ring.set_spinning(False)
        self.ring.set_status("OFF", "red")
        self.card.set_row("status",  "ОТКЛЮЧЕН",   "#ff4678")
        self.card.set_row("country", "—",           "#7ab8e0")
        self.card.set_row("ping",    "—",           "#7ab8e0")
        self.btn.set_text("ПОДКЛЮЧИТЬ")
        self.btn_pause.set_text("⏸ ПАУЗА")
        self._update_tray("off")
        self._log("Отключено")
        if self._worker:
            try: self._worker.stop()
            except Exception: pass
            self._worker._kill_hiddify()
        SystemManager.set_proxy(False)
        if was_connected:
            ToastNotifier.disconnected()

    def _hide_all_panels(self):
        for panel in (self.settings_win, self.region_win, self.history_win):
            if panel is None:
                continue
            try:
                if panel.isVisible():
                    panel.hide()
            except Exception:
                pass

    def hideEvent(self, e):
        # когда главное окно сворачивается — прячем шторки тоже
        super().hideEvent(e)
        self._hide_all_panels()

    def _quit(self):
        self.ring.set_spinning(False)
        self._hide_all_panels()
        if self._worker:
            try: self._worker.stop()
            except Exception: pass
            self._worker._kill_hiddify()
        set_system_proxy(False)
        if hasattr(self, '_tray'):
            try: self._tray.stop()
            except Exception: pass
        QApplication.quit()


# ──────────────────────────────────────────────
def _load_bundled_fonts(app):
    """Подгрузить локальный Lexend, чтобы UI не зависел от того, установлен
    ли шрифт в системе. Без этого на чистых Windows Qt падает на стандартный
    растровый fallback (Arial/Tahoma в малых кеглях рендерится «крошкой»)."""
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
    if not os.path.isdir(base):
        return
    loaded_family = None
    for fname in sorted(os.listdir(base)):
        if not fname.lower().endswith((".ttf", ".otf")):
            continue
        fid = QFontDatabase.addApplicationFont(os.path.join(base, fname))
        if fid < 0:
            logger.debug(f"Не удалось загрузить шрифт {fname}")
            continue
        families = QFontDatabase.applicationFontFamilies(fid)
        if families and loaded_family is None:
            loaded_family = families[0]
    if loaded_family:
        # ставим как дефолтный шрифт приложения — каскадно подхватится
        # любым QLabel / QPushButton / стилем, где явно не переопределён
        f = QFont(loaded_family, 10)
        f.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        app.setFont(f)
        logger.info(f"Загружен шрифт интерфейса: {loaded_family}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _load_bundled_fonts(app)
    window = dg4VPNApp()
    window.show()
    sys.exit(app.exec())
