# -*- encoding: utf-8 -*-
# 外部变量/注释开始
# 外部变量/注释结束
"""
@File    :   windows.py    
@Author  :   Guesser
@Modify Time      @Version    @Description
------------      --------    -----------
2025/10/25 1:22    1.0         None
"""
import atexit
import logging
import os
import signal
import subprocess
import threading
from datetime import datetime
import psutil
import platform
import time
import requests
logging.basicConfig(format='[%(asctime)s] %(levelname)s     %(message)s', level=logging.INFO)

IS_EXITED = False


class ProcessParams:
    def __init__(self):
        self.secret_key = ''
        self.api_address = ''
        self.path = "config.txt"

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
            user_input = input(f"请输入{item}\n")
            result += "{}={}\n".format(item, user_input)
        self.write(self.path,result)

    def check_params(self):
        if self.secret_key and self.api_address and self.api_address.startswith('http'):
            logging.info("参数检查通过")
            return True
        logging.error("密钥为空或api地址为空或api地址未以http/https开头")
        return False

    def read_params(self):
        if os.path.exists(self.path):
            raw_data = self.open(self.path)
            for line in raw_data.splitlines():
                key, value = line.split('=')
                if key.strip() == 'secret_key':
                    self.secret_key = value.strip()
                if key.strip() == 'api_address':
                    self.api_address = value.strip()
        if self.check_params():
            logging.info("成功获取到运行必要参数")
            return self.api_address, self.secret_key
        else:
            self.ask_user_params()
            return self.read_params()


class SystemMonitor:
    """系统监测类：用于获取CPU、内存、网络、进程及磁盘等系统运行信息"""

    def __init__(self, secret_key:str):
        self.prompt = "系统监测"
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
            "secret_key": None,
            "os": self.get_os_pretty_name()
        }
        self.secret_key = secret_key
        threading.Thread(target=self.update_worker).start()

    @staticmethod
    def get_os_pretty_name():
        system = platform.system()

        # Windows
        if system == "Windows":
            try:
                result = subprocess.check_output("wmic os get Caption", shell=True)
                lines = result.decode().strip().split("\n")
                if len(lines) > 1:
                    return lines[1].strip()
            except Exception:
                return f"Windows {platform.release()}"

        # Linux
        elif system == "Linux":
            try:
                with open("/etc/os-release") as f:
                    info = {}
                    for line in f:
                        if "=" in line:
                            k, v = line.strip().split("=", 1)
                            info[k] = v.strip('"')
                return f"{info.get('NAME', 'Linux')} {info.get('VERSION', '').strip()}"
            except Exception:
                return f"Linux {platform.release()}"

        # macOS
        elif system == "Darwin":
            try:
                version = subprocess.check_output(["sw_vers", "-productVersion"]).decode().strip()
                return f"macOS {version}"
            except Exception:
                return "macOS (unknown version)"

        # 其他系统
        else:
            return f"{system} {platform.release()}"

    @staticmethod
    def get_uptime():
        return time.time() - psutil.boot_time()

    @staticmethod
    def get_cpu_info() -> tuple[float, str, int, float]:
        """
        获取CPU使用信息
        :returns:
            float: CPU总使用率（百分比）
            str: CPU型号名称
            int: CPU逻辑处理器数
        """
        cpu_usage = psutil.cpu_percent(interval=0.1)
        cpu_model = platform.processor() or "Unknown"
        cpu_cores = psutil.cpu_count()
        cpu_freq = psutil.cpu_freq()
        return cpu_usage, cpu_model, cpu_cores, round(cpu_freq.max / 1000,3)

    @staticmethod
    def get_memory_info() -> tuple[int, int, float, int, int, float]:
        """
        获取内存与交换分区使用信息
        :returns:
            int: 物理内存总量（字节）
            int: 已使用物理内存（字节）
            float: 物理内存使用率（百分比）
            int: 交换分区总量（字节）
            int: 已使用交换分区（字节）
            float: 交换分区使用率（百分比）
        """
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        return mem.total, mem.used, mem.percent, swap.total, swap.used, swap.percent

    @staticmethod
    def get_network_info() -> tuple[int, int, int]:
        """
        获取网络总体流量信息（非实时）
        :returns:
            int: 已发送字节数
            int: 已接收字节数
            int: 已发送数据包数
        """
        net_io = psutil.net_io_counters()
        return net_io.bytes_sent, net_io.bytes_recv, net_io.packets_sent

    @staticmethod
    def get_process_count() -> int:
        """
        获取当前运行的进程数量
        :returns:
            int: 进程总数
        """
        return len(psutil.pids())

    @staticmethod
    def get_disk_usage() -> list[tuple[str, int, int, float]]:
        """
        获取所有磁盘分区的使用信息
        :returns:
            list[tuple]:
                每个元素为 (挂载点, 总空间, 已用空间, 使用率%)
        """
        partitions = psutil.disk_partitions()
        disk_info_list = []
        for part in partitions:
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disk_info_list.append((part.mountpoint, usage.total, usage.used, usage.percent))
            except PermissionError:
                # 某些系统分区（如虚拟盘）可能无法访问
                continue
        return disk_info_list

    @staticmethod
    def get_realtime_network(interval=1) -> tuple[float, float]:
        """
        获取实时网络上下行速率
        :param interval: 采样间隔秒数
        :returns:
            float: 上传速度（KB/s）
            float: 下载速度（KB/s）
        """
        old = psutil.net_io_counters()
        time.sleep(interval)
        new = psutil.net_io_counters()
        sent_speed = (new.bytes_sent - old.bytes_sent) / interval / 1024
        recv_speed = (new.bytes_recv - old.bytes_recv) / interval / 1024
        return sent_speed, recv_speed

    @staticmethod
    def change_data_to_human_friendly(data:int| float, units:str = "bytes", goal:str = None) -> str:
        """
        :arg
                data: 要转换的原值
                units: 原值的单位
                goal: 目标单位,默认转换为>1单位的数据
        :returns:
                str: 转换结果,保留三位小数
        """
        change_dict = {
            "bytes": 1,
            "KB": 1024,
            "MB": 1048576,
            "GB": 1073741824,
            "TB": 1099511627776
        }
        if goal and goal in change_dict:
            return f"{round(data / change_dict[goal], 3)} {goal}"
        for k, v in change_dict.items():
            # 先转换为bytes
            result = data * change_dict[units] / v
            if result < 1024:
                return f"{round(result, 3)} {k}"
        return f"{round(data * change_dict[units] / change_dict['TB'], 3)} TB"

    @staticmethod
    def change_time_to_human_friendly(time_data:int| float) -> str:
        """
        :arg
            time_data: 转换对象,单位为s
        :return:
            str: 转换后的字符串
        """
        # 一个月30天 一年365天
        change_dict = {
            "years": 31536000,
            "months": 2592000,
            "weeks": 604800,
            "days": 86400,
            "hours": 3600,
            "minutes": 60,
            "seconds": 1
        }
        result = ""
        for k, v in change_dict.items():
            quotient = time_data / v
            remainder = time_data % v
            if quotient >= 1:
                time_data = remainder
                result += f"{int(quotient)}{k} "
        return result[:-1]

    def process_all_info(self):
        """
        采集系统全部信息并更新到 self.system_info_dict，
        同时格式化打印人类可读输出。
        """
        # 采集各项数据
        cpu_usage, cpu_model, cpu_cores, cpu_freq = self.get_cpu_info()
        mem_total, mem_used, mem_percent, swap_total, swap_used, swap_percent = self.get_memory_info()
        net_sent, net_recv, net_pk_sent = self.get_network_info()
        process_count = self.get_process_count()
        disks = self.get_disk_usage()
        sent_speed, recv_speed = self.get_realtime_network()

        # 更新内部字典
        self.system_info_dict.update({
            "cpu_usage": cpu_usage,
            "cpu_model": cpu_model,
            "cpu_count": cpu_cores,
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
            "process_count": process_count,
            "disks": [(disk[0],
                       self.change_data_to_human_friendly(disk[1]),
                       self.change_data_to_human_friendly(disk[2]),
                       round(disk[2] / disk[1] * 100, 3))
                      for disk in disks],
            "sent_speed": self.change_data_to_human_friendly(sent_speed),
            "recv_speed": self.change_data_to_human_friendly(recv_speed),
            "uptime": self.change_time_to_human_friendly(self.get_uptime()),
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "secret_key": self.secret_key
        })

    def update_worker(self, refresh_interval:int = 0.5) -> None:
        # 用于异步更新数据,网络会花1s,cpu使用率会花0.1s
        """:arg
                refresh_interval: 更新频率"""
        while True:
            if IS_EXITED:
                return
            self.process_all_info()
            time.sleep(refresh_interval)

    @staticmethod
    def snake_to_small_camel(data:dict) -> dict:
        new_dict = {}
        for k, v in data.items():
            if "_" not in k:
                new_dict[k] = v
                continue
            parts = k.split('_')
            new_dict[parts[0].lower() + ''.join(word.capitalize() for word in parts[1:])] = v
        return new_dict

    def print(self):
        info = self.system_info_dict
        print(f"\n=== 系统状态更新时间: {info.get('last_update')} ===")
        print(f"CPU: {info['cpu_model']} | 使用率: {info['cpu_usage']}% | 核心数: {info['cpu_count']} | 基准速度：{info['cpu_freq']}GHz")
        print(f"操作系统: {info['os']}")
        print(f"不间断运行时间: {info['uptime']}")
        print(f"内存: {info['mem_used']} / {info['mem_total']} ({info['mem_percent']}%)")
        print(f"交换分区: {info['swap_used']} / {info['swap_total']} ({info['swap_percent']}%)")
        print(f"网络: ↑ {info['sent_speed']}/s ↓ {info['recv_speed']}/s")
        print(f"总发送: {info['network_sent']} | 总接收: {info['network_received']}")
        print(f"进程数: {info['process_count']}")
        print("磁盘使用情况:")
        for disk in info["disks"]:
            print(f"  - {disk[0]}: {disk[2]} / {disk[1]} {disk[3]}%")
        print("=" * 50)


def exit_func():
    global IS_EXITED
    if IS_EXITED:
        return
    IS_EXITED = True


def handle_exit(signum, frame):
    exit_func()


atexit.register(exit_func)
signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)


def main():
    global IS_EXITED
    api_address, secret_key = ProcessParams().read_params()
    # api_address = "http://192.168.153.135"
    # secret_key = "gJXoyo44y8NtsyaUCR"
    monitor = SystemMonitor(secret_key)
    time.sleep(4)
    logging.info("客户端正常运行")
    while True:
        if IS_EXITED:
            break
        try:
            time.sleep(2)
            requests.post(f"{api_address}/api/host/update_host_details",
                              json=monitor.snake_to_small_camel(monitor.system_info_dict),timeout=10)
        except Exception as e:
            logging.error(str(e))
            time.sleep(2)


if __name__ == '__main__':
    main()
