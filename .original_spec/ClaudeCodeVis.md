- 所有的 Python 用 uv 管理环境
- 所有的网页完成后要用 playwright 截图测试功能性和美观性

完成一个 Claude Code Session 可视化网页
- 包含一些 python 脚本，支持 cli 单独调用也支持和作为网页后端集成，作用是解析 ~/.claude/project 下的 session 数据或者是通过命令行指定具体路径
- 包含一个前端网页，可视化每个session，启动时可指定可视化单个session，如果没有参数默认可视化用户目录所有 session，不同 session 可用下拉框选择
- 支持理解 session 和 subagnet 的关系，支持显示 subagent 内部的对话，不同来源的对话框颜色要区分
- 前端网页中间是个类似社交媒体的对话框，窄高布局可以下拉移动
- 网页要显示 session 右侧的详细信息，不仅包括元数据，也包括各种提取的统计信息，比如消息数量，tool 调用数量，subagent 调用数量等等，token 消耗，甚至完成一些更高级的数据分析，比如 profiliing 不同 tool token 占比之类的，越详细越专业越好，读取了具体的 session 知道格式再决定怎么显示