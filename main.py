import asyncio
import logging
import os
import re
import html
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.enums.parse_mode import ParseMode
from aiogram.enums.chat_member_status import ChatMemberStatus
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
    FSInputFile,
)

# ————————————————————— Настройка логирования —————————————————————
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_actions.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logging.getLogger('aiogram.event').setLevel(logging.INFO)

# ————————————————————— Конфигурация —————————————————————
BOT_TOKEN = "свой_токен"
ADMINS = {123, 456, 789} # админы
LOG_CHANNEL = "@test"  # Канал для пересылки сообщений

# Создаём Bot с DefaultBotProperties для parse_mode
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ————————————————————— База данных (SQLite) —————————————————————
class Database:
    def __init__(self, db_path='bot_data.db'):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                first_name TEXT,
                last_name TEXT
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS warns (
                user_id INTEGER PRIMARY KEY,
                count INTEGER DEFAULT 0
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS mutes (
                user_id INTEGER PRIMARY KEY,
                chat_id INTEGER,
                until REAL
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS bans (
                chat_id INTEGER,
                user_id INTEGER,
                PRIMARY KEY (chat_id, user_id)
            )
        ''')
        self.conn.commit()

    def update_user(self, user: types.User):
        self.cursor.execute('''
            INSERT OR REPLACE INTO users (id, username, full_name, first_name, last_name)
            VALUES (?, ?, ?, ?, ?)
        ''', (user.id, user.username, user.full_name, user.first_name, user.last_name))
        self.conn.commit()

    def get_user(self, user_id: int) -> dict:
        self.cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        row = self.cursor.fetchone()
        if row:
            return {
                'id': row[0],
                'username': row[1],
                'full_name': row[2],
                'first_name': row[3],
                'last_name': row[4]
            }
        return {}

    def get_user_by_username(self, username: str) -> int | None:
        if not username:
            return None
        self.cursor.execute('SELECT id FROM users WHERE username = ?', (username.lower(),))
        row = self.cursor.fetchone()
        return row[0] if row else None

    def add_warn(self, user_id: int) -> int:
        self.cursor.execute('''
            INSERT INTO warns (user_id, count) VALUES (?, 1)
            ON CONFLICT(user_id) DO UPDATE SET count = count + 1
            RETURNING count
        ''', (user_id,))
        result = self.cursor.fetchone()
        self.conn.commit()
        return result[0] if result else 1

    def get_warns(self, user_id: int) -> int:
        self.cursor.execute('SELECT count FROM warns WHERE user_id = ?', (user_id,))
        row = self.cursor.fetchone()
        return row[0] if row else 0

    def clear_warns(self, user_id: int) -> int:
        self.cursor.execute('SELECT count FROM warns WHERE user_id = ?', (user_id,))
        row = self.cursor.fetchone()
        count = row[0] if row else 0
        self.cursor.execute('DELETE FROM warns WHERE user_id = ?', (user_id,))
        self.conn.commit()
        return count

    def clear_all_warns(self):
        self.cursor.execute('DELETE FROM warns')
        self.conn.commit()

    def add_mute(self, user_id: int, chat_id: int, until: float):
        self.cursor.execute('''
            INSERT OR REPLACE INTO mutes (user_id, chat_id, until)
            VALUES (?, ?, ?)
        ''', (user_id, chat_id, until))
        self.conn.commit()

    def remove_mute(self, user_id: int):
        self.cursor.execute('DELETE FROM mutes WHERE user_id = ?', (user_id,))
        self.conn.commit()

    def get_mute(self, user_id: int) -> dict | None:
        self.cursor.execute('SELECT * FROM mutes WHERE user_id = ?', (user_id,))
        row = self.cursor.fetchone()
        if row:
            return {'user_id': row[0], 'chat_id': row[1], 'until': row[2]}
        return None

    def get_active_mutes(self) -> list:
        now = datetime.now().timestamp()
        self.cursor.execute('SELECT * FROM mutes WHERE until > ?', (now,))
        return [
            {'user_id': row[0], 'chat_id': row[1], 'until': row[2]}
            for row in self.cursor.fetchall()
        ]
    
    def get_all_users_with_warns(self) -> list[int]:
        self.cursor.execute('SELECT user_id FROM warns WHERE count > 0')
        return [row[0] for row in self.cursor.fetchall()]

    def add_ban(self, chat_id: int, user_id: int):
        self.cursor.execute('''
            INSERT OR IGNORE INTO bans (chat_id, user_id) VALUES (?, ?)
        ''', (chat_id, user_id))
        self.conn.commit()

    def remove_ban(self, chat_id: int, user_id: int):
        self.cursor.execute('''
            DELETE FROM bans WHERE chat_id = ? AND user_id = ?
        ''', (chat_id, user_id))
        self.conn.commit()

    def get_bans(self, chat_id: int) -> list[int]:
        self.cursor.execute('SELECT user_id FROM bans WHERE chat_id = ?', (chat_id,))
        return [row[0] for row in self.cursor.fetchall()]

    def clear_bans(self, chat_id: int):
        self.cursor.execute('DELETE FROM bans WHERE chat_id = ?', (chat_id,))
        self.conn.commit()

    def close(self):
        self.conn.close()

# Инициализация базы данных
db = Database()

# ————————————————————— Временные хранилища —————————————————————
pending_check: dict[int, dict] = {}
verification_tasks: dict[int, asyncio.Task] = {}

# ————————————————————— Утилиты —————————————————————
def log_action(action: str, performer_id: int, target_id: int = None, details: str = None):
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
    params = {
        'chat_id': chat_id,
        'user_id': user_id,
        'permissions': ChatPermissions(
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
        )
    }
    if until_ts:
        params['until_date'] = int(until_ts)
    try:
        await bot.restrict_chat_member(**params)
    except Exception as e:
        logger.error(f"Ошибка при ограничении пользователя: {e}")

async def lift_restrictions(chat_id: int, user_id: int) -> bool:
    try:
        chat = await bot.get_chat(chat_id)
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=chat.permissions
        )
        db.remove_mute(user_id)
        log_action("Restrictions lifted", 0, user_id)
        return True
    except Exception as e:
        logger.error(f"Ошибка при снятии ограничений: {e}")
        return False

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
        # Если это объект User
        if isinstance(ref, types.User):
            db.update_user(ref)
            return ref.id
            
        # Если это строка
        if isinstance(ref, str):
            # Удаляем @ в начале
            ref = ref.lstrip('@').lower()
            
            # Если это число
            if ref.isdigit():
                return int(ref)
                
            # Поиск по username
            user_id = db.get_user_by_username(ref)
            if user_id:
                return user_id
                
            # Попытка получить пользователя по упоминанию
            if ref.startswith('tg://user?id='):
                return int(ref.split('=')[1])
                
        return None
    except Exception as e:
        logger.error(f"Ошибка в get_user_id: {e}")
        return None

# ————————————————————— Инициализация и клавиатура —————————————————————
check_kb = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="Я не бот ✅", callback_data="verify")]]
)

# ————————————————————— Фоновые задачи —————————————————————
async def clear_console_periodically():
    while True:
        await asyncio.sleep(3600)
        os.system('cls' if os.name == 'nt' else 'clear')

async def background_unmute():
    while True:
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
        await asyncio.sleep(10)

# ————————————————————— Верификация новых участников —————————————————————
@dp.chat_member(F.chat_member_updated.new_chat_member.status == ChatMemberStatus.MEMBER)
async def on_member_update(event: types.ChatMemberUpdated):
    try:
        await start_verification(event.new_chat_member.user, event.chat.id)
    except Exception as e:
        logger.error(f"Ошибка в on_member_update: {e}")

@dp.message(F.new_chat_members)
async def on_new_chat_members(message: types.Message):
    try:
        for u in message.new_chat_members:
            await start_verification(u, message.chat.id)
    except Exception as e:
        logger.error(f"Ошибка в on_new_chat_members: {e}")

async def start_verification(user: types.User, chat_id: int):
    try:
        db.update_user(user)
        mention = await get_user_mention(chat_id, user.id)
        await restrict_user(chat_id, user.id)
        msg = await bot.send_message(
            chat_id,
            f"Привет, {mention}! Ты попал в чат OG Community!\n"
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
            await bot.ban_chat_member(data["chat_id"], user_id)
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
        
        # Отмена таймаута
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
            f"Привет, {mention}! ❤️\n"
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

# ————————————————————— Команды модерации —————————————————————
@dp.message(Command(commands=["ban", "mute", "warn", "unban", "unmute", "warns", "clearwarns"]))
async def moderation_commands(message: types.Message):
    try:
        if not await is_moderator(message.chat.id, message.from_user.id):
            await message.reply("❌ У вас нет прав.")
            return
        
        # Получаем команду без префикса /
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
        
        # Определение цели
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
        
        # Проверка статуса
        try:
            m = await bot.get_chat_member(message.chat.id, uid)
            if m.status == ChatMemberStatus.KICKED:
                await message.reply(f"ℹ️ {await get_user_mention(message.chat.id, uid)} уже забанен.")
                return
        except:
            pass
        
        # Бан пользователя
        await bot.ban_chat_member(message.chat.id, uid)
        db.add_ban(message.chat.id, uid)
        
        await message.reply(
            f"✅ {await get_user_mention(message.chat.id, uid)} забанен.\n"
            f"Причина: {reason or 'не указана'}"
        )
        log_action("Ban", message.from_user.id, uid, reason)
    except Exception as e:
        logger.error(f"Ошибка в cmd_ban: {e}")
        await message.reply("❌ Произошла ошибка при выполнении команды.")

async def cmd_mute(message: types.Message):
    try:
        parts = message.text.split(maxsplit=3)
        
        # Определение цели и параметров
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
        
        # Проверка существующего мута
        mute = db.get_mute(uid)
        now = datetime.now().timestamp()
        if mute and mute["until"] > now:
            until_dt = datetime.fromtimestamp(mute["until"])
            until_str = until_dt.strftime("%d.%m.%Y %H:%M")
            await message.reply(
                f"ℹ️ {await get_user_mention(message.chat.id, uid)} уже в муте до {until_str}."
            )
            return
        
        # Установка длительности
        duration = parse_duration(dur_str) or timedelta(hours=3)
        until = datetime.now() + duration
        until_ts = until.timestamp()
        
        # Применение ограничений
        await restrict_user(message.chat.id, uid, until_ts)
        db.add_mute(uid, message.chat.id, until_ts)
        
        reply_text = f"✅ {await get_user_mention(message.chat.id, uid)}, замучен на {get_duration_display(duration)}."
        if reason:
            reply_text += f"\nПричина: {reason}"
            
        await message.reply(reply_text)
        log_action("Mute", message.from_user.id, uid, get_duration_display(duration))
    except Exception as e:
        logger.error(f"Ошибка в cmd_mute: {e}")
        await message.reply("❌ Произошла ошибка при выполнении команды.")

async def cmd_warn(message: types.Message):
    try:
        parts = message.text.split(maxsplit=2)
        
        # Определение цели
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
        
        # Добавление предупреждения
        count = db.add_warn(uid)
        form = pluralize(count, "предупреждение", "предупреждения", "предупреждений")
        
        # Формирование ответа
        text = f"⚠️ {await get_user_mention(message.chat.id, uid)} получил предупреждение.\nВсего: {count} {form}."
        if reason:
            text += f"\nПричина: {reason}"
        
        # Автобан при 5 предупреждениях
        if count >= 5:
            await bot.ban_chat_member(message.chat.id, uid)
            db.add_ban(message.chat.id, uid)
            text += "\n🚫 Авто-бан за 5 предупреждений."
            log_action("Auto-ban 5 warns", 0, uid)
        
        await message.reply(text)
        log_action("Warn", message.from_user.id, uid, f"Total: {count}")
    except Exception as e:
        logger.error(f"Ошибка в cmd_warn: {e}")
        await message.reply("❌ Произошла ошибка при выполнении команды.")

async def cmd_unban(message: types.Message):
    try:
        parts = message.text.split(maxsplit=1)
        
        # Определение цели
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
        
        # Снятие бана
        await bot.unban_chat_member(message.chat.id, uid)
        db.remove_ban(message.chat.id, uid)
        
        await message.reply(f"✅ {await get_user_mention(message.chat.id, uid)} разбанен.")
        log_action("Unban", message.from_user.id, uid)
    except Exception as e:
        logger.error(f"Ошибка в cmd_unban: {e}")
        await message.reply("❌ Произошла ошибка при выполнении команды.")

async def cmd_unmute(message: types.Message):
    try:
        parts = message.text.split(maxsplit=1)
        
        # Определение цели
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
        
        # Снятие мута
        if await lift_restrictions(message.chat.id, uid):
            await message.reply(f"✅ {await get_user_mention(message.chat.id, uid)}, ограничения сняты.")
            log_action("Unmute", message.from_user.id, uid)
        else:
            await message.reply("❌ Не удалось снять ограничения.")
    except Exception as e:
        logger.error(f"Ошибка в cmd_unmute: {e}")
        await message.reply("❌ Произошла ошибка при выполнении команды.")

async def cmd_warns(message: types.Message):
    try:
        parts = message.text.split(maxsplit=1)
        
        # Определение цели
        if message.reply_to_message:
            tgt = message.reply_to_message.from_user
        else:
            tgt = parts[1] if len(parts) > 1 else message.from_user
        
        uid = await get_user_id(message, tgt)
        if not uid:
            await message.reply("❌ Пользователь не найден.")
            return
        
        # Получение количества предупреждений
        count = db.get_warns(uid)
        form = pluralize(count, "предупреждение", "предупреждения", "предупреждений")
        await message.reply(f"ℹ️ {await get_user_mention(message.chat.id, uid)} имеет {count} {form}.")
    except Exception as e:
        logger.error(f"Ошибка в cmd_warns: {e}")
        await message.reply("❌ Произошла ошибка при выполнении команды.")

async def cmd_clearwarns(message: types.Message):
    try:
        parts = message.text.split(maxsplit=1)
        
        # Определение цели
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
        
        # Сброс предупреждений
        old_count = db.clear_warns(uid)
        await message.reply(
            f"✅ Предупреждения сброшены ({old_count} → 0) для "
            f"{await get_user_mention(message.chat.id, uid)}."
        )
        log_action("Clear warns", message.from_user.id, uid)
    except Exception as e:
        logger.error(f"Ошибка в cmd_clearwarns: {e}")
        await message.reply("❌ Произошла ошибка при выполнении команды.")

# ————————————————————— Списки и амнистия —————————————————————
@dp.message(Command(commands=["муты", "варны", "баны", "амнистия", "amnesty"]))
async def list_commands(message: types.Message):
    try:
        if not await is_moderator(message.chat.id, message.from_user.id):
            await message.reply("❌ У вас нет прав.")
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
    try:
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
    try:
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
    try:
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
    try:
        # Снятие всех мутов
        for mute in db.get_active_mutes():
            await lift_restrictions(mute["chat_id"], mute["user_id"])
        
        # Разбан всех пользователей
        bans = db.get_bans(message.chat.id)
        for uid in bans:
            try:
                await bot.unban_chat_member(message.chat.id, uid)
                db.remove_ban(message.chat.id, uid)
            except:
                pass
        
        # Сброс всех предупреждений
        db.clear_all_warns()
        
        await message.reply("✅ Амнистия проведена! Все ограничения сняты, предупреждения обнулены.")
        log_action("Amnesty", message.from_user.id)
    except Exception as e:
        logger.error(f"Ошибка в cmd_amnesty: {e}")
        await message.reply("❌ Произошла ошибка при выполнении команды.")

# ————————————————————— Прощание при уходе участника —————————————————————
@dp.message(F.left_chat_member)
async def on_user_left(message: types.Message):
    try:
        user = message.left_chat_member
        mention = f'<a href="tg://user?id={user.id}">{html.escape(user.full_name)}</a>'
        await message.answer(f"👋 Всего хорошего, {mention}!")
    except:
        pass

# ————————————————————— Пересылка сообщений в канал —————————————————————
@dp.message(F.chat.type.in_({"group", "supergroup"}) & ~F.service & ~F.text.startswith('/'))
async def forward_to_channel(message: types.Message):
    """Пересылает все сообщения чата в указанный канал"""
    try:
        # Пересылаем сообщение с сохранением формата
        await bot.forward_message(
            chat_id=LOG_CHANNEL,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )
    except Exception as e:
        logger.error(f"Ошибка при пересылке сообщения: {e}")

# ————————————————————— Запуск бота —————————————————————
async def main():
    asyncio.create_task(clear_console_periodically())
    asyncio.create_task(background_unmute())
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        db.close()  # Закрытие соединения с БД при выходе