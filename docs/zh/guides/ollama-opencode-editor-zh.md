# OpenViking + 本地 Ollama + 编辑器（OpenCode / Cursor）指南

本文汇总：**本地 Ollama 跑 OpenViking**、**健康检查**、**OpenCode 记忆插件**、**数据与备份**、以及**如何让编辑器尽量依赖 OpenViking**。便于随仓库推送与团队同步。

---

## 1. 架构关系（先读这段）

- **OpenViking** 是独立的 **HTTP 服务**（默认常见端口 `1933`），持久化上下文、向量检索、会话等。
- **OpenCode** 通过官方示例插件 [`examples/opencode-memory-plugin`](../../../examples/opencode-memory-plugin/) 把 OpenViking 暴露为工具（`memsearch` / `memread` / `membrowse` / `memcommit`）。
- **Cursor** 没有内置「只认 OpenViking」的开关；要靠 **Rules、MCP、自建工作流** 等间接约束（见下文 §7）。

上下文「记在谁那儿」：**记在 OpenViking 配置的 `storage.workspace` 目录里**，不是记在 OpenViking 源码仓库里。

---

## 2. 本地用 Ollama 启动 OpenViking

本仓库提供脚本与模板（可迁 VPS）：

| 文件 | 说明 |
|------|------|
| [`deploy/start-openviking-ollama.sh`](../../../deploy/start-openviking-ollama.sh) | 从模板生成运行时配置并启动服务 |
| [`deploy/ov.ollama.conf.template`](../../../deploy/ov.ollama.conf.template) | 配置模板（`${变量}` 占位） |
| [`deploy/.env.example`](../../../deploy/.env.example) | 复制为 `deploy/.env` 后改环境变量 |
| [`ov.local-ollama.json`](../../../ov.local-ollama.json) | 本机示例 JSON（可选参考） |

**说明（与上游 README 的差异）：**

- 上游文档中的 VLM **`litellm` 提供商在部分版本中被禁用**，本地 Ollama 聊天模型应使用 **`vlm.provider: "openai"`** + **`api_base: http://127.0.0.1:11434/v1`** + 占位 **`api_key`**。
- **嵌入**使用 **`embedding.dense.provider: "ollama"`**（走 Ollama 的 OpenAI 兼容 Embeddings）。

启动前请确保 Ollama 已运行，并已 `ollama pull` 对应聊天模型与嵌入模型。

```bash
# 在仓库根目录
./deploy/start-openviking-ollama.sh
```

VPS 上：复制 `deploy/.env.example` → `deploy/.env`，修改 `OLLAMA_API_BASE`、`OPENVIKING_WORKSPACE`、`OPENVIKING_HOST=0.0.0.0` 等后再执行脚本。

---

## 3. 服务是否成功：健康检查

进程日志中出现 `Application startup complete` 且 Uvicorn 监听端口，仅表示进程起来；建议再用 HTTP 探活：

```bash
curl -sS http://127.0.0.1:1933/health
curl -sS http://127.0.0.1:1933/ready
```

- `/health`：`healthy: true` 即基本可用。
- `/ready`：检查 AGFS、向量库等；`api_key_manager: not_configured` 在本机未配置 API Key 时为正常（开发模式）。

终端里行尾的 **`%`** 多为 zsh 提示「输出末尾无换行」，不是错误；可用 `curl ...; echo` 或 `| jq .` 消除。

**根路径 `/`：** 本仓库在 `openviking/server/app.py` 中增加了 `GET /` 与 `GET /favicon.ico`，避免浏览器打开根 URL 时出现无意义的 404 日志；若你使用 PyPI/`uvx` 旧包而无该补丁，请以 `/health`、`/docs` 为准。

---

## 4. 与 OpenCode 集成（记忆插件）

详细步骤见：

- 中文概述：[examples/opencode-memory-plugin/README_CN.md](../../../examples/opencode-memory-plugin/README_CN.md)
- 中文安装：[examples/opencode-memory-plugin/INSTALL-ZH.md](../../../examples/opencode-memory-plugin/INSTALL-ZH.md)

**摘要：**

1. 保持 OpenViking 服务可访问（如 `http://127.0.0.1:1933`）。
2. 将 `openviking-memory.ts` 与配置复制到 **`~/.config/opencode/plugins/`** 顶层（OpenCode 自动发现该目录下一级的 `*.ts` / `*.js`）。
3. 编辑 `openviking-config.json` 中的 `endpoint`；本机无鉴权时 `apiKey` 可留空。
4. 若服务端启用 API Key，优先用环境变量 **`OPENVIKING_API_KEY`**。

插件会在同目录写入 `openviking-memory.log`、`openviking-session-map.json` 等运行时文件，勿提交到 Git。

---

## 5. 为什么 `viking://resources/` 是空的？

`viking://` 是 **虚拟文件系统命名空间**。**新装、尚未导入资源**时，`viking://resources/` **为空是正常现象**。

只有在你通过 **`ov add-resource`、API、插件同步** 等写入后，下面才会有内容。空目录不代表服务坏了。

---

## 6. 数据在哪？丢了什么会丢「上下文历史」？

| 丢失内容 | OpenViking 里的上下文 / 记忆 |
|----------|------------------------------|
| 仅丢失 **OpenViking 源码克隆**，**workspace 目录仍在** | **通常不丢**。重装代码，把配置指回 **同一 `storage.workspace`** 即可。 |
| **workspace 目录被删或损坏且无备份** | **会丢**。所有依赖该实例的 OpenCode（及任何连该服务的客户端）上，**存在 OpenViking 里的**长期记忆与索引资源会没了。 |
| 编辑器 **本地聊天/索引**（与 OpenViking 无关的部分） | 由各自产品决定，**与 OpenViking workspace 是否丢失无必然等价关系**。 |

**实践建议：**

- **工作区与源码分离**（例如专用目录 `~/openviking_workspace_ollama` 或 VPS 数据盘）。
- **定期备份 `storage.workspace` 指向的整个目录**（打包、快照、同步到对象存储）。
- 关键原文档仍应用 **Git 或常规备份** 保留；OpenViking 是检索与上下文层，不是唯一「原件仓库」。

---

## 7. 如何「尽量强制」编辑器使用 OpenViking？

先说结论：**没有通用的、编辑器级别的硬开关**能 100% 禁止模型「不用工具、只靠自身上下文」。能做的是 **配置 + 流程 + 提示词约束**。

### 7.1 OpenCode

- **插件层**：在 `openviking-config.json` 中设置 `"enabled": true`，并保证 `endpoint` 指向正确实例；服务端可用时插件会注册 `memsearch` 等工具。
- **行为层**：在 **Agent / 项目系统提示** 中写明规则，例如：
  - 回答前对「项目事实、用户偏好、历史约定」**必须先 `memsearch`**，再 `memread`；
  - 需要浏览结构时用 `membrowse`；
  - 长对话后定期或话题结束时调用 `memcommit`。
- 若 OpenCode 后续提供「必选工具」或「策略模板」类能力，可再收紧；以你所用版本的官方文档为准。

### 7.2 Cursor

- Cursor **没有**与 OpenViking 的官方一键绑定。
- 可行方向（择一或组合）：
  - **User / Project Rules**：写明「涉及跨会话记忆时，应通过团队约定的接口访问 OpenViking（例如文档化 API、内部脚本）」；模型仍可能不遵守，需人工抽查。
  - **MCP**：若你或社区提供「OpenViking MCP」封装 HTTP API，可在 Cursor 里挂载 MCP，把记忆操作变成工具调用，再配合 Rules 强调优先使用。
  - **统一入口**：团队规定「长期记忆只写入 OpenViking」，Cursor 侧只做编辑，记忆统一在 OpenCode + OpenViking 流水线维护。

### 7.3 安全与线上

对外暴露 OpenViking 时，务必配置 **`server.root_api_key`**（及文档要求的鉴权方式），避免未授权访问 workspace。

---

## 8. 相关链接（仓库内）

| 主题 | 路径 |
|------|------|
| OpenCode 插件（中文） | `examples/opencode-memory-plugin/README_CN.md` |
| OpenCode 安装（中文） | `examples/opencode-memory-plugin/INSTALL-ZH.md` |
| Ollama 启动脚本 | `deploy/start-openviking-ollama.sh` |
| 上游总 README（中文） | `README_CN.md` |

---

*文档版本与仓库同步维护；部署参数以你环境内的 `deploy/.env` 与生成后的运行时配置为准。*
