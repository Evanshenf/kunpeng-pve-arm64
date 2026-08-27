# BMA 与 HiBMC 驱动适配

## 1. 源码边界

BMA 和 HiBMC DRM 驱动源码存在于 openEuler 内核源码中；iBMA 的
Manager、Monitor 和 Redfish 用户态属于闭源软件，不在内核源码中。

本次源码基线为 openEuler 24.03 LTS-SP3 的发行 SRPM：

```text
kernel-6.6.0-145.3.26.157.oe2403sp3.src.rpm
```

应从 openEuler 官方仓库取得 SRPM 并验证 RPM 签名及 SHA256，再从其完整
`kernel.tar.gz` 提取 BMA/HiBMC 源码。

## 2. 驱动组成

| 模块 | 用途 |
| --- | --- |
| `host_edma_drv` | iBMA EDMA 核心，匹配 `19e5:1710/1712` |
| `host_cdev_drv` | 字符设备 `/dev/hwibmc*` |
| `host_veth_drv` | OS 与 BMC 的 VETH 管理链路 |
| `cdev_veth_drv` | CDEV 网络模式，可选 |
| `host_kbox_drv` | KBOX，可选 |
| `hibmc_drm` | BMC VGA DRM 驱动，匹配 `19e5:1711` |

HiBMC DRM 不是 iBMA 必需模块。PVE 已通过 UEFI GOP/simpledrm 提供控制台
时，不应仅为了 iBMA 强行加载 `hibmc_drm`。

## 3. Linux 7.0 兼容修改

BMA 补丁主要包含：

- timer API 迁移到 `timer_container_of()` 和 `timer_delete_sync()`；
- `strlcpy()` 迁移为 `strscpy()`；
- 删除驱动内部复制的旧 `VM_*` 常量，使用目标内核定义。

HiBMC 补丁主要包含：

- DRM aperture API 更新；
- connector `const mode` 参数适配；
- DRM client/fbdev TTM 接口适配。

对应补丁：

- [`bma-pve-7.0-compat.patch`](../patches/bma-pve-7.0-compat.patch)
- [`hibmc-pve-7.0-compat.patch`](../patches/hibmc-pve-7.0-compat.patch)

## 4. 应用补丁

补丁路径以 openEuler 源码目录中的相对路径为基准。先复制一份构建树，再
应用补丁，禁止直接修改唯一的原始源码归档。

```sh
cp -a /path/to/bma-source ./bma-pve-compat
patch -p1 -d ./bma-pve-compat < patches/bma-pve-7.0-compat.patch
```

HiBMC 同理。不同 openEuler 更新版本的上下文可能变化，`patch` 失败时应
人工移植，不要使用强制或模糊度过高的方式跳过冲突。

## 5. 构建

```sh
sudo apt-get install build-essential bc bison flex libelf-dev libssl-dev pahole rsync

KDIR=/usr/src/linux-headers-$(uname -r) \
BMA_SRC=/path/to/bma-pve-compat \
OUT=$PWD/modules \
./scripts/build-kunpeng-modules.sh
```

如需构建 HiBMC，还需提供 `HIBMC_SRC` 和与目标内核完全对应的
`VRAM_HELPER_SRC`。

## 6. 加载前检查

```sh
modinfo -F vermagic modules/host_edma_drv.ko
uname -r
modprobe -n -v host_edma_drv
```

要求模块 `vermagic` 的首字段与 `uname -r` 完全相同。首次加载顺序：

```text
host_edma_drv -> host_cdev_drv -> host_veth_drv
```

回滚顺序相反。加载后检查：

```sh
lspci -nnk -d 19e5:1710
ls -l /dev/hwibmc*
ip -br link show veth
dmesg | grep -Ei 'edma|ibma|unknown symbol|oops|call trace'
```

## 7. 内核升级

外置模块不随 PVE 内核自动升级。升级后必须：

1. 安装新内核 headers；
2. 重新应用或复核补丁；
3. 重编所有 BMA 模块；
4. 核对 `vermagic`、modversion 和加载结果；
5. 再重启到新内核。

Secure Boot 开启时还需对模块签名，并将签名证书加入平台信任链。
