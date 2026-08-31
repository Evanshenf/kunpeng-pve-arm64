#!/usr/bin/env python3
"""Run two complementary image-analysis requests against a DP2 vLLM API."""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except ImportError:  # pragma: no cover - handled by argument validation
    Image = None


GENERIC_REGION_PROMPTS = {
    "upper": (
        "这是原图上部裁剪图，与下部裁剪有少量重叠。"
        "逐行完整提取中文、数字、型号、状态和列表项，不改写、不重复。"
        "必须检查到裁剪图最底部。跳过没有填写内容的空标签。"
        "只输出紧凑JSON，字段为region、image_type、scene、lines、uncertain_text；"
        "region固定为upper，lines必须包含裁剪图中的全部非空文字行。"
        "不要输出JSON之外的内容。"
    ),
    "lower": (
        "这是原图下部裁剪图，与上部裁剪有少量重叠。"
        "逐行完整提取中文、数字、型号、状态和列表项，不改写、不重复。"
        "必须检查到裁剪图最底部。跳过没有填写内容的空标签。"
        "只输出紧凑JSON，字段为region、image_type、scene、lines、uncertain_text；"
        "region固定为lower，lines必须包含裁剪图中的全部非空文字行。"
        "不要输出JSON之外的内容。"
    ),
}

AGENDA_REGION_PROMPTS = {
    "upper": (
        "这是会议议程上部裁剪图，与下部有少量重叠。按阅读顺序提取每个议题。"
        "只输出紧凑JSON，字段为region、items、uncertain_text；region固定为upper。"
        "items中每项字段为title、subitems、speaker、duration、conclusion。"
        "标题与唯一内容重复时只保留title；省略空字段，不改写、不重复，不输出解释。"
    ),
    "lower": (
        "这是会议议程下部裁剪图，与上部有少量重叠。按阅读顺序提取每个议题。"
        "只输出紧凑JSON，字段为region、items、uncertain_text；region固定为lower。"
        "items中每项字段为title、subitems、speaker、duration、conclusion。"
        "标题与唯一内容重复时只保留title；省略空字段，不改写、不重复，不输出解释。"
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze upper and lower overlapping regions concurrently."
    )
    parser.add_argument("image", type=Path)
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000/v1/chat/completions",
    )
    parser.add_argument("--api-key", default=os.environ.get("VISION_API_KEY"))
    parser.add_argument("--model", default="qwen3-vl-4b")
    parser.add_argument(
        "--profile",
        choices=("generic", "agenda"),
        default="generic",
        help="Output profile used by both region prompts.",
    )
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--overlap",
        type=float,
        default=0.2,
        help="Vertical overlap ratio between the two crops (default: 0.2).",
    )
    args = parser.parse_args()
    if not args.api_key:
        parser.error("--api-key or VISION_API_KEY is required")
    if not args.image.is_file():
        parser.error(f"image does not exist: {args.image}")
    if Image is None:
        parser.error("Pillow is required: install python3-pillow or pip install Pillow")
    if not 0 <= args.overlap < 1:
        parser.error("--overlap must be in the range [0, 1)")
    return args


def encode_png(image: Any) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def image_region_data_urls(path: Path, overlap: float) -> dict[str, str]:
    assert Image is not None
    with Image.open(path) as source:
        image = source.convert("RGB")
        width, height = image.size
        if height < 2:
            raise ValueError("image height must be at least 2 pixels")
        upper_end = max(1, round(height * (1 + overlap) / 2))
        lower_start = min(height - 1, round(height * (1 - overlap) / 2))
        return {
            "upper": encode_png(image.crop((0, 0, width, upper_end))),
            "lower": encode_png(image.crop((0, lower_start, width, height))),
        }


def decode_json_content(content: str) -> dict[str, Any]:
    stripped = content.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        stripped = stripped[start : end + 1]
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        array_match = re.search(
            r'"\s*(lines|key_text)\s*"\s*:\s*\[(.*)', stripped, flags=re.DOTALL
        )
        recovered: dict[str, Any] = {"raw_content": content, "parse_error": True}
        if array_match:
            field = array_match.group(1)
            array_text = array_match.group(2).split("]", 1)[0]
            string_tokens = re.findall(r'"(?:\\.|[^"\\])*"', array_text)
            recovered[field] = [json.loads(token) for token in string_tokens]
        return recovered
    return normalize_json(parsed) if isinstance(parsed, dict) else {"result": parsed}


def normalize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key).strip(): normalize_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_json(item) for item in value]
    return value


def analyze_region(
    region: str,
    prompt: str,
    data_url: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    payload = {
        "model": args.model,
        "temperature": 0,
        "max_tokens": args.max_tokens,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
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
        raise RuntimeError(f"{region} request failed: HTTP {error.code}: {detail}") from error

    elapsed = time.monotonic() - started
    choice = body.get("choices", [{}])[0]
    content = choice.get("message", {}).get("content", "")
    return {
        "region": region,
        "elapsed_seconds": round(elapsed, 3),
        "finish_reason": choice.get("finish_reason"),
        "usage": body.get("usage", {}),
        "result": decode_json_content(content),
    }


def list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def unique_values(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(value)
    return result


def merge_text_lines(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen_long: set[str] = set()
    for value in values:
        text = " ".join(str(value).split())
        if not text:
            continue
        if len(text) >= 12:
            if text in seen_long:
                continue
            seen_long.add(text)
        result.append(text)
    return result


def clean_item(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, list):
        result = []
        for item in value:
            cleaned = clean_item(item)
            if cleaned not in (None, "", [], {}):
                result.append(cleaned)
        return result
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            cleaned = clean_item(item)
            if cleaned not in (None, "", [], {}):
                result[str(key).strip()] = cleaned
        return result
    return value


def merge_agenda_items(parsed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    for region in parsed:
        for raw_item in list_value(region.get("items")):
            if not isinstance(raw_item, dict):
                continue
            item = clean_item(raw_item)
            title = str(item.get("title", "")).strip()
            marker = re.sub(r"\s+", "", title)
            if not marker or marker not in positions:
                if marker:
                    positions[marker] = len(result)
                result.append(item)
                continue

            existing = result[positions[marker]]
            for key, value in item.items():
                if key == "subitems":
                    existing[key] = unique_values(
                        list_value(existing.get(key)) + list_value(value)
                    )
                elif not existing.get(key) and value:
                    existing[key] = value
    return result


def merge_regions(regions: list[dict[str, Any]], wall_time: float) -> dict[str, Any]:
    parsed = [region["result"] for region in regions]
    return {
        "strategy": "dual-overlapping-regions",
        "wall_time_seconds": round(wall_time, 3),
        "image_type": unique_values(
            [item.get("image_type") for item in parsed if item.get("image_type")]
        ),
        "scene": unique_values(
            [item.get("scene") for item in parsed if item.get("scene")]
        ),
        "key_text": merge_text_lines(
            [
                value
                for item in parsed
                for value in list_value(item.get("lines", item.get("key_text")))
            ]
        ),
        "abnormalities": unique_values(
            [
                value
                for item in parsed
                for value in list_value(item.get("abnormalities"))
            ]
        ),
        "recommended_action": unique_values(
            [
                value
                for item in parsed
                for value in list_value(item.get("recommended_action"))
                if value
            ]
        ),
        "uncertain_text": unique_values(
            [
                value
                for item in parsed
                for value in list_value(item.get("uncertain_text"))
            ]
        ),
        "items": merge_agenda_items(parsed),
        "details_by_region": {
            region["region"]: region["result"].get("details") for region in regions
        },
        "requests": regions,
    }


def main() -> None:
    args = parse_args()
    data_urls = image_region_data_urls(args.image, args.overlap)
    prompts = (
        AGENDA_REGION_PROMPTS if args.profile == "agenda" else GENERIC_REGION_PROMPTS
    )
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(analyze_region, region, prompt, data_urls[region], args)
            for region, prompt in prompts.items()
        ]
        regions = [future.result() for future in futures]
    output = merge_regions(regions, time.monotonic() - started)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
