# 旧版本迁移，暂时未接入验证

from dataclasses import dataclass, field
from typing import Any, Mapping

from openai import OpenAI

from .base import BaseSkill, DouyinPmCliClient, ExecuteResponse


def _default_prompt() -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是一个擅长写续火花消息的助手。用户需要你生成一段不超过20字的续火花消息，"
                "内容要温馨、有趣、适合发给聊天对象。请直接输出消息内容，不要加引号或其他修饰。"
            ),
        },
        {"role": "user", "content": "生成一段续火花消息，直接输出内容不要思考过程"},
    ]


@dataclass(slots=True)
class OpenAIMessageSkillConfig:
    api_key: str = ""
    model: str = "MiniMax-M2.7"
    prompt: list[dict[str, str]] = field(default_factory=_default_prompt)


class OpenAIMessageSkill(BaseSkill[OpenAIMessageSkillConfig]):
    def __init__(self, client: DouyinPmCliClient):
        super().__init__("openai_message", client)

    @classmethod
    def build_config(
        cls, raw: Mapping[str, Any] | None = None
    ) -> OpenAIMessageSkillConfig:
        raw = raw or {}

        api_key = raw.get("api_key", "")
        if not isinstance(api_key, str):
            raise ValueError("api_key 必须是字符串")

        model = raw.get("model", "MiniMax-M2.7")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model 必须是非空字符串")

        prompt_raw = raw.get("prompt")
        if prompt_raw is None:
            prompt = _default_prompt()
        elif isinstance(prompt_raw, list):
            prompt = []
            for item in prompt_raw:
                if not isinstance(item, dict):
                    raise ValueError("prompt 列表中的每一项都必须是对象")
                role = item.get("role")
                content = item.get("content")
                if not isinstance(role, str) or not isinstance(content, str):
                    raise ValueError("prompt 项必须包含字符串类型的 role 和 content")
                prompt.append({"role": role, "content": content})
        else:
            raise ValueError("prompt 必须是对象列表")

        return OpenAIMessageSkillConfig(api_key=api_key, model=model, prompt=prompt)

    def execute(
        self,
        conversation_id: str,
        conversation_short_id: int | str,
        is_group: bool = False,
        config: OpenAIMessageSkillConfig | None = None,
    ) -> ExecuteResponse:
        config = config or self.build_config()

        if not config.api_key:
            return {
                "success": False,
                "message": "openai智能消息发送失败: 缺少 api_key",
                "data": {},
            }

        client = OpenAI(api_key=config.api_key)
        response = client.chat.completions.create(
            model=config.model,
            messages=config.prompt,
            extra_body={"reasoning_split": True},
        )

        content = (response.choices[0].message.content or "").strip()

        result = self.client.send_text(
            conversation_id=conversation_id,
            conversation_short_id=conversation_short_id,
            content=content,
            is_group=is_group,
        )

        data = result.data

        if result.success:
            data["message"] = content  # 添加发送的消息内容到返回数据中
            return {
                "success": True,
                "message": "openai智能消息发送成功",
                "data": data,
            }

        return {
            "success": False,
            "message": f"openai智能消息发送失败: {data.get('message', '未知错误')}",
            "data": data.get("error", {}),
        }


# 兼容旧引用
HitokotoSkill = OpenAIMessageSkill
