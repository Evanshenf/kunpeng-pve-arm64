# Qwen3-VL：Ascend 310P vNPU 推理部署

[English](en/qwen3-vl-vnpu.md)

## 1. 实测目标

本文记录在 PVE ARM64 虚拟机中使用 Atlas 300I Duo `vir04`，部署
Qwen3-VL-4B-Instruct W8A8SC TP1 和 vLLM Ascend OpenAI 兼容 API 的方法。

已验证的数据路径：

```text
PVE ARM64 -> VFIO mdev / vir04 -> openEuler Guest
  -> Ascend vnpu_guest driver -> Docker -> vLLM Ascend -> Qwen3-VL
```

该流程只发布配置、脚本和源码规避，不分发模型权重、厂商驱动、
镜像层或密钥。

## 2. 实测基线

| 项目 | 配置 |
| --- | --- |
| 宿主 | PVE 9.2.9 ARM64，Linux `7.0.14-6-pve` |
| 加速卡 | Atlas 300I Duo / Ascend 310P3 |
| vNPU | `vir04`，4 AI Core / 24 GB |
| Guest | openEuler 24.03 LTS SP3，16 vCPU / 32 GiB RAM |
| Guest 驱动 | Ascend 25.2.0 `vnpu_guest` |
| Docker | 25.0.3 |
| 基础镜像 | `quay.io/ascend/vllm-ascend:v0.23.0-310p-openeuler` ARM64 |
| 模型 | Qwen3-VL-4B-Instruct W8A8SC TP1 |

PVE mdev 配置示例：

```bash
qm set <VMID> -hostpci0 <BDF>,mdev=vnpu-vir04
```

ARM `virt` 机型不要附加 `pcie=1`。宿主驱动和 mdev 的完整部署见
[Atlas 300I Duo vNPU 文档](ascend-310p-vnpu-pve.md)。

## 3. 310P 多模态规避

实测 vLLM Ascend 0.23.0 的多模态 embedding 合并在 310P 上可因 AICPU
`IndexPut` 报 `507018`。[`examples/qwen3-vl-310p`](../examples/qwen3-vl-310p/)
引入 vllm-ascend PR #12914 的 310P 限定规避：将布尔掩码 `index_put_`
替换为整数索引 `index_copy_`。

构建时锁定基础镜像 digest：

```bash
cd examples/qwen3-vl-310p
docker build -t local/vllm-ascend:qwen3vl-0.23.0-310p .
```

如后续上游版本已合并等价修复，应先去掉本地 monkey patch 再做回归，
避免重复覆盖。

## 4. Guest 部署

### 4.1 前置检查

```bash
npu-smi info
docker version
```

NPU 应显示 `310Pvir04` 和 `Health: OK`。

### 4.2 模型和目录

从授权渠道取得与 Ascend 310P/vLLM 匹配的 TP1 权重，并记录来源、版本、
大小和 SHA-256。本仓库的 `run-container.sh` 默认从下列目录挂载：

```text
/srv/models/Qwen3-VL-4B-Instruct-w8a8sc-310-vllm-tp1
```

安装运行文件：

```bash
install -d -m 0755 /opt/vision-qwen3vl /var/cache/vision-qwen3vl
install -m 0755 run-container.sh start-vllm.sh wait-for-npu.sh \
    /opt/vision-qwen3vl/
install -d -m 0750 /etc/vision-qwen3vl
install -m 0600 runtime.env.example /etc/vision-qwen3vl/runtime.env
install -m 0644 vision-qwen3vl.service /etc/systemd/system/
```

将 `runtime.env` 中的示例 API Key 替换为随机值：

```bash
openssl rand -hex 32
chmod 0600 /etc/vision-qwen3vl/runtime.env
```

不要将真实密钥提交到 Git。

### 4.3 启动

```bash
systemctl daemon-reload
systemctl enable --now vision-qwen3vl.service
```

`wait-for-npu.sh` 会先检查必要设备节点和 `npu-smi`。模型首次编译和
Graph 构建可需要数分钟，应以 `/health` 返回 HTTP 200 为最终就绪条件。

## 5. API 使用

健康检查：

```bash
curl -fsS http://<guest-ip>:8000/health
```

认证接口：

```bash
curl -fsS http://<guest-ip>:8000/v1/models \
    -H "Authorization: Bearer ${VISION_API_KEY}"
```

图片请求使用 OpenAI 兼容的 `image_url` 内容块，可传 HTTP(S) URL 或
`data:image/...;base64,...`。需要稳定字段时建议增加 JSON Schema 约束。

## 6. 性能结论

| 用例 | 单 `vir04` 实测 |
| --- | ---: |
| 1920×1080，2064 prompt tokens，8～9 输出 tokens | 4.709～5.061 s |
| 1280×720，短结果 | 约 1.65 s |
| 1280×720，完整格式化 JSON | 约 7.68 s |
| 640×360，短结果 | 约 0.69～0.83 s |

从 eager 切换到 `FULL_DECODE_ONLY` Graph 后，解码速度约提升 2.3 倍。
Graph 不修改模型权重或图片，当前样例未发现识别准确率回退。

缩放图片会损失小字和坐标精度。对桌面自动化，建议使用“低分辨率全图
定位 + 原图裁剪复核”，并把裁剪坐标映射回原始分辨率。

`vir04` 已是当前单个 vNPU 最大通用模板。增加第二个 `vir04` 做双实例
可使并发吞吐接近翻倍，但不会缩短单请求；TP2 需要匹配权重和通信验证，
对 4B 模型的单请求收益通常低于 2 倍。

## 7. 维护与安全

```bash
systemctl status vision-qwen3vl.service
journalctl -u vision-qwen3vl.service -b --no-pager
docker logs --tail 200 vision-qwen3vl
npu-smi info
```

- 如 Graph 出现兼容性回归，可临时将 `VLLM_EXECUTION_MODE=eager` 后重启。
- 升级模型或镜像前保留原标签、digest、权重哈希和服务参数。
- 当前示例是带 API Key 的明文 HTTP，不应直接暴露到不可信网络。
- 模型许可、容器镜像和 Ascend 驱动仍遵循各自上游许可。
