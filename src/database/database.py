import sqlite3
from typing import Optional, Dict, List
from aiogram import types


class Database:
    def __init__(self, db_path='src/database/bot_data.db'):
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

    def get_user(self, user_id: int) -> Dict:
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

    def get_user_by_username(self, username: str) -> Optional[int]:
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

    def get_mute(self, user_id: int) -> Optional[Dict]:
        self.cursor.execute('SELECT * FROM mutes WHERE user_id = ?', (user_id,))
        row = self.cursor.fetchone()
        if row:
            return {'user_id': row[0], 'chat_id': row[1], 'until': row[2]}
        return None

    def get_active_mutes(self) -> List[Dict]:
        from datetime import datetime
        now = datetime.now().timestamp()
        self.cursor.execute('SELECT * FROM mutes WHERE until > ?', (now,))
        return [
            {'user_id': row[0], 'chat_id': row[1], 'until': row[2]}
            for row in self.cursor.fetchall()
        ]
    
    def get_all_users_with_warns(self) -> List[int]:
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

    def get_bans(self, chat_id: int) -> List[int]:
        self.cursor.execute('SELECT user_id FROM bans WHERE chat_id = ?', (chat_id,))
        return [row[0] for row in self.cursor.fetchall()]

    def clear_bans(self, chat_id: int):
        self.cursor.execute('DELETE FROM bans WHERE chat_id = ?', (chat_id,))
        self.conn.commit()

    def close(self):
        self.conn.close()
