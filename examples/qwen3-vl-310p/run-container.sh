#!/usr/bin/env bash
set -euo pipefail

IMAGE="${IMAGE:-local/vllm-ascend:qwen3vl-0.23.0-310p}"
ENV_FILE="${ENV_FILE:-/etc/vision-qwen3vl/runtime.env}"
MODEL_DIR="${MODEL_DIR:-/srv/models/Qwen3-VL-4B-Instruct-w8a8sc-310-vllm-tp1}"

visible_devices="$(sed -n 's/^ASCEND_RT_VISIBLE_DEVICES=//p' "$ENV_FILE" | tail -n 1)"
visible_devices="${visible_devices:-0}"
if [[ ! "$visible_devices" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
    printf 'Invalid ASCEND_RT_VISIBLE_DEVICES: %s\n' "$visible_devices" >&2
    exit 1
fi

device_args=()
IFS=',' read -r -a device_ids <<< "$visible_devices"
for device_id in "${device_ids[@]}"; do
    device_node="/dev/davinci${device_id}"
    if [[ ! -c "$device_node" ]]; then
        printf 'NPU device node does not exist: %s\n' "$device_node" >&2
        exit 1
    fi
    device_args+=(--device "$device_node")
done

exec docker run --rm \
    --name vision-qwen3vl \
    --network host \
    --hostname vision-qwen3vl \
    --add-host vision-qwen3vl:127.0.1.1 \
    --add-host vision-qwen3vl.local:127.0.1.1 \
    --shm-size 10g \
    --ulimit nofile=65536:65536 \
    --env-file "$ENV_FILE" \
    "${device_args[@]}" \
    --device /dev/davinci_manager \
    --device /dev/devmm_svm \
    --device /dev/hisi_hdc \
    --volume /usr/local/dcmi:/usr/local/dcmi:ro \
    --volume /usr/local/bin/npu-smi:/usr/local/bin/npu-smi:ro \
    --volume /usr/local/sbin/npu-smi:/usr/local/sbin/npu-smi:ro \
    --volume /usr/local/Ascend/driver/lib64:/usr/local/Ascend/driver/lib64:ro \
    --volume /usr/local/Ascend/driver/version.info:/usr/local/Ascend/driver/version.info:ro \
    --volume /etc/ascend_install.info:/etc/ascend_install.info:ro \
    --volume "$MODEL_DIR":/models/qwen3vl:ro \
    --volume /var/cache/vision-qwen3vl:/root/.cache/vllm \
    --volume /opt/vision-qwen3vl/start-vllm.sh:/usr/local/bin/start-vllm:ro \
    --entrypoint /usr/local/bin/start-vllm \
    "$IMAGE"
