#!/usr/bin/env bash
set -euo pipefail

MODEL_PATH="${MODEL_PATH:-/models/qwen3vl}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-qwen3-vl-4b}"
PORT="${PORT:-8000}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-4}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.85}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-1}"
DATA_PARALLEL_SIZE="${DATA_PARALLEL_SIZE:-1}"
API_SERVER_COUNT="${API_SERVER_COUNT:-1}"
LOAD_FORMAT="${LOAD_FORMAT:-sharded_state}"

export ASCEND_RT_VISIBLE_DEVICES="${ASCEND_RT_VISIBLE_DEVICES:-0}"
export PYTORCH_NPU_ALLOC_CONF="${PYTORCH_NPU_ALLOC_CONF:-expandable_segments:True}"
export OMP_PROC_BIND="${OMP_PROC_BIND:-false}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export TASK_QUEUE_ENABLE="${TASK_QUEUE_ENABLE:-1}"
export GLOO_SOCKET_IFNAME="${GLOO_SOCKET_IFNAME:-lo}"

args=(
    serve "$MODEL_PATH"
    --host 0.0.0.0
    --port "$PORT"
    --served-model-name "$SERVED_MODEL_NAME"
    --dtype float16
    --quantization ascend
    --load-format "$LOAD_FORMAT"
    --tensor-parallel-size "$TENSOR_PARALLEL_SIZE"
    --data-parallel-size "$DATA_PARALLEL_SIZE"
    --api-server-count "$API_SERVER_COUNT"
    --max-model-len "$MAX_MODEL_LEN"
    --max-num-seqs "$MAX_NUM_SEQS"
    --max-num-batched-tokens 4096
    --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION"
    --trust-remote-code
    --no-enable-prefix-caching
    --limit-mm-per-prompt '{"image":4,"video":0}'
    --mm-processor-cache-gb 0
    --additional-config '{"ascend_compilation_config":{"enable_npugraph_ex":false,"fuse_norm_quant":false}}'
)

if [[ "${VLLM_EXECUTION_MODE:-eager}" == "graph" ]]; then
    args+=(
        --compilation-config
        '{"cudagraph_mode":"FULL_DECODE_ONLY","cudagraph_capture_sizes":[1,2,4]}'
    )
else
    args+=(--enforce-eager)
fi

exec vllm "${args[@]}"
