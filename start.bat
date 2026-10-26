@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo  Whale-chan QQ Bot
echo ========================================
.venv\Scripts\python.exe bot.py
echo.
echo [Bot stopped] press any key to exit
pause >nul
