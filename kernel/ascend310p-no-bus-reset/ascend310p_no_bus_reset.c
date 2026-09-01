// SPDX-License-Identifier: GPL-2.0-only

#include <linux/device/bus.h>
#include <linux/module.h>
#include <linux/pci.h>
#include <linux/string.h>

#define PCI_VENDOR_ID_HUAWEI_LOCAL 0x19e5
#define PCI_DEVICE_ID_ASCEND310P 0xd500
#define ASCEND310P_BDF_LIST_SIZE 256

static char target_bdfs[ASCEND310P_BDF_LIST_SIZE];
module_param_string(target_bdfs, target_bdfs, sizeof(target_bdfs), 0444);
MODULE_PARM_DESC(
	target_bdfs,
	"Comma-separated PCI BDF allowlist; empty protects every Ascend 310P"
);

static bool ascend310p_is_target(struct pci_dev *pdev)
{
	char list[ASCEND310P_BDF_LIST_SIZE];
	char *cursor;
	char *token;

	if (pdev->vendor != PCI_VENDOR_ID_HUAWEI_LOCAL ||
	    pdev->device != PCI_DEVICE_ID_ASCEND310P)
		return false;

	if (!target_bdfs[0])
		return true;

	strscpy(list, target_bdfs, sizeof(list));
	cursor = list;
	while ((token = strsep(&cursor, ",")) != NULL) {
		token = strim(token);
		if (token[0] && !strcmp(token, pci_name(pdev)))
			return true;
	}

	return false;
}

static void ascend310p_disable_bus_reset(struct pci_dev *pdev)
{
	if (!ascend310p_is_target(pdev))
		return;

	if (pdev->dev_flags & PCI_DEV_FLAGS_NO_BUS_RESET)
		return;

	pdev->dev_flags |= PCI_DEV_FLAGS_NO_BUS_RESET;
	pci_info(pdev, "disabled unsafe secondary bus reset\n");
}

static void ascend310p_enable_bus_reset(struct pci_dev *pdev)
{
	if (!ascend310p_is_target(pdev))
		return;

	if (!(pdev->dev_flags & PCI_DEV_FLAGS_NO_BUS_RESET))
		return;

	pdev->dev_flags &= ~PCI_DEV_FLAGS_NO_BUS_RESET;
	pci_info(pdev, "restored secondary bus reset for controlled maintenance\n");
}

static int ascend310p_pci_bus_notify(struct notifier_block *nb,
				     unsigned long action, void *data)
{
	struct device *dev = data;

	if (action != BUS_NOTIFY_ADD_DEVICE || dev->bus != &pci_bus_type)
		return NOTIFY_DONE;

	ascend310p_disable_bus_reset(to_pci_dev(dev));
	return NOTIFY_OK;
}

static struct notifier_block ascend310p_pci_nb = {
	.notifier_call = ascend310p_pci_bus_notify,
};

static int __init ascend310p_no_bus_reset_init(void)
{
	struct pci_dev *pdev = NULL;
	int ret;

	ret = bus_register_notifier(&pci_bus_type, &ascend310p_pci_nb);
	if (ret)
		return ret;

	for_each_pci_dev(pdev)
		ascend310p_disable_bus_reset(pdev);

	pr_info("ascend310p_no_bus_reset: guard enabled\n");
	return 0;
}

static void __exit ascend310p_no_bus_reset_exit(void)
{
	struct pci_dev *pdev = NULL;

	bus_unregister_notifier(&pci_bus_type, &ascend310p_pci_nb);
	for_each_pci_dev(pdev)
		ascend310p_enable_bus_reset(pdev);

	pr_info("ascend310p_no_bus_reset: guard disabled\n");
}

module_init(ascend310p_no_bus_reset_init);
module_exit(ascend310p_no_bus_reset_exit);

MODULE_AUTHOR("Evanshenf <archwse@gmail.com>");
MODULE_DESCRIPTION("Prevent unsafe PCI bus reset of Huawei Ascend 310P devices");
MODULE_LICENSE("GPL");
