import asyncio

from src.config import dp
from src.database import Database
from src.background import clear_console_periodically, background_unmute

import src.handlers.moderation  
import src.handlers.lists       
import src.verification         
import src.handlers.mute_filter 
import src.handlers.other       

async def main():
    asyncio.create_task(clear_console_periodically())
    asyncio.create_task(background_unmute())
    
    from src.config import bot
    
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        db = Database()
        db.close()