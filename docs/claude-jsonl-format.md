# Claude Code JSONL Session Format

Claude Code 将每个会话（session）存储为一个 JSONL 文件，位于 `~/.claude/projects/<project-slug>/<session-id>.jsonl`。每行是一个独立的 JSON 对象。

## Record Types

每条记录通过 `type` 字段区分：

| type | 说明 | 含 `message` | 含 `usage` |
|------|------|:-----------:|:----------:|
| `user` | 用户输入 或 工具返回结果 | Yes | No |
| `assistant` | 模型输出的单个 content block | Yes | Yes |
| `progress` | Hook 执行进度、工具执行进度 | No | No |
| `system` | 系统事件（hook summary、stop signals） | No | No |
| `file-history-snapshot` | 文件历史快照（用于撤销） | No | No |
| `queue-operation` | 后台任务队列操作（enqueue/dequeue） | No | No |

> **重要**: 没有明确的"会话打开/关闭"事件。只能通过消息时间戳间隔来推断。

## 消息粒度：一个 content block = 一条 JSONL 记录

这是理解 JSONL 格式最关键的点。**模型的一次响应（API turn）不是一条记录，而是多条记录**，每个 content block 单独一行。

### 示例：模型一次响应读取 6 个文件

```
用户发送消息:
  {"type":"user", "message":{"role":"user","content":[{"type":"text","text":"帮我重构代码"}]}}

模型输出（1个 API turn → 7条 JSONL 记录）:
  {"type":"assistant", "message":{"content":[{"type":"text","text":"我来读一下文件..."}], "usage":{...}}}       ← text block
  {"type":"assistant", "message":{"content":[{"type":"tool_use","name":"Read","id":"toolu_01A..."}], "usage":{...}}}  ← tool_use
  {"type":"assistant", "message":{"content":[{"type":"tool_use","name":"Read","id":"toolu_01B..."}], "usage":{...}}}  ← tool_use
  {"type":"assistant", "message":{"content":[{"type":"tool_use","name":"Read","id":"toolu_01C..."}], "usage":{...}}}  ← tool_use
  {"type":"assistant", "message":{"content":[{"type":"tool_use","name":"Read","id":"toolu_01D..."}], "usage":{...}}}  ← tool_use
  {"type":"assistant", "message":{"content":[{"type":"tool_use","name":"Read","id":"toolu_01E..."}], "usage":{...}}}  ← tool_use
  {"type":"assistant", "message":{"content":[{"type":"tool_use","name":"Read","id":"toolu_01F..."}], "usage":{...}}}  ← tool_use

工具结果返回（6条 user 记录，每个 tool_result 一条）:
  {"type":"user", "message":{"content":[{"type":"tool_result","tool_use_id":"toolu_01A...","content":"..."}]}}
  {"type":"user", "message":{"content":[{"type":"tool_result","tool_use_id":"toolu_01B...","content":"..."}]}}
  ...
```

### 时间戳特征

- 同一个 API turn 内的多条 assistant 记录时间戳递增，间隔约 0.3~1s（流式输出间隔）
- tool_result 的 user 记录时间戳几乎同时（<0.01s 间隔，同一批返回）
- **真正的用户交互**是不带 `tool_result` 的 `user` 记录

## Content Block Types

### Assistant 消息中的 content block

| type | 说明 | 关键字段 |
|------|------|---------|
| `text` | 文本输出 | `text` |
| `thinking` | 内部推理（extended thinking） | `thinking`, `signature` |
| `tool_use` | 工具调用 | `id`, `name`, `input` |

### User 消息中的 content block

| type | 说明 | 关键字段 |
|------|------|---------|
| `text` | 用户输入文本 | `text` |
| `tool_result` | 工具执行结果 | `tool_use_id`, `content`, `is_error` |

## Token Usage

只有 `assistant` 记录带有 `message.usage`：

```json
{
  "usage": {
    "input_tokens": 3,
    "output_tokens": 469,
    "cache_creation_input_tokens": 12345,
    "cache_read_input_tokens": 67890,
    "service_tier": "standard"
  }
}
```

- `input_tokens`: 非缓存的输入 token
- `output_tokens`: 模型输出 token
- `cache_read_input_tokens`: 从缓存读取的 token
- `cache_creation_input_tokens`: 写入缓存的 token

> 同一 turn 内的多条 assistant 记录中，只有最后一条的 `usage` 包含真实的累计值，前面的是流式中间状态。但目前我们对所有 assistant 记录的 usage 求和，因为每条的增量值也是有意义的。

## 常用顶层字段

```json
{
  "type": "user|assistant|progress|system|...",
  "sessionId": "39672551-...",
  "uuid": "unique-record-id",
  "parentUuid": "parent-record-id",
  "timestamp": "2026-02-11T04:17:06.684Z",
  "isSidechain": false,
  "userType": "external",
  "cwd": "/home/user/project",
  "version": "2.1.34",
  "gitBranch": "main",
  "message": { ... }
}
```

| 字段 | 说明 |
|------|------|
| `sessionId` | 会话 ID，对应文件名 |
| `uuid` | 本条记录唯一 ID |
| `parentUuid` | 父记录 ID（用于构建消息树） |
| `timestamp` | ISO 8601 时间戳 |
| `isSidechain` | 是否为 subagent 消息 |
| `agentId` | subagent 的 ID（仅 subagent 消息） |
| `cwd` | 当前工作目录 |
| `version` | Claude Code 版本号 |

## Subagent 消息

当 Claude 使用 `Task` 工具创建 subagent 时，subagent 的消息穿插在主会话 JSONL 中，通过 `isSidechain: true` 和 `agentId` 区分。Subagent 的 JSONL 也会单独存一份在 `<session-id>/subagents/agent-<id>.jsonl`。

---

# 本仓库的处理方式

## Parser 过滤规则

`session_parser.py` 中的 `parse_jsonl_file()` 只解析能通过 `MessageRecord` Pydantic 校验的记录。实际上只有 `type=user` 和 `type=assistant` 的记录能通过，因为 `progress`、`system` 等类型缺少 `MessageRecord` 要求的字段。

因此：
- **被解析**: `user`(1241条) + `assistant`(1906条) = 3147 条
- **被跳过**: `progress`(11391) + `system`(116) + `file-history-snapshot`(97) + `queue-operation`(44) = 11648 条

## 消息计数

当前统计中，`assistant_message_count` 是 **JSONL 记录数**（每个 content block 一条），而非 API turn 数。例如：

- 1906 条 assistant 记录 ≈ 1009 个实际模型 turn（平均每 turn 1.9 条记录）

## 时间归因算法

对每对相邻消息，计算时间间隔 `gap = timestamp[i] - timestamp[i-1]`：

```
gap > 30min (inactivity threshold)
  → Inactive（应用关闭/用户离开）

gap <= 30min:
  下一条是 assistant  → Model time（模型推理 + 流式输出）
  下一条是 user + tool_result  → Tool time（工具执行）
  下一条是 user + text  → User time（用户思考/输入）
```

### 已知局限

1. **同一 turn 的流式间隔**: assistant→assistant 的 0.3~1s 间隔被计入 Model time，严格来说是网络传输时间，但影响很小（~4%）
2. **批量工具调用共享时间戳**: 同一 turn 中多个 tool_use 共享 assistant 消息时间戳，第一个 tool 的延迟会被高估
3. **Subagent 消息穿插**: subagent 消息按时间排序后与主消息混合计算，不单独追踪

## Tool 延迟计算

`tool_use_map` 存储 `tool_use_id → (tool_name, timestamp)`。当遇到对应的 `tool_result` 时：

```
latency = tool_result_timestamp - tool_use_timestamp
```

累积到每个 tool 的 `total_latency`，最终算出 `avg_latency = total_latency / count`。
