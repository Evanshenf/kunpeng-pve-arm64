# Atlas 300I Duo vNPU：PVE ARM64 适配与部署

[English](en/ascend-310p-vnpu-pve.md)

## 1. 目标与实测结论

本文记录在鲲鹏 920 ARM64 服务器和 Proxmox VE 9.2 上，让两张 Atlas 300I
Duo（4 个 Ascend 310P3 逻辑设备）进入 VM 模式，并通过 VFIO mediated
device（mdev）分配给 PVE 虚拟机的完整方法。

已完成的实机闭环包括：SMMU/IOMMU 识别、26.1.1 驱动编译安装、33 个 DKMS
模块生成、`mdev.ko`/`drv_vascend` 加载、vNPU 类型枚举、mdev 创建与删除、
IOMMU group 建立、重启后 VM 模式恢复，以及 PVE 服务健康检查。

这是一份特定组合的工程验证结果，不是华为或 Proxmox 对所有机型、内核和
固件版本的兼容承诺。

## 2. 验证基线

| 项目 | 实测配置 |
| --- | --- |
| 架构 | AArch64，双路 Kunpeng 920 |
| PVE | 9.2.9 ARM64 |
| 内核 | `7.0.14-6-pve` |
| 加速卡 | 2 张 Atlas 300I Duo |
| PCI ID | `19e5:d500` |
| 驱动输入 | 官方 `ascend310p-driver 26.1.1 arm64` Debian 包 |
| 固件 | 实测版本与驱动兼容性检查为 `OK`；固件未由本流程升级 |
| 虚拟化接口 | SMMUv3、IOMMU、VFIO、mdev、PVE `hostpci.mdev` |

## 3. 数据路径

```mermaid
flowchart LR
    BIOS[BIOS: Enable SMMU] --> IOMMU[PVE kernel: SMMUv3 / IOMMU]
    IOMMU --> PF[Atlas 300I Duo PF]
    PF --> Driver[Ascend 310P host driver]
    Driver --> MDEV[mdev core + drv_vascend]
    MDEV --> PVE[PVE hostpci.mdev]
    PVE --> VM[VM + Ascend vNPU guest driver]
```

Linux mdev 提供创建、删除和管理 mediated device 的通用框架；厂商驱动负责
注册物理父设备和可用类型，PVE 再把指定类型映射给 QEMU/KVM 虚拟机。Linux
官方框架说明见 [VFIO Mediated devices](https://docs.kernel.org/driver-api/vfio-mediated-device.html)，
PVE 的 mdev 配置形式也可参考其
[vGPU 文档](https://pve.proxmox.com/wiki/NVIDIA_vGPU_on_Proxmox_VE_7.x)。

## 4. 原始环境为什么不能直接使用

1. BIOS `EnableSMMU` 关闭时没有 IOMMU group，VFIO 无法安全隔离 DMA。
2. 实测 PVE 内核没有启用 `CONFIG_VFIO_MDEV`，因此不提供 `mdev.ko`。
3. Ascend 26.1.1 源码使用了旧 Kbuild、KVM、IOMMU、timer、PFN 和页表接口，
   不能直接针对 Linux 7.0 编译。
4. 厂商安装器不能识别 `proxmox-headers-*`，并会丢失 Debian GCC 内建头文件
   路径。
5. 310P 重启后默认回到容器模式，未切换 VM 模式时虽能看到
   `mdev_supported_types`，但 `available_instances` 为 0。

## 5. 补丁内容

[`ascend310p-driver-26.1.1-pve-7.0-vnpu.patch`](../patches/ascend310p-driver-26.1.1-pve-7.0-vnpu.patch)
包含以下修改：

- 将不再生效的 `EXTRA_CFLAGS` 迁移为 Kbuild `ccflags-y`。
- 增加集中式 `linux7_compat.h`，适配 timer/hrtimer、CXL namespace、
  `follow_pfnmap`、ARM64 页表和其他内核接口变化。
- 将 IOMMU domain 创建迁移到 `iommu_paging_domain_alloc()`。
- 将 IRQ bypass 注册迁移到 Linux 7 的 eventfd + irq 接口。
- 使用 KVM memslot 与 `pin_user_pages_remote()` 替代不再导出的
  `gfn_to_pfn()`、`kvm_release_pfn_clean()` 和 `kvm_is_visible_gfn()`。
- 在目标内核缺少 mdev 时，加入 Linux stable `v7.0.14` 的原生 mdev 核心，
  作为同一 DKMS 工程的兼容模块；mdev 实现本身未做功能修改。
- 识别 PVE 的内核 headers，并保留 Debian GCC 的内建 include 路径。

## 6. 前置条件

1. 保留 BMC KVM/SOL 等带外恢复手段，并安排维护窗口。
2. 在 BIOS 中启用 SMMU/IOMMU，重启后确认存在 IOMMU group。
3. 从授权渠道取得官方 `ascend310p-driver 26.1.1 arm64` Debian 包。
4. 安装构建依赖：

```bash
apt update
apt install -y build-essential dkms patch net-tools pciutils uuid-runtime \
    proxmox-headers-$(uname -r)
```

5. 确认所有 Atlas BAR 已分配。若大 BAR 分配失败，应先解决平台 PCIe 资源
   窗口；不要盲目复制其他机器的 CMA 地址或启动参数。

## 7. 构建与安装

仓库不提供重封装的驱动二进制。以下脚本只在本机解包官方包、应用补丁并
重新生成 Debian 包：

```bash
git clone https://github.com/Evanshenf/kunpeng-pve-arm64.git
cd kunpeng-pve-arm64
sudo ./scripts/build-ascend310p-pve-package.sh \
    /path/to/ascend310p-driver_26.1.1_arm64.deb
sudo dpkg -i ./ascend310p-driver_26.1.1+pve7.0.14.3_arm64.deb
```

脚本会检查包名、版本和架构，补丁应用失败时立即退出，不会修改输入包。

## 8. 持久化 VM 模式

卡初始化完成前执行 `npu-smi set` 会失败，因此启动服务不仅等待 PCI 设备，
还会等待每个目标设备出现 `chip_id`：

```bash
install -m 0755 scripts/ascend-vnpu-vm-mode \
    /usr/local/sbin/ascend-vnpu-vm-mode
install -m 0644 systemd/ascend-vnpu-vm-mode.service \
    /etc/systemd/system/ascend-vnpu-vm-mode.service
systemctl daemon-reload
systemctl enable --now ascend-vnpu-vm-mode.service
```

默认至少等待 1 个 `19e5:d500` 设备。多卡环境可在 unit 中设置
`Environment=MIN_DEVICE_COUNT=<物理功能数量>`，避免部分卡尚未初始化时过早
切换模式。

## 9. 验收

### 9.1 基础状态

```bash
uname -r
lspci -nn | grep -i '19e5:d500'
find /sys/kernel/iommu_groups -type l | sort
npu-smi info
npu-smi info -m
lsmod | grep -E 'mdev|drv_vascend|vfio'
systemctl --no-pager status ascend-vnpu-vm-mode.service
```

### 9.2 vNPU 类型和容量

```bash
for type in /sys/bus/pci/devices/*/mdev_supported_types/*; do
    [ -e "$type/available_instances" ] || continue
    printf '%s: ' "$type"
    cat "$type/available_instances"
done
```

实测每个物理功能在 VM 模式下可见 `vir01=7`、`vir02=3`、`vir04=1`。不同卡型、
固件或资源占用下应以本机 sysfs 返回为准。

### 9.3 创建与删除测试

```bash
BDF=<目标PCI地址，例如0000:03:00.0>
TYPE=vnpu-vir01
UUID=$(uuidgen)
echo "$UUID" > "/sys/bus/pci/devices/$BDF/mdev_supported_types/$TYPE/create"
readlink -f "/sys/bus/mdev/devices/$UUID/iommu_group"
echo 1 > "/sys/bus/mdev/devices/$UUID/remove"
test ! -e "/sys/bus/mdev/devices/$UUID"
```

### 9.4 交给 PVE 管理生命周期

```bash
qm set <VMID> -hostpci0 <BDF>,mdev=vnpu-vir01,pcie=1
```

PVE 会随 VM 启停创建和删除 mdev。不要同时把同一物理功能作为整卡直通给
其他 VM。Guest 内仍需安装与宿主驱动匹配的 Ascend vNPU guest 驱动和运行时。

## 10. 常见问题

| 现象 | 优先检查 |
| --- | --- |
| 没有 `/sys/kernel/iommu_groups` | BIOS SMMU/IOMMU 是否启用，内核启动日志是否识别 SMMUv3 |
| PCI BAR 分配失败 | 固件 PCIe 窗口、64 位 MMIO、`pci=realloc` 和平台资源规划 |
| 安装器提示找不到 headers | `proxmox-headers-$(uname -r)` 是否安装，`/lib/modules/.../build` 是否有效 |
| 编译出现旧 KVM/IOMMU API 错误 | 驱动是否为 26.1.1，运行内核是否仍为已验证版本，补丁是否完整应用 |
| 没有 `mdev.ko` | 检查目标内核 `CONFIG_VFIO_MDEV`；本补丁仅为缺少该模块的基线提供兼容实现 |
| `available_instances=0` | `npu-smi` VM 模式、`chip_id` 就绪状态及 systemd 服务日志 |
| VM 内看不到设备 | PVE `hostpci.mdev`、Guest vNPU 驱动、IOMMU group 和 PF 复用冲突 |

## 11. 升级与生产边界

- 补丁只在 `7.0.14-6-pve` + Ascend 26.1.1 上完成实机验证。每次 PVE 内核或
  驱动升级都必须重新编译并执行 mdev 创建、删除、VM 启停和异常回收测试。
- 如果后续 PVE 内核原生启用 `CONFIG_VFIO_MDEV`，应删除兼容 mdev 模块，避免
  与内核原生实现重名。
- 生产前还需在目标 Guest 中验证业务压力、宿主重启、VM 异常退出、资源回收
  和多租户隔离。本次验证没有替代应用层验收。
- 官方 Ascend 文档中的 VM 模式命令为
  `npu-smi set -t vnpu-mode -d 1`，可参考
  [Atlas 虚拟机配置指南](https://www.hiascend.com/doc_center/source/zh/Atlas%20200I%20A2/24.1.RC1/re/virtualmachineconfiguration/%E8%99%9A%E6%8B%9F%E6%9C%BA%E9%85%8D%E7%BD%AE%E6%8C%87%E5%8D%97-24.1.RC1.pdf)。
