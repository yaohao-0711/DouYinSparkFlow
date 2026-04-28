from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

import random
import requests

from .base import BaseSkill, DouyinPmCliClient, ExecuteResponse, parse_enum_list


DEFAULT_HITOKOTO_TEMPLATE = "[盖瑞]今日火花[加一]\n—— [右边] 每日一言 [左边] ——\n[API]"


class HitokotoType(Enum):
    """
    一言分类枚举
    """

    No_LIMIT = "不限"  # 不限
    ANIMATION = "动画"  # 动画
    MANGA = "漫画"  # 漫画
    GAME = "游戏"  # 游戏
    LITERATURE = "文学"  # 文学
    ORIGINAL = "原创"  # 原创
    NETWORK = "来自网络"  # 来自网络
    OTHER = "其他"  # 其他
    MOVIE = "影视"  # 影视
    POETRY = "诗词"  # 诗词
    PHILOSOPHY = "哲学"  # 哲学
    JOKE = "抖机灵"  # 抖机灵

    def get_param_code(self) -> str:
        """
        获取一言接口请求参数 c 对应的值
        例如：动画 → a，漫画 → b
        """
        type_code_map = {
            "动画": "a",
            "漫画": "b",
            "游戏": "c",
            "文学": "d",
            "原创": "e",
            "来自网络": "f",
            "其他": "g",
            "影视": "h",
            "诗词": "i",
            "哲学": "k",
            "抖机灵": "l",
            "不限": "",
        }
        return type_code_map[self.value]


@dataclass(slots=True)
class HitokotoSkillConfig:
    hitokoto_type: list[HitokotoType] = field(default_factory=list)
    message_template: str = DEFAULT_HITOKOTO_TEMPLATE


def request_hitokoto(hitokoto_type: HitokotoType) -> str:
    """请求一言 API 获取一句话"""
    # 从一言 API 获取随机的一言
    if hitokoto_type == HitokotoType.No_LIMIT:
        api_url = "https://v1.hitokoto.cn/"
    else:
        api_url = f"https://v1.hitokoto.cn/?c={hitokoto_type.get_param_code()}"

    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        data = response.json()
        theFrom = data.get("from")
        if theFrom is None or theFrom.strip() == "":
            theFrom = "未知来源"
        theFromWho = data.get("from_who")
        if theFromWho is None or theFromWho.strip() == "":
            theFromWho = "未知作者"
        return f"{data['hitokoto']} —— {theFrom} ({theFromWho})"
    except Exception as e:
        return "[error] 无法获取一言内容"


class HitokotoSkill(BaseSkill[HitokotoSkillConfig]):
    def __init__(self, client: DouyinPmCliClient):
        super().__init__("hitokoto", client)

    @classmethod
    def build_config(cls, raw: Mapping[str, Any] | None = None) -> HitokotoSkillConfig:
        raw = raw or {}
        hitokoto_type = parse_enum_list(
            raw.get("hitokoto_type"), HitokotoType, "hitokoto_type"
        )
        message_template = raw.get("message_template", DEFAULT_HITOKOTO_TEMPLATE)
        if not isinstance(message_template, str) or not message_template.strip():
            raise ValueError("message_template 必须是非空字符串")

        return HitokotoSkillConfig(
            hitokoto_type=hitokoto_type,
            message_template=message_template,
        )

    def execute(
        self,
        conversation_id: str,
        conversation_short_id: int | str,
        is_group: bool = False,
        config: HitokotoSkillConfig | None = None,
    ) -> ExecuteResponse:
        config = config or self.build_config()

        res = (
            random.choice(config.hitokoto_type)
            if config.hitokoto_type
            else HitokotoType.No_LIMIT
        )

        if "[API]" in config.message_template:
            api_content = request_hitokoto(res)
            message = config.message_template.replace("[API]", api_content)
        else:
            message = config.message_template

        result = self.client.send_text(
            conversation_id=conversation_id,
            conversation_short_id=conversation_short_id,
            content=message,
            is_group=is_group,
        )

        data = result.data

        if result.success:
            data["message"] = message  # 添加发送的消息内容到返回数据中
            return {
                "success": True,
                "message": "一言发送成功",
                "data": data,
            }
        else:
            return {
                "success": False,
                "message": f"一言发送失败: {data.get('message', '未知错误')}",
                "data": data.get("error", {}),
            }
