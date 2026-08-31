# Qwen3-VL on Ascend 310P vNPU

[中文文档](../../docs/qwen3-vl-vnpu.md) | [English guide](../../docs/en/qwen3-vl-vnpu.md)

This directory contains the public, credential-free files used to run a TP1
Qwen3-VL W8A8SC checkpoint on an Ascend 310P `vir04` guest or on multiple
physical 310P chips with vLLM data parallelism.

It does not contain model weights, vendor drivers, container layers, or API
keys. Obtain those artifacts from their authorized sources.

The image patch follows vllm-ascend PR #12914 and replaces the failing 310P
AICPU boolean `IndexPut` path with integer-index `index_copy_`.

Quick outline:

```bash
docker build -t local/vllm-ascend:qwen3vl-0.23.0-310p .
install -d -m 0755 /opt/vision-qwen3vl /var/cache/vision-qwen3vl
install -m 0755 run-container.sh start-vllm.sh wait-for-npu.sh \
    /opt/vision-qwen3vl/
install -d -m 0750 /etc/vision-qwen3vl
install -m 0600 runtime.env.example /etc/vision-qwen3vl/runtime.env
install -m 0644 vision-qwen3vl.service /etc/systemd/system/
```

Replace the example API key, place the tested TP1 model under the path expected
by `run-container.sh`, then enable the service. Do not expose the plain HTTP
endpoint directly to an untrusted network.

For a four-chip physical guest, set `ASCEND_RT_VISIBLE_DEVICES=0,1,2,3`,
`DATA_PARALLEL_SIZE=4`, `TENSOR_PARALLEL_SIZE=1`, and `API_SERVER_COUNT=1`.
The launcher mounts only the requested `/dev/davinci*` nodes. A TP1
`sharded_state` checkpoint must remain at `TENSOR_PARALLEL_SIZE=1` unless a
separately generated TP checkpoint is available.
