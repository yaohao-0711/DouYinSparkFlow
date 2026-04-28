from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

import random
import re
import requests

from .base import BaseSkill, DouyinPmCliClient, ExecuteResponse, parse_enum_list

hot_videos = {}


from enum import Enum

class VideoType(Enum):
    COURSE = "课程"
    GAME = "游戏"
    ACG = "二次元"
    MUSIC = "音乐"
    FILM = "影视"
    FOOD = "美食"
    KNOWLEDGE = "知识"
    THEATER = "小剧场"
    VLOG = "生活vlog"
    SPORTS = "体育"
    TRAVEL = "旅行"
    CHILD = "儿童"
    ANIMAL = "动物"
    AGRICULTURE = "三农"
    CAR = "汽车"
    BEAUTY = "美妆穿搭"

    def get_param_code(self) -> str:
        """
        根据中文枚举值，获取接口真实请求参数
        """
        type_code_map = {
            "课程": "course",
            "游戏": "game",
            "二次元": "acg",
            "音乐": "music",
            "影视": "film",
            "美食": "food",
            "知识": "knowledge",
            "小剧场": "theater",
            "生活vlog": "vlog",
            "体育": "sports",
            "旅行": "travel",
            "儿童": "child",
            "动物": "animal",
            "三农": "agriculture",
            "汽车": "car",
            "美妆穿搭": "beauty",
        }
        return type_code_map.get(self.value)


@dataclass(slots=True)
class RandomHotVideoSkillConfig:
    video_type: list[VideoType] = field(default_factory=list)


def get_video(video_type: VideoType):
    url = f"https://www.douyin.com/jingxuan/{ video_type.get_param_code() }"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0",
        "Referer": "https://www.douyin.com/",
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="144", "Microsoft Edge";v="144"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }

    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.text
        patten = r"""<div\b(?=[^>]*\bclass\s*=\s*["'][^"']*\bdiscover-video-card-item\b[^"']*["'])(?=[^>]*\bid\s*=\s*["'](\d+)["'])[^>]*>"""
        matches = re.findall(patten, data)
    else:
        print("【hot_video】请求视频失败", response.status_code, response.text)
        matches = []

    hot_videos[video_type.value] = matches
    return matches


class RandomHotVideoSkill(BaseSkill[RandomHotVideoSkillConfig]):
    def __init__(self, client: DouyinPmCliClient):
        super().__init__("random_hot_video", client)

    @classmethod
    def build_config(cls, raw: Mapping[str, Any] | None = None) -> RandomHotVideoSkillConfig:
        raw = raw or {}
        video_type = parse_enum_list(raw.get("video_type"), VideoType, "video_type")
        if not video_type:
            video_type = list(VideoType)
        return RandomHotVideoSkillConfig(video_type=video_type)

    def execute(
        self,
        conversation_id: str,
        conversation_short_id: int | str,
        is_group: bool = False,
        config: RandomHotVideoSkillConfig | None = None,
    ) -> ExecuteResponse:
        config = config or self.build_config()
        
        videoType = config.video_type if config.video_type else list(VideoType)

        # 随机选择一个视频类型
        res = random.choice(videoType)
        video_list = hot_videos.get(res.value, []) or get_video(res)  # 获取视频列表，如果已经获取过则使用缓存
        video_id = random.choice(video_list) if video_list else None

        if video_id:
            result = self.client.send_video_card(
                conversation_id=conversation_id,
                conversation_short_id=conversation_short_id,
                item_id=video_id,
                is_group=is_group,
            )

            """jar返回失败是
            {
                "success": false,
                "type": "<传入的 --type，可选>",
                "error": "<异常类名>",
                "message": "<最底层异常信息>"
            }
            成功是
            {
                "success": true,
                "type": "<你传入的 --type，可选>",
                "data": {
                    "item_id": "<视频ID>",
                    "video_url": "<视频链接>",
                    "cover_url": "<封面链接>",
                    "title": "<视频标题>"
                }
            }
            """
            data = result.data
            
            if result.success:
                data["video_type"] = res.value  # 添加视频类型到返回数据中
                data["video_id"] = video_id  # 添加视频ID到返回数据中
                return {
                    "success": True,
                    "message": "视频发送成功",
                    "data": data,
                }
            else:
                return {
                    "success": False,
                    "message": f"视频发送失败: {data.get('message', '未知错误')}",
                    "data": data.get("error", {}),
                }

        else:
            return {"success": False, "message": "没有可用的视频ID", "data": {}}
