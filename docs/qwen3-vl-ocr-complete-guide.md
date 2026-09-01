# Qwen3-VL 与 OCR 统一识图平台保姆级教程

## 1. 文档目标

本文是一份可独立转发的完整使用和维护手册，覆盖：

- OCR、Qwen 和混合识图分别适合什么场景；
- 如何用 Linux、Windows PowerShell、Python 和 OpenAI SDK 调用；
- 如何提取文字、置信度和坐标；
- OpenAI 请求字段、OCR 命令行参数、Qwen 运行参数的含义；
- 如何从零部署 OCR、Qwen 和统一网关；
- 如何检查服务、分析慢请求、处理 401/超时/识别错误；
- 如何升级、停用和回退。

当前实机地址：

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| 统一识图网关 | `http://192.168.16.220:8001/v1` | 推荐调用入口 |
| 原生 Qwen/vLLM | `http://192.168.16.220:8000/v1` | 仅直接调用 Qwen 时使用 |
| 网关健康检查 | `http://192.168.16.220:8001/health` | 同时检查 OCR 和 Qwen |
| Qwen 健康检查 | `http://192.168.16.220:8000/health` | 只检查 vLLM |

API Key 不在本文记录。调用方从管理员处获取后，以环境变量或密钥管理工具保存，
不要写进代码仓、截图、聊天记录或文档。

## 2. 先理解三种能力

### 2.1 OCR

OCR 负责从图片中读取：

- 中文、英文、数字、型号和序列号；
- 每行文字的四点框坐标；
- 每行识别置信度；
- 按页面从上到下的文字顺序；
- 已适配固定结构，例如会议议程。

OCR 不理解无文字图标、颜色含义、设备照片、拓扑关系和整体语义。

### 2.2 Qwen3-VL

Qwen3-VL 负责理解：

- 图片是什么场景；
- 图标、颜色、状态和位置关系；
- 页面是否存在异常；
- 图表、照片、拓扑图表达的含义；
- 根据图片生成总结或操作建议。

Qwen 对姓名、长型号和密集小字可能出现单字误识，而且输出 token 越多，耗时
越长。

### 2.3 OCR + Qwen

混合模式先用 OCR 固定精确文字，再把原图和 OCR 原文一起交给 Qwen。这样：

- 姓名、型号和数字优先采用 OCR；
- 图标、颜色和关系由 Qwen 理解；
- 比只用 Qwen 更适合 BMC 页面、告警截图和运维界面。

## 3. 四个可用模型名称

调用统一网关时，通过 `model` 选择执行路径：

| model | 是否调用 OCR | 是否调用 Qwen | 推荐场景 |
| --- | --- | --- | --- |
| `vision-ocr` | 是 | 否 | 提取文字、坐标、型号、表格、议程 |
| `vision-hybrid` | 是 | 是 | 文字要准确，同时需要理解图片 |
| `vision-auto` | 自动 | 自动 | 调用方不确定如何选择 |
| `qwen3-vl-4b` | 否 | 是 | 照片、图标、场景理解、短总结 |

`vision-auto` 的规则：

- 提示词包含“提取文字、识别文字、文字坐标、会议议程、读取表格、OCR”等意图
  时，只走 OCR；
- 其他图片分析请求走 hybrid；
- 如果业务对执行路径有明确要求，直接指定 `vision-ocr` 或
  `vision-hybrid`，不要依赖自动判断。

## 4. 五分钟快速验证

### 4.1 Linux 设置环境变量

```bash
export VISION_BASE_URL='http://192.168.16.220:8001/v1'
export VISION_API_KEY='<管理员提供的API_KEY>'
```

### 4.2 Windows PowerShell 设置环境变量

```powershell
$env:VISION_BASE_URL = "http://192.168.16.220:8001/v1"
$env:VISION_API_KEY = "<管理员提供的API_KEY>"
```

### 4.3 检查健康状态

Linux：

```bash
curl -fsS http://192.168.16.220:8001/health
```

Windows：

```powershell
curl.exe http://192.168.16.220:8001/health
```

正常返回：

```json
{"status":"ok","ocr":"ready","qwen":"ready"}
```

字段含义：

| 字段 | 含义 |
| --- | --- |
| `status=ok` | OCR 和 Qwen 都可用 |
| `status=degraded` | OCR 可用，但 Qwen 未就绪或异常 |
| `ocr=ready` | OCR 模型已经预加载 |
| `qwen=ready` | `8000/health` 返回成功 |

### 4.4 查看模型列表

Linux：

```bash
curl -fsS "$VISION_BASE_URL/models" \
    -H "Authorization: Bearer $VISION_API_KEY"
```

Windows：

```powershell
curl.exe "$env:VISION_BASE_URL/models" `
    -H "Authorization: Bearer $env:VISION_API_KEY"
```

如果未携带认证信息，预期返回 HTTP 401。

## 5. OpenAI 请求结构

统一入口使用：

```text
POST http://192.168.16.220:8001/v1/chat/completions
```

最常用请求结构：

```json
{
  "model": "vision-hybrid",
  "temperature": 0,
  "max_tokens": 256,
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "image_url",
          "image_url": {
            "url": "data:image/png;base64,<图片BASE64>"
          }
        },
        {
          "type": "text",
          "text": "分析图片中的异常，并保留原始型号和数值"
        }
      ]
    }
  ]
}
```

### 5.1 常用请求参数

| 参数 | 类型 | 推荐值 | 含义 |
| --- | --- | --- | --- |
| `model` | 字符串 | 见模型表 | 选择 OCR、hybrid、auto 或 Qwen |
| `messages` | 数组 | 必填 | 对话消息，图片和提示词放在 user content 中 |
| `temperature` | 数值 | `0` | 0 更稳定，适合运维和结构化输出 |
| `max_tokens` | 整数 | `64～512` | 最大输出 token 数，越大可能越慢 |
| `stream` | 布尔 | `true/false` | 是否使用 SSE 流式返回 |
| `top_p` | 数值 | 通常省略 | 采样范围；确定性任务不建议单独调整 |
| `chat_template_kwargs` | 对象 | 可选 | 可传 `{"enable_thinking":false}` |
| `router_mode` | 字符串 | 可选 | 覆盖 model 路由，通常不需要 |

`timeout` 不是服务端 JSON 字段，而是客户端等待时间。首次 Qwen 服务启动可能
需要 3～5 分钟，普通请求建议客户端超时设置为 120～300 秒。

### 5.2 图片字段

OCR 和 hybrid 默认接受：

```text
data:image/png;base64,...
data:image/jpeg;base64,...
data:image/webp;base64,...
data:image/bmp;base64,...
```

默认限制：

| 项目 | 默认值 |
| --- | ---: |
| 完整请求体 | 32 MiB |
| 解码后的单张图片 | 20 MiB |
| 远程 HTTP 图片 URL | 禁用 |

远程 URL 默认关闭是为了防止网关成为任意 URL 访问器。建议调用方把本地图片转
成 Base64 data URI。

## 6. Python 完整调用示例

下面脚本只使用 Python 标准库，不需要安装第三方包。

```python
import base64
import json
import os
import time
import urllib.request

BASE_URL = os.getenv("VISION_BASE_URL", "http://192.168.16.220:8001/v1")
API_KEY = os.environ["VISION_API_KEY"]


def image_to_data_url(path: str) -> str:
    suffix = path.lower().rsplit(".", 1)[-1]
    mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
    with open(path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("ascii")
    return f"data:image/{mime};base64,{encoded}"


def analyze_image(path: str, model: str, prompt: str, max_tokens: int = 256):
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": image_to_data_url(path)},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    request = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=300) as response:
        body = json.load(response)
    print(f"耗时: {time.monotonic() - started:.3f}s")
    print(f"实际路由: {body.get('router', {}).get('route')}")
    return body


result = analyze_image(
    "test.png",
    "vision-hybrid",
    "分析图片中的异常，型号、姓名和数值必须保留原文",
    256,
)
print(result["choices"][0]["message"]["content"])
```

只识别文字和坐标时改为：

```python
result = analyze_image(
    "test.png",
    "vision-ocr",
    "提取全部文字和坐标",
    64,
)
```

## 7. OpenAI Python SDK 示例

安装 SDK：

```bash
python3 -m pip install openai
```

调用：

```python
import base64
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["VISION_API_KEY"],
    base_url=os.getenv("VISION_BASE_URL", "http://192.168.16.220:8001/v1"),
)

with open("test.png", "rb") as image_file:
    encoded = base64.b64encode(image_file.read()).decode("ascii")

response = client.chat.completions.create(
    model="vision-auto",
    temperature=0,
    max_tokens=256,
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{encoded}",
                    },
                },
                {
                    "type": "text",
                    "text": "提取全部文字和坐标",
                },
            ],
        }
    ],
)

print(response.choices[0].message.content)
```

注意：顶层 `router` 是网关扩展字段，部分 OpenAI SDK 版本不会直接映射为属性。
需要完整扩展字段时，可使用标准库、`requests`，或读取 SDK 的原始响应。

## 8. Windows PowerShell 完整示例

```powershell
$BaseUrl = "http://192.168.16.220:8001/v1"
$ApiKey = $env:VISION_API_KEY
$ImagePath = "C:\Temp\test.png"

$ImageBytes = [System.IO.File]::ReadAllBytes($ImagePath)
$ImageBase64 = [Convert]::ToBase64String($ImageBytes)
$DataUrl = "data:image/png;base64,$ImageBase64"

$Body = @{
    model = "vision-ocr"
    temperature = 0
    max_tokens = 64
    messages = @(
        @{
            role = "user"
            content = @(
                @{
                    type = "image_url"
                    image_url = @{
                        url = $DataUrl
                    }
                },
                @{
                    type = "text"
                    text = "提取全部文字和坐标"
                }
            )
        }
    )
} | ConvertTo-Json -Depth 10 -Compress

$Headers = @{
    Authorization = "Bearer $ApiKey"
}

$Result = Invoke-RestMethod `
    -Uri "$BaseUrl/chat/completions" `
    -Method Post `
    -Headers $Headers `
    -ContentType "application/json; charset=utf-8" `
    -Body ([Text.Encoding]::UTF8.GetBytes($Body)) `
    -TimeoutSec 300

$Result.choices[0].message.content
```

如果出现中文乱码，确认 `Body` 使用 UTF-8 字节发送，不要依赖旧版 PowerShell
默认编码。

## 9. 流式响应

Qwen 和 hybrid 支持 SSE。OCR 的流式模式会一次性返回完整 OCR JSON，然后
发送 `[DONE]`。

Python SDK：

```python
stream = client.chat.completions.create(
    model="qwen3-vl-4b",
    stream=True,
    max_tokens=128,
    messages=[
        {"role": "user", "content": "用三句话说明服务器BMC的作用"}
    ],
)

for chunk in stream:
    text = chunk.choices[0].delta.content
    if text:
        print(text, end="", flush=True)
print()
```

流式输出只改善“用户多久看到第一段文字”，不会减少生成全部 token 所需的总
算力。

## 10. OCR 返回值与坐标解析

OCR 模式仍使用 OpenAI 外层响应，但
`choices[0].message.content` 是一个 JSON 字符串，需要再解析一次。

简化结构：

```json
{
  "engine": "RapidOCR-3.9.2/PP-OCRv6-small",
  "elapsed_seconds": 1.5,
  "batch_size": 16,
  "image_size": {"width": 957, "height": 877},
  "line_count": 29,
  "lines": [
    {
      "text": "主讲人：张三",
      "score": 0.998,
      "box": [[70, 143], [206, 145], [205, 173], [70, 170]]
    }
  ],
  "structured": {
    "type": "agenda",
    "items": []
  }
}
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `text` | OCR 识别文字 |
| `score` | 0～1 置信度，越高越可靠 |
| `box` | 左上、右上、右下、左下四点坐标 |
| `image_size` | 原图宽高，坐标基于原图 |
| `structured` | 已支持的规则化结构，例如 agenda |

解析和计算中心点：

```python
import json

outer = result
ocr = json.loads(outer["choices"][0]["message"]["content"])

for line in ocr["lines"]:
    points = line["box"]
    center_x = round(sum(point[0] for point in points) / len(points))
    center_y = round(sum(point[1] for point in points) / len(points))
    print(line["text"], line["score"], center_x, center_y)
```

OCR 坐标只对应文字区域。无文字图标、复选框和图片按钮需要 DOM、模板匹配、
UI 检测模型或 Qwen 视觉分析。

## 11. 提示词模板

### 11.1 精确 OCR

```text
提取图片中的全部文字、数字、型号和序列号，保持原始顺序并返回坐标。
```

模型选择：`vision-ocr`。

### 11.2 BMC 告警截图

```text
分析这张BMC告警截图。精确文字以OCR结果为准，同时说明告警对象、严重度、
可能原因和建议检查项。不要把未显示的内容当成事实。
```

模型选择：`vision-hybrid`。

### 11.3 页面按钮定位

```text
提取页面中的文字和坐标，找出“保存”按钮对应文字框，不执行点击。
```

模型选择：`vision-ocr`。如果按钮只有图标，改用 `vision-hybrid`。

### 11.4 设备照片

```text
说明照片中有哪些服务器部件、连接关系和可见异常。无法确认的部分明确标注不确定。
```

模型选择：`qwen3-vl-4b` 或 `vision-hybrid`。

### 11.5 强制短输出

```text
只用一句话总结，不超过50个汉字。
```

减少输出 token 通常比增加并行卡更直接地降低单请求总耗时。

## 12. 本地 OCR 命令行工具

OCR 环境：

```text
/opt/rapidocr-bench/venv
```

脚本：

```text
/opt/rapidocr-bench/ocr-first-analyze.py
```

### 12.1 OCR 原始文字和坐标

```bash
/opt/rapidocr-bench/venv/bin/python \
    /opt/rapidocr-bench/ocr-first-analyze.py test.png \
    --mode ocr
```

### 12.2 会议议程规则整理

```bash
/opt/rapidocr-bench/venv/bin/python \
    /opt/rapidocr-bench/ocr-first-analyze.py test.png \
    --mode rules \
    --profile agenda
```

### 12.3 OCR 后调用 Qwen 文本整理

```bash
export VISION_API_KEY='<API_KEY>'

/opt/rapidocr-bench/venv/bin/python \
    /opt/rapidocr-bench/ocr-first-analyze.py test.png \
    --mode hybrid \
    --profile generic \
    --url http://127.0.0.1:8000/v1/chat/completions
```

这种 CLI hybrid 只把 OCR 文本交给 Qwen，不发送原图。对于需要图标和颜色理解
的场景，应调用 `8001` 的 `vision-hybrid`。

### 12.4 CLI 参数表

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `image` | 必填 | 本地图片路径 |
| `--mode` | `ocr` | `ocr`、`rules` 或 `hybrid` |
| `--profile` | `generic` | `generic` 或 `agenda` |
| `--url` | `127.0.0.1:8000` | hybrid 使用的 Qwen 地址 |
| `--api-key` | 环境变量 | 也可使用 `VISION_API_KEY` |
| `--model` | `qwen3-vl-4b` | 上游模型名 |
| `--max-tokens` | `384` | Qwen 最大输出 token |
| `--min-score` | `0.5` | OCR 最低保留置信度 |
| `--ocr-batch-size` | `16` | OCR 分类/识别批量 |
| `--timeout` | `300` | Qwen 请求超时秒数 |

`ocr-batch-size=16` 是当前 29 行测试图的最优实测值。其他 CPU 或超长页面应
重新测试，不要认为数值越大一定越快。

## 13. 双区域并行工具

`dual-region-analyze.py` 把图片裁为上下两个有重叠的区域，并发调用两个 Qwen
DP 副本。它适合 Qwen 长输出容易被截断、但又不能只用 OCR 的情况。

```bash
export VISION_API_KEY='<API_KEY>'

python3 dual-region-analyze.py test.png \
    --url http://192.168.16.220:8000/v1/chat/completions \
    --profile agenda \
    --max-tokens 512 \
    --overlap 0.2
```

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--profile` | `generic` | 通用或议程输出格式 |
| `--max-tokens` | `512` | 每个区域最大输出 token |
| `--overlap` | `0.2` | 两个裁剪区域垂直重叠比例 |
| `--timeout` | `300` | 单请求超时 |

纯文字页面优先使用 OCR。双区域 Qwen 仍可能对姓名和型号产生冲突。

## 14. 从零部署 OCR

openEuler ARM64 示例：

```bash
install -d -m 0755 /opt/rapidocr-bench
python3 -m venv /opt/rapidocr-bench/venv
/opt/rapidocr-bench/venv/bin/pip install \
    -i https://mirrors.huaweicloud.com/repository/pypi/simple \
    rapidocr==3.9.2 onnxruntime==1.29.0

/opt/rapidocr-bench/venv/bin/pip uninstall -y opencv-python
/opt/rapidocr-bench/venv/bin/pip install \
    -i https://mirrors.huaweicloud.com/repository/pypi/simple \
    opencv-python-headless==5.0.0.93
```

使用 headless OpenCV 是为了避免服务器额外安装 `libGL.so.1` 和桌面图形库。

验证：

```bash
/opt/rapidocr-bench/venv/bin/python -c \
    'from rapidocr import RapidOCR; print("RapidOCR import OK")'
```

安装命令行客户端：

```bash
install -m 0755 ocr-first-analyze.py /opt/rapidocr-bench/
```

## 15. 从零部署 Qwen3-VL

### 15.1 前置检查

```bash
npu-smi info
docker version
```

当前混合部署中，Guest 应看到两颗物理 `310P3`，不是 `310Pvir04`：

```text
/dev/davinci0
/dev/davinci1
```

Guest 驱动模式必须为：

```bash
grep '^Driver_Install_Mode=' /etc/ascend_install.info
# Driver_Install_Mode=normal
```

### 15.2 目录

```text
/srv/models/Qwen3-VL-4B-Instruct-w8a8sc-310-vllm-tp1
/opt/vision-qwen3vl
/etc/vision-qwen3vl/runtime.env
/var/cache/vision-qwen3vl
```

本仓库不分发模型权重、厂商驱动或容器层。必须从授权渠道取得，并记录版本、
来源和 SHA-256。

### 15.3 构建和安装运行文件

在 `examples/qwen3-vl-310p` 目录中执行：

```bash
docker build -t local/vllm-ascend:qwen3vl-0.23.0-310p .

install -d -m 0755 /opt/vision-qwen3vl /var/cache/vision-qwen3vl
install -m 0755 run-container.sh start-vllm.sh wait-for-npu.sh \
    /opt/vision-qwen3vl/

install -d -m 0750 /etc/vision-qwen3vl
install -m 0600 runtime.env.example /etc/vision-qwen3vl/runtime.env
install -m 0644 vision-qwen3vl.service /etc/systemd/system/
```

确认 `run-container.sh` 中的宿主模型目录与实际路径一致。当前脚本默认：

```text
/srv/models/Qwen3-VL-4B-Instruct-w8a8sc-310-vllm-tp1
```

### 15.4 运行参数文件

当前实机主要参数：

```text
MODEL_PATH=/models/qwen3vl
SERVED_MODEL_NAME=qwen3-vl-4b
PORT=8000
MAX_MODEL_LEN=8192
MAX_NUM_SEQS=4
GPU_MEMORY_UTILIZATION=0.85
ASCEND_RT_VISIBLE_DEVICES=0,1
TENSOR_PARALLEL_SIZE=1
DATA_PARALLEL_SIZE=2
API_SERVER_COUNT=1
LOAD_FORMAT=sharded_state
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
VLLM_API_KEY=<随机密钥>
GLOO_SOCKET_IFNAME=lo
VLLM_ENGINE_READY_TIMEOUT_S=1800
VLLM_EXECUTE_MODEL_TIMEOUT_SECONDS=3000
VLLM_EXECUTION_MODE=graph
```

权限：

```bash
chmod 0600 /etc/vision-qwen3vl/runtime.env
```

### 15.5 Qwen 运行参数说明

| 参数 | 当前值 | 含义和调整影响 |
| --- | --- | --- |
| `MODEL_PATH` | `/models/qwen3vl` | 容器内模型路径 |
| `SERVED_MODEL_NAME` | `qwen3-vl-4b` | API 暴露的模型名 |
| `PORT` | `8000` | vLLM 监听端口 |
| `MAX_MODEL_LEN` | `8192` | 最大上下文长度；越大 KV cache 需求越高 |
| `MAX_NUM_SEQS` | `4` | 每个引擎允许的并发序列上限 |
| `GPU_MEMORY_UTILIZATION` | `0.85` | NPU 内存使用目标比例 |
| `ASCEND_RT_VISIBLE_DEVICES` | `0,1` | 容器可见的两颗物理芯片 |
| `TENSOR_PARALLEL_SIZE` | `1` | 当前 TP1 权重不能直接改成 TP2 |
| `DATA_PARALLEL_SIZE` | `2` | 两份完整模型副本，提高并发吞吐 |
| `API_SERVER_COUNT` | `1` | 对外 API 进程数量 |
| `LOAD_FORMAT` | `sharded_state` | 当前量化权重格式 |
| `HF_HUB_OFFLINE` | `1` | 禁止运行时访问 Hugging Face |
| `TRANSFORMERS_OFFLINE` | `1` | Transformers 离线模式 |
| `VLLM_API_KEY` | 随机值 | API Bearer 认证密钥 |
| `GLOO_SOCKET_IFNAME` | `lo` | 本机 DP 协调接口 |
| `VLLM_EXECUTION_MODE` | `graph` | 使用 FULL_DECODE_ONLY Graph |

DP2 的含义是两颗芯片各运行一份完整模型。它提高并发吞吐，不会把同一个 token
拆给两颗芯片共同计算。

启动脚本中的固定 vLLM 参数：

| vLLM 参数 | 当前值 | 说明 |
| --- | --- | --- |
| `--dtype` | `float16` | 运行时非量化张量的数据类型 |
| `--quantization` | `ascend` | 使用 Ascend 量化加载路径 |
| `--max-num-batched-tokens` | `4096` | 单轮调度最大批量 token |
| `--trust-remote-code` | 开启 | 允许模型目录中的自定义实现 |
| `--no-enable-prefix-caching` | 开启 | 当前关闭前缀缓存 |
| `--limit-mm-per-prompt` | `image=4, video=0` | 单请求最多 4 张图片，禁用视频 |
| `--mm-processor-cache-gb` | `0` | 不单独预留多模态处理缓存 |
| `--compilation-config` | `FULL_DECODE_ONLY` | 只捕获 decode Graph |
| `cudagraph_capture_sizes` | `[1,2,4]` | 为 1、2、4 批大小捕获 Graph |
| `enable_npugraph_ex` | `false` | 310P 不支持该后端 |
| `fuse_norm_quant` | `false` | 使用当前 310P 已验证路径 |

这些参数与模型格式、vLLM Ascend、CANN 和 310P 硬件相关。没有回归数据时不要
只为追求速度修改量化、Graph 或融合参数。

### 15.6 启动

```bash
systemctl daemon-reload
systemctl enable --now vision-qwen3vl.service
```

首次启动通常需要 3～5 分钟，期间包括：

- 两份权重加载；
- 视觉编码器 warmup；
- torch.compile；
- FULL_DECODE_ONLY Graph 捕获；
- KV cache 初始化。

以健康检查为准，不要只看进程存在：

```bash
curl -f http://127.0.0.1:8000/health
```

## 16. 从零部署统一网关

安装目录：

```bash
install -d -m 0755 /opt/vision-router
install -m 0755 vision-router.py /opt/vision-router/
install -m 0644 vision-router.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now vision-router.service
```

网关复用 `/etc/vision-qwen3vl/runtime.env` 中的 `VLLM_API_KEY`，不需要再保存
第二份密钥。

### 16.1 网关环境参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `ROUTER_HOST` | `0.0.0.0` | 监听地址 |
| `ROUTER_PORT` | `8001` | 网关端口 |
| `QWEN_UPSTREAM_URL` | `127.0.0.1:8000/...` | Qwen 上游接口 |
| `QWEN_UPSTREAM_HEALTH_URL` | `127.0.0.1:8000/health` | Qwen 健康检查 |
| `QWEN_UPSTREAM_MODEL` | `qwen3-vl-4b` | 上游模型名 |
| `OCR_BATCH_SIZE` | `16` | OCR 分类和识别批量 |
| `OCR_MIN_SCORE` | `0.5` | 低于此置信度的文字行不返回 |
| `QWEN_UPSTREAM_TIMEOUT` | `300` | 上游请求超时秒数 |
| `MAX_REQUEST_BYTES` | `32 MiB` | 完整请求限制 |
| `MAX_IMAGE_BYTES` | `20 MiB` | Base64 解码后图片限制 |
| `ALLOW_REMOTE_IMAGE_URLS` | `0` | 是否允许网关主动下载 URL |

## 17. 当前性能与资源开销

当前硬件为一张 Atlas 300I Duo 整卡直通，卡内两颗物理 310P3 运行 DP2。

| 用例 | 实测结果 |
| --- | ---: |
| OCR 29 行文字 | 约 1.5～1.8 s |
| OCR + Qwen 约 50 tokens 简短分析 | 4.576 s |
| Qwen 295 completion tokens | 9.341 s |
| Qwen 单流端到端输出率 | 约 31.6 tokens/s |
| 两个 295-token 请求并发 | 10.609 s |
| 双并发聚合输出率 | 约 55.6 tokens/s |

资源特征：

- OCR 常驻约 200～250 MiB 系统内存，推理时使用 CPU，不占 NPU；
- Qwen DP2 常驻约 25 GiB Guest 系统内存；
- 两颗物理 NPU 各加载一份约 6.77 GB 权重，并分配 KV cache；
- 空闲时 AI Core 利用率接近 0，但模型和 KV cache 仍常驻内存；
- 本地部署不产生外部 API 按 token 计费。

## 18. 如何选择最快方案

| 需求 | 推荐 |
| --- | --- |
| 只读文字、型号、坐标 | `vision-ocr` |
| 固定议程或表单 | OCR + 本地规则 |
| BMC 页面告警分析 | `vision-hybrid` |
| 实物照片和无文字图标 | `qwen3-vl-4b` |
| 不确定 | `vision-auto` |
| 页面有 DOM/无障碍树 | 优先 DOM，不要先截图识别 |

降低延迟的优先顺序：

1. 不需要语义时不要调用 Qwen；
2. 限制输出长度；
3. 裁剪到真正需要分析的区域；
4. 开启流式输出改善首字等待；
5. 多请求并发利用 DP2；
6. 不要为了单请求延迟盲目增加 DP 副本。

## 19. 服务维护

### 19.1 查看状态

```bash
systemctl status vision-qwen3vl.service
systemctl status vision-router.service
```

### 19.2 查看日志

```bash
journalctl -u vision-qwen3vl.service -b --no-pager
journalctl -u vision-router.service -b --no-pager
docker logs --tail 200 vision-qwen3vl
```

### 19.3 查看 NPU

```bash
npu-smi info
```

### 19.4 重启顺序

```bash
systemctl restart vision-qwen3vl.service
systemctl restart vision-router.service
```

如果只修改 OCR 网关代码，不需要重启 Qwen：

```bash
systemctl restart vision-router.service
```

### 19.5 停止 Qwen 但保留 OCR

```bash
systemctl stop vision-qwen3vl.service
systemctl restart vision-router.service
```

此时 `vision-ocr` 仍可工作，`/health` 会显示 `status=degraded`、
`qwen=unavailable`。`vision-hybrid` 和 Qwen 直通不可用。

## 20. 常见故障排查

### 20.1 HTTP 401

原因：API Key 缺失、拼写错误或多了空格。

检查：

```bash
curl "$VISION_BASE_URL/models" \
    -H "Authorization: Bearer $VISION_API_KEY"
```

请求头必须是：

```text
Authorization: Bearer <API_KEY>
```

### 20.2 Connection refused

```bash
systemctl status vision-router.service
ss -lntp | grep 8001
```

如果 `8000` 不通但 `8001` 可用，OCR 可能仍可工作。

### 20.3 `/health` 为 degraded

```bash
systemctl status vision-qwen3vl.service
docker logs --tail 200 vision-qwen3vl
curl -v http://127.0.0.1:8000/health
```

服务刚启动时等待 3～5 分钟属于正常现象。

### 20.4 图片过大

现象：HTTP 413 或提示超过大小限制。

处理：

- 裁剪无关区域；
- 使用 JPEG/WebP；
- 降低分辨率，但保留小字可读性；
- 不要仅为绕过限制而无限提高服务端上限。

### 20.5 remote image URLs are disabled

把 URL 图片先下载到调用端，再转换为 Base64 data URI。除非网络范围完全受控，
否则不建议启用 `ALLOW_REMOTE_IMAGE_URLS=1`。

### 20.6 OCR 有错字或连字

常见情况：

- `2000 2.5` 被识别为 `20002.5`；
- 极小字体、压缩图、反色和低对比度文字；
- 生僻姓名或特殊符号。

处理顺序：

1. 使用原图，不要先缩小；
2. 裁剪目标区域并适度放大；
3. 查看 `score`，只复核低置信度行；
4. 型号使用业务词典或正则校验；
5. 不要让 Qwen 无依据地改写精确字符串。

### 20.7 Qwen 输出被截断

现象：`finish_reason=length`。

处理：

- 增加 `max_tokens`；
- 要求更紧凑输出；
- 长图片使用 OCR 或双区域并发；
- 不要用超长自然语言重复图片中的全部文字。

### 20.8 Qwen 请求慢

先区分：

- TTFT：首 token 等待；
- decode：输出 token 数除以 tokens/s；
- OCR：通常约 1.5 秒；
- 服务启动：可能需要 3～5 分钟。

查看 vLLM 指标：

```bash
curl http://127.0.0.1:8000/metrics | \
    grep -E 'time_to_first_token|inter_token_latency|request_decode_time'
```

当前单流约 31 tokens/s。输出 300 tokens 本身就需要接近 10 秒，不应只按整卡
纸面 TOPS 推算。

### 20.9 OCR 正常但 Qwen 不可用

使用 `vision-ocr` 继续提供文字服务，同时检查：

```bash
npu-smi info
systemctl status vision-qwen3vl.service
docker logs --tail 200 vision-qwen3vl
```

### 20.10 NPU 设备节点缺失

当前物理卡 Guest 应存在：

```text
/dev/davinci0
/dev/davinci1
/dev/davinci_manager
/dev/devmm_svm
/dev/hisi_hdc
```

并确认：

```bash
grep '^Driver_Install_Mode=' /etc/ascend_install.info
# normal
```

此问题属于驱动或 VFIO 层，不是 API 参数问题。

## 21. 安全要求

- 当前接口是内网明文 HTTP，不应直接暴露到互联网；
- API Key 文件权限应为 0600；
- 不把真实密钥写入 Git、Markdown、截图和脚本示例；
- 不默认允许服务端下载任意 URL；
- 生产调用记录中避免保存含客户隐私的原始图片；
- 对图片上传大小、并发数和客户端超时设置上限；
- 需要跨不可信网络时，在网关前增加 HTTPS 反向代理和访问控制。

## 22. 升级与回退

升级前保存：

- 当前容器镜像标签和 digest；
- 模型目录和 SHA-256；
- `/etc/vision-qwen3vl/runtime.env`；
- `/opt/vision-qwen3vl`、`/opt/vision-router`；
- systemd 单元；
- 当前 OCR 包版本；
- 一组固定测试图片和期望结果。

推荐升级顺序：

1. 保留原镜像和配置；
2. 在新标签中构建，不覆盖原标签；
3. 先验证 `/health` 和 `/v1/models`；
4. 验证 OCR 文字、坐标和置信度；
5. 验证 Qwen 图片理解、短文本和流式输出；
6. 对比单请求和双并发性能；
7. 通过后再切换 systemd 配置。

回退网关：

```bash
systemctl disable --now vision-router.service
```

停用网关不会修改原 `8000` Qwen 服务。恢复：

```bash
systemctl enable --now vision-router.service
```

## 23. 最终验收清单

```text
[ ] 8001/health 返回 status=ok
[ ] 未认证访问 /v1/models 返回 401
[ ] 认证后可看到四个模型名
[ ] vision-ocr 能返回文字、score 和 box
[ ] vision-auto 的文字请求实际 route=ocr
[ ] vision-hybrid 同时返回 OCR 行数和 Qwen 结果
[ ] qwen3-vl-4b 直通成功
[ ] stream=true 能收到 [DONE]
[ ] OCR 固定图片行数和坐标无明显回退
[ ] Qwen 固定图片结果和耗时无明显回退
[ ] systemd 服务均 enabled/active
[ ] npu-smi 两颗物理芯片 Health OK
[ ] 文档和脚本中没有真实 API Key
```

## 24. 常用命令速查

```bash
# 健康检查
curl http://192.168.16.220:8001/health

# 模型列表
curl http://192.168.16.220:8001/v1/models \
    -H "Authorization: Bearer $VISION_API_KEY"

# 服务状态
systemctl status vision-qwen3vl.service
systemctl status vision-router.service

# 服务日志
journalctl -u vision-qwen3vl.service -b --no-pager
journalctl -u vision-router.service -b --no-pager
docker logs --tail 200 vision-qwen3vl

# NPU 状态
npu-smi info

# 端口
ss -lntp | grep -E ':8000|:8001'

# 当前模型参数
sed -E '/KEY|TOKEN|PASSWORD|SECRET/d' /etc/vision-qwen3vl/runtime.env
```

普通调用方只需要阅读第 2～11 节；运维和部署人员再阅读第 12～24 节。
