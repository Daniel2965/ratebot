import asyncio
import logging
from datetime import datetime, date, timedelta
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
ADMIN_ID_NUM = 746812838  # <--- ID для получения уведомлений о покупках
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
    waiting_for_delete_reason = State()

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
    async with db_pool.acquire() as conn:
        await conn.execute("""INSERT INTO users (user_id, username, age, gender, photo_id) VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username, photo_id = EXCLUDED.photo_id""", 
            message.from_user.id, message.from_user.username, data['age'], data['gender'], message.photo[-1].file_id)
    await state.clear()
    await show_main_menu(message)

async def show_main_menu(message: types.Message):
    buttons = [
        [KeyboardButton(text="💎 ВИП"), KeyboardButton(text="🔥 Оценивать")], 
        [KeyboardButton(text="👤 Моя анкета"), KeyboardButton(text="🏆 Топы")]
    ]
    if await check_admin(message.from_user): 
        buttons.append([KeyboardButton(text="👑 Админка")])
    await message.answer("⚡ Главное меню:", reply_markup=ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True))

@dp.message(F.text)
async def main_menu_router(message: types.Message):
    text = message.text.lower()
    if "админка" in text and await check_admin(message.from_user): 
        await admin_panel(message)
    elif "оценивать" in text: 
        await start_rating(message)
    elif "анкета" in text: 
        await show_profile(message)
    elif "топ" in text: 
        await show_tops(message)
    elif "вип" in text: 
        await show_vip_offers(message)

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
        user = await get_db_user(user_id)
        if not user:
            await message.answer("Сначала пройдите регистрацию через /start")
            return
        
        target = await conn.fetchrow("""
            SELECT * FROM users 
            WHERE gender != $1 AND user_id != $2 AND photo_id IS NOT NULL 
            AND user_id NOT IN (SELECT target_id FROM ratings WHERE voter_id = $2)
            ORDER BY RANDOM() LIMIT 1
        """, user['gender'], user_id)

    if not target:
        await message.answer("😔 Больше нет анкет для оценки. Загляните позже!")
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
    await callback.message.answer("⚙️ Выберите оценку для пользователя:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("set_score_"))
async def save_score_callback(callback: types.CallbackQuery):
    _, _, target_id_str, *score_parts = callback.data.split("_")
    target_id = int(target_id_str)
    score = "_".join(score_parts)
    voter_id = callback.from_user.id

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO ratings (voter_id, target_id, score) VALUES ($1, $2, $3)
            ON CONFLICT (voter_id, target_id) DO UPDATE SET score = EXCLUDED.score
        """, voter_id, target_id, score)

    await callback.answer("✅ Оценка сохранена!")
    try:
        await callback.message.delete()
    except:
        pass
    await start_rating(callback.message)

async def get_user_calculated_rating(user_id: int, gender: str):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT score FROM ratings WHERE target_id = $1", user_id)
    if not rows:
        return "Нет оценок", 0
    
    scores_list = MALE_SCORES if gender == 'male' else FEMALE_SCORES
    counts = Counter(r['score'] for r in rows)
    
    valid_scores = [s for s in scores_list if s in counts]
    if not valid_scores:
        return "Нет оценок", len(rows)
    
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
    
    caption = (
        f"👤 **Ваша анкета:**\n"
        f"🎂 Возраст: {user['age']}\n"
        f" Пол: {'Мужской' if user['gender']=='male' else 'Женский'}\n"
        f"⭐ Ваш рейтинг: **{rating}**\n"
        f"👥 Получено оценок: {count}\n"
        f"💎 ВИП-статус: {vip_status}"
    )
    await message.answer_photo(photo=user['photo_id'], caption=caption, parse_mode="Markdown")

async def show_tops(message: types.Message):
    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id, username, gender, photo_id FROM users WHERE photo_id IS NOT NULL")
        
    leaderboard = []
    for u in users:
        rating, count = await get_user_calculated_rating(u['user_id'], u['gender'])
        if rating == "Нет оценок":
            continue
            
        scores_list = MALE_SCORES if u['gender'] == 'male' else FEMALE_SCORES
        rank = scores_list.index(rating) if rating in scores_list else -1
        
        leaderboard.append({
            'username': u['username'] or f"ID:{u['user_id']}",
            'rating': rating,
            'count': count,
            'rank': rank,
            'photo_id': u['photo_id']
        })

    leaderboard.sort(key=lambda x: (x['rank'], x['count']), reverse=True)
    top_10 = leaderboard[:10]

    if not top_10:
        await message.answer("😴 Топ пока пуст.")
        return

    await message.answer("🏆 **ТОП-10 ПОЛЬЗОВАТЕЛЕЙ:** 🏆")

    for i, u in enumerate(top_10, 1):
        caption = (
            f"🥇 **Место №{i}**\n"
            f"👤 Пользователь: @{u['username']}\n"
            f"⭐ Оценка: **{u['rating']}**\n"
            f"👥 Всего голосов: {u['count']}"
        )
        try:
            await message.answer_photo(photo=u['photo_id'], caption=caption, parse_mode="Markdown")
            await asyncio.sleep(0.3)
        except Exception as e:
            logging.error(f"Ошибка в ТОП: {e}")

async def show_vip_offers(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 1 день — 10 Stars", callback_data="buy_vip_1")],
        [InlineKeyboardButton(text="⭐ 3 дня — 30 Stars", callback_data="buy_vip_3")],
        [InlineKeyboardButton(text="⭐ 7 дней — 50 Stars", callback_data="buy_vip_7")],
        [InlineKeyboardButton(text="⭐ 30 дней — 100 Stars", callback_data="buy_vip_30")],
        [InlineKeyboardButton(text="💎 Навсегда — 200 Stars", callback_data="buy_vip_36500")]
    ])
    await message.answer("💎 Выберите вариант покупки **ВИП-статуса**:", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("buy_vip_"))
async def process_vip_buy(callback: types.CallbackQuery):
    days = int(callback.data.split("_")[2])
    vip_prices = {
        1: (10, "1 день"),
        3: (30, "3 дня"),
        7: (50, "7 дней"),
        30: (100, "30 дней"),
        36500: (200, "Навсегда")
    }
    stars, title_text = vip_prices.get(days, (10, "1 день"))
    
    await bot.send_invoice(
        chat_id=callback.from_user.id, 
        title=f"💎 ВИП ({title_text})",
        description=f"Безлимит оценок ({title_text})", 
        payload=f"vip_{days}",
        currency="XTR", 
        prices=[LabeledPrice(label=f"ВИП {title_text}", amount=stars)]
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
    
    try:
        await bot.send_message(chat_id=ADMIN_ID_NUM, text=f"💰 Покупка ВИП!\nЮзер: @{message.from_user.username}\nДней: {days}")
    except:
        pass
        
    await message.answer("🎉 ВИП успешно активирован!")

# ================= 👑 АДМИН ПАНЕЛЬ + РЕПОРТЫ 👑 =================
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if not await check_admin(message.from_user): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="adm_users_1")],
        [InlineKeyboardButton(text="🚨 Жалобы", callback_data="adm_reports_1")],
        [InlineKeyboardButton(text="🎁 Выдать ВИП по @username", callback_data="adm_give_vip")]
    ])
    await message.answer("👑 **Панель администратора:**", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("adm_reports_"))
async def adm_show_reports(callback: types.CallbackQuery):
    if not await check_admin(callback.from_user):
        await callback.answer("Ошибка доступа", show_alert=True)
        return
        
    page = int(callback.data.split("_")[2])
    limit = 5
    offset = (page - 1) * limit

    async with db_pool.acquire() as conn:
        reports = await conn.fetch("SELECT * FROM reports ORDER BY id DESC LIMIT $1 OFFSET $2", limit, offset)
        total_count = await conn.fetchval("SELECT COUNT(*) FROM reports")

    if not reports:
        await callback.answer("Жалоб нет.", show_alert=True)
        return

    text = f"🚨 **Жалобы (Страница {page}):**\n\n"
    for r in reports:
        text += f"• На пользователя ID: `{r['target_id']}` | От ID: `{r['voter_id']}`\n"

    total_pages = (total_count + limit - 1) // limit
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm_reports_{page - 1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"adm_reports_{page + 1}"))

    keyboard = [nav_buttons] if nav_buttons else []
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data.startswith("report_"))
async def process_report(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[1])
    voter_id = callback.from_user.id
    
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO reports (target_id, voter_id) VALUES ($1, $2)", target_id, voter_id)
        
    await callback.answer("🚩 Жалоба отправлена администратору!", show_alert=True)

@dp.callback_query(F.data.startswith("adm_users_"))
async def adm_show_users(callback: types.CallbackQuery):
    if not await check_admin(callback.from_user):
        await callback.answer("Ошибка доступа", show_alert=True)
        return

    page = int(callback.data.split("_")[2])
    limit = 10
    offset = (page - 1) * limit

    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id, username FROM users ORDER BY user_id ASC LIMIT $1 OFFSET $2", limit, offset)
        total_count = await conn.fetchval("SELECT COUNT(*) FROM users")

    if not users:
        await callback.answer("На этой странице нет пользователей.", show_alert=True)
        return

    text = f"👥 **Список зарегистрированных пользователей (Страница {page}):**\n\n"
    for i, u in enumerate(users, start=offset + 1):
        uname = f"@{u['username']}" if u['username'] else f"ID: `{u['user_id']}`"
        text += f"{i}. {uname}\n"

    total_pages = (total_count + limit - 1) // limit
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"adm_users_{page - 1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"adm_users_{page + 1}"))

    keyboard = [nav_buttons] if nav_buttons else []
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data == "adm_give_vip")
async def adm_give_vip_start(callback: types.CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user):
        await callback.answer("Ошибка доступа", show_alert=True)
        return
    await callback.message.answer("✏️ Введите @username пользователя (без знака @):")
    await state.set_state(AdminState.waiting_for_username)
    await callback.answer()

@dp.message(AdminState.waiting_for_username)
async def adm_get_username(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user):
        return
    username = message.text.replace("@", "").strip()
    await state.update_data(target_username=username)
    await message.answer("⏳ На сколько дней выдать ВИП? (введите число):")
    await state.set_state(AdminState.waiting_for_days)

@dp.message(AdminState.waiting_for_days)
async def adm_get_days(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user):
        return
    if not message.text.isdigit():
        await message.answer("⚠️ Введите число дней:")
        return
    
    days = int(message.text)
    data = await state.get_data()
    username = data.get("target_username")

    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE LOWER(username) = LOWER($1)", username)
        if not user:
            await message.answer(f"❌ Пользователь @{username} не найден в базе данных бота.")
            await state.clear()
            return

        now = datetime.now()
        start_date = user['vip_until'] if user['vip_until'] and user['vip_until'] > now else now
        new_vip = start_date + timedelta(days=days)
        
        await conn.execute("UPDATE users SET is_vip = TRUE, vip_until = $1 WHERE user_id = $2", new_vip, user['user_id'])

    try:
        await bot.send_message(chat_id=user['user_id'], text=f"🎉 Администратор выдал вам 💎 **ВИП на {days} дней**!")
    except Exception:
        pass

    await message.answer(f"✅ Пользователю @{username} успешно выдан ВИП на {days} дней!")
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
                vip_until TIMESTAMP
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
                voter_id BIGINT
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

