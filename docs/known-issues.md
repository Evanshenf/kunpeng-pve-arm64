# 已知问题与上游 Bug

[中文](known-issues.md) | [English](en/known-issues.md)

## 1. ARM64 内核缺少通用 mdev 模块

实测 PVE 9.2 ARM64 的 `7.0.14-6-pve` 内核已启用 VFIO、SMMUv3 和 IOMMU，
但没有 `CONFIG_VFIO_MDEV`，官方内核包也不提供 `mdev.ko`。同代 amd64 PVE
内核则配置为 `CONFIG_VFIO_MDEV=m`。

PVE 用户态已经具备通用 mdev 能力：`qemu-server` 可以发现类型、读取
`available_instances` 并管理创建/删除生命周期。加载与目标内核匹配的 mdev
兼容模块后，Atlas 300I Duo 的 vNPU 类型可由 PVE API 正常枚举。因此上游需求
聚焦于 ARM64 内核配置，不要求 PVE 引入厂商专用代码。

- [Proxmox Bug 7988](https://bugzilla.proxmox.com/show_bug.cgi?id=7988)
- [实机验证与临时兼容方案](ascend-310p-vnpu-pve.md)
- [Linux 7 VFIO region 增量补丁](../patches/ascend310p-linux7-vfio-region-info.patch)

另一个独立兼容点是 Linux 7 将 region 查询迁移到
`vfio_device_ops.get_region_info_caps`。本仓库已适配该回调，并在 QEMU 11 上
完成 openEuler Guest 启动和 `npu-smi Health: OK` 验证。

如果上游内核后续提供 `mdev.ko`，应移除仓库方案中的外置 mdev 兼容模块，避免
同名模块冲突，并重新执行 vNPU 创建、删除和 PVE 生命周期测试。

## 2. Ascend remote GUP 缺少 mmap 锁

早期 Linux 7 适配在 `kvmdt_gfn_to_mfn()` 中直接调用
`pin_user_pages_remote()`，但未持有 `kvm->mm` 的 mmap 读锁。启动
带 mdev 的 Guest 时，内核会在 `find_vma`、`__get_user_pages` 和
`__gup_longterm_locked` 输出 rwsem WARNING。

修复按 Linux remote-GUP 契约获取 `mmap_read_lock()`，传入 `locked`
指针并条件解锁。完整补丁已纳入 `.5` 构建，也提供
[GUP 锁增量补丁](../patches/ascend310p-linux7-gup-lock.patch)。

实机重启、mdev DMA pool 初始化和 1080p 推理回归后，上述告警为 0。

## 3. qemu-server 在 ARM64 发送 x86 属性

现象：

```text
query-cpu-model-expansion failed
Parameter 'model.props.hv-passthrough' is unexpected
```

原因：`qemu-server` 对 ARM64 KVM 查询也发送了 x86 Hyper-V 专用属性
`hv-passthrough`。

修复：只在 `x86_64` 下设置该属性。

- [Proxmox Bug 7981](https://bugzilla.proxmox.com/show_bug.cgi?id=7981)
- [补丁](../patches/qemu-server-arm64-hv-passthrough.patch)

## 4. 鲲鹏 HPRE RSA 验签阻塞

现象：加载已签名内核模块时，任务可能卡在 `rsassa_pkcs1_verify`；同时系统
注册了 `hpre-rsa` 和 `rsa-generic`。

临时规避是在受影响内核上禁用 `hisi_hpre`，保留其他加速驱动，并重新生成
initramfs。是否采用该规避必须以实机调用栈和模块验证结果为依据。

- [Proxmox Bug 7980](https://bugzilla.proxmox.com/show_bug.cgi?id=7980)

## 5. KHO 造成伪 CMA 页块

部分 Proxmox 内核默认启用 Kexec HandOver scratch 区域，可能使
`CmaFree > CmaTotal` 并造成过早 OOM 判断。

- [Proxmox Bug 7813](https://bugzilla.proxmox.com/show_bug.cgi?id=7813)
- 当前内核可使用 `kho=off` 规避。

鲲鹏平台还可能存在真实 CMA 不足。增大 CMA 时应逐级验证；固定地址必须
依据本机 `/proc/iomem` 中连续、无保留孔洞的低地址 System RAM 计算。

验收指标：

```sh
grep -E 'CmaTotal|CmaFree' /proc/meminfo
find /sys/kernel/mm/cma -maxdepth 2 -type f -print -exec cat {} \;
```

要求 `CmaFree <= CmaTotal`，且 `alloc_pages_fail` 为 0 或经过明确评估。

## 6. ACPI IORT 零位宽 UBSAN

部分鲲鹏固件 IORT Named Component 的 `Memory Size Limit` 为 0，Linux
全局 DMA 上限扫描可能调用 `DMA_BIT_MASK(0)`，触发 64 位移位 UBSAN。

如果 PCI、SMMU 和 DMA 功能正常，该问题通常表现为启动期健壮性告警；仍应
分别向固件和 Linux IORT 维护者反馈，不能通过隐藏日志代替修复。

## 7. 通用包在 ARM64 加载 x86 模块

通用 `qemu-server` 配置可能尝试加载 x86 专用 `msr` 模块，ARM64 上会产生
一条找不到模块的日志。它不影响 ARM KVM，但软件包应按架构拆分模块列表。

## 8. Ascend 310P 整卡 reset 后重新枚举

对 `19e5:d500` 执行通用 PCI bus reset 会触发链路 Down/Up 和设备重新枚举，
使 QEMU 已打开的 VFIO fd 失效。PVE 启动前 reset 与 QEMU reset 都需要规避。

已验证修复包括：initramfs 提前绑定 `vfio-pci`、PVE `driver=keep`、设置
`PCI_DEV_FLAGS_NO_BUS_RESET` 的 DKMS guard、function reset guard，以及 QEMU
BAR2/reset quirk。

为避免 Guest 继承上一轮设备状态，PVE `pre-start` hook 会在 QEMU 打开设备前
执行受控 reset，并等待完整重新枚举；关机和 VFIO fd 释放阶段仍禁止 reset。

- [完整分析与部署](ascend-310p-vfio-pve.md)
- [QEMU 补丁](../patches/pve-qemu-11.0.3-ascend310p-vfio.patch)

## 9. Ascend 整卡与 vNPU 混用时 UDA 等待不存在的设备

一张 Duo 卡在 initramfs 中绑定 VFIO 后，宿主仅管理另一张卡的两颗芯片。
Ascend UDA 原逻辑使用 NUMA 节点数 4 作为期望芯片数，导致所有 `npu-smi`
请求阻塞并最终报告 `dev_num=2; uda_detected_dev_num=4`。

混合模式还要求物理卡在厂商驱动加载前完成 BDF 早绑定，并在 pre-start reset
期间关闭 PCI 自动探测，避免厂商驱动重新抢占。当前验证方案使用默认关闭的
UDA 计数参数、BDF 范围 reset guard 和专用 mixed-mode 服务。

- [混合模式完整部署](ascend-310p-mixed-mode-pve.md)
- [UDA 计数增量补丁](../patches/ascend310p-mixed-mode-uda-count.patch)

## 10. 本地热修复维护原则

- 软件包升级后先检查上游是否已修复，不要机械覆盖新版源码。
- 使用 `dpkg -V` 记录本地修改。
- 保留原文件、补丁、哈希和回滚步骤。
- 每次升级后重新运行 KVM CPU 能力查询和来宾启动测试。
