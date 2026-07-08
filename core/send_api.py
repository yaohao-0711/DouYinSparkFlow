import os
import json
import time
import logging
from utils.logger import setup_logger

logger = setup_logger(level="Info")


def _lvl(s):
    return {
        "Debug": logging.DEBUG,
        "Info": logging.INFO,
        "Warning": logging.WARNING,
        "Error": logging.ERROR,
    }.get(s, logging.INFO)


def discover_and_send(page, targets, user_id_dict, match_mode, build_message_fn, config):
    account = config.get("_account_name", "账号")
    log_level = config.get("logLevel", "Info")
    logger.setLevel(_lvl(log_level))

    logger.info(f"[{account}] ===== 抗改版发送流程开始，目标数={len(targets)} =====")

    # ---- 网络捕获 ----
    net = []

    def on_resp(resp):
        try:
            u = resp.url
            if "douyin.com" in u:
                ct = resp.headers.get("content-type", "")
                net.append({
                    "url": u,
                    "status": resp.status,
                    "method": resp.request.method,
                    "content_type": ct,
                    "length": int(resp.headers.get("content-length", 0) or 0),
                })
        except Exception:
            pass

    page.on("response", on_resp)

    # ---- 等待聊天页渲染 ----
    logger.info(f"[{account}] 等待聊天页加载 (6s)...")
    time.sleep(6)

    # ---- 登录态检测（基于真实重定向，避免误判）----
    page_url = page.url
    logger.info(f"[{account}] 当前页面 URL: {page_url}")
    try:
        body_text = page.evaluate("() => (document.body ? document.body.innerText : '')") or ""
    except Exception:
        body_text = ""
    logger.info(f"[{account}] 页面文本(前1000字): {body_text[:1000]}")
    is_login_page = ("passport" in page_url.lower()) or ("login" in page_url.lower() and "creator-micro" not in page_url.lower())
    if is_login_page:
        logger.error(f"[{account}] !!! 未登录：页面被重定向到登录页 ({page_url})，Cookie 已失效")
        logger.error(f"[{account}] !!! 请重新从 creator.douyin.com 导出 Cookie 并更新 GitHub Secret COOKIES_28860838926")
        raise RuntimeError(f"[{account}] 未登录，Cookie 失效，请更新 COOKIES_28860838926")
    logger.info(f"[{account}] 页面未被重定向到登录页，视为已登录（继续）")

    # ---- 导出完整 DOM ----
    try:
        html = page.content()
        with open("logs/dom_dump.html", "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(f"[{account}] 已导出 DOM -> logs/dom_dump.html ({len(html)} 字节)")
    except Exception as e:
        logger.error(f"[{account}] DOM 导出失败: {e}")

    # ---- 导出候选条目摘要（含 href 与 HTML 片段，便于定位好友 id）----
    try:
        summary = page.evaluate("""() => {
            const out = [];
            const seen = new Set();
            const sel = 'li, [role=listitem], a, div[role=button], [class*=list-item], [class*=conversation], [class*=item]';
            const items = document.querySelectorAll(sel);
            for (const el of items) {
                const txt = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                if (!txt) continue;
                if (txt.length > 80) continue;
                const key = txt.slice(0, 40);
                if (seen.has(key)) continue;
                seen.add(key);
                const cls = (typeof el.className === 'string') ? el.className : '';
                const a = el.querySelector('a') || el;
                const href = (a.getAttribute && a.getAttribute('href')) || '';
                out.push({ tag: el.tagName, cls: cls.slice(0,140), text: txt.slice(0,70), href: href.slice(0,120), html: (el.outerHTML||'').slice(0,400) });
                if (out.length > 500) break;
            }
            return { url: location.href, items: out };
        }""")
        with open("logs/dom_summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        logger.info(f"[{account}] 已导出 dom_summary.json，候选条目 {len(summary.get('items', []))}")
    except Exception as e:
        logger.error(f"[{account}] dom_summary 导出失败: {e}")

    # ---- 逐目标：定位 -> 点击 -> 发送 ----
    sent = 0
    for t in targets:
        logger.info(f"[{account}] ---- 处理目标 {t} ----")
        try:
            msg = build_message_fn()
        except Exception as e:
            logger.error(f"[{account}] 构建消息失败: {e}")
            msg = "[666]"
        logger.info(f"[{account}] 消息内容: {msg!r}")

        # 在 DOM 中扫描含目标字符串的最小元素
        try:
            hit = page.evaluate("""(target) => {
                const t = String(target);
                let best = null, bestLen = Infinity;
                const all = document.querySelectorAll('*');
                for (const el of all) {
                    const h = el.outerHTML || '';
                    if (h.indexOf(t) !== -1) {
                        const len = h.length;
                        if (len < bestLen) { bestLen = len; best = el; }
                    }
                }
                if (!best) return null;
                const cls = (typeof best.className === 'string') ? best.className : '';
                return {
                    tag: best.tagName,
                    cls: cls.slice(0, 200),
                    text: (best.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 160),
                    html: best.outerHTML.slice(0, 1200)
                };
            }""", t)
        except Exception as e:
            logger.error(f"[{account}] 目标 {t} DOM 扫描异常: {e}")
            hit = None

        if not hit:
            logger.warning(f"[{account}] 目标 {t} 未在 DOM 中找到任何匹配元素，跳过")
            continue

        logger.info(f"[{account}] 目标 {t} 命中元素 tag={hit['tag']} cls={hit['cls']}")
        logger.info(f"[{account}] 命中元素文本: {hit['text']}")
        logger.debug(f"[{account}] 命中元素HTML片段: {hit['html']}")

        # 点击：爬到最近的可点击祖先（行）再点击，事件冒泡打开会话
        try:
            clicked = page.evaluate("""(target) => {
                const t = String(target);
                let best = null, bestLen = Infinity;
                const all = document.querySelectorAll('*');
                for (const el of all) {
                    const h = el.outerHTML || '';
                    if (h.indexOf(t) !== -1) { const len = h.length; if (len < bestLen){bestLen=len;best=el;} }
                }
                if (!best) return {ok:false};
                let row = best;
                while (row && row !== document.body) {
                    const tag = row.tagName;
                    const cls = (typeof row.className === 'string') ? row.className : '';
                    const role = row.getAttribute && row.getAttribute('role');
                    if (tag === 'LI' || tag === 'A' || role === 'button' || /list-item|conversation|item|row/i.test(cls)) break;
                    row = row.parentElement;
                }
                let target_el = (row && row !== document.body) ? row : best;
                target_el.click();
                return {ok:true, tag: target_el.tagName, cls: (typeof target_el.className==='string'?target_el.className:'').slice(0,160)};
            }""", t)
            logger.info(f"[{account}] 目标 {t} 点击结果: {clicked}")
        except Exception as e:
            logger.error(f"[{account}] 目标 {t} 点击异常: {e}")
            continue

        # 等待会话窗口与输入框渲染
        time.sleep(3)

        # 定位输入框并发送
        inp = None
        for sel in ["textarea", "[contenteditable='true']", "[contenteditable=true]", "input[type='text']", "[placeholder*='发送']", "[placeholder*='消息']"]:
            try:
                el = page.query_selector(sel)
                if el:
                    inp = el
                    logger.info(f"[{account}] 目标 {t} 找到输入框选择器: {sel}")
                    break
            except Exception:
                pass

        if not inp:
            logger.warning(f"[{account}] 目标 {t} 未找到输入框，跳过发送")
            continue

        try:
            inp.click()
            inp.fill(msg)
            time.sleep(0.5)
            page.keyboard.press("Enter")
            logger.info(f"[{account}] 目标 {t} 已尝试发送（fill + Enter）")
            sent += 1
            time.sleep(8)  # 降速，避免频繁
        except Exception as e:
            logger.error(f"[{account}] 目标 {t} 发送异常: {e}")

    # ---- 写网络日志 ----
    try:
        with open("logs/network.json", "w", encoding="utf-8") as f:
            json.dump(net, f, ensure_ascii=False, indent=2)
        logger.info(f"[{account}] 已导出 network.json，记录 {len(net)} 条 douyin 响应")
    except Exception as e:
        logger.error(f"[{account}] network.json 导出失败: {e}")

    logger.info(f"[{account}] ===== 发送流程结束，成功发送 {sent}/{len(targets)} =====")

    if sent == 0 and len(targets) > 0:
        raise RuntimeError(f"[{account}] 没有任何目标发送成功，视为失败（避免假成功）")
