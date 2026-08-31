#!/usr/bin/env python3
"""Extract text locally with OCR and optionally ask Qwen to structure it."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


PROMPTS = {
    "generic": (
        "以下内容由OCR按屏幕从上到下提取。只能以OCR原文为事实来源，不得臆测；"
        "保留姓名、型号、数值和状态原文。输出紧凑JSON，字段为summary、key_text、"
        "abnormalities、recommended_actions、uncertain_text。无异常时abnormalities为空数组，"
        "不输出JSON之外的内容。\n\nOCR文本：\n"
    ),
    "agenda": (
        "以下内容由OCR按页面从上到下提取。将其整理为会议议程，但不得改写姓名、型号、"
        "数值或结论。输出紧凑JSON，字段为items、uncertain_text；items中每项仅含title、"
        "details、speaker、duration、conclusion，省略空字段，不输出JSON之外的内容。\n\n"
        "OCR文本：\n"
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run local OCR first, with optional text-only Qwen analysis."
    )
    parser.add_argument("image", type=Path)
    parser.add_argument(
        "--mode", choices=("ocr", "rules", "hybrid"), default="ocr"
    )
    parser.add_argument(
        "--profile", choices=tuple(PROMPTS), default="generic"
    )
    parser.add_argument(
        "--url", default="http://127.0.0.1:8000/v1/chat/completions"
    )
    parser.add_argument("--api-key", default=os.environ.get("VISION_API_KEY"))
    parser.add_argument("--model", default="qwen3-vl-4b")
    parser.add_argument("--max-tokens", type=int, default=384)
    parser.add_argument("--min-score", type=float, default=0.5)
    parser.add_argument(
        "--ocr-batch-size",
        type=int,
        default=16,
        help="Text recognition/classification batch size (tested default: 16).",
    )
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()
    if not args.image.is_file():
        parser.error(f"image does not exist: {args.image}")
    if args.mode == "hybrid" and not args.api_key:
        parser.error("hybrid mode requires --api-key or VISION_API_KEY")
    if args.mode == "rules" and args.profile != "agenda":
        parser.error("rules mode currently requires --profile agenda")
    if not 0 <= args.min_score <= 1:
        parser.error("--min-score must be in the range [0, 1]")
    if args.ocr_batch_size < 1:
        parser.error("--ocr-batch-size must be positive")
    return args


def load_ocr(batch_size: int) -> tuple[Any, float]:
    try:
        from rapidocr import RapidOCR
    except ImportError as error:
        raise SystemExit(
            "RapidOCR is required. See README.md for the tested installation steps."
        ) from error

    started = time.monotonic()
    engine = RapidOCR(
        params={
            "Global.log_level": "error",
            "Cls.cls_batch_num": batch_size,
            "Rec.rec_batch_num": batch_size,
        }
    )
    return engine, time.monotonic() - started


def normalize_box(box: Any) -> list[list[int]]:
    return [[round(float(x)), round(float(y))] for x, y in box]


def run_ocr(engine: Any, image: Path, min_score: float) -> tuple[list[dict[str, Any]], float]:
    started = time.monotonic()
    output = engine(str(image))
    elapsed = time.monotonic() - started
    lines = [
        {
            "text": text,
            "score": round(float(score), 5),
            "box": normalize_box(box),
        }
        for text, score, box in zip(output.txts, output.scores, output.boxes)
        if float(score) >= min_score
    ]
    return lines, elapsed


def value_after_label(text: str) -> str:
    return re.split(r"[：:]", text, maxsplit=1)[1].strip()


def parse_agenda(lines: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_details = False
    uncertain = [line["text"] for line in lines if line["score"] < 0.9]

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

    return {"items": items, "uncertain_text": uncertain}


def decode_json_content(content: str) -> Any:
    stripped = content.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        stripped = stripped[start : end + 1]
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return {"raw_content": content, "parse_error": True}


def analyze_text(lines: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    numbered_text = "\n".join(
        f"{index:03d}: {line['text']}" for index, line in enumerate(lines, 1)
    )
    payload = {
        "model": args.model,
        "temperature": 0,
        "max_tokens": args.max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {
                "role": "user",
                "content": PROMPTS[args.profile] + numbered_text,
            }
        ],
    }
    request = urllib.request.Request(
        args.url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {args.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Qwen request failed: HTTP {error.code}: {detail}") from error

    elapsed = time.monotonic() - started
    choice = body.get("choices", [{}])[0]
    content = choice.get("message", {}).get("content", "")
    return {
        "elapsed_seconds": round(elapsed, 3),
        "finish_reason": choice.get("finish_reason"),
        "usage": body.get("usage", {}),
        "result": decode_json_content(content),
    }


def main() -> None:
    args = parse_args()
    total_started = time.monotonic()
    engine, init_elapsed = load_ocr(args.ocr_batch_size)
    lines, ocr_elapsed = run_ocr(engine, args.image, args.min_score)
    strategies = {
        "ocr": "ocr-only",
        "rules": "ocr-with-deterministic-rules",
        "hybrid": "ocr-first-text-analysis",
    }
    output: dict[str, Any] = {
        "strategy": strategies[args.mode],
        "timing": {
            "ocr_init_seconds": round(init_elapsed, 3),
            "ocr_inference_seconds": round(ocr_elapsed, 3),
        },
        "ocr": {
            "batch_size": args.ocr_batch_size,
            "line_count": len(lines),
            "lines": lines,
        },
    }
    if args.mode == "rules":
        output["structured"] = parse_agenda(lines)
    elif args.mode == "hybrid":
        output["analysis"] = analyze_text(lines, args)
    output["timing"]["wall_time_seconds"] = round(
        time.monotonic() - total_started, 3
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
