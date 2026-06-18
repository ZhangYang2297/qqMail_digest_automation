# qqMail-digest-automation

实时接收 QQ 邮箱邮件 → 过滤垃圾邮件 → 大模型生成中文摘要 → 每日归档 → 可选推送提醒到微信/手机/本地 TXT。

支持统一 OpenAI 兼容端点，小模型优先、额度耗尽自动 fallback，开箱即用。

## 功能特点

- **IMAP 轮询**：持续监控 QQ 邮箱收件箱，支持后台常驻或 Windows 计划任务定时轮询。
- **垃圾过滤**：基于主题/发件人关键词打分打分，超过阈值自动跳过。
- **统一大模型支持**：兼容任意 OpenAI 兼容端点（阿里云 DashScope、OpenAI、本地部署兼容端点等），支持**小模型优先**，额度/权限错误自动尝试下一个模型。
- **日期过滤**：可选只处理**邮件发送时间为本地当天**的邮件，避免重复处理历史邮件。
- **每日归档**：每天一个独立 TXT 文件放在指定文件夹，文件名 `YYYYMMDD.txt`；当天无邮件依然创建空文件。
- **推送提醒**：原生支持企业微信机器人、Server酱、PushPlus 以及自定义 webhook，收到新邮件可直接推送到微信/手机。
- **Windows 通知兜底**：本地监控脚本收到新邮件会弹出系统气泡提醒。
- **Python 零依赖**：仅使用 Python 标准库，不需要 `pip install` 任何包。

## 架构与选型

| 模块 | 说明 |
|---|---|
| 运行方式 | 推荐本地 Python 脚本 + Windows 计划任务；也可部署到 NAS/VPS 作为后台服务。不需要前端。 |
| 大模型 | 支持任意 OpenAI 兼容 HTTP 端点，只要你提供 `base_url` + `api_key` + 优先级模型列表即可。 |
| 推送渠道 | 推荐 Server酱/PushPlus/企业微信机器人，比直接操控个人微信/QQ 客户端更稳定，不会触发风控。 |
| 归档 | 默认每日一个 TXT，当天处理好的邮件直接追加，方便归档查找。 |

## 快速开始

### 1. 准备 QQ 邮箱

1. 登录 QQ 邮箱网页版：<https://mail.qq.com>
2. 点击 `设置` → `账户`
3. 找到 `POP3/IMAP/SMTP服务` → 开启 `IMAP/SMTP服务`
4. 按提示发送短信验证，生成**授权码**，这就是你 IMAP 登录密码，不是 QQ 登录密码。

### 2. 复制配置

```bash
cp assets/sample_config.json config.json
```

### 3. 填写配置

主要配置项说明：

```json
{
  "qqmail": {
    "imap_host": "imap.qq.com",
    "imap_port": 993,
    "email": "你的QQ邮箱",
    "auth_code_env": "QQMAIL_AUTH_CODE",  // 推荐把授权码放在环境变量，不写进配置文件
    "auth_code": "",                              // 如果不放到环境变量，可以写这里（不推荐共享）
    "mailbox": "INBOX",
    "poll_seconds": 60,                         // 轮询间隔，单位秒
    "fetch_limit": 20                          // 每次最多处理多少封新邮件
  },
  "llm": {
    "provider": "dashscope",                     // "heuristic" 表示只用本地启发式摘要，不需要大模型
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "api_key_env": "DASHSCOPE_API_KEY",        // API Key 推荐放到环境变量
    "api_key": "",
    "models": ["qwen-turbo", "qwen-plus", "qwen-plus-latest", "qwen-max"],  // 按优先级从前往后尝试
    "timeout_seconds": 45,
    "max_chars": 4000                           // 给大模型的最大正文长度
  },
  "date_filter": {
    "enabled": true,                           // true 只处理当天发送的邮件
    "mode": "local_today"
  },
  "desktop_txt": {
    "enabled": true,
    "folder": "%USERPROFILE%\\Documents\\QQmail\\txt",  // 归档目录
    "daily_file_pattern": "%Y%m%d.txt"                    // 文件名日期格式
  },
  "delivery": {
    "wecom_robot_webhook": "",        // 企业微信机器人 webhook，填写后会推送
    "serverchan_sendkey": "",        // Server酱 sendkey，填写后会推送
    "pushplus_token": "",            // PushPlus token，填写后会推送
    "custom_webhook_url": ""         // 自定义推送端点
  },
  "spam_filter": {
    "skip_folders": ["垃圾箱", "Junk", "Spam"],
    "subject_keywords": ["发票代开", "贷款", "博彩", "中奖", "返利", "推广", "unsubscribe", "casino", "loan"],
    "sender_keywords": ["noreply-spam", "promo", "marketing"],
    "min_score_to_skip": 2          // 打分超过这个值就跳过
  },
  "state_path": "%USERPROFILE%\\Documents\\QQmail\\qqmail_digest_state.json"  // 记录已经处理过的邮件 UID，避免重复处理
}
```

**获取授权码/API Key：**

- QQ IMAP 授权码：见上文“准备 QQ 邮箱”。
- 阿里云 DashScope API Key：开通 DashScope 后在 [https://dashscope.aliyuncs.com/](https://dashscope.aliyuncs.com/) 控制台获取。
- 如果不用大模型，把 `llm.provider` 改成 `"heuristic"`，即可使用本地启发式摘要，不需要 API Key。

### 4. 验证

```powershell
# 标记所有已有邮件为已处理，不生成摘要，建立基线
python scripts/qqmail_digest_watcher.py --config config.json --mark-existing-seen

# 验证一次轮询
python scripts/qqmail_digest_watcher.py --config config.json --once
```

如果输出 `processed=N`，N > 0 表示处理了 N 封新邮件，会写入对应日期的 TXT。

### 5. 后台运行监控

项目里已经有 `run_qqmail_monitor.ps1`，直接运行即可后台轮询，收到新邮件弹 Windows 通知：

```powershell
.\run_qqmail_monitor.ps1
```

### 6. 开机自动启动（推荐）

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_windows_task.ps1 `
  -TaskName QQMailDigestWatcher `
  -PythonExe (Get-Command python).Source `
  -ScriptPath scripts/qqmail_digest_watcher.py `
  -ConfigPath config.json
```

之后每次开机自动启动。

## 大模型探测

可以探测当前端点下可用文本模型，自动过滤掉 code/vision/audio/embedding 等非文本模型，并且按小模型优先排序：

```powershell
python scripts/dashscope_model_probe.py --config config.json --list
```

输出会按小模型优先列出所有可用文本模型，方便你复制到配置里。

## 推送提醒

| 渠道 | 获取方式 |
|---|---|
| **Server酱** | <https://sct.ftqq.com/> 注册后获取 sendkey |
| **PushPlus** | <https://www.pushplus.plus/> 获取 token |
| **企业微信机器人** | 在企业微信群添加机器人拿到 webhook |
| **自定义** | 填 `custom_webhook_url`，脚本会 POST JSON `{"title": "QQ邮箱摘要", "content": summary}` |

## 发布记录

### 本次提交

- 统一大模型配置：支持任意 OpenAI 兼容端点，不再绑定阿里云。
- 小模型优先，额度/权限错误自动 fallback 到下一个模型。
- 只处理当天发送的邮件，避免旧邮件重复处理。
- 每天一个独立 TXT 文件，空文件也保留。
- 同时记录收取时间和邮件发送时间。
- 支持标记已有邮件为基线，避免重复生成摘要。
- 原生支持多种推送渠道，可直接推送到手机微信。

### 后续更新计划

- [x] 本机每日 TXT 归档 + Windows 通知
- [ ] 完整对接公众号/小程序推送（需要自己搭建后端）
- [ ] 自动生成邮件回复草稿，可选触发发送
- [ ] 多账号支持
- [ ] 自定义关键词分类归档

## License

MIT
