# 🤖 Stock Agent

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB.svg)](https://react.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **本地化 AI 投资工作台** — 集成 AI Copilot 对话、多数据源行情、策略回测、风险管理、盯盘告警于一体的个人投资决策系统。

[**功能特性**](#-功能特性) · [**快速开始**](#-快速开始) · [**系统架构**](#️-系统架构) · [**配置说明**](#-配置说明) · [**开发指南**](#-开发指南)

---

## 🖥️ 产品预览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  AI Stock Workbench                                          [AI 就绪] [Z] │
├──────┬──────────────────────────────────────────────────────────────────────┤
│      │                                                                     │
│  AI  │  ┌─────────────────────────────────────────────────────────────┐   │
│      │  │  总览 - 投资组合仪表盘                                       │   │
│ 总览 ├─►│                                                             │   │
│      │  │  📊 持仓总值: ¥1,234,567    📈 今日收益: +1.25%            │   │
│ 个股 │  │  📋 持仓数量: 8             ⚠️ 风险警报: 2                  │   │
│      │  │                                                             │   │
│ 市场 │  │  ┌─────────────────────┐  ┌─────────────────────────────┐  │   │
│      │  │  │ 自选股              │  │ AI Copilot                  │  │   │
│ 自选 │  │  │ AAPL   $185.2 +1.2% │  │                             │  │   │
│      │  │  │ 00700  ¥380  -0.5% │  │ 🤖 分析一下 AAPL 的风险    │  │   │
│ 持仓 ├─►│  │ 600519 ¥1710 +0.8% │  │                             │  │   │
│      │  │  └─────────────────────┘  │ 📊 正在分析...              │  │   │
│ 盯盘 │  │                             │                             │  │   │
│      │  │  ┌─────────────────────┐  │ ✅ AAPL 当前处于上升趋势... │  │   │
│ 策略 │  │  │ 盯盘事件            │  │                             │  │   │
│      │  │  │ ⚠️ AAPL 涨幅超5%   │  │ 🔍 追问:                   │  │   │
│ 任务 │  │  │ ⚠️ 茅台跌破支撑位  │  │  [技术面] [基本面] [风险]   │  │   │
│      │  │  └─────────────────────┘  └─────────────────────────────┘  │   │
│ 报告 │  └─────────────────────────────────────────────────────────────┘   │
│      │                                                                     │
│ 设置 │                                                                     │
└──────┴─────────────────────────────────────────────────────────────────────┘
```

---

## ✨ 功能特性

| 模块 | 能力 |
|------|------|
| **AI Copilot** | 多轮对话、流式响应、工具调用、推理过程可视化、会话管理 |
| **个股研究** | 基本面分析、技术面分析、情报搜索、财务数据、追问建议 |
| **市场概览** | 大盘复盘、板块表现、市场时间线、涨跌统计 |
| **自选股** | 分组管理、实时行情、AI 评分、批量导入 |
| **持仓管理** | 持仓快照、权重分析、风险评估、调仓草案 |
| **盯盘系统** | 自定义规则、多种触发条件、事件历史、告警通知 |
| **策略回测** | 策略创建、历史回测、收益指标、信号分析 |
| **风险控制** | 风险策略配置、集中度监控、单票限额、板块限额 |
| **报告生成** | 智能报告、质量评分、证据链、候选行动 |
| **任务管理** | 任务追踪、步骤详情、工具执行记录 |
| **决策日志** | 决策记录、结果追踪、经验沉淀 |
| **模拟交易** | 纸面交易、绩效分析、组合快照 |
| **世界杯预测** | 赛事分析、赔率计算、投注管理（扩展模块） |

---

## 🛠️ 系统架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            Frontend (React + Vite)                      │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────────┐  │
│  │ Overview │ │Research │ │ Holdings│ │Monitor  │ │  CopilotPanel   │  │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────────────┘  │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ REST API + SSE
┌────────────────────────────────▼────────────────────────────────────────┐
│                           Backend (FastAPI)                             │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │                         API Routes                                │ │
│  │  /overview  /stocks  /watchlist  /holdings  /monitor  /copilot   │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │                      App Services Layer                          │ │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌────────────┐ │ │
│  │  │CopilotService│ │MonitorService│ │StrategyService│ │ReportService│ │ │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └────────────┘ │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │                    Agent Runtime (DeerFlow)                       │ │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌────────────┐ │ │
│  │  │ToolBridge   │ │SkillRegistry│ │SubAgent     │ │Streaming   │ │ │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └────────────┘ │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │                    Stock Domain Layer                             │ │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌────────────┐ │ │
│  │  │ProviderRouter│ │  Backtest   │ │   Risk      │ │  Catalog   │ │ │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └────────────┘ │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │                    Persistence Layer (SQLite)                     │ │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌────────────┐ │ │
│  │  │  Repository │ │  FileStore  │ │  DB Schema  │ │  Migrations│ │ │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └────────────┘ │ │
│  └───────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────────┐
│                        External Data Sources                           │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────┐  │
│  │   AkShare   │ │  YFinance   │ │  Tencent    │ │  DeepSeek/OpenAI│  │
│  │  (A/H股)    │ │   (美股)    │ │  (行情)     │ │    (AI 模型)    │  │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 技术栈

| 层级 | 技术 |
|------|------|
| **前端** | React 19, TypeScript, Vite, Tailwind CSS |
| **后端** | Python 3.12, FastAPI, Pydantic, Uvicorn |
| **AI 运行时** | DeerFlow (ByteDance), OpenAI API |
| **数据源** | AkShare, YFinance, 东方财富, 新浪财经 |
| **数据库** | SQLite (本地文件) |
| **测试** | Pytest, Vitest, Playwright |

---

## 🚀 快速开始

### Mac / Linux

```bash
# 1. 克隆项目
git clone https://github.com/your-username/stock-agent-001.git
cd stock-agent-001

# 2. 运行安装脚本
chmod +x install.sh
./install.sh

# 3. 配置 API Key（安装脚本会提示）
vi .env

# 4. 启动服务
./start.sh
```

### Windows

```batch
:: 1. 克隆项目
git clone https://github.com/your-username/stock-agent-001.git
cd stock-agent-001

:: 2. 运行安装脚本（双击或在 CMD 中运行）
install.bat

:: 3. 配置 API Key（安装脚本会提示用记事本打开）

:: 4. 启动服务
start.bat
```

> **Windows 用户注意：**
> - 需要预先安装 [Python 3.12+](https://www.python.org/downloads/)（安装时勾选 "Add Python to PATH"）
> - 需要预先安装 [Node.js 18+](https://nodejs.org/)
> - 建议使用 CMD 或 PowerShell 运行，不建议使用 Git Bash（部分命令不兼容）

### 手动安装（所有平台）

```bash
# 1. 创建虚拟环境
python3 -m venv .venv        # Mac/Linux
python -m venv .venv         # Windows

# 2. 激活虚拟环境
source .venv/bin/activate    # Mac/Linux
.venv\Scripts\activate       # Windows

# 3. 安装后端依赖
pip install uv
uv pip install -e "."

# 4. 安装前端依赖
cd frontend && npm install && cd ..

# 5. 配置环境变量
cp .env.example .env
vi .env                      # 或用记事本打开

# 6. 启动后端
uv run uvicorn backend.app:app --host 0.0.0.0 --port 6666

# 7. 启动前端（新终端）
cd frontend && npm run dev
```

### 访问地址

| 服务 | 地址 |
|------|------|
| **前端应用** | http://localhost:5173 |
| **后端 API** | http://localhost:6666 |
| **API 文档** | http://localhost:6666/docs |
| **生产模式** | http://localhost:6666/app (需先构建前端) |

---

## ⚙️ 配置说明

### 环境变量

编辑 `.env` 文件：

```env
# AI 模型配置
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://api.deepseek.com/v1
WORKBENCH_AI_MODEL=deepseek-chat

# 可选：其他 AI 提供商
# ANTHROPIC_API_KEY=your_claude_key
# GEMINI_API_KEY=your_gemini_key
```

### 数据源配置

系统支持多数据源自动降级：

| 数据源 | 市场 | 优先级 |
|--------|------|--------|
| AkShare | A股、港股 | 高 |
| YFinance | 美股 | 高 |
| 东方财富 | A股行情 | 中 |
| 新浪财经 | 港股行情 | 中 |
| Mock | 测试环境 | 低 |

### AI 技能系统

系统内置 6 个 AI 技能，可通过 `extensions_config.json` 启用/禁用：

```json
{
  "skills": {
    "stock-researcher":  {"enabled": true},
    "risk-officer":      {"enabled": true},
    "strategy-analyst":  {"enabled": true},
    "rebalance-planner": {"enabled": true},
    "stock-monitor":     {"enabled": true},
    "report-writer":     {"enabled": true}
  }
}
```

---

## 📊 功能详解

### AI Copilot

- **多轮对话**：支持上下文记忆的连续对话
- **流式响应**：实时显示 AI 推理过程
- **工具调用**：自动调用 40+ 个投资工具
- **推理可视化**：展示 AI 思考链路

### 个股研究

```python
# AI 自动执行的研究流程
1. get_stock_context    # 获取基本面概况
2. get_daily_history    # 分析 K 线趋势
3. search_stock_intel   # 搜索最新情报
4. 输出结构化分析报告
```

### 盯盘规则

支持多种触发条件：

| 规则类型 | 说明 |
|----------|------|
| `single_position_weight_gt` | 仓位超限 |
| `price_change_pct_gt` | 涨跌幅超限 |
| `ma_crossover` | 均线金叉/死叉 |
| `volume_spike` | 成交量异常 |
| `sector_correlation` | 板块联动 |
| `combined_condition` | 复合条件 |
| `intel_keyword_match` | 情报关键词 |

### 风险管理

```yaml
# 风险策略示例
single_stock_limit: 15%      # 单票上限
single_stock_warning: 12%    # 单票预警线
sector_limit: 35%            # 板块上限
max_drawdown: 20%            # 最大回撤
```

---

## 🧪 测试

```bash
# 运行后端测试
pytest

# 运行前端测试
cd frontend && npm test

# 运行 E2E 测试
cd frontend && npm run test:e2e

# 运行 AI 回归测试
python scripts/run_ai_regression.py
```

---

## 📁 项目结构

```
stock-agent-001/
├── backend/
│   ├── agent_runtime/      # AI 运行时（DeerFlow 集成）
│   │   ├── tool_bridge.py  # 工具桥接层
│   │   ├── skill_registry.py # 技能注册
│   │   └── tools.py        # 工具定义
│   ├── api/                # API 路由
│   │   ├── routes_copilot.py
│   │   ├── routes_stock.py
│   │   └── ...
│   ├── app_services/       # 业务服务层
│   │   ├── copilot_service.py
│   │   ├── monitor_service.py
│   │   └── ...
│   ├── stock_domain/       # 股票领域层
│   │   ├── provider_router.py # 数据源路由
│   │   ├── backtest_tools.py  # 回测工具
│   │   └── ...
│   ├── persistence/        # 持久化层
│   │   ├── db.py           # 数据库
│   │   └── repositories.py # 仓储
│   └── schemas.py          # 数据模型
├── frontend/
│   ├── src/
│   │   ├── components/     # 组件
│   │   ├── hooks/          # 自定义 Hook
│   │   ├── pages/          # 页面
│   │   ├── api/            # API 客户端
│   │   └── types/          # 类型定义
│   └── package.json
├── skills/                 # AI 技能定义
│   └── custom/
│       ├── stock-researcher/
│       ├── risk-officer/
│       └── ...
├── doc/                    # 项目文档
├── tests/                  # 测试文件
├── scripts/                # 工具脚本
├── install.sh              # 安装脚本
├── start.sh                # 启动脚本
└── pyproject.toml          # Python 项目配置
```

---

## 🔧 开发指南

### 添加新工具

1. 在 `backend/agent_runtime/tools.py` 定义工具
2. 在 `backend/agent_runtime/tool_bridge.py` 注册工具
3. 在 `backend/app_services/` 实现业务逻辑
4. 更新技能定义（如需要）

### 添加新页面

1. 在 `frontend/src/pages/` 创建页面组件
2. 在 `frontend/src/types/index.ts` 添加 Screen 类型
3. 在 `frontend/src/components/layout/Rail.tsx` 添加导航
4. 在 `frontend/src/pages/ScreenRenderer.tsx` 注册路由

### 添加新技能

1. 在 `skills/custom/` 创建技能目录
2. 创建 `SKILL.md` 定义技能规范
3. 在 `extensions_config.json` 启用技能

---

## 📚 文档中心

- [架构设计](doc/ARCHITECTURE_ANALYSIS.md)
- [AI 对话架构](doc/AI_CHAT_ARCHITECTURE.md)
- [数据源配置](doc/data_cache_strategy.md)
- [回测标准](doc/BACKTEST_STANDARDS.md)
- [技能系统](doc/SKILL_SYSTEM.md)
- [工具绑定](doc/TOOL_DEEP_BINDING.md)
- [完整文档目录](doc/README.md)

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'feat: Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

---

## 📄 License

[MIT License](LICENSE) © 2026

---

## ⚠️ 免责声明

**本项目仅供学习和研究使用，不构成任何投资建议。**

- 股市有风险，投资需谨慎
- 作者不对使用本项目产生的任何损失负责
- AI 分析结果仅供参考，投资决策请自行判断
- 数据源可能存在延迟或错误，请以官方数据为准

---

## 🙏 致谢

- [DeerFlow](https://github.com/bytedance/deer-flow) - ByteDance 开源的 AI Agent 框架
- [AkShare](https://github.com/akfamily/akshare) - 开源财经数据接口
- [FastAPI](https://fastapi.tiangolo.com/) - 现代 Python Web 框架
- [React](https://react.dev/) - 用户界面库
- [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) - README 风格参考
