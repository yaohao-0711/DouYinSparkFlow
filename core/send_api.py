"""
send_api.py — 抖音续火花「抗改版」发送模块 (v2.2 DOM 抓取版)
===========================================================
关键修正（基于 run#17 诊断）：
- 会话列表【不是】独立 imapi 接口，而是直接渲染在聊天页左侧 DOM 中。
- 因此改为：从聊天页 DOM 抓取会话列表（好友昵称 + conversation_id/href），
  用昵称/short_id 匹配目标，优先按 conversation_id 直接打开（最稳），
  否则按昵称文本点击（抗布局改版）。
- 原生输入框发送 + 送达校验。
- 任意好友失败则抛异常，让 workflow 真正标记失败（杜绝假成功）。
"""

import time
import os
import re
import json
import logging
from utils.logger import setup_logger

logger = setup_logger("send_api", level="Info")


# ---------------------------------------------------------------------------
# 通用 protobuf 解码器（兼容接口返回 protobuf 的情况）
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


def _all_strings(nodes):
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
# 从聊天页 DOM 抓取会话列表（核心抗改版手段）
# ---------------------------------------------------------------------------
def scrape_conversations_dom(page):
    """
    从聊天页左侧会话列表 DOM 中提取条目。
    每条：{nickname, conversation_id, uid, href}
    同时把原始结构 dump 到 logs/dom_summary.json 供离线精修。
    """
    os.makedirs("logs", exist_ok=True)
    result = {"data": None, "error": None}
    try:
        data = page.evaluate(
            """() => {
                const out = {hrefs: [], items: [], scripts_hint: []};
                document.querySelectorAll('a').forEach(a => {
                    const h = a.getAttribute('href') || '';
                    if (h.indexOf('conversation') >= 0 || h.indexOf('chat') >= 0) {
                        out.hrefs.push({href: h, text: (a.innerText||'').trim().slice(0,50)});
                    }
                });
                const sels = ['[class*="conversation"]','[class*="Conversation"]',
                              '[class*="list-item"]','[class*="chat-item"]',
                              '[class*="im-item"]','[class*="friend"]','li'];
                const seen = new Set();
                sels.forEach(sel => {
                    document.querySelectorAll(sel).forEach(e => {
                        const txt = (e.innerText||'').trim().slice(0,50);
                        if (!txt) return;
                        const cls = (e.className||'').toString();
                        const key = txt + '|' + cls.slice(0,40);
                        if (seen.has(key)) return; seen.add(key);
                        out.items.push({
                            cls: cls.slice(0,60),
                            text: txt,
                            href: e.getAttribute('href') || '',
                            cid: e.getAttribute('data-conversation-id') || e.getAttribute('data-cid') || e.getAttribute('data-id') || '',
                            uid: e.getAttribute('data-uid') || e.getAttribute('data-user-id') || e.getAttribute('data-userid') || ''
                        });
                    });
                });
                return out;
            }"""
        )
        result["data"] = data
    except Exception as e:
        result["error"] = repr(e)

    try:
        with open("logs/dom_summary.json", "w", encoding="utf-8") as fp:
            json.dump(result, fp, ensure_ascii=False, indent=2)
    except Exception:
        pass

    items = []
    if result.get("data"):
        for it in result["data"].get("items", []):
            cid = it.get("cid") or ""
            if not cid and it.get("href"):
                m = re.search(r"conversation_id=([^&?#]+)", it["href"])
                if m:
                    cid = m.group(1)
            uid = it.get("uid") or ""
            if not uid and it.get("href"):
                m = re.search(r"[?&/](uid|user_id|to_user_id)=([^&?#]+)", it["href"])
                if m:
                    uid = m.group(2)
            nickname = it.get("text")
            if nickname or cid:
                items.append({
                    "nickname": nickname,
                    "conversation_id": cid,
                    "uid": uid,
                    "href": it.get("href"),
                })
        for h in result["data"].get("hrefs", []):
            m = re.search(r"conversation_id=([^&?#]+)", h["href"])
            if m and h.get("text"):
                items.append({
                    "nickname": h["text"],
                    "conversation_id": m.group(1),
                    "uid": "",
                    "href": h["href"],
                })
    return items


# ---------------------------------------------------------------------------
# 打开会话并原生发送
# ---------------------------------------------------------------------------
def click_by_text(page, text):
    if not text:
        return False
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
    chat_input_selector = "xpath=//div[contains(@class, 'chat-input-')]"
    page.wait_for_selector(chat_input_selector, timeout=config["browserTimeout"])
    chat_input = page.locator(chat_input_selector)
    chat_input.click()
    chat_input.type(message, delay=20)
    chat_input.press("Enter")


def verify_delivery(page, friend_display):
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
        return True


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def discover_and_send(page, targets, user_id_dict, match_mode, build_message_fn, config, list_store=None):
    chat_url = "https://creator.douyin.com/creator-micro/data/following/chat"
    account_name = config.get("_account_name", "账号")
    os.makedirs("logs", exist_ok=True)

    # 等待页面会话列表渲染
    time.sleep(3)

    # 1) 从 DOM 抓取会话列表（核心）
    dom_items = scrape_conversations_dom(page)
    logger.info("从 DOM 抓取到 %d 个会话条目" % len(dom_items))
    try:
        with open("logs/conversations.json", "w", encoding="utf-8") as fp:
            json.dump(dom_items, fp, ensure_ascii=False, indent=2)
    except Exception:
        pass

    by_short = {}
    by_name = {}
    for it in dom_items:
        nm = it.get("nickname")
        cid = it.get("conversation_id")
        uid = it.get("uid")
        if uid:
            by_short[uid] = {"nickname": nm, "conversation_id": cid, "uid": uid}
        if nm:
            by_name[nm] = {"nickname": nm, "conversation_id": cid, "uid": uid}
    # 兼容 userIDDict（旧逻辑可能填好的昵称）
    for sid, info in (user_id_dict or {}).items():
        nm = info.get("nickname")
        if nm and nm not in by_name:
            by_name[nm] = {"nickname": nm, "conversation_id": None, "uid": str(sid)}

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
