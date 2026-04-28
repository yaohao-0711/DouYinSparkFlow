from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Generic, Mapping, TypeAlias, TypeGuard, TypeVar, TypedDict

from core.web_api import DouyinPmCliClient

class ExecuteResponse(TypedDict):
    success: bool
    message: str
    data: Any


ConfigT = TypeVar("ConfigT")
EnumT = TypeVar("EnumT", bound=Enum)

def parse_enum_list(
    raw_value: Any,
    enum_cls: type[EnumT],
    field_name: str,
) -> list[EnumT]:
    if raw_value is None:
        return []

    if isinstance(raw_value, str):
        items = [raw_value]
    elif isinstance(raw_value, list) and all(isinstance(item, str) for item in raw_value):
        items = raw_value
    else:
        raise ValueError(f"{field_name} 必须是字符串或字符串列表")

    value_map = {enum_item.value: enum_item for enum_item in enum_cls}
    invalid_items = [item for item in items if item not in value_map]
    if invalid_items:
        raise ValueError(
            f"{field_name} 非法值: {invalid_items}，可选值: {sorted(value_map.keys())}"
        )

    return [value_map[item] for item in items]


class BaseSkill(ABC, Generic[ConfigT]):
    def __init__(self, name, client: DouyinPmCliClient):
        self.name = name
        self.client = client

    @abstractmethod
    def execute(
        self,
        conversation_id: str,
        conversation_short_id: int | str,
        is_group: bool = False,
        config: ConfigT | None = None,
    ) -> ExecuteResponse:
        raise NotImplementedError("Subclasses must implement this method")

    @classmethod
    @abstractmethod
    def build_config(cls, raw: Mapping[str, Any] | None = None) -> ConfigT:
        raise NotImplementedError("Subclasses must implement this method")
