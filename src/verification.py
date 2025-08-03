import asyncio
import os
import html
import logging
from aiogram import F, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.enums.chat_member_status import ChatMemberStatus

from .config import bot, dp
from .database import Database
from .utils import restrict_user, lift_restrictions, log_action, get_user_mention

logger = logging.getLogger(__name__)

pending_check: dict[int, dict] = {}
verification_tasks: dict[int, asyncio.Task] = {}

check_kb = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="Я не бот ✅", callback_data="verify")]]
)

@dp.message(F.new_chat_members)
async def on_new_chat_members(message: types.Message):
    try:
        db = Database()
        for u in message.new_chat_members:
            if db.get_ban(message.chat.id, u.id):
                logger.info(f"Забаненный пользователь {u.id} ({u.full_name}) пытается вернуться")
                try:
                    member = await bot.get_chat_member(message.chat.id, u.id)
                    if member.status != ChatMemberStatus.KICKED:
                        await bot.ban_chat_member(message.chat.id, u.id, until_date=0, revoke_messages=True)
                        await bot.send_message(
                            message.chat.id,
                            f"🚫 {html.escape(u.full_name)} забанен и не может находиться в этом чате."
                        )
                        log_action("Re-banned user", 0, u.id, "Attempted to rejoin while banned")
                except Exception as e:
                    logger.error(f"Ошибка при повторном бане пользователя {u.id}: {e}")
                continue
            
            await start_verification(u, message.chat.id)
    except Exception as e:
        logger.error(f"Ошибка в on_new_chat_members: {e}")

async def start_verification(user: types.User, chat_id: int):
    """Начинает процесс верификации нового пользователя"""
    try:
        if user.is_bot:
            return
            
        db = Database()
        db.update_user(user)
        mention = await get_user_mention(chat_id, user.id)
        await restrict_user(chat_id, user.id)
        msg = await bot.send_message(
            chat_id,
            f"Привет, {mention}! Ты попал в чат OG Community!\n\n"
            "Нажмите кнопку ниже в течение 2 минут, чтобы подтвердить, что вы не бот.",
            reply_markup=check_kb
        )
        pending_check[user.id] = {
            "chat_id": chat_id,
            "message_id": msg.message_id,
            "username": user.full_name
        }
        verification_tasks[user.id] = asyncio.create_task(
            check_verification_timeout(user.id)
        )
        log_action("Start verification", user.id, details=f"chat={chat_id}")
    except Exception as e:
        logger.error(f"Ошибка при старте верификации: {e}")

async def check_verification_timeout(user_id: int):
    await asyncio.sleep(120)
    data = pending_check.pop(user_id, None)
    if data:
        try:
            db = Database()
            await bot.ban_chat_member(data["chat_id"], user_id, until_date=0)
            db.add_ban(data["chat_id"], user_id)
            await bot.send_message(
                data["chat_id"],
                f"{data['username']} не прошёл проверку и был исключён."
            )
        except Exception as e:
            logger.error(f"Ошибка при бане пользователя: {e}")
        log_action("User banned (failed verification)", 0, user_id)
        if user_id in verification_tasks:
            verification_tasks.pop(user_id)

@dp.callback_query(F.data == "verify")
async def on_verify(callback: types.CallbackQuery):
    try:
        uid = callback.from_user.id
        if uid not in pending_check:
            await callback.answer("Проверка не требуется.", show_alert=True)
            return
        
        if uid in verification_tasks:
            verification_tasks[uid].cancel()
            verification_tasks.pop(uid)
        
        data = pending_check.pop(uid)
        await lift_restrictions(data["chat_id"], uid)
        
        try:
            await bot.delete_message(data["chat_id"], data["message_id"])
        except:
            pass
        
        mention = await get_user_mention(data["chat_id"], uid)
        text = (
            f"Привет, {mention}! ❤️\n\n"
            f"💸Ты попал в чат <a href='https://t.me/+yX2pvGLopGg5Zjky'>OG Coin Community</a>!\n\n"
            "🔗OG GROUP PROJECT\n"
            "• <a href='https://t.me/ogmobot'>Мониторинг неулучшенных подарков</a>\n"
            "• <a href='https://t.me/oggiftsRobot'>Мониторинг Telegram маркета</a>\n"
            "• <a href='https://t.me/oggift_bot'>Бот автоматической покупки новых подарков</a>\n"
            "• <a href='https://t.me/oggarant_bot'>Рулетка NFT</a>\n"
            "• <a href='https://t.me/blum/app?startapp=memepadjetton_OG_i5J0k-ref_6v4MU9NhXS'>Монета</a>\n\n"
            "<a href='https://oggift.ru/'>Наш сайт</a> | <a href='https://t.me/+yX2pvGLopGg5Zjky'>Наша группа</a>"
        )
        
        img_path = os.path.join(os.getcwd(), "img.jpg")
        if os.path.isfile(img_path):
            await bot.send_photo(data["chat_id"], photo=FSInputFile(img_path), caption=text)
        else:
            await bot.send_message(data["chat_id"], text)
        
        await callback.answer("Проверка пройдена!", show_alert=True)
        log_action("User passed verification", uid)
    except Exception as e:
        logger.error(f"Ошибка в on_verify: {e}")
        await callback.answer("Произошла ошибка. Пожалуйста, попробуйте снова.", show_alert=True)
