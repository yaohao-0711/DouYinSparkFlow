import os, sys
from enum import Enum
import json
import logging
from utils.logger import setup_logger
from skills import get_available_skills

logger = setup_logger(level=logging.DEBUG)

"""
是否启用调试模式
更详细的日志打印
"""
DEBUG = True
config = None
userData = None


class Environment(Enum):
    GITHUBACTION = "GITHUB_ACTION"  # GitHub Action 运行
    LOCAL = "LOCAL"  # 本地代码运行
    PACKED = "PACKED"  # PyInstaller 打包运行

    def __str__(self):
        return self.value


def get_environment():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Environment.PACKED
    elif os.getenv("GITHUB_ACTIONS") == "true":
        return Environment.GITHUBACTION
    else:
        return Environment.LOCAL


def get_config():
    """
    获取配置信息
    :return: 配置字典
    """
    global config

    if config:
        return config

    defaultSkillName = "random_dynamic_emoji"

    defaultSkillConfig = {
        "dynamic_emoji_type": ["续火花"],
    }
    if (
        os.getenv("SKILL")
        and os.getenv("SKILL") in get_available_skills()
        and os.getenv(f"SKILL_{os.getenv('SKILL').upper()}")
    ):
        skill_name = os.getenv("SKILL")
        skill_config_str = os.getenv(f"SKILL_{skill_name.upper()}", "{}")
        try:
            skill_config = json.loads(skill_config_str)

            skill = {"name": skill_name, "config": skill_config}
        except json.JSONDecodeError as e:
            logger.warning(
                f"技能 {skill_name} 的配置解析失败，已使用默认random_dynamic_emoji skill 以及 默认配置: {e}"
            )
            skill_config = defaultSkillConfig
            skill = {"name": defaultSkillName, "config": skill_config}
    else:
        skill = {"name": defaultSkillName, "config": defaultSkillConfig}

    config = {
        "proxyAddress": os.getenv("PROXY_ADDRESS", ""),
        "logLevel": os.getenv("LOG_LEVEL", "DEBUG"),  # 日志级别
        "skill": skill
    }

    return config


def parse_cookies_str(cookies_str):
    """
    将 cookies 字符串解析为字典
    :param cookies_str: cookies 字符串，格式为 "key1=value1; key2=value2; ..."
    :return: cookies 字典
    """
    cookies = {}
    for item in cookies_str.split(";"):
        if "=" in item:
            key, value = item.strip().split("=", 1)
            cookies[key] = value

    # 校验cookie中必须有的值：ms_token s_v_web_id UIFID
    required_keys = ["ms_token", "s_v_web_id", "UIFID"]
    for key in required_keys:
        if key not in cookies:
            print(f"Cookie 中缺少必需的字段: {key}")
            raise ValueError(f"Cookie 中缺少必需的字段: {key}")

    return cookies


def get_userData():
    """
    获取用户数据目录
    :return: 用户数据目录路径
    """
    global userData

    if userData:
        return userData

    tasks = json.loads(os.getenv("TASKS", "[]"))

    userData = []

    for task in tasks:
        username = task.get("username", "未知用户")
        user_id = task.get("user_id")
        if not user_id:
            logger.warning(f"{username} 的任务  缺少 user_id 字段，已跳过")
            continue
        cookies_key = f"cookies_{user_id}".upper()
        cookies_str = os.getenv(cookies_key, "")
        if not cookies_str:
            logger.warning(f"{username} 的任务 缺少 {cookies_key} 环境变量，已跳过")
            continue
        try:
            cookies = parse_cookies_str(cookies_str.strip())
        except Exception as e:
            logger.warning(
                f"{username} 的任务 cookies 环境变量格式错误，解析失败，已跳过: {e}"
            )
            continue
        
        session_id_key = f"SESSIONID_{user_id}".upper()
        session_id = os.getenv(session_id_key, "")
        
        if not session_id:
            logger.warning(f"{username} 的任务 缺少 {session_id_key} 环境变量，已跳过")
            continue

        userData.append(
            {
                "user_id": user_id.strip(),
                "session_id": session_id.strip(),
                "username": username.strip(),
                "cookies": cookies,
                "targets": task.get("targets", []),
            }
        )

    return userData
