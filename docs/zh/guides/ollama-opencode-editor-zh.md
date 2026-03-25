# OpenViking + 本地 Ollama + 编辑器（OpenCode / Cursor）指南

本文汇总：**本地 Ollama 跑 OpenViking**、**健康检查**、**OpenCode 记忆插件**、**如何验证插件是否在跑**、**数据与备份**、以及**如何让编辑器尽量依赖 OpenViking**。便于随仓库推送与团队同步。

---

## 1. 架构关系（先读这段）

- **OpenViking** 是独立的 **HTTP 服务**（默认常见端口 `1933`），持久化上下文、向量检索、会话等。
- **OpenCode** 通过官方示例插件 [`examples/opencode-memory-plugin`](../../../examples/opencode-memory-plugin/) 把 OpenViking 暴露为工具（`memsearch` / `memread` / `membrowse` / `memcommit`）。
- **Cursor** 没有内置「只认 OpenViking」的开关；要靠 **Rules、MCP、自建工作流** 等间接约束（见下文 §8）。

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

**本机推荐组合（可选）：**

- 在 `~/.config/opencode/opencode.json` 顶层增加 **`instructions`**，指向一份说明文件（例如 `~/.config/opencode/instructions/openviking-memory.md`），引导 Agent 在涉及偏好/历史/项目事实时优先调用 `memsearch` / `memread` 等。详见 OpenCode 官方配置 schema 中的 `instructions` 字段。

---

## 5. 如何确认 OpenCode「在用」插件管理上下文？

先分清两件事：**插件后台自动做的事**，与 **模型是否每轮都调用 `memsearch`**，不是同一回事。

### 5.1 插件会自动做什么（不依赖模型点工具）

OpenCode 加载 `openviking-memory.ts` 且 `openviking-config.json` 里 **`enabled: true`** 时，插件会：

| 行为 | 说明 |
|------|------|
| 初始化 | 读取配置、写日志 |
| 健康检查 | 请求 OpenViking 的 `/health` |
| **自动 commit 调度** | `autoCommit.enabled: true` 时，约每分钟检查一次，按 `intervalMinutes`（如 10）对会话触发向 OpenViking 的提交逻辑 |
| **会话绑定** | 在 `session.created` 等事件里为 OpenCode 会话创建/对齐 OpenViking session，并维护 `openviking-session-map.json` |
| **消息同步** | 通过事件钩子把对话消息写入 OpenViking 会话（具体见插件源码中的 `event` 处理） |

以上**不要求**模型调用 `memsearch`，属于**同步对话 + 定时提交**管线。

### 5.2 什么不会「每轮自动」发生

**`memsearch` / `memread` / `membrowse`** 是 Agent **工具（tool）**，是否调用由**模型决定**。`instructions` 只能提高概率，**不是**内核级「每轮强制检索」开关。

- 若关心「对话有没有进 OpenViking」→ 看 **§5.3** 的日志与映射文件、以及服务端 session。
- 若关心「回答前有没有先查记忆」→ 看模型是否调用了 `mem*` 工具，并继续用 **§8** 的规则与 instructions 约束。

### 5.3 自检清单（推荐按顺序做）

1. **看插件日志**

   ```bash
   tail -f ~/.config/opencode/plugins/openviking-memory.log
   ```

   重启 OpenCode、新开会话后，应能看到（具体文案以日志为准）：

   - `OpenViking Memory Plugin initialized`（含 `endpoint`）
   - `OpenViking health check passed`（服务未启动则为 failed）
   - `Auto-commit scheduler started`
   - 新建会话时出现 `OpenCode session created` 等与 OpenViking session 相关的成功日志  

   若启动即出现 **`OpenViking Memory Plugin is disabled`**，检查配置里 `enabled` 是否为 `false` 或配置文件路径是否错误。

2. **看会话映射是否在更新**

   ```bash
   cat ~/.config/opencode/plugins/openviking-session-map.json
   ```

   在 OpenCode 中多轮对话后再次查看；有新增或更新说明插件在处理会话。

3. **看 OpenViking 侧**  
   查看服务端日志是否有对应 session / message / task 请求；若安装了 `ov` CLI，可用官方命令或 HTTP API 核对 session。

4. **看 OpenCode 工具列表**  
   Agent 可用工具中应出现 **memsearch、memread、membrowse、memcommit**。若完全没有，多为插件未被加载（路径须为 `~/.config/opencode/plugins/` 下**一级**的 `*.ts` / `*.js`）。

5. **OpenCode 调试**  
   若支持在 `opencode.json` 中设置 **`logLevel`: `DEBUG`**（以当前版本文档为准），可进一步确认插件加载与报错信息。

### 5.4 小结

- **「插件在自动管上下文」** ≈ 日志里有初始化/健康检查/auto-commit、映射文件在动、服务端有流量。  
- **「每答必先 memsearch」** 目前只能靠 **instructions + 模型自觉**；若要更强约束，依赖 OpenCode 后续能力或自建工作流。

---

## 6. 为什么 `viking://resources/` 是空的？

`viking://` 是 **虚拟文件系统命名空间**。**新装、尚未导入资源**时，`viking://resources/` **为空是正常现象**。

只有在你通过 **`ov add-resource`、API、插件同步** 等写入后，下面才会有内容。空目录不代表服务坏了。

---

## 7. 数据在哪？丢了什么会丢「上下文历史」？

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

## 8. 如何「尽量强制」编辑器使用 OpenViking？

先说结论：**没有通用的、编辑器级别的硬开关**能 100% 禁止模型「不用工具、只靠自身上下文」。能做的是 **配置 + 流程 + 提示词约束**。

### 8.1 OpenCode

- **插件层**：在 `openviking-config.json` 中设置 `"enabled": true`，并保证 `endpoint` 指向正确实例；服务端可用时插件会注册 `memsearch` 等工具。
- **行为层**：在 **Agent / 项目系统提示** 中写明规则，例如：
  - 回答前对「项目事实、用户偏好、历史约定」**必须先 `memsearch`**，再 `memread`；
  - 需要浏览结构时用 `membrowse`；
  - 长对话后定期或话题结束时调用 `memcommit`。
- 若 OpenCode 后续提供「必选工具」或「策略模板」类能力，可再收紧；以你所用版本的官方文档为准。

### 8.2 Cursor（推荐：官方 MCP + 项目 Rules）

Cursor **没有**内置 OpenViking 按钮，推荐组合：

1. **OpenViking 主服务**（`openviking-server`，常见端口 **1933**）照常运行，负责存储与索引。
2. **OpenViking MCP 服务**（官方示例 `examples/mcp-query`，默认 **HTTP `http://127.0.0.1:2033/mcp`**），把 **`search` / `query` / `add_resource`** 暴露给 Cursor。  
   本仓库提供免源码构建的启动脚本（使用 PyPI 的 `openviking` wheel）：
   - [`deploy/start-openviking-mcp-for-cursor.sh`](../../../deploy/start-openviking-mcp-for-cursor.sh)  
   - 默认读取与 `start-openviking-ollama.sh` 一致的 **`OV_CONFIG`**（如 `~/.cache/openviking-ollama/ov.generated.json`）与 **`OV_DATA`**（workspace 目录）。首次需已生成配置且目录存在。
3. **Cursor MCP 配置**：在 `~/.cursor/mcp.json` 的 `mcpServers` 中增加：
   ```json
   "openviking": {
     "url": "http://127.0.0.1:2033/mcp"
   }
   ```
   保存后重启 Cursor，在 MCP 面板中启用 **openviking**。
4. **项目 Rules**：在仓库 `.cursor/rules/` 下增加说明，引导在「跨会话记忆 / 已入库文档」场景优先调用 **openviking** 的 MCP 工具（与 OpenCode 的 `memsearch` 互为补充；**同一 `OV_DATA` workspace** 则数据一致）。

官方 MCP 能力说明见上游文档：[Model Context Protocol (MCP)](https://volcengine-openviking.mintlify.app/integrations/mcp) 与 `examples/mcp-query/README.md`。

**注意**：MCP 进程与 `openviking-server` 是**两个进程**；开发时通常两个终端分别启动，或使用进程管理器。

### 8.3 安全与线上

对外暴露 OpenViking 时，务必配置 **`server.root_api_key`**（及文档要求的鉴权方式），避免未授权访问 workspace。

---

## 9. 相关链接（仓库内）

| 主题 | 路径 |
|------|------|
| OpenCode 插件（中文） | `examples/opencode-memory-plugin/README_CN.md` |
| OpenCode 安装（中文） | `examples/opencode-memory-plugin/INSTALL-ZH.md` |
| Ollama 启动脚本 | `deploy/start-openviking-ollama.sh` |
| 上游总 README（中文） | `README_CN.md` |

---

*文档版本与仓库同步维护；部署参数以你环境内的 `deploy/.env` 与生成后的运行时配置为准。*
