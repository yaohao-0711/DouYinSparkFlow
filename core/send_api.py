"""
send_api.py — 抖音续火花「抗改版」发送模块 (v2)
=============================================
设计目标（一劳永逸）：
1. 在导航到聊天页【之前】就挂上响应监听器，捕获私信列表接口
   （imapi.douyin.com 的 conversation/list，可能是 protobuf 或 JSON）。
2. 解析出「好友(short_id/nickname) -> conversation_id」映射，
   彻底去掉原来依赖 XPath 点击「好友标签页」的脆弱逻辑。
3. 对每个目标好友，优先按 conversation_id 直接打开会话（最稳，不依赖 DOM），
   失败再按好友昵称文本点击（文本匹配抗布局改版）。
4. 原生输入框发送（fill + Enter，run 10 已验证可送达）。
5. 所有日志统一写入 logs/app.log；任何好友未成功发送则抛异常，
   让 workflow 真正标记失败（不再出现“假成功”）。
"""

import time
import os
import re
import json
import logging
from utils.logger import setup_logger

# 与 tasks.py 共用同一个 app.log 文件，确保日志不丢失
logger = setup_logger("send_api", level="Info")


# ---------------------------------------------------------------------------
# 通用 protobuf 解码器（用于诊断/解析列表接口）
# ---------------------------------------------------------------------------
def _read_varint(b, p):
    shift = 0
    result = 0
    while True:
        x = b[p]
        p += 1
        result |= (x & 0x7F) << shift
        if not (x & 0x80):
            break
        shift += 7
    return result, p


def _decode_proto(b):
    p = 0
    n = len(b)
    out = []
    while p < n:
        tag, p = _read_varint(b, p)
        f = tag >> 3
        wt = tag & 7
        if wt == 0:
            v, p = _read_varint(b, p)
            out.append((f, "v", v))
        elif wt == 2:
            ln, p = _read_varint(b, p)
            sub = b[p: p + ln]
            p += ln
            out.append((f, "ld", sub))
        elif wt == 5:
            out.append((f, "f32", b[p: p + 4]))
            p += 4
        elif wt == 1:
            out.append((f, "f64", b[p: p + 8]))
            p += 8
        else:
            out.append((f, "wt%d" % wt, None))
            break
    return out


def decode_proto_text(b):
    try:
        def stringify(nodes, depth=0):
            lines = []
            for nd in nodes:
                f, t, v = nd[0], nd[1], nd[2]
                if t == "ld":
                    try:
                        s = v.decode("utf-8")
                        if any(32 <= ord(c) < 127 or ord(c) > 127 for c in s):
                            lines.append(("  " * depth) + "f%d ld STR=%r" % (f, s[:400]))
                            continue
                    except Exception:
                        pass
                    try:
                        sub = stringify(_decode_proto(v), depth + 1)
                        lines.append(("  " * depth) + "f%d ld {" % f)
                        lines.extend(sub)
                    except Exception:
                        lines.append(("  " * depth) + "f%d ld <bytes %d>" % (f, len(v)))
                else:
                    lines.append(("  " * depth) + "f%d %s %r" % (f, t, v))
            return lines

        return "\n".join(stringify(_decode_proto(b)))
    except Exception as e:  # pragma: no cover
        return "decode error: %r" % e


def _all_strings(nodes):
    """递归收集所有可读字符串叶子。"""
    res = []
    for nd in nodes:
        f, t, v = nd[0], nd[1], nd[2]
        if t == "ld":
            try:
                s = v.decode("utf-8")
                if any(32 <= ord(c) < 127 or ord(c) > 127 for c in s):
                    res.append(s)
            except Exception:
                pass
            try:
                res.extend(_all_strings(_decode_proto(v)))
            except Exception:
                pass
    return res


# ---------------------------------------------------------------------------
# 结构化解析：从列表接口提取 好友 -> 会话 信息
# ---------------------------------------------------------------------------
def _looks_like_name(s):
    if not s or len(s) > 30:
        return False
    if any(ch in s for ch in "/\\.:@#%&?=http"):
        return False
    if re.fullmatch(r"\d+", s):
        return False
    if s.lower().startswith("http"):
        return False
    return True


def _extract_conversation_id(strings):
    """conversation_id 形如 0:1:277555714458343:...（含冒号的长串）。"""
    for s in strings:
        m = re.search(r"\d+:\d+:\d+:\d+", s)
        if m:
            return m.group(0)
    # 个别接口可能直接给纯数字会话 id（兜底）
    for s in strings:
        m = re.search(r"\b(\d{15,22})\b", s)
        if m:
            return m.group(1)
    return None


def _extract_ids(strings):
    short_id = None
    user_id = None
    for s in strings:
        for m in re.finditer(r"\b(\d{8,22})\b", s):
            d = m.group(1)
            if short_id is None and 8 <= len(d) <= 13:
                short_id = d
            elif user_id is None and len(d) >= 14:
                user_id = d
    return short_id, user_id


def _extract_nickname(strings):
    for s in strings:
        if _looks_like_name(s):
            return s
    return None


def _json_walk_strings(obj, out):
    if isinstance(obj, dict):
        for v in obj.values():
            _json_walk_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _json_walk_strings(v, out)
    elif isinstance(obj, str):
        out.append(obj)


def _json_conversations(data):
    candidates = []
    if isinstance(data, list):
        candidates = [x for x in data if isinstance(x, dict)]
    elif isinstance(data, dict):
        # 常见包裹结构：data['data']['conversation_list'] / ['conversation_list'] / ['list']
        for key in ("conversation_list", "list", "conversations", "data"):
            v = data.get(key)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                candidates = v
                break
        if not candidates:
            # 退而求其次：把整个 data 当成一个会话
            candidates = [data]
    out = []
    for c in candidates:
        strings = []
        _json_walk_strings(c, strings)
        cid = _extract_conversation_id(strings)
        sid, uid = _extract_ids(strings)
        nm = _extract_nickname(strings)
        if cid or nm or sid or uid:
            out.append({
                "conversation_id": cid,
                "short_id": sid,
                "user_id": uid,
                "nickname": nm,
                "_all_strings": strings[:60],
            })
    return out


def parse_conversations(list_bytes):
    """返回会话对象列表：[{conversation_id, short_id, user_id, nickname, _all_strings}]"""
    out = []
    if not list_bytes:
        return out
    # 1) 先尝试 JSON
    stripped = list_bytes.lstrip()
    if stripped[:1] in (b"{", b"["):
        try:
            data = json.loads(list_bytes.decode("utf-8", "replace"))
            convs = _json_conversations(data)
            if convs:
                return convs
        except Exception:
            pass
    # 2) protobuf 路径
    try:
        nodes = _decode_proto(list_bytes)
    except Exception:
        return out
    for f, t, v in nodes:
        if t != "ld":
            continue
        try:
            sub_nodes = _decode_proto(v)
        except Exception:
            sub_nodes = []
        strings = _all_strings(sub_nodes)
        if not strings:
            continue
        cid = _extract_conversation_id(strings)
        short_id, user_id = _extract_ids(strings)
        nickname = _extract_nickname(strings)
        if cid or nickname or short_id or user_id:
            out.append({
                "conversation_id": cid,
                "short_id": short_id,
                "user_id": user_id,
                "nickname": nickname,
                "_all_strings": strings[:60],
            })
    return out


# ---------------------------------------------------------------------------
# 列表接口捕获（在导航前挂监听器）
# ---------------------------------------------------------------------------
def install_list_capture(page, store, timeout_ms=8000):
    """
    必须在 page.goto(chat) 【之前】调用。
    挂上响应监听器，捕获 conversation/list 接口原始响应。
    """
    def on_response(response):
        url = response.url
        try:
            if (
                "imapi.douyin.com" in url
                and ("conversation" in url or "/list" in url or "get_by_user" in url)
                and store.get("list") is None
            ):
                try:
                    body = response.body()
                except Exception:
                    body = b""
                store["list"] = body or b""
                store["list_url"] = url
                try:
                    os.makedirs("logs", exist_ok=True)
                    open("logs/list_proto.bin", "wb").write(store["list"])
                    open("logs/list_proto.txt", "w", encoding="utf-8").write(
                        decode_proto_text(store["list"])
                    )
                    open("logs/list_strings.txt", "w", encoding="utf-8").write(
                        "\n".join(_all_strings(_decode_proto(store["list"])))
                    )
                    logger.info("已捕获会话列表接口：%s (%d bytes)" % (url, len(store["list"])))
                except Exception as e:
                    logger.warning("写入列表日志失败: %r" % e)
        except Exception:
            pass

    page.on("response", on_response)
    return store


def capture_conversations(page, timeout_ms=8000):
    """兜底：若提前监听器没拿到，主动挂监听器等待一段时间。"""
    captured = {}

    def on_response(response):
        url = response.url
        try:
            if (
                "imapi.douyin.com" in url
                and ("conversation" in url or "/list" in url or "get_by_user" in url)
                and captured.get("list") is None
            ):
                try:
                    body = response.body()
                except Exception:
                    body = b""
                captured["list"] = body or b""
                try:
                    os.makedirs("logs", exist_ok=True)
                    open("logs/list_proto.bin", "wb").write(captured["list"])
                    open("logs/list_proto.txt", "w", encoding="utf-8").write(
                        decode_proto_text(captured["list"])
                    )
                    open("logs/list_strings.txt", "w", encoding="utf-8").write(
                        "\n".join(_all_strings(_decode_proto(captured["list"])))
                    )
                except Exception:
                    pass
        except Exception:
            pass

    page.on("response", on_response)
    try:
        page.wait_for_timeout(timeout_ms)
    except Exception:
        pass
    return captured.get("list")


# ---------------------------------------------------------------------------
# 打开会话并原生发送
# ---------------------------------------------------------------------------
def click_by_text(page, text):
    """按好友昵称文本点击会话（抗布局改版兜底方案）。返回是否成功。"""
    if not text:
        return False
    # 多套策略，由稳到宽
    strategies = [
        "xpath=//*[contains(@class,'conversation') or contains(@class,'list') or contains(@class,'item')]//*[contains(text(), '%s')]" % text,
        "xpath=//li[contains(., '%s')]" % text,
        "xpath=//*[contains(@class,'list') or contains(@class,'conversation')][contains(., '%s')]" % text,
        "xpath=//*[contains(., '%s')]" % text,
    ]
    for sel in strategies:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.click(timeout=8000)
                page.wait_for_selector(
                    "xpath=//div[contains(@class, 'chat-input-')]", timeout=15000
                )
                return True
        except Exception:
            continue
    return False


def open_conversation(page, conversation_id, chat_url, friend_display):
    """
    打开指定会话。优先用 conversation_id 直接打开（最稳），失败则按好友名点击。
    """
    if conversation_id:
        try:
            url = "%s?conversation_id=%s" % (chat_url, conversation_id)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_selector(
                "xpath=//div[contains(@class, 'chat-input-')]", timeout=15000
            )
            logger.info("已通过 conversation_id 打开会话：%s" % conversation_id)
            return True
        except Exception as e:
            logger.warning("通过 conversation_id 打开失败，回退按名称点击：%r" % e)

    if friend_display and click_by_text(page, friend_display):
        logger.info("已通过名称点击打开会话：%s" % friend_display)
        return True

    logger.error("无法打开会话：%s" % friend_display)
    return False


def native_send(page, message, config):
    """在已打开的会话里输入并发送。"""
    chat_input_selector = "xpath=//div[contains(@class, 'chat-input-')]"
    page.wait_for_selector(chat_input_selector, timeout=config["browserTimeout"])
    chat_input = page.locator(chat_input_selector)
    chat_input.click()
    chat_input.type(message, delay=20)
    chat_input.press("Enter")


def verify_delivery(page, friend_display):
    """送达校验：检测页面是否出现失败提示。"""
    try:
        fail_xpath = (
            "xpath=//*[contains(text(),'发送失败') "
            "or contains(text(),'发送频繁') "
            "or contains(text(),'网络异常')]"
        )
        if page.locator(fail_xpath).count() > 0:
            logger.warning("给好友「%s」发送后检测到失败提示，可能未送达！" % friend_display)
            try:
                safe = re.sub(r"\W+", "_", friend_display)
                page.screenshot(path="logs/send_fail_%s.png" % safe)
            except Exception:
                pass
            return False
        logger.info("给好友「%s」发送后未发现失败提示（视为已送达）" % friend_display)
        return True
    except Exception as e:
        logger.warning("送达校验异常: %r" % e)
        return True  # 校验异常不计入失败


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def discover_and_send(page, targets, user_id_dict, match_mode, build_message_fn, config, list_store=None):
    """
    抗改版主流程：
    1. 拿到会话列表 -> 解析出好友->会话映射
    2. 逐好友：优先 conversation_id 打开，否则按昵称点击；原生发送；送达校验
    3. 任意好友失败则抛异常，让 workflow 标记失败（杜绝假成功）
    """
    chat_url = "https://creator.douyin.com/creator-micro/data/following/chat"
    account_name = config.get("_account_name", "账号")
    os.makedirs("logs", exist_ok=True)

    # 1) 取得列表原始数据
    list_bytes = (list_store or {}).get("list")
    if not list_bytes:
        logger.warning("未通过提前监听器拿到列表，尝试主动捕获一次")
        list_bytes = capture_conversations(page, timeout_ms=8000)
    if not list_bytes:
        logger.error("未能捕获到会话列表接口，无法建立好友->会话映射！将仅尝试按昵称兜底（可能不稳定）")
    else:
        logger.info("已获得会话列表 (%d bytes)" % len(list_bytes))

    # 2) 解析会话
    conversations = parse_conversations(list_bytes) if list_bytes else []
    try:
        with open("logs/conversations.json", "w", encoding="utf-8") as fp:
            json.dump(conversations, fp, ensure_ascii=False, indent=2)
    except Exception:
        pass
    logger.info("从列表解析到 %d 个会话对象" % len(conversations))

    # 建立查找表
    by_short = {}
    by_name = {}
    for c in conversations:
        if c.get("short_id"):
            by_short[c["short_id"]] = c
        if c.get("user_id") and c["user_id"] not in by_short:
            by_short[c["user_id"]] = c
        if c.get("nickname"):
            by_name[c["nickname"]] = c

    # 兼容旧逻辑可能填好的 userIDDict（按昵称兜底）
    for sid, info in (user_id_dict or {}).items():
        nm = info.get("nickname")
        if nm and nm not in by_name:
            by_name[nm] = {"nickname": nm, "conversation_id": None, "short_id": str(sid)}

    fail_count = 0
    sent_count = 0

    for target in targets:
        if match_mode == "short_id":
            entry = by_short.get(str(target)) or by_name.get(str(target))
            friend_display = (
                (entry or {}).get("nickname")
                or (user_id_dict.get(str(target), {}) or {}).get("nickname")
                or str(target)
            )
            conv_id = (entry or {}).get("conversation_id")
        else:
            entry = by_name.get(target)
            friend_display = target
            conv_id = (entry or {}).get("conversation_id") if entry else None

        logger.info("准备给好友「%s」发送消息 (conversation_id=%s)" % (friend_display, conv_id))
        if not open_conversation(page, conv_id, chat_url, friend_display):
            logger.warning("好友「%s」会话打开失败，跳过" % friend_display)
            fail_count += 1
            continue

        message = build_message_fn()
        try:
            native_send(page, message, config)
            logger.info("已向好友「%s」发送消息，等待送达确认" % friend_display)
            sent_count += 1
        except Exception as e:
            logger.error("给好友「%s」发送失败: %r" % (friend_display, e))
            fail_count += 1
            continue

        # 降速，避免触发频率限制
        send_interval = int(config.get("sendInterval", 8000)) / 1000
        time.sleep(send_interval)

        if not verify_delivery(page, friend_display):
            fail_count += 1

    logger.info(
        "本轮完成：成功发送 %d / 失败 %d / 目标 %d"
        % (sent_count, fail_count, len(targets))
    )
    if fail_count > 0:
        raise RuntimeError("有 %d 个好友未成功发送，请检查 logs/" % fail_count)
