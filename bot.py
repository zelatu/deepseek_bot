"""NoneBot2 入口。双击 start.bat 或运行 `python bot.py` 启动。"""

from pathlib import Path

import nonebot
from nonebot.adapters.onebot.v11 import Adapter

nonebot.init()
nonebot.get_driver().register_adapter(Adapter)
nonebot.load_plugins(str(Path(__file__).parent / "plugins"))

if __name__ == "__main__":
    nonebot.run()
