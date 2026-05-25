from flask import Flask, render_template, request, Response, jsonify
import threading
import time
import json
import random
import hashlib
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import requests
import urllib3
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import unpad

urllib3.disable_warnings()
requests.packages.urllib3.disable_warnings()

# ==================== 核心类和函数 ====================

REWARD_TIERS: dict[str, dict[str, Any]] = {
    "1":  {"count": 1,   "reward": "15 金币"},
    "2":  {"count": 2,   "reward": "3 天VIP"},
    "3":  {"count": 5,   "reward": "8 天VIP"},
    "4":  {"count": 8,   "reward": "2 次AI脱衣"},
    "5":  {"count": 10,  "reward": "2 次AI图片换脸"},
    "6":  {"count": 15,  "reward": "45 金币"},
    "7":  {"count": 20,  "reward": "45 天VIP"},
    "8":  {"count": 50,  "reward": "80 天VIP"},
    "9":  {"count": 100, "reward": "180 天VIP"},
    "10": {"count": 200, "reward": "1000 金币"},
}

PUBLIC_KEY_RAW = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCgsH82stbCUaE1fTsotU0E2HWU9uQz496NFKgjjHBn"
    "Bzqk9YtYcowNFxaOz6G5Q3bw5j/+0+iAD58/n99ENjFkipiulu30eRiUpHUVFyc+EJ14FLKIXNksQWTu"
    "AivCkIYcDNP42in1nyjdXrpps7klCMm9MeAz8Mm+k9r1MGVJsQIDAQAB"
)

class AtomicCounter:
    def __init__(self) -> None:
        self._value = 0
        self._lock = threading.Lock()

    def inc(self) -> int:
        with self._lock:
            self._value += 1
            return self._value

@dataclass(slots=True)
class ApiConfig:
    base_url: str = "https://34.81.42.86:2242"
    macct: str = "sf42"
    ver: str = "1.0"
    os: str = "2"
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    )
    accept: str = "application/json,*/*"
    content_type: str = "application/json; charset=UTF-8"
    timeout: float = 10.0
    aes_key: str = "GcgzsKdDZTumABNz7uujrCfPIk9TQ355"

class ApiClient:
    def __init__(self, config: ApiConfig, public_key: str) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.verify = False
        self._aes_key = config.aes_key.encode("utf-8")
        self._public_key = RSA.import_key(self._load_public_key(public_key))
        self.session.headers.update({
            "user-agent": config.user_agent,
            "accept": config.accept,
            "content-type": config.content_type,
            "ver": config.ver,
            "os": config.os,
            "macct": config.macct,
        })

    def close(self) -> None:
        self.session.close()

    def set_token(self, token: str | None) -> None:
        if token is None:
            self.session.headers.pop("token", None)
        else:
            self.session.headers.update({"token": token})

    def post_plain(self, path: str, payload: dict[str, Any], params: dict[str, Any] | None = None):
        return self._post(path, payload, params=params)

    def post_rsa(self, path: str, payload: dict[str, Any]):
        return self._post(path, {"encrypt": self.rsa_encrypt_payload(payload)})

    def rsa_encrypt_payload(self, payload: dict[str, Any]) -> str:
        plain = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        cipher = PKCS1_v1_5.new(self._public_key)
        chunk_size = self._public_key.size_in_bytes() - 11
        encrypted = bytearray()
        for i in range(0, len(plain), chunk_size):
            encrypted.extend(cipher.encrypt(plain[i:i + chunk_size]))
        return base64.b64encode(bytes(encrypted)).decode("ascii")

    def decrypt_response_text(self, raw_text: str) -> dict[str, Any]:
        text = raw_text.strip()
        if text.startswith('"') and text.endswith('"'):
            text = json.loads(text)
        cipher = AES.new(self._aes_key, AES.MODE_ECB)
        plain = unpad(cipher.decrypt(base64.b64decode(text)), AES.block_size).decode("utf-8")
        return json.loads(plain)

    def _post(self, path: str, payload: dict[str, Any], params: dict[str, Any] | None = None):
        response = self.session.post(
            f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}",
            params=params,
            json=payload,
            timeout=self.config.timeout,
        )
        response.raise_for_status()
        result = self.decrypt_response_text(response.text)
        return ApiResult(code=result["code"], msg=result["msg"], data=result["data"])

    @staticmethod
    def _load_public_key(raw: str) -> str:
        if "BEGIN PUBLIC KEY" in raw or "BEGIN RSA PUBLIC KEY" in raw:
            return raw
        b64 = "".join(raw.split())
        lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
        return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(lines) + "\n-----END PUBLIC KEY-----\n"

class ApiResult:
    def __init__(self, code: int, msg: str, data: Any):
        self.code = code
        self.msg = msg
        self.data = data

class ApiService:
    LOGIN_PATH = "/front/cluser/c/user/mac/login"
    BIND_REFER_PATH = "/front/cluser/c/user/bind/refer"

    def __init__(self, client: ApiClient) -> None:
        self.client = client

    def login(self, mac: str):
        payload = {
            "mac": mac,
            "tips": hashlib.md5(f"{self.client.config.macct}{mac}1".encode("utf-8")).hexdigest(),
            "os": "1",
        }
        return self.client.post_rsa(self.LOGIN_PATH, payload)

    def bind_refer(self, code: str):
        return self.client.post_plain(self.BIND_REFER_PATH, {}, params={"code": code})

def make_uid() -> str:
    raw = f"{time.time()}{random.random()}{threading.get_ident()}"
    uid = hex(hash(raw))[2:]
    return uid if len(uid) == 16 else f"1{uid[:15]}"

def do_invite(refer_code: str, counter: AtomicCounter, total: int, start_time: float):
    client = None
    try:
        client = ApiClient(ApiConfig(), PUBLIC_KEY_RAW)
        api = ApiService(client)

        uid = make_uid()
        data = api.login(uid).data
        token = data["token"]
        client.set_token(token)

        result = api.bind_refer(refer_code)
        success = result.code == 0
        msg = result.msg
    except Exception as ex:
        success = False
        msg = str(ex)
    finally:
        if client is not None:
            client.close()

    n = counter.inc()
    elapsed = time.time() - start_time
    rate = n / elapsed if elapsed > 0 else 0
    status = "OK" if success else "FAIL"
    pct = n * 100 // total
    log_msg = f"[{n:>4}/{total}] {status:4s} | {rate:.1f}/s | {pct}% | {msg}"
    print(log_msg)
    return n, success, log_msg

# ==================== Flask 服务 ====================

app = Flask(__name__)
app.config['SECRET_KEY'] = 'invite_tool_secret_key_2026'

task_status = {
    "running": False,
    "success": 0,
    "total_target": 0,
    "logs": [],
    "round": 0,
    "max_rounds": 10,
    "refer_code": ""
}

lock = threading.Lock()

def add_system_log(msg: str, level="info"):
    with lock:
        prefix = {"success": "✅", "warning": "⚠️", "error": "❌"}.get(level, "ℹ️")
        task_status["logs"].append(f"{prefix} {msg}")

def sleep_random(min_sec=0.8, max_sec=2.0):
    time.sleep(random.uniform(min_sec, max_sec))

def run_invite_batch(refer_code: str, batch_size: int, workers: int):
    counter = AtomicCounter()
    start_time = time.time()
    success_in_batch = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(do_invite, refer_code, counter, batch_size, start_time) 
                  for _ in range(batch_size)]
        
        for future in as_completed(futures):
            n, success, log_msg = future.result()
            with lock:
                if success:
                    success_in_batch += 1
                    task_status["success"] += 1
                task_status["logs"].append(log_msg)
    return success_in_batch

def run_full_task(refer_code: str, target_count: int, workers: int):
    global task_status
    with lock:
        task_status["running"] = True
        task_status["success"] = 0
        task_status["total_target"] = target_count
        task_status["logs"] = []
        task_status["round"] = 0
        task_status["refer_code"] = refer_code

    current_success = 0
    round_num = 0

    while current_success < target_count and round_num < task_status["max_rounds"]:
        round_num += 1
        with lock:
            task_status["round"] = round_num

        remaining = target_count - current_success
        add_system_log(f"第 {round_num} 轮开始，剩余需要 {remaining} 个成功")

        success_this_round = run_invite_batch(refer_code, remaining, workers)
        current_success += success_this_round

        with lock:
            task_status["success"] = current_success

        if current_success >= target_count:
            add_system_log("🎉 已达成目标！", "success")
            break
        else:
            add_system_log(f"本轮成功 {success_this_round} 个，总成功 {current_success}/{target_count}，等待后继续...", "warning")
            sleep_random(1.2, 2.5)   # 防风控延时

    with lock:
        task_status["running"] = False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start', methods=['POST'])
def start():
    if task_status["running"]:
        return jsonify({"status": "error", "msg": "任务正在运行中"})

    data = request.get_json()
    refer_code = data.get('refer_code', 'NZR6STU0').strip()
    count = int(data.get('count', 20))
    workers = int(data.get('workers', 20))

    thread = threading.Thread(target=run_full_task, args=(refer_code, count, workers))
    thread.daemon = True
    thread.start()

    return jsonify({"status": "success", "msg": "任务已启动"})

@app.route('/status')
def status():
    def event_stream():
        while True:
            with lock:
                data = {
                    "running": task_status["running"],
                    "success": task_status["success"],
                    "total": task_status["total_target"],
                    "round": task_status["round"],
                    "logs": task_status["logs"][-200:]
                }
            yield f"data: {json.dumps(data)}\n\n"
            time.sleep(0.6)
    return Response(event_stream(), mimetype="text/event-stream")

if __name__ == '__main__':
    print("邀请刷量工具 Web 服务启动中...")
    print("访问地址: http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)