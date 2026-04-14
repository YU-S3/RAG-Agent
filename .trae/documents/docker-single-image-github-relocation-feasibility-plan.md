# Docker 单镜像 + GitHub 跨机使用可行性计划

## Summary

* 目标：回答“当前项目是否可做到：打包为 Docker 镜像，在另一台机器仅拉取镜像 + GitHub 代码、配置自己的 API Key 后即可使用”。

* 结论（基于现状）：**可以做到，但当前仓库尚未开箱即用**；需要补齐容器化资产与密钥管理后才能稳定落地。

* 范围：本阶段仅做代码现状评估与实施计划，不执行代码改动。

## Current State Analysis

* 服务形态已具备容器化基础：后端是标准 FastAPI 应用（`app/main.py`），依赖通过 `requirements.txt` 管理，启动方式清晰（`README.md`）。

* 配置注入机制可用于跨机部署：使用 Pydantic Settings + `.env`（`app/core/settings.py`），天然支持通过环境变量注入 API Key、Qdrant 等参数。

* 运行时存在“外部依赖”：

  * LLM：`domains/default/domain.yaml` 默认本地 `ollama` 地址 `http://127.0.0.1:11434`，并且路由器支持远程 OpenAI 兼容接口（`app/services/llm_router.py`、`app/services/local_llm.py`）。

  * 向量库：`RagStore` 优先尝试 Qdrant，失败回退本地文件（`app/rag/store.py`）。

* 数据默认本地落盘：会话与 RAG 回退数据在 `eval/memory`、`eval/rag` 下写入文件（`app/memory/session_store.py`、`app/rag/store.py`），若容器重建未挂载卷会丢失。

* 缺失容器化关键文件：仓库当前无 `Dockerfile`、`docker-compose.yml`、`.dockerignore`、`.gitignore`，因此“当前直接打包并跨机即用”不成立。

* 安全风险现状：`.env` 与默认值中包含真实敏感密钥内容（`REMOTE_LLM_API_KEY`、`QDRANT_API_KEY` 等），若直接上传 GitHub 存在泄露风险，需先治理。

## Proposed Changes

* `Dockerfile`（新增）

  * 做什么：构建应用运行镜像（Python 3.10 + requirements + `uvicorn app.main:app`）。

  * 为什么：提供标准可分发镜像，满足“另一台机器仅拉镜像可跑”。

  * 怎么做：多阶段或单阶段构建；暴露 `8000`；使用环境变量注入配置；保留 `eval` 路径用于可选数据卷挂载。

* `.dockerignore`（新增）

  * 做什么：排除 `.conda`、缓存、测试临时文件、日志与本地数据。

  * 为什么：减小镜像体积并避免将本地环境打入镜像。

  * 怎么做：至少忽略 `.conda/`、`__pycache__/`、`eval/*`（按需保留空目录）、`.env`。

* `.gitignore`（新增）

  * 做什么：忽略 `.env`、密钥文件、运行时数据。

  * 为什么：防止密钥与状态文件提交到 GitHub。

  * 怎么做：加入 `.env`、`RAG_test001_api_key.txt`、`eval/**/*.jsonl`、`eval/memory/sessions.json` 等规则。

* `README.md`（更新）

  * 做什么：新增“跨机部署”章节（镜像构建、运行、环境变量、卷挂载、健康检查）。

  * 为什么：让使用方按文档完成“拉镜像 + 拉代码 + 配置密钥”流程。

  * 怎么做：提供最小命令模板与必填变量清单，明确两种部署模式：

    * 模式 A：远程模型 API（只配 API Key，最符合你的目标）；

    * 模式 B：本地/独立 Ollama（需额外服务，不建议塞入同一个应用容器）。

* `.env.example`（更新）

  * 做什么：保留占位符，不出现真实密钥；补全 Docker 运行相关说明。

  * 为什么：支持团队在新机器上快速替换自己的 Key。

  * 怎么做：所有密钥字段改为 `<YOUR_...>`，文档强调复制为本地 `.env`。

## Assumptions & Decisions

* 假设 1：你的“配置好自己的 apikey 等内容即可使用”优先指向远程大模型 API（而非把 Ollama + 大模型权重打入同一镜像）。

* 决策 1：推荐“应用单镜像 + 外部模型服务（远程 API 或独立 Ollama）”作为主路径，体积小、启动快、迁移成本低。

* 决策 2：若强制“应用 + Ollama + 权重单容器”，技术上可做但不作为默认方案（镜像巨大、冷启动慢、跨平台兼容与分发成本高）。

* 决策 3：跨机可复用必须以“密钥不入库、环境变量注入、数据卷可选持久化”为前提。

## Verification Steps

* 静态验证

  * 确认仓库包含 `Dockerfile`、`.dockerignore`、`.gitignore`、更新后的 `README.md` 与 `.env.example`。

  * 确认仓库中不存在真实 API Key（尤其 `.env` 不入库）。

* 运行验证（目标机器）

  * 拉取镜像后以 `.env` 注入启动容器，`/health` 与 `/ready` 返回成功。

  * 调用 `/v1/generate` 验证模型调用链路正常（远程 API Key 生效）。

  * 若启用 RAG，验证上传与检索接口可用。

* 持久化验证

  * 不挂载卷时：重启容器后本地回退数据可丢失（符合预期）。

  * 挂载卷时：`eval/memory`、`eval/rag` 数据可保留（符合预期）。

* 安全验证

  * 检查 Git 历史与当前工作区无明文密钥文件被追踪。

## Direct Answer To Your Question

* 能不能做到：**能**。

* 现在是不是已经“直接可用”：**还不能**，因为缺少容器化与密钥治理文件。

* 补齐以上改动后，就可以实现你描述的流程：另一台机器拉镜像 + 拉 GitHub 项目（主要用于配置与文档）+ 填自己的 API Key，即可运行。

  <br />

