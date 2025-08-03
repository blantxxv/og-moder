import html
import logging
from aiogram import F, types

from ..config import bot, dp, LOG_CHANNEL

logger = logging.getLogger(__name__)

@dp.message(F.left_chat_member)
async def on_user_left(message: types.Message):
    try:
        user = message.left_chat_member
        mention = f'<a href="tg://user?id={user.id}">{html.escape(user.full_name)}</a>'
        await message.answer(f"👋 Всего хорошего, {mention}!")
    except:
        pass

@dp.message(F.chat.type.in_({"group", "supergroup"}) & ~F.service & ~F.text.startswith('/'))
async def forward_to_channel(message: types.Message):
    """Пересылает все сообщения чата в указанный канал"""
    try:
        if LOG_CHANNEL:
            await bot.forward_message(
                chat_id=LOG_CHANNEL,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
    except Exception as e:
        logger.error(f"Ошибка при пересылке сообщения: {e}")
