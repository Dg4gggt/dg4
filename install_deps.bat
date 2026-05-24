@echo off
cd /d "%~dp0"
echo Установка зависимостей для Cyber-VPN...
pip install Pillow pystray keyboard requests --user
echo.
if %errorlevel% neq 0 (
    echo [!] Ошибка при установке через pip. Попробуйте запустить терминал от имени администратора.
) else (
    echo [OK] Все библиотеки установлены успешно.
)
pause
