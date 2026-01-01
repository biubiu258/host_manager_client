#!/usr/bin/env bash
set -euo pipefail

# ========= 可按需改的默认值 =========
APP_NAME="host-manager-client"
INSTALL_DIR="/opt/host_manager_client"
CLIENT_URL="https://raw.githubusercontent.com/biubiu258/host_manager_client/main/client.py"
PYTHON_BIN="/usr/bin/python3"
RUN_USER="root"   # 如需用普通用户运行，改成用户名（并确保该用户对 INSTALL_DIR 有读写权限）

SERVICE_PATH="/etc/systemd/system/${APP_NAME}.service"
CONFIG_PATH="${INSTALL_DIR}/config.txt"
CLIENT_PATH="${INSTALL_DIR}/client.py"

# ========= 工具检查 =========
need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "缺少命令：$1"; exit 1; }; }
need_cmd "${PYTHON_BIN}"
need_cmd systemctl
need_cmd mkdir
need_cmd chmod
need_cmd tee

download_file() {
  local url="$1"
  local out="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$out"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$out" "$url"
  else
    echo "缺少下载工具：curl 或 wget"
    exit 1
  fi
}

echo_step() { echo -e "\n==> $*"; }

# ========= 0) 必须 root 执行 =========
if [[ "${EUID}" -ne 0 ]]; then
  echo "请用 sudo 运行：sudo bash $0"
  exit 1
fi

# ========= 1) 下载主脚本 =========
echo_step "创建目录：${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"

echo_step "下载 client.py"
download_file "${CLIENT_URL}" "${CLIENT_PATH}"
chmod 0755 "${CLIENT_PATH}"
echo "已下载到：${CLIENT_PATH}"

# ========= 2) Shell 引导写配置（替代 Python input） =========
echo_step "引导填写配置（将写入 ${CONFIG_PATH}）"

# 读取输入（带提示），非空校验
read_nonempty() {
  local key="$1"
  local val=""
  while true; do
    read -r -p "请输入 ${key}: " val
    if [[ -n "${val}" ]]; then
      echo "${val}"
      return 0
    fi
    echo "不能为空，请重新输入。"
  done
}

API_ADDRESS="$(read_nonempty api_address)"
SECRET_KEY="$(read_nonempty secret_key)"

# 写入 config.txt（覆盖写，权限尽量收紧）
umask 077
cat > "${CONFIG_PATH}" <<EOF
api_address=${API_ADDRESS}
secret_key=${SECRET_KEY}
EOF
chmod 0600 "${CONFIG_PATH}"
echo "配置已写入：${CONFIG_PATH}"

# ========= 3) 添加/覆盖 systemd 服务并启动 =========
echo_step "写入 systemd service：${SERVICE_PATH}"

# 如果旧服务存在，先停掉并禁用（再覆盖）
if [[ -f "${SERVICE_PATH}" ]]; then
  echo "检测到旧的 ${APP_NAME}.service，正在停止并覆盖..."
  systemctl stop "${APP_NAME}" >/dev/null 2>&1 || true
  systemctl disable "${APP_NAME}" >/dev/null 2>&1 || true
fi

cat > "${SERVICE_PATH}" <<EOF
[Unit]
Description=Host Manager Client (Python)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${PYTHON_BIN} ${CLIENT_PATH}
Restart=always
RestartSec=3
User=${RUN_USER}
Environment=PYTHONUNBUFFERED=1

# 日志走 journalctl（推荐）
# StandardOutput=journal
# StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

chmod 0644 "${SERVICE_PATH}"

echo_step "systemd daemon-reload"
systemctl daemon-reload

echo_step "启用开机自启并启动"
systemctl enable --now "${APP_NAME}"

echo_step "查看状态"
systemctl --no-pager status "${APP_NAME}" || true

echo_step "安装完成 ✅"
echo "后续常用命令："
echo "  查看日志：sudo journalctl -u ${APP_NAME} -f"
echo "  重启服务：sudo systemctl restart ${APP_NAME}"
echo "  停止服务：sudo systemctl stop ${APP_NAME}"
echo "  禁用自启：sudo systemctl disable ${APP_NAME}"
