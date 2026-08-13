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

# Telegram ID админа (обновится автоматически по юзернейму @BLRPMM при старте)
ADMIN_USERNAME = "BLRPMM"
ADMIN_ID = 0  
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

async def is_user_vip(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    user = await get_db_user(user_id)
    if not user:
        return False
    return user['is_vip'] and (user['vip_until'] and user['vip_until'] > datetime.now())

async def check_subscription(user_id: int) -> bool:
    try:
        clean_channel = CHANNEL_USERNAME.strip()
        member = await bot.get_chat_member(chat_id=clean_channel, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except Exception as e:
        logging.error(f"Ошибка проверки подписки: {e}")
        return False

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    global ADMIN_ID
    if message.from_user.username and message.from_user.username.lower() == ADMIN_USERNAME.lower():
        ADMIN_ID = message.from_user.id

    user = await get_db_user(message.from_user.id)
    if user and user['photo_id']:
        await show_main_menu(message)
        return

    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        referrer_id = int(args[1].replace("ref_", ""))
        await state.update_data(referrer_id=referrer_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Политика конфиденциальности 📜", url="https://telegra.ph/Privacy-Policy")],
        [InlineKeyboardButton(text="✅ Да, согласен ✨", callback_data="agree_policy")]
    ])
    await message.answer("👋 Добро пожаловать! Подтвердите согласие с политикой конфиденциальности:", reply_markup=kb)
    await state.set_state(Registration.waiting_for_agreement)

@dp.callback_query(F.data == "agree_policy", Registration.waiting_for_agreement)
async def process_agreement(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🎂 Укажите ваш возраст (от 12 до 30):")
    await state.set_state(Registration.waiting_for_age)
    await callback.answer()

@dp.message(Registration.waiting_for_age)
async def process_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or not (12 <= int(message.text) <= 30):
        await message.answer("⚠️ Введите число от 12 до 30:")
        return
    await state.update_data(age=int(message.text))
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="👨 Мужчина"), KeyboardButton(text="👩 Женщина")]
    ], resize_keyboard=True, one_time_keyboard=True)
    await message.answer("⚧ Выберите ваш пол:", reply_markup=kb)
    await state.set_state(Registration.waiting_for_gender)

@dp.message(Registration.waiting_for_gender, F.text.in_(["👨 Мужчина", "👩 Женщина"]))
async def process_gender(message: types.Message, state: FSMContext):
    gender = "male" if "Мужчина" in message.text else "female"
    await state.update_data(gender=gender)
    await message.answer("📸 Отправьте фото вашего лица:", reply_markup=types.ReplyKeyboardRemove())
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
    await message.answer("🎉 Регистрация успешно завершена! 🔥")
    await show_main_menu(message)

async def show_main_menu(message: types.Message):
    if not await check_subscription(message.from_user.id):
        clean_name = CHANNEL_USERNAME.replace("@", "").strip()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться на канал", url=f"https://t.me/{clean_name}")],
            [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")]
        ])
        await message.answer(f"🔒 Для доступа нужно подписаться на канал {CHANNEL_USERNAME}!", reply_markup=kb)
        return

    buttons = [
        [KeyboardButton(text="💎 ВИП"), KeyboardButton(text="🔥 Оценивать")],
        [KeyboardButton(text="👤 Моя анкета"), KeyboardButton(text="🔗 Рефералы")],
        [KeyboardButton(text="⚙️ Кого оценивать"), KeyboardButton(text="🏆 Топы")]
    ]
    if message.from_user.id == ADMIN_ID or (message.from_user.username and message.from_user.username.lower() == ADMIN_USERNAME.lower()):
        buttons.append([KeyboardButton(text="👑 Админка")])

    kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    await message.answer("⚡ Главное меню:", reply_markup=kb)

@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: types.CallbackQuery):
    if await check_subscription(callback.from_user.id):
        await callback.message.delete()
        await show_main_menu(callback.message)
    else:
        await callback.answer("⚠️ Вы всё еще не подписались!", show_alert=True)

@dp.message(F.text.in_(["💎 ВИП", "🔥 Оценивать", "👤 Моя анкета", "🔗 Рефералы", "⚙️ Кого оценивать", "🏆 Топы", "👑 Админка"]))
async def main_menu_router(message: types.Message, state: FSMContext):
    if not await check_subscription(message.from_user.id):
        await show_main_menu(message)
        return

    text = message.text
    if text == "👤 Моя анкета":
        await show_profile(message)
    elif text == "⚙️ Кого оценивать":
        await choose_target_gender(message)
    elif text == "🔗 Рефералы":
        await show_referral(message)
    elif text == "🔥 Оценивать":
        await start_rating(message)
    elif text == "🏆 Топы":
        await show_tops(message)
    elif text == "💎 ВИП":
        await show_vip_offers(message)
    elif text == "👑 Админка":
        await admin_panel(message)

async def get_user_calculated_rating(user_id: int, gender: str):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT score FROM ratings WHERE target_user_id = $1", user_id)
        if not rows:
            return "Нет оценок", 0
        scores = [r['score'] for r in rows]
        most_common_score, max_count = Counter(scores).most_common(1)[0]
        return most_common_score, len(scores)

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

        is_vip = await is_user_vip(user_id)
        if not is_vip and daily_count >= 30:
            await message.answer("❌ Дневной лимит (30 оценок) исчерпан! Приобретите 💎 ВИП для безлимита!")
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
            await message.answer("😴 Анкет для оценки пока нет, зайдите позже!")
            return

        rating, count = await get_user_calculated_rating(target['user_id'], target['gender'])
        name = target['username'] if target['username'] else f"User{target['user_id']}"
        caption = (
            f"🕸 **{name}, {target['age']}** · Средний тир: **{rating}**\n"
            f"👥 **Анкету оценили: {count}**\n\n"
            f"**Какой тир поставишь?**"
        )

        scores = MALE_SCORES if target['gender'] == 'male' else FEMALE_SCORES
        keyboard = []
        for i in range(0, len(scores), 2):
            row = [InlineKeyboardButton(text=f"🕸 {scores[i]}", callback_data=f"rate_{target['user_id']}_{scores[i]}")]
            if i + 1 < len(scores):
                row.append(InlineKeyboardButton(text=f"🕸 {scores[i+1]}", callback_data=f"rate_{target['user_id']}_{scores[i+1]}"))
            keyboard.append(row)

        if target['username']:
            chat_url = f"https://t.me/{target['username']}"
        else:
            chat_url = f"tg://openmessage?user_id={target['user_id']}"

        keyboard.append([InlineKeyboardButton(text="💬 Хочу пообщаться", url=chat_url)])
        keyboard.append([InlineKeyboardButton(text="🚩 Жалоба", callback_data=f"report_{target['user_id']}")])

        await message.answer_photo(
            photo=target['photo_id'],
            caption=caption,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="Markdown"
        )

@dp.callback_query(F.data.startswith("rate_"))
async def process_rate_callback(callback: types.CallbackQuery):
    _, target_id, score = callback.data.split("_")
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO ratings (target_user_id, voter_user_id, score) VALUES ($1, $2, $3)", int(target_id), callback.from_user.id, score)
        await conn.execute("UPDATE users SET daily_ratings_count = daily_ratings_count + 1 WHERE user_id = $1", callback.from_user.id)
    await callback.message.delete()
    await callback.answer("✅ Оценка принята!")
    await start_rating(callback.message)

@dp.callback_query(F.data.startswith("report_"))
async def process_report(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[1])
    target_user = await get_db_user(target_id)
    
    if not target_user:
        await callback.answer("Ошибка!", show_alert=True)
        return

    if ADMIN_ID != 0:
        report_text = (
            f"🚨 **НОВАЯ ЖАЛОБА!** 🚨\n"
            f"👤 Нарушитель: @{target_user['username']} (`{target_id}`)\n"
            f"👨‍⚖️ Отправитель: @{callback.from_user.username} (`{callback.from_user.id}`)"
        )
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑 Удалить анкету", callback_data=f"adm_del_{target_id}"),
                InlineKeyboardButton(text="✅ Пропустить", callback_data="adm_skip")
            ]
        ])
        try:
            await bot.send_photo(
                chat_id=ADMIN_ID,
                photo=target_user['photo_id'],
                caption=report_text,
                reply_markup=admin_kb,
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Ошибка отправки репорта: {e}")

    await callback.answer("🚩 Жалоба отправлена администратору!", show_alert=True)

@dp.callback_query(F.data.startswith("adm_del_"))
async def adm_del_start(callback: types.CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split("_")[2])
    await state.update_data(delete_target_id=target_id)
    await state.set_state(AdminState.waiting_for_delete_reason)
    await callback.message.answer("✏️ Введите причину удаления анкеты:")
    await callback.answer()

@dp.message(AdminState.waiting_for_delete_reason)
async def adm_del_finish(message: types.Message, state: FSMContext):
    reason = message.text
    data = await state.get_data()
    target_id = data.get("delete_target_id")

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET photo_id = NULL WHERE user_id = $1", target_id)

    try:
        await bot.send_message(chat_id=target_id, text=f"⚠️ Ваша анкета была удалена администратором.\n📝 **Причина:** {reason}")
    except Exception:
        pass

    await message.answer("✅ Анкета успешна удалена!")
    await state.clear()

@dp.callback_query(F.data == "adm_skip")
async def adm_skip(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer("Пропущено")

async def show_profile(message: types.Message):
    user = await get_db_user(message.from_user.id)
    rating, count = await get_user_calculated_rating(user['user_id'], user['gender'])
    is_vip = await is_user_vip(message.from_user.id)
    
    if message.from_user.id == ADMIN_ID:
        vip_status = "👑 Вечный ВИП (Админ)"
    elif is_vip:
        vip_status = f"✨ До {user['vip_until'].strftime('%d.%m.%Y')}"
    else:
        vip_status = "❌ Нет"

    text = (
        f"👤 **Ваша анкета:**\n\n"
        f"🎂 Возраст: {user['age']}\n"
        f"⚧ Пол: {'Мужской 👨' if user['gender'] == 'male' else 'Женский 👩'}\n"
        f"⭐ Оценка: **{rating}** (голосов: {count})\n"
        f"💎 ВИП-статус: **{vip_status}**"
    )
    await message.answer_photo(photo=user['photo_id'], caption=text, parse_mode="Markdown")

async def choose_target_gender(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨 Мужчин", callback_data="set_target_male")],
        [InlineKeyboardButton(text="👩 Женщин", callback_data="set_target_female")],
        [InlineKeyboardButton(text="🌈 Всех", callback_data="set_target_all")]
    ])
    await message.answer("⚙️ Кого вы хотите оценивать?", reply_markup=kb)

@dp.callback_query(F.data.startswith("set_target_"))
async def set_target_callback(callback: types.CallbackQuery):
    target = callback.data.replace("set_target_", "")
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET target_gender = $1 WHERE user_id = $2", target, callback.from_user.id)
    await callback.answer("✅ Сохранено!")
    await callback.message.edit_text("⚙️ Настройки успешно обновлены!")

async def show_referral(message: types.Message):
    bot_info = await bot.get_me()
    await message.answer(f"🔗 Ваша реферальная ссылка:\n`https://t.me/{bot_info.username}?start=ref_{message.from_user.id}`", parse_mode="Markdown")

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
        [InlineKeyboardButton(text="⭐ 10 дней — 100 Stars", callback_data="buy_vip_10")],
        [InlineKeyboardButton(text="⭐ 30 дней — 300 Stars", callback_data="buy_vip_30")]
    ])
    await message.answer("💎 Выберите вариант покупки **ВИП-статуса**:", reply_markup=kb)

@dp.callback_query(F.data.startswith("buy_vip_"))
async def process_vip_buy(callback: types.CallbackQuery):
    days = int(callback.data.split("_")[2])
    stars = {1: 10, 3: 30, 10: 100, 30: 300}[days]
    await bot.send_invoice(
        chat_id=callback.from_user.id, title=f"💎 ВИП на {days} дн.",
        description=f"Безлимит оценок на {days} дней", payload=f"vip_{days}",
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

# ================= 👑 АДМИН ПАНЕЛЬ 👑 =================
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID and message.from_user.username != ADMIN_USERNAME:
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Выдать ВИП по @username", callback_data="adm_give_vip")]
    ])
    await message.answer("👑 **Панель администратора:**", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "adm_give_vip")
async def adm_give_vip_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("✏️ Введите @username пользователя (без знака @):")
    await state.set_state(AdminState.waiting_for_username)
    await callback.answer()

@dp.message(AdminState.waiting_for_username)
async def adm_get_username(message: types.Message, state: FSMContext):
    username = message.text.replace("@", "").strip()
    await state.update_data(target_username=username)
    await message.answer("⏳ На сколько дней выдать ВИП? (введите число):")
    await state.set_state(AdminState.waiting_for_days)

@dp.message(AdminState.waiting_for_days)
async def adm_get_days(message: types.Message, state: FSMContext):
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
    
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 10000)
    await site.start()

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
