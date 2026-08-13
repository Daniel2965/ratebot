import asyncio
import logging
from datetime import datetime, date, timedelta
from collections import Counter

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, 
    ReplyKeyboardMarkup, KeyboardButton, LabeledPrice, PreCheckoutQuery
)
from aiohttp import web
import asyncpg

# ================= 🔧 ВСТАВЬ СВОИ ДАННЫЕ СЮДА 🔧 =================
BOT_TOKEN = "8950068828:AAGGTOqKNHCGzLj-4VsfSjMe-ImLynRaNKg"
CHANNEL_USERNAME = "@ratevinchik"
DATABASE_URL = "postgres://neondb_owner:npg_G9EeWbxdrUg2@ep-still-heart-ayeph7s3-pooler.c-5.us-east-2.aws.neon.tech/neondb?sslmode=require"
# =================================================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db_pool: asyncpg.Pool = None

MALE_SCORES = ["sub 3", "sub 5", "ltn", "mtn", "htn", "chad-lite", "chad", "adam-lite", "true adam"]
FEMALE_SCORES = ["sub 3", "sub 5", "ltb", "mtb", "htb", "Stacy-lite", "Stacy", "Eve-lite", "True Eve"]

class Registration(StatesGroup):
    waiting_for_agreement = State()
    waiting_for_age = State()
    waiting_for_gender = State()
    waiting_for_photo = State()

async def get_db_user(user_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)

async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except Exception:
        return False

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user = await get_db_user(message.from_user.id)
    if user and user['photo_id']:
        await show_main_menu(message)
        return

    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        referrer_id = int(args[1].replace("ref_", ""))
        await state.update_data(referrer_id=referrer_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Политика конфиденциальности", url="https://telegra.ph/Privacy-Policy")],
        [InlineKeyboardButton(text="✅ Да, согласен", callback_data="agree_policy")]
    ])
    await message.answer("Добро пожаловать! Подтвердите согласие с политикой конфиденциальности:", reply_markup=kb)
    await state.set_state(Registration.waiting_for_agreement)

@dp.callback_query(F.data == "agree_policy", Registration.waiting_for_agreement)
async def process_agreement(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Укажите ваш возраст (от 12 до 30):")
    await state.set_state(Registration.waiting_for_age)
    await callback.answer()

@dp.message(Registration.waiting_for_age)
async def process_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or not (12 <= int(message.text) <= 30):
        await message.answer("Введите число от 12 до 30:")
        return
    await state.update_data(age=int(message.text))
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Мужчина"), KeyboardButton(text="Женщина")]
    ], resize_keyboard=True, one_time_keyboard=True)
    await message.answer("Выберите ваш пол:", reply_markup=kb)
    await state.set_state(Registration.waiting_for_gender)

@dp.message(Registration.waiting_for_gender, F.text.in_(["Мужчина", "Женщина"]))
async def process_gender(message: types.Message, state: FSMContext):
    gender = "male" if message.text == "Мужчина" else "female"
    await state.update_data(gender=gender)
    await message.answer("Отправьте фото вашего лица:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(Registration.waiting_for_photo)

@dp.message(Registration.waiting_for_photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photo_id = message.photo[-1].file_id
    user_id = message.from_user.id
    referrer_id = data.get("referrer_id")

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, age, gender, photo_id, referrer_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (user_id) DO UPDATE 
            SET age = EXCLUDED.age, gender = EXCLUDED.gender, photo_id = EXCLUDED.photo_id
        """, user_id, message.from_user.username, data['age'], data['gender'], photo_id, referrer_id)

    await state.clear()
    await message.answer("🎉 Регистрация завершена!")
    await show_main_menu(message)

async def show_main_menu(message: types.Message):
    if not await check_subscription(message.from_user.id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
            [InlineKeyboardButton(text="Я подписался", callback_data="check_sub")]
        ])
        await message.answer(f"Для доступа нужно подписаться на {CHANNEL_USERNAME}!", reply_markup=kb)
        return

    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="ВИП"), KeyboardButton(text="Оценивать")],
        [KeyboardButton(text="Моя анкета"), KeyboardButton(text="Реферальная система")],
        [KeyboardButton(text="Выбрать кого оценивать"), KeyboardButton(text="Топы")]
    ], resize_keyboard=True)
    await message.answer("Главное меню:", reply_markup=kb)

@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: types.CallbackQuery):
    if await check_subscription(callback.from_user.id):
        await callback.message.delete()
        await show_main_menu(callback.message)
    else:
        await callback.answer("Вы всё еще не подписались!", show_alert=True)

@dp.message(F.text.in_(["ВИП", "Оценивать", "Моя анкета", "Реферальная система", "Выбрать кого оценивать", "Топы"]))
async def main_menu_router(message: types.Message, state: FSMContext):
    if not await check_subscription(message.from_user.id):
        await show_main_menu(message)
        return

    text = message.text
    if text == "Моя анкета":
        await show_profile(message)
    elif text == "Выбрать кого оценивать":
        await choose_target_gender(message)
    elif text == "Реферальная система":
        await show_referral(message)
    elif text == "Оценивать":
        await start_rating(message)
    elif text == "Топы":
        await show_tops(message)
    elif text == "ВИП":
        await show_vip_offers(message)

async def get_user_calculated_rating(user_id: int, gender: str):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT score FROM ratings WHERE target_user_id = $1", user_id)
        if not rows:
            return "Нет оценок", 0
        scores = [r['score'] for r in rows]
        most_common_score, max_count = Counter(scores).most_common(1)[0]
        return most_common_score, max_count

async def start_rating(message: types.Message):
    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        today = date.today()
        if user['last_rating_date'] != today:
            await conn.execute("UPDATE users SET daily_ratings_count = 0, last_rating_date = $1 WHERE user_id = $2", today, user_id)
            daily_count = 0
        else:
            daily_count = user['daily_ratings_count']

        is_vip = user['is_vip'] and (user['vip_until'] and user['vip_until'] > datetime.now())
        if not is_vip and daily_count >= 30:
            await message.answer("❌ Лимит (30 оценок) исчерпан. Купите ВИП!")
            return

        gender_filter = user['target_gender']
        query = """
            SELECT * FROM users 
            WHERE user_id != $1 AND photo_id IS NOT NULL 
            AND user_id NOT IN (SELECT target_user_id FROM ratings WHERE voter_user_id = $1)
        """
        params = [user_id]
        if gender_filter in ['male', 'female']:
            query += " AND gender = $2"
            params.append(gender_filter)
            
        query += " ORDER BY RANDOM() LIMIT 1"
        target = await conn.fetchrow(query, *params)

        if not target:
            await message.answer("Анкет для оценки пока нет.")
            return

        scores = MALE_SCORES if target['gender'] == 'male' else FEMALE_SCORES
        buttons = [[InlineKeyboardButton(text=s, callback_data=f"rate_{target['user_id']}_{s}")] for s in scores]
        await message.answer_photo(photo=target['photo_id'], caption=f"Анкета: {target['age']} лет", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("rate_"))
async def process_rate_callback(callback: types.CallbackQuery):
    _, target_id, score = callback.data.split("_")
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO ratings (target_user_id, voter_user_id, score) VALUES ($1, $2, $3)", int(target_id), callback.from_user.id, score)
        await conn.execute("UPDATE users SET daily_ratings_count = daily_ratings_count + 1 WHERE user_id = $1", callback.from_user.id)
    await callback.message.delete()
    await callback.answer("Принято!")
    await start_rating(callback.message)

async def show_profile(message: types.Message):
    user = await get_db_user(message.from_user.id)
    rating, count = await get_user_calculated_rating(user['user_id'], user['gender'])
    vip_status = f"До {user['vip_until'].strftime('%d.%m.%Y')}" if user['is_vip'] and user['vip_until'] else "Нет"
    text = f"👤 **Анкета:**\nВозраст: {user['age']}\nПол: {'Мужской' if user['gender'] == 'male' else 'Женский'}\nОценка: **{rating}** ({count} раз)\nВИП: {vip_status}"
    await message.answer_photo(photo=user['photo_id'], caption=text, parse_mode="Markdown")

async def choose_target_gender(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Мужчин", callback_data="set_target_male")],
        [InlineKeyboardButton(text="Женщин", callback_data="set_target_female")],
        [InlineKeyboardButton(text="Всех", callback_data="set_target_all")]
    ])
    await message.answer("Кого оценивать?", reply_markup=kb)

@dp.callback_query(F.data.startswith("set_target_"))
async def set_target_callback(callback: types.CallbackQuery):
    target = callback.data.replace("set_target_", "")
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET target_gender = $1 WHERE user_id = $2", target, callback.from_user.id)
    await callback.answer("Сохранено!")
    await callback.message.edit_text("Настройки обновлены.")

async def show_referral(message: types.Message):
    bot_info = await bot.get_me()
    await message.answer(f"Ссылка: `https://t.me/{bot_info.username}?start=ref_{message.from_user.id}`", parse_mode="Markdown")

async def show_tops(message: types.Message):
    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id, username, gender FROM users WHERE photo_id IS NOT NULL")
        
    leaderboard = []
    for u in users:
        rating, count = await get_user_calculated_rating(u['user_id'], u['gender'])
        if rating == "Нет оценок": continue
        scores_list = MALE_SCORES if u['gender'] == 'male' else FEMALE_SCORES
        rank = scores_list.index(rating) if rating in scores_list else -1
        leaderboard.append({'username': u['username'] or f"ID:{u['user_id']}", 'rating': rating, 'count': count, 'rank': rank})

    leaderboard.sort(key=lambda x: (x['rank'], x['count']), reverse=True)
    top_10 = leaderboard[:10]
    if not top_10:
        await message.answer("Топ пуст.")
        return

    res = "🏆 **ТОП-10:**\n\n" + "\n".join([f"{i}. @{u['username']} — **{u['rating']}** ({u['count']})" for i, u in enumerate(top_10, 1)])
    await message.answer(res, parse_mode="Markdown")

async def show_vip_offers(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 день — 10 ⭐", callback_data="buy_vip_1")],
        [InlineKeyboardButton(text="3 дня — 30 ⭐", callback_data="buy_vip_3")],
        [InlineKeyboardButton(text="10 дней — 100 ⭐", callback_data="buy_vip_10")],
        [InlineKeyboardButton(text="30 дней — 300 ⭐", callback_data="buy_vip_30")]
    ])
    await message.answer("Выберите ВИП:", reply_markup=kb)

@dp.callback_query(F.data.startswith("buy_vip_"))
async def process_vip_buy(callback: types.CallbackQuery):
    days = int(callback.data.split("_")[2])
    stars = {1: 10, 3: 30, 10: 100, 30: 300}[days]
    await bot.send_invoice(
        chat_id=callback.from_user.id, title=f"ВИП на {days} дн.",
        description=f"Безлимит оценок на {days} дн.", payload=f"vip_{days}",
        currency="XTR", prices=[LabeledPrice(label=f"ВИП {days} дн.", amount=stars)]
    )
    await callback.answer()

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message):
    days = int(message.successful_payment.invoice_payload.split("_")[1])
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT vip_until FROM users WHERE user_id = $1", message.from_user.id)
        now = datetime.now()
        start_date = user['vip_until'] if user['vip_until'] and user['vip_until'] > now else now
        await conn.execute("UPDATE users SET is_vip = TRUE, vip_until = $1 WHERE user_id = $2", start_date + timedelta(days=days), message.from_user.id)
    await message.answer("🎉 ВИП успешно активирован!")

# Эндпоинт для обмана портов Render
async def handle_ping(request):
    return web.Response(text="Bot is alive!")

async def main():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    
    # Фейковый веб-сервер для того чтобы Render не отключал бота
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 10000)
    await site.start()

    # Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

