# Atlas 300I Duo Mixed Mode: Full VFIO and vNPU on Separate Cards

[中文](../ascend-310p-mixed-mode-pve.md)

## Result

The validated Kunpeng/PVE ARM64 host uses two Atlas 300I Duo cards in different
modes:

- `0000:03:00.0` is bound to `vfio-pci` in initramfs and passed to VM100;
- `0000:04:00.0` remains host-managed and exposes `vir01=7`, `vir02=3`, and
  `vir04=1`;
- the guest sees two healthy physical 310P3 chips and runs Qwen3-VL DP2/TP1;
- OCR remains a guest-CPU service.

## Required fixes

The vendor VM-mode command affects every host-visible card even when `-i` is
supplied. Runtime unbind is too late because the host driver has already placed
the card in a vNPU boot mode. The physical card must therefore be hidden behind
VFIO in initramfs before the host driver loads.

The host UDA driver also derives its expected physical-device count from the
NUMA-node count. This host has four NUMA nodes but only two host-visible 310P
chips after one Duo card is hidden. The incremental
[`ascend310p-mixed-mode-uda-count.patch`](../../patches/ascend310p-mixed-mode-uda-count.patch)
adds the read-only `uda_expected_phy_dev_num` parameter; zero preserves the
vendor behavior, while this deployment sets it to two.

During the controlled pre-start bus reset, PCI automatic probing is disabled
temporarily. The final `19e5:d500` endpoint receives
`driver_override=vfio-pci` before a manual probe, so the host vendor driver
cannot reclaim it and change its boot mode.

## Configuration

```text
ASCEND_VFIO_BDFS=0000:03:00.0
ASCEND_VNPU_BDFS=0000:04:00.0
ASCEND_SET_VNPU_VM_MODE=1
```

```text
options ascend310p_no_bus_reset target_bdfs=0000:03:00.0
options ascend_uda uda_expected_phy_dev_num=2
```

```text
hostpci0: 0000:03:00.0,driver=keep
hookscript: local:snippets/pve-ascend310p-hook
```

Disable the global `ascend-vnpu-vm-mode.service`. Enable
`ascend310p-mixed-mode-bind.service` and
`ascend310p-vfio-reset-guard.service` instead. The initramfs hook and init-top
script under `initramfs/` copy the BDF configuration and bind the selected card
before vendor modules are available.

## Validation

Two complete pre-start cycles passed. Each cycle produced one controlled
reset, no vendor-driver claim of `03:00.0`, no missing-host-device error, and a
healthy two-chip physical guest. `04:00.0` retained its `7/3/1` templates. A
temporary `vir01` instance reduced availability from seven to six and removal
restored it to seven while Qwen was using the physical card.

Measured results:

| Workload | Dual vir04 DP2 | One physical Duo card DP2 |
| --- | ---: | ---: |
| 295 output tokens, single request | 12.128 s | 9.341 s |
| End-to-end output rate | about 24.3 tokens/s | 31.6 tokens/s |
| Two concurrent 295-token requests | not measured | 10.609 s, 55.6 aggregate tokens/s |
| OCR plus short Qwen analysis | 5.414 s | 4.576 s |

Keep the original VM snapshot, QEMU package, driver source, module hashes, and
host configuration together. Kernel, QEMU, or Ascend driver upgrades require
rebuilding the local patches and repeating host-boot, mdev lifecycle, guest
boot, and two-cycle reset tests.
