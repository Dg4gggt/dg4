@echo off
cd /d "%~dp0"
echo Установка зависимостей для dg4VPN...
pip install Pillow pystray keyboard requests PyQt6 psutil winotify --user
echo.
if %errorlevel% neq 0 (
    echo [!] Ошибка при установке через pip. Попробуйте запустить терминал от имени администратора.
) else (
    echo [OK] Все библиотеки установлены успешно.
)
pause
