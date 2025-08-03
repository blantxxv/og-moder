import logging
from datetime import datetime
from aiogram import F, types
from aiogram.filters import Command

from ..config import bot, dp
from ..database import Database
from ..utils import is_moderator, get_user_mention, lift_restrictions, log_action

logger = logging.getLogger(__name__)

@dp.message(Command(commands=["муты", "варны", "баны", "амнистия", "amnesty"]))
async def list_commands(message: types.Message):
    """Обработчик команд списков и амнистии"""
    try:
        if not await is_moderator(message.chat.id, message.from_user.id):
            await message.reply("❌ У вас недостаточно прав.")
            return
        
        cmd = message.text.split()[0][1:].lower()
        handlers = {
            "муты": cmd_mutes,
            "варны": cmd_warns_list,
            "баны": cmd_bans_list,
            "амнистия": cmd_amnesty,
            "amnesty": cmd_amnesty
        }
        
        if cmd in handlers:
            await handlers[cmd](message)
        
        try:
            await message.delete()
        except:
            pass
    except Exception as e:
        logger.error(f"Ошибка в list_commands: {e}")

async def cmd_mutes(message: types.Message):
    """Показывает список активных мутов"""
    try:
        db = Database()
        now = datetime.now().timestamp()
        mutes = db.get_active_mutes()
        
        if not mutes:
            await message.reply("Нет активных мутов.")
            return
        
        lines = []
        for mute in mutes:
            if mute["until"] > now:
                mention = await get_user_mention(mute["chat_id"], mute["user_id"])
                until_dt = datetime.fromtimestamp(mute["until"])
                until_str = until_dt.strftime("%d.%m.%Y %H:%M")
                lines.append(f"✅ {mention} до {until_str}")
        
        await message.reply("\n".join(lines))
    except Exception as e:
        logger.error(f"Ошибка в cmd_mutes: {e}")
        await message.reply("❌ Произошла ошибка при выполнении команды.")

async def cmd_warns_list(message: types.Message):
    """Показывает список пользователей с предупреждениями"""
    try:
        db = Database()
        uids = db.get_all_users_with_warns()
        if not uids:
            await message.reply("Нет пользователей с предупреждениями.")
            return
        
        lines = []
        for uid in uids:
            count = db.get_warns(uid)
            if count > 0:
                mention = await get_user_mention(message.chat.id, uid)
                lines.append(f"⚠️ {mention}: {count}")
        
        await message.reply("\n".join(lines))
    except Exception as e:
        logger.error(f"Ошибка в cmd_warns_list: {e}")
        await message.reply("❌ Произошла ошибка при выполнении команды.")

async def cmd_bans_list(message: types.Message):
    """Показывает список забаненных пользователей"""
    try:
        db = Database()
        bans = db.get_bans(message.chat.id)
        if not bans:
            await message.reply("Нет забаненных пользователей.")
            return
        
        lines = []
        for uid in bans:
            mention = await get_user_mention(message.chat.id, uid)
            lines.append(f"🚫 {mention}")
        
        await message.reply("\n".join(lines))
    except Exception as e:
        logger.error(f"Ошибка в cmd_bans_list: {e}")
        await message.reply("❌ Произошла ошибка при выполнении команды.")

async def cmd_amnesty(message: types.Message):
    """Проводит амнистию - снимает все ограничения"""
    try:
        db = Database()
        
        for mute in db.get_active_mutes():
            await lift_restrictions(mute["chat_id"], mute["user_id"])
        
        bans = db.get_bans(message.chat.id)
        for uid in bans:
            try:
                await bot.unban_chat_member(message.chat.id, uid)
                db.remove_ban(message.chat.id, uid)
            except:
                pass
        
        db.clear_all_warns()
        
        await message.reply("✅ Амнистия проведена! Все ограничения сняты, предупреждения обнулены.")
        log_action("Amnesty", message.from_user.id)
    except Exception as e:
        logger.error(f"Ошибка в cmd_amnesty: {e}")
        await message.reply("❌ Произошла ошибка при выполнении команды.")