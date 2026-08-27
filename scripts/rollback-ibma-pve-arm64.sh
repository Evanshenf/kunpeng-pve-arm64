#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "必须以 root 执行。" >&2
    exit 1
fi

kernel=$(uname -r)
stamp=$(date +%Y%m%d-%H%M%S)
quarantine="/root/maintenance-backup/ibma-rollback-$stamp"
install -d -m 0700 "$quarantine"

systemctl stop iBMA.service 2>/dev/null || true
systemctl disable iBMA.service 2>/dev/null || true

for module_name in host_kbox_drv cdev_veth_drv host_veth_drv host_cdev_drv host_edma_drv; do
    if [[ -d /sys/module/$module_name ]]; then
        modprobe -r "$module_name"
    fi
done

if [[ -e /opt/ibma ]]; then
    mv /opt/ibma "$quarantine/ibma"
fi
if [[ -e /etc/systemd/system/iBMA.service ]]; then
    mv /etc/systemd/system/iBMA.service "$quarantine/iBMA.service"
fi
if [[ -e "/lib/modules/$kernel/updates/iBMA_driver" ]]; then
    mv "/lib/modules/$kernel/updates/iBMA_driver" "$quarantine/iBMA_driver"
fi
if [[ -L /usr/local/bin/ibmacli ]]; then
    mv /usr/local/bin/ibmacli "$quarantine/ibmacli.link"
fi

depmod -a "$kernel"
systemctl daemon-reload
echo "iBMA 已停止并迁移到：$quarantine"
