@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: Stock Agent — Windows 后端启动（桌面客户端为 Tauri，见 macOS / install 文档）

set BACKEND_PORT=8686

echo.
echo Stock Agent 后端启动中... (Windows)
echo [HINT] Tauri 桌面客户端目前请在 macOS 上使用 ./start.sh
echo.

cd /d "%~dp0"

if not exist .venv (
    echo [X] 未找到虚拟环境，请先运行 install.bat
    pause
    exit /b 1
)

set DEV_MODE=false
:parse_args
if "%~1"=="" goto :start
if /i "%~1"=="--dev" set DEV_MODE=true
if /i "%~1"=="--port" (
    set BACKEND_PORT=%~2
    shift
)
if /i "%~1"=="--help" goto :show_help
shift
goto :parse_args

:show_help
echo 用法: start.bat [--dev] [--port PORT]
echo   --dev   后端热重载
pause
exit /b 0

:start
call .venv\Scripts\activate.bat
set WORKBENCH_DATA_DIR=%CD%\data
if not exist "%WORKBENCH_DATA_DIR%" mkdir "%WORKBENCH_DATA_DIR%"

echo [INFO] 启动后端 (端口: %BACKEND_PORT%)...
if "%DEV_MODE%"=="true" (
    start "Stock Agent Backend" cmd /k "uv run uvicorn backend.app:app --host 127.0.0.1 --port %BACKEND_PORT% --reload --reload-dir backend"
) else (
    start "Stock Agent Backend" cmd /k "uv run uvicorn backend.app:app --host 127.0.0.1 --port %BACKEND_PORT%"
)

echo [OK] 后端: http://127.0.0.1:%BACKEND_PORT%
echo 按任意键关闭此窗口（后端窗口需单独关闭）
pause >nul
exit /b 0
