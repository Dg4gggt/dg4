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

# ──────────────────────────────────────────────
#  УПРАВЛЕНИЕ СИСТЕМОЙ (ПРОКСИ И ПРОЦЕССЫ)
# ──────────────────────────────────────────────
class SystemManager:
    @staticmethod
    def enable_blur(hwnd, color=0x20100A32):
        """Включает нативный эффект размытия Windows (Acrylic/BlurBehind)."""
        try:
            from ctypes import windll, c_int, byref, Structure, sizeof, POINTER, c_void_p
            
            class AccentPolicy(Structure):
                _fields_ = [
                    ('AccentState', c_int),
                    ('AccentFlags', c_int),
                    ('GradientColor', c_int),
                    ('AnimationId', c_int)
                ]

            class WindowCompositionAttributeData(Structure):
                _fields_ = [
                    ('Attribute', c_int),
                    ('Data', POINTER(AccentPolicy)),
                    ('SizeOfData', c_int)
                ]

            accent = AccentPolicy()
            accent.AccentState = 3  # ACCENT_ENABLE_BLURBEHIND (или 4 для Acrylic)
            accent.GradientColor = color # ABGR формат

            data = WindowCompositionAttributeData()
            data.Attribute = 19  # WCA_ACCENT_POLICY
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
            
            # Оповещаем систему об изменениях
            ctypes.windll.Wininet.InternetSetOptionW(0, 39, 0, 0)
            ctypes.windll.Wininet.InternetSetOptionW(0, 37, 0, 0)
            logger.info(f"Системный прокси {'включен' if enable else 'выключен'}")
        except Exception as e:
            logger.error(f"Ошибка при настройке прокси: {e}")

    @staticmethod
    def kill_hiddify():
        try:
            # Сначала пробуем мягко через taskkill
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

# ──────────────────────────────────────────────
#  PyQt6
# ──────────────────────────────────────────────
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QTextEdit, QFrame, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QPoint, QPropertyAnimation,
    QEasingCurve, QRect, pyqtProperty, QObject
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient,
    QRadialGradient, QFont, QPainterPath, QConicalGradient,
    QFontDatabase
)

# ──────────────────────────────────────────────
#  КОНФИГУРАЦИЯ
# ──────────────────────────────────────────────
CONFIG = {
    "hotkey": "ctrl+alt+b",
    "pause_hotkey": "ctrl+alt+p",
    "excluded_countries": ["RU", "BY"],
    "priority_protocols": ["reality", "vless", "trojan"],
    "hiddify_cli": os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "vpn_launcher", "HiddifyCli.exe"
    )
}

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
            # Добавляем временную метку
            key_data["timestamp"] = time.time()
            
            # Уникальность по ссылке
            history = [k for k in history if k['link'] != key_data['link']]
            history.insert(0, key_data)
            
            # Ограничиваем историю (например, последние 50)
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
                    # Фильтруем ключи старше 24 часов
                    now = time.time()
                    history = [k for k in history if now - k.get("timestamp", 0) < 86400]
                    return history
        except Exception: pass
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
        # Конвертация кода страны в эмодзи флаг
        try:
            return "".join(chr(127397 + ord(c)) for c in country_code.upper())
        except:
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
#  WORKER THREAD — запускает логику в фоне
# ──────────────────────────────────────────────
class VPNWorker(QThread):
    log_signal       = pyqtSignal(str)
    connected_signal = pyqtSignal(dict)
    disconnected_signal = pyqtSignal()
    status_signal    = pyqtSignal(str, str)   # text, color_name

    def __init__(self, logic, action, key=None, use_cache=True):
        super().__init__()
        self.logic  = logic
        self.action = action   # "connect" | "resume"
        self.key    = key
        self.use_cache = use_cache
        self._lock  = threading.Lock()
        self.vpn_process = None

    def run(self):
        if self.action == "connect":
            self._connect()
        elif self.action == "resume":
            self._resume()

    def _connect(self):
        self.status_signal.emit("...", "yellow")
        self.log_signal.emit("Поиск лучших узлов...")

        # Кэш (используем только если use_cache=True)
        if self.use_cache:
            cached = self._load_cache()
            if cached:
                self.log_signal.emit("Пробую последний рабочий ключ...")
                if self._try_key(cached):
                    self._save_cache(cached)
                    self.connected_signal.emit(cached)
                    return
                self.log_signal.emit("Кэш устарел, ищу новые...")
        else:
            self.log_signal.emit("Сканирую свежие ключи из источников...")

        best_keys = self.logic.get_best_keys(callback_log=self.log_signal.emit)
        if not best_keys:
            self.log_signal.emit("Ключи не найдены")
            self.disconnected_signal.emit()
            return

        for i, key_data in enumerate(best_keys[:15]):
            self.log_signal.emit(f"Тест узла {i+1}...")
            self._kill_hiddify()
            if self._try_key(key_data):
                self._save_cache(key_data)
                self.connected_signal.emit(key_data)
                return

        self.log_signal.emit("Нет рабочих узлов")
        self.disconnected_signal.emit()

    def _resume(self):
        self.status_signal.emit("...", "yellow")
        if self.key and self._try_key(self.key):
            self._save_cache(self.key)
            self.connected_signal.emit(self.key)
            return
        self.log_signal.emit("Сбой возобновления, ищу новый...")
        self._connect()

    def _try_key(self, key_data) -> bool:
        SystemManager.kill_hiddify()
        if not self._start_hiddify(key_data):
            return False
        SystemManager.set_proxy(True, "127.0.0.1", 12334)
        
        # Защищенная проверка доступности прокси через методы vpn_logic
        gpt_ok = False
        try:
            if hasattr(self.logic, 'check_chatgpt_via_proxy'):
                gpt_ok, _ = self.logic.check_chatgpt_via_proxy()
            elif hasattr(self.logic, 'check_gemini_via_proxy'):
                gpt_ok, _ = self.logic.check_gemini_via_proxy()
            else:
                # Если методов проверки нет, делаем базовый запрос как fallback
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
                # Используем создание процесса в отдельной группе, чтобы легче управлять
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
                # Пробуем мягко завершить группу процессов
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
        except Exception: pass

    def _load_cache(self):
        try:
            if os.path.exists(_CACHE_FILE):
                with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception: pass
        return None


# ──────────────────────────────────────────────
#  КОЛЬЦО СТАТУСА  (двойная орбита + частицы)
# ──────────────────────────────────────────────
class RingWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(240, 240)
        self._status_text  = "OFF"
        self._status_color = C["red"]
        self._angle        = 0          # угол спиннера
        self._orbit2       = 0          # вторая орбита (обратная)
        self._spinning     = False
        self._pulse        = 0.0        # 0..1 для pulsing glow
        self._pulse_dir    = 1
        self._particles    = []         # [(angle, radius, alpha, speed)]
        self._border_pos   = 0.0

        self._spin_timer = QTimer(self)
        self._spin_timer.timeout.connect(self._tick_spin)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._tick_pulse)
        self._pulse_timer.start(20)

        self._border_timer = QTimer(self)
        self._border_timer.timeout.connect(self._tick_border)
        self._border_timer.start(16)

    def set_status(self, text, color_name):
        self._status_text  = text
        self._status_color = C.get(color_name, C["red"])
        # Перезапускаем частицы при смене статуса
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
        """Запускаем всплеск частиц при смене статуса."""
        import random
        self._particles = [
            [random.uniform(0, 360), random.uniform(60, 90),
             255, random.uniform(1.5, 3.5)]
            for _ in range(18)
        ]

    def _tick_spin(self):
        self._angle   = (self._angle  + 4)   % 360
        self._orbit2  = (self._orbit2 - 2.5) % 360
        # Обновляем частицы
        alive = []
        for p in self._particles:
            p[1] += p[3]          # radius растёт
            p[2] = max(0, p[2] - 8)  # fade
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
        cx, cy, r = 120, 120, 88

        # ── Частицы (позади всего) ──
        for pt in self._particles:
            ang, rad, alpha, _ = pt
            px = cx + rad * math.cos(math.radians(ang))
            py = cy + rad * math.sin(math.radians(ang))
            pc = QColor(self._status_color); pc.setAlpha(int(alpha * 0.8))
            p.setBrush(QBrush(pc)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(int(px-3), int(py-3), 6, 6)

        # ── Внешнее pulsing glow ──
        glow_r = r + 28 + int(self._pulse * 14)
        glow = QRadialGradient(cx, cy, glow_r)
        gc = QColor(self._status_color)
        gc.setAlpha(int(30 + self._pulse * 25))
        glow.setColorAt(0, gc)
        glow.setColorAt(0.6, QColor(gc.red(), gc.green(), gc.blue(), int(gc.alpha()*0.3)))
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(glow)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(cx - glow_r, cy - glow_r, glow_r * 2, glow_r * 2)

        # ── Фоновый glass-круг ──
        bg_grad = QRadialGradient(cx, cy, r)
        bg_grad.setColorAt(0, QColor(20, 30, 70, 210))
        bg_grad.setColorAt(0.6, QColor(10, 16, 45, 220))
        bg_grad.setColorAt(1, QColor(6, 8, 24, 240))
        p.setBrush(QBrush(bg_grad)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # ── Внутренний glass-блик (сверху) ──
        hi_grad = QLinearGradient(cx - r, cy - r, cx + r, cy)
        hi_grad.setColorAt(0, QColor(255, 255, 255, 18))
        hi_grad.setColorAt(1, QColor(255, 255, 255, 0))
        hi_path = QPainterPath()
        hi_path.addEllipse(cx - r + 2, cy - r + 2, r * 2 - 4, r - 4)
        p.fillPath(hi_path, QBrush(hi_grad))

        # ── Орбита 1: бегущая дуга (циан) ──
        pen1 = QPen(C["accent"]); pen1.setWidth(2)
        pen1.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen1); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(cx-r-6, cy-r-6, (r+6)*2, (r+6)*2,
                  int(self._border_pos * 16), 80 * 16)

        # ── Орбита 2: обратная дуга (фиолетовая) ──
        pen2 = QPen(C["accent2"]); pen2.setWidth(2)
        pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen2); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(cx-r-6, cy-r-6, (r+6)*2, (r+6)*2,
                  int(self._orbit2 * 16), 50 * 16)

        # ── Кольца статуса ──
        for radius, width, alpha in [(r, 2, 220), (r-16, 4, 160), (r-26, 1, 60)]:
            col = QColor(self._status_color); col.setAlpha(alpha)
            p.setPen(QPen(col, width)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(cx-radius, cy-radius, radius*2, radius*2)

        # ── Спиннер (светящаяся капля) ──
        if self._spinning:
            for offset, size, alpha in [(0, 10, 240), (-18, 7, 140), (-36, 5, 70)]:
                ang = self._angle + offset
                sx = cx + (r - 10) * math.cos(math.radians(ang))
                sy = cy + (r - 10) * math.sin(math.radians(ang))
                sc = QColor(C["accent"]); sc.setAlpha(alpha)
                p.setBrush(QBrush(sc)); p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(int(sx-size//2), int(sy-size//2), size, size)
            # Вторая капля обратного направления
            for offset, size, alpha in [(0, 8, 180), (-22, 5, 100)]:
                ang = self._orbit2 + offset
                sx = cx + (r - 10) * math.cos(math.radians(ang))
                sy = cy + (r - 10) * math.sin(math.radians(ang))
                sc = QColor(C["accent2"]); sc.setAlpha(alpha)
                p.setBrush(QBrush(sc)); p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(int(sx-size//2), int(sy-size//2), size, size)

        # ── Центральный текст ──
        p.setPen(QPen(self._status_color))
        font = QFont("Lexend", 24, QFont.Weight.Bold)
        p.setFont(font)
        p.drawText(QRect(cx-70, cy-22, 140, 44),
                   Qt.AlignmentFlag.AlignCenter, self._status_text)

        p.end()


# ──────────────────────────────────────────────
#  КАРТОЧКА ИНФО — горизонтальные плитки (glass)
# ──────────────────────────────────────────────
class InfoCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(86)
        self._hover = False
        self._hover_alpha = 0
        self._shimmer = 0.0       # 0..1 бегущий блик
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

        # Glass фон
        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0, QColor(18, 26, 72, 200 + self._hover_alpha // 6))
        grad.setColorAt(0.5, QColor(12, 20, 58, 185))
        grad.setColorAt(1, QColor(8, 14, 40, 195))
        p.fillPath(path, QBrush(grad))

        # Бегущий блик (shimmer) по горизонтали при hover
        if self._hover_alpha > 0 and self._shimmer > 0:
            sx = int(self._shimmer * (w + 80)) - 80
            shimmer_grad = QLinearGradient(sx, 0, sx + 80, 0)
            shimmer_grad.setColorAt(0,   QColor(255, 255, 255, 0))
            shimmer_grad.setColorAt(0.5, QColor(255, 255, 255, int(14 * self._hover_alpha / 255)))
            shimmer_grad.setColorAt(1,   QColor(255, 255, 255, 0))
            p.fillPath(path, QBrush(shimmer_grad))

        # Разделители между плитками
        p.setPen(QPen(QColor(0, 180, 255, 30), 1))
        tile_w = w // 3
        for i in (1, 2):
            p.drawLine(tile_w * i, 12, tile_w * i, h - 12)

        # Рамка
        border_alpha = 55 + int(self._hover_alpha * 0.7)
        pen = QPen(QColor(0, 200, 255, border_alpha), 1)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # Top highlight
        hi = QPainterPath()
        hi.addRoundedRect(1, 1, w - 2, h // 2, 14, 14)
        p.fillPath(hi, QColor(255, 255, 255, 10 + self._hover_alpha // 14))
        p.end()


# ──────────────────────────────────────────────
#  КНОПКА ПОДКЛЮЧЕНИЯ — широкая, pill-форма, ripple-анимация
# ──────────────────────────────────────────────
class ConnectButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._text  = "ПОДКЛЮЧИТЬ"
        self._hover = False
        self._press = False
        self._glow  = 0.0
        self._ripple_r   = 0.0          # радиус ripple
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
            self._ripple_r    += 6
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
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, h // 2, h // 2)

        # Градиент фона — циан→фиолетовый
        g = QLinearGradient(0, 0, w, h)
        if self._press:
            g.setColorAt(0, QColor(0,  140, 200))
            g.setColorAt(1, QColor(100, 20, 180))
        else:
            t = self._glow
            g.setColorAt(0, QColor(int(0   + 20*t),  int(170 + 30*t), int(240 + 10*t)))
            g.setColorAt(1, QColor(int(100 + 40*t),  int(20  + 10*t), int(200 + 30*t)))
        p.fillPath(path, QBrush(g))

        # Ripple
        if self._ripple_r > 0 and self._ripple_alpha > 0:
            p.setClipPath(path)
            rc = QColor(255, 255, 255, int(self._ripple_alpha))
            p.setBrush(QBrush(rc)); p.setPen(Qt.PenStyle.NoPen)
            rr = int(self._ripple_r)
            p.drawEllipse(self._ripple_x - rr, self._ripple_y - rr, rr*2, rr*2)
            p.setClipping(False)

        # Glow снаружи
        if self._glow > 0:
            for i in range(1, 4):
                gp = QPainterPath()
                gp.addRoundedRect(-i*2, -i*2, w+i*4, h+i*4, h//2+i*2, h//2+i*2)
                gc2 = QColor(0, 200, 255, int(28 * self._glow / i))
                p.setPen(QPen(gc2, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(gp)

        # Glass-блик
        hi = QPainterPath()
        hi.addRoundedRect(4, 2, w-8, h//2-2, h//2-2, h//2-2)
        p.fillPath(hi, QColor(255, 255, 255, int(28 + 12*self._glow)))

        # Текст
        p.setPen(QColor(255, 255, 255))
        font = QFont("Lexend", 11, QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        p.setFont(font)
        p.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, self._text)
        p.end()


# ──────────────────────────────────────────────
#  МАЛАЯ КНОПКА — с анимированной заливкой
# ──────────────────────────────────────────────
class SmallButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, icon_text, parent=None):
        super().__init__(parent)
        self.setFixedSize(108, 38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._text  = icon_text
        self._hover = False
        self._press = False
        self._fill  = 0.0       # 0..1 fill animation
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
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, 10, 10)

        # Фон: от тёмного к cyan при hover
        bg = QLinearGradient(0, 0, w, h)
        bg.setColorAt(0, QColor(16, 24, 60, int(160 + 60*self._fill)))
        bg.setColorAt(1, QColor(8,  16, 45, int(150 + 50*self._fill)))
        p.fillPath(path, QBrush(bg))

        # Цветная заливка снизу вверх при hover
        if self._fill > 0:
            fill_h = int(h * self._fill)
            clip = QPainterPath()
            clip.addRoundedRect(0, h - fill_h, w, fill_h, 10 if fill_h >= h else 0, 10 if fill_h >= h else 0)
            fill_grad = QLinearGradient(0, h, 0, h - fill_h)
            fill_grad.setColorAt(0, QColor(0, 180, 255, int(80 * self._fill)))
            fill_grad.setColorAt(1, QColor(120, 40, 255, int(60 * self._fill)))
            p.fillPath(clip, QBrush(fill_grad))

        # Рамка
        bc = QColor(0, 200, 255, int(50 + 130 * self._fill))
        if self._press: bc = QColor(0, 220, 255, 220)
        p.setPen(QPen(bc, 1.2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # Текст
        tc = QColor(int(200 + 55*self._fill), int(230 + 25*self._fill), 255)
        p.setPen(tc)
        p.setFont(QFont("Lexend", 9, QFont.Weight.Bold))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)
        p.end()

# ──────────────────────────────────────────────
#  ОКНО ИСТОРИИ
# ──────────────────────────────────────────────
from PyQt6.QtWidgets import QDialog, QScrollArea, QListWidget, QListWidgetItem

class HistoryWindow(QDialog):
    key_selected = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("История ключей")
        self.setFixedSize(360, 450)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Контейнер с фоном
        self.container = QFrame()
        self.container.setObjectName("HistoryContainer")
        self.container.setStyleSheet("""
            #HistoryContainer {
                background: rgba(6, 10, 28, 245);
                border: 1px solid rgba(0, 180, 255, 90);
                border-radius: 20px;
            }
        """)
        container_layout = QVBoxLayout(self.container)
        
        title_row = QHBoxLayout()
        title = QLabel("ИСТОРИЯ УЗЛОВ")
        title.setStyleSheet("color: #00d2ff; font-family: Lexend; font-size: 14px; font-weight: bold; letter-spacing: 1px;")
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setStyleSheet("color: #94a3b8; background: transparent; border: none; font-size: 16px;")
        close_btn.clicked.connect(self.close)
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(close_btn)
        container_layout.addLayout(title_row)

        self.list = QListWidget()
        self.list.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item {
                background: rgba(10, 16, 48, 180);
                border-radius: 12px;
                margin-bottom: 8px;
                padding: 10px;
                border: 1px solid rgba(0, 160, 255, 30);
            }
            QListWidget::item:hover {
                background: rgba(0, 40, 80, 200);
                border-color: rgba(0, 200, 255, 80);
            }
        """)
        self.list.itemClicked.connect(self._on_item_clicked)
        container_layout.addWidget(self.list)
        
        layout.addWidget(self.container)
        self.refresh()

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
        self.close()

    def mousePressEvent(self, e):
        self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if hasattr(self, '_drag_pos'):
            self.move(e.globalPosition().toPoint() - self._drag_pos)


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
        self.is_connected= False
        self.current_key = None
        self.start_time  = None
        self._worker     = None
        self._drag_pos   = None
        self._blur_pixmap = None

        self._setup_window()
        self._setup_ui()
        self._connect_signals()

        if pystray:
            self._setup_tray()
        if keyboard:
            self._setup_hotkeys()

        if not is_admin():
            self._log("⚠ ЗАПУСТИТЕ ОТ АДМИНА!")

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
        self.resize(400, 650)
        self._center()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_mask()

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
        # Включаем нативный блюр через Windows API
        SystemManager.enable_blur(self.winId())

    def moveEvent(self, e):
        super().moveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, 24, 24)
        p.setClipPath(path)

        # Тёмно-синий glass-оверлей поверх нативного блюра
        overlay = QLinearGradient(0, 0, 0, h)
        overlay.setColorAt(0.0, QColor(8,  12, 34, 175))
        overlay.setColorAt(0.5, QColor(6,  10, 28, 185))
        overlay.setColorAt(1.0, QColor(4,  8,  22, 195))
        p.fillRect(0, 0, w, h, QBrush(overlay))

        # Радиальный акцент в центре (слабый свет сверху)
        radial = QRadialGradient(w / 2, 0, w * 0.8)
        radial.setColorAt(0,   QColor(0, 180, 255, 22))
        radial.setColorAt(0.5, QColor(0, 120, 200, 10))
        radial.setColorAt(1,   QColor(0,   0,   0,  0))
        p.fillRect(0, 0, w, h, QBrush(radial))

        p.setClipping(False)

        # Рамка — вращающийся конический градиент (циан + фиолет)
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
        main.setSpacing(10)

        # ── Заголовок ──────────────────────────
        hdr = QHBoxLayout()
        hdr.setContentsMargins(8, 2, 4, 2)

        # Логотип с animated dot
        logo_w = QWidget(); logo_w.setFixedSize(100, 32)
        logo_w.setStyleSheet("background: transparent;")

        dot = QLabel("◉")
        dot.setStyleSheet(
            "color: #00d2ff; font-size: 13px; background: transparent; padding-right: 2px;")
        title = QLabel("dg4VPN")
        title.setStyleSheet(
            "color: #dce8ff; font-family: Lexend; font-size: 14px; "
            "font-weight: bold; letter-spacing: 1px; background: transparent;")
        logo_row = QHBoxLayout(logo_w)
        logo_row.setContentsMargins(0,0,0,0); logo_row.setSpacing(4)
        logo_row.addWidget(dot); logo_row.addWidget(title)

        hdr.addWidget(logo_w)
        hdr.addStretch()

        for txt, col, cmd in [("—", "#60a0c0", self.hide),
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

        # ── Кольцо ────────────────────────────
        ring_container = QWidget()
        ring_container.setStyleSheet("background: transparent;")
        rl = QHBoxLayout(ring_container)
        rl.setContentsMargins(0, 4, 0, 4)
        self.ring = RingWidget()
        rl.addWidget(self.ring, alignment=Qt.AlignmentFlag.AlignCenter)
        main.addWidget(ring_container)

        # ── Инфо-карточка ──────────────────────
        self.card = InfoCard()
        main.addWidget(self.card)

        # ── Главная кнопка ────────────────────
        self.btn = ConnectButton()
        self.btn.clicked.connect(self._toggle_vpn)
        main.addWidget(self.btn)

        # ── Три малые кнопки в ряд ────────────
        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.btn_pause   = SmallButton("⏸  ПАУЗА")
        self.btn_pause.clicked.connect(self._toggle_pause)

        self.btn_search  = SmallButton("⟳  ПОИСК")
        self.btn_search.clicked.connect(lambda: self._start_connect(use_cache=False))

        self.btn_history = SmallButton("☰  ИСТОРИЯ")
        self.btn_history.clicked.connect(self._show_history)

        controls.addWidget(self.btn_pause)
        controls.addWidget(self.btn_search)
        controls.addWidget(self.btn_history)
        main.addLayout(controls)

        # ── Консоль логов ─────────────────────
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFixedHeight(82)
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
            QScrollBar:vertical {
                background: transparent; width: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(0,180,255,80); border-radius: 2px;
            }
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

    def _show_history(self):
        if not hasattr(self, 'history_win'):
            self.history_win = HistoryWindow(self)
            self.history_win.key_selected.connect(self._on_key_selected_from_history)
        
        # Центрируем относительно главного окна
        self.history_win.refresh()
        self.history_win.move(self.x() + (self.width() - self.history_win.width()) // 2,
                             self.y() + (self.height() - self.history_win.height()) // 2)
        self.history_win.show()

    def _on_key_selected_from_history(self, key_data):
        self._log(f"Выбран ключ из истории: {key_data.get('name')}")
        self._start_connect_with_key(key_data)

    def _start_connect_with_key(self, key_data):
        self.ring.set_spinning(True)
        self.ring.set_status("...", "yellow")
        self.btn.set_text("ЗАПУСК...")
        self._update_tray("work")
        
        self._worker = VPNWorker(self.logic, "resume", key=key_data)
        self._worker.log_signal.connect(self._log_signal)
        self._worker.connected_signal.connect(self._on_worker_connected)
        self._worker.disconnected_signal.connect(self._on_worker_disconnected)
        self._worker.start()

    # ── Горячие клавиши ───────────────────────
    def _setup_hotkeys(self):
        if keyboard:
            try:
                keyboard.add_hotkey(CONFIG["hotkey"],       self._toggle_vpn)
                keyboard.add_hotkey(CONFIG["pause_hotkey"], self._toggle_pause)
                self._log("Горячие клавиши активны")
            except Exception as e:
                logger.warning(f"Не удалось настроить горячие клавиши: {e}")
        else:
            self._log("Горячие клавиши недоступны (нужны права админа)")

    # ── VPN логика ────────────────────────────
    def _toggle_vpn(self):
        if self.is_connected or self.is_paused:
            self._on_disconnected()
        else:
            self._start_connect()

    def _start_connect(self, use_cache=True):
        self.ring.set_spinning(True)
        self.ring.set_status("...", "yellow")
        self.btn.set_text("ПОИСК...")
        self._update_tray("work")
        if not use_cache:
            self._log("Запущен полный поиск новых ключей...")

        self._worker = VPNWorker(self.logic, "connect", use_cache=use_cache)
        self._worker.log_signal.connect(self._log_signal)
        self._worker.connected_signal.connect(self._on_worker_connected)
        self._worker.disconnected_signal.connect(self._on_worker_disconnected)
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
            self.btn_pause.set_text("ПУСК")
            self._update_tray("pause")
        else:
            with self._lock:
                self.is_paused = False
            self._log("Возобновление...")
            self.ring.set_spinning(True)
            self.ring.set_status("...", "yellow")
            self.btn.set_text("ЗАПУСК...")
            self.btn_pause.set_text("ПАУЗА")
            self._update_tray("work")

            with self._lock:
                key = self.current_key
            self._worker = VPNWorker(self.logic, "resume", key=key)
            self._worker.log_signal.connect(self._log_signal)
            self._worker.connected_signal.connect(self._on_worker_connected)
            self._worker.disconnected_signal.connect(self._on_worker_disconnected)
            self._worker.start()

    def _on_worker_connected(self, key_data):
        self._connected_signal.emit(key_data)

    def _on_worker_disconnected(self):
        self._disconnected_signal.emit()

    def _on_connected(self, key_data):
        with self._lock:
            self.current_key  = key_data
            self.is_connected = True
        
        # Сохраняем в историю
        HistoryManager.save_key(key_data)
        
        self.ring.set_spinning(False)
        self.ring.set_status("ON", "green")
        self.card.set_row("status",  "ЗАЩИЩЕНО",                               "#32f0a0")
        flag = HistoryManager.get_flag(key_data.get("country", "??"))
        self.card.set_row("country", f"{flag} {key_data.get('country','??').upper()}")
        ping = key_data.get("latency")
        self.card.set_row("ping",    f"{ping} МС" if ping else "< 2000 МС", "#32f0a0")
        self.btn.set_text("ОТКЛЮЧИТЬ")
        self._update_tray("on")
        self.start_time = time.time()

    def _on_disconnected(self):
        with self._lock:
            self.is_connected = False
            self.is_paused    = False
        self.ring.set_spinning(False)
        self.ring.set_status("OFF", "red")
        self.card.set_row("status",  "ОТКЛЮЧЕН",   "#ff4678")
        self.card.set_row("country", "—",           "#7ab8e0")
        self.card.set_row("ping",    "—",           "#7ab8e0")
        self.btn.set_text("ПОДКЛЮЧИТЬ")
        self.btn_pause.set_text("ПАУЗА")
        self._update_tray("off")
        self._log("Отключено")
        if self._worker:
            self._worker._kill_hiddify()
        SystemManager.set_proxy(False)

    def _quit(self):
        self.ring.set_spinning(False)
        if self._worker:
            self._worker._kill_hiddify()
        set_system_proxy(False)
        if hasattr(self, '_tray'):
            try: self._tray.stop()
            except Exception: pass
        QApplication.quit()


# ──────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = dg4VPNApp()
    window.show()
    sys.exit(app.exec())