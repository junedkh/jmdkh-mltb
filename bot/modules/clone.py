from random import SystemRandom
from string import ascii_letters, digits
from threading import Thread
from time import sleep, time

from telegram.ext import CallbackQueryHandler, CommandHandler

from bot import (CATEGORY_NAMES, DATABASE_URL, LOGGER, Interval, btn_listener,
                 config_dict, dispatcher, download_dict, download_dict_lock)
from bot.helper.ext_utils.bot_utils import (check_buttons, check_user_tasks,
                                            get_category_btns,
                                            get_readable_file_size,
                                            get_readable_time, is_gdrive_link,
                                            new_thread)
from bot.helper.ext_utils.db_handler import DbManger
from bot.helper.ext_utils.jmdkh_utils import extract_link
from bot.helper.mirror_utils.status_utils.clone_status import CloneStatus
from bot.helper.mirror_utils.upload_utils.gdriveTools import GoogleDriveHelper
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.message_utils import (chat_restrict,
                                                      delete_all_messages,
                                                      delete_links,
                                                      deleteMessage,
                                                      editMessage, forcesub,
                                                      message_filter,
                                                      sendDmMessage,
                                                      sendMarkup, sendMessage,
                                                      sendStatusMessage,
                                                      update_all_messages)


def _clone(message, bot):
    args = message.text.split()
    reply_to = message.reply_to_message
    link = ''
    multi = 0
    msg_id = message.message_id
    c_index = 0
    if len(args) > 1:
        link = args[1].strip()
        if link.strip().isdigit():
            multi = int(link)
            link = ''
        elif message.from_user.username:
            tag = f"@{message.from_user.username}"
        else:
            tag = message.from_user.mention_html(message.from_user.first_name)
    if reply_to:
        if len(link) == 0:
            link = reply_to.text.split(maxsplit=1)[0].strip()
        if reply_to.from_user.username:
            tag = f"@{reply_to.from_user.username}"
        else:
            tag = reply_to.from_user.mention_html(reply_to.from_user.first_name)
    if not is_gdrive_link(link) or (link.strip().isdigit() and multi == 0):
        msg_ = 'Send Gdrive link along with command or by replying to the link by command' \
            f'\n\n<b>Multi links only by replying to first link/file:</b>\n<code>/{BotCommands.CloneCommand}</code> 10(number of links/files)'
        delete_links(bot, message)
        return sendMessage(msg_, bot, message)
    if message_filter(bot,message, tag):
        return
    if DATABASE_URL and config_dict['STOP_DUPLICATE_TASKS']:
        raw_url = extract_link(link)
        exist = DbManger().check_download(raw_url)
        if exist:
            _msg = f'<b>Download is already added by {exist["tag"]}</b>\n\nCheck the download status in @{exist["botname"]}\n\n<b>Link</b>: <code>{exist["_id"]}</code>'
            delete_links(bot, message)
            return sendMessage(_msg, bot, message)
    if forcesub(bot,message, tag):
        return
    maxtask = config_dict['USER_MAX_TASKS']
    if maxtask and not CustomFilters.owner_query(message.from_user.id) and check_user_tasks(message.from_user.id, maxtask):
        return sendMessage(f"Tasks limit exceeded for {maxtask} tasks", bot, message)
    time_out = 30
    listner = [bot, message, c_index, time_out, time(), tag, link]
    if len(CATEGORY_NAMES) > 1:
        if checked:= check_buttons():
            return sendMessage(checked, bot, message)
        text, btns = get_category_btns('clone', time_out, msg_id, c_index)
        btn_listener[msg_id] = listner
        chat_restrict(message)
        engine = sendMarkup(text, bot, message, btns)
        _auto_start_dl(engine, msg_id, time_out)
    else:
        chat_restrict(message)
        start_clone(listner)
    if multi > 1:
        sleep(4)
        nextmsg = type('nextmsg', (object, ), {'chat_id': message.chat_id, 'message_id': message.reply_to_message.message_id + 1})
        cmsg = message.text.split()
        cmsg[1] = f"{multi - 1}"
        nextmsg = sendMessage(" ".join(cmsg), bot, nextmsg)
        nextmsg.from_user.id = message.from_user.id
        sleep(4)
        Thread(target=_clone, args=(nextmsg, bot)).start()

@new_thread
def _auto_start_dl(msg, msg_id, time_out):
    sleep(time_out)
    try:
        info = btn_listener[msg_id]
        del btn_listener[msg_id]
        editMessage("Timed out! Task has been started.", msg)
        start_clone(info)
    except:
        pass

@new_thread
def start_clone(listner):
    bot = listner[0]
    message = listner[1]
    c_index = listner[2]
    tag = listner[5]
    link = listner[6]
    if config_dict['ENABLE_DM'] and message.chat.type != 'private':
        dmMessage = sendDmMessage(link, bot, message)
        if not dmMessage:
            return
    else:
        dmMessage = None
    gd = GoogleDriveHelper(user_id=message.from_user.id)
    res, size, name, files = gd.helper(link)
    if res != "":
        delete_links(bot, message)
        return sendMessage(res, bot, message)
    if config_dict['STOP_DUPLICATE']:
        LOGGER.info('Checking File/Folder if already in Drive...')
        smsg, button = gd.drive_list(name, True, True)
        if smsg:
            msg = "File/Folder is already available in Drive.\nHere are the search results:"
            delete_links(bot, message)
            return sendMarkup(msg, bot, message, button)
    CLONE_LIMIT = config_dict['CLONE_LIMIT']
    if CLONE_LIMIT:
        limit = CLONE_LIMIT * 1024**3
        if size > limit:
            msg2 = f'Failed, Clone limit is {get_readable_file_size(limit)}.\nYour File/Folder size is {get_readable_file_size(size)}.'
            delete_links(bot, message)
            return sendMessage(msg2, bot, message)
    mode = f'Clone {CATEGORY_NAMES[c_index]}'
    delete_links(bot, message)
    if files <= 20:
        msg = sendMessage(f"Cloning: <code>{link}</code>", bot, message)
        result, buttons = gd.clone(link, c_index)
        deleteMessage(bot, msg)
    else:
        drive = GoogleDriveHelper(name, user_id=message.from_user.id)
        gid = ''.join(SystemRandom().choices(ascii_letters + digits, k=12))
        clone_status = CloneStatus(drive, size, message, gid, mode)
        with download_dict_lock:
            download_dict[message.message_id] = clone_status
        sendStatusMessage(message, bot)
        result, buttons = drive.clone(link, c_index)
        with download_dict_lock:
            del download_dict[message.message_id]
            count = len(download_dict)
        try:
            if count == 0:
                Interval[0].cancel()
                del Interval[0]
                delete_all_messages()
            else:
                update_all_messages()
        except IndexError:
            pass
    cc = f'\n\n<b>#cc</b>: {tag} | <b>Elapsed</b>: {get_readable_time(time() - message.date.timestamp())}\n\n<b>Upload</b>: {mode}'
    if buttons in ["cancelled", ""]:
        sendMessage(f"{tag} {result}", bot, message)
    else:
        if dmMessage:
            sendMarkup(f"{result + cc}", bot, dmMessage, buttons.build_menu(2))
            sendMessage(f"{result + cc}\n\n<b>Links has been sent in your DM.</b>", bot, message)
        else:
            if message.chat.type != 'private':
                buttons.sbutton("Save This Message", 'save', 'footer')
            sendMarkup(f"{result + cc}", bot, message, buttons.build_menu(2))
        LOGGER.info(f"Cloning Done: {name}")

@new_thread
def clone_confirm(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    message = query.message
    data = query.data
    data = data.split()
    msg_id = int(data[2])
    try:
        listnerInfo = btn_listener[msg_id]
    except KeyError:
        return editMessage('<b>Download has been cancelled or started already</b>', message)
    if user_id != listnerInfo[1].from_user.id:
        return query.answer("You are not the owner of this download", show_alert=True)
    elif data[1] == 'scat':
        c_index = int(data[3])
        if listnerInfo[2] == c_index:
            return query.answer(f"{CATEGORY_NAMES[c_index]} is Selected Already", show_alert=True)
        query.answer()
        listnerInfo[2] = c_index
    elif data[1] == 'cancel':
        query.answer()
        del btn_listener[msg_id]
        return editMessage('<b>Download has been cancelled</b>', message)
    elif data[1] == 'start':
        query.answer()
        del btn_listener[msg_id]
        message.delete()
        return start_clone(listnerInfo)
    time_out = listnerInfo[3] - (time() - listnerInfo[4])
    text, btns = get_category_btns('clone', time_out, msg_id, listnerInfo[2])
    editMessage(text, message, btns)

@new_thread
def cloneNode(update, context):
    _clone(update.message, context.bot)

clone_handler = CommandHandler(BotCommands.CloneCommand, cloneNode,
                               filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
clone_confirm_handler = CallbackQueryHandler(clone_confirm, pattern="clone", run_async=True)
dispatcher.add_handler(clone_confirm_handler)
dispatcher.add_handler(clone_handler)
