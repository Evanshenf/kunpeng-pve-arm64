# Third-Party Notices / 第三方声明

## Huawei Ascend

`patches/ascend310p-driver-26.1.1-pve-7.0-vnpu.patch` is a compatibility patch
for source files delivered inside the official Huawei Ascend 310P driver
package. The repository does not redistribute the original package, firmware,
prebuilt modules, certificates, or other vendor binaries. Users must obtain the
official package through an authorized Huawei/Ascend channel and comply with
the license notices shipped with that package.

该补丁仅描述对华为官方 Ascend 310P 驱动源码的兼容性修改。仓库不分发原始
驱动包、固件、预编译模块、证书或其他厂商二进制。使用者应从获得授权的
华为/昇腾渠道取得官方包，并遵守包内许可证与权利声明。

Huawei, Ascend, Atlas, and related names are trademarks of their respective
owners. This project is an independent community compatibility effort and does
not imply endorsement or official support by Huawei.

## Linux mdev

The compatibility patch carries the mediated-device core implementation from
the Linux stable `v7.0.14` source tree because the tested PVE kernel was built
without `CONFIG_VFIO_MDEV`. Those files retain their original SPDX and
copyright notices and are distributed under GPL-2.0-only.

Reference: <https://docs.kernel.org/driver-api/vfio-mediated-device.html>

## Proxmox VE

Proxmox and Proxmox VE are trademarks of Proxmox Server Solutions GmbH. This
repository is not an official Proxmox product or support commitment.
