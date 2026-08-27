# BMA and HiBMC Driver Porting

[中文](../kunpeng-driver-porting.md) | [English](kunpeng-driver-porting.md)

## 1. Source Boundary

The BMA and HiBMC DRM drivers are available in the openEuler kernel source.
The iBMA Manager, Monitor, and Redfish userspace is closed-source and is not
part of the kernel tree.

The validated source baseline was the release SRPM from openEuler 24.03
LTS-SP3:

```text
kernel-6.6.0-145.3.26.157.oe2403sp3.src.rpm
```

Obtain the SRPM from an official openEuler repository, verify its RPM signature
and SHA256 digest, and then extract the BMA and HiBMC sources from its complete
`kernel.tar.gz` archive.

## 2. Driver Components

| Module | Purpose |
| --- | --- |
| `host_edma_drv` | iBMA EDMA core, matching `19e5:1710/1712` |
| `host_cdev_drv` | Character devices under `/dev/hwibmc*` |
| `host_veth_drv` | VETH management link between the OS and BMC |
| `cdev_veth_drv` | Optional CDEV network mode |
| `host_kbox_drv` | Optional KBOX support |
| `hibmc_drm` | BMC VGA DRM driver, matching `19e5:1711` |

HiBMC DRM is not a direct dependency of the BMA EDMA/VETH path, but it can be
enabled as the native display driver. When PVE already has a basic console via
UEFI GOP and simpledrm, switch drivers only during a maintenance window with a
working out-of-band recovery path.

## 3. Linux 7.0 Compatibility Changes

The BMA patch primarily:

- migrates timer APIs to `timer_container_of()` and `timer_delete_sync()`;
- replaces removed `strlcpy()` calls with `strscpy()`;
- removes private copies of legacy `VM_*` constants and uses target-kernel
  definitions.

The HiBMC patch primarily:

- updates the DRM aperture API;
- adapts the connector `const mode` parameter;
- adapts the DRM client/fbdev TTM interfaces.

Patches:

- [`bma-pve-7.0-compat.patch`](../../patches/bma-pve-7.0-compat.patch)
- [`hibmc-pve-7.0-compat.patch`](../../patches/hibmc-pve-7.0-compat.patch)

## 4. Applying the Patches

Patch paths are relative to the corresponding openEuler source directory.
Create a separate build tree first; do not modify your only pristine source
archive.

```sh
cp -a /path/to/bma-source ./bma-pve-compat
patch -p1 -d ./bma-pve-compat < patches/bma-pve-7.0-compat.patch
```

Apply the HiBMC patch in the same way. Context may differ in newer openEuler
updates. If `patch` fails, port the change manually rather than forcing rejects
or accepting excessive fuzz.

## 5. Building

```sh
sudo apt-get install build-essential bc bison flex libelf-dev libssl-dev pahole rsync

KDIR=/usr/src/linux-headers-$(uname -r) \
BMA_SRC=/path/to/bma-pve-compat \
OUT=$PWD/modules \
./scripts/build-kunpeng-modules.sh
```

To build HiBMC, also provide `HIBMC_SRC` and a `VRAM_HELPER_SRC` that exactly
matches the target kernel.

## 6. Checks Before Loading

```sh
modinfo -F vermagic modules/host_edma_drv.ko
uname -r
modprobe -n -v host_edma_drv
```

The first field of each module's `vermagic` must exactly match `uname -r`.
Initial load order:

```text
host_edma_drv -> host_cdev_drv -> host_veth_drv
```

Unload in reverse order. After loading, verify:

```sh
lspci -nnk -d 19e5:1710
ls -l /dev/hwibmc*
ip -br link show veth
dmesg | grep -Ei 'edma|ibma|unknown symbol|oops|call trace'
```

When HiBMC is enabled, also verify:

```sh
lspci -nnk -d 19e5:1711
cat /proc/fb
cat /sys/class/graphics/fb0/name
cat /sys/class/drm/card*-*/status
```

## 7. Kernel Upgrades

External modules do not follow PVE kernel upgrades automatically. Before
booting a new kernel:

1. install the new kernel headers;
2. reapply or review the compatibility patches;
3. rebuild all BMA modules;
4. verify `vermagic`, modversions, and load behavior;
5. only then reboot into the new kernel.

With Secure Boot enabled, sign the modules and enroll the signing certificate
into the platform trust chain.
