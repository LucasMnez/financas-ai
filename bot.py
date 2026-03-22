import logging
import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
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


async def _reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    text = update.message.text or ""
    logger.info(f"[{chat_id}] {text[:60]}")
    try:
        reply = _handler.handle(text, chat_id=chat_id)
        await update.message.reply_text(reply, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error handling message from {chat_id}: {e}")
        await update.message.reply_text(
            "⚠️ Erro interno. Tente novamente em instantes.",
        )


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()

    for cmd in ["start", "ajuda", "ativar", "desativar", "pendentes"]:
        app.add_handler(CommandHandler(cmd, _reply))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _reply))

    logger.info("Bot started. Polling for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
