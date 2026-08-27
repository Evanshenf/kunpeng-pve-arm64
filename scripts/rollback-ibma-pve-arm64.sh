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

hibmc_reboot_required=false
if [[ -d /sys/module/hibmc_drm ]]; then
    hibmc_reboot_required=true
    echo "hibmc_drm 正在提供 framebuffer，本次不在线强制卸载；清理持久配置后需重启。"
fi

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
if [[ -e "/lib/modules/$kernel/updates/HiBMC_driver" ]]; then
    mv "/lib/modules/$kernel/updates/HiBMC_driver" "$quarantine/HiBMC_driver"
fi
if [[ -e /etc/modules-load.d/hibmc-drm.conf ]]; then
    mv /etc/modules-load.d/hibmc-drm.conf "$quarantine/hibmc-drm.conf"
fi
if [[ -L /usr/local/bin/ibmacli ]]; then
    mv /usr/local/bin/ibmacli "$quarantine/ibmacli.link"
fi

depmod -a "$kernel"
systemctl daemon-reload
echo "iBMA 已停止并迁移到：$quarantine"
if $hibmc_reboot_required; then
    echo "必须正常重启一次，才能由固件 framebuffer/simpledrm 重新接管显示。"
fi
