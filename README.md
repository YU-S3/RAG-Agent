# Meta Agent

一个可扩展的 AI Agent 项目，包含：
- 配置驱动工作流（LangGraph）
- 模块化 RAG（检索、重排、上传、任务化导入）
- 长短期记忆
- 本地 Web 前端 + CLI
- 评测、可观测、安全与生产控制能力

## 项目进度
- M1（配置化 MVP）已完成：目录骨架、配置系统、API 入口、本地 LLM 接入
- M2（可插拔与稳态）已完成：工具热插拔、路由降级、自愈校验
- M3（生产化能力）已完成核心项：RAG、记忆、评测、审计、限流、回滚

## 目录结构
```text
app/
  core/            # 配置、路由、Prompt 加载
  workflow/        # LangGraph 工作流与质量控制
  rag/             # 分段、解析、检索、存储、重排
  memory/          # 短期/长期记忆编排
  services/        # LLM 客户端与路由
  security/        # 鉴权与输入防护
  observability/   # trace 与 dashboard 聚合
  production/      # 限流、灰度、checkpoint
  main.py          # FastAPI 入口
  cli.py           # CLI 入口
domains/           # 领域配置（domain.yaml）
tools/             # 工具声明（yaml）
prompts/           # Prompt 模板
web/               # 前端静态资源
eval/              # 评测集、报告、事件日志
tests/             # 自动化检查
```

## 核心功能
- 配置驱动：通过 `domains/<domain>/domain.yaml` 控制模型策略、工具、输出 schema、重试阈值
- 工作流：planner -> executor -> analyzer，支持低置信度重试与熔断降级
- RAG：
  - 文档入库：`/v1/rag/documents`、`/v1/rag/upload`、`/v1/rag/upload/tasks`
  - 检索融合：Embedding + BM25 + Rerank（可选 BGE）
  - 向量存储：优先 Qdrant，异常回退本地文件
- 记忆：会话窗口记忆 + 历史对话长期记忆写回
- 可观测：`trace_id` 全链路、事件日志、评测报告
- 前端与 CLI：本地 Web 页面 + 命令行运行/导入/插件执行

## 配置说明
- 复制模板：
```powershell
Copy-Item .env.example .env
```
- 最少需要配置：
  - `REMOTE_LLM_BASE_URL`
  - `REMOTE_LLM_API_KEY`
  - `REMOTE_LLM_MODEL`
- 可选配置：
  - `QDRANT_URL`
  - `QDRANT_API_KEY`
  - `RAG_STORE_PROVIDER`（`auto`/`local`/`qdrant`）

依赖说明：
- `requirements.txt` 已包含 `hf-xet==1.4.3`，用于 Hugging Face Xet 加速下载，减少 `hf_xet` 缺失警告。

## 本地运行（Conda）
```powershell
conda create -p .conda\meta-agent python=3.10 -y
conda activate C:\Users\YCY\Desktop\AI_Agent\.conda\meta-agent
python -m pip install -r requirements.txt

Copy-Item .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

健康检查：
```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/health"
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/ready"
```

## Windows 用户从拉取到运行（Docker + 基础镜像）
> 适合“用户拉取代码后，在容器内按 `requirements.txt` 安装依赖再启动”。

### 1) 拉取项目
```cmd
git clone git@github.com:YU-S3/RAG-Agent.git
cd /d RAG-Agent
```
若未配置 SSH：
```cmd
git clone https://github.com/YU-S3/RAG-Agent.git
cd /d RAG-Agent
```

### 2) 准备配置
```cmd
copy .env.example .env
```
编辑 `.env`，填好自己的模型与向量库密钥。

### 3) 拉取基础镜像
```cmd
docker pull python:3.10-slim
```

### 4) 启动容器（安装依赖 + 启动后端）
```cmd
docker run --name rag-agent-dev ^
  -p 8000:8000 ^
  --env-file .env ^
  -v "%cd%":/app ^
  -v rag_pip_cache:/root/.cache/pip ^
  -w /app ^
  python:3.10-slim ^
  sh -lc "python -m pip install --upgrade pip && pip install -r requirements.txt && uvicorn app.main:app --host 0.0.0.0 --port 8000"
```

### 5) 打开前端
- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/web/`

### 6) 运维命令
```cmd
docker logs -f rag-agent-dev
docker stop rag-agent-dev
docker start rag-agent-dev
docker rm -f rag-agent-dev
```

## 镜像模式运行（已构建好应用镜像时）
```powershell
docker build -t meta-agent:latest .
docker run --name meta-agent -p 8000:8000 --env-file .env meta-agent:latest
```

## 常用接口
- `GET /health`
- `GET /ready`
- `POST /v1/generate`
- `POST /v1/generate/stream`
- `POST /v1/rag/documents`
- `POST /v1/rag/upload`
- `POST /v1/rag/upload/tasks`
- `GET /v1/rag/upload/tasks/{task_id}`
- `GET /v1/rag/documents?domain=default`

请求示例：
```powershell
$body = @{
  domain = "default"
  task = "为需求评审准备三步执行计划"
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/generate" -ContentType "application/json" -Body $body
```

## 测试与评测
```powershell
python -m tests.smoke_check
python -m tests.cli_mvp_check
python eval/run_eval.py
```

CI 工作流：
- `.github/workflows/eval.yml`

## 上传到 GitHub 指令
```bash
git add README.md requirements.txt plugins/sample.echo.json eval/run_eval.py
git commit -m "docs: update README with full setup and run guide"
git push origin main
```

如果出现远端分支非快进（`non-fast-forward`）：
```bash
git fetch origin
git pull --rebase origin main --allow-unrelated-histories
git push origin main
```
