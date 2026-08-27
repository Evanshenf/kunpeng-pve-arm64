# PVE ARM64 Installation and Acceptance

[中文](../pve-arm64-install.md) | [English](pve-arm64-install.md)

## 1. Scope

This guide targets Kunpeng servers with UEFI, ACPI, SMMUv3, and ARM KVM.
Before writing disks, boot the installer in a non-destructive mode and verify
that its kernel detects the system disk, management NIC, and serial or display
controller.

## 2. Installation Image

The validated image was:

```text
proxmox-ve_9.2-1-arm64.iso
SHA256: b1619dcd1f5b1a6d67d77b59e7e2fa2033174551d1e1b9dc22b2171ec093abbd
```

Official URL used during validation:

<https://enterprise.proxmox.com/iso/proxmox-ve_9.2-1-arm64.iso>

When a newer release is available, use its current official checksum rather
than the historical value above.

```sh
sha256sum proxmox-ve_9.2-1-arm64.iso
```

## 3. Pre-installation Checks

1. Back up the original OS, VMs, network configuration, and application data
   to another server.
2. Verify that at least one out-of-band path works: BMC KVM, virtual media, or
   SOL.
3. Record the PCI IDs of the system-disk controller and management NIC.
4. Confirm that the installer kernel provides the required drivers:
   - HNS3: `hns3/hclge`;
   - MegaRAID: `megaraid_sas`;
   - HiSilicon SAS: `hisi_sas_v3_hw`;
   - KVM/SMMU: `CONFIG_KVM` and `CONFIG_ARM_SMMU_V3`.
5. Prefer the debug, TUI, or serial installer entry for the first boot. Do not
   overwrite the original OS immediately.

## 4. Post-installation Baseline

```sh
pveversion -v
uname -a
lscpu
ls -l /dev/kvm
systemctl --failed
pvesm status
ip -br link
ip route
```

Acceptance criteria:

- `/dev/kvm` exists;
- the PVE API and WebUI are reachable;
- the system disk, physical NIC, and bridge network work correctly;
- no storage, IOMMU, RAS, or filesystem errors are present;
- ARM64 UEFI firmware is available.

## 5. ARM Virtual Machines

Same-architecture ARM VMs use KVM by default. The absence of an explicit
`kvm: 1` line in the VM configuration does not mean that TCG is in use.
Recommended settings are:

```text
arch: aarch64
cpu: host
machine: virt
bios: ovmf
```

Verify the running VM with:

```sh
qm showcmd VMID --pretty | grep -Ei 'kvm|cpu|machine'
pid=$(cat /run/qemu-server/VMID.pid)
ls -l /proc/$pid/fd | grep /dev/kvm
```

Software emulation is used only when KVM is explicitly disabled, a foreign
architecture is emulated, or host KVM is unavailable. LXC itself does not use
KVM. Running QEMU/KVM inside an LXC requires a separately controlled
passthrough of `/dev/kvm`.

## 6. Reboot Acceptance Before Production

Perform at least one complete host reboot and verify that:

- all native PVE services recover;
- VMs and containers return in the configured startup order;
- storage and bridge networking remain healthy;
- external modules and local hotfixes remain effective;
- CI agents or application probes reconnect.
