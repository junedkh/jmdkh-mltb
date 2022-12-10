from time import sleep, time

from telegram.ext import CallbackQueryHandler, CommandHandler

from bot import (CATEGORY_NAMES, btn_listener, dispatcher, download_dict,
                 download_dict_lock)
from bot.helper.ext_utils.bot_utils import (MirrorStatus, get_category_btns,
                                            getDownloadByGid, new_thread)
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.message_utils import (editMessage, sendMarkup,
                                                      sendMessage)


def change_category(update, context):
    user_id = update.message.from_user.id
    if len(context.args) == 1:
        gid = context.args[0]
        dl = getDownloadByGid(gid)
        if not dl:
            sendMessage(f"GID: <code>{gid}</code> Not Found.", context.bot, update.message)
            return
    elif update.message.reply_to_message:
        mirror_message = update.message.reply_to_message
        with download_dict_lock:
            if mirror_message.message_id in download_dict:
                dl = download_dict[mirror_message.message_id]
            else:
                dl = None
        if not dl:
            sendMessage("This is not an active task!", context.bot, update.message)
            return
    elif len(context.args) == 0:
        msg = "Reply to an active /{cmd} which was used to start the download or add gid along with {cmd}\n\n" \
            "This command mainly for change category incase you decided to change category from already added donwload. " \
            "But you can always use /{mir} with to select category before download start."
        sendMessage(msg.format_map({'cmd': BotCommands.CategorySelect,'mir': BotCommands.MirrorCommand[0]}), context.bot, update.message)
        return

    if not CustomFilters.owner_query(user_id) and dl.message.from_user.id != user_id:
        sendMessage("This task is not for you!", context.bot, update.message)
        return
    if dl.status() not in [MirrorStatus.STATUS_DOWNLOADING, MirrorStatus.STATUS_PAUSED, MirrorStatus.STATUS_WAITING]:
        sendMessage(f'Task should be on {MirrorStatus.STATUS_DOWNLOADING} or {MirrorStatus.STATUS_PAUSED} or {MirrorStatus.STATUS_WAITING}', context.bot, update.message)
        return
    listener = dl.listener() if dl and hasattr(dl, 'listener') else None
    if listener and len(CATEGORY_NAMES) > 1 and not listener.isLeech:
        msg_id = update.message.message_id
        time_out = 30
        btn_listener[msg_id] = [dl.gid(), time_out, time(), listener, listener.c_index]
        text, btns = get_category_btns('change', time_out, msg_id, listener.c_index)
        engine = sendMarkup(text, context.bot, update.message, btns)
        _auto_select(engine, msg_id, time_out)
    else:
        sendMessage("Can not change Category for this task!", context.bot, update.message)

@new_thread
def _auto_select(msg, msg_id, time_out):
    sleep(time_out)
    try:
        info = btn_listener[msg_id]
        del btn_listener[msg_id]
        listener = info[3]
        mode = f'Drive {CATEGORY_NAMES[listener.c_index]}'
        if listener.isLeech:
            mode = 'Leech'
        if listener.isZip:
            mode += ' as Zip'
        elif listener.extract:
            mode += ' as Unzip'
        listener.mode = mode
        editMessage(f"Timed out! Task has been set.\n\n<b>Upload</b>: {mode}", msg)
    except:
        pass

@new_thread
def confirm_category(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    message = query.message
    data = query.data
    data = data.split()
    msg_id = int(data[2])
    try:
        categoryInfo = btn_listener[msg_id]
    except KeyError:
        return editMessage('<b>Old Task</b>', message)
    listener = categoryInfo[3]
    if user_id != listener.message.from_user.id and not CustomFilters.owner_query(user_id):
        query.answer("This task is not for you!", show_alert=True)
    elif data[1] == 'scat':
        c_index = int(data[3])
        if listener.c_index == c_index:
            return query.answer(f"{CATEGORY_NAMES[c_index]} is Selected Already", show_alert=True)
        query.answer()
        listener.c_index = c_index
    elif data[1] == 'cancel':
        query.answer()
        listener.c_index = categoryInfo[4]
        mode = f'Drive {CATEGORY_NAMES[listener.c_index]}'
        if listener.isLeech:
            mode = 'Telegram'
        if listener.isZip:
            mode += ' as Zip'
        elif listener.extract:
            mode += ' as Unzip'
        listener.mode = mode
        del btn_listener[msg_id]
        return editMessage("<b>Has been cancelled</b>", message)
    elif data[1] == 'done':
        query.answer()
        del btn_listener[msg_id]
        mode = f'Drive {CATEGORY_NAMES[listener.c_index]}'
        if listener.isLeech:
            mode = 'Telegram'
        if listener.isZip:
            mode += ' as Zip'
        elif listener.extract:
            mode += ' as Unzip'
        listener.mode = mode
        return editMessage(f"Task updated.\n\n<b>Upload</b>: {mode}", message)
    time_out = categoryInfo[1] - (time() - categoryInfo[2])
    text, btns = get_category_btns('change', time_out, msg_id, c_index)
    editMessage(text, message, btns)

confirm_category_handler = CallbackQueryHandler(confirm_category, pattern="change", run_async=True)

change_category_handler = CommandHandler(BotCommands.CategorySelect, change_category,
                        filters=(CustomFilters.authorized_chat | CustomFilters.authorized_user), run_async=True)
dispatcher.add_handler(confirm_category_handler)
dispatcher.add_handler(change_category_handler)
