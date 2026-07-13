#!/usr/bin/env bash
set -euo pipefail
APP_NAME="host-manager-client"
INSTALL_DIR="/opt/host_manager_client"
SERVICE_PATH="/etc/systemd/system/${APP_NAME}.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 sudo 执行此卸载脚本"
  exit 1
fi

echo "1. 停止并禁用服务"
systemctl stop "$APP_NAME" 2>/dev/null || true
systemctl disable "$APP_NAME" 2>/dev/null || true

echo "2. 删除systemd服务文件"
rm -f "$SERVICE_PATH"
systemctl daemon-reload
systemctl reset-failed

echo "3. 删除程序及配置目录"
rm -rf "$INSTALL_DIR"

echo "卸载完成，所有任务与文件已清理干净"
