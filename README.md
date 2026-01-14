# 快速安装命令
```
curl -fsSL https://raw.githubusercontent.com/biubiu258/host_manager_client/main/install.sh -o install.sh
chmod +x install.sh
sudo ./install.sh
```
# 🖥️ SystemMonitor 客户端程序

一个跨平台（Windows / Linux / macOS）系统监控客户端，用于实时采集主机 CPU、内存、磁盘、网络等信息，并定时上传到指定 API 服务端。  
程序支持自动配置、进程监控、多线程实时刷新、异常处理、系统优雅退出等特性。

---

## ✨ 功能特性

- **系统信息采集**
  - CPU 使用率、型号、核心数、频率
  - 内存与 Swap 使用情况
  - 网络流量与实时上下行速度
  - 进程数量
  - 磁盘分区使用情况
  - 系统开机时间（uptime）
  - 操作系统类型与版本
- **自动配置**
  - 启动时读取 `config.txt`
  - 若缺失或错误，会自动引导用户输入参数（API 地址、密钥）
- **数据自动上报**
  - 将监控结果自动转换为 camelCase 并 POST 到服务器：
    ```
    POST <api_address>/api/host/update_host_details
    ```
- **跨平台支持**（Windows / Linux / macOS）
- **优雅退出**
  - 捕获 `SIGINT`、`SIGTERM` 以及 `atexit` 钩子
  - 自动释放资源与关闭线程

---

## 📦 项目结构

```
windows.py     # 主程序
config.txt     # 程序配置文件（首次启动可自动生成）
```

---

## ⚙️ 安装与运行

### 1. 安装依赖

```bash
pip install psutil requests
```

### 2. 配置 API 信息

程序将自动读取 `config.txt`：

```txt
api_address=http://your_api_server
secret_key=your_secret_key
```

如果该文件不存在或内容非法，程序将自动提示你输入：

```
请输入api_address
请输入secret_key
```

### 3. 启动程序

```bash
python windows.py
```

启动成功后，程序会：

- 自动初始化系统监控线程
- 每隔 2 秒向服务器发送系统状态数据
- 控制台输出系统运行日志

---

## 🧩 系统监控说明

`SystemMonitor` 类会在后台线程持续刷新系统信息，结构如下：

```python
self.system_info_dict = {
    "cpu_usage": ...,
    "cpu_model": ...,
    "cpu_count": ...,
    "cpu_freq": ...,
    "mem_total": ...,
    "mem_used": ...,
    "mem_percent": ...,
    "swap_total": ...,
    "swap_used": ...,
    "swap_percent": ...,
    "network_sent": ...,
    "network_received": ...,
    "network_pocket_sent": ...,
    "process_count": ...,
    "disks": [...],
    "uptime": ...,
    "sent_speed": ...,
    "recv_speed": ...,
    "os": ...,
    "secret_key": ...
}
```

上传前会自动转换为 **小驼峰格式（camelCase）**。

---

## 🛠️ API 上传逻辑

每隔 **2 秒**程序执行：

```python
requests.post(
    f"{api_address}/api/host/update_host_details",
    json=monitor.snake_to_small_camel(monitor.system_info_dict),
    timeout=10
)
```

若 API 连接失败，会自动记录错误并继续重试。

---

## 📴 程序退出机制

支持以下关闭方式：

- Ctrl+C（SIGINT）
- kill 命令（SIGTERM）
- 程序自然退出（atexit）

退出时会：

- 设置全局变量 `IS_EXITED = True`
- 停止后台监控线程
- 停止 API 上传循环

---

## 📚 核心类说明

### `ProcessParams`

- 管理程序配置
- 读取/写入 `config.txt`
- 校验 API 地址与密钥
- 自动提示用户输入缺省配置

### `SystemMonitor`

- 单线程后台刷新系统信息
- 提供统一的字典结构用于上传
- 提供多处工具函数（单位转换、时间转换等）

### 主程序 `main()`

- 初始化配置
- 启动监控线程
- 持续上报 API

---

## 🔒 安全说明

- `secret_key` 会被一同上传用于服务端验证
- 程序不会将密钥输出至日志
- 程序不会采集敏感信息，仅采集系统状态

---

