from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

import random

from .base import BaseSkill, DouyinPmCliClient, ExecuteResponse, parse_enum_list


class DynamicEmojiType(Enum):
    FIRE_SPARK = "续火花"
    HEART = "比心"
    WHAT_ARE_YOU_DOING = "在干嘛"
    LOL = "笑死"
    NUMB = "麻了"
    LAY_FLAT = "躺平"
    ROLL_THE_DICE = "摇骰子"
    ROCK_PAPER_SCISSORS = "猜拳"
    HAPPY = "开心"
    HI = "嗨"
    BUBBLE = "吹泡泡"
    BLACK_QUESTION = "黑人问号"
    GOOD_MORNING = "早上好"
    GOOD_EVENING = "晚上好"
    SLEEP_EARLY = "早点睡"
    LOVE_HEART = "爱心"
    POOP = "便便"
    TAP_TAP = "戳一戳"
    PERFECT = "绝了"
    READ = "已阅"
    BIRTHDAY_WISH = "生日祝福"

@dataclass(slots=True)
class RandomDynamicEmojiSkillConfig:
    dynamic_emoji_type: list[DynamicEmojiType] = field(
        default_factory=list
    )


class RandomDynamicEmojiSkill(BaseSkill[RandomDynamicEmojiSkillConfig]):
    def __init__(self, client: DouyinPmCliClient):
        super().__init__("random_dynamic_emoji", client)

    @classmethod
    def build_config(
        cls, raw: Mapping[str, Any] | None = None
    ) -> RandomDynamicEmojiSkillConfig:
        raw = raw or {}
        dynamic_emoji_type = parse_enum_list(
            raw.get("dynamic_emoji_type"), DynamicEmojiType, "dynamic_emoji_type"
        )
        if not dynamic_emoji_type:
            dynamic_emoji_type = list(DynamicEmojiType)
        return RandomDynamicEmojiSkillConfig(dynamic_emoji_type=dynamic_emoji_type)

    def execute(
        self,
        conversation_id: str,
        conversation_short_id: int | str,
        is_group: bool = False,
        config: RandomDynamicEmojiSkillConfig | None = None,
    ) -> ExecuteResponse:
        config = config or self.build_config()
        
        dynamic_emoji_type = config.dynamic_emoji_type if config.dynamic_emoji_type else list(DynamicEmojiType)

        # 随机选择一个动态表情类型
        res = random.choice(dynamic_emoji_type)
        
        emoji_name = res.value  # 获取枚举的值作为表情名称
        result = self.client.send_dynamic_emoji(
            conversation_id=conversation_id,
            conversation_short_id=conversation_short_id,
            emoji_name=emoji_name,  # 传入枚举的值
            is_group=is_group,
        )

        data = result.data

        if result.success:
            data["emoji_name"] = emoji_name  # 添加动态表情类型到返回数据中
            return {
                "success": True,
                "message": "动态表情发送成功",
                "data": data,
            }
        else:
            return {
                "success": False,
                "message": f"动态表情发送失败: {data.get('message', '未知错误')}",
                "data": data.get("error", {}),
            }
