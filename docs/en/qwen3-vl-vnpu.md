# Qwen3-VL Inference on an Ascend 310P vNPU

[Chinese](../qwen3-vl-vnpu.md)

## 1. Validated Goal

This guide runs a TP1 Qwen3-VL-4B-Instruct W8A8SC checkpoint with vLLM Ascend
inside an openEuler guest backed by an Atlas 300I Duo `vir04` mdev:

```text
PVE ARM64 -> VFIO mdev / vir04 -> openEuler guest
  -> Ascend vnpu_guest driver -> Docker -> vLLM Ascend -> Qwen3-VL
```

The repository contains only source patches, scripts, and configuration. It
does not redistribute model weights, vendor drivers, container layers, or API
keys.

## 2. Tested Baseline

| Item | Configuration |
| --- | --- |
| Host | PVE 9.2.9 ARM64, Linux `7.0.14-6-pve` |
| Accelerator | Atlas 300I Duo / Ascend 310P3 |
| vNPU | `vir04`, 4 AI Cores and 24 GB |
| Guest | openEuler 24.03 LTS SP3, 16 vCPUs, 32 GiB RAM |
| Guest driver | Ascend 25.2.0 `vnpu_guest` |
| Docker | 25.0.3 |
| Base image | `quay.io/ascend/vllm-ascend:v0.23.0-310p-openeuler`, ARM64 |
| Model | Qwen3-VL-4B-Instruct W8A8SC TP1 |

PVE assignment example:

```bash
qm set <VMID> -hostpci0 <BDF>,mdev=vnpu-vir04
```

Do not add `pcie=1` to an ARM `virt` machine. See the
[Atlas vNPU guide](ascend-310p-vnpu-pve.md) for host-driver and mdev setup.

## 3. 310P Multimodal Workaround

On the tested vLLM Ascend 0.23.0 stack, multimodal embedding merge can hit an
AICPU `IndexPut` failure with error `507018` on 310P. The files under
[`examples/qwen3-vl-310p`](../../examples/qwen3-vl-310p/) follow
vllm-ascend PR #12914 and replace boolean-mask `index_put_` with integer-index
`index_copy_` on 310P only.

Build the pinned image:

```bash
cd examples/qwen3-vl-310p
docker build -t local/vllm-ascend:qwen3vl-0.23.0-310p .
```

Remove the local monkey patch and retest when a later upstream release carries
an equivalent fix.

## 4. Guest Deployment

Confirm the guest device and Docker first:

```bash
npu-smi info
docker version
```

The device should report `310Pvir04` and `Health: OK`. Obtain a compatible TP1
checkpoint from an authorized source and record its origin, version, size, and
SHA-256. The example scripts expect it at:

```text
/srv/models/Qwen3-VL-4B-Instruct-w8a8sc-310-vllm-tp1
```

Install the runtime files:

```bash
install -d -m 0755 /opt/vision-qwen3vl /var/cache/vision-qwen3vl
install -m 0755 run-container.sh start-vllm.sh wait-for-npu.sh \
    /opt/vision-qwen3vl/
install -d -m 0750 /etc/vision-qwen3vl
install -m 0600 runtime.env.example /etc/vision-qwen3vl/runtime.env
install -m 0644 vision-qwen3vl.service /etc/systemd/system/
```

Replace the example API key with a random secret and keep the environment file
at mode `0600`. Never commit the real value.

```bash
openssl rand -hex 32
systemctl daemon-reload
systemctl enable --now vision-qwen3vl.service
```

`wait-for-npu.sh` checks the required device nodes and `npu-smi` before Docker
starts. Initial model compilation and graph capture can take several minutes;
use an HTTP 200 response from `/health` as the readiness condition.

The same scripts support data parallelism with physical devices. A full-card
guest can set the following values in `runtime.env`:

```text
ASCEND_RT_VISIBLE_DEVICES=0,1,2,3
TENSOR_PARALLEL_SIZE=1
DATA_PARALLEL_SIZE=4
API_SERVER_COUNT=1
LOAD_FORMAT=sharded_state
```

See the [full VFIO passthrough guide](ascend-310p-vfio-pve.md) for host setup.

A dual-`vir04` guest can use one standard pool from each physical card:

```text
hostpci0: 0000:03:00.0,mdev=vnpu-vir04
hostpci1: 0000:04:00.0,mdev=vnpu-vir04
```

Set `ASCEND_RT_VISIBLE_DEVICES=0,1`, `DATA_PARALLEL_SIZE=2`, and
`TENSOR_PARALLEL_SIZE=1`. The current TP1 W8A8SC checkpoint cannot be changed
directly to TP2.

## 5. API Use

```bash
curl -fsS http://<guest-ip>:8000/health
curl -fsS http://<guest-ip>:8000/v1/models \
    -H "Authorization: Bearer ${VISION_API_KEY}"
```

Image requests use the OpenAI-compatible `image_url` content block with either
an HTTP(S) URL or a `data:image/...;base64,...` URI. Use JSON Schema when a
stable field layout is required.

## 6. Performance Findings

| Workload | One `vir04`, measured |
| --- | ---: |
| 1920x1080, 2064 prompt tokens, 8-9 output tokens | 4.709-5.061 s |
| 1280x720, short result | about 1.65 s |
| 1280x720, full formatted JSON | about 7.68 s |
| 640x360, short result | about 0.69-0.83 s |

Switching from eager execution to `FULL_DECODE_ONLY` graph mode improved decode
speed by roughly 2.3x. Graph mode does not change model weights or image input,
and no accuracy regression was observed in the tested structured fields.

Downscaling can reduce small-text and coordinate accuracy. For desktop
automation, use a low-resolution full-frame localization pass followed by an
original-resolution crop, then map crop coordinates back to the source image.

`vir04` is the largest single general-purpose vNPU template on this baseline.
A second `vir04` running a second replica can nearly double concurrency but
does not reduce single-request latency. TP2 requires matching weights and
inter-device communication validation; a 4B model generally scales by less
than 2x for a single request.

With two full cards and four physical 310P3 chips, measured DP4 throughput was
3.89-3.98x the single-request baseline. See the
[full-passthrough performance results](ascend-310p-vfio-pve.md#5-qwen3-vl-dp4-result)
for the exact workload and limits.

Measured dual-`vir04` DP2 results:

| Workload | Result |
| --- | ---: |
| Single request, 384 completion tokens, 3-run mean | 17.744 s |
| Two identical concurrent requests, wall time | 19.969 s |
| Aggregate throughput gain | 1.777x |
| One complete request, 590 completion tokens | 26.314 s |
| Two overlapping crops with complete output | 18.041 s |
| Complete-result latency reduction | 31.44% |

[`dual-region-analyze.py`](../../examples/qwen3-vl-310p/dual-region-analyze.py)
crops the source into overlapping upper/lower 60% regions, runs both requests
concurrently, and merges JSON without a third model call. Coverage was
complete, but the 4B model still produced a few conflicting OCR characters in
person names; retain per-region output or add a dedicated OCR verifier when
exact text is required.

The same 957x877, 29-line Chinese screenshot was also tested with RapidOCR
3.9.2 and the PP-OCRv6 small models on the guest CPU:

| Path | Measured result |
| --- | ---: |
| OCR, default batch size 6, warm mean | 1.850 s |
| OCR, batch size 16, warm mean | 1.623 s |
| OCR, batch size 32, warm mean | 1.998 s |
| OCR plus 4B text-only agenda formatting | 19.808 s, still truncated at 384 tokens |
| OCR plus deterministic formatting (final client) | 2.494 s including process startup, all 5 items |

For text-heavy screens, use
[`ocr-first-analyze.py`](../../examples/qwen3-vl-310p/ocr-first-analyze.py)
to return text, confidence, and exact boxes. Apply deterministic rules to known
forms and agendas, and reserve Qwen for icons, relationships, and semantic
anomalies. Sending all OCR text back through the 4B model unconditionally
erases the latency advantage during generation.

### 6.1 Why card TOPS do not predict single-stream tokens/s

Huawei specifies 280 INT8 TOPS and 408 GB/s for an entire Atlas 300I Duo: two
310-series processors and 16 AI Cores in total. A `vir04` contains four AI
Cores and a proportional resource slice. The current two `vir04` devices host
two independent TP1 replicas; DP2 load-balances concurrent requests instead of
combining both slices for one token.

Current cumulative vLLM Prometheus measurements are:

| Metric | Engine 0 | Engine 1 |
| --- | ---: | ---: |
| Mean inter-token latency | 42.96 ms | 41.98 ms |
| Corresponding decode rate | 23.28 tokens/s | 23.82 tokens/s |
| Mean TTFT | 1.36 s | 1.30 s |

A controlled text-only request produced 295 tokens in 12.128 seconds, or about
24.3 end-to-end tokens/s. During the request the selected `vir04` sustained
91-93% AI Core utilization while the other DP replica stayed idle. The slice
is therefore busy: autoregressive decode is a low-batch, weight-streaming
workload constrained by per-slice memory bandwidth, launch overhead, and the
serial dependency between tokens, rather than the card's large-matrix INT8
peak.

For the same 871-prompt/384-completion workload, a full physical chip reduced
latency from about 17.89 seconds on `vir04` to about 13.51 seconds. More
physical resources help, but not linearly. The practical order for further
single-request optimization is OCR/rule bypass, streaming, a compatible
speculative decoder, a rebuilt TP2 quantized checkpoint, and only then a
lower-bit checkpoint validated on 310P. Adding DP replicas alone cannot reduce
single-stream latency.

## 7. Operations and Security

```bash
systemctl status vision-qwen3vl.service
journalctl -u vision-qwen3vl.service -b --no-pager
docker logs --tail 200 vision-qwen3vl
npu-smi info
```

- Set `VLLM_EXECUTION_MODE=eager` as a temporary rollback if graph execution
  regresses after an upgrade.
- Preserve the previous image tag, digest, checkpoint hash, and service
  settings before an upgrade.
- The example endpoint is API-key protected but plain HTTP. Do not expose it
  directly to an untrusted network.
- Model, container, and Ascend driver licenses remain governed by their
  respective upstream projects and vendors.
