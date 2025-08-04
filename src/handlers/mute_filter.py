import logging
from datetime import datetime
from aiogram import F, types

from ..config import dp
from ..database import Database
from ..utils import is_moderator

logger = logging.getLogger(__name__)

@dp.message(F.chat.type.in_({"group", "supergroup"}) & ~F.service & ~F.text.startswith('/'))
async def check_muted_users(message: types.Message):
    try:
        if await is_moderator(message.chat.id, message.from_user.id):
            return
            
        db = Database()
        mute = db.get_mute(message.from_user.id)
        
        if mute:
            now = datetime.now().timestamp()
            if mute["until"] > now:
                try:
                    await message.delete()
                    logger.info(f"Удалено сообщение от замученного пользователя {message.from_user.id}")
                except Exception as e:
                    logger.error(f"Ошибка при удалении сообщения: {e}")
                return
            else:
                db.remove_mute(message.from_user.id)
                
    except Exception as e:
        logger.error(f"Ошибка в check_muted_users: {e}")