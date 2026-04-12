"""One-time interactive login to create the Telethon session file.

Run this script once from the terminal:
    .venv/Scripts/python.exe scripts/telegram_login.py

It will prompt for the OTP code sent to your Telegram app.
After successful login, trdex_telegram.session is created in the project root
and subsequent runs will be fully automatic.
"""

import asyncio

from trdex.config import get_settings


async def main() -> None:
    from telethon import TelegramClient  # type: ignore[import-untyped]

    s = get_settings()
    print(f"Logging in as {s.telegram_phone} ...")
    client = TelegramClient("session/trdex_telegram", s.telegram_api_id, s.telegram_api_hash)
    await client.start(phone=s.telegram_phone)
    me = await client.get_me()
    print(f"Logged in as: {me.first_name} (@{me.username})")
    print("Session saved to trdex_telegram.session — future runs will be automatic.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
