# QQ Mail Digest Automation

实时接收 QQ 邮箱新邮件 → 过滤垃圾邮件 → LLM 生成中文摘要 → 每日归档 + 可选推送提醒到微信/手机。

## 功能特点

- **IMAP 轮询 QQ 邮箱**：支持长轮询后台监控，也可以用 Windows 计划任务定时轮询。
- **垃圾过滤**：基于主题/发件人关键词打分，超过阈值跳过。
- **LLM 摘要**：支持任意 OpenAI 兼容端点（阿里云 DashScope、OpenAI、本地兼容端点等均可），**小模型优先，额度耗尽自动切下一个模型**。
- **日期过滤**：可选只处理邮件发送时间为当天本地日期的邮件。
- **每日归档**：每天生成一个独立 TXT 文件，放在指定文件夹，文件名 `YYYYMMDD.txt`。当天无邮件依然创建空文件。
- **推送提醒**：支持企业微信机器人、Serverchan、PushPlus 以及自定义 webhook，收到新邮件可推送到微信/手机。
- **Windows 通知兜底**：本地监控脚本可以弹系统气泡提醒。

## 统一大模型管理

现在支持统一配置任意 OpenAI 兼容端点，不再绑定 DashScope：

```json
"llm": {
  "provider": "dashscope",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "api_key_env": "DASHSCOPE_API_KEY",
  "api_key": "",
  "models": ["qwen-turbo", "qwen-plus", "qwen-plus-latest", "qwen-max"],
  "timeout_seconds": 45,
  "max_chars": 4000
}
```

- 只要提供 `base_url` + `api_key_env` + `models`，就能支持其他 LLM 服务。
- 自动按小模型优先排序，失败自动 fallback。
- 如果没有 API Key，自动 fallback 到启发式本地摘要。

## 配置说明

主要配置项参考 [`assets/sample_config.json`](assets/sample_config.json):

| 区块 | 说明 |
|---|---|
| `qqmail` | IMAP 配置：`email` 是你的 QQ 邮箱，`auth_code_env` 是授权码环境变量，`poll_seconds` 轮询间隔。 |
| `llm` | 统一大模型配置，见上文。 |
| `date_filter` | `enabled: true` 只处理当天发送的邮件。 |
| `desktop_txt` | `enabled: true` 开启每日归档，`folder` 归档目录，`daily_file_pattern` 文件名格式。 |
| `delivery` | 推送配置：`wecom_robot_webhook`/`serverchan_sendkey`/`pushplus_token`/`custom_webhook_url`。 |
| `spam_filter` | 关键词打分配置，默认跳过得分 `>= min_score_to_skip` 的邮件。 |

## 依赖

- Python 3.8+
- 仅使用 Python 标准库，不需要额外安装第三方包。
- Windows 自带 PowerShell，不需要额外依赖。

## 使用

### 一次性验证

```powershell
python scripts/qqmail_digest_watcher.py --config path/to/config.json --once
```

### 标记已有邮件为已读（不生成摘要，只建立基线）

```powershell
python scripts/qqmail_digest_watcher.py --config path/to/config.json --mark-existing-seen
```

### 后台持续监控（Windows PowerShell）

创建 `run_qqmail_monitor.ps1`（已经做好放在项目根目录），它会每分钟轮询一次，收到新邮件弹 Windows 通知：

```powershell
.\run_qqmail_monitor.ps1
```

### Windows 开机自动启动

使用脚本 `scripts/install_windows_task.ps1` 注册计划任务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_windows_task.ps1 `
  -TaskName QQMailDigestWatcher `
  -PythonExe (Get-Command python).Source `
  -ScriptPath scripts/qqmail_digest_watcher.py `
  -ConfigPath path/to/config.json
```

## 本次提交内容

- `qqmail_digest_watcher.py`: 统一大模型支持，兼容任意 OpenAI 兼容端点，支持模型 fallback。
- `dashscope_model_probe.py`: 探测可用文本模型，自动过滤非文本模型，小模型优先排序。
- `assets/sample_config.json`: 统一 `llm` 节点，向后兼容旧配置。
- 新增功能：
  - 只处理本地当天发送的邮件
  - 每日一个 TXT 文件，空文件也保留
  - 邮件中同时显示“收取时间”和“邮件发送时间”
  - 支持标记现有邮件为已见基线，避免重复处理历史邮件
- 推送通道：支持企业微信/ServerChan/PushPlus/自定义 webhook。

## 后续更新计划

- [x] 本机归档已经完成：每日 TXT + Windows 通知。
- [ ] 推送功能：支持配置后推送到手机微信/公众号/小程序。
- [ ] 自动生成邮件回复草稿，并可以触发发送。
- [ ] 支持多邮箱账号、关键词分类归档、自定义规则。

## License

MIT
