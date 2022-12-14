from telegram.ext import CallbackQueryHandler

from bot import btn_listener, dispatcher
from bot.helper.telegram_helper.message_utils import editMessage


def verifyAnno(update, context):
    query = update.callback_query
    message = query.message
    data = query.data
    data = data.split()
    msg_id = int(data[1])
    if msg_id in btn_listener:
        btn_listener[msg_id][1] = query.from_user.id
        btn_listener[msg_id][0] = False
        message.delete()
    else:
        editMessage('<b>Old Message</b>', message)

anno_handler = CallbackQueryHandler(verifyAnno, pattern="verify")
dispatcher.add_handler(anno_handler)