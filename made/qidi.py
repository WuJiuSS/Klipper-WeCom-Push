import requests
import sqlite3
import configparser
import time
import jwt
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
config_path = os.path.join(root_dir, 'config.conf')
config = configparser.ConfigParser()
config.read(config_path, encoding='utf-8')
DB_FILE = 'qidi_token.db'
username = config.get('made', 'username')
password = config.get('made', 'password')
ip = config.get('made', 'ip')


def create_connection():
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        return conn
    except Exception as e:
        print(f"数据库连接错误: {e}")
    return conn


def init_db():
    """初始化数据库表"""
    conn = create_connection()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute('''
                 CREATE TABLE IF NOT EXISTS qidi_token_cache (
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     token TEXT NOT NULL,
                     expires_at INTEGER NOT NULL,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                 )
             ''')
            conn.commit()
        except Exception as e:
            print(f"初始化数据库错误: {e}")
        finally:
            conn.close()


def save_token_to_db(token):
    conn = create_connection()
    if conn is not None:
        try:
            # 解析token获取过期时间
            decoded_token = jwt.decode(token, options={"verify_signature": False})
            expires_at = decoded_token.get('exp', 0)
            print(expires_at)

            current_time = int(time.time())
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO qidi_token_cache (token, expires_at)
                VALUES (?, ?)
            ''', (token, expires_at))
            conn.commit()
            print(f"Token已保存，过期时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expires_at))}")
        except Exception as e:
            print(f"保存token到数据库错误: {e}")
        finally:
            conn.close()


def get_cached_token():
    """从数据库获取缓存的token"""
    conn = create_connection()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT token, expires_at FROM qidi_token_cache 
                ORDER BY created_at DESC LIMIT 1
            ''')
            row = cursor.fetchone()
            if row:
                return {'token': row[0], 'expires_at': row[1]}
        except Exception as e:
            print(f"查询缓存token错误: {e}")
        finally:
            conn.close()
    return None


def is_token_valid(token_data):
    """检查token是否有效"""
    if not token_data:
        return False

    current_time = int(time.time())
    # 检查token是否过期（考虑缓冲时间）
    if current_time >= (token_data['expires_at'] - 300):
        print(f"Token已过期或即将过期，需要重新获取")
        return False

    # 可选：验证token格式
    try:
        jwt.decode(token_data['token'], options={"verify_signature": False})
        return True
    except Exception as e:
        print(f"Token格式无效: {e}")
        return False


def login():
    """登录获取token"""
    url = "https://api2.qidi3dprinter.com/qidi/common/emailLogin"
    headers = {
        "Authorization": "Bearer",
        "lang": "zh",
        "user-agent": "Mozilla/5.0 (Linux; Android 9; SHARK KTUS-H0 Build/PQ3B.190801.09281831; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/91.0.4472.114 Mobile Safari/537.36 uni-app Html5Plus/1.0 (Immersed/24.0)",
        "Content-Type": "application/json",
        "Host": "api2.qidi3dprinter.com",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Accept": "*/*"
    }
    json_data = {"email": username, "password": password}

    try:
        response = requests.post(url, headers=headers, json=json_data)
        response.raise_for_status()
        res = response.json()

        if res.get("status") == 0:
            qidi_token = res["data"]["token"]
            print("登录成功，获取到新token")
            return qidi_token
        else:
            print(f"登录失败: {res.get('message', '未知错误')}")
    except requests.exceptions.RequestException as e:
        print(f"网络请求错误: {e}")
    except Exception as e:
        print(f"登录过程错误: {e}")

    return None


def get_token():
    init_db()
    cached_token = get_cached_token()
    if is_token_valid(cached_token):
        return cached_token['token']
    new_token = login()
    if new_token:
        save_token_to_db(new_token)
        return new_token
    else:
        return None


def get_device_url():
    token = get_token()
    if not token:
        return None
    url = "https://api2.qidi3dprinter.com/qidi/user/deviceList?page=1&limit=99"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    response = requests.get(url, headers=headers, timeout=10).json()
    if response['status'] == 0:
        for x in response['data']['list']:
            if x['local_ip'] == ip:
                device_url = x['url']
                return device_url
    return None

