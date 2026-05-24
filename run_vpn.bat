@echo off
:: Переходим в папку, где лежит этот bat-файл (нужно для запуска от Админа)
cd /d "%~dp0"

title Cyber-VPN Launcher
echo Запуск Cyber-VPN Менеджера...
echo.
echo Для работы горячих клавиш (Ctrl+Alt+B) и запуска VPN через HiddifyCli
echo этот скрипт желательно запускать от имени Администратора.
echo.

python vpn_app.py
if %errorlevel% neq 0 (
    echo.
    echo [!] Произошла ошибка при запуске приложения.
    echo Убедитесь, что Python установлен и библиотеки скачаны через install_deps.bat.
    pause
)
