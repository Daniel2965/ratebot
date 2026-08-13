import asyncio
import logging
from datetime import datetime, timedelta
from collections import Counter

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, LabeledPrice, PreCheckoutQuery
)
from aiohttp import web
import asyncpg

# ================= 🔧 НАСТРОЙКИ 🔧 =================
BOT_TOKEN = "8950068828:AAGGTOqKNHCGzLj-4VsfSjMe-ImLynRaNKg"
CHANNEL_USERNAME = "@ratevinchik"
DATABASE_URL = "postgres://neondb_owner:npg_G9EeWbxdrUg2@ep-still-heart-ayeph7s3-pooler.c-5.us-east-2.aws.neon.tech/neondb?sslmode=require"

ADMIN_USERNAMES = ["BLRPMM", "Lelouch_Vi_Britannia4"]
ADMIN_ID_NUM = 746812838
# ===================================================

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

class AdminState(StatesGroup):
    waiting_for_username = State()
    waiting_for_days = State()

class ReportState(StatesGroup):
    waiting_for_reason = State()

class AdminReportState(StatesGroup):
    waiting_for_ban_reason = State()

async def get_db_user(user_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)

async def check_admin(user: types.User) -> bool:
    if user.username and user.username.lower() in [u.lower() for u in ADMIN_USERNAMES]:
        return True
    if user.id == ADMIN_ID_NUM:
        return True
    return False

async def is_user_vip(user_id: int, username: str = None) -> bool:
    if username and username.lower() in [u.lower() for u in ADMIN_USERNAMES]:
        return True
    if user_id == ADMIN_ID_NUM:
        return True
    user = await get_db_user(user_id)
    if not user: return False
    return bool(user['is_vip'] and user['vip_until'] and user['vip_until'] > datetime.now())

async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except: return False

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].split("_")[1])
            if referrer_id == message.from_user.id:
                referrer_id = None
        except ValueError:
            pass

    await state.update_data(referrer_id=referrer_id)

    user = await get_db_user(message.from_user.id)
    if user and user['photo_id']:
        await show_main_menu(message)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, согласен ✨", callback_data="agree_policy")]
    ])
    await message.answer("👋 Добро пожаловать!", reply_markup=kb)
    await state.set_state(Registration.waiting_for_agreement)

@dp.callback_query(F.data == "agree_policy")
async def process_agreement(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🎂 Укажите ваш возраст (от 12 до 30):")
    await state.set_state(Registration.waiting_for_age)
    await callback.answer()

@dp.message(Registration.waiting_for_age)
async def process_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or not (12 <= int(message.text) <= 30): return
    await state.update_data(age=int(message.text))
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="👨 Мужчина"), KeyboardButton(text="👩 Женщина")]], resize_keyboard=True)
    await message.answer("⚧ Выберите пол:", reply_markup=kb)
    await state.set_state(Registration.waiting_for_gender)

@dp.message(Registration.waiting_for_gender)
async def process_gender(message: types.Message, state: FSMContext):
    gender = "male" if "Мужчина" in message.text else "female"
    await state.update_data(gender=gender)
    await message.answer("📸 Отправьте фото:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(Registration.waiting_for_photo)

@dp.message(Registration.waiting_for_photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    referrer_id = data.get("referrer_id")

    async with db_pool.acquire() as conn:
        await conn.execute("""INSERT INTO users (user_id, username, age, gender, photo_id, referrer_id, search_gender)
            VALUES ($1, $2, $3, $4, $5, $6, 'opposite')
            ON CONFLICT (user_id) DO UPDATE
            SET username = EXCLUDED.username, photo_id = EXCLUDED.photo_id""",
            message.from_user.id, message.from_user.username, data['age'], data['gender'], message.photo[-1].file_id, referrer_id)

    await state.clear()
    await message.answer("🎉 Регистрация успешно завершена!")
    await show_main_menu(message)

# ================= ⚡ ГЛАВНОЕ МЕНЮ ⚡ =================
async def show_main_menu(message: types.Message):
    buttons = [
        [KeyboardButton(text="🔥 Оценивать"), KeyboardButton(text="👤 Моя анкета")],
        [KeyboardButton(text="💎 ВИП"), KeyboardButton(text="🏆 Топы")],
        [KeyboardButton(text="⚙️ Кого оценивать"), KeyboardButton(text="🤝 Рефералы")],
        [KeyboardButton(text="🔄 Пересоздать анкету")]
    ]
    if await check_admin(message.from_user):
        buttons.append([KeyboardButton(text="👑 Админка")])
    await message.answer("⚡ Главное меню:", reply_markup=ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True))

@dp.message(F.text == "🔥 Оценивать")
async def handle_rate(message: types.Message): await start_rating(message)

@dp.message(F.text == "👤 Моя анкета")
async def handle_profile(message: types.Message): await show_profile(message)

@dp.message(F.text == "🏆 Топы")
async def handle_tops(message: types.Message): await show_tops(message)

@dp.message(F.text == "💎 ВИП")
async def handle_vip(message: types.Message): await show_vip_offers(message)

@dp.message(F.text == "⚙️ Кого оценивать")
async def handle_settings(message: types.Message): await choose_search_gender(message)

@dp.message(F.text == "🤝 Рефералы")
async def handle_ref(message: types.Message): await show_referrals(message)

@dp.message(F.text == "🔄 Пересоздать анкету")
async def handle_recreate(message: types.Message): await recreate_profile_start(message)

@dp.message(F.text == "👑 Админка")
async def handle_admin(message: types.Message): await admin_panel(message)

# ================= ⚙️ КОГО ОЦЕНИВАТЬ ⚙️ =================
async def choose_search_gender(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Парней 👨", callback_data="set_search_male")],
        [InlineKeyboardButton(text="Девушек 👩", callback_data="set_search_female")],
        [InlineKeyboardButton(text="Всех 🌍", callback_data="set_search_all")]
    ])
    await message.answer("👀 Выберите, чьи анкеты вы хотите оценивать:", reply_markup=kb)

@dp.callback_query(F.data.startswith("set_search_"))
async def set_search_gender_cb(callback: types.CallbackQuery):
    choice = callback.data.split("_")[2]
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET search_gender = $1 WHERE user_id = $2", choice, callback.from_user.id)
    val_map = {"male": "Парней 👨", "female": "Девушек 👩", "all": "Всех 🌍"}
    await callback.message.edit_text(f"✅ Настройки поиска сохранены! Вы будете оценивать: <b>{val_map[choice]}</b>", parse_mode="HTML")
    await callback.answer()

# ================= 🔄 ПЕРЕСОЗДАТЬ АНКЕТУ 🔄 =================
async def recreate_profile_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, пересоздать", callback_data="confirm_recreate")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_recreate")]
    ])
    await message.answer("⚠️ Вы уверены, что хотите удалить текущую анкету и создать новую?\n<i>(Ваши оценки и рейтинг сохранятся)</i>", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "confirm_recreate")
async def process_confirm_recreate(callback: types.CallbackQuery, state: FSMContext):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET photo_id = NULL WHERE user_id = $1", callback.from_user.id)
    await callback.message.delete()
    await callback.message.answer("🗑 Анкета удалена. Пожалуйста, пройдите регистрацию заново.")
    await cmd_start(callback.message, state)
    await callback.answer()

@dp.callback_query(F.data == "cancel_recreate")
async def process_cancel_recreate(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("Отменено. Ваша анкета сохранена! 😌")
    await callback.answer()

# ================= 🤝 РЕФЕРАЛЬНАЯ СИСТЕМА 🤝 =================
async def show_referrals(message: types.Message):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{message.from_user.id}"
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE referrer_id = $1", message.from_user.id)
    text = (f"🤝 <b>Реферальная система</b>\n\nПриглашайте друзей по своей ссылке!\n\n"
            f"🔗 Ваша ссылка:\n<code>{ref_link}</code>\n\n👥 Вы пригласили: <b>{count}</b> чел.")
    await message.answer(text, parse_mode="HTML")

# ================= 🔥 ПРОЦЕСС ОЦЕНКИ 🔥 =================
async def start_rating(message: types.Message):
    user_id = message.from_user.id
    if not await is_user_vip(user_id, message.from_user.username) and not await check_subscription(user_id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
            [InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_sub")]
        ])
        await message.answer(f"⚠️ Для оценки необходимо подписаться на канал {CHANNEL_USERNAME}", reply_markup=kb)
        return

    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if not user:
            await message.answer("Сначала пройдите регистрацию через /start")
            return
        search_gender = dict(user).get('search_gender', 'opposite')
        if search_gender == 'opposite':
            target_gender = 'female' if user['gender'] == 'male' else 'male'
        elif search_gender in ['male', 'female']:
            target_gender = search_gender
        else:
            target_gender = None
        if target_gender:
            target = await conn.fetchrow("""SELECT * FROM users WHERE gender = $1 AND user_id != $2 AND photo_id IS NOT NULL AND user_id NOT IN (SELECT target_id FROM ratings WHERE voter_id = $2) ORDER BY RANDOM() LIMIT 1""", target_gender, user_id)
        else:
            target = await conn.fetchrow("""SELECT * FROM users WHERE user_id != $1 AND photo_id IS NOT NULL AND user_id NOT IN (SELECT target_id FROM ratings WHERE voter_id = $1) ORDER BY RANDOM() LIMIT 1""", user_id)
    if not target:
        await message.answer("😔 Больше нет подходящих анкет для оценки.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Оценить", callback_data=f"rate_{target['user_id']}")],
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip_target")],
        [InlineKeyboardButton(text="🚨 Пожаловаться", callback_data=f"report_{target['user_id']}")]
    ])
    caption = f"👤 Возраст: {target['age']}\n Пол: {'Мужской' if target['gender']=='male' else 'Женский'}"
    await message.answer_photo(photo=target['photo_id'], caption=caption, reply_markup=kb)

@dp.callback_query(F.data == "skip_target")
async def skip_target_callback(callback: types.CallbackQuery):
    await callback.message.delete()
    await start_rating(callback.message)

@dp.callback_query(F.data.startswith("rate_"))
async def rate_target_callback(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[1])
    async with db_pool.acquire() as conn:
        target = await conn.fetchrow("SELECT gender FROM users WHERE user_id = $1", target_id)
    if not target:
        await callback.answer("Анкета не найдена")
        return
    scores = MALE_SCORES if target['gender'] == 'male' else FEMALE_SCORES
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=score, callback_data=f"set_score_{target_id}_{score}")] for score in scores
    ])
    await message.answer("⚙️ Выберите оценку для пользователя:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("set_score_"))
async def save_score_callback(callback: types.CallbackQuery):
    _, _, target_id_str, *score_parts = callback.data.split("_")
    target_id = int(target_id_str)
    score = "_".join(score_parts)
    voter_id = callback.from_user.id
    async with db_pool.acquire() as conn:
        await conn.execute("""INSERT INTO ratings (voter_id, target_id, score) VALUES ($1, $2, $3) ON CONFLICT (voter_id, target_id) DO UPDATE SET score = EXCLUDED.score""", voter_id, target_id, score)
    await callback.answer("✅ Оценка сохранена!")
    try: await callback.message.delete()
    except: pass
    await start_rating(callback.message)

# ================= 🚨 ЖАЛОБЫ 🚨 =================
@dp.callback_query(F.data.startswith("report_"))
async def start_report_process(callback: types.CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split("_")[1])
    await state.update_data(report_target_id=target_id)
    await callback.message.answer("🚨 Опишите причину жалобы (текстом):")
    await state.set_state(ReportState.waiting_for_reason)
    await callback.answer()

@dp.message(ReportState.waiting_for_reason)
async def process_report_reason(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("report_target_id")
    voter_id = message.from_user.id
    reason = message.text
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO reports (target_id, voter_id, reason) VALUES ($1, $2, $3)", target_id, voter_id, reason)
    await message.answer("🚩 Жалоба отправлена администратору!")
    await state.clear()

async def get_user_calculated_rating(user_id: int, gender: str):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT score FROM ratings WHERE target_id = $1", user_id)
    if not rows: return "Нет оценок", 0
    scores_list = MALE_SCORES if gender == 'male' else FEMALE_SCORES
    counts = Counter(r['score'] for r in rows)
    valid_scores = [s for s in scores_list if s in counts]
    if not valid_scores: return "Нет оценок", len(rows)
    best_score = max(valid_scores, key=lambda s: scores_list.index(s))
    return best_score, len(rows)

async def show_profile(message: types.Message):
    user_id = message.from_user.id
    user = await get_db_user(user_id)
    if not user or not user['photo_id']:
        await message.answer("У вас нет активной анкеты. Пройдите /start")
        return
    rating, count = await get_user_calculated_rating(user_id, user['gender'])
    vip_status = "💎 Активен" if await is_user_vip(user_id, user['username']) else "❌ Нет"
    caption = (f"👤 <b>Ваша анкета:</b>\n🎂 Возраст: {user['age']}\n Пол: {'Мужской' if user['gender']=='male' else 'Женский'}\n"
               f"⭐ Ваш рейтинг: <b>{rating}</b>\n👥 Получено оценок: {count}\n💎 ВИП-статус: {vip_status}")
    await message.answer_photo(photo=user['photo_id'], caption=caption, parse_mode="HTML")

async def show_tops(message: types.Message):
    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id, username, gender, photo_id FROM users WHERE photo_id IS NOT NULL")
    leaderboard = []
    for u in users:
        rating, count = await get_user_calculated_rating(u['user_id'], u['gender'])
        if rating == "Нет оценок": continue
        scores_list = MALE_SCORES if u['gender'] == 'male' else FEMALE_SCORES
        rank = scores_list.index(rating) if rating in scores_list else -1
        leaderboard.append({'username': u['username'] or f"ID:{u['user_id']}", 'rating': rating, 'count': count, 'rank': rank, 'photo_id': u['photo_id']})
    leaderboard.sort(key=lambda x: (x['rank'], x['count']), reverse=True)
    top_10 = leaderboard[:10]
    if not top_10:
        await message.answer("😴 Топ пока пуст.")
        return
    await message.answer("🏆 <b>ТОП-10 ПОЛЬЗОВАТЕЛЕЙ:</b> 🏆", parse_mode="HTML")
    for i, u in enumerate(top_10, 1):
        caption = (f"🥇 <b>Место №{i}</b>\n👤 Пользователь: @{u['username']}\n⭐ Оценка: <b>{u['rating']}</b>\n👥 Всего голосов: {u['count']}")
        try: await message.answer_photo(photo=u['photo_id'], caption=caption, parse_mode="HTML")
        except: pass

async def show_vip_offers(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 1 день — 10 Stars", callback_data="buy_vip_1")],
        [InlineKeyboardButton(text="💎 Навсегда — 200 Stars", callback_data="buy_vip_36500")]
    ])
    await message.answer("💎 Выберите вариант покупки <b>ВИП-статуса</b>:", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_vip_"))
async def process_vip_buy(callback: types.CallbackQuery):
    days = int(callback.data.split("_")[2])
    stars = 10 if days == 1 else 200
    await bot.send_invoice(chat_id=callback.from_user.id, title="💎 ВИП", description="Безлимит оценок", payload=f"vip_{days}", currency="XTR", prices=[LabeledPrice(label="ВИП", amount=stars)])
    await callback.answer()

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery): await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message):
    days = int(message.successful_payment.invoice_payload.split("_")[1])
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT vip_until FROM users WHERE user_id = $1", message.from_user.id)
        now = datetime.now()
        start_date = user['vip_until'] if user['vip_until'] and user['vip_until'] > now else now
        await conn.execute("UPDATE users SET is_vip = TRUE, vip_until = $1 WHERE user_id = $2", start_date + timedelta(days=days), message.from_user.id)
    await message.answer("🎉 ВИП успешно активирован!")

# ================= 👑 АДМИН ПАНЕЛЬ 👑 =================
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if not await check_admin(message.from_user): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="adm_users_1")],
        [InlineKeyboardButton(text="🎁 Выдать ВИП", callback_data="adm_give_vip")]
    ])
    await message.answer("👑 <b>Панель администратора:</b>", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("adm_users_"))
async def adm_show_users(callback: types.CallbackQuery):
    if not await check_admin(callback.from_user): return
    page = int(callback.data.split("_")[2])
    limit = 10
    offset = (page - 1) * limit
    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id, username FROM users ORDER BY user_id ASC LIMIT $1 OFFSET $2", limit, offset)
    text = f"👥 <b>Пользователи (стр {page}):</b>\n\n" + "".join([f"{u['username'] or u['user_id']}\n" for u in users])
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "adm_give_vip")
async def adm_give_vip_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("✏️ Введите username:")
    await state.set_state(AdminState.waiting_for_username)
    await callback.answer()

@dp.message(AdminState.waiting_for_username)
async def adm_get_username(message: types.Message, state: FSMContext):
    username = message.text.replace("@", "").strip()
    await state.update_data(target_username=username)
    await message.answer("⏳ На сколько дней?")
    await state.set_state(AdminState.waiting_for_days)

@dp.message(AdminState.waiting_for_days)
async def adm_get_days(message: types.Message, state: FSMContext):
    days = int(message.text)
    data = await state.get_data()
    username = data.get("target_username")
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE LOWER(username) = LOWER($1)", username)
        if user:
            await conn.execute("UPDATE users SET is_vip = TRUE, vip_until = $1 WHERE user_id = $2", datetime.now() + timedelta(days=days), user['user_id'])
            await message.answer(f"✅ Выдан ВИП @{username}")
    await state.clear()

async def handle_ping(request):
    return web.Response(text="Bot is alive!")

async def main():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                age INT,
                gender TEXT,
                photo_id TEXT,
                is_vip BOOLEAN DEFAULT FALSE,
                vip_until TIMESTAMP,
                referrer_id BIGINT,
                search_gender TEXT DEFAULT 'opposite'
            );
            CREATE TABLE IF NOT EXISTS ratings (
                voter_id BIGINT,
                target_id BIGINT,
                score TEXT,
                PRIMARY KEY (voter_id, target_id)
            );
            CREATE TABLE IF NOT EXISTS reports (
                id SERIAL PRIMARY KEY,
                target_id BIGINT,
                voter_id BIGINT,
                reason TEXT
            );
        """)
    
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 10000)
    await site.start()

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

