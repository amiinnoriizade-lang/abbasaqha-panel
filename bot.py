import os
import uuid
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_TG_ID = os.getenv("ADMIN_TG_ID", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/abbasagha.db")
PANEL_PORT = os.getenv("PANEL_PORT", "8080")
SERVER_IP = os.getenv("SERVER_IP", "127.0.0.1")

engine = create_async_engine(DATABASE_URL)

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛒 خرید اشتراک VPN"), KeyboardButton(text="🎁 دریافت تست رایگان")],
        [KeyboardButton(text="📊 سرویس‌های من"), KeyboardButton(text="💳 شارژ کیف پول / پرداخت")]
    ],
    resize_keyboard=True
)

async def create_vpn_account(username: str, protocol: str, gb: float, days: int) -> str:
    sub_token = uuid.uuid4().hex[:16]
    uid = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(
            text("""INSERT INTO vpn_users (username, uuid_str, sub_token, protocol, outbound_tag, total_gb, used_up_bytes, used_down_bytes, live_up_bps, live_down_bps, is_online, expire_days, created_at, status, owner_username, l2tp_password)
                    VALUES (:u, :uid, :st, :p, 'direct', :gb, 0, 0, 0, 0, 1, :days, datetime('now'), 'active', 'bot', 'abbas123')"""),
            {"u": username, "uid": uid, "st": sub_token, "p": protocol, "gb": gb, "days": days}
        )
    return f"http://{SERVER_IP}:{PANEL_PORT}/sub/{sub_token}"

async def main():
    if not BOT_TOKEN:
        while True:
            await asyncio.sleep(60)
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def cmd_start(message: types.Message):
        await message.answer("سلام! به ربات فروش خودکار **عباس آقا** خوش آمدید 🌹", reply_markup=main_kb)

    @dp.message(F.text == "🎁 دریافت تست رایگان")
    async def free_test(message: types.Message):
        uname = f"test_{message.from_user.id}"
        try:
            sub_url = await create_vpn_account(uname, "v2ray", 1.0, 1)
            await message.answer(f"✅ اکانت تست ۱ گیگابایتی ساخته شد:\n`{sub_url}`", parse_mode="Markdown")
        except Exception:
            await message.answer("⚠️ قبلاً تست دریافت کرده‌اید.")

    @dp.message(F.text == "🛒 خرید اشتراک VPN")
    async def buy_menu(message: types.Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 ۳۰ گیگ - ۱ ماهه (۹۵,۰۰۰ تومان)", callback_data="plan_30_30_95000")],
            [InlineKeyboardButton(text="💎 ۶۰ گیگ - ۱ ماهه (۱۶۵,۰۰۰ تومان)", callback_data="plan_60_30_165000")]
        ])
        await message.answer("بسته مورد نظر را انتخاب کنید:", reply_markup=kb)

    @dp.callback_query(F.data.startswith("plan_"))
    async def select_gateway(call: types.CallbackQuery):
        _, gb, days, price = call.data.split("_")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 کارت به کارت", callback_data=f"pay_card_{gb}_{days}_{price}")],
            [InlineKeyboardButton(text="🟡 درگاه زرین‌پال", callback_data=f"pay_zarinpal_{gb}_{days}_{price}")],
            [InlineKeyboardButton(text="🔵 درگاه آبان‌گیت", callback_data=f"pay_abangate_{gb}_{days}_{price}")],
            [InlineKeyboardButton(text="🪙 درگاه ارز دیجیتال (USDT)", callback_data=f"pay_crypto_{gb}_{days}_{price}")]
        ])
        await call.message.edit_text("روش پرداخت را انتخاب کنید:", reply_markup=kb)

    @dp.callback_query(F.data.startswith("pay_"))
    async def process_payment(call: types.CallbackQuery):
        _, gw, gb, days, price = call.data.split("_")
        await call.message.edit_text(f"درگاه انتخابی: {gw.upper()} | مبلغ: {int(price):,} تومان\nپس از پرداخت، اکانت شما فعال می‌شود.")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
