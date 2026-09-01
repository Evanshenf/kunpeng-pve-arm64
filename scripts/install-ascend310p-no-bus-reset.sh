#!/usr/bin/env bash
set -euo pipefail

package_name="ascend310p-no-bus-reset"
package_version="1.1.0"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source_dir="$(cd -- "$script_dir/../kernel/ascend310p-no-bus-reset" && pwd)"
dkms_dir="/usr/src/${package_name}-${package_version}"

if [[ $EUID -ne 0 ]]; then
    echo "This installer must run as root" >&2
    exit 1
fi

if [[ ! -d "/lib/modules/$(uname -r)/build" ]]; then
    printf 'Kernel headers are missing for %s\n' "$(uname -r)" >&2
    exit 1
fi

for command_name in dkms fuser modprobe; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf 'Required command is missing: %s\n' "$command_name" >&2
        exit 1
    fi
done

if lsmod | awk '{ print $1 }' | grep -qx ascend310p_no_bus_reset; then
    for pci_device in /sys/bus/pci/devices/*; do
        [[ -r "$pci_device/vendor" && -r "$pci_device/device" ]] || continue
        [[ "$(<"$pci_device/vendor")" == "0x19e5" ]] || continue
        [[ "$(<"$pci_device/device")" == "0xd500" ]] || continue
        [[ -L "$pci_device/iommu_group" ]] || continue
        group="$(basename "$(readlink -f "$pci_device/iommu_group")")"
        if [[ -c "/dev/vfio/$group" ]] && fuser -s "/dev/vfio/$group"; then
            printf 'Ascend VFIO group %s is in use; stop its VM before updating DKMS\n' \
                "$group" >&2
            exit 1
        fi
    done
    modprobe -r ascend310p_no_bus_reset
fi

if dkms status -m "$package_name" -v "$package_version" | grep -q .; then
    dkms remove -m "$package_name" -v "$package_version" --all
fi

install -d -m 0755 "$dkms_dir"
install -m 0644 "$source_dir/Makefile" "$dkms_dir/Makefile"
install -m 0644 "$source_dir/dkms.conf" "$dkms_dir/dkms.conf"
install -m 0644 "$source_dir/ascend310p_no_bus_reset.c" \
    "$dkms_dir/ascend310p_no_bus_reset.c"

dkms add -m "$package_name" -v "$package_version"
dkms build -m "$package_name" -v "$package_version"
dkms install -m "$package_name" -v "$package_version"

if [[ -n "${ASCEND_VFIO_BDFS:-}" ]]; then
    if [[ ! "$ASCEND_VFIO_BDFS" =~ ^[0-9a-fA-F:.]+(,[0-9a-fA-F:.]+)*$ ]]; then
        printf 'Invalid ASCEND_VFIO_BDFS: %s\n' "$ASCEND_VFIO_BDFS" >&2
        exit 1
    fi
    printf 'options ascend310p_no_bus_reset target_bdfs=%s\n' \
        "$ASCEND_VFIO_BDFS" \
        > /etc/modprobe.d/ascend310p-no-bus-reset.conf
fi

printf '%s\n' ascend310p_no_bus_reset \
    > /etc/modules-load.d/ascend310p-no-bus-reset.conf
modprobe ascend310p_no_bus_reset

echo "Installed ascend310p_no_bus_reset for $(uname -r)"
