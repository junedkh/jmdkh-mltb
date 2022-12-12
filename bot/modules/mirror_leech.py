from base64 import b64encode
from html import escape
from os import path
from re import match, split
from threading import Thread
from time import sleep, time

from requests import request
from telegram.ext import CallbackQueryHandler, CommandHandler

from bot import (CATEGORY_NAMES, DATABASE_URL, DOWNLOAD_DIR, IS_USER_SESSION,
                 LOGGER, btn_listener, config_dict, dispatcher)
from bot.helper.ext_utils.bot_utils import (check_user_tasks,
                                            get_category_btns, check_buttons,
                                            get_content_type, is_gdrive_link,
                                            is_magnet, is_mega_link, is_url,
                                            new_thread)
from bot.helper.ext_utils.db_handler import DbManger
from bot.helper.ext_utils.exceptions import DirectDownloadLinkException
from bot.helper.ext_utils.jmdkh_utils import extract_link
from bot.helper.mirror_utils.download_utils.aria2_download import add_aria2c_download
from bot.helper.mirror_utils.download_utils.direct_link_generator import direct_link_generator
from bot.helper.mirror_utils.download_utils.gd_downloader import add_gd_download
from bot.helper.mirror_utils.download_utils.mega_downloader import add_mega_download
from bot.helper.mirror_utils.download_utils.qbit_downloader import add_qb_torrent
from bot.helper.mirror_utils.download_utils.telegram_downloader import TelegramDownloadHelper
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.message_utils import (chat_restrict,
                                                      delete_links,
                                                      editMessage, forcesub,
                                                      message_filter,
                                                      sendDmMessage,
                                                      sendMarkup, sendMessage)
from bot.modules.listener import MirrorLeechListener


def _mirror_leech(bot, message, isZip=False, extract=False, isQbit=False, isLeech=False):
    msg_id = message.message_id
    mesg = message.text.split('\n')
    message_args = mesg[0].split(maxsplit=1)
    index = 1
    ratio = None
    seed_time = None
    select = False
    seed = False
    multi = 0
    link = ''
    tfile = False
    raw_url = None
    c_index = 0
    time_out = 30
    maxtask = config_dict['USER_MAX_TASKS']
    if len(message_args) > 1:
        args = mesg[0].split(maxsplit=3)
        for x in args:
            x = x.strip()
            if x == 's':
               select = True
               index += 1
            elif x == 'd':
                seed = True
                index += 1
            elif x.startswith('d:'):
                seed = True
                index += 1
                dargs = x.split(':')
                ratio = dargs[1] if dargs[1] else None
                if len(dargs) == 3:
                    seed_time = dargs[2] if dargs[2] else None
            elif x.isdigit():
                multi = int(x)
                mi = index
        if multi == 0:
            message_args = mesg[0].split(maxsplit=index)
            if len(message_args) > index:
                link = message_args[index].strip()
                if link.startswith(("|", "pswd:")):
                    link = ''

    name = mesg[0].split('|', maxsplit=1)
    if len(name) > 1:
        if 'pswd:' in name[0]:
            name = ''
        else:
            name = name[1].split('pswd:')[0].strip()
    else:
        name = ''

    pswd = mesg[0].split(' pswd: ')
    pswd = pswd[1] if len(pswd) > 1 else None

    if message.from_user.username:
        tag = f"@{message.from_user.username}"
    else:
        tag = message.from_user.mention_html(message.from_user.first_name)

    if link != '':
        link = split(r"pswd:|\|", link)[0]
        link = link.strip()

    reply_to = message.reply_to_message
    if reply_to:
        file_ = reply_to.document or reply_to.video or reply_to.audio or reply_to.photo or None
        if not reply_to.from_user.is_bot:
            if reply_to.from_user.username:
                tag = f"@{reply_to.from_user.username}"
            else:
                tag = reply_to.from_user.mention_html(reply_to.from_user.first_name)
        if message_filter(bot, message, tag):
            return
        if len(link) == 0 or not is_url(link) and not is_magnet(link):
            if file_ is None:
                reply_text = reply_to.text.split(maxsplit=1)[0].strip()
                if is_url(reply_text) or is_magnet(reply_text):
                    link = reply_to.text.strip()
            elif isinstance(file_, list):
                link = file_[-1].get_file().file_path
            elif not isQbit and file_.mime_type != "application/x-bittorrent":
                if DATABASE_URL and config_dict['STOP_DUPLICATE_TASKS']:
                    raw_url = file_.file_unique_id
                    exist = DbManger().check_download(raw_url)
                    if exist:
                        _msg = f'<b>Download is already added by {exist["tag"]}</b>\n\nCheck the download status in @{exist["botname"]}\n\n<b>Link</b>: <code>{exist["_id"]}</code>'
                        delete_links(bot, message)
                        return sendMessage(_msg, bot, message)
                if forcesub(bot, message, tag):
                    return
                if maxtask and not CustomFilters.owner_query(message.from_user.id) and check_user_tasks(message.from_user.id, maxtask):
                    return sendMessage(f"Tasks limit exceeded for {maxtask} tasks", bot, message)
                link = 'telegram_file'
                listener = [bot, message, isZip, extract, isQbit, isLeech, pswd, tag, select, seed, raw_url]
                extras = [link, name, ratio, seed_time, c_index, time()]
                if len(CATEGORY_NAMES) > 1 and not isLeech:
                    if checked:= check_buttons():
                        return sendMessage(checked, bot, message)
                    btn_listener[msg_id] = [listener, extras, time_out]
                    chat_restrict(message)
                    text, btns = get_category_btns('mir', time_out, msg_id, c_index)
                    engine = sendMarkup(text, bot, message, btns)
                    _auto_start_dl(engine, msg_id, time_out)
                else:
                    chat_restrict(message)
                    start_mirror_leech(extras, listener)
                if multi > 1:
                    sleep(4)
                    nextmsg = type('nextmsg', (object, ), {'chat_id': message.chat_id, 'message_id': message.reply_to_message.message_id + 1})
                    msg = message.text.split(maxsplit=mi+1)
                    msg[mi] = f"{multi - 1}"
                    nextmsg = sendMessage(" ".join(msg), bot, nextmsg)
                    nextmsg.from_user.id = message.from_user.id
                    sleep(4)
                    Thread(target=_mirror_leech, args=(bot, nextmsg, isZip, extract, isQbit, isLeech)).start()
                return
            else:
                tfile = True
                link = file_.get_file().file_path
    if not is_url(link) and not is_magnet(link) or (link.isdigit() and multi == 0):
        help_msg = '''
<code>/{cmd}</code> link |newname pswd: xx(zip/unzip)

<b>By replying to link/file:</b>
<code>/{cmd}</code> |newname pswd: xx(zip/unzip)

<b>Direct link authorization:</b>
<code>/{cmd}</code> link |newname pswd: xx(zip/unzip)
<b>username</b>
<b>password</b>

<b>Bittorrent selection:</b>
<code>/{cmd}</code> <b>s</b> link or by replying to file/link
This perfix should be always before |newname or pswd:

<b>Bittorrent seed</b>:
<code>/{cmd}</code> <b>d</b> link or by replying to file/link
To specify ratio and seed time add d:ratio:time. Ex: d:0.7:10 (ratio and time) or d:0.7 (only ratio) or d::10 (only time) where time in minutes.
This perfix should be always before |newname or pswd:

<b>Multi links only by replying to first link/file:</b>
<code>/{cmd}</code> 10(number of links/files)
Number should be always before |newname or pswd:

<b>NOTES:</b>
1. When use cmd by reply don't add any perfix in link msg! always add them after cmd msg!
2. You can't add this perfixes <b>|newname, pswd: and authorization</b> randomly. They should be arranged like exmaple above, rename then pswd then authorization. If you don't want to add pswd for example then it will be (|newname authorization), just don't change the arrangement.
3. You can add this perfixes <b>d, s and multi</b> randomly. Ex: <code>/{cmd}</code> d:1:20 s 10 <b>or</b> <code>/{cmd}</code> s 10 d:0.5:100
4. Commands that start with <b>qb</b> are ONLY for torrents.
'''
        delete_links(bot, message)
        return sendMessage(help_msg.format_map({'cmd': BotCommands.MirrorCommand[0]}), bot, message)
    if message_filter(bot, message, tag):
        return
    if DATABASE_URL and config_dict['STOP_DUPLICATE_TASKS']:
        raw_url = extract_link(link, tfile)
        exist = DbManger().check_download(raw_url)
        if exist:
            _msg = f'<b>Download is already added by {exist["tag"]}</b>\n\nCheck the download status in @{exist["botname"]}\n\n<b>Link</b>: <code>{exist["_id"]}</code>'
            delete_links(bot, message)
            return sendMessage(_msg, bot, message)
    if forcesub(bot, message, tag):
        return
    if maxtask and not CustomFilters.owner_query(message.from_user.id) and check_user_tasks(message.from_user.id, maxtask):
        return sendMessage(f"Tasks limit exceeded for {maxtask} tasks", bot, message)
    listener = [bot, message, isZip, extract, isQbit, isLeech, pswd, tag, select, seed, raw_url]
    extras = [link, name, ratio, seed_time, c_index, time()]
    if len(CATEGORY_NAMES) > 1 and not isLeech :
        if checked:= check_buttons():
            return sendMessage(checked, bot, message)
        btn_listener[msg_id] = [listener, extras, time_out]
        text, btns = get_category_btns('mir', time_out, msg_id, c_index)
        chat_restrict(message)
        engine = sendMarkup(text, bot, message, btns)
        _auto_start_dl(engine, msg_id, time_out)
    else:
        chat_restrict(message)
        start_mirror_leech(extras, listener)
    if multi > 1:
        sleep(4)
        nextmsg = type('nextmsg', (object, ), {'chat_id': message.chat_id, 'message_id': message.reply_to_message.message_id + 1})
        msg = message.text.split(maxsplit=mi+1)
        msg[mi] = f"{multi - 1}"
        nextmsg = sendMessage(" ".join(msg), bot, nextmsg)
        nextmsg.from_user.id = message.from_user.id
        sleep(4)
        Thread(target=_mirror_leech, args=(bot, nextmsg, isZip, extract, isQbit, isLeech)).start()

@new_thread
def _auto_start_dl(msg, msg_id, time_out):
    sleep(time_out)
    try:
        info = btn_listener[msg_id]
        del btn_listener[msg_id]
        editMessage("Timed out! Task has been started.", msg)
        start_mirror_leech(info[1], info[0])
    except:
        pass

def start_mirror_leech(extra, s_listener):
    bot = s_listener[0]
    message = s_listener[1]
    isZip = s_listener[2]
    extract = s_listener[3]
    isQbit = s_listener[4]
    isLeech = s_listener[5]
    pswd = s_listener[6]
    tag = s_listener[7]
    select = s_listener[8]
    seed = s_listener[9]
    raw_url = s_listener[10]
    link = extra[0]
    name = extra[1]
    ratio = extra[2]
    seed_time = extra[3]
    c_index = int(extra[4])
    if isLeech and config_dict['DISABLE_LEECH']:
        delete_links(bot, message)
        return sendMessage('Locked!', bot, message)
    if not isZip and not extract and not isLeech and is_gdrive_link(link):
        gmsg = f"Use /{BotCommands.CloneCommand} to clone Google Drive file/folder\n\n"
        gmsg += "Use Zip mode to make zip of Google Drive folder\n\n"
        gmsg += "Use Unzip mode to extracts Google Drive archive folder/file\n\n"
        gmsg += "Use Telegram mode to upload on telegram"
        delete_links(bot, message)
        return sendMessage(gmsg, bot, message)
    if config_dict['ENABLE_DM'] and message.chat.type != 'private':
        if isLeech and IS_USER_SESSION and not config_dict['DUMP_CHAT']:
            delete_links(bot, message)
            return sendMessage('ENABLE_DM and User Session need DUMP_CHAT', bot, message)
        tfile = link == 'telegram_file' or "https://api.telegram.org/file/" in link
        dmMessage = sendDmMessage(link, bot, message, True, tfile)
        if not dmMessage:
            return
    else:
        dmMessage = None
    listener = MirrorLeechListener(bot, message, isZip, extract, isQbit, isLeech, pswd, tag, select, seed, raw_url, c_index, dmMessage)
    listener.mode = 'Leech' if isLeech else f'Drive {CATEGORY_NAMES[c_index]}'
    if isZip:
        listener.mode += ' as Zip'
    elif extract:
        listener.mode += ' as Unzip'
    if link == 'telegram_file':
        Thread(target=TelegramDownloadHelper(listener).add_download, args=(message, f'{DOWNLOAD_DIR}{listener.uid}/', name)).start()
        delete_links(bot, message)
        return
    LOGGER.info(link)
    if not is_mega_link(link) and not isQbit and not is_magnet(link) \
        and not is_gdrive_link(link) and not link.endswith('.torrent'):
        content_type = get_content_type(link)
        if content_type is None or match(r'text/html|text/plain', content_type):
            _tempmsg = sendMessage(f"Processing: <code>{link}</code>", bot, message)
            try:
                link = direct_link_generator(link)
                LOGGER.info(f"Generated link: {link}")
                editMessage(f"Generated link: <code>{link}</code>", _tempmsg)
            except DirectDownloadLinkException as e:
                LOGGER.info(str(e))
                if str(e).startswith('ERROR:'):
                    delete_links(bot, message)
                    return editMessage(escape(str(e)), _tempmsg)
            _tempmsg.delete()
    elif isQbit and not is_magnet(link):
        if link.endswith('.torrent') or "https://api.telegram.org/file/" in link:
            content_type = None
        else:
            content_type = get_content_type(link)
        if content_type is None or match(r'application/x-bittorrent|application/octet-stream', content_type):
            try:
                resp = request('GET', link, timeout=10, headers = {'user-agent': 'Wget/1.12'})
                if resp.status_code != 200:
                    delete_links(bot, message)
                    return sendMessage(f"{tag} ERROR: link got HTTP response: {resp.status_code}", bot, message)
                file_name = str(time()).replace(".", "") + ".torrent"
                with open(file_name, "wb") as t:
                    t.write(resp.content)
                link = str(file_name)
            except Exception as e:
                error = str(e).replace('<', ' ').replace('>', ' ')
                if error.startswith('No connection adapters were found for'):
                    link = error.split("'")[1]
                else:
                    LOGGER.error(str(e))
                    delete_links(bot, message)
                    return sendMessage(f"{tag} {error}", bot, message)
        else:
            msg = "qBittorrent for torrents only. if you are trying to dowload torrent then report."
            return sendMessage(msg, bot, message)
    if is_gdrive_link(link):
        Thread(target=add_gd_download, args=(link, f'{DOWNLOAD_DIR}{listener.uid}', listener, name)).start()
    elif is_mega_link(link):
        listener.ismega = sendMessage("💡 <b>Mega link this might take a minutes</b>", bot, message)
        Thread(target=add_mega_download, args=(link, f'{DOWNLOAD_DIR}{listener.uid}/', listener, name)).start()
    elif isQbit and (is_magnet(link) or path.exists(link)):
        Thread(target=add_qb_torrent, args=(link, f'{DOWNLOAD_DIR}{listener.uid}', listener, ratio, seed_time)).start()
    else:
        mesg = message.text.split('\n')
        if len(mesg) > 1:
            ussr = mesg[1]
            pssw = mesg[2] if len(mesg) > 2 else ''
            auth = f"{ussr}:{pssw}"
            auth = "Basic " + b64encode(auth.encode()).decode('ascii')
        else:
            auth = ''
        Thread(target=add_aria2c_download, args=(link, f'{DOWNLOAD_DIR}{listener.uid}', listener, name, auth, ratio, seed_time)).start()
    delete_links(bot, message)

@new_thread
def mir_confirm(update, context):
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
    listener = listnerInfo[0]
    extra = listnerInfo[1]
    if user_id != listener[1].from_user.id and not CustomFilters.owner_query(user_id):
        return query.answer("You are not the owner of this download", show_alert=True)
    elif data[1] == 'scat':
        c_index = int(data[3])
        if extra[4] == c_index:
            return query.answer(f"{CATEGORY_NAMES[c_index]} is Selected Already", show_alert=True)
        query.answer()
        extra[4] = c_index
    elif data[1] == 'cancel':
        query.answer()
        del btn_listener[msg_id]
        return editMessage('<b>Download has been cancelled</b>', message)
    elif data[1] == 'start':
        query.answer()
        del btn_listener[msg_id]
        message.delete()
        return start_mirror_leech(extra, listener)
    time_out = listnerInfo[2] - (time() - extra[5])
    text, btns = get_category_btns('mir', time_out, msg_id, extra[4])
    editMessage(text, message, btns)

def mirror(update, context):
    _mirror_leech(context.bot, update.message)

def mirror(update, context):
    _mirror_leech(context.bot, update.message)

def unzip_mirror(update, context):
    _mirror_leech(context.bot, update.message, extract=True)

def zip_mirror(update, context):
    _mirror_leech(context.bot, update.message, True)

def qb_mirror(update, context):
    _mirror_leech(context.bot, update.message, isQbit=True)

def qb_unzip_mirror(update, context):
    _mirror_leech(context.bot, update.message, extract=True, isQbit=True)

def qb_zip_mirror(update, context):
    _mirror_leech(context.bot, update.message, True, isQbit=True)

def leech(update, context):
    _mirror_leech(context.bot, update.message, isLeech=True)

def unzip_leech(update, context):
    _mirror_leech(context.bot, update.message, extract=True, isLeech=True)

def zip_leech(update, context):
    _mirror_leech(context.bot, update.message, True, isLeech=True)

def qb_leech(update, context):
    _mirror_leech(context.bot, update.message, isQbit=True, isLeech=True)

def qb_unzip_leech(update, context):
    _mirror_leech(context.bot, update.message, extract=True, isQbit=True, isLeech=True)

def qb_zip_leech(update, context):
    _mirror_leech(context.bot, update.message, True, isQbit=True, isLeech=True)

mirror_handler = CommandHandler(BotCommands.MirrorCommand, mirror,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
unzip_mirror_handler = CommandHandler(BotCommands.UnzipMirrorCommand, unzip_mirror,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
zip_mirror_handler = CommandHandler(BotCommands.ZipMirrorCommand, zip_mirror,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_mirror_handler = CommandHandler(BotCommands.QbMirrorCommand, qb_mirror,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_unzip_mirror_handler = CommandHandler(BotCommands.QbUnzipMirrorCommand, qb_unzip_mirror,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_zip_mirror_handler = CommandHandler(BotCommands.QbZipMirrorCommand, qb_zip_mirror,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
leech_handler = CommandHandler(BotCommands.LeechCommand, leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
unzip_leech_handler = CommandHandler(BotCommands.UnzipLeechCommand, unzip_leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
zip_leech_handler = CommandHandler(BotCommands.ZipLeechCommand, zip_leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_leech_handler = CommandHandler(BotCommands.QbLeechCommand, qb_leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_unzip_leech_handler = CommandHandler(BotCommands.QbUnzipLeechCommand, qb_unzip_leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_zip_leech_handler = CommandHandler(BotCommands.QbZipLeechCommand, qb_zip_leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)

mir_handler = CallbackQueryHandler(mir_confirm, pattern="mir", run_async=True)

dispatcher.add_handler(mirror_handler)
dispatcher.add_handler(unzip_mirror_handler)
dispatcher.add_handler(zip_mirror_handler)
dispatcher.add_handler(qb_mirror_handler)
dispatcher.add_handler(qb_unzip_mirror_handler)
dispatcher.add_handler(qb_zip_mirror_handler)
dispatcher.add_handler(leech_handler)
dispatcher.add_handler(unzip_leech_handler)
dispatcher.add_handler(zip_leech_handler)
dispatcher.add_handler(qb_leech_handler)
dispatcher.add_handler(qb_unzip_leech_handler)
dispatcher.add_handler(qb_zip_leech_handler)
dispatcher.add_handler(mir_handler)