# Atlas 300I Duo vNPU on PVE ARM64

[中文](../ascend-310p-vnpu-pve.md)

## 1. Goal and Result

This guide documents how Atlas 300I Duo cards were enabled for VFIO mediated
device (mdev) assignment on a Kunpeng 920 ARM64 server running Proxmox VE 9.2.
The validated host contained two cards and four logical Ascend 310P3 devices.

The end-to-end validation covered SMMU/IOMMU discovery, driver build and
installation, 33 DKMS modules, `mdev.ko` and `drv_vascend`, vNPU type discovery,
mdev create/remove, IOMMU group creation, VM-mode persistence after reboot, and
PVE service health. QEMU 11 guest boot and the openEuler vNPU guest driver were
also validated.

This is a validated engineering baseline, not a compatibility commitment from
Huawei or Proxmox for every platform, firmware, or kernel.

## 2. Validated Baseline

| Item | Tested configuration |
| --- | --- |
| Architecture | AArch64, dual-socket Kunpeng 920 |
| PVE | 9.2.9 ARM64 |
| Kernel | `7.0.14-6-pve` |
| QEMU | `pve-qemu-kvm 11.0.3-1` |
| Accelerators | Two Atlas 300I Duo cards |
| PCI ID | `19e5:d500` |
| Driver input | Official `ascend310p-driver 26.1.1 arm64` Debian package |
| Firmware | Driver compatibility check returned `OK`; firmware was not flashed |
| Virtualization | SMMUv3, IOMMU, VFIO, mdev, and PVE `hostpci.mdev` |
| Guest | openEuler 24.03 LTS SP3 with the 25.2.0 `vnpu_guest` driver |

## 3. Architecture

```mermaid
flowchart LR
    BIOS[BIOS: Enable SMMU] --> IOMMU[PVE kernel: SMMUv3 / IOMMU]
    IOMMU --> PF[Atlas 300I Duo PF]
    PF --> Driver[Ascend 310P host driver]
    Driver --> MDEV[mdev core + drv_vascend]
    MDEV --> PVE[PVE hostpci.mdev]
    PVE --> VM[VM + Ascend vNPU guest driver]
```

The Linux mdev core provides the generic mediated-device lifecycle. The vendor
driver registers parent devices and supported types, and PVE assigns a selected
type to QEMU/KVM. See the upstream
[VFIO mdev documentation](https://docs.kernel.org/driver-api/vfio-mediated-device.html)
and the PVE [mdev configuration example](https://pve.proxmox.com/wiki/NVIDIA_vGPU_on_Proxmox_VE_7.x).

## 4. Why the Unmodified Stack Failed

1. BIOS SMMU was disabled, so no IOMMU groups existed.
2. The tested PVE kernel did not provide `CONFIG_VFIO_MDEV` or `mdev.ko`.
3. Ascend 26.1.1 still used older Kbuild, KVM, IOMMU, timer, PFN, and page-table
   APIs that no longer compiled on Linux 7.0.
4. Linux 7 VFIO core no longer forwards `VFIO_DEVICE_GET_REGION_INFO` to the
   vendor `.ioctl`; it requires `.get_region_info_caps`. Without it, QEMU fails
   on region 0 with `EINVAL`.
5. The vendor installer did not recognize `proxmox-headers-*` and removed the
   Debian GCC built-in include path.
6. Ascend 310P boots in container mode. Before VM mode is selected, supported
   types may exist while `available_instances` remains zero.
7. Linux 7 requires callers of `pin_user_pages_remote()` to hold the target
   `mm` mmap read lock. Without it, mdev DMA-pool initialization repeatedly
   warns in `find_vma`, `__get_user_pages`, and `__gup_longterm_locked`.

## 5. Patch Scope

[`ascend310p-driver-26.1.1-pve-7.0-vnpu.patch`](../../patches/ascend310p-driver-26.1.1-pve-7.0-vnpu.patch)
implements the following changes:

- Migrates obsolete `EXTRA_CFLAGS` use to Kbuild `ccflags-y`.
- Adds a centralized `linux7_compat.h` for timer/hrtimer, CXL namespace,
  `follow_pfnmap`, ARM64 page-table, and related API changes.
- Uses `iommu_paging_domain_alloc()` for IOMMU domain allocation.
- Migrates IRQ bypass registration to the Linux 7 eventfd + IRQ interface.
- Replaces unexported KVM GFN helpers with memslot lookup and
  `pin_user_pages_remote()`.
- Takes `mmap_read_lock(kvm->mm)`, passes the `locked` state to remote GUP, and
  conditionally releases the lock according to the GUP contract.
- Implements Linux 7 `.get_region_info_caps` using the existing vendor BAR and
  sparse-map data so QEMU 11 can query every VFIO region.
- Builds the unmodified mdev core from Linux stable `v7.0.14` as part of the
  same DKMS project when the target kernel does not provide it.
- Recognizes PVE kernel headers and preserves Debian GCC built-in includes.

An incremental patch is also provided for reviewing or updating an existing
v0.2.0 deployment:
[`ascend310p-linux7-vfio-region-info.patch`](../../patches/ascend310p-linux7-vfio-region-info.patch).

The remote-GUP locking fix is also available as a minimal incremental patch:
[`ascend310p-linux7-gup-lock.patch`](../../patches/ascend310p-linux7-gup-lock.patch).

## 6. Prerequisites

1. Keep BMC KVM/SOL or another out-of-band recovery path available.
2. Enable SMMU/IOMMU in firmware and verify IOMMU groups after reboot.
3. Obtain the official Ascend 310P 26.1.1 arm64 Debian package through an
   authorized channel.
4. Install the build dependencies:

```bash
apt update
apt install -y build-essential dkms patch net-tools pciutils uuid-runtime \
    proxmox-headers-$(uname -r)
```

5. Verify that all large PCI BARs are assigned. Do not copy CMA addresses or
   kernel command lines from a different machine without checking its map.

## 7. Build and Install

The repository does not distribute a repackaged vendor binary. Build one
locally from the official package:

```bash
git clone https://github.com/Evanshenf/kunpeng-pve-arm64.git
cd kunpeng-pve-arm64
sudo ./scripts/build-ascend310p-pve-package.sh \
    /path/to/ascend310p-driver_26.1.1_arm64.deb
sudo dpkg -i ./ascend310p-driver_26.1.1+pve7.0.14.5_arm64.deb
```

The script validates package name, version, and architecture. It exits on a
patch mismatch and never modifies the input package.

## 8. Persist VM Mode

The service waits for each target PCI function to expose `chip_id` before
running `npu-smi`, avoiding an early-boot race:

```bash
install -m 0755 scripts/ascend-vnpu-vm-mode \
    /usr/local/sbin/ascend-vnpu-vm-mode
install -m 0644 systemd/ascend-vnpu-vm-mode.service \
    /etc/systemd/system/ascend-vnpu-vm-mode.service
systemctl daemon-reload
systemctl enable --now ascend-vnpu-vm-mode.service
```

The default minimum is one `19e5:d500` function. On multi-card hosts, set
`Environment=MIN_DEVICE_COUNT=<physical-function-count>` in the unit so the
service does not run before all cards are initialized.
The unit also declares `Before=pve-guests.service`, preventing on-boot guests
from creating mdevs before VM mode is ready.

## 9. Validation

```bash
uname -r
lspci -nn | grep -i '19e5:d500'
find /sys/kernel/iommu_groups -type l | sort
npu-smi info
npu-smi info -m
lsmod | grep -E 'mdev|drv_vascend|vfio'
systemctl --no-pager status ascend-vnpu-vm-mode.service

for type in /sys/bus/pci/devices/*/mdev_supported_types/*; do
    [ -e "$type/available_instances" ] || continue
    printf '%s: ' "$type"
    cat "$type/available_instances"
done
```

The tested physical functions reported `vir01=7`, `vir02=3`, and `vir04=1`.
Always treat the local sysfs values as authoritative.

Create and remove one test instance:

```bash
BDF=<target-PCI-address>
TYPE=vnpu-vir01
UUID=$(uuidgen)
echo "$UUID" > "/sys/bus/pci/devices/$BDF/mdev_supported_types/$TYPE/create"
readlink -f "/sys/bus/mdev/devices/$UUID/iommu_group"
echo 1 > "/sys/bus/mdev/devices/$UUID/remove"
test ! -e "/sys/bus/mdev/devices/$UUID"
```

Delegate lifecycle management to PVE:

```bash
qm set <VMID> -hostpci0 <BDF>,mdev=vnpu-vir01
```

Do not assign the same physical function as a full PCI passthrough device at
the same time. The guest still requires a compatible Ascend vNPU guest driver
and runtime. Do not add `pcie=1` on an ARM `virt` machine; PVE associates that
option with the x86 q35 machine type.

After starting a guest with an mdev, verify that the remote-GUP warning is gone:

```bash
journalctl -k -b --no-pager | \
    grep -E 'find_vma|__get_user_pages|__gup_longterm_locked|kvmdt_gfn_to_mfn'
```

The validated `.5` build reported zero matching warnings after
`dma pool init success` and completed a 1080p multimodal inference request.

## 10. Troubleshooting

| Symptom | First checks |
| --- | --- |
| No `/sys/kernel/iommu_groups` | Firmware SMMU/IOMMU and SMMUv3 boot messages |
| PCI BAR allocation failure | Firmware MMIO windows, 64-bit MMIO, `pci=realloc`, and platform resource layout |
| Installer cannot find headers | Matching `proxmox-headers-*` and `/lib/modules/.../build` |
| Old KVM/IOMMU API build errors | Exact driver/kernel versions and complete patch application |
| QEMU reports `failed to get region 0 info` | Apply the v0.2.1 Linux 7 `.get_region_info_caps` fix |
| ARM startup reports q35 is not enabled | Remove `pcie=1`; ARM `virt` does not use x86 q35 |
| rwsem/GUP warning during mdev initialization | Ensure the package includes `ascend310p-linux7-gup-lock.patch` |
| No `mdev.ko` | Target `CONFIG_VFIO_MDEV`; this patch only supplies mdev for the validated missing-module baseline |
| `available_instances=0` | `npu-smi` VM mode, `chip_id` readiness, and service logs |
| Device absent in the guest | PVE `hostpci.mdev`, guest driver, IOMMU group, and PF ownership conflicts |

## 11. Upgrade and Production Boundaries

- This patch was validated only with `7.0.14-6-pve` and Ascend 26.1.1. Rebuild
  and repeat lifecycle tests after every kernel or driver upgrade.
- Remove the bundled compatibility mdev module if a later PVE kernel enables
  `CONFIG_VFIO_MDEV`, otherwise module names will conflict.
- Guest boot, virtual PCI BARs, the 25.2.0 `vnpu_guest` driver, and
  `npu-smi Health: OK` were validated, together with Qwen3-VL-4B inference and
  host reboot recovery. Before production use, still validate sustained model
  load, abnormal VM exit, resource reclamation, and tenant isolation.
- The official VM-mode command is `npu-smi set -t vnpu-mode -d 1`; see the
  [Ascend VM configuration guide](https://www.hiascend.com/doc_center/source/zh/Atlas%20200I%20A2/24.1.RC1/re/virtualmachineconfiguration/%E8%99%9A%E6%8B%9F%E6%9C%BA%E9%85%8D%E7%BD%AE%E6%8C%87%E5%8D%97-24.1.RC1.pdf).
