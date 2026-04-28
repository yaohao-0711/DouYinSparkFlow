from dataclasses import dataclass, field
from typing import Any, Mapping

import random

from .base import BaseSkill, DouyinPmCliClient, ExecuteResponse, parse_enum_list
from .random_dynamic_emoji import (
    DynamicEmojiType,
    RandomDynamicEmojiSkill,
    RandomDynamicEmojiSkillConfig,
)
from .random_hot_video import VideoType, RandomHotVideoSkill, RandomHotVideoSkillConfig


@dataclass(slots=True)
class HumanLikeSimSkillConfig:
    video_type: list[VideoType] = field(default_factory=list)
    dynamic_emoji_type: list[DynamicEmojiType] = field(default_factory=list)
    video_probability: float = 0.3


class HumanLikeSimSkill(BaseSkill[HumanLikeSimSkillConfig]):
    def __init__(self, client: DouyinPmCliClient):
        super().__init__("human_like_sim", client)

    @classmethod
    def build_config(
        cls, raw: Mapping[str, Any] | None = None
    ) -> HumanLikeSimSkillConfig:
        raw = raw or {}
        video_type = parse_enum_list(raw.get("video_type"), VideoType, "video_type")
        dynamic_emoji_type = parse_enum_list(
            raw.get("dynamic_emoji_type"), DynamicEmojiType, "dynamic_emoji_type"
        )

        if not video_type:
            video_type = list(VideoType)
        if not dynamic_emoji_type:
            dynamic_emoji_type = list(DynamicEmojiType)

        video_probability_raw = raw.get("video_probability", 0.3)
        try:
            video_probability = float(video_probability_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("video_probability 必须是数字") from exc

        if not 0 <= video_probability <= 1:
            raise ValueError("video_probability 必须在 [0, 1] 范围内")

        return HumanLikeSimSkillConfig(
            video_type=video_type,
            dynamic_emoji_type=dynamic_emoji_type,
            video_probability=video_probability,
        )

    def execute(
        self,
        conversation_id: str,
        conversation_short_id: int | str,
        is_group: bool = False,
        config: HumanLikeSimSkillConfig | None = None,
    ) -> ExecuteResponse:
        config = config or self.build_config()

        # 根据视频发送概率决定执行哪个技能
        if random.random() < config.video_probability:
            # 执行发送视频的技能
            hot_video_skill = RandomHotVideoSkill(self.client)
            return hot_video_skill.execute(
                conversation_id=conversation_id,
                conversation_short_id=conversation_short_id,
                is_group=is_group,
                config=RandomHotVideoSkillConfig(video_type=config.video_type),
            )
        else:
            # 执行发送动态表情的技能
            dynamic_emoji_skill = RandomDynamicEmojiSkill(self.client)
            return dynamic_emoji_skill.execute(
                conversation_id=conversation_id,
                conversation_short_id=conversation_short_id,
                is_group=is_group,
                config=RandomDynamicEmojiSkillConfig(
                    dynamic_emoji_type=config.dynamic_emoji_type
                ),
            )
