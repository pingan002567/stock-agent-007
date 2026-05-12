@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: ===========================
:: Stock Agent 安装脚本 (Windows)
:: ===========================

echo.
echo ╔═══════════════════════════════════════════════╗
echo ║     Stock Agent 安装程序 (Windows)            ║
echo ╚═══════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

:: ===========================
:: 1. 检查 Python
:: ===========================
echo [INFO] 检查 Python...

python --version >nul 2>&1
if errorlevel 1 (
    echo [✗] 未检测到 Python
    echo.
    echo [HINT] 请按以下步骤安装 Python:
    echo [HINT] 1. 访问 https://www.python.org/downloads/
    echo [HINT] 2. 下载 Python 3.12 或更高版本
    echo [HINT] 3. 安装时务必勾选 "Add Python to PATH"
    echo [HINT] 4. 安装完成后重新运行此脚本
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VER=%%i
echo [✓] Python %PYTHON_VER%

:: ===========================
:: 2. 检查 Node.js
:: ===========================
echo [INFO] 检查 Node.js...

node --version >nul 2>&1
if errorlevel 1 (
    echo [✗] 未检测到 Node.js
    echo.
    echo [HINT] 请按以下步骤安装 Node.js:
    echo [HINT] 1. 访问 https://nodejs.org/
    echo [HINT] 2. 下载 LTS 版本 (推荐 18.x 或更高)
    echo [HINT] 3. 运行安装程序，使用默认设置
    echo [HINT] 4. 安装完成后重新运行此脚本
    echo.
    pause
    exit /b 1
)

for /f %%i in ('node --version') do set NODE_VER=%%i
echo [✓] Node.js %NODE_VER%

:: ===========================
:: 3. 检查 npm
:: ===========================
echo [INFO] 检查 npm...

npm --version >nul 2>&1
if errorlevel 1 (
    echo [✗] 未检测到 npm
    echo [HINT] npm 通常随 Node.js 一起安装，请重新安装 Node.js
    pause
    exit /b 1
)

for /f %%i in ('npm --version') do set NPM_VER=%%i
echo [✓] npm %NPM_VER%

:: ===========================
:: 4. 检查 Git
:: ===========================
echo [INFO] 检查 Git...

git --version >nul 2>&1
if errorlevel 1 (
    echo [!] Git 未安装（可选）
    echo [HINT] 如需使用 Git，请从 https://git-scm.com/ 下载安装
    echo.
)

:: ===========================
:: 5. 配置环境变量
:: ===========================
echo [INFO] 配置环境变量...

if not exist .env (
    if exist .env.example (
        copy .env.example .env >nul
        echo [!] 已创建 .env 文件
        echo.
        echo 请编辑 .env 文件，填入你的 API Key:
        echo   OPENAI_API_KEY=your_api_key_here
        echo.
        set /p EDIT_ENV="是否现在编辑? (y/n): "
        if /i "!EDIT_ENV!"=="y" (
            notepad .env
        )
    ) else (
        echo [!] .env.example 文件不存在
    )
) else (
    echo [✓] .env 文件已存在
)

:: ===========================
:: 6. 创建虚拟环境
:: ===========================
echo [INFO] 创建 Python 虚拟环境...

if not exist .venv (
    python -m venv .venv
    if errorlevel 1 (
        echo [✗] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo [✓] 虚拟环境已创建
) else (
    echo [✓] 虚拟环境已存在
)

:: ===========================
:: 7. 安装 Python 依赖
:: ===========================
echo [INFO] 安装 Python 依赖（可能需要几分钟）...

call .venv\Scripts\activate.bat

:: 安装 uv
pip install uv >nul 2>&1
if errorlevel 1 (
    echo [✗] 安装 uv 失败
    pause
    exit /b 1
)

:: 安装项目依赖
uv pip install -e ".[akshare,yfinance]"
if errorlevel 1 (
    echo [✗] 安装项目依赖失败
    echo [HINT] 请检查网络连接后重试
    pause
    exit /b 1
)

echo [✓] Python 依赖已安装

:: ===========================
:: 8. 安装前端依赖
:: ===========================
echo [INFO] 安装前端依赖...

cd frontend
npm install
if errorlevel 1 (
    echo [✗] 安装前端依赖失败
    echo [HINT] 请检查网络连接后重试
    cd ..
    pause
    exit /b 1
)
cd ..

echo [✓] 前端依赖已安装

:: ===========================
:: 9. 初始化数据库
:: ===========================
echo [INFO] 初始化数据库...

if not exist data mkdir data
if not exist log mkdir log

call .venv\Scripts\activate.bat

:: 启动临时后端
echo [INFO] 启动临时后端服务...
start /b "" uv run uvicorn backend.app:app --host 127.0.0.1 --port 16666
timeout /t 5 /nobreak >nul

:: 导入数据
echo [INFO] 导入股票数据...
curl -s -X POST http://127.0.0.1:16666/api/stocks/import-a-share-master >nul 2>&1
echo [✓] A股数据已导入

curl -s -X POST http://127.0.0.1:16666/api/stocks/import-hk-master >nul 2>&1
echo [✓] 港股数据已导入

curl -s -X POST http://127.0.0.1:16666/api/stocks/import-us-master >nul 2>&1
echo [✓] 美股数据已导入

:: 停止临时后端
taskkill /f /im uvicorn.exe >nul 2>&1

echo [✓] 数据库初始化完成

:: ===========================
:: 完成
:: ===========================
echo.
echo ╔═══════════════════════════════════════════════╗
echo ║           安装完成!                           ║
echo ╠═══════════════════════════════════════════════╣
echo ║                                               ║
echo ║  启动命令: start.bat                          ║
echo ║                                               ║
echo ║  或手动启动:                                  ║
echo ║    终端1: .venv\Scripts\activate              ║
echo ║            uv run uvicorn backend.app:app     ║
echo ║              --host 0.0.0.0 --port 6666      ║
echo ║    终端2: cd frontend ^&^& npm run dev          ║
echo ║                                               ║
echo ╚═══════════════════════════════════════════════╝
echo.

pause
