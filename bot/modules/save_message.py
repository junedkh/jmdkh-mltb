from pyrogram.errors import UserIsBlocked
from pyrogram.filters import regex
from pyrogram.handlers import CallbackQueryHandler

from bot import LOGGER, bot
from bot.helper.ext_utils.bot_utils import new_task
from bot.helper.telegram_helper.button_build import ButtonMaker


@new_task
async def save_message(client, query):
    try:
        button = ButtonMaker()
        button_exist = False
        for _markup in query.message.reply_markup.inline_keyboard[0]:
            if isinstance(_markup, list):
                for another_markup in _markup:
                    if not another_markup.callback_data:
                        button_exist = True
                        button.ubutton(another_markup.text, another_markup.url)
            elif not _markup.callback_data:
                button_exist = True
                button.ubutton(_markup.text, _markup.url)
        reply_markup = button.build_menu(2) if button_exist else None
        await query.message.copy(query.from_user.id, reply_markup=reply_markup, disable_notification=False)
        await query.answer('Saved Successfully', show_alert=True)
    except UserIsBlocked:
        await query.answer(f'Start @{client.me.username} in private and try again', show_alert=True)
    except Exception as e:
        LOGGER.error(e)
        await query.answer("Something went wrong!", show_alert=True)


bot.add_handler(CallbackQueryHandler(save_message, filters=regex("^save")))