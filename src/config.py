import os
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums.parse_mode import ParseMode

load_dotenv()

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

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMINS = set(map(int, os.getenv("ADMINS", "").split(","))) if os.getenv("ADMINS") else set()
LOG_CHANNEL = os.getenv("LOG_CHANNEL")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
