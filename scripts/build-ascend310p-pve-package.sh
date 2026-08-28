#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
PATCH_FILE=${PATCH_FILE:-$REPO_ROOT/patches/ascend310p-driver-26.1.1-pve-7.0-vnpu.patch}
PACKAGE_SUFFIX=${PACKAGE_SUFFIX:-pve7.0.14.5}

usage() {
    cat <<'EOF'
用法：
  sudo ./scripts/build-ascend310p-pve-package.sh <官方驱动.deb> [输出.deb]

输入包必须是华为官方 ascend310p-driver 26.1.1 arm64 软件包。本脚本不会下载、
上传或分发厂商二进制，只在本机解包、应用兼容补丁并生成新的 Debian 软件包。
EOF
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
    usage >&2
    exit 2
fi

for command in dpkg-deb patch sed sha256sum mktemp; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "缺少命令：$command" >&2
        exit 1
    fi
done

INPUT_PACKAGE=$(realpath "$1")
if [[ ! -f $INPUT_PACKAGE ]]; then
    echo "找不到输入包：$INPUT_PACKAGE" >&2
    exit 1
fi
if [[ ! -f $PATCH_FILE ]]; then
    echo "找不到补丁：$PATCH_FILE" >&2
    exit 1
fi

package_name=$(dpkg-deb -f "$INPUT_PACKAGE" Package)
package_version=$(dpkg-deb -f "$INPUT_PACKAGE" Version)
package_arch=$(dpkg-deb -f "$INPUT_PACKAGE" Architecture)

if [[ $package_name != ascend310p-driver ]]; then
    echo "不支持的软件包：$package_name" >&2
    exit 1
fi
if [[ $package_version != 26.1.1 ]]; then
    echo "不支持的驱动版本：$package_version（仅验证 26.1.1）" >&2
    exit 1
fi
if [[ $package_arch != arm64 ]]; then
    echo "不支持的架构：$package_arch（仅支持 arm64）" >&2
    exit 1
fi

OUTPUT_PACKAGE=${2:-$PWD/${package_name}_${package_version}+${PACKAGE_SUFFIX}_${package_arch}.deb}
OUTPUT_PACKAGE=$(realpath -m "$OUTPUT_PACKAGE")
if [[ $OUTPUT_PACKAGE == "$INPUT_PACKAGE" ]]; then
    echo "输出路径不能与官方输入包相同。" >&2
    exit 1
fi
if [[ -e $OUTPUT_PACKAGE ]]; then
    echo "输出文件已存在，请更换路径：$OUTPUT_PACKAGE" >&2
    exit 1
fi
mkdir -p "$(dirname "$OUTPUT_PACKAGE")"

work_dir=$(mktemp -d -t ascend310p-pve-build.XXXXXX)
trap 'rm -rf "$work_dir"' EXIT
package_root=$work_dir/package
mkdir -p "$package_root/DEBIAN"

echo "[1/4] 解包官方驱动"
dpkg-deb -x "$INPUT_PACKAGE" "$package_root"
dpkg-deb -e "$INPUT_PACKAGE" "$package_root/DEBIAN"

driver_root=$package_root/usr/local/Ascend/driver
if [[ ! -d $driver_root ]]; then
    echo "输入包中不存在预期目录：usr/local/Ascend/driver" >&2
    exit 1
fi

echo "[2/4] 应用 PVE/Linux 7 vNPU 兼容补丁"
patch --batch --forward -p1 -d "$driver_root" < "$PATCH_FILE"

echo "[3/4] 更新 Debian 软件包版本"
new_version=${package_version}+${PACKAGE_SUFFIX}
sed -i -E "s/^Version:.*/Version: ${new_version}/" "$package_root/DEBIAN/control"

echo "[4/4] 生成软件包"
dpkg-deb --build --root-owner-group "$package_root" "$OUTPUT_PACKAGE"

echo
echo "已生成：$OUTPUT_PACKAGE"
dpkg-deb -f "$OUTPUT_PACKAGE" Package Version Architecture
sha256sum "$OUTPUT_PACKAGE"
