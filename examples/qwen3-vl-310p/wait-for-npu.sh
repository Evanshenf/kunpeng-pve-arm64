#!/usr/bin/env bash
set -euo pipefail

timeout_seconds="${NPU_READY_TIMEOUT_SECONDS:-180}"
deadline=$((SECONDS + timeout_seconds))
devices=(
    /dev/davinci0
    /dev/davinci_manager
    /dev/devmm_svm
    /dev/hisi_hdc
)

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
