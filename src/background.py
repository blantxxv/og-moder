import asyncio
import os
import logging
from datetime import datetime

from .config import bot
from .database import Database
from .utils import lift_restrictions, get_user_mention, log_action

logger = logging.getLogger(__name__)

async def clear_console_periodically():
    while True:
        await asyncio.sleep(3600)
        os.system('cls' if os.name == 'nt' else 'clear')

async def background_unmute():
    while True:
        try:
            db = Database()
            now = datetime.now().timestamp()
            for mute in db.get_active_mutes():
                if now >= mute["until"]:
                    if await lift_restrictions(mute["chat_id"], mute["user_id"]):
                        mention = await get_user_mention(mute["chat_id"], mute["user_id"])
                        try:
                            await bot.send_message(
                                mute["chat_id"],
                                f"{mention}, ограничения сняты, вы можете вновь общаться"
                            )
                        except:
                            pass
                        log_action("Auto-unmute", 0, mute["user_id"])
        except Exception as e:
            logger.error(f"Ошибка в background_unmute: {e}")
        
        await asyncio.sleep(10)
