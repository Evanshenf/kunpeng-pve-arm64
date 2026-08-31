# Known Issues and Upstream Bugs

[中文](../known-issues.md) | [English](known-issues.md)

## 1. ARM64 Kernel Does Not Ship the Generic mdev Module

On the tested PVE 9.2 ARM64 baseline, kernel `7.0.14-6-pve` enables VFIO,
SMMUv3, and IOMMU but not `CONFIG_VFIO_MDEV`, and the official kernel package
does not provide `mdev.ko`. Contemporary amd64 PVE kernels set
`CONFIG_VFIO_MDEV=m`.

The PVE userspace is already generic: `qemu-server` discovers mdev types, reads
`available_instances`, and manages create/remove lifecycle. After loading a
kernel-matched mdev compatibility module, the PVE API successfully enumerated
the Atlas 300I Duo vNPU types. The upstream request therefore targets the ARM64
kernel configuration and does not ask PVE to carry vendor-specific code.

- [Proxmox Bug 7988](https://bugzilla.proxmox.com/show_bug.cgi?id=7988)
- [Validated setup and temporary compatibility path](ascend-310p-vnpu-pve.md)
- [Incremental Linux 7 VFIO region patch](../../patches/ascend310p-linux7-vfio-region-info.patch)

Linux 7 also moved region queries to
`vfio_device_ops.get_region_info_caps`. The repository now implements this
callback and has validated an openEuler guest boot and `npu-smi Health: OK` on
QEMU 11.

Once an upstream PVE ARM64 kernel provides `mdev.ko`, remove the external mdev
compatibility module to avoid a module-name conflict, then repeat vNPU
create/remove and PVE lifecycle tests.

## 2. Ascend Remote GUP Misses the mmap Lock

The initial Linux 7 port called `pin_user_pages_remote()` from
`kvmdt_gfn_to_mfn()` without holding the `kvm->mm` mmap read lock. Starting a
guest with an mdev then emitted rwsem warnings in `find_vma`,
`__get_user_pages`, and `__gup_longterm_locked`.

The fix follows the Linux remote-GUP contract: take `mmap_read_lock()`, pass the
`locked` state, and conditionally unlock it. It is included in the `.5` build
and is also available as an
[incremental GUP-lock patch](../../patches/ascend310p-linux7-gup-lock.patch).

After a host reboot, mdev DMA-pool initialization, and a 1080p inference test,
the validated host reported zero matching warnings.

## 3. qemu-server Sends an x86 Property on ARM64

Symptom:

```text
query-cpu-model-expansion failed
Parameter 'model.props.hv-passthrough' is unexpected
```

Cause: `qemu-server` sends the x86 Hyper-V-only `hv-passthrough` property while
querying an ARM64 KVM CPU model.

Fix: set this property only on `x86_64`.

- [Proxmox Bug 7981](https://bugzilla.proxmox.com/show_bug.cgi?id=7981)
- [Patch](../../patches/qemu-server-arm64-hv-passthrough.patch)

## 4. Kunpeng HPRE RSA Verification Stall

Symptom: loading a signed kernel module can block in `rsassa_pkcs1_verify` when
both `hpre-rsa` and `rsa-generic` are registered.

A temporary workaround on an affected kernel is to disable `hisi_hpre`, keep
the other accelerator drivers enabled, and regenerate the initramfs. Apply this
workaround only when the live call stack and module-verification behavior match
the issue.

- [Proxmox Bug 7980](https://bugzilla.proxmox.com/show_bug.cgi?id=7980)

## 5. Phantom CMA Pageblocks Created by KHO

Some Proxmox kernels enable a Kexec HandOver scratch area by default. It can
produce `CmaFree > CmaTotal` and cause premature OOM decisions.

- [Proxmox Bug 7813](https://bugzilla.proxmox.com/show_bug.cgi?id=7813)
- `kho=off` is a runtime workaround for the affected kernel.

Kunpeng systems may also have a real CMA shortage. Increase CMA incrementally
and validate every step. Derive any fixed address from a contiguous, hole-free,
low-address System RAM range in the local `/proc/iomem`.

Acceptance metrics:

```sh
grep -E 'CmaTotal|CmaFree' /proc/meminfo
find /sys/kernel/mm/cma -maxdepth 2 -type f -print -exec cat {} \;
```

Require `CmaFree <= CmaTotal`, and either zero `alloc_pages_fail` or a documented
assessment of every remaining failure.

## 6. ACPI IORT Zero-width UBSAN

On some Kunpeng firmware, an IORT Named Component reports a `Memory Size Limit`
of zero. The Linux global DMA-limit scan can then evaluate `DMA_BIT_MASK(0)` and
trigger a 64-bit shift UBSAN warning.

If PCI, SMMU, and DMA remain functional, this is usually a boot-time robustness
warning. It should still be reported to both the firmware vendor and Linux IORT
maintainers; suppressing the log is not a substitute for a fix.

## 7. Generic Packages Attempt to Load an x86 Module on ARM64

A generic `qemu-server` module list may attempt to load the x86-only `msr`
module and emit one not-found message on ARM64. This does not affect ARM KVM,
but the package should split module lists by architecture.

## 8. Ascend 310P Re-enumerates After a Full-device Reset

A generic PCI bus reset of `19e5:d500` causes a link Down/Up cycle and endpoint
re-enumeration, invalidating QEMU's open VFIO descriptor. Both the PVE
pre-start reset and the QEMU reset path must be avoided.

The validated fix combines early `vfio-pci` binding, PVE `driver=keep`, a DKMS
guard that sets `PCI_DEV_FLAGS_NO_BUS_RESET`, a function-reset guard, and a
QEMU BAR2/reset quirk.

To avoid carrying device state across guest boots, a PVE `pre-start` hook
performs a controlled reset and waits for full re-enumeration before QEMU opens
the device. Reset remains prohibited during shutdown and VFIO fd release.

- [Full analysis and deployment](ascend-310p-vfio-pve.md)
- [QEMU patch](../../patches/pve-qemu-11.0.3-ascend310p-vfio.patch)

## 9. Local Hotfix Maintenance Rules

- Check whether an upstream package already contains the fix before modifying
  a newly upgraded file.
- Track local package changes with `dpkg -V`.
- Keep the original file, patch, checksum, and rollback procedure together.
- Re-run KVM CPU capability discovery and guest startup tests after every
  upgrade.
