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
