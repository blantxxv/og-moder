import re
import html
import logging
from datetime import timedelta
from aiogram import types
from aiogram.enums.chat_member_status import ChatMemberStatus
from aiogram.types import ChatPermissions

from .config import bot, ADMINS
from .database import Database

logger = logging.getLogger(__name__)

def log_action(action: str, performer_id: int, target_id: int = None, details: str = None):
    db = Database()
    perf = db.get_user(performer_id).get('full_name', f"ID {performer_id}") if performer_id else "System"
    tgt = db.get_user(target_id).get('full_name', f"ID {target_id}") if target_id else ""
    msg = f"Action: {action} | Performer: {perf}"
    if tgt:
        msg += f" | Target: {tgt}"
    if details:
        msg += f" | Details: {details}"
    logger.info(msg)

def pluralize(n: int, form1: str, form2: str, form5: str) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return form1
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return form2
    return form5

def get_duration_display(duration: timedelta) -> str:
    sec = int(duration.total_seconds())
    if sec < 60:
        return f"{sec} сек"
    if sec < 3600:
        m = sec // 60
        return f"{m} {pluralize(m, 'минута', 'минуты', 'минут')}"
    if sec < 86400:
        h = sec // 3600
        return f"{h} {pluralize(h, 'час', 'часа', 'часов')}"
    d = sec // 86400
    return f"{d} {pluralize(d, 'день', 'дня', 'дней')}"

def parse_duration(s: str) -> timedelta | None:
    if not s:
        return None
    m = re.match(r'(\d+)([mhd])', s)
    if not m:
        return None
    num, unit = int(m.group(1)), m.group(2)
    return {
        'm': timedelta(minutes=num),
        'h': timedelta(hours=num),
        'd': timedelta(days=num)
    }[unit]

async def restrict_user(chat_id: int, user_id: int, until_ts: float = None):
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
            logger.warning(f"Попытка ограничить администратора {user_id}")
            return
    except Exception as e:
        logger.error(f"Ошибка при получении статуса пользователя {user_id}: {e}")
    
    permissions = ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False
    )
    
    try:
        if until_ts:
            from datetime import datetime
            until_date = datetime.fromtimestamp(until_ts)
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=permissions,
                until_date=until_date
            )
            logger.info(f"Пользователь {user_id} ограничен в чате {chat_id} до {until_date}")
        else:
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=permissions
            )
            logger.info(f"Пользователь {user_id} ограничен в чате {chat_id} навсегда")
    except Exception as e:
        logger.error(f"Ошибка при ограничении пользователя {user_id}: {e}")
        try:
            bot_member = await bot.get_chat_member(chat_id, (await bot.get_me()).id)
            logger.error(f"Права бота: {bot_member.status}, can_restrict_members: {getattr(bot_member, 'can_restrict_members', 'неизвестно')}")
        except:
            pass

async def lift_restrictions(chat_id: int, user_id: int) -> bool:
    """Снимает ограничения с пользователя"""
    api_success = False
    
    db = Database()
    db.remove_mute(user_id)
    
    try:
        chat = await bot.get_chat(chat_id)
        
        if chat.type != "supergroup":
            logger.info(f"Чат {chat_id} не является супергруппой, пропускаем API-снятие ограничений")
            log_action("Unmute from DB", 0, user_id, "Chat type not supergroup")
            return True
        
        default_permissions = chat.permissions
        
        if default_permissions is None:
            default_permissions = ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False,
                can_manage_topics=False
            )
        
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=default_permissions
        )
        
        api_success = True
        log_action("Restrictions lifted", 0, user_id)
        logger.info(f"Ограничения сняты с пользователя {user_id} в чате {chat_id}")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при снятии ограничений через API с пользователя {user_id}: {e}")
        try:
            bot_member = await bot.get_chat_member(chat_id, (await bot.get_me()).id)
            logger.error(f"Права бота: {bot_member.status}, can_restrict_members: {getattr(bot_member, 'can_restrict_members', 'неизвестно')}")
        except:
            pass
        
        log_action("Unmute from DB only", 0, user_id, f"API failed: {str(e)}")
        logger.info(f"Пользователь {user_id} удален из БД мутов, но API-снятие ограничений не удалось")
        return True  

async def is_moderator(chat_id: int, user_id: int) -> bool:
    if user_id in ADMINS:
        return True
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        return m.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
    except Exception as e:
        logger.error(f"Ошибка при проверке модератора: {e}")
        return False

async def get_user_mention(chat_id: int, user_id: int) -> str:
    try:
        user = await bot.get_chat(user_id)
        name = html.escape(user.full_name)
        return f'<a href="tg://user?id={user_id}">{name}</a>'
    except:
        return f"ID {user_id}"

async def get_user_id(message: types.Message, ref) -> int | None:
    try:
        db = Database()
        
        if isinstance(ref, types.User):
            db.update_user(ref)
            return ref.id
            
        if isinstance(ref, str):
            ref = ref.lstrip('@').lower()
            
            if ref.isdigit():
                return int(ref)
                
            user_id = db.get_user_by_username(ref)
            if user_id:
                return user_id
                
            if ref.startswith('tg://user?id='):
                return int(ref.split('=')[1])
                
        return None
    except Exception as e:
        logger.error(f"Ошибка в get_user_id: {e}")
        return None