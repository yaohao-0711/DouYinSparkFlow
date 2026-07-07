# 尝试从 .env 文件加载环境变量
import os
if os.path.exists(".env"):
    from dotenv import load_dotenv

    load_dotenv(".env")

from capture_api import main as capture_main

capture_main()
