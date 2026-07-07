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

CAPTURE = []
SEND_RESULT = None


def on_request(request):
    url = request.url
    if "imapi.snssdk.com" in url or "aweme/v1" in url or "snssdk.com/aweme" in url:
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
        CAPTURE.append(
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
    if "imapi.snssdk.com" in url:
        body = ""
        try:
            body = response.text()[:3000]
        except Exception as e:
            body = f"<err {e}>"
        CAPTURE.append(
            {"type": "response", "status": response.status, "url": url, "body_preview": body}
        )
        logger.info(f"[RES] {response.status} {url}")


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
        page.goto(
            "https://creator.douyin.com/creator-micro/data/following/chat",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        # 等待页面拉取私信列表（产生 imapi 请求）
        time.sleep(12)

        # 从已捕获的 GET 响应里尝试提取 conversation_id / peer_user_id
        conv_id = peer_id = None
        for c in CAPTURE:
            if c.get("type") == "response" and "body_preview" in c:
                bp = c["body_preview"]
                m = re.search(r'"conversation_id"\s*:\s*"([^"]+)"', bp)
                if m and not conv_id:
                    conv_id = m.group(1)
                m = re.search(r'"(?:peer_user_id|to_user_id)"\s*:\s*(\d+)', bp)
                if m and not peer_id:
                    peer_id = m.group(1)

        logger.info(f"提取到 conv_id={conv_id} peer_id={peer_id}")

        # 尝试用刚捕获的 GET 请求头（含 X-Gorgon）重放一个 send 请求
        get_req = next(
            (
                c
                for c in CAPTURE
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
                    "capture": CAPTURE,
                    "send_result": SEND_RESULT,
                    "conv_id": conv_id,
                    "peer_id": peer_id,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        logger.info(f"capture saved, 共 {len(CAPTURE)} 条请求记录")
    finally:
        browser.close()
        playwright.stop()


if __name__ == "__main__":
    main()
