#!/usr/bin/env python3
from io import FileIO
from logging import ERROR, getLogger
from os import listdir, makedirs
from os import path as ospath
from os import remove as osremove
from pickle import load as pload
from random import randrange
from re import search as re_search
from time import time
from urllib.parse import parse_qs
from urllib.parse import quote as rquote
from urllib.parse import urlparse

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from tenacity import (RetryError, retry, retry_if_exception_type,
                      stop_after_attempt, wait_exponential)

from bot import GLOBAL_EXTENSION_FILTER, SHORTENERES, config_dict, list_drives
from bot.helper.ext_utils.bot_utils import (async_to_sync, extra_btns,
                                            get_readable_file_size,
                                            setInterval)
from bot.helper.ext_utils.fs_utils import get_mime_type
from bot.helper.ext_utils.shortener import short_url
from bot.helper.ext_utils.telegraph_helper import telegraph
from bot.helper.telegram_helper.button_build import ButtonMaker

LOGGER = getLogger(__name__)
getLogger('googleapiclient.discovery').setLevel(ERROR)


class GoogleDriveHelper:

    def __init__(self, name=None, path=None, listener=None):
        self.__G_DRIVE_TOKEN_FILE = "token.pickle"
        self.__OAUTH_SCOPE = ['https://www.googleapis.com/auth/drive']
        self.__G_DRIVE_DIR_MIME_TYPE = "application/vnd.google-apps.folder"
        self.__G_DRIVE_BASE_DOWNLOAD_URL = "https://drive.google.com/uc?id={}&export=download"
        self.__G_DRIVE_DIR_BASE_DOWNLOAD_URL = "https://drive.google.com/drive/folders/{}"
        self.__listener = listener
        self.__path = path
        self.__total_bytes = 0
        self.__total_files = 0
        self.__total_folders = 0
        self.__start_time = 0
        self.__total_time = 0
        self.__alt_auth = False
        self.__is_uploading = False
        self.__is_downloading = False
        self.__is_cloning = False
        self.__is_cancelled = False
        self.__is_errored = False
        self.__status = None
        self.__updater = None
        self.__update_interval = 3
        self.__sa_index = 0
        self.__sa_count = 1
        self.__sa_number = 100
        self.__service = self.__authorize()
        self._file_processed_bytes = 0
        self.name = name
        self.processed_bytes = 0
        self.transferred_size = 0

    def speed(self):
        try:
            return self.processed_bytes / self.__total_time
        except:
            return 0

    def cspeed(self):
        try:
            return self.transferred_size / int(time() - self.__start_time)
        except:
            return 0

    def __authorize(self):
        credentials = None
        if config_dict['USE_SERVICE_ACCOUNTS']:
            json_files = listdir("accounts")
            self.__sa_number = len(json_files)
            if self.__sa_count == 0:
                self.__sa_index = randrange(self.__sa_number)
            LOGGER.info(
                f"Authorizing with {json_files[self.__sa_index]} service account")
            credentials = service_account.Credentials.from_service_account_file(
                f'accounts/{json_files[self.__sa_index]}',
                scopes=self.__OAUTH_SCOPE)
        elif ospath.exists(self.__G_DRIVE_TOKEN_FILE):
            LOGGER.info("Authorize with token.pickle")
            with open(self.__G_DRIVE_TOKEN_FILE, 'rb') as f:
                credentials = pload(f)
        else:
            LOGGER.error('token.pickle not found!')
        return build('drive', 'v3', credentials=credentials, cache_discovery=False)

    def __alt_authorize(self):
        credentials = None
        if config_dict['USE_SERVICE_ACCOUNTS'] and not self.__alt_auth:
            self.__alt_auth = True
            if ospath.exists(self.__G_DRIVE_TOKEN_FILE):
                LOGGER.info("Authorize with token.pickle")
                with open(self.__G_DRIVE_TOKEN_FILE, 'rb') as f:
                    credentials = pload(f)
                return build('drive', 'v3', credentials=credentials, cache_discovery=False)
        return None

    def __switchServiceAccount(self):
        if self.__sa_index == self.__sa_number - 1:
            self.__sa_index = 0
        else:
            self.__sa_index += 1
        self.__sa_count += 1
        LOGGER.info(f"Switching to {self.__sa_index} index")
        self.__service = self.__authorize()

    @staticmethod
    def getIdFromUrl(link):
        if "folders" in link or "file" in link:
            regex = r"https:\/\/drive\.google\.com\/(?:drive(.*?)\/folders\/|file(.*?)?\/d\/)([-\w]+)"
            res = re_search(regex, link)
            if res is None:
                raise IndexError("G-Drive ID not found.")
            return res.group(3)
        parsed = urlparse(link)
        return parse_qs(parsed.query)['id'][0]

    @retry(wait=wait_exponential(multiplier=2, min=3, max=6), stop=stop_after_attempt(3),
           retry=retry_if_exception_type(Exception))
    def __set_permission(self, file_id):
        permissions = {
            'role': 'reader',
            'type': 'anyone',
            'value': None,
            'withLink': True
        }
        return self.__service.permissions().create(fileId=file_id, body=permissions, supportsAllDrives=True).execute()

    @retry(wait=wait_exponential(multiplier=2, min=3, max=6), stop=stop_after_attempt(3),
           retry=retry_if_exception_type(Exception))
    def __getFileMetadata(self, file_id):
        return self.__service.files().get(fileId=file_id, supportsAllDrives=True,
                                          fields='name, id, mimeType, size').execute()

    @retry(wait=wait_exponential(multiplier=2, min=3, max=6), stop=stop_after_attempt(3),
           retry=retry_if_exception_type(Exception))
    def getFolderData(self, file_id):
        try:
            meta = self.__service.files().get(fileId=file_id, supportsAllDrives=True).execute()
            if meta.get('mimeType', '') == self.__G_DRIVE_DIR_MIME_TYPE:
                return meta.get('name')
        except:
            return

    @retry(wait=wait_exponential(multiplier=2, min=3, max=6), stop=stop_after_attempt(3),
           retry=retry_if_exception_type(Exception))
    def __getFilesByFolderId(self, folder_id):
        page_token = None
        files = []
        while True:
            response = self.__service.files().list(supportsAllDrives=True, includeItemsFromAllDrives=True,
                                                   q=f"'{folder_id}' in parents and trashed = false",
                                                   spaces='drive', pageSize=200,
                                                   fields='nextPageToken, files(id, name, mimeType, size, shortcutDetails)',
                                                   orderBy='folder, name', pageToken=page_token).execute()
            files.extend(response.get('files', []))
            page_token = response.get('nextPageToken')
            if page_token is None:
                break
        return files

    async def __progress(self):
        if self.__status is not None:
            chunk_size = self.__status.total_size * \
                self.__status.progress() - self._file_processed_bytes
            self._file_processed_bytes = self.__status.total_size * self.__status.progress()
            self.processed_bytes += chunk_size
            self.__total_time += self.__update_interval

    def deletefile(self, link: str):
        try:
            file_id = self.getIdFromUrl(link)
        except (KeyError, IndexError):
            return "Google Drive ID could not be found in the provided link"
        msg = ''
        try:
            self.__service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
            msg = "Successfully deleted"
            LOGGER.info(f"Delete Result: {msg}")
        except HttpError as err:
            if "File not found" in str(err):
                msg = "No such file exist"
            elif "insufficientFilePermissions" in str(err):
                msg = "Insufficient File Permissions"
                token_service = self.__alt_authorize()
                if token_service is not None:
                    self.__service = token_service
                    return self.deletefile(link)
            else:
                msg = err
            LOGGER.error(f"Delete Result: {msg}")
        finally:
            return msg

    def upload(self, file_name, size, gdrive_id):
        self.__is_uploading = True
        item_path = f"{self.__path}/{file_name}"
        LOGGER.info(f"Uploading: {item_path}")
        self.__updater = setInterval(self.__update_interval, self.__progress)
        try:
            if ospath.isfile(item_path):
                mime_type = get_mime_type(item_path)
                dir_id = gdrive_id
                link = self.__upload_file(
                    item_path, file_name, mime_type, dir_id, is_dir=False)
                if self.__is_cancelled:
                    return
                if link is None:
                    raise Exception('Upload has been manually cancelled')
                LOGGER.info(f"Uploaded To G-Drive: {item_path}")
            else:
                mime_type = 'Folder'
                dir_id = self.__create_directory(ospath.basename(
                    ospath.abspath(file_name)), gdrive_id)
                result = self.__upload_dir(item_path, dir_id)
                if result is None:
                    raise Exception('Upload has been manually cancelled!')
                link = self.__G_DRIVE_DIR_BASE_DOWNLOAD_URL.format(dir_id)
                if self.__is_cancelled:
                    return
                LOGGER.info(f"Uploaded To G-Drive: {file_name}")
        except Exception as err:
            if isinstance(err, RetryError):
                LOGGER.info(
                    f"Total Attempts: {err.last_attempt.attempt_number}")
                err = err.last_attempt.exception()
            err = str(err).replace('>', '').replace('<', '')
            async_to_sync(self.__listener.onUploadError, err)
            self.__is_errored = True
        finally:
            self.__updater.cancel()
            if self.__is_cancelled and not self.__is_errored:
                if mime_type == 'Folder':
                    LOGGER.info("Deleting uploaded data from Drive...")
                    link = self.__G_DRIVE_DIR_BASE_DOWNLOAD_URL.format(dir_id)
                    self.deletefile(link)
                return
            elif self.__is_errored:
                return
        async_to_sync(self.__listener.onUploadComplete, link, size, self.__total_files,
                      self.__total_folders, mime_type, file_name, drive_id=dir_id)

    def __upload_dir(self, input_directory, dest_id):
        list_dirs = listdir(input_directory)
        if len(list_dirs) == 0:
            return dest_id
        new_id = None
        for item in list_dirs:
            current_file_name = ospath.join(input_directory, item)
            if ospath.isdir(current_file_name):
                current_dir_id = self.__create_directory(item, dest_id)
                new_id = self.__upload_dir(current_file_name, current_dir_id)
                self.__total_folders += 1
            elif not item.lower().endswith(tuple(GLOBAL_EXTENSION_FILTER)):
                mime_type = get_mime_type(current_file_name)
                file_name = current_file_name.split("/")[-1]
                # current_file_name will have the full path
                self.__upload_file(current_file_name,
                                   file_name, mime_type, dest_id)
                self.__total_files += 1
                new_id = dest_id
            else:
                osremove(current_file_name)
                new_id = 'filter'
            if self.__is_cancelled:
                break
        return new_id

    @retry(wait=wait_exponential(multiplier=2, min=3, max=6), stop=stop_after_attempt(3),
           retry=retry_if_exception_type(Exception))
    def __create_directory(self, directory_name, dest_id):
        file_metadata = {
            "name": directory_name,
            "description": f'Uploaded by {self.__listener.message.from_user.id}',
            "mimeType": self.__G_DRIVE_DIR_MIME_TYPE
        }
        if dest_id is not None:
            file_metadata["parents"] = [dest_id]
        file = self.__service.files().create(
            body=file_metadata, supportsAllDrives=True).execute()
        file_id = file.get("id")
        if not config_dict['IS_TEAM_DRIVE']:
            self.__set_permission(file_id)
        LOGGER.info(
            f'Created G-Drive Folder:\nName: {file.get("name")}')
        return file_id

    @retry(wait=wait_exponential(multiplier=2, min=3, max=6), stop=stop_after_attempt(3),
           retry=(retry_if_exception_type(Exception)))
    def __upload_file(self, file_path, file_name, mime_type, dest_id, is_dir=True):
        # File body description
        file_metadata = {
            'name': file_name,
            'description': f'Uploaded by {self.__listener.message.from_user.id}',
            'mimeType': mime_type,
        }
        if dest_id is not None:
            file_metadata['parents'] = [dest_id]

        if ospath.getsize(file_path) == 0:
            media_body = MediaFileUpload(file_path,
                                         mimetype=mime_type,
                                         resumable=False)
            response = self.__service.files().create(body=file_metadata, media_body=media_body,
                                                     supportsAllDrives=True).execute()
            if not config_dict['IS_TEAM_DRIVE']:
                self.__set_permission(response['id'])

            drive_file = self.__service.files().get(
                fileId=response['id'], supportsAllDrives=True).execute()
            return self.__G_DRIVE_BASE_DOWNLOAD_URL.format(drive_file.get('id'))
        media_body = MediaFileUpload(file_path,
                                     mimetype=mime_type,
                                     resumable=True,
                                     chunksize=100 * 1024 * 1024)

        # Insert a file
        drive_file = self.__service.files().create(
            body=file_metadata, media_body=media_body, supportsAllDrives=True)
        response = None
        retries = 0
        while response is None and not self.__is_cancelled:
            try:
                self.__status, response = drive_file.next_chunk()
            except HttpError as err:
                if err.resp.status in [500, 502, 503, 504] and retries < 10:
                    retries += 1
                    continue
                if err.resp.get('content-type', '').startswith('application/json'):
                    reason = eval(err.content).get(
                        'error').get('errors')[0].get('reason')
                    if reason not in [
                        'userRateLimitExceeded',
                        'dailyLimitExceeded',
                    ]:
                        raise err
                    if config_dict['USE_SERVICE_ACCOUNTS']:
                        if self.__sa_count >= self.__sa_number:
                            LOGGER.info(
                                f"Reached maximum number of service accounts switching, which is {self.__sa_count}")
                            raise err
                        else:
                            if self.__is_cancelled:
                                return
                            self.__switchServiceAccount()
                            LOGGER.info(f"Got: {reason}, Trying Again.")
                            return self.__upload_file(file_path, file_name, mime_type, dest_id)
                    else:
                        LOGGER.error(f"Got: {reason}")
                        raise err
        if self.__is_cancelled:
            return
        if not self.__listener.seed or self.__listener.newDir:
            try:
                osremove(file_path)
            except:
                pass
        self._file_processed_bytes = 0
        # Insert new permissions
        if not config_dict['IS_TEAM_DRIVE']:
            self.__set_permission(response['id'])
        # Define file instance and get url for download
        if not is_dir:
            drive_file = self.__service.files().get(
                fileId=response['id'], supportsAllDrives=True).execute()
            return self.__G_DRIVE_BASE_DOWNLOAD_URL.format(drive_file.get('id'))
        return

    def clone(self, link, gdrive_id):
        self.__is_cloning = True
        self.__start_time = time()
        self.__total_files = 0
        self.__total_folders = 0
        try:
            file_id = self.getIdFromUrl(link)
        except (KeyError, IndexError):
            return async_to_sync(self.__listener.onDownloadError, "Google Drive ID could not be found in the provided link")
        LOGGER.info(f"File ID: {file_id}")
        try:
            meta = self.__getFileMetadata(file_id)
            mime_type = meta.get("mimeType")
            if mime_type == self.__G_DRIVE_DIR_MIME_TYPE:
                dir_id = self.__create_directory(meta.get('name'), gdrive_id)
                self.__cloneFolder(meta.get('name'), meta.get(
                    'name'), meta.get('id'), dir_id)
                durl = self.__G_DRIVE_DIR_BASE_DOWNLOAD_URL.format(dir_id)
                if self.__is_cancelled:
                    LOGGER.info("Deleting cloned data from Drive...")
                    self.deletefile(durl)
                    return async_to_sync(self.__listener.onDownloadError, "your clone has been stopped and cloned data has been deleted!")
                size = self.transferred_size
                mime_type = "Folder"
            else:
                dir_id = gdrive_id
                file = self.__copyFile(meta.get('id'), dir_id)
                durl = self.__G_DRIVE_BASE_DOWNLOAD_URL.format(file.get("id"))
                if mime_type is None:
                    mime_type = 'File'
                size = int(meta.get("size", 0))
        except Exception as err:
            if isinstance(err, RetryError):
                LOGGER.info(
                    f"Total Attempts: {err.last_attempt.attempt_number}")
                err = err.last_attempt.exception()
            err = str(err).replace('>', '').replace('<', '')
            if "File not found" in err:
                if token_service := self.__alt_authorize():
                    self.__service = token_service
                    return self.clone(link, gdrive_id)
                async_to_sync(self.__listener.onDownloadError,
                              "File not found.")
            elif "User rate limit exceeded" in err:
                async_to_sync(self.__listener.onDownloadError,
                              "User rate limit exceeded.")
            else:
                self.__listener.onDownloadError(f"Error.\n{err}")
            return
        return async_to_sync(self.__listener.onUploadComplete, durl, size, self.__total_files, self.__total_folders, mime_type, meta.get("name"), drive_id=dir_id)

    def __cloneFolder(self, name, local_path, folder_id, dest_id):
        LOGGER.info(f"Syncing: {local_path}")
        files = self.__getFilesByFolderId(folder_id)
        if len(files) == 0:
            return dest_id
        for file in files:
            if file.get('mimeType') == self.__G_DRIVE_DIR_MIME_TYPE:
                self.__total_folders += 1
                file_path = ospath.join(local_path, file.get('name'))
                current_dir_id = self.__create_directory(
                    file.get('name'), dest_id)
                self.__cloneFolder(file.get('name'), file_path,
                                   file.get('id'), current_dir_id)
            elif not file.get('name').lower().endswith(tuple(GLOBAL_EXTENSION_FILTER)):
                self.__total_files += 1
                self.transferred_size += int(file.get('size', 0))
                self.__copyFile(file.get('id'), dest_id)
            if self.__is_cancelled:
                break

    @retry(wait=wait_exponential(multiplier=2, min=3, max=6), stop=stop_after_attempt(3),
           retry=retry_if_exception_type(Exception))
    def __copyFile(self, file_id, dest_id):
        body = {'parents': [dest_id]}
        try:
            return self.__service.files().copy(fileId=file_id, body=body, supportsAllDrives=True).execute()
        except HttpError as err:
            if err.resp.get('content-type', '').startswith('application/json'):
                reason = eval(err.content).get(
                    'error').get('errors')[0].get('reason')
                if reason not in ['userRateLimitExceeded', 'dailyLimitExceeded', 'cannotCopyFile']:
                    raise err
                if reason == 'cannotCopyFile':
                    LOGGER.error(err)
                elif config_dict['USE_SERVICE_ACCOUNTS']:
                    if self.__sa_count >= self.__sa_number:
                        LOGGER.info(
                            f"Reached maximum number of service accounts switching, which is {self.__sa_count}")
                        raise err
                    else:
                        if self.__is_cancelled:
                            return
                        self.__switchServiceAccount()
                        return self.__copyFile(file_id, dest_id)
                else:
                    LOGGER.error(f"Got: {reason}")
                    raise err

    def __escapes(self, estr):
        chars = ['\\', "'", '"', r'\a', r'\b', r'\f', r'\n', r'\r', r'\t']
        for char in chars:
            estr = estr.replace(char, f'\\{char}')
        return estr.strip()

    def __get_recursive_list(self, file, rootid):
        rtnlist = []
        # if not rootid:
        #    rootid = file.get('teamDriveId')
        if rootid == "root":
            rootid = self.__service.files().get(
                fileId='root', fields='id').execute().get('id')
        x = file.get("name")
        y = file.get("id")
        while (y != rootid):
            rtnlist.append(x)
            file = self.__service.files().get(fileId=file.get("parents")[0], supportsAllDrives=True,
                                              fields='id, name, parents').execute()
            x = file.get("name")
            y = file.get("id")
        rtnlist.reverse()
        return rtnlist

    def __drive_query(self, dir_id, fileName, stopDup, isRecursive, itemType):
        try:
            if isRecursive:
                if stopDup:
                    query = f"name = '{fileName}' and "
                else:
                    fileName = fileName.split()
                    query = "".join(
                        f"name contains '{name}' and "
                        for name in fileName
                        if name != ''
                    )
                    if itemType == "files":
                        query += "mimeType != 'application/vnd.google-apps.folder' and "
                    elif itemType == "folders":
                        query += "mimeType = 'application/vnd.google-apps.folder' and "
                query += "trashed = false"
                if dir_id == "root":
                    return self.__service.files().list(q=f"{query} and 'me' in owners",
                                                       pageSize=200, spaces='drive',
                                                       fields='files(id, name, mimeType, size, parents)',
                                                       orderBy='folder, name asc').execute()
                else:
                    return self.__service.files().list(supportsAllDrives=True, includeItemsFromAllDrives=True,
                                                       driveId=dir_id, q=query, spaces='drive', pageSize=200,
                                                       fields='files(id, name, mimeType, size, teamDriveId, parents)',
                                                       corpora='drive', orderBy='folder, name asc').execute()
            else:
                if stopDup:
                    query = f"'{dir_id}' in parents and name = '{fileName}' and "
                else:
                    query = f"'{dir_id}' in parents and "
                    fileName = fileName.split()
                    for name in fileName:
                        if name != '':
                            query += f"name contains '{name}' and "
                    if itemType == "files":
                        query += "mimeType != 'application/vnd.google-apps.folder' and "
                    elif itemType == "folders":
                        query += "mimeType = 'application/vnd.google-apps.folder' and "
                query += "trashed = false"
                return self.__service.files().list(supportsAllDrives=True, includeItemsFromAllDrives=True,
                                                   q=query, spaces='drive', pageSize=200,
                                                   fields='files(id, name, mimeType, size)',
                                                   orderBy='folder, name asc').execute()
        except Exception as err:
            err = str(err).replace('>', '').replace('<', '')
            LOGGER.error(err)
            return {'files': []}

    def drive_list(self, fileName, stopDup=False, noMulti=False, isRecursive=True, itemType=""):
        msg = ""
        fileName = self.__escapes(str(fileName))
        contents_count = 0
        telegraph_content = []
        Title = False
        if len(list_drives) > 1:
            if token_service := self.__alt_authorize():
                self.__service = token_service
        for drive_name, drive_dict in list_drives.items():
            dir_id = drive_dict['drive_id']
            index_url = drive_dict['index_link']
            isRecur = False if isRecursive and len(
                dir_id) > 23 else isRecursive
            response = self.__drive_query(
                dir_id, fileName, stopDup, isRecur, itemType)
            if not response["files"]:
                if noMulti:
                    break
                else:
                    continue
            if not Title:
                msg += f'<h4>Search Result For {fileName}</h4>'
                Title = True
            if drive_name:
                msg += f"╾────────────╼<br><b>{drive_name}</b><br>╾────────────╼<br>"
            for file in response.get('files', []):
                mime_type = file.get('mimeType')
                if mime_type == "application/vnd.google-apps.folder":
                    if SHORTENERES:
                        msg += f"📁 .<code>{file.get('name').replace(' ', '-').replace('.', ',')}<br>(folder)</code><br>"
                    else:
                        msg += f"📁 <code>{file.get('name')}<br>(folder)</code><br>"
                    if not config_dict['DISABLE_DRIVE_LINK']:
                        furl = short_url(
                            f"https://drive.google.com/drive/folders/{file.get('id')}")
                        msg += f"<b><a href={furl}>Drive Link</a></b>"
                    if index_url:
                        if isRecur:
                            url_path = "/".join([rquote(n, safe='')
                                                for n in self.__get_recursive_list(file, dir_id)])
                        else:
                            url_path = rquote(f'{file.get("name")}', safe='')
                        url = short_url(f'{index_url}/{url_path}/')
                        msg += f' 📁 <b>| <a href={url}>Index Link</a></b>'
                elif mime_type == 'application/vnd.google-apps.shortcut':
                    if not config_dict['DISABLE_DRIVE_LINK']:
                        furl = short_url(
                            f"https://drive.google.com/drive/folders/{file.get('id')}")
                        if SHORTENERES:
                            msg += f"⁍<a href={furl}>{file.get('name').replace(' ', '-').replace('.', ',')}" \
                                f"</a> (shortcut)"
                        else:
                            msg += f"⁍<a href={furl}>{file.get('name')}" \
                                   f"</a> (shortcut)"
                else:
                    if SHORTENERES:
                        msg += f"📄 <code>{file.get('name').replace(' ', '-').replace('.', ',')}<br>({get_readable_file_size(int(file.get('size', 0)))})</code><br>"
                    else:
                        msg += f"📄 <code>{file.get('name')}<br>({get_readable_file_size(int(file.get('size', 0)))})</code><br>"
                    if not config_dict['DISABLE_DRIVE_LINK']:
                        furl = short_url(
                            f"https://drive.google.com/uc?id={file.get('id')}&export=download")
                        msg += f"<b><a href={furl}>Drive Link</a></b>"
                    if index_url:
                        if isRecur:
                            url_path = "/".join(rquote(n, safe='')
                                                for n in self.__get_recursive_list(file, dir_id))
                        else:
                            url_path = rquote(f'{file.get("name")}')
                        url = short_url(f'{index_url}/{url_path}')
                        msg += f' <b>| 🚀 <a href={url}>Index Link</a></b>'
                        if config_dict['VIEW_LINK']:
                            urlv = f'{index_url}/{url_path}?a=view'
                            urlv = short_url(urlv)
                            msg += f' <b>| 💻 <a href={urlv}>View Link</a></b>'
                msg += '<br><br>'
                contents_count += 1
                if len(msg.encode('utf-8')) > 39000:
                    telegraph_content.append(msg)
                    msg = ""
            if noMulti:
                break

        if msg != '':
            telegraph_content.append(msg)

        if not telegraph_content:
            return "", None

        path = [async_to_sync(telegraph.create_page, title='Jmdkh-mltb Drive Search',
                content=content)["path"] for content in telegraph_content]
        if len(path) > 1:
            async_to_sync(telegraph.edit_telegraph, path, telegraph_content)

        msg = f"<b>Found {contents_count} result for <i>{fileName}</i></b>"
        buttons = ButtonMaker()
        buttons.ubutton("🔎 VIEW", f"https://telegra.ph/{path[0]}", 'header')
        buttons = extra_btns(buttons)
        return msg, buttons.build_menu(2)

    def count(self, link):
        try:
            file_id = self.getIdFromUrl(link)
        except (KeyError, IndexError):
            return "Google Drive ID could not be found in the provided link"
        msg = ""
        LOGGER.info(f"File ID: {file_id}")
        try:
            meta = self.__getFileMetadata(file_id)
            name = meta['name']
            LOGGER.info(f"Counting: {name}")
            mime_type = meta.get('mimeType')
            if mime_type == self.__G_DRIVE_DIR_MIME_TYPE:
                self.__gDrive_directory(meta)
                msg += f'<b>Name</b>: <code>{name}</code>'
                msg += f'\n\n<b>Size</b>: {get_readable_file_size(self.__total_bytes)}'
                msg += '\n\n<b>Type</b>: Folder'
                msg += f' |<b>SubFolders</b>: {self.__total_folders}'
            else:
                msg += f'<b>Name</b>: <code>{name}</code>'
                if mime_type is None:
                    mime_type = 'File'
                self.__total_files += 1
                self.__gDrive_file(meta)
                msg += f'\n<b>Size</b>: {get_readable_file_size(self.__total_bytes)}'
                msg += f'\n\n<b>Type</b>: {mime_type}'
            msg += f' |<b>Files</b>: {self.__total_files}'
        except Exception as err:
            if isinstance(err, RetryError):
                LOGGER.info(
                    f"Total Attempts: {err.last_attempt.attempt_number}")
                err = err.last_attempt.exception()
            err = str(err).replace('>', '').replace('<', '')
            if "File not found" in err:
                if token_service := self.__alt_authorize():
                    self.__service = token_service
                    return self.count(link)
                msg = "File not found."
            else:
                msg = f"Error.\n{err}"
        return msg

    def __gDrive_file(self, filee):
        size = int(filee.get('size', 0))
        self.__total_bytes += size

    def __gDrive_directory(self, drive_folder):
        files = self.__getFilesByFolderId(drive_folder['id'])
        if len(files) == 0:
            return
        for filee in files:
            if shortcut_details := filee.get('shortcutDetails'):
                mime_type = shortcut_details['targetMimeType']
                file_id = shortcut_details['targetId']
                filee = self.__getFileMetadata(file_id)
            else:
                mime_type = filee.get('mimeType')
            if mime_type == self.__G_DRIVE_DIR_MIME_TYPE:
                self.__total_folders += 1
                self.__gDrive_directory(filee)
            else:
                self.__total_files += 1
                self.__gDrive_file(filee)

    def helper(self, link):
        try:
            file_id = self.getIdFromUrl(link)
        except (KeyError, IndexError):
            msg = "Google Drive ID could not be found in the provided link"
            return msg, "", "", ""
        LOGGER.info(f"File ID: {file_id}")
        try:
            meta = self.__getFileMetadata(file_id)
            name = meta['name']
            LOGGER.info(f"Checking size, this might take a minute: {name}")
            if meta.get('mimeType') == self.__G_DRIVE_DIR_MIME_TYPE:
                self.__gDrive_directory(meta)
            else:
                self.__total_files += 1
                self.__gDrive_file(meta)
            size = self.__total_bytes
            files = self.__total_files
        except Exception as err:
            if isinstance(err, RetryError):
                LOGGER.info(
                    f"Total Attempts: {err.last_attempt.attempt_number}")
                err = err.last_attempt.exception()
            err = str(err).replace('>', '').replace('<', '')
            if "File not found" in err:
                token_service = self.__alt_authorize()
                if token_service is not None:
                    self.__service = token_service
                    return self.helper(link)
                msg = "File not found."
            else:
                msg = f"Error.\n{err}"
            return msg, "", "", ""
        return "", size, name, files

    def download(self, link):
        self.__is_downloading = True
        file_id = self.getIdFromUrl(link)
        self.__updater = setInterval(self.__update_interval, self.__progress)
        try:
            meta = self.__getFileMetadata(file_id)
            if meta.get("mimeType") == self.__G_DRIVE_DIR_MIME_TYPE:
                self.__download_folder(file_id, self.__path, self.name)
            else:
                makedirs(self.__path, exist_ok=True)
                self.__download_file(file_id, self.__path,
                                     self.name, meta.get('mimeType'))
        except Exception as err:
            if isinstance(err, RetryError):
                LOGGER.info(
                    f"Total Attempts: {err.last_attempt.attempt_number}")
                err = err.last_attempt.exception()
            err = str(err).replace('>', '').replace('<', '')
            if "downloadQuotaExceeded" in err:
                err = "Download Quota Exceeded."
            elif "File not found" in err:
                if token_service := self.__alt_authorize():
                    self.__service = token_service
                    self.__updater.cancel()
                    return self.download(link)
            async_to_sync(self.__listener.onDownloadError, err)
            self.__is_cancelled = True
        finally:
            self.__updater.cancel()
            if self.__is_cancelled:
                return
        async_to_sync(self.__listener.onDownloadComplete)

    def __download_folder(self, folder_id, path, folder_name):
        folder_name = folder_name.replace('/', '')
        if not ospath.exists(f"{path}/{folder_name}"):
            makedirs(f"{path}/{folder_name}")
        path += f"/{folder_name}"
        result = self.__getFilesByFolderId(folder_id)
        if len(result) == 0:
            return
        result = sorted(result, key=lambda k: k['name'])
        for item in result:
            file_id = item['id']
            filename = item['name']
            if shortcut_details := item.get('shortcutDetails'):
                file_id = shortcut_details['targetId']
                mime_type = shortcut_details['targetMimeType']
            else:
                mime_type = item.get('mimeType')
            if mime_type == self.__G_DRIVE_DIR_MIME_TYPE:
                self.__download_folder(file_id, path, filename)
            elif not ospath.isfile(f"{path}{filename}") and not filename.lower().endswith(tuple(GLOBAL_EXTENSION_FILTER)):
                self.__download_file(file_id, path, filename, mime_type)
            if self.__is_cancelled:
                break

    @retry(wait=wait_exponential(multiplier=2, min=3, max=6), stop=stop_after_attempt(3),
           retry=(retry_if_exception_type(Exception)))
    def __download_file(self, file_id, path, filename, mime_type):
        request = self.__service.files().get_media(
            fileId=file_id, supportsAllDrives=True)
        filename = filename.replace('/', '')
        if len(filename.encode()) > 255:
            ext = ospath.splitext(filename)[1]
            filename = f"{filename[:245]}{ext}"
            if self.name.endswith(ext):
                self.name = filename
        if self.__is_cancelled:
            return
        fh = FileIO(f"{path}/{filename}", 'wb')
        downloader = MediaIoBaseDownload(
            fh, request, chunksize=100 * 1024 * 1024)
        done = False
        retries = 0
        while not done:
            if self.__is_cancelled:
                fh.close()
                break
            try:
                self.__status, done = downloader.next_chunk()
            except HttpError as err:
                if err.resp.status in [500, 502, 503, 504] and retries < 10:
                    retries += 1
                    continue
                if err.resp.get('content-type', '').startswith('application/json'):
                    reason = eval(err.content).get(
                        'error').get('errors')[0].get('reason')
                    if reason not in [
                        'downloadQuotaExceeded',
                        'dailyLimitExceeded',
                    ]:
                        raise err
                    if config_dict['USE_SERVICE_ACCOUNTS']:
                        if self.__sa_count >= self.__sa_number:
                            LOGGER.info(
                                f"Reached maximum number of service accounts switching, which is {self.__sa_count}")
                            raise err
                        else:
                            if self.__is_cancelled:
                                return
                            self.__switchServiceAccount()
                            LOGGER.info(f"Got: {reason}, Trying Again...")
                            return self.__download_file(file_id, path, filename, mime_type)
                    else:
                        LOGGER.error(f"Got: {reason}")
                        raise err
        self._file_processed_bytes = 0

    async def cancel_download(self):
        self.__is_cancelled = True
        if self.__is_downloading:
            LOGGER.info(f"Cancelling Download: {self.name}")
            await self.__listener.onDownloadError('Download stopped by user!')
        elif self.__is_cloning:
            LOGGER.info(f"Cancelling Clone: {self.name}")
        elif self.__is_uploading:
            LOGGER.info(f"Cancelling Upload: {self.name}")
            await self.__listener.onUploadError('your upload has been stopped and uploaded data has been deleted!')
