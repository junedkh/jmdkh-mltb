from os import remove
from time import sleep, time

from pyrogram.errors import FloodWait
from telegram import ChatPermissions, InlineKeyboardMarkup
from telegram.error import RetryAfter, Unauthorized

from bot import (FSUB_IDS, LOGGER, Interval, bot, botname, config_dict,
                 rss_session, status_reply_dict, status_reply_dict_lock)
from bot.helper.ext_utils.bot_utils import get_readable_message, setInterval
from bot.helper.telegram_helper.button_build import ButtonMaker


def sendMessage(text: str, bot, message):
    try:
        return bot.sendMessage(message.chat_id,
                            reply_to_message_id=message.message_id,
                            text=text, allow_sending_without_reply=True, parse_mode='HTML', disable_web_page_preview=True)
    except RetryAfter as r:
        LOGGER.warning(str(r))
        sleep(r.retry_after * 1.5)
        return sendMessage(text, bot, message)
    except Exception as e:
        LOGGER.error(str(e))
        return

def sendMarkup(text: str, bot, message, reply_markup: InlineKeyboardMarkup):
    try:
        return bot.sendMessage(message.chat_id,
                            reply_to_message_id=message.message_id,
                            text=text, reply_markup=reply_markup, allow_sending_without_reply=True,
                            parse_mode='HTML', disable_web_page_preview=True)
    except RetryAfter as r:
        LOGGER.warning(str(r))
        sleep(r.retry_after * 1.5)
        return sendMarkup(text, bot, message, reply_markup)
    except Exception as e:
        LOGGER.error(str(e))
        return

def editMessage(text: str, message, reply_markup=None):
    try:
        bot.editMessageText(text=text, message_id=message.message_id,
                              chat_id=message.chat.id,reply_markup=reply_markup,
                              parse_mode='HTML', disable_web_page_preview=True)
    except RetryAfter as r:
        LOGGER.warning(str(r))
        sleep(r.retry_after * 1.5)
        return editMessage(text, message, reply_markup)
    except Exception as e:
        LOGGER.error(str(e))
        return str(e)

def sendRss(text, bot):
    if not rss_session:
        try:
            return bot.sendMessage(config_dict['RSS_CHAT_ID'], text, parse_mode='HTML', disable_web_page_preview=True)
        except RetryAfter as r:
            LOGGER.warning(str(r))
            sleep(r.retry_after * 1.5)
            return sendRss(text, bot)
        except Exception as e:
            LOGGER.error(str(e))
            return
    else:
        try:
            with rss_session:
                return rss_session.send_message(config_dict['RSS_CHAT_ID'], text, disable_web_page_preview=True)
        except FloodWait as e:
            LOGGER.warning(str(e))
            sleep(e.value * 1.5)
            return sendRss(text, bot)
        except Exception as e:
            LOGGER.error(str(e))
            return

def deleteMessage(bot, message):
    try:
        bot.deleteMessage(chat_id=message.chat.id, message_id=message.message_id)
    except:
        pass

def sendLogFile(bot, message):
    with open('log.txt', 'rb') as f:
        bot.sendDocument(document=f, filename=f.name,
                          reply_to_message_id=message.message_id,
                          chat_id=message.chat_id)

def sendFile(bot, message, name: str, caption=""):
    try:
        with open(name, 'rb') as f:
            bot.sendDocument(document=f, filename=f.name, reply_to_message_id=message.message_id,
            caption=caption, parse_mode='HTML',chat_id=message.chat_id)
        remove(name)
        return
    except RetryAfter as r:
        LOGGER.warning(str(r))
        sleep(r.retry_after * 1.5)
        return sendFile(bot, message, name, caption)
    except Exception as e:
        LOGGER.error(str(e))
        return

def auto_delete_message(bot, cmd_message, bot_message):
    if config_dict['AUTO_DELETE_MESSAGE_DURATION'] != -1:
        sleep(config_dict['AUTO_DELETE_MESSAGE_DURATION'])
        deleteMessage(bot, cmd_message)
        deleteMessage(bot, bot_message)

def delete_all_messages():
    with status_reply_dict_lock:
        for data in list(status_reply_dict.values()):
            try:
                deleteMessage(bot, data[0])
                del status_reply_dict[data[0].chat.id]
            except Exception as e:
                LOGGER.error(str(e))

def update_all_messages(force=False):
    with status_reply_dict_lock:
        if not status_reply_dict or not Interval or (not force and time() - list(status_reply_dict.values())[0][1] < 3):
            return
        for chat_id in status_reply_dict:
            status_reply_dict[chat_id][1] = time()

    msg, buttons = get_readable_message()
    if msg is None:
        return
    with status_reply_dict_lock:
        for chat_id in status_reply_dict:
            if status_reply_dict[chat_id] and msg != status_reply_dict[chat_id][0].text:
                if buttons == "":
                    rmsg = editMessage(msg, status_reply_dict[chat_id][0])
                else:
                    rmsg = editMessage(msg, status_reply_dict[chat_id][0], buttons)
                if rmsg == "Message to edit not found":
                    del status_reply_dict[chat_id]
                    return
                status_reply_dict[chat_id][0].text = msg
                status_reply_dict[chat_id][1] = time()

def sendStatusMessage(msg, bot):
    progress, buttons = get_readable_message()
    if progress is None:
        return
    with status_reply_dict_lock:
        if msg.chat.id in status_reply_dict:
            message = status_reply_dict[msg.chat.id][0]
            deleteMessage(bot, message)
            del status_reply_dict[msg.chat.id]
        if buttons == "":
            message = sendMessage(progress, bot, msg)
        else:
            message = sendMarkup(progress, bot, msg, buttons)
        status_reply_dict[msg.chat.id] = [message, time()]
        if not Interval:
            Interval.append(setInterval(config_dict['DOWNLOAD_STATUS_UPDATE_INTERVAL'], update_all_messages))

def sendDmMessage(text, bot, message, disable_notification=False, forward=False):
    try:
        if forward:
            return bot.forward_message(message.from_user.id,
                            from_chat_id=message.chat_id,
                            message_id=message.reply_to_message.message_id,
                            disable_notification=disable_notification)
        return bot.sendMessage(message.from_user.id,
                            reply_to_message_id=message.message_id,
                             disable_notification=disable_notification,
                            text=text, allow_sending_without_reply=True, parse_mode='HTML', disable_web_page_preview=True)
    except RetryAfter as r:
        LOGGER.warning(str(r))
        sleep(r.retry_after * 1.5)
        return sendMessage(text, bot, message)
    except Unauthorized:
        buttons = ButtonMaker()
        buttons.buildbutton("Start", f"http://t.me/{botname}?start=start")
        sendMarkup("<b>You Didn't START the BOT in DM</b>", bot, message, buttons.build_menu(1))
        return
    except Exception as e:
        LOGGER.error(str(e))
        return

def forcesub(bot, message, tag):
    if not FSUB_IDS:
        return
    if message.chat.type != 'supergroup':
        return
    if message.from_user.username == "Channel_Bot":
        return sendMessage('You cannot use bot as a channel', bot, message)
    user_id = message.from_user.id
    member = message.chat.get_member(user_id)
    if member.is_anonymous or member.status in ["administrator", "creator"]:
        return
    join_button = {}
    for channel_id in FSUB_IDS:
        chat = bot.get_chat(channel_id)
        member = chat.get_member(user_id)
        if member.status in ["left", "kicked"] :
            join_button[chat.title] = chat.link or chat.invite_link
    if join_button:
        btn = ButtonMaker()
        for key, value in join_button.items():
            btn.buildbutton(key, value)
        return sendMarkup(f'💡 {tag},\nYou have to join our channel!\n🔻 Join And Try Again!', bot, message, btn.build_menu(2))

def message_filter(bot, message, tag):
    if not config_dict['ENABLE_MESSAGE_FILTER']:
        return
    if message.chat.type != 'supergroup':
        return
    member = message.chat.get_member(message.from_user.id)
    if member.is_anonymous or member.status in ["administrator", "creator"]:
        return
    _msg = ''
    if message.reply_to_message:
        if message.reply_to_message.forward_date:
            message.reply_to_message.delete()
            _msg = "You can't mirror or leech forward messages to this bot.\n\nRemove it and try again"
        elif message.reply_to_message.caption:
            message.reply_to_message.delete()
            _msg = "You can't mirror or leech with captions text to this bot.\n\nRemove it and try again"
    elif message.forward_date:
        message.delete()
        _msg = "You can't mirror or leech forward messages to this bot.\n\nRemove it and try again"
    if _msg:
        message.message_id = None
        return sendMessage(f"{tag} {_msg}", bot, message)

def chat_restrict(message):
    if not config_dict['ENABLE_CHAT_RESTRICT']:
        return
    if message.chat.type != 'supergroup':
        return
    member = message.chat.get_member(message.from_user.id)
    if member.is_anonymous or member.status in ["administrator", "creator"]:
        return
    message.chat.restrict_member(message.from_user.id, ChatPermissions(), int(time() + 60))

def delete_links(bot, message):
    if config_dict['DELETE_LINKS']:
        if message.reply_to_message:
            deleteMessage(bot, message.reply_to_message)
        else:
            deleteMessage(bot, message)