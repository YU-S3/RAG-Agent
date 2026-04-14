# 远程部署 Ollama 与应用解耦可行性评估计划

## Summary
- 目标：基于现有仓库代码与文档，判断是否支持将 Ollama 部署在另一台笔记本，并让本项目仅作为应用层调用远程 LLM 服务。
- 交付：给出“是否可行”的明确结论、当前能力边界、最小落地方式、风险点与验证路径。
- 范围：仅做只读评估与方案计划，不改业务代码、不改配置文件。

## Current State Analysis
- 运行文档显示当前默认本地 Ollama 运行方式，应用与模型同机启动（`README.md` 的启动步骤）。
- 领域配置中 `model_policy.base_url` 当前为 `http://127.0.0.1:11434`，说明 LLM 服务地址是可配置字段（`domains/default/domain.yaml`）。
- 请求链路为：`/v1/generate` -> `MetaRouter` -> 读取 `domain.yaml` -> `DynamicLLMRouter` -> `LocalLLMClient` 按 `base_url` 调用 `POST {base_url}/api/generate`。
- `Settings` 与 `.env.example` 当前未提供专用的 `OLLAMA_HOST/OLLAMA_BASE_URL` 环境变量；但支持 `DOMAIN_CONFIG_ROOT` 切换配置根目录。
- LLM 客户端超时与重试存在默认值（超时 180 秒、重试 3 次），适配远程网络时需关注可用性与时延抖动。

## Proposed Changes
- 本次阶段不改代码，仅输出评估结论与实施建议文档化说明。
- 评估输出将引用以下文件并说明“为什么可行”：
  - `README.md`：确认当前启动与部署假设。
  - `domains/default/domain.yaml`：确认远程地址切换入口。
  - `app/core/domain_config.py`、`app/core/meta_router.py`：确认配置加载链路。
  - `app/services/llm_router.py`、`app/services/local_llm.py`：确认调用方式与运行时参数。
  - `app/core/settings.py`、`.env.example`：确认环境变量能力与缺口。
- 给出两种落地路径（不改代码）：
  - 直接改 `domains/<domain>/domain.yaml` 的 `base_url` 指向远程 Ollama。
  - 使用独立配置目录并通过 `DOMAIN_CONFIG_ROOT` 切换，避免改默认配置。
- 给出可选增强方向（后续如需实施再开发）：
  - 新增环境变量覆盖 `base_url`/超时；
  - 增加远程健康探测与降级提示。

## Assumptions & Decisions
- 假设用户当前目标是“先确认可行性与操作路径”，不是立即实施代码改造。
- 决策：先给出“可行/不可行 + 依据 + 最小步骤 + 风险”，不进入代码修改阶段。
- 决策：以仓库现状为准，不引入 Docker/K8s 等额外部署体系假设。

## Verification Steps
- 代码层验证（已完成）：确认 `base_url` 真实进入 HTTP 请求地址拼接逻辑。
- 文档层验证（已完成）：确认 README 运行方式、环境变量项与当前能力边界一致。
- 结论一致性检查（待输出时执行）：逐条核对“可行性结论”与代码证据，确保每条结论有对应文件依据。
