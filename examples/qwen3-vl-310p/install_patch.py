# SPDX-License-Identifier: Apache-2.0
"""Install the 310P multimodal workaround into a vLLM Ascend image."""

from pathlib import Path


INIT_FILE = Path(
    "/vllm-workspace/vllm-ascend/"
    "vllm_ascend/patch/platform/__init__.py"
)
IMPORT_LINE = (
    "    import vllm_ascend.patch.platform.patch_mm_merge_310p  # noqa\n"
)
ANCHOR = (
    "    import vllm_ascend.patch.platform.patch_mamba_config_310  # noqa\n"
)


def main() -> None:
    text = INIT_FILE.read_text(encoding="utf-8")
    if IMPORT_LINE in text:
        return
    if ANCHOR not in text:
        raise RuntimeError(f"Patch anchor not found in {INIT_FILE}")
    INIT_FILE.write_text(
        text.replace(ANCHOR, ANCHOR + IMPORT_LINE, 1),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
