#!/usr/bin/env bash
set -euo pipefail

timeout_seconds="${NPU_READY_TIMEOUT_SECONDS:-180}"
deadline=$((SECONDS + timeout_seconds))
env_file="${ENV_FILE:-/etc/vision-qwen3vl/runtime.env}"
visible_devices="$(sed -n 's/^ASCEND_RT_VISIBLE_DEVICES=//p' "$env_file" | tail -n 1)"
visible_devices="${visible_devices:-0}"

if [[ ! "$visible_devices" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
    printf 'ASCEND_RT_VISIBLE_DEVICES 格式无效：%s\n' "$visible_devices" >&2
    exit 1
fi

devices=(
    /dev/davinci_manager
    /dev/devmm_svm
    /dev/hisi_hdc
)
IFS=',' read -r -a device_ids <<< "$visible_devices"
for device_id in "${device_ids[@]}"; do
    devices+=("/dev/davinci${device_id}")
done

while (( SECONDS < deadline )); do
    ready=true
    for device in "${devices[@]}"; do
        if [[ ! -c "$device" ]]; then
            ready=false
            break
        fi
    done

    if [[ "$ready" == true ]] && timeout 10 npu-smi info >/dev/null 2>&1; then
        exit 0
    fi

    sleep 2
done

printf '等待 NPU 设备就绪超时（%s 秒）\n' "$timeout_seconds" >&2
exit 1
