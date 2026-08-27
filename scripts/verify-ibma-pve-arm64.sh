#!/usr/bin/env bash
set -euo pipefail

echo "== 内核模块 =="
for module_name in host_edma_drv host_cdev_drv host_veth_drv cdev_veth_drv host_kbox_drv; do
    if [[ -d /sys/module/$module_name ]]; then
        echo "$module_name: loaded"
    else
        echo "$module_name: not-loaded"
    fi
done

echo "== PCI 设备 =="
lspci -nnk -d 19e5:1710 || true

echo "== 字符设备与网络 =="
find /dev -maxdepth 1 \( -type c -o -type b \) \
    \( -name '*ibmc*' -o -name 'kbox' \) -print 2>/dev/null || true
ip -br link | grep -E '(^veth[[:space:]]|cdev)' || true
ip -br addr | grep -E '169\.254\.100\.' || true

echo "== 服务与进程 =="
systemctl --no-pager --full status iBMA.service || true
pgrep -af '/opt/ibma/bin/(Manager|Monitor|iBMA_RedfishMain)' || true
ss -lntp | grep -E ':8090|:8091' || true

echo "== 本地接口 =="
http_code=$(curl -k -sS -o /dev/null -w '%{http_code}' --max-time 5 \
    https://169.254.100.1:8090/redfish/v1/ || true)
echo "HTTPS Redfish HTTP 状态：${http_code:-unreachable}（未认证时 401 属于预期）"

echo "== 当前启动日志 =="
journalctl -b -u iBMA.service --no-pager -n 120 || true
dmesg --level=err,warn | grep -Ei 'edma|ibma|veth|cdev|kbox' | tail -n 120 || true
