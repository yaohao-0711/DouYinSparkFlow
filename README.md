# DouYin Spark Flow

![cover](docs/images/cover.png)

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python)
![Playwright](https://img.shields.io/badge/Playwright-%E2%9C%94-green?logo=playwright)
![chrome-headless-shell](https://img.shields.io/badge/chrome--headless--shell-%E2%9C%94-brightgreen?logo=googlechrome)

## API 测试分支使用说明

本分支相关能力依赖仓库 [douyin-web-api-sdk](https://github.com/Rockedw/douyin-web-api-sdk)，使用即代表同意其条款和约定。

> 重要提醒
> 1. 本项目不涉及接口破解或逆向抖音代码，相关能力来源于网络资料，请自行评估风险。
> 2. 本项目仅用于学习交流，请勿大规模宣传、商用或售卖。
> 3. 如出现不可控风险，项目可能随时删库或停止维护。

### 1. 启用工作流

在 GitHub Actions 中启用最新的 `.github/workflows/schedule_api.yml` 工作流：
`【api（测试）分支】DouYin Spark Flow Schedule Run`

### 2. 配置 Environment Variables

需要在 Action 的环境变量中至少配置以下字段：

- `SKILL`：技能名称，允许值为 `human_like_sim`、`random_dynamic_emoji`、`random_hot_video`、`hitokoto`
- `SKILL_{SKILL名大写}`：对应技能的 JSON 配置（建议配置）
- `TASKS`：任务配置 JSON（必填）
- `LOG_LEVEL`：日志等级（与 `main` 分支一致）

示例：

```txt
SKILL=human_like_sim
SKILL_HUMAN_LIKE_SIM={"video_type":["影视","美食","小剧场","动物","游戏","二次元"],"dynamic_emoji_type":["续火花","比心"],"video_probability":0.3}
```

不同技能常用配置示例：

```txt
SKILL=random_dynamic_emoji
SKILL_RANDOM_DYNAMIC_EMOJI={"dynamic_emoji_type":["续火花","比心","在干嘛"]}

SKILL=random_hot_video
SKILL_RANDOM_HOT_VIDEO={"video_type":["影视","游戏","二次元"]}

SKILL=hitokoto
SKILL_HITOKOTO={"hitokoto_type":["不限","影视"],"message_template":"[盖瑞]今日火花[加一]\n[API]"}
```

### 3. 配置 `TASKS`

`TASKS` 的值是一个 JSON 数组，格式示例：

```json
[
  {
    "username": "任务账户名称",
    "user_id": "108986587854",
    "targets": [
      {
        "remark": "备注名称",
        "conversation_id": "1:1:1234567890:9876543210",
        "conversation_short_id": "1234567890123456789",
        "is_group": false
      }
    ]
  }
]
```

- `is_group`：是否群聊，群聊填 `true`，私聊填 `false`
- `conversation_id`、`conversation_short_id`、`user_id` 可通过脚本 [hook.js](hook.js) 获取

获取方式：

1. 打开 [www.douyin.com/chat](https://www.douyin.com/chat)
2. 在浏览器控制台粘贴并执行 `hook.js`
3. 打开目标会话，手动发送任意消息
4. 控制台会输出 `conversationId`、`conversationShortId`、`user_id`、`cookies`

注意：控制台输出字段是驼峰命名（如 `conversationId`），写入 `TASKS` 时请改为下划线字段（如 `conversation_id`）。

### 4. 配置 Secrets

- `COOKIES_{user_id}`：例如 `COOKIES_108986587854`，值使用 `hook.js` 输出的 `cookies`，必须放在 Secrets 中避免泄露
- `SESSIONID_{user_id}`：例如 `SESSIONID_108986587854`，值为浏览器 Cookie 中名为 `sessionid` 的值（可在开发者工具 Application/Cookies 查看）

需要每个账号都按 `user_id` 维度独立配置 `COOKIES_{user_id}` 与 `SESSIONID_{user_id}`，便于多账号并行任务管理。

## 贡献者

感谢所有为本项目做出贡献的开发者：

[![contributors](https://contrib.rocks/image?repo=2061360308/DouYinSparkFlow)](https://github.com/2061360308/DouYinSparkFlow/graphs/contributors)

## 📌 项目介绍

**抖音火花自动续火脚本**一款轻量实用的抖音互动脚本，可自动为你和抖音好友续火花，无需手动操作。

✅ 支持 GitHub Actions 自动运行（开箱即用的 Workflow 配置）

✅ 也可源码部署至自有服务器，青龙/白虎等任务管理面板，灵活适配个人使用场景

### 特性/优势

- [x] 在线可视化配置工具，新手也能入门操作
- [x] Fork即用，无需克隆代码，配置运行环境
- [x] 多用户,同时批量支持多个账户
- [x] 多目标,一个账户支持多个续火花目标
- [x] 支持按照昵称和抖音号两种方式查找好友目标
- [x] 一言支持,更丰富的消息文本

使用`PlayWright`以及`chrome-headless-shell`自动化操作[抖音创作者中心](https://creator.douyin.com/)，进行定时发送抖音消息来续火花

## 🚀 使用方法

**材料准备：** 一个 GitHub 账号和可用浏览器即可，不设额外门槛。

**编辑项目配置：** 保姆级教程见 [配置生成器使用](docs/配置生成器使用.md)

**部署方法：**

1. Github Action 部署（推荐👍），操作说明见 [Action部署说明](docs/Action部署说明.md)

2. 源码部署 （更适合高级用户），操作说明见[源代码部署说明](docs/源代码部署说明.md)

## 📢交流讨论

已开放讨论区，有疑问或展示相关成果，发布话题需求的可以加入讨论

[跳转讨论区](https://github.com/2061360308/DouYinSparkFlow/discussions)

## ⭐Star 趋势

[![Star History Chart](https://api.star-history.com/svg?repos=2061360308/DouYinSparkFlow&type=Date)](https://www.star-history.com/#2061360308/DouYinSparkFlow&Date)

## ⚠️ 免责声明

1. 本项目为**开源学习用途**，仅用于技术研究和个人自用，严禁用于商业用途、恶意刷量或违反抖音平台规则的行为。
2. 使用本脚本产生的一切风险（包括但不限于抖音账号限流、封禁、处罚等）均由使用者自行承担，项目开发者不承担任何责任。
3. 本项目仅调用公开的接口/模拟人工操作，不涉及破解、入侵抖音系统，使用者需遵守《抖音用户服务协议》及相关法律法规。
4. 请合理控制脚本运行频率，避免给抖音平台服务器造成压力，建议仅用于个人少量好友的火花维系。
5. 若你使用本项目即表示已阅读并同意本免责声明，如不同意请立即停止使用。

## 📄 开源协议

本项目基于 MIT 协议开源，你可以自由使用、修改和分发本项目代码，详见 [LICENSE](LICENSE) 文件。
