#!/usr/bin/env python3
"""OpenAI-compatible OCR and Qwen routing service."""

from __future__ import annotations

import base64
import binascii
import copy
import hmac
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from rapidocr import RapidOCR


HOST = os.environ.get("ROUTER_HOST", "0.0.0.0")
PORT = int(os.environ.get("ROUTER_PORT", "8001"))
UPSTREAM_URL = os.environ.get(
    "QWEN_UPSTREAM_URL", "http://127.0.0.1:8000/v1/chat/completions"
)
UPSTREAM_HEALTH_URL = os.environ.get(
    "QWEN_UPSTREAM_HEALTH_URL", "http://127.0.0.1:8000/health"
)
API_KEY = os.environ.get("ROUTER_API_KEY") or os.environ.get("VLLM_API_KEY")
UPSTREAM_MODEL = os.environ.get("QWEN_UPSTREAM_MODEL", "qwen3-vl-4b")
OCR_BATCH_SIZE = int(os.environ.get("OCR_BATCH_SIZE", "16"))
OCR_MIN_SCORE = float(os.environ.get("OCR_MIN_SCORE", "0.5"))
UPSTREAM_TIMEOUT = float(os.environ.get("QWEN_UPSTREAM_TIMEOUT", "300"))
MAX_REQUEST_BYTES = int(os.environ.get("MAX_REQUEST_BYTES", str(32 * 1024 * 1024)))
MAX_IMAGE_BYTES = int(os.environ.get("MAX_IMAGE_BYTES", str(20 * 1024 * 1024)))
ALLOW_REMOTE_IMAGE_URLS = os.environ.get("ALLOW_REMOTE_IMAGE_URLS", "0") == "1"

OCR_MODELS = {"ocr", "vision-ocr"}
HYBRID_MODELS = {"hybrid", "vision-hybrid"}
AUTO_MODELS = {"auto", "vision-auto"}
DIRECT_MODELS = {UPSTREAM_MODEL, "qwen"}
ALL_MODELS = ("vision-auto", "vision-ocr", "vision-hybrid", UPSTREAM_MODEL)

OCR_INTENT_PATTERNS = (
    "ocr",
    "提取文字",
    "识别文字",
    "全部文字",
    "完整文字",
    "逐行文字",
    "文字坐标",
    "文字和坐标",
    "文本坐标",
    "读出文字",
    "提取表格",
    "读取表格",
    "表格文字",
    "会议议程",
    "整理议程",
)


def require_configuration() -> None:
    if not API_KEY:
        raise SystemExit("ROUTER_API_KEY or VLLM_API_KEY must be configured")
    if OCR_BATCH_SIZE < 1:
        raise SystemExit("OCR_BATCH_SIZE must be positive")
    if not 0 <= OCR_MIN_SCORE <= 1:
        raise SystemExit("OCR_MIN_SCORE must be in the range [0, 1]")


def normalize_box(box: Any) -> list[list[int]]:
    return [[round(float(x)), round(float(y))] for x, y in box]


def value_after_label(text: str) -> str:
    parts = re.split(r"[：:]", text, maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else ""


def parse_agenda(lines: list[dict[str, Any]]) -> dict[str, Any] | None:
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_details = False

    for line in lines:
        text = line["text"].strip()
        if re.match(r"^议题[一二三四五六七八九十0-9]+[：:]", text):
            current = {"title": text}
            items.append(current)
            in_details = False
            continue
        if current is None:
            continue
        if re.match(r"^议题内容[：:]", text):
            in_details = True
            value = value_after_label(text)
            if value:
                current.setdefault("details", []).append(value)
            continue
        if re.match(r"^主讲人[：:]", text):
            current["speaker"] = value_after_label(text)
            in_details = False
            continue
        if re.match(r"^时间[：:]", text):
            current["duration"] = value_after_label(text)
            in_details = False
            continue
        if re.match(r"^评审结论[：:]", text):
            value = value_after_label(text)
            if value:
                current["conclusion"] = value
            in_details = False
            continue
        if in_details or re.match(r"^\d+[、.]", text):
            current.setdefault("details", []).append(text)

    if not items:
        return None
    return {
        "items": items,
        "uncertain_text": [line["text"] for line in lines if line["score"] < 0.9],
    }


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(item.get("text", ""))
        for item in content
        if isinstance(item, dict) and item.get("type") == "text"
    )


def request_text(payload: dict[str, Any]) -> str:
    return "\n".join(
        content_text(message.get("content"))
        for message in payload.get("messages", [])
        if isinstance(message, dict)
    ).lower()


def find_image_url(payload: dict[str, Any]) -> str | None:
    for message in reversed(payload.get("messages", [])):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "image_url":
                continue
            image_url = item.get("image_url")
            if isinstance(image_url, dict):
                image_url = image_url.get("url")
            if isinstance(image_url, str) and image_url:
                return image_url
    return None


def read_limited(response: Any, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(1024 * 1024, limit + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            raise ValueError(f"image exceeds {limit} bytes")


def image_bytes(image_url: str) -> bytes:
    if image_url.startswith("data:"):
        match = re.fullmatch(
            r"data:image/(?:png|jpe?g|webp|bmp);base64,(.+)",
            image_url,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            raise ValueError("unsupported image data URI")
        try:
            raw = base64.b64decode(match.group(1), validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("invalid base64 image") from error
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError(f"image exceeds {MAX_IMAGE_BYTES} bytes")
        return raw

    if not re.match(r"^https?://", image_url, flags=re.IGNORECASE):
        raise ValueError("image URL must be a data URI or HTTP(S) URL")
    if not ALLOW_REMOTE_IMAGE_URLS:
        raise ValueError(
            "remote image URLs are disabled; send a data:image/...;base64 URI"
        )
    request = urllib.request.Request(
        image_url, headers={"User-Agent": "vision-router/1.0"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return read_limited(response, MAX_IMAGE_BYTES)


class OCRService:
    def __init__(self) -> None:
        self.engine = RapidOCR(
            params={
                "Global.log_level": "error",
                "Cls.cls_batch_num": OCR_BATCH_SIZE,
                "Rec.rec_batch_num": OCR_BATCH_SIZE,
            }
        )
        self.lock = threading.Lock()

    def analyze(self, raw: bytes) -> dict[str, Any]:
        started = time.monotonic()
        with self.lock:
            output = self.engine(raw)
        elapsed = time.monotonic() - started
        txts = output.txts if output.txts is not None else ()
        scores = output.scores if output.scores is not None else ()
        boxes = output.boxes if output.boxes is not None else ()
        lines = [
            {
                "text": text,
                "score": round(float(score), 5),
                "box": normalize_box(box),
            }
            for text, score, box in zip(txts, scores, boxes)
            if float(score) >= OCR_MIN_SCORE
        ]
        shape = getattr(output.img, "shape", ())
        result: dict[str, Any] = {
            "engine": "RapidOCR-3.9.2/PP-OCRv6-small",
            "elapsed_seconds": round(elapsed, 3),
            "batch_size": OCR_BATCH_SIZE,
            "image_size": {
                "width": int(shape[1]) if len(shape) >= 2 else None,
                "height": int(shape[0]) if len(shape) >= 2 else None,
            },
            "line_count": len(lines),
            "lines": lines,
        }
        agenda = parse_agenda(lines)
        if agenda:
            result["structured"] = {"type": "agenda", **agenda}
        return result


def append_ocr_context(payload: dict[str, Any], ocr: dict[str, Any]) -> None:
    text = "\n".join(line["text"] for line in ocr["lines"])
    note = (
        "\n\n以下是专用OCR按屏幕顺序提取的文字。姓名、型号、数字和状态应以此"
        "为准；同时结合原图理解图标、颜色、位置关系和异常语义。不要臆造OCR中"
        "不存在的精确文字。\n[OCR开始]\n"
        f"{text}\n[OCR结束]"
    )
    for message in reversed(payload.get("messages", [])):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = content + note
        elif isinstance(content, list):
            content.append({"type": "text", "text": note})
        else:
            message["content"] = note
        return
    payload.setdefault("messages", []).append({"role": "user", "content": note})


def select_route(payload: dict[str, Any]) -> str:
    requested = str(payload.get("router_mode") or payload.get("model") or "").lower()
    if requested in OCR_MODELS:
        return "ocr"
    if requested in HYBRID_MODELS:
        return "hybrid"
    if requested in DIRECT_MODELS:
        return "qwen"
    if requested not in AUTO_MODELS:
        raise ValueError(f"unsupported model or router_mode: {requested}")
    text = request_text(payload)
    return "ocr" if any(pattern in text for pattern in OCR_INTENT_PATTERNS) else "hybrid"


def completion_response(model: str, content: str, route: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-router-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "router": {"route": route},
    }


def completion_chunk(model: str, content: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-router-{uuid.uuid4().hex}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def qwen_health() -> str:
    try:
        with urllib.request.urlopen(UPSTREAM_HEALTH_URL, timeout=2) as response:
            return "ready" if response.status == HTTPStatus.OK else "unavailable"
    except (urllib.error.URLError, TimeoutError):
        return "unavailable"


class VisionRouterHandler(BaseHTTPRequestHandler):
    server_version = "VisionRouter/1.0"

    @property
    def ocr(self) -> OCRService:
        return self.server.ocr  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        print(
            f"{self.log_date_time_string()} {self.client_address[0]} " + fmt % args,
            flush=True,
        )

    def send_json(self, status: int, value: Any) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, status: int, message: str) -> None:
        self.send_json(status, {"error": {"message": message, "type": "router_error"}})

    def authenticated(self) -> bool:
        expected = f"Bearer {API_KEY}"
        actual = self.headers.get("Authorization", "")
        return hmac.compare_digest(actual, expected)

    def require_auth(self) -> bool:
        if self.authenticated():
            return True
        self.send_error_json(HTTPStatus.UNAUTHORIZED, "Unauthorized")
        return False

    def do_GET(self) -> None:
        if self.path == "/health":
            qwen = qwen_health()
            self.send_json(
                HTTPStatus.OK,
                {
                    "status": "ok" if qwen == "ready" else "degraded",
                    "ocr": "ready",
                    "qwen": qwen,
                },
            )
            return
        if self.path == "/v1/models":
            if not self.require_auth():
                return
            now = int(time.time())
            self.send_json(
                HTTPStatus.OK,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": model,
                            "object": "model",
                            "created": now,
                            "owned_by": "vision-router",
                        }
                        for model in ALL_MODELS
                    ],
                },
            )
            return
        self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")

    def read_payload(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("invalid Content-Length") from error
        if length <= 0:
            raise ValueError("empty request body")
        if length > MAX_REQUEST_BYTES:
            raise OverflowError(f"request exceeds {MAX_REQUEST_BYTES} bytes")
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as error:
            raise ValueError("invalid JSON body") from error
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def send_ocr(self, payload: dict[str, Any], ocr: dict[str, Any]) -> None:
        content = json.dumps(ocr, ensure_ascii=False, indent=2)
        model = str(payload.get("model") or "vision-ocr")
        if payload.get("stream"):
            chunk = completion_chunk(model, content)
            data = f"data: {json.dumps(chunk, ensure_ascii=False)}\n\ndata: [DONE]\n\n".encode(
                "utf-8"
            )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Vision-Route", "ocr")
            self.end_headers()
            self.wfile.write(data)
            return
        response = completion_response(model, content, "ocr")
        response["router"]["ocr_elapsed_seconds"] = ocr["elapsed_seconds"]
        response["router"]["ocr_line_count"] = ocr["line_count"]
        self.send_json(HTTPStatus.OK, response)

    def proxy_qwen(
        self, payload: dict[str, Any], route: str, ocr: dict[str, Any] | None
    ) -> None:
        upstream_payload = copy.deepcopy(payload)
        upstream_payload.pop("router_mode", None)
        upstream_payload["model"] = UPSTREAM_MODEL
        if ocr is not None:
            append_ocr_context(upstream_payload, ocr)
        request = urllib.request.Request(
            UPSTREAM_URL,
            data=json.dumps(upstream_payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            response = urllib.request.urlopen(request, timeout=UPSTREAM_TIMEOUT)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            self.send_error_json(error.code, f"upstream error: {detail}")
            return
        except urllib.error.URLError as error:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, f"upstream unavailable: {error}")
            return

        with response:
            if upstream_payload.get("stream"):
                self.send_response(response.status)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Vision-Route", route)
                if ocr is not None:
                    self.send_header("X-OCR-Lines", str(ocr["line_count"]))
                self.end_headers()
                while True:
                    line = response.readline()
                    if not line:
                        break
                    self.wfile.write(line)
                    self.wfile.flush()
                return

            body = json.load(response)
        body["router"] = {"route": route}
        if ocr is not None:
            body["router"].update(
                {
                    "ocr_elapsed_seconds": ocr["elapsed_seconds"],
                    "ocr_line_count": ocr["line_count"],
                }
            )
        self.send_json(HTTPStatus.OK, body)

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")
            return
        if not self.require_auth():
            return
        try:
            payload = self.read_payload()
            route = select_route(payload)
            if route == "qwen":
                self.proxy_qwen(payload, route, None)
                return
            url = find_image_url(payload)
            if not url:
                if route == "hybrid":
                    self.proxy_qwen(payload, "qwen-no-image", None)
                    return
                raise ValueError("no image_url content block found")
            raw = image_bytes(url)
            ocr = self.ocr.analyze(raw)
            if route == "ocr":
                self.send_ocr(payload, ocr)
                return
            self.proxy_qwen(payload, route, ocr)
        except OverflowError as error:
            self.send_error_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, str(error))
        except ValueError as error:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
        except Exception as error:  # pragma: no cover - final service boundary
            self.send_error_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"internal router error: {type(error).__name__}: {error}",
            )


class VisionRouterServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], ocr: OCRService) -> None:
        super().__init__(address, VisionRouterHandler)
        self.ocr = ocr


def main() -> None:
    require_configuration()
    started = time.monotonic()
    ocr = OCRService()
    server = VisionRouterServer((HOST, PORT), ocr)
    print(
        f"vision-router ready on {HOST}:{PORT}; OCR init "
        f"{time.monotonic() - started:.3f}s",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
