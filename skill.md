---
name: qqmail-digest-automation
description: Plan, implement, operate, and reuse a QQ Mail automation that receives new emails via IMAP, filters spam, summarizes normal mail with large language model (supports unified OpenAI-compatible endpoint, small-model-first quota fallback), and delivers summaries to desktop TXT folder or webhook channels like WeChat/ServerChan/PushPlus. Use when you need to build or run QQ 邮箱实时收信、垃圾邮件过滤、大模型摘要、本地每日归档、推送提醒 automation.
---

# qqmail-digest-automation

QQ 邮箱自动收信 → 垃圾过滤 → 大模型摘要 → 每日归档 → 可选推送微信/手机。支持统一 OpenAI 兼容端点，小模型优先、额度用尽自动 fallback。

## Features

- IMAP 轮询 QQ 邮箱，支持后台常驻或 Windows 计划任务。
- 关键词垃圾过滤，打分跳过疑似垃圾。
- **统一大模型支持**：兼容任意 OpenAI 兼容 HTTP 端点（阿里云 DashScope、OpenAI、本地部署兼容端点）。
- **小模型优先**：自动对配置模型按大小排序，额度/权限错误自动 fallback 到下一个模型。
- **日期过滤**：可选只处理邮件发送时间为本地当天的邮件。
- **每日归档**：每天一个 `YYYYMMDD.txt`，空文件也保留；当日无邮件依然创建文件。
- 多推送渠道：企业微信机器人 / Server酱 / PushPlus / 自定义 webhook。
- Windows 气泡通知兜底。
- 零依赖：只用 Python 标准库，不需要 `pip install`。

## Quick Start

1. **Enable QQ Mail IMAP**
   - Open https://mail.qq.com
   - Settings → Account → Enable IMAP/SMTP → Get authorization code.

2. **Copy config**
   ```bash
   cp assets/sample_config.json config.json
   ```

3. **Fill config**

   | Section | Description |
   |---|---|
   | `qqmail` | IMAP settings: `email` is your QQ mail, `auth_code_env` is env name of IMAP authorization code. |
   | `llm` | Unified LLM settings: set `provider` = `heuristic` to disable LLM and use local heuristic summary. |
   | `date_filter` | `enabled: true` to process only mails sent today. |
   | `desktop_txt` | Daily output folder, file name pattern is `%Y%m%d.txt`. |
   | `delivery` | Fill webhook/token for push channels. |
   | `spam_filter` | Keyword scoring, skip when score ≥ `min_score_to_skip`. |

   Get credentials:
   - QQ IMAP authorization code: see step 1 above.
   - Alibaba Cloud DashScope API key: get from https://dashscope.aliyuncs.com/
   - No API key: set `llm.provider = heuristic` for local summary.

4. **Validate**
   ```powershell
   # mark existing mails as seen, do not generate summary
   python scripts/qqmail_digest_watcher.py --config config.json --mark-existing-seen

   # run one poll
   python scripts/qqmail_digest_watcher.py --config config.json --once
   ```

5. **Run background monitor (Windows)**
   ```powershell
   .\run_qqmail_monitor.ps1
   ```
   It polls every minute and pops system notifications when new mails arrive.

6. **Auto-start on login (recommended)**
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/install_windows_task.ps1 `
     -TaskName QQMailDigestWatcher `
     -PythonExe (Get-Command python).Source `
     -ScriptPath scripts/qqmail_digest_watcher.py `
     -ConfigPath config.json
   ```

## Probe available LLM models

```powershell
python scripts/dashscope_model_probe.py --config config.json --list
```

It will filter non-text models and sort from smaller to larger. Copy the output list to `llm.models` in your config.

## Delivery / Push

| Channel | How to get token |
|---|---|
| Server酱 | https://sct.ftqq.com/ |
| PushPlus | https://www.pushplus.plus/ |
| WeChat Work robot | Create robot in group chat |
| Custom | Post JSON `{"title": "QQ邮箱摘要", "content": summary}` to your URL |

## Future roadmap

- [x] Daily TXT archive + Windows notification done
- [ ] Integrate WeChat Official Account / MiniProgram push (requires self-hosted backend)
- [ ] Auto-generate reply draft and trigger send
- [ ] Multiple account support
- [ ] Keyword-based category archive

## License

MIT
