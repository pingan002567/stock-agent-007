@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: ===========================
:: Stock Agent 启动脚本 (Windows)
:: ===========================

set BACKEND_PORT=6666
set FRONTEND_PORT=5173

echo.
echo ╔═══════════════════════════════════════════════════════════╗
echo ║             Stock Agent 启动中... (Windows)              ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

:: ===========================
:: 检查环境
:: ===========================
if not exist .env (
    echo [✗] 未找到 .env 文件
    echo [HINT] 请先运行 install.bat 安装依赖
    echo [HINT] 或手动复制 .env.example 为 .env 并配置 API Key
    echo.
    pause
    exit /b 1
)

if not exist .venv (
    echo [✗] 未找到虚拟环境
    echo [HINT] 请先运行 install.bat 安装依赖
    echo.
    pause
    exit /b 1
)

if not exist frontend\node_modules (
    echo [✗] 前端依赖未安装
    echo [HINT] 请先运行 install.bat 安装依赖
    echo.
    pause
    exit /b 1
)

:: ===========================
:: 解析参数
:: ===========================
set BACKEND_ONLY=false
set FRONTEND_ONLY=false
set DEV_MODE=false

:parse_args
if "%~1"=="" goto :start
if /i "%~1"=="--backend-only" set BACKEND_ONLY=true
if /i "%~1"=="--frontend-only" set FRONTEND_ONLY=true
if /i "%~1"=="--dev" set DEV_MODE=true
if /i "%~1"=="--port" (
    set BACKEND_PORT=%~2
    shift
)
if /i "%~1"=="--help" goto :show_help
shift
goto :parse_args

:show_help
echo.
echo Stock Agent 启动脚本 (Windows)
echo.
echo 用法: start.bat [选项]
echo.
echo 选项:
echo   --backend-only    仅启动后端
echo   --frontend-only   仅启动前端
echo   --dev             开发模式 (带热重载)
echo   --port PORT       设置后端端口 (默认: 6666)
echo   --help            显示此帮助信息
echo.
echo 示例:
echo   start.bat                # 启动所有服务
echo   start.bat --backend-only # 仅启动后端
echo   start.bat --port 8000    # 使用 8000 端口启动后端
echo.
pause
exit /b 0

:: ===========================
:: 启动服务
:: ===========================
:start

:: 激活虚拟环境
call .venv\Scripts\activate.bat

:: 启动后端
if "%FRONTEND_ONLY%"=="false" (
    echo [INFO] 启动后端服务 (端口: %BACKEND_PORT%)...
    
    if "%DEV_MODE%"=="true" (
        start "Stock Agent Backend" cmd /c "uv run uvicorn backend.app:app --host 0.0.0.0 --port %BACKEND_PORT% --reload --reload-dir backend"
    ) else (
        start "Stock Agent Backend" cmd /c "uv run uvicorn backend.app:app --host 0.0.0.0 --port %BACKEND_PORT%"
    )
    
    echo [INFO] 等待后端启动...
    timeout /t 5 /nobreak >nul
    echo [✓] 后端服务已启动
)

:: 启动前端
if "%BACKEND_ONLY%"=="false" (
    echo [INFO] 启动前端服务 (端口: %FRONTEND_PORT%)...
    
    cd frontend
    start "Stock Agent Frontend" cmd /c "npm run dev -- --port %FRONTEND_PORT%"
    cd ..
    
    echo [✓] 前端服务已启动
)

:: ===========================
:: 显示状态
:: ===========================
echo.
echo ╔═══════════════════════════════════════════════════════════╗
echo ║                    Stock Agent 已启动                     ║
echo ╠═══════════════════════════════════════════════════════════╣
echo ║  📱 前端:     http://localhost:%FRONTEND_PORT%                         
echo ║  🔧 后端:     http://localhost:%BACKEND_PORT%                         
echo ║  📚 API文档:  http://localhost:%BACKEND_PORT%/docs                    
echo ╠═══════════════════════════════════════════════════════════╣
echo ║  关闭此窗口或按 Ctrl+C 停止服务                          ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.
echo [HINT] 如果浏览器未自动打开，请手动访问上述地址
echo.

:: 等待用户退出
echo 按任意键停止服务...
pause >nul

:: 停止服务
echo.
echo [INFO] 正在停止服务...
taskkill /f /fi "WindowTitle eq Stock Agent Backend*" >nul 2>&1
taskkill /f /fi "WindowTitle eq Stock Agent Frontend*" >nul 2>&1
echo [✓] 服务已停止

pause
