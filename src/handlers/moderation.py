import logging
from datetime import datetime, timedelta
from aiogram import F, types
from aiogram.filters import Command
from aiogram.enums.chat_member_status import ChatMemberStatus

from ..config import bot, dp
from ..database import Database
from ..utils import (
    is_moderator, get_user_id, get_user_mention, restrict_user, 
    lift_restrictions, log_action, pluralize, parse_duration, get_duration_display
)

logger = logging.getLogger(__name__)

_processed_messages = set()

@dp.message(Command(commands=["ban", "mute", "warn", "unban", "unmute", "warns", "clearwarns"]))
async def moderation_commands(message: types.Message):
    try:
        msg_key = f"{message.chat.id}:{message.message_id}:{message.from_user.id}"
        if msg_key in _processed_messages:
            return
        _processed_messages.add(msg_key)
        
        if len(_processed_messages) > 100:
            _processed_messages.clear()
        
        if not await is_moderator(message.chat.id, message.from_user.id):
            await message.reply("❌ У вас недостаточно прав.")
            return
        
        cmd = message.text.split()[0][1:].lower()
        
        handlers = {
            "ban": cmd_ban,
            "mute": cmd_mute,
            "warn": cmd_warn,
            "unban": cmd_unban,
            "unmute": cmd_unmute,
            "warns": cmd_warns,
            "clearwarns": cmd_clearwarns
        }
        
        if cmd in handlers:
            await handlers[cmd](message)
        
        try:
            await message.delete()
        except:
            pass
    except Exception as e:
        logger.error(f"Ошибка в moderation_commands: {e}")

async def cmd_ban(message: types.Message):
    try:
        parts = message.text.split(maxsplit=2)
        db = Database()
        
        if message.reply_to_message:
            tgt = message.reply_to_message.from_user
            reason = parts[1] if len(parts) > 1 else None
        else:
            if len(parts) < 2:
                await message.reply("❌ Укажите пользователя.")
                return
            tgt = parts[1]
            reason = parts[2] if len(parts) > 2 else None
        
        uid = await get_user_id(message, tgt)
        if not uid:
            await message.reply("❌ Пользователь не найден.")
            return
        
        try:
            m = await bot.get_chat_member(message.chat.id, uid)
            if m.status == ChatMemberStatus.KICKED:
                await message.reply(f"ℹ️ {await get_user_mention(message.chat.id, uid)} уже забанен.")
                return
        except:
            pass
        
        try:
            await bot.ban_chat_member(message.chat.id, uid, until_date=0, revoke_messages=True)
            ban_status = "исключен из чата и добавлен в черный список"
        except Exception as kick_error:
            logger.error(f"Ошибка при кике пользователя: {kick_error}")
            ban_status = "добавлен в черный список"
        
        db.add_ban(message.chat.id, uid)
        
        if message.reply_to_message:
            try:
                await bot.delete_message(message.chat.id, message.reply_to_message.message_id)
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение при бане: {e}")
        
        await message.reply(
            f"🚫 {await get_user_mention(message.chat.id, uid)} {ban_status}.\n\n"
            f"Причина: {reason or 'не указана'}"
        )
        log_action("Ban", message.from_user.id, uid, reason)
    except Exception as e:
        logger.error(f"Ошибка в cmd_ban: {e}", exc_info=True)
        await message.reply(f"❌ Произошла ошибка при выполнении команды: {str(e)}")

async def cmd_mute(message: types.Message):
    """Команда мута пользователя"""
    try:
        parts = message.text.split(maxsplit=3)
        db = Database()
        
        if message.reply_to_message:
            tgt = message.reply_to_message.from_user
            dur_str = parts[1] if len(parts) > 1 else None
            reason = parts[2] if len(parts) > 2 else None
        else:
            if len(parts) < 2:
                await message.reply("❌ Укажите пользователя.")
                return
            tgt = parts[1]
            dur_str = parts[2] if len(parts) > 2 else None
            reason = parts[3] if len(parts) > 3 else None
        
        uid = await get_user_id(message, tgt)
        if not uid:
            await message.reply("❌ Пользователь не найден.")
            return
        
        mute = db.get_mute(uid)
        now = datetime.now().timestamp()
        if mute and mute["until"] > now:
            until_dt = datetime.fromtimestamp(mute["until"])
            until_str = until_dt.strftime("%d.%m.%Y %H:%M")
            await message.reply(
                f"ℹ️ {await get_user_mention(message.chat.id, uid)} уже в муте до {until_str}."
            )
            return
        
        duration = parse_duration(dur_str) or timedelta(hours=3)
        until = datetime.now() + duration
        until_ts = until.timestamp()
        
        await restrict_user(message.chat.id, uid, until_ts)
        db.add_mute(uid, message.chat.id, until_ts)
        
        if message.reply_to_message:
            try:
                await bot.delete_message(message.chat.id, message.reply_to_message.message_id)
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение при муте: {e}")
        
        try:
            member = await bot.get_chat_member(message.chat.id, uid)
            if not member.can_send_messages:
                status_emoji = "✅"
                status_text = "замучен"
            else:
                status_emoji = "⚠️" 
                status_text = "ограничен"
        except:
            status_emoji = "✅"
            status_text = "замучен"
        
        reply_text = f"{status_emoji} {await get_user_mention(message.chat.id, uid)}, {status_text} на {get_duration_display(duration)}."
        if reason:
            reply_text += f"\n\nПричина: {reason}"
            
        await message.reply(reply_text)
        log_action("Mute", message.from_user.id, uid, get_duration_display(duration))
    except Exception as e:
        logger.error(f"Ошибка в cmd_mute: {e}")
        await message.reply("❌ Произошла ошибка при выполнении команды.")

async def cmd_warn(message: types.Message):
    try:
        parts = message.text.split(maxsplit=2)
        db = Database()
        
        if message.reply_to_message:
            tgt = message.reply_to_message.from_user
            reason = parts[1] if len(parts) > 1 else None
        else:
            if len(parts) < 2:
                await message.reply("❌ Укажите пользователя.")
                return
            tgt = parts[1]
            reason = parts[2] if len(parts) > 2 else None
        
        uid = await get_user_id(message, tgt)
        if not uid:
            await message.reply("❌ Пользователь не найден.")
            return
        
        count = db.add_warn(uid)
        form = pluralize(count, "предупреждение", "предупреждения", "предупреждений")
        
        if message.reply_to_message:
            try:
                await bot.delete_message(message.chat.id, message.reply_to_message.message_id)
            except Exception as e:
                logger.warning(f"Не удалось удалить сообщение при предупреждении: {e}")
        
        text = f"⚠️ {await get_user_mention(message.chat.id, uid)} получил предупреждение.\nВсего: {count} {form}."
        if reason:
            text += f"\nПричина: {reason}"
        
        if count >= 5:
            await bot.ban_chat_member(message.chat.id, uid, until_date=0, revoke_messages=True)
            db.add_ban(message.chat.id, uid)
            text += "\n\n🚫 Авто-бан за 5 предупреждений."
            log_action("Auto-ban 5 warns", 0, uid)
        
        await message.reply(text)
        log_action("Warn", message.from_user.id, uid, f"Total: {count}")
    except Exception as e:
        logger.error(f"Ошибка в cmd_warn: {e}")
        await message.reply("❌ Произошла ошибка при выполнении команды.")

async def cmd_unban(message: types.Message):
    """Команда разбана пользователя"""
    try:
        parts = message.text.split(maxsplit=1)
        db = Database()
        
        if message.reply_to_message:
            tgt = message.reply_to_message.from_user
        else:
            if len(parts) < 2:
                await message.reply("❌ Укажите пользователя.")
                return
            tgt = parts[1]
        
        uid = await get_user_id(message, tgt)
        if not uid:
            await message.reply("❌ Пользователь не найден.")
            return
        
        ban = db.get_ban(message.chat.id, uid)
        if not ban:
            await message.reply(f"ℹ️ {await get_user_mention(message.chat.id, uid)} не забанен.")
            return
        
        db.remove_ban(message.chat.id, uid)
        
        try:
            await bot.unban_chat_member(message.chat.id, uid, only_if_banned=True)
            status_text = "✅ Бан снят, пользователь может вернуться в чат"
        except Exception as api_error:
            if "supergroup and channel chats only" in str(api_error):
                status_text = "✅ Бан снят из базы данных (в обычных группах Telegram не поддерживает разбан через API)"
            else:
                status_text = "✅ Бан снят из базы данных"
        
        await message.reply(f"{status_text}. {await get_user_mention(message.chat.id, uid)} больше не забанен.")
        log_action("Unban", message.from_user.id, uid)
    except Exception as e:
        logger.error(f"Ошибка в cmd_unban: {e}", exc_info=True)
        await message.reply(f"❌ Произошла ошибка при выполнении команды: {str(e)}")

async def cmd_unmute(message: types.Message):
    try:
        parts = message.text.split(maxsplit=1)
        
        if message.reply_to_message:
            tgt = message.reply_to_message.from_user
        else:
            if len(parts) < 2:
                await message.reply("❌ Укажите пользователя.")
                return
            tgt = parts[1]
        
        uid = await get_user_id(message, tgt)
        if not uid:
            await message.reply("❌ Пользователь не найден.")
            return
        
        db = Database()
        mute = db.get_mute(uid)
        if not mute:
            await message.reply(f"ℹ️ {await get_user_mention(message.chat.id, uid)} не находится в муте.")
            return
        
        await lift_restrictions(message.chat.id, uid)
        
        try:
            member = await bot.get_chat_member(message.chat.id, uid)
            if member.can_send_messages:
                status_text = "✅ Мут снят, пользователь может общаться"
            else:
                status_text = "✅ Мут снят из базы данных, но ограничения Telegram могут остаться"
        except:
            status_text = "✅ Мут снят из базы данных"
            
        await message.reply(f"{status_text}. {await get_user_mention(message.chat.id, uid)} больше не в муте.")
        log_action("Unmute", message.from_user.id, uid)
    except Exception as e:
        logger.error(f"Ошибка в cmd_unmute: {e}")
        await message.reply("❌ Произошла ошибка при выполнении команды.")

async def cmd_warns(message: types.Message):
    try:
        parts = message.text.split(maxsplit=1)
        db = Database()
        
        if message.reply_to_message:
            tgt = message.reply_to_message.from_user
        else:
            tgt = parts[1] if len(parts) > 1 else message.from_user
        
        uid = await get_user_id(message, tgt)
        if not uid:
            await message.reply("❌ Пользователь не найден.")
            return
        
        count = db.get_warns(uid)
        form = pluralize(count, "предупреждение", "предупреждения", "предупреждений")
        await message.reply(f"ℹ️ {await get_user_mention(message.chat.id, uid)} имеет {count} {form}.")
    except Exception as e:
        logger.error(f"Ошибка в cmd_warns: {e}")
        await message.reply("❌ Произошла ошибка при выполнении команды.")

async def cmd_clearwarns(message: types.Message):
    """Команда сброса предупреждений"""
    try:
        parts = message.text.split(maxsplit=1)
        db = Database()
        
        if message.reply_to_message:
            tgt = message.reply_to_message.from_user
        else:
            if len(parts) < 2:
                await message.reply("❌ Укажите пользователя.")
                return
            tgt = parts[1]
        
        uid = await get_user_id(message, tgt)
        if not uid:
            await message.reply("❌ Пользователь не найден.")
            return
        
        old_count = db.clear_warns(uid)
        await message.reply(
            f"✅ Предупреждения сброшены ({old_count} → 0) для "
            f"{await get_user_mention(message.chat.id, uid)}."
        )
        log_action("Clear warns", message.from_user.id, uid)
    except Exception as e:
        logger.error(f"Ошибка в cmd_clearwarns: {e}")
        await message.reply("❌ Произошла ошибка при выполнении команды.")