#!/usr/bin/env python3
"""Telegram bot UI for fetching VLESS config from local FastAPI.

Features:
- /start with "Get My Config" button
- Fetches config from local API: /api/v1/get-config?uuid=...
- Returns VLESS link in a code block
- Optional QR code image output for quick mobile scanning
"""

from __future__ import annotations

import asyncio
import html
import io
import os
from dataclasses import dataclass
from typing import Dict, Optional
from uuid import UUID

import qrcode
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
FASTAPI_BASE_URL = os.getenv("FASTAPI_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_USER_UUID = os.getenv("DEFAULT_USER_UUID", "")
ENABLE_QR = os.getenv("ENABLE_QR", "true").lower() in {"1", "true", "yes", "on"}


@dataclass
class ConfigResponse:
    vercel_domain: str
    full_vless_link: str


USER_UUID_MAP: Dict[int, str] = {}


def _normalize_uuid(value: str) -> str:
    parsed = UUID(value)
    return str(parsed)


def _resolve_user_uuid(user_id: int) -> Optional[str]:
    if user_id in USER_UUID_MAP:
        return USER_UUID_MAP[user_id]
    if DEFAULT_USER_UUID:
        return DEFAULT_USER_UUID
    return None


def _fetch_config_sync(user_uuid: str) -> ConfigResponse:
    url = f"{FASTAPI_BASE_URL.rstrip('/')}/api/v1/get-config"
    response = requests.get(url, params={"uuid": user_uuid}, timeout=12)
    response.raise_for_status()

    payload = response.json()
    if payload.get("status") != "success":
        raise RuntimeError(f"Unexpected API status: {payload}")

    full_vless_link = payload.get("full_vless_link")
    vercel_domain = payload.get("vercel_domain")
    if not full_vless_link or not vercel_domain:
        raise RuntimeError(f"Incomplete API response: {payload}")

    return ConfigResponse(vercel_domain=vercel_domain, full_vless_link=full_vless_link)


async def _fetch_config(user_uuid: str) -> ConfigResponse:
    return await asyncio.to_thread(_fetch_config_sync, user_uuid)


def _render_qr_bytes(data: str) -> io.BytesIO:
    image = qrcode.make(data)
    binary = io.BytesIO()
    image.save(binary, format="PNG")
    binary.seek(0)
    return binary


def _config_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Get My Config", callback_data="get_config")]]
    )


async def _send_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return

    user_uuid = _resolve_user_uuid(user.id)
    if not user_uuid:
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                "UUID not configured for your account.\n"
                "Use /setuuid <uuid> or set DEFAULT_USER_UUID on the server."
            ),
        )
        return

    try:
        config = await _fetch_config(user_uuid)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        await context.bot.send_message(
            chat_id=chat.id,
            text=f"Failed to fetch config from API (HTTP {status}).",
        )
        return
    except Exception as exc:
        await context.bot.send_message(
            chat_id=chat.id,
            text=f"Failed to fetch config: {exc}",
        )
        return

    safe_link = html.escape(config.full_vless_link)
    message = (
        f"Domain: <b>{html.escape(config.vercel_domain)}</b>\n"
        f"UUID: <code>{html.escape(user_uuid)}</code>\n\n"
        f"<pre>{safe_link}</pre>"
    )
    await context.bot.send_message(chat_id=chat.id, text=message, parse_mode=ParseMode.HTML)

    if ENABLE_QR:
        qr_bytes = await asyncio.to_thread(_render_qr_bytes, config.full_vless_link)
        await context.bot.send_photo(
            chat_id=chat.id,
            photo=qr_bytes,
            caption="Scan this QR code from your client device.",
        )


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if not chat:
        return

    await context.bot.send_message(
        chat_id=chat.id,
        text=(
            "Welcome. Tap the button below to fetch your VLESS config.\n"
            "If needed, set your UUID with /setuuid <uuid>."
        ),
        reply_markup=_config_keyboard(),
    )


async def set_uuid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return

    if not context.args:
        await context.bot.send_message(chat_id=chat.id, text="Usage: /setuuid <uuid>")
        return

    candidate = context.args[0].strip()
    try:
        normalized = _normalize_uuid(candidate)
    except ValueError:
        await context.bot.send_message(chat_id=chat.id, text="Invalid UUID format.")
        return

    USER_UUID_MAP[user.id] = normalized
    await context.bot.send_message(chat_id=chat.id, text="UUID saved. Tap Get My Config.")


async def get_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_config(update, context)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()
    if query.data == "get_config":
        await _send_config(update, context)


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("setuuid", set_uuid_handler))
    app.add_handler(CommandHandler("getconfig", get_config_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
