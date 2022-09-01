from logging import getLogger, FileHandler, StreamHandler, INFO, basicConfig
from time import sleep, time
from psutil import boot_time, disk_usage, net_io_counters
from subprocess import check_output
from os import path as ospath
from qbittorrentapi import NotFound404Error, Client as qbClient
from aria2p import API as ariaAPI, Client as ariaClient
from flask import Flask, request
from requests import get as rget
from web.nodes import make_tree
app = Flask(__name__)

basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[FileHandler('log.txt'), StreamHandler()],
                    level=INFO)

aria2 = ariaAPI(ariaClient(host="http://localhost", port=6800, secret=""))

LOGGER = getLogger(__name__)

rawowners = "<h1 style='text-align: center'>See my Channel <a href='https://t.me/JMDKH_Team'>@Telegram</a><br><br>By<br><br><a href='https://github.com/junedkh'>Juned KH</a></h1>"

pin_entry = '''
    <section>
      <form action="{form_url}">
        <div>
          <label for="pin_code">Pin Code :</label>
          <input
            type="text"
            name="pin_code"
            placeholder="Enter the code that you have got from Telegram to access the Torrent"
          />
        </div>
        <button type="submit" class="btn btn-primary">Submit</button>
      </form>
          <span
            >* Dont mess around. Your download will get messed up.</
          >
    </section>
'''
files_list = '''
    <div id="sticks">
        <h4>Selected files: <b id="checked_files">0</b> of <b id="total_files">0</b></h4>
        <h4>Selected files size: <b id="checked_size">0</b> of <b id="total_size">0</b></h4>
    </div>
    <section>
        <input type="hidden" name="URL" id="URL" value="{form_url}" />
        <form id="SelectedFilesForm" name="SelectedFilesForm">
            <!-- {My_content} -->
            <input type="submit" name="Submit" />
        </form>
    </section>
'''
rawindexpage = rget('https://cdn.jsdelivr.net/gh/junedkh/somesrcs/wserver/index.html').text
stlye1 = rget('https://cdn.jsdelivr.net/gh/junedkh/somesrcs/wserver/style1.css').text
stlye2 = rget('https://cdn.jsdelivr.net/gh/junedkh/somesrcs/wserver/style2.css').text

def re_verfiy(paused, resumed, client, hash_id):

    paused = paused.strip()
    resumed = resumed.strip()
    if paused:
        paused = paused.split("|")
    if resumed:
        resumed = resumed.split("|")

    k = 0
    while True:
        res = client.torrents_files(torrent_hash=hash_id)
        verify = True
        for i in res:
            if str(i.id) in paused and i.priority != 0:
                verify = False
                break
            if str(i.id) in resumed and i.priority == 0:
                verify = False
                break
        if verify:
            break
        LOGGER.info("Reverification Failed! Correcting stuff...")
        client.auth_log_out()
        sleep(1)
        client = qbClient(host="localhost", port="8090")
        try:
            client.torrents_file_priority(torrent_hash=hash_id, file_ids=paused, priority=0)
        except NotFound404Error:
            raise NotFound404Error
        except Exception as e:
            LOGGER.error(f"{e} Errored in reverification paused!")
        try:
            client.torrents_file_priority(torrent_hash=hash_id, file_ids=resumed, priority=1)
        except NotFound404Error:
            raise NotFound404Error
        except Exception as e:
            LOGGER.error(f"{e} Errored in reverification resumed!")
        k += 1
        if k > 5:
            return False
    LOGGER.info(f"Verified! Hash: {hash_id}")
    return True

@app.route('/app/files/<string:id_>', methods=['GET'])
def list_torrent_contents(id_):

    if "pin_code" not in request.args.keys():
        return rawindexpage.replace("/* style1 */", stlye1).replace("<!-- pin_entry -->", pin_entry) \
            .replace("{form_url}", f"/app/files/{id_}")

    pincode = ""
    for nbr in id_:
        if nbr.isdigit():
            pincode += str(nbr)
        if len(pincode) == 4:
            break
    if request.args["pin_code"] != pincode:
        return rawindexpage.replace("/* style1 */", stlye1).replace(
            "<!-- Print -->", "<h1 style='text-align: center;color: red;'>Incorrect pin code</h1>")

    if len(id_) > 20:
        client = qbClient(host="localhost", port="8090")
        res = client.torrents_files(torrent_hash=id_)
        cont = make_tree(res)
        client.auth_log_out()
    else:
        res = aria2.client.get_files(id_)
        cont = make_tree(res, True)
    return rawindexpage.replace("/* style2 */", stlye2).replace("<!-- files_list -->", files_list) \
        .replace("{form_url}", f"/app/files/{id_}?pin_code={pincode}") \
        .replace("<!-- {My_content} -->", cont[0])

@app.route('/app/files/<string:id_>', methods=['POST'])
def set_priority(id_):
    data = dict(request.form)
    resume = ""
    if len(id_) > 20:
        pause = ""

        for i, value in data.items():
            if "filenode" in i:
                node_no = i.split("_")[-1]

                if value == "on":
                    resume += f"{node_no}|"
                else:
                    pause += f"{node_no}|"

        pause = pause.strip("|")
        resume = resume.strip("|")

        client = qbClient(host="localhost", port="8090")

        try:
            client.torrents_file_priority(torrent_hash=id_, file_ids=pause, priority=0)
        except NotFound404Error:
            raise NotFound404Error
        except Exception as e:
            LOGGER.error(f"{e} Errored in paused")
        try:
            client.torrents_file_priority(torrent_hash=id_, file_ids=resume, priority=1)
        except NotFound404Error:
            raise NotFound404Error
        except Exception as e:
            LOGGER.error(f"{e} Errored in resumed")
        sleep(1)
        if not re_verfiy(pause, resume, client, id_):
            LOGGER.error(f"Verification Failed! Hash: {id_}")
        client.auth_log_out()
    else:
        for i, value in data.items():
            if "filenode" in i and value == "on":
                node_no = i.split("_")[-1]
                resume += f'{node_no},'

        resume = resume.strip(",")

        res = aria2.client.change_option(id_, {'select-file': resume})
        if res == "OK":
            LOGGER.info(f"Verified! Gid: {id_}")
        else:
            LOGGER.info(f"Verification Failed! Report! Gid: {id_}")
    return list_torrent_contents(id_)

botStartTime = time()
if ospath.exists('.git'):
    commit_date = check_output(["git log -1 --date=format:'%y/%m/%d %H:%M' --pretty=format:'%cd'"], shell=True).decode()
else:
    commit_date = 'No UPSTREAM_REPO'

@app.route('/status', methods=['GET'])
def status():
    bot_uptime = time() - botStartTime
    uptime = time() - boot_time()
    sent = net_io_counters().bytes_sent
    recv = net_io_counters().bytes_recv
    return {
        'commit_date': commit_date,
        'uptime': uptime,
        'on_time': bot_uptime,
        'free_disk': disk_usage('.').free,
        'total_disk': disk_usage('.').total,
        'network': {
            'sent': sent,
            'recv': recv,
        },
    }
@app.route('/')
def homepage():
    return rawindexpage.replace("/* style1 */", stlye1).replace("<!-- Print -->", rawowners)

@app.errorhandler(Exception)
def page_not_found(e):
    return rawindexpage.replace("/* style1 */", stlye1) \
                    .replace("<!-- Print -->", f"<h1 style='text-align: center;color: red;'>404: Torrent not found! Mostly wrong input. <br><br>Error: {e}</h1>"), 404

if __name__ == "__main__":
    app.run()