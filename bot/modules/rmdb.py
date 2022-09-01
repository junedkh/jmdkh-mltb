from telegram.ext import CommandHandler
from bot import DB_URI, dispatcher
from bot.helper.ext_utils.bot_utils import is_magnet, is_url, new_thread
from bot.helper.telegram_helper.message_utils import sendMessage
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.ext_utils.db_handler import DbManger
from re import match

def is_uid4(uuid):
    return bool(match(r'[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89aAbB][a-f0-9]{3}-[a-f0-9]{12}', uuid))

def _rmdb(message, bot):
    mesg = message.text.split('\n')
    message_args = mesg[0].split(' ', maxsplit=1)
    tfile = False
    file = None
    try:
        link = message_args[1]
    except IndexError:
        link = ''
    tag = None
    reply_to = message.reply_to_message
    if reply_to is not None:
        media_array = [reply_to.document, reply_to.video, reply_to.audio]
        file = next((i for i in media_array if i is not None), None)
        if not reply_to.from_user.is_bot:
            if reply_to.from_user.username:
                tag = f"@{reply_to.from_user.username}"
            else:
                tag = reply_to.from_user.mention_html(reply_to.from_user.first_name)

        if not is_url(link) and not is_magnet(link) and not is_uid4(link) and not link:
            if file is None:
                if is_url(reply_to.text) or is_magnet(reply_to.text) or is_uid4(reply_to.text):
                    link = reply_to.text.strip()
                else:
                    mesg = message.text.split('\n')
                    message_args = mesg[0].split(' ', maxsplit=1)
                    try:
                        link = message_args[1]
                    except IndexError:
                        pass
            elif file.mime_type == "application/x-bittorrent":
                tfile = True
                link = file.get_file().download_url
            else:
                link = file.file_name
                exist = DbManger().check_download(link)
                if exist:
                    DbManger().remove_download(exist[0])
                    msg = 'Download is removed from database successfully'
                    msg += f'\n{exist[2]} Your download is removed.'
                    if tag:
                        msg += f'\n{tag} Now you can download this link'
                else:
                    msg = 'This file is not exists in database'
                return sendMessage(msg, bot, message)

    if is_url(link) or is_magnet(link) or is_uid4(link):
        rawlink = DbManger().extract_link(tfile, link)
        exist = DbManger().check_download(rawlink)
        if exist:
            DbManger().remove_download(exist[0])
            msg = 'Download is removed from database successfully'
            msg += f'\n{exist[2]} Your download is removed.'
            if tag:
                msg += f'\n{tag} Now you can download this link'
        else:
            msg = 'This download is not exists in database'
    else:
        msg = "Please send a valid magnet link / url / uuid"
    return sendMessage(msg, bot, message)

@new_thread
def rmdbNode(update, context):
    _rmdb(update.message, context.bot)

if DB_URI is not None:
    rmdb_handler = CommandHandler(command=BotCommands.RmdbCommand, callback=rmdbNode, filters=CustomFilters.owner_filter | CustomFilters.sudo_user, run_async=True)
    dispatcher.add_handler(rmdb_handler)