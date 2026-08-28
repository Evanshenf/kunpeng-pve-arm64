# Kunpeng PVE ARM64 实践与驱动适配

[中文](README.md) | [English](README_EN.md)

本仓库记录在鲲鹏 920 服务器上部署 Proxmox VE ARM64、适配 openEuler
BMA/HiBMC 内核驱动、部署 iBMA 用户态，以及让 Atlas 300I Duo
（Ascend 310P）通过 VFIO mdev/vNPU 分配给虚拟机的实测流程。

## 重点成果

- **鲲鹏 PVE ARM64**：PVE 9.2、ARM KVM、AAVMF、VM/LXC 的安装与验收。
- **Atlas 300I Duo vNPU**：补齐 PVE Linux 7 的 mdev 能力，完成 Ascend
  310P 驱动接口迁移、VM 模式持久化和 PVE `hostpci.mdev` 闭环验证。
- **鲲鹏管理驱动**：BMA、HiBMC DRM 和 iBMA 的构建、部署与回退。
- **可复现交付**：只发布源码补丁和重建工具，不分发厂商二进制。

## 已验证基线

| 项目 | 版本或状态 |
| --- | --- |
| CPU | 双路 Kunpeng 920，AArch64 |
| PVE | 9.2.9 ARM64 |
| 内核 | `7.0.14-6-pve` |
| QEMU | `pve-qemu-kvm 11.0.3-1` |
| iBMA 用户态 | 2.20.0，闭源交付，不在本仓库分发 |
| BMA 驱动 | 0.4.0，由 openEuler 内核源码适配构建 |
| HiBMC DRM | 可选，`hibmcdrmfb` 与 BMC 截图验证通过 |
| NPU | 2 张 Atlas 300I Duo，4 个 Ascend 310P3 逻辑设备 |
| vNPU | SMMU/IOMMU、mdev、QEMU 11 Guest 启动和 vNPU Guest 驱动识别通过 |
| 虚拟化 | ARM KVM、AAVMF、PVE VM 和 LXC 均通过 |

该组合不是 Proxmox 或服务器厂商对所有鲲鹏机型的正式兼容承诺。内核、
BIOS、BMC 和硬件拓扑变化后必须重新验证。

## 仓库内容

- [PVE ARM64 安装与验收](docs/pve-arm64-install.md)
- [BMA 与 HiBMC 驱动适配](docs/kunpeng-driver-porting.md)
- [iBMA 部署与回滚](docs/ibma-deployment.md)
- [Atlas 300I Duo vNPU：PVE ARM64 适配与部署](docs/ascend-310p-vnpu-pve.md)
- [已知问题与上游 Bug](docs/known-issues.md)
- `patches/`：BMA、HiBMC、qemu-server 和 Ascend 310P 的源码补丁
- `scripts/`：驱动构建、iBMA/Ascend 安装辅助、验证和回滚脚本

## 重要边界

1. 本仓库不包含 iBMA/Ascend 厂商二进制、厂商证书、固件或预编译内核模块。
2. BMA 模块必须针对目标 PVE 内核 headers 重新构建，禁止跨内核复用。
3. 固定 CMA 物理地址属于机器级配置，必须依据本机 `/proc/iomem` 计算，
   不可复制其他服务器的地址。
4. 首次加载外置驱动时必须保留 BMC KVM/SOL 或其他带外恢复路径。
5. 启用 Secure Boot 时，必须完成外置模块签名和可信密钥登记。

## 搜索关键词

`Proxmox VE ARM64`、`Kunpeng 920`、`Atlas 300I Duo`、`Ascend 310P`、
`vNPU`、`VFIO mdev`、`CONFIG_VFIO_MDEV`、`available_instances=0`、
`Linux 7 driver porting`。

## 许可证

仓库中的自有脚本、文档和内核源码补丁按 GPL-2.0-only 发布。第三方软件、
源码和商标分别遵循其原始许可证与权利声明。详见
[第三方声明](THIRD_PARTY_NOTICES.md)。
