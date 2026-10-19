# 踪流 Trajectory

Trajectory 将 Agent 执行记录组织为可分析的任务和步骤，展示用量、API 等价成本、人类交互及对应证据。打开 BatCave 的 `/trajectory/`，通过统一页面查看用量概览和会话任务分析。

任务分析包含可展开任务层级、分段时间线及开销火焰图。计数或价格缺失时显示未知或已知小计；活动时间不等于人工工时，API 等价成本不等于实际订阅账单。

Sparkstead 自动同步与 Agent 主动同步使用同一经过认证的接口及持久化进度。当前接口、权限及输入格式通过 `/trajectory/help` 发现。调用者必须使用已注册机器账户下的 API Key。

完整使用说明以 [README.md](README.md) 为准。开发者参阅 [ARCHITECTURE.md](ARCHITECTURE.md)；贡献规则以 [AGENTS.md](AGENTS.md) 为准。历史本地分析器与数据库查询命令已退出当前产品，历史用户数据库不由代码清理删除。
