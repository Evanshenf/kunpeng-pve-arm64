#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
用法：
  install-ibma-pve-arm64.sh --runtime-dir DIR --modules-dir DIR \
    [--config-file FILE] [--start]

参数：
  --runtime-dir  已合法取得并解压的 iBMA 用户态目录。
  --modules-dir  针对当前 PVE 内核编译的 BMA 模块目录。
  --config-file  已审核的完整 iBMA.ini；省略时保留厂商运行目录中的配置。
  --start        安装完成后立即启动；默认只安装并启用开机启动。
EOF
}

runtime_dir=""
modules_dir=""
config_file=""
start_now=false

while (($#)); do
    case "$1" in
        --runtime-dir)
            runtime_dir="${2:-}"
            shift 2
            ;;
        --modules-dir)
            modules_dir="${2:-}"
            shift 2
            ;;
        --config-file)
            config_file="${2:-}"
            shift 2
            ;;
        --start)
            start_now=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "未知参数：$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    echo "必须以 root 执行。" >&2
    exit 1
fi
if [[ $(uname -m) != aarch64 ]]; then
    echo "当前脚本仅支持 aarch64。" >&2
    exit 1
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/.." && pwd)
service_file="$repo_root/systemd/iBMA.service"
kernel=$(uname -r)
module_target="/lib/modules/$kernel/updates/iBMA_driver"
required_modules=(host_edma_drv host_cdev_drv host_veth_drv cdev_veth_drv host_kbox_drv)
required_commands=(modinfo depmod systemctl ipmitool dmidecode setfacl netstat ifconfig)

[[ -f "$runtime_dir/iBMA.sh" ]] || { echo "无效用户态目录：$runtime_dir" >&2; exit 1; }
[[ -d $modules_dir ]] || { echo "无效模块目录：$modules_dir" >&2; exit 1; }
[[ -f $service_file ]] || { echo "缺少 systemd unit：$service_file" >&2; exit 1; }
[[ ! -e /opt/ibma ]] || { echo "/opt/ibma 已存在，请先备份或回滚。" >&2; exit 1; }
if [[ -n $config_file && ! -f $config_file ]]; then
    echo "配置文件不存在：$config_file" >&2
    exit 1
fi

for command_name in "${required_commands[@]}"; do
    command -v "$command_name" >/dev/null || {
        echo "缺少依赖命令：$command_name" >&2
        exit 1
    }
done

for module_name in "${required_modules[@]}"; do
    module_file="$modules_dir/$module_name.ko"
    [[ -f $module_file ]] || { echo "缺少模块：$module_file" >&2; exit 1; }
    module_kernel=$(modinfo -F vermagic "$module_file" | awk '{print $1}')
    [[ $module_kernel == "$kernel" ]] || {
        echo "$module_name vermagic=$module_kernel，与当前内核 $kernel 不匹配。" >&2
        exit 1
    }
done

if [[ -r /proc/sys/kernel/module_sig_enforce ]] &&
   [[ $(cat /proc/sys/kernel/module_sig_enforce) == 1 ]]; then
    echo "当前内核强制模块签名，未登记可信签名时禁止继续。" >&2
    exit 1
fi

backup_root="/root/maintenance-backup/ibma-$(date +%Y%m%d-%H%M%S)"
install -d -m 0700 "$backup_root"
dpkg-query -W acl net-tools > "$backup_root/dependencies.txt" 2>&1 || true

install -d -m 0755 "$module_target"
for module_name in "${required_modules[@]}"; do
    install -o root -g root -m 0644 "$modules_dir/$module_name.ko" "$module_target/"
done
depmod -a "$kernel"

install -d -m 0755 /opt
cp -a "$runtime_dir" /opt/ibma
if [[ -n $config_file ]]; then
    install -o root -g root -m 0640 "$config_file" /opt/ibma/config/iBMA.ini
fi
install -o root -g root -m 0644 "$service_file" /etc/systemd/system/iBMA.service
ln -sfn /opt/ibma/bin/ibmacli /usr/local/bin/ibmacli

systemctl daemon-reload
systemctl enable iBMA.service

if $start_now; then
    systemctl start iBMA.service
fi

echo "iBMA 文件已安装。回滚基准目录：$backup_root"
