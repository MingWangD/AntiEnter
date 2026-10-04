@echo off
chcp 65001 >nul
title AntiEnter for Windows
echo ==================================================
echo         AntiEnter Windows 自动回车启动器          
echo ==================================================
echo 正在启动 AntiEnter（桌面端 + CLI 双端全自动模式）...
echo.

where python >nul 2>nul
if %errorlevel% equ 0 (
    python "%~dp0src\main.py" start
) else (
    where py >nul 2>nul
    if %errorlevel% equ 0 (
        py "%~dp0src\main.py" start
    ) else (
        echo [错误] 系统未检测到 Python，请先安装 Python 3.9+ 并勾选 "Add to PATH"。
    )
)

echo.
pause
