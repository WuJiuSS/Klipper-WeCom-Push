# -*- encoding:utf-8 -*-
from flask import abort, request, render_template, jsonify, Response, Flask, redirect
from xml.dom.minidom import parseString
import time
import os
import sys
import requests
import random
import hashlib
import configparser
from Klipper_server import (
    getAccessToken,
    get_wechat_jsapi_ticket,
    generate_jsapi_config,
    controlLight,
    getPrintStatus,
    getSystemStatus,
    sendWxMSg,
    get_current_print_image,
    getPrintJobList
)
from multiprocessing import Process
import string
sys.path.append("weworkapi_python/callback_python3")
from WXBizMsgCrypt import WXBizMsgCrypt

# 加载配置文件
config = configparser.ConfigParser()
config.read('config.conf', encoding='utf-8')

app = Flask(__name__)

# 初始化企业微信API
qy_api = [
    WXBizMsgCrypt(
        config.get('wechat', 'token'),
        config.get('wechat', 'encoding_aes_key'),
        config.get('wechat', 'corp_id')
    ),
]

@app.route('/hook_path', methods=['GET', 'POST'])
def douban():
    if request.method == 'GET':
        echo_str = signature(request, 0)
        return echo_str
    elif request.method == 'POST':
        echo_str = signature2(request, 0)
        return echo_str

@app.route('/camera', methods=['GET'])
def camera():
    return render_template("webcam.html")

@app.route("/getSnapshot", methods=['GET', 'POST'])
def getSnapshot():
    try:
        cache_bust = int(time.time() * 1000)
        snapshot_url = f"{config.get('server', 'webcam_snapshot_url')}?action=snapshot&cacheBust={cache_bust}"
        response = requests.get(snapshot_url, stream=True)
        return Response(
            response.content,
            content_type=response.headers["Content-Type"]
        )
    except Exception as e:
        return f"获取快照失败: {str(e)}", 500

def signature(request, i):
    msg_signature = request.args.get('msg_signature', '')
    timestamp = request.args.get('timestamp', '')
    nonce = request.args.get('nonce', '')
    echo_str = request.args.get('echostr', '')
    ret, sEchoStr = qy_api[i].VerifyURL(msg_signature, timestamp, nonce, echo_str)
    if ret != 0:
        print("ERR: VerifyURL ret: " + str(ret))
        return "failed"
    else:
        return sEchoStr

def signature2(request, i):
    msg_signature = request.args.get('msg_signature', '')
    timestamp = request.args.get('timestamp', '')
    nonce = request.args.get('nonce', '')
    data = request.data.decode('utf-8')
    ret, sMsg = qy_api[i].DecryptMsg(data, msg_signature, timestamp, nonce)
    if ret != 0:
        print("ERR: DecryptMsg ret: " + str(ret))
        return "failed"
    else:
        doc = parseString(sMsg)
        collection = doc.documentElement
        name_xml = collection.getElementsByTagName("FromUserName")
        msg_xml = collection.getElementsByTagName("Content")
        type_xml = collection.getElementsByTagName("MsgType")
        pic_xml = collection.getElementsByTagName("PicUrl")
        msg = ""
        name = ""
        msg_type = type_xml[0].childNodes[0].data
        if msg_type == "text":
            name = name_xml[0].childNodes[0].data
            msg = msg_xml[0].childNodes[0].data
            if msg == '系统状态':
                sendWxMSg(name, getSystemStatus())
            if msg == '打印状态' or msg == '打印进度':
                msg = getPrintStatus()
                sendWxMSg(name, getPrintStatus(), get_current_print_image())
            if msg == '打印任务统计':
                sendWxMSg(name, getPrintJobList())
            if msg == '拍照':
                sendWxMSg(name, '', get_current_print_image())
            if msg in ['开灯', '关灯']:
                action = 'on' if msg == '开灯' else 'off'
                result = controlLight(action)
                img = get_current_print_image() if any(x in result for x in ["成功", "开启", "关闭"]) else None
                sendWxMSg(name, result, img)
        elif msg_type == "image":
            name = name_xml[0].childNodes[0].data
            pic_url = pic_xml[0].childNodes[0].data
        return 'ok'

if __name__ == '__main__':
    app.run(
        host="0.0.0.0",
        port=config.getint('server', 'flask_port')
    )