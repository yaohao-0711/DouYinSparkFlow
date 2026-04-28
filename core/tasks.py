import traceback
from utils.logger import setup_logger
from utils.config import get_config, get_userData
import time
import json
from .web_api import DouyinPmCliClient
from skills import execute_skill

config = get_config()
userData = get_userData()
logger = setup_logger(level=config.get("logLevel", "Info"))
matchMode = config.get("matchMode", "nickname")
userIDDict = {}

def do_user_task(client, username, targets, skill_name, skill_config):
    for target in targets:
        remark = target.get("remark", "未知好友")
        logger.info(f"正在处理账号 {username} 的目标好友 {remark}")
        try:
            result = execute_skill(
                skill_name=skill_name,
                client=client,
                conversation_id=target.get("conversation_id"),
                conversation_short_id=target.get("conversation_short_id"),
                is_group=target.get("is_group", False),
                config_raw=skill_config,
            )
            logger.info(f"账号 {username} 的目标好友 {remark} 处理结果: {json.dumps(result, ensure_ascii=False)}")
            time.sleep(5)  # 等待5秒再处理下一个好友，避免请求过快
        except Exception as e:
            logger.error(f"账号 {username} 的目标好友 {remark} 处理失败: {e}\n{traceback.format_exc()}")

def runTasks():
    try:
        # 检查是否启用多任务和任务数量
        # 创建信号量以限制并发任务数量
        logger.info("开始执行任务")
        logger.debug(f"当前配置如下：")
        skill_name = config['skill']["name"]
        skill_config = config['skill']["config"]
        logger.debug(f"启用的Skill: {skill_name}")
        logger.debug(f"【{skill_name}】Skill配置: \n\t{json.dumps(skill_config, ensure_ascii=False, indent=4)}")
        for user in userData:
            logger.debug(f"用户: {user.get('username', '未知用户')}, 目标好友: {[t['remark'] for t in user['targets']]}")

        client = None
        
        for user in userData:
            cookies = user["cookies"]
            targets = user["targets"]
            user_id = user["user_id"]
            session_id = user["session_id"]
            username = user.get("username", "未知用户")
            
            ms_token=cookies.get("ms_token", "")
            verify_fp=cookies.get("s_v_web_id", "")
            fp=cookies.get("s_v_web_id", "")
            uifid=cookies.get("UIFID", "")
            
            if not client:
                # 创建 DouyinPmCliClient 实例
                client = DouyinPmCliClient(
                    session_id=session_id,
                    user_id=user_id,
                    ms_token=ms_token,
                    verify_fp=verify_fp,
                    fp=fp,
                    uifid=uifid,
                )
            else:
                # 更新 client 的 属性以切换账号
                client.session_id = session_id
                client.user_id = user_id
                client.ms_token = ms_token
                client.verify_fp = verify_fp
                client.fp = fp
                client.uifid = uifid
            
            logger.info(f"开始处理账号 {username}")
            # 创建任务
            do_user_task(client, username, targets, skill_name, skill_config)
            logger.info(f"账号 {username} 任务完成")
    except Exception as e:
        logger.error(f"执行任务时发生错误: {e}\n{traceback.format_exc()}")
