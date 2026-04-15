import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "-1003678808679"))
TARGET_CHAT_ID = int(os.getenv("TARGET_CHAT_ID", "-1002964912521"))
DB_NAME = os.getenv("DB_NAME", "bot_database.db")

PROJECT_NAME = os.getenv("PROJECT_NAME", "NAME")
WELCOME_TEXT = os.getenv(
    "WELCOME_TEXT",
    "Добро пожаловать!"
)
RULES_TEXT = os.getenv(
    "RULES_TEXT",
    "После заполнения анкеты вы соглашаетесь с правилами проекта."
)

QUESTION_1 = os.getenv("QUESTION_1", "Как тебя зовут (ник/имя)?")
QUESTION_2 = os.getenv("QUESTION_2", "Твой возраст?")
QUESTION_3 = os.getenv("QUESTION_3", "Расскажи немного о себе")
QUESTION_4 = os.getenv("QUESTION_4", "Откуда узнал о нас?")

APPROVE_TEXT = os.getenv("APPROVE_TEXT", "✅ Прошёл")
REJECT_TEXT = os.getenv("REJECT_TEXT", "❌ Не прошёл")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher()

class Questionnaire(StatesGroup):
    name = State()
    age = State()
    about = State()
    interests = State()

# --- БАЗА ДАННЫХ ---

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                is_submitted INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                name TEXT,
                age TEXT,
                about TEXT,
                interests TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )
        """)
        await db.commit()

async def check_user_submitted(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT is_submitted FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None and row[0] == 1

async def register_submission(user_id: int, username: str, full_name: str):
async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO users (user_id, username, full_name, is_submitted)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                is_submitted = 1
        """, (user_id, username, full_name))
        await db.commit()

async def save_application(user_id, username, full_name, name, age, about, interests):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO applications (
                user_id, username, full_name, name, age, about, interests, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                name = excluded.name,
                age = excluded.age,
                about = excluded.about,
                interests = excluded.interests,
                status = 'pending',
                created_at = excluded.created_at
        """, (
            user_id,
            username,
            full_name,
            name,
            age,
            about,
            interests,
            datetime.now(timezone.utc).isoformat()
        ))
        await db.commit()

async def get_application(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("""
            SELECT user_id, username, full_name, name, age, about, interests, status
            FROM applications
            WHERE user_id = ?
        """, (user_id,)) as cursor:
            return await cursor.fetchone()

async def set_application_status(user_id: int, status: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            UPDATE applications
            SET status = ?
            WHERE user_id = ?
        """, (status, user_id))
        await db.commit()

# --- КНОПКИ ---

def admin_keyboard(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=APPROVE_TEXT, callback_data=f"approve:{user_id}")
    builder.button(text=REJECT_TEXT, callback_data=f"reject:{user_id}")
    builder.adjust(2)
    return builder.as_markup()

# --- ОФОРМЛЕНИЕ АНКЕТЫ ---

def format_application_text(full_name: str, user_id: int, username: str, data: dict) -> str:
    return (
        f"╭─✨ <b>Новая анкета</b> ✨─╮\n\n"
        f"👤 <b>Пользователь:</b> {full_name}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"🔗 <b>Username:</b> {username}\n\n"
        f"├─ <b>{QUESTION_1}</b>\n"
        f"│  <i>{data['name']}</i>\n\n"
        f"├─ <b>{QUESTION_2}</b>\n"
        f"│  <i>{data['age']}</i>\n\n"
        f"├─ <b>{QUESTION_3}</b>\n"
        f"│  <i>{data['about']}</i>\n\n"
        f"╰─ <b>{QUESTION_4}</b>\n"
        f"   <i>{data['interests']}</i>\n\n"
        f"<b>Статус:</b> <code>pending</code>"
    )

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("get_id"))
async def cmd_get_id(message: types.Message):
    await message.answer(f"ID чата: {message.chat.id}", parse_mode=ParseMode.HTML)

@dp.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext):
    if await check_user_submitted(message.from_user.id):
        await message.answer("❌ Вы уже отправляли анкету. Повторная подача заявки невозможна.")
        return

    await message.answer(
        f"Привет, {message.from_user.full_name}! 👋\n"
        f"{WELCOME_TEXT}\n\n"
        f"Чтобы подать заявку на вступление, заполни небольшую анкету.\n"
f"{RULES_TEXT}\n\n"
        f"{QUESTION_1}",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Questionnaire.name)

@dp.message(Questionnaire.name, F.text)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer(QUESTION_2)
    await state.set_state(Questionnaire.age)

@dp.message(Questionnaire.age, F.text)
async def process_age(message: types.Message, state: FSMContext):
    await state.update_data(age=message.text)
    await message.answer(QUESTION_3)
    await state.set_state(Questionnaire.about)

@dp.message(Questionnaire.about, F.text)
async def process_about(message: types.Message, state: FSMContext):
    await state.update_data(about=message.text)
    await message.answer(QUESTION_4)
    await state.set_state(Questionnaire.interests)

@dp.message(Questionnaire.interests, F.text)
async def process_interests(message: types.Message, state: FSMContext):
    await state.update_data(interests=message.text)
    data = await state.get_data()

    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "скрыт"
    full_name = message.from_user.full_name

    admin_text = format_application_text(full_name, user_id, username, data)

    try:
        await save_application(
            user_id=user_id,
            username=username,
            full_name=full_name,
            name=data["name"],
            age=data["age"],
            about=data["about"],
            interests=data["interests"]
        )

        await bot.send_message(
            ADMIN_CHAT_ID,
            admin_text,
            reply_markup=admin_keyboard(user_id),
            parse_mode=ParseMode.HTML
        )

        await register_submission(user_id, username, full_name)

        await message.answer(
            f"✨ Спасибо! Твоя анкета отправлена администраторам {PROJECT_NAME}.\n"
            f"Ожидай решения!"
        )
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await message.answer("❌ Ошибка при отправке. Возможно, бот не добавлен в чат админов или нет прав.")

    await state.clear()

@dp.message(Questionnaire())
async def error_not_text(message: types.Message):
    await message.answer("⚠️ Пожалуйста, используйте только текст для заполнения анкеты.")

# --- РЕШЕНИЯ АДМИНА ---

@dp.callback_query(F.data.startswith("approve:"))
async def approve_application(callback: types.CallbackQuery):
    try:
        user_id = int(callback.data.split(":")[1])
        app = await get_application(user_id)

        if not app:
            await callback.answer("Анкета не найдена.", show_alert=True)
            return

        if app[7] != "pending":
            await callback.answer("Эта анкета уже обработана.", show_alert=True)
            return

        expire_date = datetime.now(timezone.utc) + timedelta(hours=24)

        invite_link = await bot.create_chat_invite_link(
            chat_id=TARGET_CHAT_ID,
            member_limit=1,
            expire_date=expire_date
        )

        await bot.send_message(
            user_id,
            "✅ <b>Ваша заявка одобрена!</b>\n\n"
            "Вот ваша одноразовая ссылка для вступления:\n"
            f"{invite_link.invite_link}",
            parse_mode=ParseMode.HTML
        )

        await set_application_status(user_id, "approved")

        try:
            new_text = callback.message.text + "\n\n✅ <b>Решение:</b> одобрен, ссылка отправлена."
            await callback.message.edit_text(new_text, parse_mode=ParseMode.HTML)
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
pass

        await callback.answer("Ссылка отправлена пользователю.")
    except Exception as e:
        logging.error(f"Ошибка при одобрении: {e}")
        await callback.answer("Не удалось отправить ссылку.", show_alert=True)

@dp.callback_query(F.data.startswith("reject:"))
async def reject_application(callback: types.CallbackQuery):
    try:
        user_id = int(callback.data.split(":")[1])
        app = await get_application(user_id)

        if not app:
            await callback.answer("Анкета не найдена.", show_alert=True)
            return

        if app[7] != "pending":
            await callback.answer("Эта анкета уже обработана.", show_alert=True)
            return

        await bot.send_message(
            user_id,
            "❌ <b>К сожалению, ваша заявка не одобрена.</b>",
            parse_mode=ParseMode.HTML
        )

        await set_application_status(user_id, "rejected")

        try:
            new_text = callback.message.text + "\n\n❌ <b>Решение:</b> не одобрен."
            await callback.message.edit_text(new_text, parse_mode=ParseMode.HTML)
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

        await callback.answer("Пользователю отправлено уведомление.")
    except Exception as e:
        logging.error(f"Ошибка при отклонении: {e}")
        await callback.answer("Не удалось отправить сообщение.", show_alert=True)

# --- ЗАПУСК ---

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
