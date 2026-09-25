@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title AZS WATCH // ARMY+

echo.
echo   ╔══════════════════════════════════════════╗
echo   ║  AZS WATCH   tactical fuel monitor       ║
echo   ║  Армія+ Плюси  ·  miltec dashboard       ║
echo   ╚══════════════════════════════════════════╝
echo.

where python >nul 2>&1
if %errorlevel%==0 (
  set "PY=python"
) else (
  where py >nul 2>&1
  if %errorlevel%==0 (
    set "PY=py"
  ) else (
    echo   [!] Python не знайдено. Встановіть Python 3 з https://www.python.org/downloads/
    echo       Під час встановлення позначте "Add python.exe to PATH".
    pause
    exit /b 1
  )
)

echo   [*] ПК:      http://127.0.0.1:8765
echo   [*] iPhone:  та сама Wi-Fi, QR на панелі
echo   [*] Якщо телефон не відкриває — один раз allow-phone.bat
echo   [*] Зупинка: закрийте це вікно або Ctrl+C
echo.
netsh advfirewall firewall show rule name="AZS WATCH" >nul 2>&1
if errorlevel 1 (
  echo   [!] Фаєрвол ще не відкритий для iPhone. Запустіть allow-phone.bat від адміністратора.
  echo.
)
set PYTHONUNBUFFERED=1
%PY% server.py --port 8765
if errorlevel 1 pause
