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

同一套脚本也支持整卡多芯片数据并行。物理卡 Guest 可在 `runtime.env` 中设置：

```text
ASCEND_RT_VISIBLE_DEVICES=0,1,2,3
TENSOR_PARALLEL_SIZE=1
DATA_PARALLEL_SIZE=4
API_SERVER_COUNT=1
LOAD_FORMAT=sharded_state
```

整卡宿主配置见
[Atlas 300I Duo 整卡直通文档](ascend-310p-vfio-pve.md)。

双 `vir04` 配置使用两张卡的普通资源池：

```text
hostpci0: 0000:03:00.0,mdev=vnpu-vir04
hostpci1: 0000:04:00.0,mdev=vnpu-vir04
```

Guest 设置 `ASCEND_RT_VISIBLE_DEVICES=0,1`、`DATA_PARALLEL_SIZE=2`、
`TENSOR_PARALLEL_SIZE=1`。当前 TP1 W8A8SC 权重不能直接改为 TP2。

当前 F30 实机进一步切换为混合模式：一张 Duo 整卡向 VM100 提供两颗物理
310P3，仍使用 `VISIBLE_DEVICES=0,1 / DP=2`；另一张 Duo 留在宿主，继续提供
`vir01=7 / vir02=3 / vir04=1`。该模式的 initramfs、UDA 和 reset 约束见
[混合部署文档](ascend-310p-mixed-mode-pve.md)。

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

两张整卡、四颗 310P3 的实测 DP4 吞吐为单请求基线的 3.89～3.98 倍；该模式仍不
缩短单请求。完整测试条件和数据见
[整卡直通性能结果](ascend-310p-vfio-pve.md#8-性能结果)。

双 `vir04` DP2 实测：

| 用例 | 结果 |
| --- | ---: |
| 单请求，384 completion tokens，3 次平均 | 17.744 s |
| 两个相同请求并发总耗时 | 19.969 s |
| 聚合吞吐提升 | 1.777 倍 |
| 单请求完整输出，590 completion tokens | 26.314 s |
| 上下重叠裁剪双请求完整输出 | 18.041 s |
| 完整结果延迟降低 | 31.44% |

[`dual-region-analyze.py`](../examples/qwen3-vl-310p/dual-region-analyze.py)
在客户端将原图裁为上下各 60%、中间重叠 20%，并发请求两个 vir04 后直接
合并 JSON，不增加第三次模型调用。该方案覆盖范围完整，但 4B 对少数人名仍
可能产生 OCR 冲突；精确文字场景应保留两个区域原始结果或增加专用 OCR 校验。

同一张 957×877、29 行中文测试图增加 RapidOCR 3.9.2 / PP-OCRv6 small
CPU 基线后，结果如下：

| 路径 | 实测结果 |
| --- | ---: |
| OCR 默认 6 行批量，热运行平均 | 1.850 s |
| OCR 16 行批量，热运行平均 | 1.623 s |
| OCR 32 行批量，热运行平均 | 1.998 s |
| OCR + 4B 纯文本议程整理 | 19.808 s，384 tokens 仍截断 |
| OCR + 本地规则整理（最终客户端） | 2.494 s（含进程启动），完整 5 个议题 |

因此文字密集页面应由
[`ocr-first-analyze.py`](../examples/qwen3-vl-310p/ocr-first-analyze.py)
先返回文本、置信度和精确框坐标。固定议程/表单使用确定性规则，只有图标、
关系和异常语义才回退到 Qwen。不要把全部 OCR 文本无条件再交给 4B 重写，
否则生成阶段会抵消 OCR 的速度收益。

### 6.1 为什么单会话不是按纸面 TOPS 换算

华为公开规格中，单张 Atlas 300I Duo 的 280 TOPS INT8 和 408 GB/s 是两颗
310 系列处理器、共 16 个 AI Core 的整卡指标；vNPU 的 AI Core、内存等资源
按模板切分。当前每个 `vir04` 只有 4 个 AI Core，两张 `vir04` 运行的是两个
TP1 模型副本。DP2 负责并发负载均衡，并不把两个切片合并计算一个 token。

当前 vLLM Prometheus 累计指标：

| 指标 | Engine 0 | Engine 1 |
| --- | ---: | ---: |
| 平均 inter-token latency | 42.96 ms | 41.98 ms |
| 对应稳定生成速度 | 23.28 tokens/s | 23.82 tokens/s |
| 平均 TTFT | 1.36 s | 1.30 s |

受控纯文本请求生成 295 tokens，总耗时 12.128 s，端到端约 24.3 tokens/s。
请求期间实际命中的 `vir04` AI Core 利用率为 91%～93%，另一个 DP 副本为
0%，说明单切片已接近忙满。自回归 decode 是低 batch 的矩阵向量和权重搬运
场景，主要受单切片内存带宽、算子调度和每 token 串行依赖限制，不能用整卡
大矩阵 INT8 TOPS 直接推算。

同一 871 prompt / 384 completion tokens 用例中，整卡单芯片从 `vir04` 的
约 17.89 s 改善到约 13.51 s，证明增加物理资源有收益，但不是线性翻倍。
进一步降低单请求延迟的候选顺序是：专用 OCR/规则绕过长生成、流式返回、
匹配模型的 speculative decoding、重新生成 TP2 量化权重，以及经 310P
实测确认的更低比特权重；不能只增加 DP 副本。

### 6.2 OCR 与 Qwen 统一入口

[`vision-router.py`](../examples/qwen3-vl-310p/vision-router.py) 作为独立
sidecar 监听 `8001`，不修改原 vLLM `8000` 服务。接口保持 OpenAI
`/v1/chat/completions` 格式，并复用 `VLLM_API_KEY`：

| model | 行为 |
| --- | --- |
| `vision-ocr` | 只执行 OCR，返回文字、置信度、框坐标及可识别的固定结构 |
| `vision-hybrid` | 先 OCR，再把原图和 OCR 原文一起交给 Qwen |
| `vision-auto` | 明确的文字/坐标/议程请求走 OCR，其余走混合分析 |
| `qwen3-vl-4b` | 原样代理到现有 Qwen 服务 |

同一测试图通过常驻网关实测：自动 OCR 总耗时 1.503 s；混合分析总耗时
5.414 s，其中 OCR 1.378 s、Qwen 输出 50 tokens；Qwen 纯文本直通
0.551 s，SSE 流式响应正常。OCR 与混合模式默认只接受 base64 data URI，
避免网关成为不受限制的远程 URL 获取器。

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
