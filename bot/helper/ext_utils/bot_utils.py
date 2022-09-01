from re import findall as re_findall
from threading import Thread, Event
from time import time
from math import ceil
from html import escape
from psutil import disk_usage
from requests import head as rhead
from urllib.request import urlopen
from urllib.parse import urlparse

from bot import download_dict, download_dict_lock, botStartTime, DOWNLOAD_DIR, BASE_URL, WEB_PINCODE, STATUS_LIMIT
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.button_build import ButtonMaker

MAGNET_REGEX = r"magnet:\?xt=urn:btih:[a-zA-Z0-9]*"
PROGRESS_INCOMPLETE = ['○','◔', '◑', '◕', '⬤', '○','◔', '◑', '◕','⬤']

COUNT = 0
PAGE_NO = 1


class MirrorStatus:
    STATUS_UPLOADING = "Uploading..."
    STATUS_DOWNLOADING = "Downloading..."
    STATUS_CLONING = "Cloning..."
    STATUS_WAITING = "Queued..."
    STATUS_PAUSED = "Paused..."
    STATUS_ARCHIVING = "Archiving..."
    STATUS_EXTRACTING = "Extracting..."
    STATUS_SPLITTING = "Splitting..."
    STATUS_CHECKING = "CheckingUp..."
    STATUS_SEEDING = "Seeding..."
    STATUS_CONVERTING = "Converting..."

SIZE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']


class setInterval:
    def __init__(self, interval, action):
        self.interval = interval
        self.action = action
        self.stopEvent = Event()
        thread = Thread(target=self.__setInterval)
        thread.start()

    def __setInterval(self):
        nextTime = time() + self.interval
        while not self.stopEvent.wait(nextTime - time()):
            nextTime += self.interval
            self.action()

    def cancel(self):
        self.stopEvent.set()

def get_readable_file_size(size_in_bytes) -> str:
    if size_in_bytes is None:
        return '0B'
    index = 0
    while size_in_bytes >= 1024:
        size_in_bytes /= 1024
        index += 1
    try:
        return f'{round(size_in_bytes, 2)}{SIZE_UNITS[index]}'
    except IndexError:
        return 'File too large'

def getDownloadByGid(gid):
    with download_dict_lock:
        for dl in list(download_dict.values()):
            if dl.gid() == gid:
                return dl
    return None

def getAllDownload(req_status: str, user_id: int = None, onece: bool = True):
    dls = []
    with download_dict_lock:
        for dl in list(download_dict.values()):
            if user_id and user_id != dl.message.from_user.id:
                continue
            status = dl.status()
            if req_status in ['all', status]:
                if onece:
                    return dl
                else:
                    dls.append(dl)
    return None if onece else dls

def bt_selection_buttons(id_: str, isCanCncl: bool = True):
    gid = id_[:12] if len(id_) > 20 else id_
    pincode = ""
    for n in id_:
        if n.isdigit():
            pincode += str(n)
        if len(pincode) == 4:
            break

    buttons = ButtonMaker()
    if WEB_PINCODE:
        buttons.buildbutton("Select Files", f"{BASE_URL}/app/files/{id_}")
        buttons.sbutton("Pincode", f"btsel pin {gid} {pincode}")
    else:
        buttons.buildbutton("Select Files", f"{BASE_URL}/app/files/{id_}?pin_code={pincode}")
    buttons.sbutton("Done Selecting", f"btsel done {gid} {id_}")
    if isCanCncl:
        buttons.sbutton("Cancel", f"btsel rm {gid} {id_}")
    return buttons.build_menu(2)

def get_progress_bar_string(status):
    completed = status.processed_bytes() / 9
    total = status.size_raw() / 9
    p = 0 if total == 0 else round(completed * 100 / total)
    p = min(max(p, 0), 100)
    cFull = p // 9
    cPart = p % 9 - 1
    p_str = "⬤" * cFull
    if cPart >= 0:
        p_str += PROGRESS_INCOMPLETE[cPart]
    p_str += "○" * (11 - cFull)
    p_str = f"「{p_str}」"
    return p_str

def get_readable_message():
    with download_dict_lock:
        msg = ""
        if STATUS_LIMIT is not None:
            tasks = len(download_dict)
            global pages
            pages = ceil(tasks/STATUS_LIMIT)
            if PAGE_NO > pages and pages != 0:
                globals()['COUNT'] -= STATUS_LIMIT
                globals()['PAGE_NO'] -= 1
        for index, download in enumerate(list(download_dict.values())[COUNT:], start=1):
            msg += f"<code>{escape(str(download.name()))}</code>"
            msg += f"\n<b>Status</b>: <i>{download.status()}</i>"
            if download.status() not in [MirrorStatus.STATUS_SPLITTING, MirrorStatus.STATUS_SEEDING, MirrorStatus.STATUS_CONVERTING]:
                msg += f"\n{get_progress_bar_string(download)} {download.progress()}"
                msg += f"\n<b>Processed</b>: {get_readable_file_size(download.processed_bytes())} of {download.size()}"
                msg += f"\n<b>Speed</b>: {download.speed()} | <b>ETA</b>: {download.eta()}"
                if hasattr(download, 'seeders_num'):
                    try:
                        msg += f"\n<b>Seeders</b>: {download.seeders_num()} | <b>Leechers</b>: {download.leechers_num()}"
                    except:
                        pass
            elif download.status() == MirrorStatus.STATUS_SEEDING:
                msg += f"\n<b>Size</b>: {download.size()}"
                msg += f"\n<b>Speed</b>: {download.upload_speed()}"
                msg += f" | <b>Uploaded</b>: {download.uploaded_bytes()}"
                msg += f"\n<b>Ratio</b>: {download.ratio()}"
                msg += f" | <b>Time</b>: {download.seeding_time()}"
            else:
                msg += f"\n<b>Size</b>: {download.size()}"
            msg += f"\n<b>Source</b>: <a href='{download.message.link}'>{download.source()}</a>"
            msg += f"\n<b>Elapsed</b>: {get_readable_time(time() - download.message.date.timestamp())}"
            if hasattr(download, 'playList'):
                try:
                    playlist = download.playList()
                    if playlist:
                        msg += f"\n<b>Playlist</b>: {playlist}"
                except:
                    pass
            msg += f"\n<b>Engine</b>: {download.engine()}"
            msg += f"\n<b>Mode</b>: {download.mode()}"
            msg += f"\n<code>/{BotCommands.CancelMirror} {download.gid()}</code>"
            msg += "\n\n"
            if STATUS_LIMIT is not None and index == STATUS_LIMIT:
                break
        if len(msg) == 0:
            return None, None
        dl_speed = 0
        up_speed = 0
        for download in list(download_dict.values()):
            if download.status() == MirrorStatus.STATUS_DOWNLOADING:
                spd = download.speed()
                if 'K' in spd:
                    dl_speed += float(spd.split('K')[0]) * 1024
                elif 'M' in spd:
                    dl_speed += float(spd.split('M')[0]) * 1048576
            elif download.status() == MirrorStatus.STATUS_UPLOADING:
                spd = download.speed()
                if 'KB/s' in spd:
                    up_speed += float(spd.split('K')[0]) * 1024
                elif 'MB/s' in spd:
                    up_speed += float(spd.split('M')[0]) * 1048576
            elif download.status() == MirrorStatus.STATUS_SEEDING:
                spd = download.upload_speed()
                if 'K' in spd:
                    up_speed += float(spd.split('K')[0]) * 1024
                elif 'M' in spd:
                    up_speed += float(spd.split('M')[0]) * 1048576
        bmsg = f"<b>Free</b>: {get_readable_file_size(disk_usage(DOWNLOAD_DIR).free)} | <b>Uptime</b>: {get_readable_time(time() - botStartTime)}" \
                f"\n<b>DL</b>: {get_readable_file_size(dl_speed)}/s | <b>UL</b>: {get_readable_file_size(up_speed)}/s"
        buttons = ButtonMaker()
        buttons.sbutton("Statistics", "status stats")
        button = buttons.build_menu(1)
        if STATUS_LIMIT is not None and tasks > STATUS_LIMIT:
            buttons = ButtonMaker()
            buttons.sbutton("Previous", "status pre")
            buttons.sbutton(f"{PAGE_NO}/{pages}", "status stats")
            buttons.sbutton("Next", "status nex")
            button = buttons.build_menu(3)
        return msg + bmsg, button

def turn(data):
    try:
        with download_dict_lock:
            global COUNT, PAGE_NO
            if data[1] == "nex":
                if PAGE_NO == pages:
                    COUNT = 0
                    PAGE_NO = 1
                else:
                    COUNT += STATUS_LIMIT
                    PAGE_NO += 1
            elif data[1] == "pre":
                if PAGE_NO == 1:
                    COUNT = STATUS_LIMIT * (pages - 1)
                    PAGE_NO = pages
                else:
                    COUNT -= STATUS_LIMIT
                    PAGE_NO -= 1
            elif data[1] == "stats":
                return "stats"
        return True
    except:
        return False

def get_readable_time(seconds: int) -> str:
    result = ''
    (days, remainder) = divmod(seconds, 86400)
    days = int(days)
    if days != 0:
        result += f'{days}d'
    (hours, remainder) = divmod(remainder, 3600)
    hours = int(hours)
    if hours != 0:
        result += f'{hours}h'
    (minutes, seconds) = divmod(remainder, 60)
    minutes = int(minutes)
    if minutes != 0:
        result += f'{minutes}m'
    seconds = int(seconds)
    result += f'{seconds}s'
    return result

def is_url(url: str):
    try:
        return urlparse(url).scheme in ['http','https', 'ftp']
    except:
        return False

def is_gdrive_link(url: str):
    return "drive.google.com" in urlparse(url).netloc

def is_sharer_link(url: str):
    domain = urlparse(url).netloc
    return any(x in domain for x in ['gdtot', 'appdrive', 'driveapp', 'hubdrive'])

def is_mega_link(url: str):
    domain = urlparse(url).netloc
    return any(x in domain for x in ['mega.nz', 'mega.co.nz'])

def get_mega_link_type(url: str):
    if "folder" in url:
        return "folder"
    elif "file" in url:
        return "file"
    elif "/#F!" in url:
        return "folder"
    return "file"

def is_magnet(url: str):
    magnet = re_findall(MAGNET_REGEX, url)
    return bool(magnet)

def new_thread(fn):
    """To use as decorator to make a function call threaded.
    Needs import
    from threading import Thread"""

    def wrapper(*args, **kwargs):
        thread = Thread(target=fn, args=args, kwargs=kwargs)
        thread.start()
        return thread

    return wrapper

def get_content_type(link: str) -> str:
    try:
        res = rhead(link, allow_redirects=True, timeout=5, headers = {'user-agent': 'Wget/1.12'})
        content_type = res.headers.get('content-type')
    except:
        try:
            res = urlopen(link, timeout=5)
            info = res.info()
            content_type = info.get_content_type()
        except:
            content_type = None
    return content_type