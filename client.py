# -*- encoding: utf-8 -*-
# 外部变量/注释开始
# 外部变量/注释结束
"""
@File    :   client.py    
@Author  :   Guesser
@Modify Time      @Version    @Description
------------      --------    -----------
2025/10/25 0:09    1.0         去掉类型提示,兼容旧版本python,整合linux和Windows
"""


"""
最终版 client.py
整合：
  - Windows + Linux 全统一监控
  - Energy-saving mode（节能模式）
  - Windows 网速使用 psutil（性能稳定）
  - Linux 过滤虚拟挂载点（snap/dev/shm/run/... 等）
"""

import sys
import atexit
import logging
import os
import signal
import subprocess
import threading
from datetime import datetime, timedelta
import platform
import time
import json
import urllib.request
# import pytz
# tz = pytz.timezone("Asia/Shanghai")

SYSTEM = platform.system()

# Windows 需要 psutil
if SYSTEM == "Windows":
    import psutil
else:
    # Linux imports
    pass

logging.basicConfig(
    format='[%(asctime)s] %(levelname)s     %(message)s',
    level=logging.INFO
)

IS_EXITED = False


def real_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.realpath(sys.executable))
    return os.path.dirname(os.path.realpath(__file__))


def now_shanghai_str():
    # 用 UTC + 8 计算“上海时间”
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

# ============================
# HTTP POST (标准库实现)
# ============================
def http_post(url, data, timeout=10):
    try:
        req = urllib.request.Request(
            url=url,
            data=json.dumps(data).encode('utf-8'),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode()
    except Exception as e:
        return str(e)


# ============================
# 参数读取
# ============================
class ProcessParams:
    def __init__(self):
        self.secret_key = ''
        self.api_address = ''
        self.path = "config.txt"
        self.real_path = real_path()

    @staticmethod
    def open(path):
        with open(path, 'r', encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def write(path, content):
        with open(path, 'w', encoding="utf-8") as f:
            f.write(content)

    def ask_user_params(self):
        ask_list = ["api_address", "secret_key"]
        result = ""
        for item in ask_list:
            user_input = input("请输入{}\n".format(item))
            result += "{}={}\n".format(item, user_input)
        self.write(os.path.join(self.real_path,self.path), result)

    def check_params(self):
        if self.secret_key and self.api_address and self.api_address.startswith("http"):
            logging.info("参数检查通过")
            return True
        logging.error("密钥为空或 api 地址为空或 api 地址未以 http 开头")
        return False

    def read_params(self):
        if os.path.exists(os.path.join(self.real_path, self.path)):
            raw = self.open(os.path.join(self.real_path, self.path))
            for line in raw.splitlines():
                key, value = line.split("=")
                if key.strip() == "secret_key":
                    self.secret_key = value.strip()
                if key.strip() == "api_address":
                    self.api_address = value.strip()

        if self.check_params():
            return self.api_address, self.secret_key

        self.ask_user_params()
        return self.read_params()


# ============================
# 主监控类
# ============================
class SystemMonitor:
    def __init__(self, secret_key, api_address, energy_saving_mode=False):
        self.secret_key = secret_key
        self.energy_saving_mode = energy_saving_mode
        self.api_address = api_address
        self.system_info_dict = {
            "cpu_usage": None,
            "cpu_model": None,
            "cpu_count": None,
            "cpu_freq": None,
            "mem_total": None,
            "mem_used": None,
            "mem_percent": None,
            "swap_total": None,
            "swap_used": None,
            "swap_percent": None,
            "network_sent": None,
            "network_received": None,
            "network_pocket_sent": None,
            "process_count": None,
            "disks": [],
            "uptime": None,
            "sent_speed": None,
            "recv_speed": None,
            "os": self.get_os_pretty_name(),
            "secret_key": secret_key
        }

        # 静态参数缓存
        self.cached_static = {
            "cpu_model": None,
            "cpu_count": None,
            "cpu_freq": None,
            "disks": None,
            "last_disk_update": 0
        }

        if SYSTEM == "Linux":
            self.prev_net = self.read_net_dev()

        threading.Thread(target=self.update_worker, daemon=True).start()

    # ---------------------------------------
    # 通用格式化方法
    # ---------------------------------------
    @staticmethod
    def change_data_to_human_friendly(data):
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if data < 1024:
                return "{} {}".format(round(data,2), unit)
            data /= 1024
        return "{} TB".format(round(data,2))

    @staticmethod
    def change_time_to_human_friendly(seconds):
        units = [
            # ("years", 365*86400),
            # ("months", 30*86400),
            ("days", 86400),
            ("hours", 3600),
            ("minutes", 60),
            ("seconds", 1)
        ]
        result = []
        for name, sec in units:
            if seconds >= sec:
                val = int(seconds // sec)
                seconds %= sec
                result.append("{}{}".format(val,name))
        return " ".join(result) if result else "0s"

    @staticmethod
    def snake_to_small_camel(data):
        new = {}
        for k, v in data.items():
            if "_" not in k:
                new[k] = v
                continue
            parts = k.split("_")
            new[parts[0] + ''.join(p.capitalize() for p in parts[1:])] = v
        return new

    # ---------------------------------------
    # OS 名称
    # ---------------------------------------
    @staticmethod
    def get_os_pretty_name():
        if SYSTEM == "Windows":
            try:
                result = subprocess.check_output("wmic os get Caption", shell=True)
                lines = result.decode().strip().split("\n")
                if len(lines) > 1:
                    return lines[1].strip()
            except:
                pass
            return "Windows {}".format(platform.release())

        elif SYSTEM == "Linux":
            try:
                with open("/etc/os-release") as f:
                    info = {}
                    for line in f:
                        if "=" in line:
                            k, v = line.strip().split("=", 1)
                            info[k] = v.strip('"')
                return "{} {}".format(info.get('NAME','Linux'), info.get('VERSION',''))
            except:
                return "Linux {}".format(platform.release())

        return SYSTEM

    # ===========================================================
    # LINUX SECTION
    # ===========================================================
    def read_cpu_stat(self):
        with open("/proc/stat") as f:
            for line in f:
                if line.startswith("cpu "):
                    parts = line.split()
                    return list(map(int, parts[1:]))
        return [0]*10

    def get_linux_cpu_usage(self):
        s1 = self.read_cpu_stat()
        time.sleep(0.1)
        s2 = self.read_cpu_stat()
        idle1, idle2 = s1[3], s2[3]
        total1, total2 = sum(s1), sum(s2)
        total_delta = total2 - total1
        idle_delta = idle2 - idle1
        if total_delta <= 0:
            return 0
        return round((1 - idle_delta/total_delta)*100, 2)

    @staticmethod
    def get_linux_cpu_model():
        with open("/proc/cpuinfo") as f:
            for line in f:
                if "model name" in line:
                    return line.split(":")[1].strip()
        return "Unknown"

    @staticmethod
    def get_linux_cpu_freq():
        with open("/proc/cpuinfo") as f:
            for line in f:
                if "cpu MHz" in line:
                    return round(float(line.split(":")[1])/1000, 3)
        return None

    @staticmethod
    def get_linux_memory():
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, value = line.split(":")
                mem[key] = int(value.split()[0])*1024
        mem_total = mem.get("MemTotal", 0)
        mem_free = mem.get("MemAvailable", mem.get("MemFree", 0))
        mem_used = mem_total - mem_free
        swap_total = mem.get("SwapTotal", 0)
        swap_free = mem.get("SwapFree", 0)
        swap_used = swap_total - swap_free
        mem_percent = round(mem_used/mem_total*100, 2)
        swap_percent = round(swap_used/max(swap_total,1)*100,2)
        return mem_total, mem_used, mem_percent, swap_total, swap_used, swap_percent

    def read_net_dev(self):
        bytes_sent = bytes_recv = packets_sent = 0
        with open("/proc/net/dev") as f:
            for line in f:
                if ":" not in line:
                    continue
                iface, data = line.split(":")
                parts = data.split()
                bytes_recv += int(parts[0])
                bytes_sent += int(parts[8])
                packets_sent += int(parts[9])
        return bytes_sent, bytes_recv, packets_sent

    def get_linux_net_speed(self):
        old_sent, old_recv, _ = self.prev_net
        new_sent, new_recv, _ = self.read_net_dev()
        self.prev_net = (new_sent, new_recv, 0)
        return round((new_sent-old_sent)/1024,2), round((new_recv-old_recv)/1024,2)

    @staticmethod
    def get_linux_process_count():
        return sum(1 for pid in os.listdir("/proc") if pid.isdigit())

    @staticmethod
    def get_linux_disks():
        result = subprocess.check_output(
            "df -B1 --output=target,size,used,fstype",
            shell=True
        ).decode().splitlines()

        disks = []
        for line in result[1:]:
            parts = line.split()
            if len(parts) != 4:
                continue

            mount, total, used, fstype = parts
            total = int(total)
            used = int(used)

            # 过滤虚拟挂载
            skip_fs = [
                "tmpfs", "devtmpfs", "squashfs", "overlay"
            ]
            skip_prefix = [
                "/snap", "/run", "/sys", "/dev/shm", "/boot/efi"
            ]

            if fstype in skip_fs:
                continue

            if any(mount.startswith(p) for p in skip_prefix):
                continue

            percent = round(used/max(total,1)*100,2)
            disks.append((mount, total, used, percent))

        return disks

    @staticmethod
    def get_linux_uptime():
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])

    def update_info_linux(self):
        now = time.time()

        # CPU usage
        cpu_usage = self.get_linux_cpu_usage()

        # static params
        if not self.cached_static["cpu_model"]:
            self.cached_static["cpu_model"] = self.get_linux_cpu_model()
            self.cached_static["cpu_count"] = os.cpu_count()
            self.cached_static["cpu_freq"] = self.get_linux_cpu_freq()

        cpu_model = self.cached_static["cpu_model"]
        cpu_count = self.cached_static["cpu_count"]
        cpu_freq = self.cached_static["cpu_freq"]

        mem_total, mem_used, mem_percent, swap_total, swap_used, swap_percent = self.get_linux_memory()

        # if self.energy_saving_mode:
        #     sent_speed = recv_speed = 0
        #     net_sent, net_recv, packets_sent = self.prev_net
        # else:
        net_sent, net_recv, packets_sent = self.read_net_dev()
        sent_speed, recv_speed = self.get_linux_net_speed()

        if now - self.cached_static["last_disk_update"] > 60 or not self.cached_static["disks"]:
            self.cached_static["disks"] = self.get_linux_disks()
            self.cached_static["last_disk_update"] = now

        disks = self.cached_static["disks"]

        uptime = self.get_linux_uptime()

        self.system_info_dict.update({
            "cpu_usage": cpu_usage,
            "cpu_model": cpu_model,
            "cpu_count": cpu_count,
            "cpu_freq": cpu_freq,
            "mem_total": self.change_data_to_human_friendly(mem_total),
            "mem_used": self.change_data_to_human_friendly(mem_used),
            "mem_percent": mem_percent,
            "swap_total": self.change_data_to_human_friendly(swap_total),
            "swap_used": self.change_data_to_human_friendly(swap_used),
            "swap_percent": swap_percent,
            "network_sent": self.change_data_to_human_friendly(net_sent),
            "network_received": self.change_data_to_human_friendly(net_recv),
            "network_pocket_sent": packets_sent,
            "process_count": self.get_linux_process_count(),
            "disks": [
                (d[0], self.change_data_to_human_friendly(d[1]),
                 self.change_data_to_human_friendly(d[2]), d[3])
                for d in disks
            ],
            "sent_speed": "{} KB/s".format(sent_speed),
            "recv_speed": "{} KB/s".format(recv_speed),
            "uptime": self.change_time_to_human_friendly(uptime),
            "last_update": now_shanghai_str(),
            "secret_key": self.secret_key
        })

    # ===========================================================
    # WINDOWS SECTION
    # ===========================================================
    def get_windows_cpu(self):
        cpu_usage = psutil.cpu_percent(interval=0.1)
        cpu_model = platform.processor() or "Unknown"
        cpu_count = psutil.cpu_count()
        cpu_freq = psutil.cpu_freq()
        return cpu_usage, cpu_model, cpu_count, round(cpu_freq.max/1000,3)

    @staticmethod
    def get_windows_memory():
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        return mem.total, mem.used, mem.percent, swap.total, swap.used, swap.percent

    @staticmethod
    def get_windows_net():
        io = psutil.net_io_counters()
        return io.bytes_sent, io.bytes_recv, io.packets_sent

    @staticmethod
    def get_windows_process_count():
        return len(psutil.pids())

    @staticmethod
    def get_windows_disks():
        partitions = psutil.disk_partitions()
        disks = []
        for part in partitions:
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append((part.mountpoint, usage.total, usage.used, usage.percent))
            except:
                continue
        return disks

    @staticmethod
    def get_windows_uptime():
        return time.time() - psutil.boot_time()

    # Windows 实时网速（稳定版）
    def get_windows_realtime_network(self, interval=1):
        old = psutil.net_io_counters()
        time.sleep(interval)
        new = psutil.net_io_counters()
        sent_speed = (new.bytes_sent - old.bytes_sent) / interval / 1024
        recv_speed = (new.bytes_recv - old.bytes_recv) / interval / 1024
        return round(sent_speed, 2), round(recv_speed, 2)

    def update_info_windows(self):
        now = time.time()

        cpu_usage, cpu_model, cpu_count, cpu_freq = self.get_windows_cpu()
        mem_total, mem_used, mem_percent, swap_total, swap_used, swap_percent = self.get_windows_memory()
        net_sent, net_recv, net_pk_sent = self.get_windows_net()

        # if self.energy_saving_mode:
        #     sent_speed = recv_speed = 0
        # else:
        sent_speed, recv_speed = self.get_windows_realtime_network()

        # 每 60 秒更新一次磁盘
        if now - self.cached_static["last_disk_update"] > 60 or not self.cached_static["disks"]:
            self.cached_static["disks"] = self.get_windows_disks()
            self.cached_static["last_disk_update"] = now

        disks = self.cached_static["disks"]
        uptime = self.get_windows_uptime()

        self.system_info_dict.update({
            "cpu_usage": cpu_usage,
            "cpu_model": cpu_model,
            "cpu_count": cpu_count,
            "cpu_freq": cpu_freq,
            "mem_total": self.change_data_to_human_friendly(mem_total),
            "mem_used": self.change_data_to_human_friendly(mem_used),
            "mem_percent": mem_percent,
            "swap_total": self.change_data_to_human_friendly(swap_total),
            "swap_used": self.change_data_to_human_friendly(swap_used),
            "swap_percent": swap_percent,
            "network_sent": self.change_data_to_human_friendly(net_sent),
            "network_received": self.change_data_to_human_friendly(net_recv),
            "network_pocket_sent": net_pk_sent,
            "process_count": self.get_windows_process_count(),
            "disks": [
                (d[0], self.change_data_to_human_friendly(d[1]),
                 self.change_data_to_human_friendly(d[2]), d[3])
                for d in disks
            ],
            "sent_speed": "{} KB/s".format(sent_speed),
            "recv_speed": "{} KB/s".format(recv_speed),
            "uptime": self.change_time_to_human_friendly(uptime),
            "last_update": now_shanghai_str(),
            "secret_key": self.secret_key
        })

    # ===========================================================
    # 统一后台更新线程
    # ===========================================================
    def update_worker(self):
        while True:
            try:
                if SYSTEM == "Linux":
                    self.update_info_linux()
                elif SYSTEM == "Windows":
                    self.update_info_windows()
                res = json.loads(http_post(
                    "{}/api/host/update_host_details".format(self.api_address),
                    data=self.snake_to_small_camel(self.system_info_dict),
                    timeout=10
                ))
                if res["code"] != 200:
                    logging.error("Failed to update host details: {}".format(res['message']))
                    os._exit(0)
                if self.energy_saving_mode:
                    if SYSTEM == "Windows":
                        time.sleep(2)
                    else:
                        time.sleep(3)
                else:
                    time.sleep(2)
            except Exception as e:
                logging.error(e)


# ============================
# 退出处理
# ============================
def exit_func():
    global IS_EXITED
    IS_EXITED = True


def handle_exit(signum, frame):
    exit_func()


atexit.register(exit_func)
signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)


# ============================
# 主流程
# ============================
def main(energy_saving_mode=False):
    api_address, secret_key = ProcessParams().read_params()

    # ⚠ 可根据需要设为 True
    SystemMonitor(secret_key, api_address, energy_saving_mode=energy_saving_mode)
    logging.info("客户端正常运行")
    while True:
        if IS_EXITED:
            break
        time.sleep(1)


if __name__ == '__main__':
    main(True)
