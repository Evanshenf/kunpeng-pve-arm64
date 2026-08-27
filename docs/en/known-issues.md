# Known Issues and Upstream Bugs

[中文](../known-issues.md) | [English](known-issues.md)

## 1. qemu-server Sends an x86 Property on ARM64

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

## 2. Kunpeng HPRE RSA Verification Stall

Symptom: loading a signed kernel module can block in `rsassa_pkcs1_verify` when
both `hpre-rsa` and `rsa-generic` are registered.

A temporary workaround on an affected kernel is to disable `hisi_hpre`, keep
the other accelerator drivers enabled, and regenerate the initramfs. Apply this
workaround only when the live call stack and module-verification behavior match
the issue.

- [Proxmox Bug 7980](https://bugzilla.proxmox.com/show_bug.cgi?id=7980)

## 3. Phantom CMA Pageblocks Created by KHO

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

## 4. ACPI IORT Zero-width UBSAN

On some Kunpeng firmware, an IORT Named Component reports a `Memory Size Limit`
of zero. The Linux global DMA-limit scan can then evaluate `DMA_BIT_MASK(0)` and
trigger a 64-bit shift UBSAN warning.

If PCI, SMMU, and DMA remain functional, this is usually a boot-time robustness
warning. It should still be reported to both the firmware vendor and Linux IORT
maintainers; suppressing the log is not a substitute for a fix.

## 5. Generic Packages Attempt to Load an x86 Module on ARM64

A generic `qemu-server` module list may attempt to load the x86-only `msr`
module and emit one not-found message on ARM64. This does not affect ARM KVM,
but the package should split module lists by architecture.

## 6. Local Hotfix Maintenance Rules

- Check whether an upstream package already contains the fix before modifying
  a newly upgraded file.
- Track local package changes with `dpkg -V`.
- Keep the original file, patch, checksum, and rollback procedure together.
- Re-run KVM CPU capability discovery and guest startup tests after every
  upgrade.
