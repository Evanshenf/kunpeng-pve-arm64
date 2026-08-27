# iBMA 部署与回滚

[中文](ibma-deployment.md) | [English](en/ibma-deployment.md)

## 1. 软件边界

iBMA 用户态不是 openEuler 内核源码的一部分。请从服务器厂商支持渠道合法
取得，并遵守许可要求；本仓库不分发闭源二进制。

华为官方入口：

<https://support.huawei.com/enterprise/en/management-software/ibma-pid-21099187/software>

软件通常需要企业支持账号和下载权限。当前实测使用 iBMA 2.20.0 用户态，
搭配针对 PVE `7.0.14-6-pve` 自行构建的 BMA 0.4.0 驱动。这是实验性兼容
组合，不是厂商正式 Debian 13/PVE 支持声明。

## 2. 依赖

```sh
sudo apt-get install --no-install-recommends \
  acl net-tools ipmitool dmidecode ethtool pciutils curl
```

部署前确认：

```sh
uname -m
uname -r
lspci -nn -d 19e5:1710
test -e /dev/kvm
```

## 3. 配置建议

在厂商提供的完整 `iBMA.ini` 中核对以下项目：

```text
iBMA_network_type=veth
iBMA_kbox=false
iBMA_support_config_rules=false
```

- VETH 使用独立链路，不应加入 PVE 管理桥。
- 首次部署关闭 KBOX，避免与 kdump 或既有 `/dev/kbox` 冲突。
- 关闭 iBMA 自行配置防火墙，避免修改 PVE firewall；如需放行规则，应由
  运维人员在 PVE 侧显式管理。

仓库中的 [`iBMA.ini.override.example`](../config/iBMA.ini.override.example)
仅列出建议覆盖项，不是完整厂商配置文件。

## 4. 安装

先准备：

- 合法取得并解压的 iBMA 用户态目录；
- 当前 PVE 内核对应的 `.ko` 模块目录；
- 已审核的完整 iBMA 配置文件。

```sh
sudo ./scripts/install-ibma-pve-arm64.sh \
  --runtime-dir /path/to/vendor/ibma \
  --modules-dir /path/to/modules \
  --config-file /path/to/iBMA.ini \
  --with-hibmc \
  --start
```

`--with-hibmc` 是可选项。BMA EDMA/VETH 主链不直接依赖 DRM；需要恢复
原生 Hi1711 显示驱动时再指定。脚本只安装并配置开机加载，不在当前会话中
强制替换 framebuffer，必须通过受控重启完成切换。

脚本会：

1. 校验 AArch64、依赖命令和模块 `vermagic`；
2. 安装模块到当前内核的 `updates/iBMA_driver`；
3. 安装厂商用户态到 `/opt/ibma`；
4. 注册并启用 `iBMA.service`；
5. 可选立即启动。

## 5. 验证

```sh
sudo ./scripts/verify-ibma-pve-arm64.sh
ibmacli version
```

成功基线：

- `host_edma_drv`、`host_cdev_drv`、`host_veth_drv` 已加载；
- `19e5:1710` 绑定 EDMA 驱动；
- `/dev/hwibmc*` 存在；
- VETH 两端互通；
- Manager、Monitor、Redfish 三个进程稳定；
- 未认证访问本地 HTTPS Redfish 返回 401；
- BMC 显示 OS、内核、iBMA 和驱动版本；
- PVE 管理桥、默认路由、VM/LXC 不受影响。

启用 `--with-hibmc` 时还应确认：

- `19e5:1711` 绑定 `hibmc-drm`；
- `/proc/fb` 显示 `hibmcdrmfb`；
- DRM 连接器状态为 `connected`；
- BMC KVM 或截图功能仍可正常读取画面。

## 6. 已知 2.20 提示

在较新的 BMC 上，2.20 启动时可能出现一次旧 IPMI 扩展命令返回格式告警。
如果后续注册、心跳、资源读取和 BMC 信息均正常，可按非阻断兼容提示记录；
如果注册失败，则应停止服务并回滚，不能忽略。

## 7. 重启验收

首次部署后必须安排一次受控重启。确认 iBMA 服务、三模块、VETH、BMC 注册
以及原有 PVE 来宾全部自动恢复，再恢复业务调度。

## 8. 回滚

```sh
sudo ./scripts/rollback-ibma-pve-arm64.sh
```

回滚脚本不会直接删除文件，而是停止服务、反向卸载模块，并将用户态、
service 和模块目录移动到 root 私有隔离目录。模块因占用无法卸载时，不要
强制操作，应保留现场并在维护窗口重启。

`hibmc_drm` 正在提供 framebuffer 时，回滚脚本不会在线强制卸载，只会
移除下次启动的持久配置并要求正常重启，让 firmware framebuffer/
`simpledrm` 重新接管。
