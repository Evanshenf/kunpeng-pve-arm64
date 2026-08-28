ARG BASE_IMAGE=quay.io/ascend/vllm-ascend@sha256:ffeb177dd585f567036f0a51a76adc6e109599f705385fbe66652d9fe76431ab
FROM ${BASE_IMAGE}

COPY patch_mm_merge_310p.py \
    /vllm-workspace/vllm-ascend/vllm_ascend/patch/platform/patch_mm_merge_310p.py
COPY install_patch.py /tmp/install_patch.py

RUN python3 /tmp/install_patch.py \
    && python3 -m py_compile \
        /vllm-workspace/vllm-ascend/vllm_ascend/patch/platform/patch_mm_merge_310p.py \
    && unlink /tmp/install_patch.py

LABEL org.opencontainers.image.title="vLLM Ascend 310P Qwen3-VL runtime" \
      org.opencontainers.image.version="0.23.0-local.1" \
      org.opencontainers.image.source="https://github.com/vllm-project/vllm-ascend/pull/12914"
