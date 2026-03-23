import logging
import os
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from dotenv import load_dotenv
from src.bot_handler import BotHandler

load_dotenv()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_handler = BotHandler()


def _confirm_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm:{pending_id}"),
        InlineKeyboardButton("✏️ Alterar", callback_data=f"change:{pending_id}"),
    ]])


def _category_keyboard(pending_id: str, categories: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(label, callback_data=f"cat:{pending_id}:{i}")]
        for i, (label, _) in enumerate(categories)
    ]
    return InlineKeyboardMarkup(buttons)


async def _reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    text = update.message.text or ""
    logger.info(f"[{chat_id}] {text[:60]}")
    try:
        reply, use_markdown, pending = _handler.handle(text, chat_id=chat_id)
        parse_mode = "Markdown" if use_markdown else None

        if pending is not None:
            pending_id = uuid.uuid4().hex[:12]
            keyboard = _confirm_keyboard(pending_id)
            await update.message.reply_text(reply, reply_markup=keyboard, parse_mode=parse_mode)
            _handler.register_pending(pending_id, pending, chat_id=chat_id)
        else:
            await update.message.reply_text(reply, parse_mode=parse_mode)

    except Exception as e:
        logger.error(f"Error handling message from {chat_id}: {e}")
        await update.message.reply_text("⚠️ Erro interno. Tente novamente em instantes.")


async def _callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()  # remove spinner

    if not query.data:
        return

    parts = query.data.split(":")
    action = parts[0]

    if action == "confirm":
        pending_id = parts[1]
        result = _handler.confirm_transaction(pending_id)
        if result is None:
            await query.edit_message_text("⚠️ Confirmação expirada. Envie a transação novamente.")
        else:
            await query.edit_message_text(result)

    elif action == "change":
        pending_id = parts[1]
        pending = _handler.get_pending(pending_id)
        if pending is None:
            await query.edit_message_text("⚠️ Confirmação expirada. Envie a transação novamente.")
            return
        categories = _handler.categorizer.categories_for(pending.intent)
        keyboard = _category_keyboard(pending_id, categories)
        await query.edit_message_reply_markup(keyboard)

    elif action == "cat":
        pending_id = parts[1]
        idx = int(parts[2])
        result = _handler.confirm_transaction(pending_id, category_index=idx)
        if result is None:
            await query.edit_message_text("⚠️ Confirmação expirada. Envie a transação novamente.")
        else:
            await query.edit_message_text(result)


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()

    for cmd in ["start", "ajuda", "ativar", "desativar", "pendentes"]:
        app.add_handler(CommandHandler(cmd, _reply))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _reply))
    app.add_handler(CallbackQueryHandler(_callback))

    logger.info("Bot started. Polling for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
