from telegram.ext import CallbackQueryHandler

from bot import btn_listener, dispatcher, LOGGER
from bot.helper.telegram_helper.message_utils import editMessage


def verifyAnno(update, context):
    query = update.callback_query
    message = query.message
    data = query.data.split()
    msg_id = int(data[2])
    if msg_id not in btn_listener:
        return editMessage('<b>Old Verification Message</b>', message)
    if data[1] == 'yes':
        user = query.from_user
        query.answer(f'Username: {user.username}\nYour userid : {user.id}', True)
        btn_listener[msg_id][1] = user.id
        btn_listener[msg_id][0] = False
        LOGGER.info(f'Verification Success by ({user.username}){user.id}')
        message.delete()
    else:
        query.answer()
        btn_listener[msg_id][0] = False
        editMessage('<b>Cancel Verification</b>', message)

anno_handler = CallbackQueryHandler(verifyAnno, pattern="verify")
dispatcher.add_handler(anno_handler)