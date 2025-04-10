# 基于阿里云百炼和和风天气的查询天气插件
> [!IMPORTANT]
> 1. 请注意本插件和 [astrbot_plugin_get_weather_cmd](https://github.com/whzcc/astrbot_plugin_get_weather_cmd) 的不同之处。本插件在检测到聊天消息以特定文本开头后触发，**使用到了 AI 大模型**。
> 
> 2. 你需要在配置时填写[阿里云百炼 API KEY](https://bailian.console.aliyun.com/#/home)（需要授权调用 qwen-turbo 或者其他你设置的模型）
> 
>    以及[和风天气 API KEY](https://console.qweather.com/home?lang=zh)。

> [!NOTE]
> 当前天气图标准备不完全，可能会出现不显示的情况。
通过和风天气 API 和阿里云百炼模型（默认使用 qwen-turbo，可在配置中更改），在检测到聊天消息以特定文本开头（默认为“天气”和“查询天气”，可在配置中更改）时生成一张某地的 12 小时天气预报图。

## 实现方式
检测到聊天消息以某一文本开头（默认为“天气”和“查询天气”，可在配置中更改）时，插件函数被触发。
图标作者为[星星峡的星星](https://www.iconfont.cn/user/detail?spm=a313x.search_index.0.d214f71f6.5af93a81LJ6prx&uid=353865&nid=zc3yXUmxY95I)和[_bzl](https://www.iconfont.cn/user/detail?spm=a313x.search_index.0.d214f71f6.5af93a81LJ6prx&uid=3937395&nid=8XMWPvgdm6bh)。

## 两个版本插件的区别
| 插件名称 | 是否有 llm | 触发方式 | 配置文件 |
| ----------- | ----------- | ----------- | ----------- |
| [astrbot_plugin_get_weather_msg](https://github.com/whzcc/astrbot_plugin_get_weather_msg)  | 有 llm，用于提取用户输入的信息 | 聊天的文本以特定字符开头（如“天气 广州的天气怎么样？” | [和风天气 API KEY](https://console.qweather.com/home?lang=zh) |
| [astrbot_plugin_get_weather_cmd](https://github.com/whzcc/astrbot_plugin_get_weather_cmd)   | 无 llm | 识别指令（“如/天气 广州”） | [和风天气 API KEY](https://console.qweather.com/home?lang=zh)、[阿里云百炼 API KEY](https://bailian.console.aliyun.com/#/home) |

## 计划
- [ ] 使用异步请求
- [ ] 让它能够读历史记录从而知道城市名称
- [ ] 完善天气图标，现在遇到不认识的天气名称会自动fallback，从这一点上看这还远远不是一个完整的插件（和风天气的天气名竟然是按照当地语言写的？？！）
