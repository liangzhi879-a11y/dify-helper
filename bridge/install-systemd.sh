#!/bin/bash
# Dify Bridge systemd 安装脚本
# 用法: sudo bash install-systemd.sh
set -e

SERVICE_NAME=dify-bridge
SERVICE_SRC="/home/sutai/dify-helper/bridge/dify-bridge.service"
SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}.service"

echo "==> 复制 service 文件到 ${SERVICE_DST}"
sudo cp "${SERVICE_SRC}" "${SERVICE_DST}"
sudo chmod 644 "${SERVICE_DST}"

echo "==> 重新加载 systemd"
sudo systemctl daemon-reload

echo "==> 停止现有 nohup bridge 进程（避免端口冲突）"
# 杀掉所有 bridge.app 进程（除自己外）
pkill -f "python -m bridge.app" 2>/dev/null || true
# 注意：service 文件里 WorkingDirectory=/home/sutai/dify-helper/bridge 是必需的，
# 因为 app.py 用 load_config("config.yaml") 相对路径找配置文件
sleep 1

echo "==> 启用并启动服务"
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl start "${SERVICE_NAME}"

echo "==> 等待 3 秒"
sleep 3

echo "==> 服务状态"
sudo systemctl status "${SERVICE_NAME}" --no-pager -l | head -20

echo ""
echo "==> 健康检查"
curl -s http://127.0.0.1:8002/health || echo "❌ health 失败"

echo ""
echo "==> 常用命令"
echo "  查看状态:   sudo systemctl status dify-bridge"
echo "  查看日志:   sudo journalctl -u dify-bridge -f"
echo "  停止:       sudo systemctl stop dify-bridge"
echo "  重启:       sudo systemctl restart dify-bridge"
echo "  禁用自启:   sudo systemctl disable dify-bridge"
