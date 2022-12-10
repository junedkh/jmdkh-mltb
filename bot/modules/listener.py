from html import escape
from os import listdir
from os import path as ospath
from os import remove as osremove
from os import walk
from re import search as re_search
from subprocess import Popen
from time import sleep, time

from requests import utils as rutils

from bot import (CATEGORY_INDEXS, DATABASE_URL, DOWNLOAD_DIR, LOGGER,
                 MAX_SPLIT_SIZE, SHORTENERES, Interval, aria2, config_dict,
                 download_dict, download_dict_lock, status_reply_dict_lock)
from bot.helper.ext_utils.bot_utils import extra_btns, get_readable_time
from bot.helper.ext_utils.db_handler import DbManger
from bot.helper.ext_utils.exceptions import NotSupportedExtractionArchive
from bot.helper.ext_utils.fs_utils import (clean_download, clean_target,
                                           get_base_name, get_path_size,
                                           split_file)
from bot.helper.ext_utils.shortener import short_url
from bot.helper.mirror_utils.status_utils.extract_status import ExtractStatus
from bot.helper.mirror_utils.status_utils.split_status import SplitStatus
from bot.helper.mirror_utils.status_utils.tg_upload_status import TgUploadStatus
from bot.helper.mirror_utils.status_utils.upload_status import UploadStatus
from bot.helper.mirror_utils.status_utils.zip_status import ZipStatus
from bot.helper.mirror_utils.upload_utils.gdriveTools import GoogleDriveHelper
from bot.helper.mirror_utils.upload_utils.pyrogramEngine import TgUploader
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.message_utils import (delete_all_messages,
                                                      sendMarkup, sendMessage,
                                                      update_all_messages)


class MirrorLeechListener:
    def __init__(self, bot, message, isZip=False, extract=False, isQbit=False, isLeech=False, pswd=None, tag=None, select=False, seed=False, raw_url=None, c_index=0, dmMessage=None):
        self.bot = bot
        self.message = message
        self.uid = message.message_id
        self.extract = extract
        self.isZip = isZip
        self.isQbit = isQbit
        self.isLeech = isLeech
        self.pswd = pswd
        self.tag = tag
        self.seed = seed
        self.newDir = ""
        self.dir = f"{DOWNLOAD_DIR}{self.uid}"
        self.select = select
        self.isPrivate = message.chat.type in ['private', 'group']
        self.suproc = None
        self.raw_url = raw_url
        self.c_index = c_index
        self.dmMessage = dmMessage

    def clean(self):
        try:
            with status_reply_dict_lock:
                Interval[0].cancel()
                Interval.clear()
            aria2.purge()
            delete_all_messages()
        except:
            pass

    def onDownloadStart(self):
        if DATABASE_URL and config_dict['STOP_DUPLICATE_TASKS']:
            DbManger().add_download_url(self.raw_url, self.tag)
        if not self.isPrivate and config_dict['INCOMPLETE_TASK_NOTIFIER'] and DATABASE_URL:
            DbManger().add_incomplete_task(self.message.chat.id, self.message.link, self.tag)

    def onDownloadComplete(self):
        LEECH_SPLIT_SIZE = config_dict['LEECH_SPLIT_SIZE']
        with download_dict_lock:
            download = download_dict[self.uid]
            name = str(download.name()).replace('/', '')
            gid = download.gid()
        LOGGER.info(f"Download completed: {name}")
        if name == "None" or self.isQbit or not ospath.exists(f"{self.dir}/{name}"):
            name = listdir(self.dir)[-1]
        m_path = f'{self.dir}/{name}'
        size = get_path_size(m_path)
        if self.isZip:
            if self.seed and self.isLeech:
                self.newDir = f"{self.dir}10000"
                path = f"{self.newDir}/{name}.zip"
            else:
                path = f"{m_path}.zip"
            with download_dict_lock:
                download_dict[self.uid] = ZipStatus(name, size, gid, self)
            if self.pswd:
                if self.isLeech and int(size) > LEECH_SPLIT_SIZE:
                    LOGGER.info(f'Zip: orig_path: {m_path}, zip_path: {path}.0*')
                    self.suproc = Popen(["7z", f"-v{LEECH_SPLIT_SIZE}b", "a", "-mx=0", f"-p{self.pswd}", path, m_path])
                else:
                    LOGGER.info(f'Zip: orig_path: {m_path}, zip_path: {path}')
                    self.suproc = Popen(["7z", "a", "-mx=0", f"-p{self.pswd}", path, m_path])
            elif self.isLeech and int(size) > LEECH_SPLIT_SIZE:
                LOGGER.info(f'Zip: orig_path: {m_path}, zip_path: {path}.0*')
                self.suproc = Popen(["7z", f"-v{LEECH_SPLIT_SIZE}b", "a", "-mx=0", path, m_path])
            else:
                LOGGER.info(f'Zip: orig_path: {m_path}, zip_path: {path}')
                self.suproc = Popen(["7z", "a", "-mx=0", path, m_path])
            self.suproc.wait()
            if self.suproc.returncode == -9:
                return
            elif not self.seed:
                clean_target(m_path)
        elif self.extract:
            try:
                if ospath.isfile(m_path):
                    path = get_base_name(m_path)
                LOGGER.info(f"Extracting: {name}")
                with download_dict_lock:
                    download_dict[self.uid] = ExtractStatus(name, size, gid, self)
                if ospath.isdir(m_path):
                    if self.seed:
                        self.newDir = f"{self.dir}10000"
                        path = f"{self.newDir}/{name}"
                    else:
                        path = m_path
                    for dirpath, _, files in walk(m_path, topdown=False):
                        for file_ in files:
                            if re_search('\.part0*1\.rar$|\.7z\.0*1$|\.zip\.0*1$|\.zip$|\.7z$|^.(?!.*\.part\d+\.rar)(?=.*\.rar$)', file_):
                                f_path = ospath.join(dirpath, file_)
                                t_path = dirpath.replace(self.dir, self.newDir) if self.seed else dirpath
                                if self.pswd:
                                    self.suproc = Popen(["7z", "x", f"-p{self.pswd}", f_path, f"-o{t_path}", "-aot"])
                                else:
                                    self.suproc = Popen(["7z", "x", f_path, f"-o{t_path}", "-aot"])
                                self.suproc.wait()
                                if self.suproc.returncode == -9:
                                    return
                                elif self.suproc.returncode != 0:
                                    LOGGER.error('Unable to extract archive splits!')
                        if not self.seed and self.suproc and self.suproc.returncode == 0:
                            for file_ in files:
                                if re_search('\.r\d+$|\.7z\.\d+$|\.z\d+$|\.zip\.\d+$|\.zip$|\.rar$|\.7z$', file_):
                                    del_path = ospath.join(dirpath, file_)
                                    try:
                                        osremove(del_path)
                                    except:
                                        return
                else:
                    if self.seed and self.isLeech:
                        self.newDir = f"{self.dir}10000"
                        path = path.replace(self.dir, self.newDir)
                    if self.pswd:
                        self.suproc = Popen(["7z", "x", f"-p{self.pswd}", m_path, f"-o{path}", "-aot"])
                    else:
                        self.suproc = Popen(["7z", "x", m_path, f"-o{path}", "-aot"])
                    self.suproc.wait()
                    if self.suproc.returncode == -9:
                        return
                    elif self.suproc.returncode == 0:
                        LOGGER.info(f"Extracted Path: {path}")
                        if not self.seed:
                            try:
                                osremove(m_path)
                            except:
                                return
                    else:
                        LOGGER.error('Unable to extract archive! Uploading anyway')
                        self.newDir = ""
                        path = m_path
            except NotSupportedExtractionArchive:
                LOGGER.info("Not any valid archive, uploading file as it is.")
                self.newDir = ""
                path = m_path
        else:
            path = m_path
        up_dir, up_name = path.rsplit('/', 1)
        size = get_path_size(up_dir)
        if self.isLeech:
            m_size = []
            o_files = []
            if not self.isZip:
                checked = False
                for dirpath, _, files in walk(up_dir, topdown=False):
                    for file_ in files:
                        f_path = ospath.join(dirpath, file_)
                        f_size = ospath.getsize(f_path)
                        if f_size > LEECH_SPLIT_SIZE:
                            if not checked:
                                checked = True
                                with download_dict_lock:
                                    download_dict[self.uid] = SplitStatus(up_name, size, gid, self)
                                LOGGER.info(f"Splitting: {up_name}")
                            res = split_file(f_path, f_size, file_, dirpath, LEECH_SPLIT_SIZE, self)
                            if not res:
                                return
                            if res == "errored":
                                if f_size <= MAX_SPLIT_SIZE:
                                    continue
                                try:
                                    osremove(f_path)
                                except:
                                    return
                            elif not self.seed or self.newDir:
                                try:
                                    osremove(f_path)
                                except:
                                    return
                            else:
                                m_size.append(f_size)
                                o_files.append(file_)
            size = get_path_size(up_dir)
            for s in m_size:
                size = size - s
            LOGGER.info(f"Leech Name: {up_name}")
            tg = TgUploader(up_name, up_dir, size, self)
            tg_upload_status = TgUploadStatus(tg, size, gid, self)
            with download_dict_lock:
                download_dict[self.uid] = tg_upload_status
            update_all_messages()
            tg.upload(o_files)
        else:
            up_path = f'{up_dir}/{up_name}'
            size = get_path_size(up_path)
            LOGGER.info(f"Upload Name: {up_name}")
            drive = GoogleDriveHelper(up_name, up_dir, size, self, self.message.from_user.id)
            upload_status = UploadStatus(drive, size, gid, self)
            with download_dict_lock:
                download_dict[self.uid] = upload_status
            update_all_messages()
            drive.upload(up_name, self.c_index)

    def onUploadComplete(self, link: str, size, files, folders, typ, name: str):
        if DATABASE_URL and config_dict['STOP_DUPLICATE_TASKS']:
            DbManger().remove_download(self.raw_url)
        if not self.isPrivate and config_dict['INCOMPLETE_TASK_NOTIFIER'] and DATABASE_URL:
            DbManger().rm_complete_task(self.message.link)
        if self.isLeech:
            msg = f'<b>Name</b>: <code>{escape(name)}</code>\n\n<b>Size</b>: {size}'
            msg += f'\n<b>Total Files</b>: {folders}'
            msg += f"\n<b>Elapsed</b>: {get_readable_time(time() - self.message.date.timestamp())}"
            if typ != 0:
                msg += f'\n<b>Corrupted Files</b>: {typ}'
            msg += f'\n<b>#cc</b>: {self.tag}'
            msg += f"\n<b>Upload</b>: {self.mode}\n\n"
            if not files:
                sendMessage(msg, self.bot, self.message)
            elif self.dmMessage:
                sendMessage(msg, self.bot, self.dmMessage)
                msg += '<b>Files has been sent in your DM.</b>'
                sendMessage(msg, self.bot, self.message)
            else:
                fmsg = ''
                for index, (link, name) in enumerate(files.items(), start=1):
                    fmsg += f"{index}. <a href='{link}'>{name}</a>\n"
                    if len(fmsg.encode() + msg.encode()) > 4000:
                        buttons = ButtonMaker()
                        buttons = extra_btns(buttons)
                        if self.message.chat.type != 'private':
                            buttons.sbutton('Save This Message', 'save', 'footer')
                        sendMarkup(msg + fmsg, self.bot, self.message, buttons.build_menu(2))
                        sleep(1)
                        fmsg = ''
                if fmsg != '':
                    buttons = ButtonMaker()
                    buttons = extra_btns(buttons)
                    if self.message.chat.type != 'private':
                        buttons.sbutton('Save This Message', 'save', 'footer')
                    sendMarkup(msg + fmsg, self.bot, self.message, buttons.build_menu(2))
            if self.seed:
                if self.newDir:
                    clean_target(self.newDir)
                return
        else:
            if SHORTENERES:
                msg = f'<b>Name</b>: <code>.{escape(name).replace(" ", "-").replace(".", ",")}</code>\n\n<b>Size</b>: {size}'
            else:
                msg = f'<b>Name</b>: <code>{escape(name)}</code>\n\n<b>Size</b>: {size}'
            msg += f'\n\n<b>Type</b>: {typ}'
            if typ == "Folder":
                msg += f' |<b>SubFolders</b>: {folders}'
                msg += f' |<b>Files</b>: {files}'
            msg += f'\n\n<b>#cc</b>: {self.tag} | <b>Elapsed</b>: {get_readable_time(time() - self.message.date.timestamp())}'
            msg += f"\n\n<b>Upload</b>: {self.mode}"
            buttons = ButtonMaker()
            if not config_dict['DISABLE_DRIVE_LINK']:
                link = short_url(link)
                buttons.buildbutton("🔐 Drive Link", link)    
            LOGGER.info(f'Done Uploading {name}')
            if INDEX_URL:= CATEGORY_INDEXS[self.c_index]:
                url_path = rutils.quote(f'{name}')
                if typ == "Folder":
                    share_url = short_url(f'{INDEX_URL}/{url_path}/')
                    buttons.buildbutton("📁 Index Link", share_url)
                else:
                    share_url = short_url(f'{INDEX_URL}/{url_path}')
                    buttons.buildbutton("🚀 Index Link", share_url)
                    if config_dict['VIEW_LINK']:
                        share_urls = short_url(f'{INDEX_URL}/{url_path}?a=view')
                        buttons.buildbutton("💻 View Link", share_urls)
            buttons = extra_btns(buttons)
            if self.dmMessage:
                sendMarkup(msg, self.bot, self.dmMessage, buttons.build_menu(2))
                msg += '\n\n<b>Links has been sent in your DM.</b>'
                sendMessage(msg, self.bot, self.message)
            else:
                if self.message.chat.type != 'private':
                    buttons.sbutton("Save This Message", 'save', 'footer')
                sendMarkup(msg, self.bot, self.message, buttons.build_menu(2))
            if self.seed:
                if self.isZip:
                    clean_target(f"{self.dir}/{name}")
                elif self.newDir:
                    clean_target(self.newDir)
                return
        self._clean_update()

    def onDownloadError(self, error):
        error = error.replace('<', ' ').replace('>', ' ')
        msg = f"{self.tag} your download has been stopped due to: {error}\n<b>Elapsed</b>: {get_readable_time(time() - self.message.date.timestamp())}"
        self._clean_update(msg)

    def onUploadError(self, error):
        e_str = error.replace('<', '').replace('>', '')
        msg = f"{self.tag} {e_str}\n<b>Elapsed</b>: {get_readable_time(time() - self.message.date.timestamp())}"
        self._clean_update(msg)

    def _clean_update(self, msg=None):
        clean_download(self.dir)
        if self.newDir:
            clean_download(self.newDir)
        with download_dict_lock:
            try:
                del download_dict[self.uid]
            except Exception as e:
                LOGGER.error(str(e))
            count = len(download_dict)
        if msg:
            msg += f"\n<b>Upload</b>: {self.mode}"
            sendMessage(msg, self.bot, self.message)
        if count == 0:
            self.clean()
        else:
            update_all_messages()
        if DATABASE_URL and config_dict['STOP_DUPLICATE_TASKS']:
            DbManger().remove_download(self.raw_url)
        if not self.isPrivate and config_dict['INCOMPLETE_TASK_NOTIFIER'] and DATABASE_URL:
            DbManger().rm_complete_task(self.message.link)
