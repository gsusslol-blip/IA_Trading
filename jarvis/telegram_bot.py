"""Telegram voice/text channel (polling inside runtime — street + full Brain)."""

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
from jarvis.remote_bridge import handle_remote_text, is_authorized_chat, remote_username
from jarvis.stt import transcribe_audio
from jarvis.tts import speak_to_file


def build_telegram_app(settings: Settings, brain: Brain) -> Application:
    application = Application.builder().token(settings.telegram_bot_token).build()
    brain.actions.client_surface = "telegram"

    async def ensure_owner(update: Update) -> bool:
        chat = update.effective_chat
        chat_id = chat.id if chat is not None else None
        if is_authorized_chat(chat_id, settings):
            return True
        print(f"[ALERTA REMOTA] Intento de acceso no autorizado desde ID: {chat_id}")
        if update.message:
            await update.message.reply_text("Acceso restringido.")
        return False

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await ensure_owner(update) or not update.message:
            return
        name = settings.assistant_name
        who = remote_username(settings)
        if update.effective_chat is not None:
            brain.bus.set_telegram_chat(update.effective_chat.id)
        await update.message.reply_text(
            f"{name}: canal persistente en línea ({who}). "
            "Escribime o mandame un audio.\n"
            "Atajos de calle: «anotá …», «recordame …», «qué recetas tengo».\n"
            "El resto lo procesa el cerebro local (client=telegram)."
        )

    async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await ensure_owner(update) or not update.message or not update.message.text:
            return
        if update.effective_chat is not None:
            brain.bus.set_telegram_chat(update.effective_chat.id)
        user_id = str(update.effective_user.id if update.effective_user else "telegram")
        text = update.message.text
        print(f"[REMOTO] Mensaje desde la calle: {text!r}")
        await update.message.chat.send_action("typing")
        answer = await asyncio.to_thread(
            handle_remote_text,
            text,
            brain=brain,
            settings=settings,
            session_id=f"tg:{user_id}",
        )
        await _send_answer(update, settings, answer)

    async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await ensure_owner(update) or not update.message:
            return
        voice = update.message.voice or update.message.audio
        if voice is None:
            return
        if not settings.has_stt:
            await update.message.reply_text(
                "Para audio necesito Faster-Whisper o GROQ/OPENAI. Mientras, escribime."
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
        user_id = str(update.effective_user.id if update.effective_user else "telegram")
        print(f"[REMOTO] Audio transcrito: {heard!r}")
        answer = await asyncio.to_thread(
            handle_remote_text,
            heard,
            brain=brain,
            settings=settings,
            session_id=f"tg:{user_id}",
        )
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
    body = header + (answer or "").strip()
    if not body:
        body = "Listo."
    # Street notes / recipe lists: text-only (faster, cheaper). Full Brain may TTS.
    skip_tts = heard is None and (
        body.startswith("Registrado en tu bitácora")
        or body.startswith("TUS RECETAS")
        or body.startswith("Todavía no hay recetas")
        or body.startswith("Decime qué anoto")
        or body.startswith("SYNC_ACK:")
        or body.startswith("SYNC_ERR:")
    )
    if skip_tts:
        await update.message.reply_text(body[:4000])
        return
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
