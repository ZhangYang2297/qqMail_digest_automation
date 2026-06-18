#!/usr/bin/env python3
"""QQ Mail digest watcher.

Standard-library implementation for polling QQ Mail via IMAP, filtering likely spam,
summarizing normal messages, and delivering summaries to TXT and optional webhooks.
"""

from __future__ import annotations

import argparse
import email
import imaplib
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from email.header import decode_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any


@dataclass
class MailItem:
    uid: str
    subject: str
    sender: str
    date: str
    text: str


def expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def decode_mime(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for chunk, charset in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts).strip()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()

def read_env_var(name: str) -> str:
    value = os.environ.get(name, "")
    if value or os.name != "nt":
        return value
    try:
        import winreg

        locations = [
            (winreg.HKEY_CURRENT_USER, r"Environment"),
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        ]
        for hive, subkey in locations:
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    registry_value, _ = winreg.QueryValueEx(key, name)
                    if registry_value:
                        return os.path.expandvars(str(registry_value))
            except FileNotFoundError:
                continue
            except OSError:
                continue
    except ImportError:
        return ""
    return ""


def extract_text(message: Message) -> str:
    candidates: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", "")).lower()
            if "attachment" in disposition:
                continue
            if content_type not in {"text/plain", "text/html"}:
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            candidates.append(html_to_text(text) if content_type == "text/html" else text)
    else:
        payload = message.get_payload(decode=True)
        if payload:
            charset = message.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            candidates.append(html_to_text(text) if message.get_content_type() == "text/html" else text)
    return normalize_text("\n".join(candidates))


def html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</p>", "\n", value)
    value = re.sub(r"<[^>]+>", " ", value)
    replacements = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'"}
    for source, target in replacements.items():
        value = value.replace(source, target)
    return value


def spam_score(item: MailItem, spam_config: dict[str, Any]) -> int:
    score = 0
    subject = item.subject.lower()
    sender = item.sender.lower()
    text_head = item.text[:1000].lower()
    for keyword in spam_config.get("subject_keywords", []):
        if keyword.lower() in subject:
            score += 1
    for keyword in spam_config.get("sender_keywords", []):
        if keyword.lower() in sender:
            score += 1
    if any(token in text_head for token in ["退订", "unsubscribe", "点击领取", "限时优惠"]):
        score += 1
    return score






def parse_mail_datetime(date_header: str) -> datetime | None:
    if not date_header:
        return None
    try:
        parsed = parsedate_to_datetime(date_header)
        if parsed.tzinfo is not None:
            return parsed.astimezone()
        return parsed
    except (TypeError, ValueError, AttributeError):
        return None


def is_mail_from_local_today(item: MailItem) -> bool:
    sent_at = parse_mail_datetime(item.date)
    if sent_at is None:
        return False
    return sent_at.date() == datetime.now().date()


def should_process_by_date(item: MailItem, config: dict[str, Any]) -> bool:
    date_filter = config.get("date_filter", {})
    mode = date_filter.get("mode", "local_today")
    if not date_filter.get("enabled", True):
        return True
    if mode == "local_today":
        return is_mail_from_local_today(item)
    return True

def format_mail_date(date_header: str) -> str:
    parsed = parse_mail_datetime(date_header)
    if parsed is None:
        return date_header or ""
    return parsed.strftime("%Y-%m-%d %H:%M:%S %z").strip()

def heuristic_summary(item: MailItem, max_chars: int) -> str:
    body = item.text[:max_chars]
    sentences = re.split(r"(?<=[。！？.!?])\s*", body)
    bullets = [normalize_text(sentence) for sentence in sentences if normalize_text(sentence)]
    bullets = bullets[:3] if bullets else [normalize_text(body[:220])]
    bullet_text = "\n".join(f"- {bullet}" for bullet in bullets if bullet)
    return f"主题：{item.subject}\n发件人：{item.sender}\n邮件发送时间：{format_mail_date(item.date) or item.date}\n摘要：\n{bullet_text}"


def build_summary_prompt(item: MailItem, max_chars: int) -> str:
    return (
        "请用中文总结这封邮件，输出固定格式：\n"
        "1. 一句话结论\n2. 关键事项\n3. 需要我做的动作\n4. 截止时间/金额/联系人（如有）\n\n"
        f"主题：{item.subject}\n发件人：{item.sender}\n邮件发送时间：{format_mail_date(item.date) or item.date}\n正文：{item.text[:max_chars]}"
    )


def is_quota_or_model_error(status_code: int, body: str) -> bool:
    text = body.lower()
    markers = [
        "quota", "insufficient", "balance", "billing", "limit", "rate limit",
        "model_not_found", "invalid model", "access denied", "forbidden",
        "quota_exceeded", "throttling", "too many requests", "余额", "额度", "限流",
    ]
    return status_code in {400, 401, 403, 404, 429} or any(marker in text for marker in markers)


def openai_completion(item: MailItem, config: dict[str, Any]) -> str:
    api_key = read_env_var("OPENAI_API_KEY")
    if not api_key:
        return heuristic_summary(item, int(config.get("max_chars", 4000)))
    model = config.get("openai_model", "gpt-4.1-mini")
    max_chars = int(config.get("max_chars", 4000))
    payload = json.dumps({"model": model, "input": build_summary_prompt(item, max_chars)}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        text_parts: list[str] = []
        for output in data.get("output", []):
            for content in output.get("content", []):
                if content.get("type") == "output_text":
                    text_parts.append(content.get("text", ""))
        return "\n".join(text_parts).strip() or heuristic_summary(item, max_chars)
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError):
        return heuristic_summary(item, max_chars)



def llm_model_sort_key(model_id: str) -> tuple[int, int, str]:
    name = model_id.lower()
    size_order = ["0.5b", "1.5b", "3b", "7b", "14b", "32b", "72b", "110b", "turbo", "flash", "lite", "plus", "max"]
    for index, marker in enumerate(size_order):
        if marker in name:
            return index, 1 if "latest" in name else 0, name
    return len(size_order), 1 if "latest" in name else 0, name


def sort_llm_models(models: list[str]) -> list[str]:
    return sorted(list(dict.fromkeys(models)), key=llm_model_sort_key)

def openai_completion(api_key: str, base_url: str, model: str, prompt: str, timeout: int) -> str:
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一个严谨的中文邮件摘要助手。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if is_quota_or_model_error(exc.code, body):
            raise RuntimeError(f"dashscope model unavailable: {model}: HTTP {exc.code}: {body[:300]}") from exc
        raise


def llm_summary(item: MailItem, config: dict[str, Any]) -> str:
    llm = config.get("llm", {})
    if not llm:
        llm = config.get("summary", {})
        if llm.get("dashscope"):
            # backward compatibility: move dashscope block to llm
            llm = llm.get("dashscope")
    base_url = llm.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    api_key_env = llm.get("api_key_env", "DASHSCOPE_API_KEY")
    api_key = read_env_var(api_key_env) or llm.get("api_key", "")
    max_chars = int(llm.get("max_chars", 4000))
    if not api_key:
        return heuristic_summary(item, max_chars)
    models = llm.get("models", []) or [llm.get("model", "qwen-turbo")]
    models = sort_llm_models(models)
    timeout = int(llm.get("timeout_seconds", 45))
    prompt = build_summary_prompt(item, max_chars)
    errors: list[str] = []
    for model in models:
        try:
            summary = openai_completion(api_key, base_url, model, prompt, timeout)
            if summary:
                return f"模型：{model}\n{summary}"
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if is_quota_or_model_error(exc.code, body):
                errors.append(f"{model}: HTTP {exc.code}: {body[:300]}")
                continue
            return heuristic_summary(item, max_chars)
        except Exception as exc:
            errors.append(f"{model}: {str(exc)[:300]}")
            continue
    fallback = heuristic_summary(item, max_chars)
    return fallback + "\n\n[LLM fallback] No working LLMs available, used heuristic summary." + ("\n" + "\n".join(errors[:3]) if errors else "")


def summarize(item: MailItem, config: dict[str, Any]) -> str:
    provider = config.get("llm", {}).get("provider") or config.get("summary", {}).get("provider") or "heuristic"
    if provider == "heuristic":
        return heuristic_summary(item, int(config.get("summary", {}).get("max_chars", 4000)))
    return llm_summary(item, config)
    provider = config.get("provider")
    if provider == "openai":
        return llm_summary(item, config)
    if provider == "dashscope":
        return llm_summary(item, config)
    return heuristic_summary(item, int(config.get("max_chars", 4000)))

def daily_txt_path(config: dict[str, Any]) -> Path | None:
    txt_config = config.get("desktop_txt", {})
    if not txt_config.get("enabled", True):
        return None
    folder = expand_path(txt_config.get("folder", "%USERPROFILE%\\Desktop\\txt"))
    folder.mkdir(parents=True, exist_ok=True)
    file_pattern = txt_config.get("daily_file_pattern", "%Y%m%d.txt")
    file_name = datetime.now().strftime(file_pattern)
    return folder / file_name


def ensure_daily_txt(config: dict[str, Any]) -> None:
    target = daily_txt_path(config)
    if target is None:
        return
    target.touch(exist_ok=True)


def append_desktop_txt(config: dict[str, Any], item: MailItem, summary: str) -> None:
    target = daily_txt_path(config)
    if target is None:
        return
    divider = "=" * 72
    with target.open("a", encoding="utf-8") as handle:
        handle.write(f"\n{divider}\n收取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n邮件发送时间：{format_mail_date(item.date) or item.date}\nUID：{item.uid}\n{summary}\n")

def post_json(url: str, payload: dict[str, Any]) -> None:
    if not url:
        return
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=15):
        return


def deliver_webhooks(config: dict[str, Any], summary: str) -> None:
    delivery = config.get("delivery", {})
    wecom = delivery.get("wecom_robot_webhook", "")
    if wecom:
        post_json(wecom, {"msgtype": "text", "text": {"content": summary[:1900]}})
    serverchan = delivery.get("serverchan_sendkey", "")
    if serverchan:
        url = f"https://sctapi.ftqq.com/{serverchan}.send"
        data = urllib.parse.urlencode({"title": "QQ邮箱摘要", "desp": summary}).encode("utf-8")
        request = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(request, timeout=15):
            return
    pushplus = delivery.get("pushplus_token", "")
    if pushplus:
        post_json("https://www.pushplus.plus/send", {"token": pushplus, "title": "QQ邮箱摘要", "content": summary, "template": "txt"})
    custom = delivery.get("custom_webhook_url", "")
    if custom:
        post_json(custom, {"title": "QQ邮箱摘要", "content": summary})


def connect(config: dict[str, Any]) -> imaplib.IMAP4_SSL:
    qqmail = config["qqmail"]
    password = read_env_var(qqmail.get("auth_code_env", "QQMAIL_AUTH_CODE")) or qqmail.get("auth_code", "")
    if not password:
        raise RuntimeError("Missing QQ Mail authorization code. Set env var or config qqmail.auth_code.")
    context = ssl.create_default_context()
    client = imaplib.IMAP4_SSL(qqmail.get("imap_host", "imap.qq.com"), int(qqmail.get("imap_port", 993)), ssl_context=context)
    client.login(qqmail["email"], password)
    client.select(qqmail.get("mailbox", "INBOX"))
    return client


def fetch_new_items(client: imaplib.IMAP4_SSL, config: dict[str, Any], seen: set[str]) -> list[MailItem]:
    status, data = client.uid("search", None, "ALL")
    if status != "OK" or not data or not data[0]:
        return []
    uids = data[0].decode("ascii", errors="ignore").split()
    fetch_limit = int(config.get("qqmail", {}).get("fetch_limit", 20))
    new_uids = [uid for uid in uids if uid not in seen][-fetch_limit:]
    items: list[MailItem] = []
    for uid in new_uids:
        status, fetched = client.uid("fetch", uid, "(RFC822)")
        if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
            continue
        message = email.message_from_bytes(fetched[0][1])
        subject = decode_mime(message.get("Subject")) or "(无主题)"
        sender_name, sender_addr = parseaddr(decode_mime(message.get("From")))
        sender = f"{sender_name} <{sender_addr}>" if sender_name else sender_addr
        items.append(MailItem(uid=uid, subject=subject, sender=sender, date=message.get("Date", ""), text=extract_text(message)))
    return items


def process_once(config: dict[str, Any]) -> int:
    ensure_daily_txt(config)
    state_path = expand_path(config.get("state_path", "%USERPROFILE%\\Documents\\QQmail\\qqmail_digest_state.json"))
    state = load_json(state_path) if state_path.exists() else {"seen_uids": []}
    seen = set(state.get("seen_uids", []))
    processed = 0
    client = connect(config)
    try:
        items = fetch_new_items(client, config, seen)
        threshold = int(config.get("spam_filter", {}).get("min_score_to_skip", 2))
        for item in items:
            seen.add(item.uid)
            if not should_process_by_date(item, config):
                continue
            if spam_score(item, config.get("spam_filter", {})) >= threshold:
                continue
            summary = summarize(item, config.get("summary", {}))
            append_desktop_txt(config, item, summary)
            deliver_webhooks(config, summary)
            processed += 1
    finally:
        try:
            client.logout()
        except imaplib.IMAP4.error:
            pass
    state["seen_uids"] = sorted(seen, key=lambda value: int(value) if value.isdigit() else value)[-2000:]
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_json(state_path, state)
    return processed




def mark_existing_seen(config: dict[str, Any]) -> int:
    ensure_daily_txt(config)
    state_path = expand_path(config.get("state_path", "%USERPROFILE%\\Documents\\QQmail\\qqmail_digest_state.json"))
    client = connect(config)
    try:
        status, data = client.uid("search", None, "ALL")
        uids = data[0].decode("ascii", errors="ignore").split() if status == "OK" and data and data[0] else []
    finally:
        try:
            client.logout()
        except imaplib.IMAP4.error:
            pass
    state = load_json(state_path) if state_path.exists() else {}
    state["seen_uids"] = sorted(set(uids), key=lambda value: int(value) if value.isdigit() else value)[-2000:]
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    state["baseline_marked_at"] = state["updated_at"]
    save_json(state_path, state)
    return len(state["seen_uids"])

def run_loop(config: dict[str, Any]) -> None:
    poll_seconds = int(config.get("qqmail", {}).get("poll_seconds", 60))
    while True:
        try:
            count = process_once(config)
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] processed={count}", flush=True)
        except Exception as exc:  # keep daemon alive and visible
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] error={exc}", flush=True)
        time.sleep(poll_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poll QQ Mail, summarize normal emails, and deliver summaries.")
    parser.add_argument("--config", required=True, help="Path to JSON config file.")
    parser.add_argument("--once", action="store_true", help="Run one polling cycle and exit.")
    parser.add_argument("--mark-existing-seen", action="store_true", help="Mark all existing mailbox messages as already seen without summarizing them.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_json(expand_path(args.config))
    if args.mark_existing_seen:
        count = mark_existing_seen(config)
        print(f"marked_seen={count}")
    elif args.once:
        count = process_once(config)
        print(f"processed={count}")
    else:
        run_loop(config)


if __name__ == "__main__":
    main()











