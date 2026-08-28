# Kunpeng PVE ARM64 Deployment and Driver Porting

[中文](README.md) | [English](README_EN.md)

This repository documents a field-tested workflow for deploying Proxmox VE
ARM64 on Kunpeng 920 servers, porting the openEuler BMA and HiBMC kernel
drivers, integrating the iBMA userspace, and assigning Atlas 300I Duo
(Ascend 310P) vNPUs to virtual machines through VFIO mdev.

## Highlights

- **Kunpeng PVE ARM64**: installation and validation of PVE 9.2, ARM KVM,
  AAVMF, VMs, and LXC.
- **Atlas 300I Duo vNPU**: Linux 7 mdev support, Ascend 310P driver API
  migration, persistent VM mode, and end-to-end PVE `hostpci.mdev` validation.
- **Local vision inference**: Qwen3-VL-4B W8A8SC and vLLM Ascend in a `vir04`
  guest, with an OpenAI-compatible API, reboot recovery, and 1080p validation.
- **Kunpeng management stack**: build, deployment, and rollback workflows for
  BMA, HiBMC DRM, and iBMA.
- **Reproducible delivery**: source patches and local rebuild tooling only;
  vendor binaries are not redistributed.

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
| NPU | Two Atlas 300I Duo cards, four logical Ascend 310P3 devices |
| vNPU | SMMU/IOMMU, mdev, QEMU 11 guest, vNPU guest driver, and vision inference validated |
| Virtualization | ARM KVM, AAVMF, PVE VMs, and LXC validated |

This combination is not an official compatibility commitment from Proxmox or
the server vendor for every Kunpeng platform. Revalidate after any change to
the kernel, BIOS, BMC, or hardware topology.

## Repository Contents

- [PVE ARM64 installation and acceptance](docs/en/pve-arm64-install.md)
- [BMA and HiBMC driver porting](docs/en/kunpeng-driver-porting.md)
- [iBMA deployment and rollback](docs/en/ibma-deployment.md)
- [Atlas 300I Duo vNPU on PVE ARM64](docs/en/ascend-310p-vnpu-pve.md)
- [Qwen3-VL inference on an Ascend 310P vNPU](docs/en/qwen3-vl-vnpu.md)
- [Known issues and upstream bugs](docs/en/known-issues.md)
- `patches/`: source patches for BMA, HiBMC, qemu-server, and Ascend 310P
- `scripts/`: build, deployment, verification, and rollback tools

## Important Boundaries

1. This repository does not contain iBMA/Ascend vendor binaries, vendor
   certificates, firmware, or prebuilt kernel modules.
2. Rebuild BMA modules against the exact target PVE kernel headers. Never reuse
   modules across kernel versions.
3. A fixed CMA physical address is machine-specific. Derive it from the local
   `/proc/iomem`; never copy an address from another server.
4. Keep BMC KVM/SOL or another out-of-band recovery path available during the
   first external-driver load.
5. When Secure Boot is enabled, sign external modules and enroll the signing
   certificate into the platform trust chain.

## Search Keywords

`Proxmox VE ARM64`, `Kunpeng 920`, `Atlas 300I Duo`, `Ascend 310P`, `vNPU`,
`VFIO mdev`, `CONFIG_VFIO_MDEV`, `available_instances=0`, and
`Linux 7 driver porting`, `Qwen3-VL Ascend 310P`, and `vLLM Ascend`.

## License

Original scripts, documentation, and kernel-source patches in this repository
are released under GPL-2.0-only. Third-party software, source code, and
trademarks remain subject to their respective licenses and rights. See
[Third-party notices](THIRD_PARTY_NOTICES.md).
