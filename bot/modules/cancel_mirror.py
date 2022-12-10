from re import findall as re_findall
from threading import Thread
from time import sleep

from telegram.ext import (CallbackQueryHandler, CommandHandler, Filters,
                          MessageHandler)

from bot import (CMD_PERFIX, botname, dispatcher, download_dict,
                 download_dict_lock)
from bot.helper.ext_utils.bot_utils import (MirrorStatus, getAllDownload,
                                            getDownloadByGid)
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.message_utils import (editMessage, sendMarkup,
                                                      sendMessage)


def cancel_mirror(update, context):
    user_id = update.message.from_user.id
    text = update.message.text
    if text:
        try:
            gid = re_findall(rf'\/cancel{CMD_PERFIX}_(\w*)', text)[0]
            dl = getDownloadByGid(gid)
            if not dl:
                sendMessage(f"GID: <code>{gid}</code> Not Found.", context.bot, update.message)
                return
        except:
            reply_to = update.message.reply_to_message
            if reply_to:
                with download_dict_lock:
                    dl = download_dict.get(reply_to.message_id)
                if not dl:
                    sendMessage("This is not an active task!", context.bot, update.message)
                    return
            else:
                msg = f"Reply to an active Command message which was used to start the download" \
                    f" or send <code>/{BotCommands.CancelMirror}_GID@{botname}</code> to cancel it!"
                sendMessage(msg, context.bot, update.message)
                return

    if not CustomFilters.owner_query(user_id) and dl.message.from_user.id != user_id:
        sendMessage("This task is not for you!", context.bot, update.message)
        return

    if dl.status() == MirrorStatus.STATUS_CONVERTING:
        sendMessage("Converting... Can't cancel this task!", context.bot, update.message)
        return

    dl.download().cancel_download()

cancel_listener = {}

def cancel_all(status, msg, listener_id):
    listener_info = cancel_listener[listener_id]
    user_id = listener_info[0]
    editMessage(f"Canceling tasks for {user_id or 'All'} in {status}", msg)
    gid = ''
    canceled = 0
    dls = getAllDownload(status, user_id, False)
    if dls:
        for dl in dls:
            try:
                if dl.gid() != gid:
                    gid = dl.gid()
                    dl.download().cancel_download()
                    canceled += 1
                    sleep(1)
            except:
                continue
            editMessage(f"Canceling tasks for {user_id or 'All'} in {status} canceled {canceled}/{len(dls)}", msg)
    sleep(1)
    editMessage(f"{canceled}/{len(dls)} Tasks has been cancel by {listener_info[3]}", msg)
    del cancel_listener[listener_id]

def cancell_all_buttons(update, context):
    with download_dict_lock:
        count = len(download_dict)
    if count == 0:
        sendMessage("No active tasks!", context.bot, update.message)
        return
    reply_to = update.message.reply_to_message
    sender_id = update.message.from_user.id
    forme = True
    if not CustomFilters.owner_query(sender_id):
        user_id = sender_id
    elif reply_to:
        user_id = reply_to.from_user.id
    elif len(context.args) == 0:
        user_id = sender_id
    elif context.args[0].lower() == 'all':
        forme = False
        user_id = sender_id
    elif context.args[0].isdigit():
        try:
            user_id = int(context.args[0])
        except:
            return sendMessage("Invalid Argument! Send Userid or reply", context.bot, update.message)
    if forme and not getAllDownload('all', user_id):
        return sendMessage(f"{user_id} Don't have any active task!", context.bot, update.message)
    if update.message.from_user.username:
        tag = f"@{update.message.from_user.username}"
    else:
        tag = update.message.from_user.mention_html(update.message.from_user.first_name)
    msg_id = update.message.message_id
    cancel_listener[msg_id] = [user_id, sender_id, False, tag, forme]
    buttons = ButtonMaker()
    buttons.sbutton("Downloading", f"cnall {MirrorStatus.STATUS_DOWNLOADING} {msg_id}")
    buttons.sbutton("Uploading", f"cnall {MirrorStatus.STATUS_UPLOADING} {msg_id}")
    buttons.sbutton("Seeding", f"cnall {MirrorStatus.STATUS_SEEDING} {msg_id}")
    buttons.sbutton("Cloning", f"cnall {MirrorStatus.STATUS_CLONING} {msg_id}")
    buttons.sbutton("Extracting", f"cnall {MirrorStatus.STATUS_EXTRACTING} {msg_id}")
    buttons.sbutton("Archiving", f"cnall {MirrorStatus.STATUS_ARCHIVING} {msg_id}")
    buttons.sbutton("Splitting", f"cnall {MirrorStatus.STATUS_SPLITTING} {msg_id}")
    buttons.sbutton("All", f"cnall all {msg_id}")
    buttons.sbutton("Close", f"cnall close {msg_id}")
    button = buttons.build_menu(2)
    bmgs = sendMarkup('Choose tasks to cancel. You have 30 Secounds only', context.bot, update.message, button)
    Thread(target=_auto_cancel, args=(bmgs, msg_id)).start()

def cancel_all_update(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    data = data.split(" ")
    message = query.message
    listener_id = int(data[-1])
    try:
        listener_info = cancel_listener[listener_id]
    except:
        return editMessage("This is an old message", message)
    if listener_info[1] != user_id:
        return query.answer(text="You are not allowed to do this!", show_alert=True)
    elif data[1] == 'close':
        query.answer()
        if not cancel_listener[listener_id][2]:
            editMessage("Cancellation Listener Closed.", message)
            del cancel_listener[listener_id]
    else:
        query.answer()
        if not listener_info[4] and CustomFilters.owner_query(listener_info[1]) and listener_info[1] == listener_info[0]:
            listener_info[0] = None
        if not getAllDownload(data[1], listener_info[0]):
            return query.answer(text=f"You don't have any active task in {data[1]}", show_alert=True)
        cancel_listener[listener_id][2] = True
        Thread(target=cancel_all, args=(data[1], message, listener_id)).start()

def _auto_cancel(msg, msg_id):
    sleep(30)
    try:
        if cancel_listener[msg_id][2]:
            editMessage('Timed out! but task will keep canceling', msg)
        else:
            del cancel_listener[msg_id]
            editMessage('Timed out!', msg)
    except:
        pass


cancel_mirror_handler = MessageHandler(((Filters.regex(rf'^\/cancel{CMD_PERFIX}_.*@{botname}$') | Filters.regex(rf'^\/cancel{CMD_PERFIX}@{botname}$')))
                                       &
                                       (CustomFilters.authorized_chat |
                                        CustomFilters.authorized_user),
                                       cancel_mirror,
                                       run_async=True)

p_cancel_mirror_handler = MessageHandler(((Filters.regex(rf'^\/cancel{CMD_PERFIX}_.*$') | Filters.regex(rf'^\/cancel{CMD_PERFIX}@{botname}$')) & Filters.chat_type.private)
                                       &
                                       (CustomFilters.authorized_chat |
                                        CustomFilters.authorized_user),
                                       cancel_mirror,
                                       run_async=True)

cancel_all_handler = CommandHandler(BotCommands.CancelAllCommand, cancell_all_buttons,
                                    filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)

cancel_all_buttons_handler = CallbackQueryHandler(cancel_all_update, pattern="cnall", run_async=True)

dispatcher.add_handler(cancel_all_handler)
dispatcher.add_handler(cancel_mirror_handler)
dispatcher.add_handler(p_cancel_mirror_handler)
dispatcher.add_handler(cancel_all_buttons_handler)
