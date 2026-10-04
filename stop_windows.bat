@echo off
chcp 65001 >nul
title AntiEnter for Windows - Stop
echo ==================================================
echo         AntiEnter Windows 停止与恢复工具          
echo ==================================================
echo 正在停止 AntiEnter 并卸载 Hook（恢复人工审批）...
echo.

where python >nul 2>nul
if %errorlevel% equ 0 (
    python "%~dp0src\main.py" stop
) else (
    where py >nul 2>nul
    if %errorlevel% equ 0 (
        py "%~dp0src\main.py" stop
    )
)

echo.
pause
