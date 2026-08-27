#!/usr/bin/env bash
set -euo pipefail

KDIR=${KDIR:-/usr/src/linux-headers-$(uname -r)}
BMA_SRC=${BMA_SRC:-}
HIBMC_SRC=${HIBMC_SRC:-}
VRAM_HELPER_SRC=${VRAM_HELPER_SRC:-}
OUT=${OUT:-$PWD/modules-rebuilt}
JOBS=${JOBS:-$(nproc)}

if [[ -z $BMA_SRC || ! -d $BMA_SRC ]]; then
    echo "请通过 BMA_SRC 指定已应用兼容补丁的 BMA 源码目录。" >&2
    exit 1
fi
if [[ ! -d $KDIR ]]; then
    echo "找不到内核 headers：$KDIR" >&2
    exit 1
fi

install -d -m 0755 "$OUT"

make -C "$KDIR" M="$BMA_SRC" clean
make -C "$KDIR" M="$BMA_SRC" CONFIG_BMA=m -j"$JOBS" modules
find "$BMA_SRC" -type f -name '*.ko' -exec cp -a {} "$OUT/" \;

if [[ -n $HIBMC_SRC || -n $VRAM_HELPER_SRC ]]; then
    if [[ ! -d $HIBMC_SRC || ! -d $VRAM_HELPER_SRC ]]; then
        echo "构建 HiBMC 时必须同时提供 HIBMC_SRC 和 VRAM_HELPER_SRC。" >&2
        exit 1
    fi

    make -C "$KDIR" M="$VRAM_HELPER_SRC" clean
    make -C "$KDIR" M="$VRAM_HELPER_SRC" -j"$JOBS" modules
    make -C "$KDIR" M="$HIBMC_SRC" clean
    make -C "$KDIR" M="$HIBMC_SRC" \
        CONFIG_DRM_HISI_HIBMC=m \
        KBUILD_EXTRA_SYMBOLS="$VRAM_HELPER_SRC/Module.symvers" \
        -j"$JOBS" modules
    find "$VRAM_HELPER_SRC" "$HIBMC_SRC" -type f -name '*.ko' \
        -exec cp -a {} "$OUT/" \;
fi

(
    cd "$OUT"
    sha256sum ./*.ko > SHA256SUMS
    sha256sum -c SHA256SUMS
    for module_file in ./*.ko; do
        printf '%s: ' "$module_file"
        modinfo -F vermagic "$module_file"
    done
)

echo "模块已输出到：$OUT"
