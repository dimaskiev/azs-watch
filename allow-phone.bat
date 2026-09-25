@echo off
setlocal
chcp 65001 >nul
title AZS WATCH // iPhone access

net session >nul 2>&1
if %errorlevel% neq 0 (
  echo   Потрібні права адміністратора, щоб відкрити порт для iPhone.
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

echo.
echo   Відкриваю порт 8765 у фаєрволі Windows...
netsh advfirewall firewall delete rule name="AZS WATCH" >nul 2>&1
netsh advfirewall firewall add rule name="AZS WATCH" dir=in action=allow protocol=TCP localport=8765 enable=yes profile=any
if %errorlevel% neq 0 (
  echo   [!] Не вдалося додати правило.
  pause
  exit /b 1
)

echo   OK. Тепер:
echo     1. Залиште ПК увімкненим і запустіть start.bat
echo     2. iPhone і ПК — одна Wi-Fi, не мобільний інтернет
echo     3. На екрані панелі з'явиться адреса і QR для Safari
echo.
pause
