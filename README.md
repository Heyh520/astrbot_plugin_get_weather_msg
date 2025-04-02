# 查询天气

通过和风天气api和阿里云百炼（使用qwen-turbo），在检测到聊天消息中出现特定文本时生成一张某地的 12 小时天气预报图

> [!IMPORTANT]
> 你需要在配置时填写[阿里云百炼 API KEY](https://bailian.console.aliyun.com/#/home)（需要授权调用qwen-turbo或者其他你设置的模型）
> 
> 以及[和风天气 API KEY](https://console.qweather.com/home?lang=zh)。

# 计划
- [ ] 让它能够读历史记录从而知道城市名称
- [ ] 完善天气图标，现在遇到不认识的天气名称会自动fallback，从这一点上看这还远远不是一个完整的插件（和风天气的天气名竟然是按照当地语言写的？？！）
- [ ] 代码这么烂，要不要优化一下呢（？）
- [ ] 算了，能用就行
