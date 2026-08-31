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

For two `vir04` devices, use `ASCEND_RT_VISIBLE_DEVICES=0,1` and
`DATA_PARALLEL_SIZE=2`. `dual-region-analyze.py` sends upper/lower overlapping
image crops concurrently and merges their JSON without a third model call.
Install Pillow on the client first (`python3-pillow` or `pip install Pillow`):

```bash
VISION_API_KEY='<secret>' ./dual-region-analyze.py /path/to/image.png \
    --url http://<guest-ip>:8000/v1/chat/completions
```

For text-heavy screenshots, use OCR as the primary path. The tested headless
installation avoids adding GUI libraries to the inference guest:

```bash
python3 -m venv /opt/rapidocr/venv
/opt/rapidocr/venv/bin/pip install rapidocr==3.9.2 onnxruntime==1.29.0
/opt/rapidocr/venv/bin/pip uninstall -y opencv-python
/opt/rapidocr/venv/bin/pip install opencv-python-headless==5.0.0.93
```

Return OCR text and bounding boxes without using the VLM:

```bash
/opt/rapidocr/venv/bin/python ocr-first-analyze.py /path/to/image.png \
    --mode ocr
```

Fixed-layout pages should be structured with deterministic rules instead of
spending VLM output tokens. The included rules profile handles agenda pages:

```bash
/opt/rapidocr/venv/bin/python ocr-first-analyze.py /path/to/image.png \
    --mode rules --profile agenda
```

The client defaults to a recognition/classification batch size of 16. On the
tested 29-line screenshot this was faster than 6 or 32 without changing the
recognized line set. Override it with `--ocr-batch-size` for other CPUs or much
larger pages.

Or send the OCR text, rather than the image, to Qwen for compact structuring:

```bash
VISION_API_KEY='<secret>' /opt/rapidocr/venv/bin/python \
    ocr-first-analyze.py /path/to/image.png --mode hybrid --profile agenda \
    --url http://<guest-ip>:8000/v1/chat/completions
```

## Unified routing API

`vision-router.py` exposes one OpenAI-compatible endpoint on port `8001` while
leaving the original vLLM endpoint on `8000` unchanged. It reuses
`VLLM_API_KEY` from `/etc/vision-qwen3vl/runtime.env` and preloads the OCR
engine once.

Available model names:

- `vision-ocr`: OCR text, confidence, boxes, and deterministic agenda parsing.
- `vision-hybrid`: OCR first, then Qwen receives both the original image and
  exact OCR text.
- `vision-auto`: OCR-only for explicit text/coordinate/agenda requests;
  otherwise hybrid analysis.
- `qwen3-vl-4b`: direct proxy to the existing vLLM service.

Install after the RapidOCR environment has been prepared:

```bash
install -d -m 0755 /opt/vision-router
install -m 0755 vision-router.py /opt/vision-router/
install -m 0644 vision-router.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now vision-router.service
```

The request format remains OpenAI compatible. Send images as base64 data URIs
for OCR and hybrid modes:

```bash
curl http://<guest-ip>:8001/v1/chat/completions \
    -H "Authorization: Bearer ${VISION_API_KEY}" \
    -H 'Content-Type: application/json' \
    -d @request.json
```

Example `request.json`:

```json
{
  "model": "vision-auto",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
        {"type": "text", "text": "提取全部文字和坐标"}
      ]
    }
  ]
}
```

Remote HTTP image downloads are disabled by default to avoid turning the
router into an unrestricted URL fetcher. Set `ALLOW_REMOTE_IMAGE_URLS=1` only
inside a controlled network when that behavior is required.
