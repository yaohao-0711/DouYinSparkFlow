import os
import re
import json
import time

from utils.config import get_config, get_userData
from utils.logger import setup_logger
from core.browser import get_browser

config = get_config()
userData = get_userData()
logger = setup_logger(level="Debug")

ALL_URLS = []          # 全部请求 URL（不过滤）
DETAIL = []            # 与私信相关的详细请求/响应
SEND_RESULT = None


def on_request(request):
    url = request.url
    ALL_URLS.append(f"{request.method} {url}")
    if "imapi.snssdk.com" in url or "aweme/v1" in url or "snssdk.com/aweme" in url or "im.douyin.com" in url:
        h = dict(request.headers)
        keep = {
            k: h[k]
            for k in h
            if k.lower()
            in (
                "x-gorgon",
                "x-khronos",
                "x-argus",
                "x-tyhon",
                "cookie",
                "content-type",
                "user-agent",
                "authorization",
            )
        }
        DETAIL.append(
            {
                "type": "request",
                "method": request.method,
                "url": url,
                "headers": keep,
                "post_data": (request.post_data[:1000] if request.post_data else None),
            }
        )
        logger.info(f"[REQ] {request.method} {url}")


def on_response(response):
    url = response.url
    if "imapi.snssdk.com" in url or "im.douyin.com" in url:
        body = ""
        try:
            body = response.text()[:4000]
        except Exception as e:
            body = f"<err {e}>"
        DETAIL.append(
            {"type": "response", "status": response.status, "url": url, "body_preview": body}
        )
        logger.info(f"[RES] {status={response.status}] {url}")


def main():
    global SEND_RESULT
    playwright, browser = get_browser()
    try:
        user = userData[0]
        cookies = user["cookies"]
        context = browser.new_context()
        context.set_default_timeout(60000)
        page = context.new_page()
        page.on("request", on_request)
        page.on("response", on_response)

        page.goto("https://creator.douyin.com/", wait_until="domcontentloaded")
        context.add_cookies(cookies)
        time.sleep(2)

        # 尝试多个候选私信地址
        candidates = [
            "https://creator.douyin.com/creator-micro/data/following/chat",
            "https://creator.douyin.com/creator-micro/im/",
            "https://im.douyin.com/",
            "https://creator.douyin.com/creator-micro/data/message",
        ]
        for url in candidates:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                logger.info(f"已导航到 {url} ，当前 page.url={page.url}")
                time.sleep(8)
            except Exception as e:
                logger.warning(f"导航 {url} 失败: {e}")

        # 记录 iframe
        frames = [f.url for f in page.frames]
        logger.info(f"frames: {frames}")

        # 从已捕获的响应里提取 conversation_id / peer_user_id
        conv_id = peer_id = None
        for c in DETAIL:
            if c.get("type") == "response" and "body_preview" in c:
                bp = c["body_preview"]
                m = re.search(r'"conversation_id"\s*:\s*"([^"]+)"', bp)
                if m and not conv_id:
                    conv_id = m.group(1)
                m = re.search(r'"(?:peer_user_id|to_user_id)"\s*:\s*(\d+)', bp)
                if m and not peer_id:
                    peer_id = m.group(1)
        logger.info(f"提取到 conv_id={conv_id} peer_id={peer_id}")

        # 重放 send
        get_req = next(
            (
                c
                for c in DETAIL
                if c["type"] == "request"
                and c["method"] == "GET"
                and "x-gorgon" in c.get("headers", {})
            ),
            None,
        )
        if get_req and conv_id:
            headers = dict(get_req["headers"])
            send_url = "https://imapi.snssdk.com/message/send/"
            body = json.dumps(
                {"conversation_id": conv_id, "content": "测试", "msg_type": 1}
            ).encode("utf-8")
            try:
                resp = page.request.post(
                    send_url, headers=headers, data=body, timeout=30000
                )
                SEND_RESULT = {"status": resp.status, "text": resp.text()[:2000]}
                logger.info(f"[SEND] status={resp.status} text={SEND_RESULT['text']}")
            except Exception as e:
                SEND_RESULT = {"error": str(e)}
                logger.error(f"[SEND] error {e}")
        else:
            logger.warning("未捕获到可用的 GET 请求头或 conversation_id，跳过重放发送")

        os.makedirs("logs", exist_ok=True)
        with open("logs/api_capture.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "all_urls": ALL_URLS,
                    "detail": DETAIL,
                    "send_result": SEND_RESULT,
                    "conv_id": conv_id,
                    "peer_id": peer_id,
                    "final_page_url": page.url,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        logger.info(f"capture saved, 全部请求 {len(ALL_URLS)} 条, 私信相关 {len(DETAIL)} 条")
    finally:
        browser.close()
        playwright.stop()


if __name__ == "__main__":
    main()
