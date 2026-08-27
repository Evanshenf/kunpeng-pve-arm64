# PVE ARM64 安装与验收

## 1. 适用范围

本文面向具备 UEFI、ACPI、SMMUv3 和 ARM KVM 的鲲鹏服务器。正式安装前应
在不写盘模式下验证安装内核能识别系统盘、管理网卡和串口/显示控制器。

## 2. 安装介质

本次验证使用：

```text
proxmox-ve_9.2-1-arm64.iso
SHA256: b1619dcd1f5b1a6d67d77b59e7e2fa2033174551d1e1b9dc22b2171ec093abbd
```

验证时的官方地址：

<https://enterprise.proxmox.com/iso/proxmox-ve_9.2-1-arm64.iso>

新版本发布后应以官方当前校验值为准，不要继续使用本文旧哈希。

```sh
sha256sum proxmox-ve_9.2-1-arm64.iso
```

## 3. 安装前检查

1. 备份原系统、虚拟机、网络配置和业务数据，并将备份放到另一台服务器。
2. 确认 BMC KVM、虚拟介质和 SOL 至少有一种可用。
3. 记录系统盘控制器和管理网卡 PCI ID。
4. 确认安装内核具有对应驱动：
   - HNS3：`hns3/hclge`；
   - MegaRAID：`megaraid_sas`；
   - HiSilicon SAS：`hisi_sas_v3_hw`；
   - KVM/SMMU：`CONFIG_KVM`、`CONFIG_ARM_SMMU_V3`。
5. 首次启动优先使用调试/TUI/串口入口，不要立即覆盖原系统。

## 4. 安装后基线

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

检查要求：

- `/dev/kvm` 存在；
- PVE API 和 WebUI 可访问；
- 系统盘、物理网卡和桥接网络正常；
- 没有存储、IOMMU、RAS 或文件系统错误；
- ARM64 UEFI 固件包可用。

## 5. ARM 虚拟机

同架构 ARM 虚拟机默认启用 KVM，配置中未显示 `kvm: 1` 也不表示使用 TCG。
建议使用：

```text
arch: aarch64
cpu: host
machine: virt
bios: ovmf
```

运行后通过以下方式确认：

```sh
qm showcmd VMID --pretty | grep -Ei 'kvm|cpu|machine'
pid=$(cat /run/qemu-server/VMID.pid)
ls -l /proc/$pid/fd | grep /dev/kvm
```

只有显式设置 `kvm: 0`、跨架构模拟或宿主 KVM 不可用时，才会退回软件
模拟。LXC 本身不使用 KVM；如需在 LXC 内运行 QEMU/KVM，必须单独受控透传
`/dev/kvm`。

## 6. 上线前重启验证

至少完成一次完整宿主重启，并确认：

- PVE 原生服务全部恢复；
- VM/LXC 按启动顺序恢复；
- 存储与桥接网络正常；
- 外置模块和本地热修复仍生效；
- CI Agent 或业务探针重新上线。
