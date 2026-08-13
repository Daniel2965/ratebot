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

async def check_admin(user: types.User) -> bool:
    global ADMIN_ID
    if user.username and user.username.lower() == ADMIN_USERNAME.lower():
        ADMIN_ID = user.id
        return True
    if ADMIN_ID != 0 and user.id == ADMIN_ID:
        return True
    return False

async def is_user_vip(user_id: int, username: str = None) -> bool:
    if username and username.lower() == ADMIN_USERNAME.lower():
        return True
    if ADMIN_ID != 0 and user_id == ADMIN_ID:
        return True
    
    user = await get_db_user(user_id)
    if not user:
        return False
    return bool(user['is_vip'] and user['vip_until'] and user['vip_until'] > datetime.now())

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
    await check_admin(message.from_user)

    user = await get_db_user(message.from_user.id)
    if user and user['photo_id']:
        await show_main_menu(message)
        return

    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].replace("ref_", ""))
            await state.update_data(referrer_id=referrer_id)
        except ValueError:
            pass

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
            SET username = EXCLUDED.username, age = EXCLUDED.age, gender = EXCLUDED.gender, photo_id = EXCLUDED.photo_id
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
        [KeyboardButton(text="⚙️ Кого оценивать"), KeyboardButton(text="🏆 Топы")],
        [KeyboardButton(text="🔄 Пересоздать анкету")]
    ]
    
    if await check_admin(message.from_user):
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

@dp.message(F.text)
async def main_menu_router(message: types.Message, state: FSMContext):
    text = message.text.lower().strip()
    
    if text.startswith("/"):
        if text == "/admin" and await check_admin(message.from_user):
            await admin_panel(message)
        return

    if not await check_subscription(message.from_user.id):
        await show_main_menu(message)
        return

    if "анкета" in text and "пересоздать" not in text:
        await show_profile(message)
    elif "пересоздать" in text:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, пересоздать", callback_data="reset_profile")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_reset")]
        ])
        await message.answer("⚠️ Вы уверены, что хотите пересоздать анкету? Ваша старая анкета и фото будут заменены.", reply_markup=kb)
    elif "кого" in text or "настройки" in text:
        await choose_target_gender(message)
    elif "реферал" in text or "ссылка" in text:
        await show_referral(message)
    elif "оценивать" in text or "оценка" in text:
        await start_rating(message)
    elif "топ" in text:
        await show_tops(message)
    elif "вип" in text or "vip" in text:
        await show_vip_offers(message)
    elif "админ" in text:
        if await check_admin(message.from_user):
            await admin_panel(message)

@dp.callback_query(F.data == "reset_profile")
async def process_reset_profile(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.message.answer("🎂 Укажите ваш возраст (от 12 до 30):", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(Registration.waiting_for_age)
    await callback.answer()

@dp.callback_query(F.data == "cancel_reset")
async def process_cancel_reset(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer("Действие отменено.")

async def get_user_calculated_rating(user_id: int, gender: str):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT score FROM ratings WHERE target_user_id = $1", user_id)
        if not rows:
            return "Нет оценок", 0
        scores = [r['score'] for r in rows]
        most_common_score, _ = Counter(scores).most_common(1)[0]
        return most_common_score, len(scores)

async def show_specific_profile(chat_id: int, target_user_id: int):
    target = await get_db_user(target_user_id)
    if not target or not target['photo_id']:
        await bot.send_message(chat_id, "⚠️ Пользователь не найден или заблокирован.")
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

    await bot.send_photo(
        chat_id=chat_id,
        photo=target['photo_id'],
        caption=caption,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="Markdown"
    )

async def start_rating(message: types.Message):
    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if not user:
            await message.answer("⚠️ Профиль не найден. Попробуйте ввести /start")
            return

        today = date.today()
        if user['last_rating_date'] != today:
            await conn.execute("UPDATE users SET daily_ratings_count = 0, last_rating_date = $1 WHERE user_id = $2", today, user_id)
            daily_count = 0
        else:
            daily_count = user['daily_ratings_count']

        is_vip = await is_user_vip(user_id, message.from_user.username)
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

        await show_specific_profile(message.chat.id, target['user_id'])

@dp.callback_query(F.data.startswith("rate_"))
async def process_rate_callback(callback: types.CallbackQuery):
    _, target_id_str, score = callback.data.split("_")
    target_id = int(target_id_str)
    voter_id = callback.from_user.id
    
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO ratings (target_user_id, voter_user_id, score) VALUES ($1, $2, $3)", target_id, voter_id, score)
        await conn.execute("UPDATE users SET daily_ratings_count = daily_ratings_count + 1 WHERE user_id = $1", voter_id)
        
        count_row = await conn.fetchrow("SELECT COUNT(*) FROM ratings WHERE target_user_id = $1", target_id)
        total_ratings = count_row['count'] if count_row else 1

    notify_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Оценить в ответ", callback_data=f"backrate_{voter_id}"),
            InlineKeyboardButton(text="👁 Показать оценку", callback_data=f"showscore_{voter_id}_{score}")
        ]
    ])

    try:
        await bot.send_message(
            chat_id=target_id,
            text=f"📨 **Тебя оценили!** Всего анкету оценили **{total_ratings}** человек.",
            reply_markup=notify_kb,
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Не удалось отправить уведомление пользователю {target_id}: {e}")

    await callback.message.delete()
    await callback.answer("✅ Оценка принята!")
    await start_rating(callback.message)

@dp.callback_query(F.data.startswith("backrate_"))
async def process_backrate(callback: types.CallbackQuery):
    target_voter_id = int(callback.data.split("_")[1])
    await callback.answer()
    await show_specific_profile(callback.message.chat.id, target_voter_id)

@dp.callback_query(F.data.startswith("showscore_"))
async def process_showscore(callback: types.CallbackQuery):
    _, voter_id_str, score = callback.data.split("_")
    await callback.answer(f"⭐ Тебе поставили оценку: {score}", show_alert=True)

@dp.callback_query(F.data.startswith("report_"))
async def process_report(callback: types.CallbackQuery):
    target_id = int(callback.data.split("_")[1])
    target_user = await get_db_user(target_id)
    
    if not target_user:
        await callback.answer("Ошибка!", show_alert=True)
        return

    if ADMIN_ID != 0:
        target_uname = f"@{target_user['username']}" if target_user['username'] else "без_юзернейма"
        voter_uname = f"@{callback.from_user.username}" if callback.from_user.username else "без_юзернейма"
        report_text = (
            f"🚨 **НОВАЯ ЖАЛОБА!** 🚨\n"
            f"👤 Нарушитель: {target_uname} (`{target_id}`)\n"
            f"👨‍⚖️ Отправитель: {voter_uname} (`{callback.from_user.id}`)"
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

    await message.answer("✅ Анкета успешно удалена!")
    await state.clear()

@dp.callback_query(F.data == "adm_skip")
async def adm_skip(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer("Пропущено")

async def show_profile(message: types.Message):
    user = await get_db_user(message.from_user.id)
    if not user:
        await message.answer("⚠️ Ваш профиль не найден. Введите /start")
        return

    rating, count = await get_user_calculated_rating(user['user_id'], user['gender'])
    is_vip = await is_user_vip(message.from_user.id, message.from_user.username)
    
    if await check_admin(message.from_user):
        vip_status = "👑 Вечный ВИП (Админ)"
    elif is_vip:
        if user['vip_until'].year > 2090:
            vip_status = "♾ Навсегда"
        else:
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
        [InlineKeyboardButton(text="⭐ 7 дней — 50 Stars", callback_data="buy_vip_7")],
        [InlineKeyboardButton(text="⭐ 30 дней — 100 Stars", callback_data="buy_vip_30")],
        [InlineKeyboardButton(text="💎 Навсегда — 200 Stars", callback_data="buy_vip_36500")]
    ])
    await message.answer("💎 Выберите вариант покупки **ВИП-статуса**:", reply_markup=kb)

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
    await message.answer("🎉 ВИП успешно активирован!")

# ================= 👑 АДМИН ПАНЕЛЬ 👑 =================
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if not await check_admin(message.from_user):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="adm_users_1")],
        [InlineKeyboardButton(text="🎁 Выдать ВИП по @username", callback_data="adm_give_vip")]
    ])
    await message.answer("👑 **Панель администратора:**", reply_markup=kb, parse_mode="Markdown")

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

    keyboard = []
    if nav_buttons:
        keyboard.append(nav_buttons)

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
    
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 10000)
    await site.start()

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
  
