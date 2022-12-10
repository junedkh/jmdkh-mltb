from random import SystemRandom
from string import ascii_letters, digits

from bot import LOGGER, config_dict, download_dict, download_dict_lock
from bot.helper.ext_utils.bot_utils import get_readable_file_size
from bot.helper.ext_utils.fs_utils import (check_storage_threshold,
                                           get_base_name)
from bot.helper.mirror_utils.status_utils.gd_download_status import GdDownloadStatus
from bot.helper.mirror_utils.upload_utils.gdriveTools import GoogleDriveHelper
from bot.helper.telegram_helper.message_utils import (sendMarkup, sendMessage,
                                                      sendStatusMessage)


def add_gd_download(link, path, listener, newname):
    drive = GoogleDriveHelper()
    res, size, name, _ = drive.helper(link)
    if res != "":
        return sendMessage(res, listener.bot, listener.message)
    if newname:
        name = newname
    if config_dict['STOP_DUPLICATE'] and not listener.isLeech:
        LOGGER.info('Checking File/Folder if already in Drive...')
        if listener.isZip:
            gname = f"{name}.zip"
        elif listener.extract:
            try:
                gname = get_base_name(name)
            except:
                gname = None
        if gname:
            gmsg, button = GoogleDriveHelper().drive_list(gname, True)
            if gmsg:
                msg = "File/Folder is already available in Drive.\nHere are the search results:"
                return sendMarkup(msg, listener.bot, listener.message, button)
    if STORAGE_THRESHOLD:= config_dict['STORAGE_THRESHOLD']:
        arch = any([listener.extract, listener.isZip])
        acpt = check_storage_threshold(size, arch)
        if not acpt:
            msg = f'You must leave {STORAGE_THRESHOLD}GB free storage.'
            msg += f'\nYour File/Folder size is {get_readable_file_size(size)}'
            return sendMessage(msg, listener.bot, listener.message)
    if GDRIVE_LIMIT:= config_dict['GDRIVE_LIMIT']:
        limit = GDRIVE_LIMIT * 1024**3
        mssg = f'Google drive limit is {get_readable_file_size(limit)}'
        if size > limit:
            msg = f'{mssg}.\nYour File/Folder size is {get_readable_file_size(size)}.'
            return sendMessage(msg, listener.bot, listener.message)
    if LEECH_LIMIT:= config_dict['LEECH_LIMIT']:
        if listener.isLeech:
            limit = LEECH_LIMIT * 1024**3
            mssg = f'Leech limit is {get_readable_file_size(limit)}'
            if size > limit:
                msg = f'{mssg}.\nYour File/Folder size is {get_readable_file_size(size)}.'
                return sendMessage(msg, listener.bot, listener.message)
    LOGGER.info(f"Download Name: {name}")
    drive = GoogleDriveHelper(name, path, size, listener, listener.message.from_user.id)
    gid = ''.join(SystemRandom().choices(ascii_letters + digits, k=12))
    download_status = GdDownloadStatus(drive, size, listener, gid)
    with download_dict_lock:
        download_dict[listener.uid] = download_status
    listener.onDownloadStart()
    sendStatusMessage(listener.message, listener.bot)
    drive.download(link)
