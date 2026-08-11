"""Microsoft Outlook 邮箱（基于 Microsoft Graph API）。

使用 refresh_token 免登录收发邮件，支持 Outlook + 别名（plus-addressing）。
注册时自动在邮箱地址后添加别名，例如 user@outlook.com -> user+grok1@outlook.com。

支持两种账号文件格式：

1) JSON 格式（accounts.json）：
{
  "accounts": [
    {
      "email": "user@outlook.com",
      "password": "***",
      "client_id": "xxx",
      "refresh_token": "xxx"
    }
  ]
}

2) 文本格式（accounts.txt，每行一个账号，与 mail.py 兼容）：
邮箱----密码----client_id----refresh_token
"""

from __future__ import annotations

import json
import random
import secrets
import string
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from email_providers.common import extract_verification_code

TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

DEFAULT_ALIAS_LENGTH = 8
MIN_ALIAS_LENGTH = 3
MAX_ALIAS_LENGTH = 20

HttpGet = Callable[..., Any]
HttpPost = Callable[..., Any]

# 运行时状态：账号列表 + token 缓存
_accounts_lock = threading.Lock()
_accounts: List[dict] = []
_token_cache: Dict[str, dict] = {}  # email -> {"access_token": ..., "expires_at": ...}
_accounts_file: str = ""
_alias_counter = 0
_alias_counter_lock = threading.Lock()


def reset_runtime_state() -> None:
    global _accounts, _token_cache, _accounts_file, _alias_counter
    with _accounts_lock:
        _accounts.clear()
    _token_cache.clear()
    _accounts_file = ""
    _alias_counter = 0


# ── 账号解析 ──────────────────────────────────────────

def _parse_text_accounts(text: str) -> Tuple[List[dict], List[str]]:
    """解析 ---- 分隔的账号文本（与 mail.py 格式兼容）。

    格式：邮箱----密码----client_id----refresh_token
    返回 (账号列表, 警告列表)。
    """
    accounts = []
    warnings = []
    for i, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("----")
        if len(parts) != 4:
            warnings.append(f"第 {i} 行格式错误，已跳过（需要 4 个字段用 ---- 分隔）")
            continue
        email, password, client_id, refresh_token = [part.strip() for part in parts]
        if not email or not client_id or not refresh_token:
            warnings.append(f"第 {i} 行缺少邮箱、client_id 或 refresh_token，已跳过")
            continue
        accounts.append({
            "email": email,
            "password": password,
            "client_id": client_id,
            "refresh_token": refresh_token,
        })
    return accounts, warnings


def _parse_json_accounts(data: Any) -> List[dict]:
    """解析 JSON 格式的账号。"""
    accounts_raw = data if isinstance(data, list) else data.get("accounts", [])
    if not isinstance(accounts_raw, list):
        raise Exception("MicrosoftMail 账号文件中的 accounts 必须是列表")

    accounts = []
    for acc in accounts_raw:
        if not isinstance(acc, dict):
            continue
        email = str(acc.get("email", "")).strip()
        client_id = str(acc.get("client_id", "")).strip()
        refresh_token = str(acc.get("refresh_token", "")).strip()
        password = str(acc.get("password", "")).strip()
        if email and client_id and refresh_token:
            accounts.append({
                "email": email,
                "password": password,
                "client_id": client_id,
                "refresh_token": refresh_token,
            })
    return accounts


def _load_accounts(accounts_file: str) -> List[dict]:
    """从文件加载账号列表。自动检测 JSON / 文本格式。"""
    path = Path(accounts_file)
    if not path.exists():
        raise Exception(
            f"MicrosoftMail 账号文件不存在: {accounts_file}\n"
            f"支持 JSON 和文本两种格式，详见文档。"
        )

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise Exception(f"MicrosoftMail 账号文件为空: {accounts_file}")

    # 尝试 JSON 解析
    try:
        data = json.loads(text)
        accounts = _parse_json_accounts(data)
        if accounts:
            return accounts
        raise Exception("MicrosoftMail JSON 账号文件中没有有效账号")
    except json.JSONDecodeError:
        pass

    # 回退到文本格式解析（---- 分隔）
    accounts, warnings = _parse_text_accounts(text)
    for w in warnings:
        print(f"[MicrosoftMail] 警告: {w}")
    if not accounts:
        raise Exception(
            f"MicrosoftMail 账号文件格式错误: {accounts_file}\n"
            f"支持两种格式：\n"
            f"  JSON: {{\"accounts\": [{{\"email\":\"...\",\"client_id\":\"...\",\"refresh_token\":\"...\"}}]}}\n"
            f"  文本: 邮箱----密码----client_id----refresh_token"
        )
    return accounts


def ensure_accounts_loaded(accounts_file: str) -> List[dict]:
    """确保账号已加载（带锁）。"""
    global _accounts, _accounts_file
    with _accounts_lock:
        if _accounts and _accounts_file == accounts_file:
            return list(_accounts)
        _accounts = _load_accounts(accounts_file)
        _accounts_file = accounts_file
        return list(_accounts)


# ── Token 管理 ────────────────────────────────────────

def _refresh_access_token(client_id: str, refresh_token: str) -> dict:
    """用 refresh_token 换取 token 响应。"""
    data = urlencode({
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": "https://graph.microsoft.com/.default",
    }).encode()

    req = Request(TOKEN_URL, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded",
    })

    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = e.read().decode(errors="replace")
        raise Exception(f"MicrosoftMail 获取 token 失败 ({e.code}): {body}") from e
    except Exception as exc:
        raise Exception(f"MicrosoftMail 获取 token 网络错误: {exc}") from exc


def _get_access_token(account: dict) -> str:
    """获取 access_token（优先使用缓存）。"""
    email = account["email"]
    cache = _token_cache.get(email)
    if cache and cache.get("access_token") and cache.get("expires_at", 0) > time.time() + 120:
        return cache["access_token"]

    token_resp = _refresh_access_token(account["client_id"], account["refresh_token"])
    expires_in = int(token_resp.get("expires_in", 3600) or 3600)
    access_token = token_resp["access_token"]

    _token_cache[email] = {
        "access_token": access_token,
        "expires_at": time.time() + expires_in,
    }
    # 如果返回了新的 refresh_token，更新缓存
    if token_resp.get("refresh_token"):
        account["refresh_token"] = token_resp["refresh_token"]
    return access_token


# ── 别名生成 ──────────────────────────────────────────

def _generate_alias(prefix: str = "", length: int = DEFAULT_ALIAS_LENGTH) -> str:
    """生成随机别名。

    Args:
        prefix: 别名前缀（如 "grok"）
        length: 别名总长度（不含前缀），默认 8，范围 [3, 20]
    """
    global _alias_counter
    with _alias_counter_lock:
        _alias_counter += 1
        counter = _alias_counter

    length = max(MIN_ALIAS_LENGTH, min(length, MAX_ALIAS_LENGTH))
    # 随机部分 = 总长度 - 前缀长度 - 计数器长度
    counter_str = str(counter)
    random_len = max(2, length - len(counter_str))
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=random_len))
    return f"{prefix}{counter_str}{suffix}"


def _make_alias_email(base_email: str, alias: str) -> str:
    """将 base_email 转换为带别名的邮箱地址。

    user@outlook.com -> user+alias@outlook.com
    """
    local, _, domain = base_email.partition("@")
    if not domain:
        raise Exception(f"MicrosoftMail 邮箱格式无效: {base_email}")
    return f"{local}+{alias}@{domain}"


# ── 公开接口 ──────────────────────────────────────────

def pick_account(accounts_file: str) -> dict:
    """随机选一个账号。"""
    accounts = ensure_accounts_loaded(accounts_file)
    if not accounts:
        raise Exception("MicrosoftMail 没有可用账号")
    return random.choice(accounts)


def create_mailbox(
    accounts_file: str,
    alias_prefix: str = "",
    alias_length: int = DEFAULT_ALIAS_LENGTH,
) -> Tuple[str, str]:
    """创建邮箱（实际上是给已有账号添加别名）。

    Args:
        accounts_file: 账号文件路径（JSON 或文本格式）
        alias_prefix: 别名前缀（如 "grok"），可选
        alias_length: 别名随机部分长度，默认 8

    返回 (alias_email, access_token)。
    """
    account = pick_account(accounts_file)
    access_token = _get_access_token(account)

    alias = _generate_alias(
        prefix=(alias_prefix or "").strip(),
        length=alias_length,
    )
    alias_email = _make_alias_email(account["email"], alias)
    print(f"[*] 已创建 MicrosoftMail 别名: {alias_email} (基于 {account['email']})")
    return alias_email, access_token


def fetch_emails(
    access_token: str,
    folder: str = "inbox",
    top: int = 20,
    keyword: str = None,
) -> List[dict]:
    """获取邮件列表。"""
    params = {
        "$top": str(top),
        "$orderby": "receivedDateTime desc",
        "$select": "id,subject,from,receivedDateTime,bodyPreview,isRead,hasAttachments",
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Prefer": 'outlook.body-content-type="text"',
    }

    if keyword:
        params["$search"] = f'"{keyword}"'
        headers["ConsistencyLevel"] = "eventual"

    url = f"{GRAPH_BASE}/me/mailFolders/{folder}/messages?{urlencode(params)}"
    req = Request(url, headers=headers)

    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data.get("value", [])
    except HTTPError as e:
        body = e.read().decode(errors="replace")
        raise Exception(f"MicrosoftMail 获取邮件失败 ({e.code}): {body}") from e
    except Exception as exc:
        raise Exception(f"MicrosoftMail 获取邮件网络错误: {exc}") from exc


def fetch_email_detail(access_token: str, message_id: str) -> dict:
    """获取单封邮件详情（含正文）。"""
    params = {
        "$select": "id,subject,from,toRecipients,receivedDateTime,body,bodyPreview,isRead",
    }
    url = f"{GRAPH_BASE}/me/messages/{message_id}?{urlencode(params)}"
    req = Request(url, headers={
        "Authorization": f"Bearer {access_token}",
        "Prefer": 'outlook.body-content-type="text"',
    })

    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = e.read().decode(errors="replace")
        raise Exception(f"MicrosoftMail 获取邮件详情失败 ({e.code}): {body}") from e
    except Exception as exc:
        raise Exception(f"MicrosoftMail 获取邮件详情网络错误: {exc}") from exc


def wait_for_code(
    accounts_file: str,
    alias_email: str,
    access_token: str,
    *,
    timeout: int = 180,
    poll_interval: int = 5,
    raise_if_cancelled: Callable[[Optional[Callable[[], bool]]], None],
    sleep_with_cancel: Callable[[float, Optional[Callable[[], bool]]], None],
    log_callback: Optional[Callable[[str], None]] = None,
    cancel_callback: Optional[Callable[[], bool]] = None,
) -> str:
    """轮询收件箱，等待验证码邮件。

    alias_email 如 user+grok1@outlook.com，Outlook 会把发到该地址的邮件
    投递到 user@outlook.com 的收件箱。我们通过 Graph API 搜索来匹配。
    """
    deadline = time.time() + timeout
    seen_ids: set = set()

    while time.time() < deadline:
        raise_if_cancelled(cancel_callback)

        try:
            messages = fetch_emails(access_token, folder="inbox", top=20)
        except Exception as exc:
            if log_callback:
                log_callback(f"[Debug] MicrosoftMail 拉取邮件列表失败: {exc}")
            sleep_with_cancel(poll_interval, cancel_callback)
            continue

        for msg in messages:
            msg_id = msg.get("id")
            if not msg_id or msg_id in seen_ids:
                continue

            subject = msg.get("subject", "") or ""
            preview = msg.get("bodyPreview", "") or ""

            seen_ids.add(msg_id)

            if log_callback:
                log_callback(f"[Debug] MicrosoftMail 收到邮件: {subject}")

            # 尝试从主题和预览中提取验证码
            combined = f"{subject}\n{preview}"
            code = extract_verification_code(combined, subject)
            if code:
                if log_callback:
                    log_callback(f"[*] MicrosoftMail 从邮件中提取到验证码: {code}")
                return code

            # 如果预览不够，获取完整正文再试
            try:
                detail = fetch_email_detail(access_token, msg_id)
                body_content = detail.get("body", {}).get("content", "") or ""
                # 检查收件人是否匹配别名邮箱
                to_recipients = detail.get("toRecipients", [])
                to_addrs = [r.get("emailAddress", {}).get("address", "").lower() for r in to_recipients]
                if to_addrs and alias_email.lower() not in to_addrs:
                    if log_callback:
                        log_callback("[Debug] MicrosoftMail 邮件收件人不匹配，跳过")
                    continue

                full_text = f"{subject}\n{body_content}"
                code = extract_verification_code(full_text, subject)
                if code:
                    if log_callback:
                        log_callback(f"[*] MicrosoftMail 从邮件详情中提取到验证码: {code}")
                    return code
            except Exception as exc:
                if log_callback:
                    log_callback(f"[Debug] MicrosoftMail 获取邮件详情失败: {exc}")

        sleep_with_cancel(poll_interval, cancel_callback)

    raise Exception(f"MicrosoftMail 在 {timeout}s 内未收到验证码邮件")


def test_connection(accounts_file: str) -> Tuple[bool, str]:
    """测试连接：尝试加载账号并获取一个 access_token。"""
    try:
        accounts = ensure_accounts_loaded(accounts_file)
        if not accounts:
            return False, "没有可用账号"
        account = random.choice(accounts)
        _get_access_token(account)
        return True, f"MicrosoftMail 连接成功（{account['email']}）"
    except Exception as exc:
        return False, f"MicrosoftMail 连接失败: {exc}"
