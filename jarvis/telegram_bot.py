"""Telegram voice/text channel."""

from __future__ import annotations

import asyncio
from io import BytesIO

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from jarvis.brain import Brain
from jarvis.config import Settings
from jarvis.stt import transcribe_audio
from jarvis.tts import speak_to_file


def build_telegram_app(settings: Settings, brain: Brain) -> Application:
    application = Application.builder().token(settings.telegram_bot_token).build()

    async def ensure_owner(update: Update) -> bool:
        user = update.effective_user
        if settings.telegram_user_id is None or user is None:
            return True
        if user.id == settings.telegram_user_id:
            return True
        if update.message:
            await update.message.reply_text("Acceso restringido.")
        return False

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await ensure_owner(update) or not update.message:
            return
        name = settings.assistant_name
        if update.effective_chat is not None:
            brain.bus.set_telegram_chat(update.effective_chat.id)
        await update.message.reply_text(
            f"{name} en línea. Escribime o mandame un audio.\n"
            "Puedo buscar, abrir apps del PC, el navegador, mapas, un borrador de WhatsApp, "
            "archivos, captura, volumen, recordatorios. Mail y luces si están configurados."
        )

    async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await ensure_owner(update) or not update.message or not update.message.text:
            return
        user_id = str(update.effective_user.id if update.effective_user else "anon")
        await update.message.chat.send_action("typing")
        answer = await asyncio.to_thread(brain.reply, user_id, update.message.text)
        await _send_answer(update, settings, answer)

    async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await ensure_owner(update) or not update.message:
            return
        voice = update.message.voice or update.message.audio
        if voice is None:
            return
        if not settings.has_stt:
            await update.message.reply_text(
                "Para audio necesito GROQ_API_KEY u OPENAI_API_KEY. Mientras tanto, escribime."
            )
            return
        await update.message.chat.send_action("typing")
        telegram_file = await context.bot.get_file(voice.file_id)
        buffer = BytesIO()
        await telegram_file.download_to_memory(buffer)
        data = buffer.getvalue()
        filename = "voice.ogg" if update.message.voice else "voice.mp3"
        try:
            heard = await asyncio.to_thread(transcribe_audio, settings, data, filename)
        except Exception as exc:  # noqa: BLE001
            await update.message.reply_text(f"No pude transcribir el audio: {exc}")
            return
        if not heard:
            await update.message.reply_text("No entendí el audio. Probá de nuevo.")
            return
        user_id = str(update.effective_user.id if update.effective_user else "anon")
        answer = await asyncio.to_thread(brain.reply, user_id, heard)
        await _send_answer(update, settings, answer, heard=heard)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    return application


async def _send_answer(
    update: Update,
    settings: Settings,
    answer: str,
    heard: str | None = None,
) -> None:
    if not update.message:
        return
    header = f"Te escuché: {heard}\n\n" if heard else ""
    body = header + answer
    try:
        audio_path = await speak_to_file(settings, answer)
        caption = body[:1024]
        with audio_path.open("rb") as handle:
            await update.message.reply_audio(
                audio=handle,
                caption=caption,
                title=settings.assistant_name,
                performer=settings.assistant_name,
            )
        if len(body) > 1024:
            await update.message.reply_text(body[1024:4000])
    except Exception:
        await update.message.reply_text(body[:4000])
