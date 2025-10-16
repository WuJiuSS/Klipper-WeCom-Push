import requests
import json
import time
import sqlite3
from sqlite3 import Error
import base64
from io import BytesIO
from PIL import Image
import os
from datetime import datetime, timedelta
import asyncio
import websockets
import random
import hashlib
import string
import configparser

# 加载配置文件
config = configparser.ConfigParser()
config.read('config.conf', encoding='utf-8')
corp_id = config.get("wechat", "corp_id")
agent_id = config.get("wechat", "agent_id")
DB_FILE = config.get('database', 'db_file')
check_interval = config.get('monitor', 'check_interval')

def get_device_ip():
    name = int(config.get("made", "name"))
    if name == 1:
        from made import qidi
        ip = qidi.get_device_url()
    else:
        ip = config.get("made", "ip")
    return ip



def create_connection():
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        return conn
    except Error as e:
        print(f"数据库连接错误: {e}")
    return conn


def init_db():
    """初始化数据库表"""
    conn = create_connection()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS token_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
        except Error as e:
            print(f"初始化数据库错误: {e}")
        finally:
            conn.close()


def get_cached_token():
    """从数据库获取缓存的token"""
    conn = create_connection()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT token, expires_at FROM token_cache 
                ORDER BY created_at DESC LIMIT 1
            ''')
            row = cursor.fetchone()
            if row:
                return {'token': row[0], 'expires_at': row[1]}
        except Error as e:
            print(f"查询缓存token错误: {e}")
        finally:
            conn.close()
    return None


def save_token_to_db(token, expires_in):
    """保存token到数据库"""
    conn = create_connection()
    if conn is not None:
        try:
            current_time = int(time.time())
            expires_at = current_time + expires_in - 200
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO token_cache (token, expires_at)
                VALUES (?, ?)
            ''', (token, expires_at))
            conn.commit()
        except Error as e:
            print(f"保存token到数据库错误: {e}")
        finally:
            conn.close()


def getAccessToken():
    """获取access_token，优先从缓存读取"""
    init_db()
    cached_token = get_cached_token()
    current_time = int(time.time())
    if cached_token and current_time < cached_token['expires_at']:
        return cached_token['token']

    url = f'https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={config.get("wechat", "corp_id")}&corpsecret={config.get("wechat", "corp_secret")}'
    print(url)
    response = requests.get(url)
    result = response.json()

    if result['errcode'] == 0:
        save_token_to_db(result['access_token'], result['expires_in'])
        return result['access_token']
    else:
        raise Exception(f"获取 access_token 失败: {result['errmsg']}")

def get_wechat_jsapi_ticket():
    """获取JS-SDK ticket"""
    access_token = getAccessToken()
    url = f'https://qyapi.weixin.qq.com/cgi-bin/get_jsapi_ticket?access_token={access_token}'
    response = requests.get(url)
    return response.json().get('ticket', '')


def generate_jsapi_config(url):
    """生成JS-SDK配置"""
    ticket = get_wechat_jsapi_ticket()
    noncestr = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    timestamp = str(int(time.time()))

    # 生成签名
    sign_str = f'jsapi_ticket={ticket}&noncestr={noncestr}&timestamp={timestamp}&url={url}'
    signature = hashlib.sha1(sign_str.encode()).hexdigest()

    return {
        'corpId': corp_id,
        'agentId': agent_id,
        'timestamp': timestamp,
        'nonceStr': noncestr,
        'signature': signature,
        'url': url
    }


def get_current_print_image():
    """获取当前打印的图片"""
    try:
        WEBCAM_SNAPSHOT_URL = f'http://{get_device_ip()}/webcam/snapshot'
        response = requests.get(WEBCAM_SNAPSHOT_URL, timeout=10)
        if response.status_code == 200:
            img_base64 = base64.b64encode(response.content).decode('utf-8')
            return img_base64
        else:
            return None
    except Exception as e:
        print(f"获取打印图片失败: {e}")
        return None


async def getPrintStatusWs(max_messages=10):
    url = f'http://{get_device_ip()}/access/oneshot_token'
    res = requests.get(url).json()
    token = res['result']
    ws_url = f'ws://{get_device_ip()}/websocket?token={token}'
    try:
        async with websockets.connect(ws_url) as websocket:
            subscribe_msg = {
                "jsonrpc": "2.0",
                "method": "printer.objects.subscribe",
                "params": {
                    "objects": {
                        "print_stats": None,
                        "virtual_sdcard": None,
                        "toolhead": None,
                        "extruder": None,
                        "heater_bed": None,
                        "motion_report": None,
                        "display_status": None,
                        "heater_generic chamber": None
                    }
                },
                "id": 1
            }
            await websocket.send(json.dumps(subscribe_msg))
            for _ in range(max_messages):
                response = await asyncio.wait_for(websocket.recv(), timeout=60)

                data = json.loads(response)
                if data.get('method') == "notify_status_update":
                    return data
            print(f"已接收{max_messages}条消息，但未收到状态更新")
            return None
    except asyncio.TimeoutError:
        print("等待响应超时")
        return "❌ 等待响应超时"
    except Exception as e:
        print(f"发生异常: {e}")
        return f"❌ WS 获取打印机状态失败: {str(e)}"


def calculatePrintTime(print_duration,display_progress):
    progress = display_progress
    if progress > 0:
        total_time = print_duration / progress
    else:
        total_time = print_duration
    total_time = total_time - print_duration
    h = int(total_time // 3600)
    m = int((total_time % 3600) // 60)
    s = int(total_time % 60)
    return f"{h}h {m}m {s}s"


def calculatePrintTime2(filename,print_duration):
    url = f'http://{get_device_ip()}/server/files/metadata?filename={filename}'
    estimated_time = requests.get(url).json()['result']['estimated_time']
    total_time = estimated_time - print_duration
    h = int(total_time // 3600)
    m = int((total_time % 3600) // 60)
    s = int(total_time % 60)
    return f"{h}h {m}m {s}s"

def getPrintStatus():
    response = requests.get(
        f"http://{get_device_ip()}/printer/objects/query?print_stats&virtual_sdcard&toolhead&extruder&heater_bed&gcode_move&display_status"
    )
    printer_data = response.json()
    print(printer_data)
    state_map = {
        'printing': '打印中',
        'paused': '已暂停',
        'complete': '已完成',
        'cancelled': '已取消',
        'error': '错误',
        'ready': '待机',
        'standby': '待机',
        'unknown': '未知状态'
    }

    state = printer_data['result']['status']['print_stats']['state']
    status_msg = f"------🖨️ 打印状态------\n"
    status_msg += f"打印机状态: {state_map.get(state, state)}\n"
    if state == 'printing':
        # a = asyncio.run(getPrintStatusWs())
        # print(a)
        status_msg = f"文件名: {printer_data['result']['status']['print_stats']['filename']}\n"

        # 已用时间计算
        print_duration = printer_data['result']['status']['print_stats']['print_duration']
        h, remainder = divmod(print_duration, 3600)
        m, s = divmod(remainder, 60)
        status_msg += f"已用时间: {int(h)}h {int(m)}m {int(s)}s\n"

        # 进度信息
        progress = printer_data['result']['status']['virtual_sdcard']['progress']
        status_msg += f"打印进度【切片】: {progress * 100:.1f}%\n"
        status_msg += f"剩余时间【切片】: {calculatePrintTime2(printer_data['result']['status']['print_stats']['filename'],printer_data['result']['status']['print_stats']['print_duration'])}%\n"


        progress = printer_data['result']['status']['display_status']['progress']
        status_msg += f"打印进度【实际】: {progress * 100:.1f}%\n"
        status_msg += f"剩余时间【实际】: {calculatePrintTime(printer_data['result']['status']['print_stats']['print_duration'],printer_data['result']['status']['display_status']['progress'])}\n"

        # 层数信息
        current_layer = printer_data['result']['status']['print_stats']['info']['current_layer']
        total_layer = printer_data['result']['status']['print_stats']['info']['total_layer']
        layer_progress = current_layer / total_layer
        status_msg += f"层进度: {current_layer}/{total_layer}\n"


        # 耗材使用
        filament_used = printer_data['result']['status']['print_stats']['filament_used'] / 1000
        status_msg += f"已用耗材: {filament_used:.2f} m\n"

    return status_msg


def getPrintJobList():
    try:
        response = requests.get(f"http://{get_device_ip()}/server/history/totals")
        data = response.json()

        if 'result' not in data or 'job_totals' not in data['result']:
            return "❌ 无法获取打印任务统计"

        totals = data['result']['job_totals']
        msg = f"------🖨️ 打印任务统计------\n"
        msg += f"总任务次数: {int(totals['total_jobs'])}\n"
        msg += format_time(totals['total_time'], "总时间")
        msg += "\n" + format_time(totals['total_print_time'], "总打印时间") + "\n"
        msg += f"总消耗耗材: {totals['total_filament_used'] / 1000:.2f} 米\n"
        msg += format_time(totals['longest_job'], "最长任务") + "\n"
        msg += format_time(totals['longest_print'], "最长打印") + "\n"

        return msg

    except Exception as e:
        return f"❌ 获取统计失败: {str(e)}"




def getSystemStatus():
    """获取系统利用率"""

    try:
        # 获取系统信息
        res = requests.get(f"http://{get_device_ip()}/machine/proc_stats")
        proc_stats = res.json()

        res = requests.get(f"http://{get_device_ip()}/machine/system_info")
        sys_info = res.json()

        # CPU使用率信息
        cpu_usage = proc_stats['result']['system_cpu_usage']
        msg =  f"------🖥️ 系统状态------\n"
        msg += f"CPU使用率: {cpu_usage['cpu']:.1f}%\n"

        core_usage = []
        i = 0
        while f'cpu{i}' in cpu_usage:
            core_usage.append(f"{cpu_usage[f'cpu{i}']:.1f}%")
            i += 1

        if core_usage:
            msg += f"核心({len(core_usage)}): " + " | ".join(core_usage) + "\n"
        else:
            msg += "核心使用率: 无数据\n"

        # 内存信息
        memory_used = proc_stats['result']['system_memory']['used']
        memory_total = proc_stats['result']['system_memory']['total']
        memory_percent = (memory_used / memory_total) * 100
        msg += f"内存使用: {memory_used / 1024:.1f}MB/{memory_total / 1024:.1f}MB ({memory_percent:.1f}%)\n"

        # CPU温度
        if 'cpu_temp' in proc_stats['result']:
            msg += f"CPU温度: {proc_stats['result']['cpu_temp']:.1f}°C\n"
        if 'network' in sys_info['result']['system_info']:
            network = sys_info['result']['system_info']['network']
            for interface, info in network.items():
                if interface.startswith('wlan') or interface.startswith('eth'):
                    msg += f"\n网络接口 {interface}:\n"
                    msg += f"MAC地址: {info['mac_address']}\n"
                    for ip in info['ip_addresses']:
                        if ip['family'] == 'ipv4' and not ip['is_link_local']:
                            msg += f"IPv4地址: {ip['address']}\n"
                        elif ip['family'] == 'ipv6' and not ip['is_link_local']:
                            msg += f"IPv6地址: {ip['address']}\n"
        # 添加系统时间
        msg += f"\n状态更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        return msg
    except Exception as e:
        return f"❌ 获取系统状态失败: {str(e)}"


def controlLight(action="on"):
    try:
        action = action.lower()
        if action not in ['on', 'off', 'toggle', 'status']:
            return "❌ 无效操作，请使用 on/off/toggle/status"
        gcode_command = f"SET_PIN PIN=caselight VALUE={1 if action == 'on' else 0}"
        requests.post( f"http://{get_device_ip()}/printer/gcode/script",json={"script": gcode_command}, )
        return f"✅ 补光灯已{'开启' if action == 'on' else '关闭'}"

    except requests.exceptions.Timeout:
        return "❌ 请求超时，请检查Moonraker连接"
    except Exception as e:
        return f"❌ 控制异常: {str(e)}"



def sendWxMSg(user_id, text_content, image_base64=None):
    """推送到企业微信"""
    try:
        access_token = getAccessToken()

        if image_base64:
            upload_url = f"https://qyapi.weixin.qq.com/cgi-bin/media/upload?access_token={access_token}&type=image"
            image_data = base64.b64decode(image_base64)
            files = {'media': ('print_snapshot.jpg', image_data, 'image/jpeg')}

            upload_response = requests.post(upload_url, files=files)
            upload_result = upload_response.json()

            if upload_result.get('errcode') == 0:
                media_id = upload_result.get('media_id')
                data = {
                    "touser": user_id,
                    "msgtype": "image",
                    "agentid": agent_id,
                    "image": {
                        "media_id": media_id
                    }
                }
                send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"
                response = requests.post(send_url, json=data)
                text_data = {
                    "touser": user_id,
                    "msgtype": "text",
                    "agentid": agent_id,
                    "text": {
                        "content": text_content
                    }
                }
                requests.post(send_url, json=text_data)

            else:
                data = {
                    "touser": user_id,
                    "msgtype": "text",
                    "agentid": agent_id,
                    "text": {
                        "content": text_content + "\n\n[图片上传失败]"
                    }
                }
                send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"
                response = requests.post(send_url, json=data)

        else:
            data = {
                "touser": user_id,
                "msgtype": "text",
                "agentid": agent_id,
                "text": {
                    "content": text_content
                }
            }
            send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"
            response = requests.post(send_url, json=data)
        result = response.json()
        if result['errcode'] != 0:
            print(f"发送消息失败: {result}")
            return False
        else:
            return  True

    except Exception as e:
        print(f"发送消息异常: {str(e)}")






def format_time(seconds, prefix):
    """格式化时间显示"""
    if seconds <= 0:
        return f"{prefix}: 0秒"

    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)

    if h > 0:
        return f"{prefix}: {int(h)}h {int(m)}m {int(s)}s"
    else:
        return f"{prefix}: {int(m)}m {int(s)}s"





class PrinterMonitor:
    def __init__(self):
        self.last_state = None
        self.current_print_info = None
        self.check_interval = int(check_interval)

    def get_printer_status(self):
        """获取打印机状态"""
        try:
            response = requests.get(
                f"http://{get_device_ip()}/printer/objects/query?"
                f"print_stats&virtual_sdcard"
            )
            printer_data = response.json()
            return printer_data['result']['status']
        except Exception as e:
            print(f"获取打印机状态失败: {e}")
            return None

    def check_state_change(self, current_status):
        """检查状态变化"""
        current_state = current_status['print_stats']['state']

        # 状态变化检测
        if self.last_state != current_state:
            old_state = self.last_state
            self.last_state = current_state

            if old_state is not None:  # 忽略第一次启动
                return True, old_state, current_state

        return False, None, None

    def handle_print_start(self, status):
        # print(status)
        # a = asyncio.run(getPrintStatusWs())
        # print(a)
        """处理打印开始事件"""
        print_stats = status['print_stats']
        filename = print_stats.get('filename', '未知文件')

        message = "🟢 打印任务开始\n\n"
        message += f"文件名: {filename}\n"
        message += f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"

        # 获取图片并发送
        # image_base64 = get_current_print_image()
        sendWxMSg("@all", message)

        # 保存当前打印信息
        self.current_print_info = {
            'filename': filename,
            'start_time': datetime.now(),
            'start_filament': print_stats.get('filament_used', 0)
        }

    def handle_print_complete(self, status):
        """处理打印完成事件"""
        print_stats = status['print_stats']
        filename = print_stats.get('filename', '未知文件')
        print_duration = print_stats.get('print_duration', 0)
        filament_used = print_stats.get('filament_used', 0)

        # 计算打印耗时
        hours, remainder = divmod(print_duration, 3600)
        minutes, seconds = divmod(remainder, 60)

        message = "✅ 打印任务完成\n\n"
        message += f"文件名: {filename}\n"
        message += f"打印耗时: {int(hours)}h {int(minutes)}m {int(seconds)}s\n"
        message += f"耗材使用量: {filament_used / 1000:.2f}米\n"
        message += f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"

        # 获取完成时的图片
        sendWxMSg("@all", message, get_current_print_image())
        # 清空当前打印信息
        self.current_print_info = None

    def handle_print_cancelled(self, status):
        """处理打印取消事件"""
        print_stats = status['print_stats']
        filename = print_stats.get('filename', '未知文件')
        print_duration = print_stats.get('print_duration', 0)
        filament_used = print_stats.get('filament_used', 0)

        hours, remainder = divmod(print_duration, 3600)
        minutes, seconds = divmod(remainder, 60)

        message = "⏹️ 打印任务取消\n\n"
        message += f"文件名: {filename}\n"
        message += f"已打印: {int(hours)}h {int(minutes)}m {int(seconds)}s\n"
        message += f"耗材使用量: {filament_used / 1000:.2f}米\n"
        message += f"取消时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        sendWxMSg("@all", message)
        self.current_print_info = None

    def handle_print_error(self, status):
        """处理打印错误事件"""
        print_stats = status['print_stats']
        filename = print_stats.get('filename', '未知文件')
        error_message = print_stats.get('message', '未知错误')

        message = "❌ 打印任务错误\n\n"
        message += f"文件名: {filename}\n"
        message += f"错误信息: {error_message}\n"
        message += f"错误时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        sendWxMSg("@all", message, get_current_print_image())
        self.current_print_info = None

    def monitor_loop(self):
        """监控循环"""
        print("🚀 打印机监控服务启动...")

        while True:
            try:
                # 获取当前状态
                current_status = self.get_printer_status()
                if not current_status:
                    time.sleep(self.check_interval)
                    continue

                # 检查状态变化
                state_changed, old_state, new_state = self.check_state_change(current_status)

                if state_changed:
                    print(f"状态变化: {old_state} -> {new_state}")

                    # 处理不同状态变化
                    if new_state == 'printing' and old_state != 'printing':
                        self.handle_print_start(current_status)

                    elif new_state == 'complete' and old_state == 'printing':
                        self.handle_print_complete(current_status)

                    elif new_state == 'cancelled' and old_state == 'printing':
                        self.handle_print_cancelled(current_status)

                    elif new_state == 'error' and old_state == 'printing':
                        self.handle_print_error(current_status)

                # 休眠一段时间
                time.sleep(self.check_interval)

            except Exception as e:
                print(f"监控循环错误: {e}")
                time.sleep(self.check_interval)