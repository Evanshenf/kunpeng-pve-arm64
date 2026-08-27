# 已知问题与上游 Bug

## 1. qemu-server 在 ARM64 发送 x86 属性

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

## 2. 鲲鹏 HPRE RSA 验签阻塞

现象：加载已签名内核模块时，任务可能卡在 `rsassa_pkcs1_verify`；同时系统
注册了 `hpre-rsa` 和 `rsa-generic`。

临时规避是在受影响内核上禁用 `hisi_hpre`，保留其他加速驱动，并重新生成
initramfs。是否采用该规避必须以实机调用栈和模块验证结果为依据。

- [Proxmox Bug 7980](https://bugzilla.proxmox.com/show_bug.cgi?id=7980)

## 3. KHO 造成伪 CMA 页块

部分 Proxmox 内核默认启用 Kexec HandOver scratch 区域，可能使
`CmaFree > CmaTotal` 并造成过早 OOM 判断。

- [Proxmox Bug 7813](https://bugzilla.proxmox.com/show_bug.cgi?id=7813)
- 当前内核可使用 `kho=off` 规避。

鲲鹏平台还可能存在真实 CMA 不足。增大 CMA 时应逐级验证；固定地址必须
依据本机 `/proc/iomem` 中连续、无保留孔洞的低地址 System RAM 计算。

验收指标：

```sh
grep -E 'CmaTotal|CmaFree' /proc/meminfo
find /sys/kernel/mm/cma -type f -maxdepth 2 -print -exec cat {} \;
```

要求 `CmaFree <= CmaTotal`，且 `alloc_pages_fail` 为 0 或经过明确评估。

## 4. ACPI IORT 零位宽 UBSAN

部分鲲鹏固件 IORT Named Component 的 `Memory Size Limit` 为 0，Linux
全局 DMA 上限扫描可能调用 `DMA_BIT_MASK(0)`，触发 64 位移位 UBSAN。

如果 PCI、SMMU 和 DMA 功能正常，该问题通常表现为启动期健壮性告警；仍应
分别向固件和 Linux IORT 维护者反馈，不能通过隐藏日志代替修复。

## 5. 通用包在 ARM64 加载 x86 模块

通用 `qemu-server` 配置可能尝试加载 x86 专用 `msr` 模块，ARM64 上会产生
一条找不到模块的日志。它不影响 ARM KVM，但软件包应按架构拆分模块列表。

## 6. 本地热修复维护原则

- 软件包升级后先检查上游是否已修复，不要机械覆盖新版源码。
- 使用 `dpkg -V` 记录本地修改。
- 保留原文件、补丁、哈希和回滚步骤。
- 每次升级后重新运行 KVM CPU 能力查询和来宾启动测试。
