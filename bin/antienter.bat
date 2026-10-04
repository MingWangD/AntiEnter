@echo off
setlocal
set "DIR=%~dp0.."
where python >nul 2>nul
if %errorlevel% equ 0 (
    python "%DIR%\src\main.py" %*
) else (
    where py >nul 2>nul
    if %errorlevel% equ 0 (
        py "%DIR%\src\main.py" %*
    ) else (
        echo [AntiEnter Error] 未检测到 Python，请先安装 Python 3.9+ 并添加到 PATH。
        exit /b 1
    )
)
endlocal
