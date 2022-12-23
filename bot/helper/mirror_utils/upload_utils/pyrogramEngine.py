from logging import ERROR, getLogger
from os import path as ospath
from os import remove, rename, walk
from re import sub
from threading import RLock
from time import sleep, time

from PIL import Image
from pyrogram.errors import FloodWait, RPCError
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import (GLOBAL_EXTENSION_FILTER, IS_USER_SESSION, app, config_dict,
                 user_data)
from bot.helper.ext_utils.bot_utils import get_readable_file_size
from bot.helper.ext_utils.fs_utils import (clean_unwanted, get_media_info,
                                           get_media_streams, take_ss)

LOGGER = getLogger(__name__)
getLogger("pyrogram").setLevel(ERROR)

IMAGE_SUFFIXES = ("JPG", "JPX", "PNG", "CR2", "TIF", "BMP", "JXR", "PSD", "ICO", "HEIC", "JPEG")


class TgUploader:

    def __init__(self, name=None, path=None, size=0, listener=None):
        self.name = name
        self.uploaded_bytes = 0
        self._last_uploaded = 0
        self.__listener = listener
        self.__path = path
        self.__start_time = time()
        self.__total_files = 0
        self.__is_cancelled = False
        self.__as_doc = config_dict['AS_DOCUMENT']
        self.__thumb = f"Thumbnails/{listener.message.from_user.id}.jpg"
        self.__msgs_dict = {}
        self.__corrupted = 0
        self.__resource_lock = RLock()
        self.__is_corrupted = False
        self.__size = size
        self.__button = None
        self.__lprefix = None
        self.__msg_to_reply()
        self.__user_settings()

    def upload(self, o_files):
        for dirpath, subdir, files in sorted(walk(self.__path)):
            for file_ in sorted(files):
                if file_ in o_files:
                    continue
                if not file_.lower().endswith(tuple(GLOBAL_EXTENSION_FILTER)):
                    up_path = ospath.join(dirpath, file_)
                    self.__total_files += 1
                    try:
                        if ospath.getsize(up_path) == 0:
                            LOGGER.error(f"{up_path} size is zero, telegram don't upload zero size files")
                            self.__corrupted += 1
                            continue
                    except Exception as e:
                        if self.__is_cancelled:
                            return
                        LOGGER.error(e)
                        continue
                    self.__upload_file(up_path, file_, dirpath)
                    if self.__is_cancelled:
                        return
                    if (not self.__listener.isPrivate or config_dict['DUMP_CHAT']) and not self.__is_corrupted:
                        self.__msgs_dict[self.__sent_msg.link] = file_
                    self._last_uploaded = 0
                    sleep(1)
        if self.__listener.seed and not self.__listener.newDir:
            clean_unwanted(self.__path)
        if self.__total_files == 0:
            self.__listener.onUploadError('No files to upload. Make sure if you filled USER_SESSION_STRING then you should use supergroup. In case you filled EXTENSION_FILTER then check if all file have this extension')
            return
        if self.__total_files <= self.__corrupted:
            self.__listener.onUploadError('Files Corrupted. Check logs!')
            return
        LOGGER.info(f"Leech Completed: {self.name}")
        size = get_readable_file_size(self.__size)
        self.__listener.onUploadComplete(None, size, self.__msgs_dict, self.__total_files, self.__corrupted, self.name)

    def __upload_file(self, up_path, file_, dirpath):
        if self.__lprefix:
            cap_mono = f"{self.__lprefix} <code>{file_}</code>"
            self.__lprefix = sub('<.*?>', '', self.__lprefix)
            file_ = f"{self.__lprefix} {file_}"
            new_path = ospath.join(dirpath, file_)
            rename(up_path, new_path)
            up_path = new_path
        else:
            cap_mono = f"<code>{file_}</code>"
        notMedia = False
        thumb = self.__thumb
        self.__is_corrupted = False
        try:
            is_video, is_audio = get_media_streams(up_path)
            if not self.__as_doc:
                if is_video:
                    duration = get_media_info(up_path)[0]
                    if thumb is None:
                        thumb = take_ss(up_path, duration)
                        if self.__is_cancelled:
                            if self.__thumb is None and thumb and ospath.lexists(thumb):
                                remove(thumb)
                            return
                    if thumb:
                        with Image.open(thumb) as img:
                            width, height = img.size
                    else:
                        width = 480
                        height = 320
                    if not file_.upper().endswith(("MKV", "MP4")):
                        file_ = f"{ospath.splitext(file_)[0]}.mp4"
                        new_path = ospath.join(dirpath, file_)
                        rename(up_path, new_path)
                        up_path = new_path
                    self.__sent_msg = self.__sent_msg.reply_video(video=up_path,
                                                                  quote=True,
                                                                  caption=cap_mono,
                                                                  duration=duration,
                                                                  width=width,
                                                                  height=height,
                                                                  thumb=thumb,
                                                                  supports_streaming=True,
                                                                  disable_notification=True,
                                                                  reply_markup=self.__button,
                                                                  progress=self.__upload_progress)
                elif is_audio:
                    duration , artist, title = get_media_info(up_path)
                    self.__sent_msg = self.__sent_msg.reply_audio(audio=up_path,
                                                                  quote=True,
                                                                  caption=cap_mono,
                                                                  duration=duration,
                                                                  performer=artist,
                                                                  title=title,
                                                                  thumb=thumb,
                                                                  disable_notification=True,
                                                                  reply_markup=self.__button,
                                                                  progress=self.__upload_progress)
                elif file_.upper().endswith(IMAGE_SUFFIXES):
                    self.__sent_msg = self.__sent_msg.reply_photo(photo=up_path,
                                                                  quote=True,
                                                                  caption=cap_mono,
                                                                  disable_notification=True,
                                                                  reply_markup=self.__button,
                                                                  progress=self.__upload_progress)
                else:
                    notMedia = True
            if self.__as_doc or notMedia:
                if is_video and thumb is None:
                    thumb = take_ss(up_path, None)
                    if self.__is_cancelled:
                        if self.__thumb is None and thumb and ospath.lexists(thumb):
                            remove(thumb)
                        return
                self.__sent_msg = self.__sent_msg.reply_document(document=up_path,
                                                                 quote=True,
                                                                 thumb=thumb,
                                                                 caption=cap_mono,
                                                                 disable_notification=True,
                                                                 reply_markup=self.__button,
                                                                 progress=self.__upload_progress)
            if self.__listener.dmMessage and self.__sent_DMmsg:
                sleep(1)
                if IS_USER_SESSION:
                    self.__sent_DMmsg = self.__listener.bot.copy_message(
                    chat_id=self.__listener.message.from_user.id,
                    from_chat_id=self.__sent_msg.chat.id,
                    message_id=self.__sent_msg.id,
                    reply_to_message_id=self.__sent_DMmsg['message_id'])
                else:
                    self.__sent_DMmsg = self.__sent_msg.copy(
                        chat_id=self.__sent_DMmsg.chat.id,
                        reply_to_message_id=self.__sent_DMmsg.id)
        except FloodWait as f:
            LOGGER.warning(str(f))
            sleep(f.value)
        except RPCError as e:
            LOGGER.error(f"RPCError: {e} Path: {up_path}")
            self.__corrupted += 1
            self.__is_corrupted = True
        except Exception as err:
            LOGGER.error(f"{err} Path: {up_path}")
            self.__corrupted += 1
            self.__is_corrupted = True
        if self.__thumb is None and thumb and ospath.lexists(thumb):
            remove(thumb)
        if not self.__is_cancelled and \
                   (not self.__listener.seed or self.__listener.newDir or dirpath.endswith("splited_files_mltb")):
            try:
                remove(up_path)
            except:
                pass

    def __upload_progress(self, current, total):
        if self.__is_cancelled:
            app.stop_transmission()
            return
        with self.__resource_lock:
            chunk_size = current - self._last_uploaded
            self._last_uploaded = current
            self.uploaded_bytes += chunk_size

    def __user_settings(self):
        user_id = self.__listener.message.from_user.id
        if user_id in user_data:
            if user_data[user_id].get('as_doc'):
                self.__as_doc = True
            elif user_data[user_id].get('as_media'):
                self.__as_doc = False
            self.__lprefix = user_data[user_id].get('lprefix')
        if not ospath.lexists(self.__thumb):
            self.__thumb = None

    def __msg_to_reply(self):
        if DUMP_CHAT:= config_dict['DUMP_CHAT']:
            msg = self.__listener.message.text if self.__listener.isPrivate else self.__listener.message.link
            self.__sent_msg = app.send_message(DUMP_CHAT, msg, disable_web_page_preview=True)
            if self.__listener.dmMessage and IS_USER_SESSION:
                self.__sent_DMmsg = {'message_id' : self.__listener.dmMessage.message_id}
            elif self.__listener.dmMessage:
                self.__sent_DMmsg = app.get_messages(self.__listener.message.from_user.id, self.__listener.dmMessage.message_id)
        elif self.__listener.dmMessage and not IS_USER_SESSION:
            self.__sent_msg = app.get_messages(self.__listener.message.from_user.id, self.__listener.dmMessage.message_id)
            self.__sent_DMmsg = None
        else:
            self.__sent_msg = app.get_messages(self.__listener.message.chat.id, self.__listener.uid)
            self.__sent_DMmsg = None
        if self.__listener.message.chat.type != 'private' and not self.__listener.dmMessage:
            self.__button = InlineKeyboardMarkup([[InlineKeyboardButton(text='Save Message', callback_data="save")]])

    @property
    def speed(self):
        with self.__resource_lock:
            try:
                return self.uploaded_bytes / (time() - self.__start_time)
            except:
                return 0

    def cancel_download(self):
        self.__is_cancelled = True
        LOGGER.info(f"Cancelling Upload: {self.name}")
        self.__listener.onUploadError('your upload has been stopped!')