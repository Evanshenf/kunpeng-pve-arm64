# Atlas 300I Duo Full VFIO Passthrough on PVE ARM64

[中文](../ascend-310p-vfio-pve.md)

## 1. Scope and result

This document describes the fixes required to pass two Atlas 300I Duo PCIe
functions through to one VM on Kunpeng 920 and Proxmox VE ARM64. The guest sees
four physical Ascend 310P3 chips, all reporting `Health: OK`.

The validated stack is PVE 9.2.9, Linux `7.0.14-6-pve`, patched
`pve-qemu-kvm 11.0.3-1+ascend2`, openEuler 24.03 LTS SP3, and the Ascend 25.2.0
normal physical-device driver. This is an engineering result for one stack,
not a general compatibility commitment from Huawei or Proxmox.

For one full-passthrough card plus one host-managed vNPU card, see the
[mixed-mode guide](ascend-310p-mixed-mode-pve.md). Full VFIO and mdev remain
mutually exclusive on the same PCI function.

## 2. Why generic passthrough fails

The 310P virtual-machine flow needs two device-specific protections:

1. QEMU must forward reads but block writes to the xloader update register at
   BAR2 offsets `0x00100430` and `0x08100430` on a dual-chip card.
2. A conventional PCI bus reset makes the endpoint disappear and re-enumerate.
   During validation, `19e5:d500` temporarily appeared as `1000:02b2`, sysfs and
   `/dev/vfio/<group>` were recreated, and QEMU lost its open VFIO device.

The reset can be initiated both by QEMU and by PVE's pre-start PCI preparation,
and Linux `vfio_pci_core_disable()` can invoke `vfio_pci_dev_set_try_reset()`
after the last VFIO fd closes. Fixing only one layer is insufficient.

## 3. Required fixes

### 3.1 Patched QEMU

Apply
[`pve-qemu-11.0.3-ascend310p-vfio.patch`](../../patches/pve-qemu-11.0.3-ascend310p-vfio.patch)
to the matching PVE QEMU source. The patch overlays the protected BAR2
registers and skips QEMU reset handling for `19e5:d500`.

Build a Debian package from the exact source version installed on the host.
Do not copy a QEMU binary built for another PVE release. After installation,
verify both strings are present:

```bash
strings /usr/bin/qemu-system-aarch64 | \
    grep -E 'blocked write to Ascend 310P|skipping unsafe Ascend 310P'
```

### 3.2 Early VFIO binding

Create `/etc/modprobe.d/ascend310p-vfio.conf`:

```text
options vfio-pci ids=19e5:d500 disable_idle_d3=1
blacklist drv_vascend
```

Add the following to `/etc/initramfs-tools/modules`, rebuild initramfs, and
reboot:

```text
vfio
vfio_iommu_type1
vfio_pci ids=19e5:d500 disable_idle_d3=1
```

Both PFs must be bound to `vfio-pci` before PVE starts guests. Disable the
`ascend-vnpu-vm-mode.service` when using full-device passthrough.

### 3.3 PVE `driver=keep` and kernel reset guards

PVE natively supports `driver=keep`, which avoids both rebinding and its
pre-start reset. Use it only when early VFIO binding is already working:

```bash
qm set <VMID> --hostpci0 <BDF0>,driver=keep
qm set <VMID> --hostpci1 <BDF1>,driver=keep
```

Install the DKMS guard. It sets the native Linux
`PCI_DEV_FLAGS_NO_BUS_RESET` flag for current and newly enumerated
`19e5:d500` functions:

```bash
apt install -y dkms psmisc proxmox-headers-$(uname -r)
sudo ./scripts/install-ascend310p-no-bus-reset.sh
```

Stop every VM using a 310P VFIO group before installing or updating the guard.
The installer refuses to proceed while any matching group remains open.

Install the systemd guard before enabling VM autostart. It loads the DKMS
module and clears function reset methods:

```bash
install -m 0755 scripts/ascend310p-vfio-reset-guard \
    /usr/local/sbin/ascend310p-vfio-reset-guard
install -m 0644 systemd/ascend310p-vfio-reset-guard.service \
    /etc/systemd/system/ascend310p-vfio-reset-guard.service
systemctl daemon-reload
systemctl enable --now ascend310p-vfio-reset-guard.service
```

Both guards discover `19e5:d500` dynamically and are ready before
`pve-guests.service`. Clearing `reset_method` alone does not block VFIO's
bus-reset fallback, while `NO_BUS_RESET` alone is not a substitute for
function-reset protection.

Never resetting the device can leave guest-visible state from the previous
boot. Install the controlled PVE pre-start flow as well:

```bash
install -m 0755 scripts/ascend310p-vfio-prepare \
    /usr/local/sbin/ascend310p-vfio-prepare
install -d -m 0755 /var/lib/vz/snippets
install -m 0755 scripts/pve-ascend310p-hook \
    /var/lib/vz/snippets/pve-ascend310p-hook
qm set <VMID> --hookscript local:snippets/pve-ascend310p-hook
```

Before QEMU opens VFIO, the hook temporarily unloads the DKMS guard, resets
one card at a time, observes the old sysfs object leave, waits for the new
`19e5:d500`, `vfio-pci`, IOMMU group, and `/dev/vfio/<group>` state to remain
stable, then restores both reset guards. No reset is performed at post-stop.
The prepare script refuses to unload the host-wide guard while any 310P VFIO
group is open. Multi-VM deployments must therefore coordinate downtime rather
than starting independent 310P passthrough guests concurrently.

## 4. Guest configuration

Install the normal physical-device driver, not `vnpu_guest`:

```bash
./Ascend-hdk-310p-npu-driver_<version>_linux-aarch64.run \
    --full --install-for-all --quiet
```

`/etc/ascend_install.info` should report `Driver_Install_Mode=normal`, and
`npu-smi info` should list four healthy 310P3 chips.

## 5. Qwen3-VL DP4 result

The validated W8A8SC checkpoint is a TP1 vLLM `sharded_state` with a
single-device `FRACTAL_NZ` layout. It cannot be safely converted to TP4 with the
generic safetensors loader. Run four TP1 replicas behind one internal vLLM load
balancer instead:

```text
ASCEND_RT_VISIBLE_DEVICES=0,1,2,3
TENSOR_PARALLEL_SIZE=1
DATA_PARALLEL_SIZE=4
API_SERVER_COUNT=1
LOAD_FORMAT=sharded_state
```

A 32 GiB guest was OOM-killed while loading four workers. A 48 GiB guest was
stable with about 11 GiB still available after model initialization.

Using the same 871-prompt-token and 384-completion-token image request:

| Mode | Mean single latency | Four concurrent wall time | Aggregate rate |
| --- | ---: | ---: | ---: |
| `vir04` vNPU TP1 | about 17.89 s | not measured | about 0.0559 req/s |
| Full physical chip TP1 | about 13.51 s | not measured | about 0.0740 req/s |
| Four physical chips, DP4/TP1 | 13.948 s | 14.030-14.362 s | 0.2785-0.2851 req/s |

DP4 improved throughput by 3.885-3.977x over its single-request baseline, while
single-request latency remained nearly unchanged as expected.

## 6. Acceptance and maintenance

Run at least two `qm shutdown` and `qm start` cycles. One controlled Link
Down/Up cycle per card is expected during `pre-start`; no new reset or Link
Down event is allowed during shutdown. Each hook run must report both cards as
ready before QEMU starts. `skipping unsafe Ascend 310P bus reset` is expected;
`No such host device` and missing `/dev/vfio/<group>` nodes are not.

Rebase and rebuild the patch after every PVE QEMU or kernel update. Keep the
official Debian package for rollback. Do not enable full passthrough and mdev
for the same PF at the same time. This repository does not distribute vendor
drivers, models, firmware, certificates, or API keys.
