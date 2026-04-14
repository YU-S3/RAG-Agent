# Meta Agent

## 当前进度
- 已完成 M1 的基础启动项：目录骨架、配置系统、API 入口、本地 LLM 接入方式
- 默认使用本地 Ollama 作为 LLM 运行方式

## 1. 创建 Anaconda 虚拟环境

```powershell
conda create -p .conda\meta-agent python=3.10 -y
conda activate C:\Users\YCY\Desktop\AI_Agent\.conda\meta-agent
python -m pip install -r requirements.txt
```

- 依赖说明：`requirements.txt` 已包含 `hf-xet==1.4.3`，用于 Hugging Face Xet 加速下载，避免 CI 中出现 `hf_xet` 缺失提示。

## 2. 启动本地 LLM（Ollama）

```powershell
ollama serve
ollama pull qwen3:8b
```

## 3. 启动 API

```powershell
Copy-Item .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Docker 跨机部署（推荐）

> 目标场景：A 机器构建镜像并推送；B 机器只拉镜像 + 拉取 GitHub 项目（用于配置与文档），填入自己的 API Key 后启动。

### 1) 构建镜像

```powershell
docker build -t meta-agent:latest .
```

### 2) 准备环境变量

```powershell
Copy-Item .env.example .env
```

请在 `.env` 中至少配置：
- `REMOTE_LLM_BASE_URL`
- `REMOTE_LLM_API_KEY`
- `REMOTE_LLM_MODEL`
- （可选）`QDRANT_URL`、`QDRANT_API_KEY`

### 3) 运行容器

```powershell
docker run --name meta-agent -p 8000:8000 --env-file .env meta-agent:latest
```

如需保留本地回退数据（会话与 RAG 文件），可挂载卷：

```powershell
docker run --name meta-agent -p 8000:8000 --env-file .env -v ${PWD}/eval:/app/eval meta-agent:latest
```

### 4) 访问检查

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/health"
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/ready"
```

说明：
- 默认推荐“应用单镜像 + 外部模型服务（远程 API 或独立 Ollama）”。
- 若 `domains/default/domain.yaml` 仍使用 `http://127.0.0.1:11434`，则容器内无法访问宿主机 Ollama；请改为可达地址或使用远程 API 配置。

## 4. 健康检查

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/health"
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/ready"
```

## 5. 调用示例

```powershell
$body = @{
  domain = "default"
  task = "为需求评审准备三步执行计划"
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/generate" -ContentType "application/json" -Body $body
```

## 6. 基础验证

```powershell
python -m tests.smoke_check
python -m tests.embedder_endpoint_check
python -m tests.local_llm_retry_check
python -m tests.debug_llm_last_check
python -m tests.quality_output_parse_check
python -m tests.rag_chunker_check
python -m tests.rag_file_parse_check
python -m tests.pdf_layout_order_check
python -m tests.rag_upload_list_check
python -m tests.rag_upload_task_progress_check
python -m tests.memory_vector_candidate_check
python -m tests.reranker_bge_fallback_check
python -m tests.reranker_hybrid_score_check
python -m tests.reranker_latency_guard_check
python -m tests.generate_stream_check
python -m tests.llm_empty_response_runtime_check
python -m tests.llm_degrade_runtime_check
python -m tests.tool_registry_check
python -m tests.llm_router_check
python -m tests.workflow_retry_check
python -m tests.quality_guard_check
python -m tests.security_guard_check
python -m tests.production_controls_check
python -m tests.security_api_check
python -m tests.rag_memory_check
python -m tests.web_mvp_check
python -m tests.cli_mvp_check
python eval/run_eval.py
```

## 7. 工具热插拔说明

- 工具描述文件目录：`tools/<domain>/*.yaml`
- 已内置示例：`tools/default/mock_search.yaml`、`tools/default/mock_calculator.yaml`
- 描述字段：
  - `name`：工具名
  - `impl`：实现映射名
  - `permission`：权限标签（如 `readonly`）
  - `args_schema`：参数约束（required/properties/type）

## 8. LLM 路由与成本治理

- 路由器实现：`app/services/llm_router.py`
- 能力包含：线上模型优先（API Key）、失败自动降级到本地、TTL缓存、预算触发轻量模型优先
- 领域配置字段（`domains/<domain>/domain.yaml` 的 `model_policy`）：
  - `model`：主模型
  - `fallback_models`：降级模型列表
  - `lite_model`：预算或低复杂度优先模型
  - `budget_tokens`：提示词预算阈值
- 提示词模板位置：`prompts/default/planner.j2`
- 本地调试接口：`GET /v1/debug/llm-last`（仅本地且 `DEBUG_LOCAL_ENABLED=true`）
- 线上模型配置（OpenAI 兼容）：
  - `REMOTE_LLM_ENABLED=true`
  - `REMOTE_LLM_BASE_URL=<https://...>`
  - `REMOTE_LLM_API_KEY=<your_key>`
  - `REMOTE_LLM_MODEL=<model_name>`

## 9. 自愈与质量控制

- 输出强校验：`app/workflow/quality.py`
- 自动修复：将上轮错误注入下一轮规划提示词
- 熔断策略：重试超过阈值后返回降级结构，避免无限重试

## 10. 可观测与评测

- 请求链路追踪：每次请求分配 `trace_id`，响应头与响应体都会返回该值
- 事件日志文件：`eval/trace_events.jsonl`
- 评测集：`eval/datasets/basic_eval.jsonl`
- 本地评测脚本：`eval/run_eval.py`
- CI 工作流：`.github/workflows/eval.yml`

## 11. 安全与生产硬化

- 输入防护：按 `INPUT_BLOCK_PATTERNS` 过滤高风险请求
- 鉴权开关：`SECURITY_ENABLED=true` 时启用 Bearer Token 校验
- 审计日志：写入 `eval/audit_events.jsonl`
- 生产控制：请求限流、灰度桶、checkpoint 持久化与回滚兜底

## 12. 模块化 RAG 与记忆

- 新增文档向量化入口：`POST /v1/rag/documents`
- 文件上传向量化入口：`POST /v1/rag/upload`（`multipart/form-data`，支持 `txt/md/markdown/pdf/doc/docx`）
- 异步上传任务入口：`POST /v1/rag/upload/tasks`，状态查询：`GET /v1/rag/upload/tasks/{task_id}`
- 流式对话入口：`POST /v1/generate/stream`（SSE事件：`stage/process/meta/token/result/done`）
- 知识库文档列表入口：`GET /v1/rag/documents?domain=default`
- PDF 解析策略：优先 `pdfplumber` 版面分析（物理布局 -> 逻辑阅读顺序），失败回退 `pypdf` 线性提取
- 向量存储：优先使用 Qdrant（通过环境变量读取连接信息）
- 可配置项：`RAG_STORE_PROVIDER`、`QDRANT_URL`、`QDRANT_API_KEY`、`QDRANT_COLLECTION`、`QDRANT_TIMEOUT_SECONDS`
- 分段策略：`spaCy 自动语言分块 + 滑动窗口`（默认 `RAG_CHUNK_STRATEGY=spacy_auto`）
- 分段参数：`RAG_CHUNK_SIZE=400`、`RAG_CHUNK_OVERLAP=80`、`RAG_CHUNK_MIN_SIZE=80`
- 检索策略：先走 Qdrant 向量召回候选（`RAG_VECTOR_CANDIDATE_TOP_N` / `RAG_VECTOR_CANDIDATE_TOP_N_MEMORY`），再本地 BM25+overlap 粗排，支持可配置 BGE 精排（`RAG_RERANKER_TYPE`）
- BGE 重排配置：`RAG_BGE_MODEL_NAME`、`RAG_BGE_DEVICE`、`RAG_BGE_BACKEND`、`RAG_BGE_ONNX_PROVIDER`、`RAG_BGE_TOP_N`、`RAG_BGE_TIMEOUT_MS`、`RAG_BGE_WEIGHT`
- BGE 权重下载：首次触发重排时会按配置自动下载（支持 ONNX Runtime 优先，失败回退 Torch）
- 调试建议：查看响应 `memory_meta.doc_rerank.bge_meta` 的 `reason/backend/latency_ms` 判断是否真正命中 BGE
- spaCy 模型可配置：`RAG_SPACY_MODEL_ZH`、`RAG_SPACY_MODEL_EN`（未安装模型时自动回退规则分段）
- 支持在线检索：Embedding + BM25 + Rerank 融合（混合检索）
- 支持短期记忆：按 `session_id` 窗口记忆并摘要压缩
- 支持长期记忆：历史对话写入向量库并参与后续检索
- `/v1/generate` 新增字段：`session_id`、`user_id`、`use_memory`、`top_k`
- 响应新增字段：`memory_meta`

## 13. 本地前端 MVP（阶段A）

- 访问地址：`http://127.0.0.1:8000/`
- 功能页面：
  - AI 对话（流式打字、会话侧栏、memory 参数、trace 展示）
  - 仪表盘（请求量、错误、延迟、审计拒绝 + 趋势图）
  - 知识导入（调用 `/v1/rag/documents`）

## 14. CLI MVP（阶段B）与增强（阶段C）

- 运行入口：`python -m app.cli <command>`
- 常用命令：
  - `python -m app.cli run "生成三步执行计划"`
  - `python -m app.cli chat --session-id s1 --user-id u1`
  - `python -m app.cli rag-import ./docs`
  - `python -m app.cli session list`
  - `python -m app.cli plugin-list --dir plugins`
  - `python -m app.cli plugin-run sample.echo "hello"`
- `rag-import` 支持文件类型：`txt/md/rst/py/pdf/docx/doc`
- 增强能力：
  - 审批模式：`--approval-mode strict`
  - 插件清单扫描与执行：`plugins/*.json`
