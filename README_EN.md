# Kunpeng PVE ARM64 Deployment and Driver Porting

[中文](README.md) | [English](README_EN.md)

This repository documents a field-tested workflow for deploying Proxmox VE
ARM64 on Kunpeng 920 servers, porting the openEuler BMA and HiBMC kernel
drivers, integrating the iBMA userspace, and diagnosing ARM64-specific issues.

## Validated Baseline

| Item | Version or status |
| --- | --- |
| CPU | Dual-socket Kunpeng 920, AArch64 |
| PVE | 9.2.9 ARM64 |
| Kernel | `7.0.14-6-pve` |
| QEMU | `pve-qemu-kvm 11.0.3-1` |
| iBMA userspace | 2.20.0, closed-source delivery not distributed here |
| BMA driver | 0.4.0, ported from the openEuler kernel source |
| HiBMC DRM | Optional; `hibmcdrmfb` and BMC screenshots validated |
| Virtualization | ARM KVM, AAVMF, PVE VMs, and LXC validated |

This combination is not an official compatibility commitment from Proxmox or
the server vendor for every Kunpeng platform. Revalidate after any change to
the kernel, BIOS, BMC, or hardware topology.

## Repository Contents

- [PVE ARM64 installation and acceptance](docs/en/pve-arm64-install.md)
- [BMA and HiBMC driver porting](docs/en/kunpeng-driver-porting.md)
- [iBMA deployment and rollback](docs/en/ibma-deployment.md)
- [Known issues and upstream bugs](docs/en/known-issues.md)
- `patches/`: source patches for BMA, HiBMC, and qemu-server
- `scripts/`: driver build, iBMA installation, verification, and rollback tools

## Important Boundaries

1. This repository does not contain closed-source iBMA binaries, vendor
   certificates, firmware, or prebuilt kernel modules.
2. Rebuild BMA modules against the exact target PVE kernel headers. Never reuse
   modules across kernel versions.
3. A fixed CMA physical address is machine-specific. Derive it from the local
   `/proc/iomem`; never copy an address from another server.
4. Keep BMC KVM/SOL or another out-of-band recovery path available during the
   first external-driver load.
5. When Secure Boot is enabled, sign external modules and enroll the signing
   certificate into the platform trust chain.

## License

Original scripts, documentation, and kernel-source patches in this repository
are released under GPL-2.0-only. Third-party software, source code, and
trademarks remain subject to their respective licenses and rights.
