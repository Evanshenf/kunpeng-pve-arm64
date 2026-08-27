# iBMA Deployment and Rollback

[中文](../ibma-deployment.md) | [English](ibma-deployment.md)

## 1. Software Boundary

The iBMA userspace is not part of the openEuler kernel source. Obtain it
legally through the server vendor's support channel and comply with its license.
This repository does not redistribute closed-source binaries.

Official Huawei entry point:

<https://support.huawei.com/enterprise/en/management-software/ibma-pid-21099187/software>

The package generally requires an enterprise support account and the relevant
download entitlement. The validated setup used iBMA 2.20.0 userspace with BMA
0.4.0 modules rebuilt for PVE `7.0.14-6-pve`. This is an experimental
compatibility combination, not an official Debian 13/PVE support statement
from the vendor.

## 2. Dependencies

```sh
sudo apt-get install --no-install-recommends \
  acl net-tools ipmitool dmidecode ethtool pciutils curl
```

Check the target before deployment:

```sh
uname -m
uname -r
lspci -nn -d 19e5:1710
test -e /dev/kvm
```

## 3. Recommended Configuration

Review these settings in the complete vendor-provided `iBMA.ini`:

```text
iBMA_network_type=veth
iBMA_kbox=false
iBMA_support_config_rules=false
```

- VETH uses an isolated link and must not be attached to the PVE management
  bridge.
- Keep KBOX disabled during the first deployment to avoid conflicts with
  kdump or an existing `/dev/kbox`.
- Disable iBMA-managed firewall changes so that the closed-source installer
  cannot modify the PVE firewall. Add any required rules explicitly through
  PVE operations.

[`iBMA.ini.override.example`](../../config/iBMA.ini.override.example) lists
only recommended overrides. It is not a complete vendor configuration file.

## 4. Installation

Prepare:

- a legally obtained and extracted iBMA userspace directory;
- a module directory built for the exact target PVE kernel;
- a reviewed, complete iBMA configuration file.

```sh
sudo ./scripts/install-ibma-pve-arm64.sh \
  --runtime-dir /path/to/vendor/ibma \
  --modules-dir /path/to/modules \
  --config-file /path/to/iBMA.ini \
  --with-hibmc \
  --start
```

`--with-hibmc` is optional. The BMA EDMA/VETH path does not directly depend
on DRM. Use this option only when the native Hi1711 display driver is desired.
The script installs it for the next boot instead of forcibly replacing the
active framebuffer in the current session. Validate the switch with a
controlled reboot.

The script:

1. validates AArch64, required commands, and module `vermagic`;
2. installs modules under the current kernel's `updates/iBMA_driver`;
3. installs the vendor userspace under `/opt/ibma`;
4. registers and enables `iBMA.service`;
5. optionally starts the service immediately.

## 5. Verification

```sh
sudo ./scripts/verify-ibma-pve-arm64.sh
ibmacli version
```

Successful baseline:

- `host_edma_drv`, `host_cdev_drv`, and `host_veth_drv` are loaded;
- `19e5:1710` is bound to the EDMA driver;
- `/dev/hwibmc*` devices exist;
- both ends of the VETH link communicate;
- Manager, Monitor, and Redfish remain stable;
- unauthenticated local HTTPS Redfish access returns 401;
- the BMC reports the OS, kernel, iBMA, and driver versions;
- the PVE management bridge, default route, VMs, and containers are unaffected.

With `--with-hibmc`, also verify that:

- `19e5:1711` is bound to `hibmc-drm`;
- `/proc/fb` reports `hibmcdrmfb`;
- the DRM connector state is `connected`;
- BMC KVM or its screenshot function can still read the display.

## 6. Known iBMA 2.20 Message

On newer BMC firmware, iBMA 2.20 may emit one response-format warning for a
legacy OEM IPMI command during startup. It can be recorded as non-blocking only
when registration, heartbeat, resource reads, and BMC inventory all succeed.
If registration fails, stop the service and roll back instead of ignoring it.

## 7. Reboot Acceptance

Schedule a controlled reboot after the first deployment. Confirm that the iBMA
service, three BMA modules, VETH, BMC registration, and all existing PVE guests
recover automatically before restoring workload scheduling.

## 8. Rollback

```sh
sudo ./scripts/rollback-ibma-pve-arm64.sh
```

The rollback script does not delete files directly. It stops the service,
unloads modules in reverse order, and moves the userspace, service unit, and
module directories into a root-only quarantine directory. If a module cannot
be unloaded because it is in use, preserve the state and reboot during a
maintenance window rather than forcing removal.

When `hibmc_drm` owns the framebuffer, the rollback script does not force an
online unload. It removes the persistent configuration for the next boot and
requires a normal reboot so that the firmware framebuffer and `simpledrm` can
take over again.
