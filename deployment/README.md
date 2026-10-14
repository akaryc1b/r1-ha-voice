# 可选独立语音容器

此目录是另行部署 gateway + 本地 Sherpa 断句服务的可选入口。**没有迁移、替换当前 N1 的两个容器，也不包含 HA、MA、Snapcast 或 R1 APK。** 当前 N1 的 16066/16068 已由原服务占用，不能同时启动本容器。已有部署可继续使用 `services/` 与 `asr/server_launcher.py`。

镜像使用 Debian trixie glibc，直接运行 Sherpa 1.13.8；无需挂载宿主 compat/glibc、Docker socket 或设备节点。提供 `linux/arm64` 与 `linux/amd64` 的运行时选择，来源与 SHA256 统一在 [asr/sources.json](../asr/sources.json)。ARM64 与 x64 官方资产命名不同，不能互换。

## 前置条件与网络

- 目标为 Linux Docker Engine + Compose v2。Windows/macOS Docker Desktop 需另行启用其 host networking 功能，不能直接把本机 Windows 测试视为 Linux 容器验证。
- 使用 `network_mode: host`，本地 ASR 保留 16066、网关默认 16068；host 模式不填写 `ports:`。确认目标机器这两个端口空闲后再启动。
- 运行时只绑定可信家庭网络。Sherpa 1.13.8 server 没有本方案可用的监听地址/鉴权参数，16066 会监听宿主网络；网关沿用 `allowed_clients`。不要把端口映射到公网。
- R1 的配置页面仍在 **R1 自己的 `:8080`**。令其网关地址指向新主机的 `:16068`，原 `/config`、`/asr`、`/tts`、`/logs` 协议保持不变。容器不提供第二个 8080 页面。
- `127.0.0.1:8095` 仅在 MA 也位于同一宿主机时正确。远端 MA、R1 地址和逻辑队列应改为实际值，示例并不自动发现设备。

Docker 的 [host 网络规则](https://docs.docker.com/engine/network/drivers/host/)说明其共享宿主网络并忽略端口映射；[多平台构建说明](https://docs.docker.com/build/building/multi-platform/)说明非本机架构需要可用的仿真或原生 builder。

## 构建、显式下载与启动

以下命令从仓库根目录运行，只操作本方案的独立 Compose 项目：

```sh
docker compose -f deployment/compose.yaml config --quiet
docker compose -f deployment/compose.yaml build
# 仅此步骤下载四个模型文件，逐项验证 SHA256；不下载测试录音。
docker compose -f deployment/compose.yaml run --rm --no-deps voice bootstrap
docker compose -f deployment/compose.yaml run --rm --no-deps voice verify
# 确认目标端口空闲并完成地址/密钥配置后才启动。
docker compose -f deployment/compose.yaml up -d
docker compose -f deployment/compose.yaml ps
```

镜像构建显式下载所选架构约 28 MB 的固定 Sherpa 运行时；**不把模型塞进镜像，也不在服务启动时自动下载模型**。缺模型或哈希不符时直接失败，并提示先执行 bootstrap。重复 bootstrap 会保留已校验文件；下载失败不会覆盖旧文件。首次模型体积和下载时间取决于上游文件，执行前应准备空间和网络。

模型使用独立 `asr-models` named volume；网页配置及私密日志保存在 `gateway-state` volume `/data`。`down` 会保留 named volumes；不要加 `--volumes`，除非明确决定删除其中的模型和私密配置。备份该卷时按含凭据的私人备份处理。

多架构构建示例（需要已有可用的 multi-platform builder，不发布镜像）：

```sh
docker buildx build --platform linux/arm64,linux/amd64 \
  -f deployment/Dockerfile --output type=oci,dest=/tmp/r1-voice.oci .
```

基础 Python 镜像与 apt 依赖未锁定镜像 digest；需要完整复现时传入审核过的 `--build-arg PYTHON_IMAGE=python:3.12-slim-trixie@sha256:...`。本目录固定了 Sherpa 文件 SHA 与 Python 依赖版本，不宣称整个镜像逐字节可复现。

## 配置和秘密文件

启动入口动态读取 `gateway_config.DEFAULTS`，复用原校验和 `gateway.example.json`。首次将监听地址改为 `0.0.0.0`，ASR 指向容器所在宿主的 `127.0.0.1:16066`；之后保留网页已经保存的配置。显式环境变量在每次启动时覆盖对应字段并持久化，持续设置时会在下次重启覆盖同字段的网页编辑。

普通字段使用 `R1_` 加配置字段大写名，例如 `R1_ASR_MODEL`、`R1_LOCAL_FIRST`、`R1_DEFAULT_RANDOM_PROVIDERS`。字符串直接填写，布尔/数字/列表使用 JSON（例如 `false`、`4`、`["apple_music"]`）。新字段通过已有网关 DEFAULTS 自动支持，不另建一套配置字段。可添加自己的 Compose override 文件：

```yaml
services:
  voice:
    environment:
      R1_ASR_MODEL: TeleAI/TeleSpeechASR
      R1_LOCAL_FIRST: "false"
      R1_ASR_TIMEOUT_SECONDS: "4"
```

基础 compose 提供地址和队列的环境插值；例如宿主环境 `R1_CONTROL_URL` 会被转为网关字段对应的容器变量 `R1_R1_CONTROL_URL`。`allowed_clients` 必须包含 `127.0.0.1`；如果把网关绑定改为特定宿主 IP，还应允许该宿主 IP，以便 healthcheck 访问同一监听地址。

密钥禁止通过 `R1_ASR_API_KEY`、`R1_TTS_API_KEY`、`R1_MA_TOKEN` 直接传入。可在 R1 8080 页面保存，或使用本方案的 `_FILE` 文件机制：

```sh
# 这些变量只保存仓库外文件的路径；不要把秘密值写进命令、.env 或 Git。
export R1_ASR_SECRET_FILE=/secure/r1/asr-key
export R1_TTS_SECRET_FILE=/secure/r1/tts-key
export R1_MA_SECRET_FILE=/secure/r1/ma-token
docker compose -f deployment/compose.yaml -f deployment/compose.secrets.yaml config --quiet
docker compose -f deployment/compose.yaml -f deployment/compose.secrets.yaml up -d
```

secret 文件需让容器 UID/GID `1000:1000` 可读，单文件最多 4096 字节；Compose 本地文件 secret 使用 bind mount，不能依赖 secret 配置里的 UID 映射替你修宿主文件权限。文件内容不会打印，仍按 GatewayConfig 规则持久保存在私密卷中。空密钥文件表示保留旧值；清除使用已有网页的显式清除选项。官方 [Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/)将所授权文件挂在 `/run/secrets/`，`_FILE` 行为由本入口实现。

## 停止、健康与隐私

`init: true` 负责 PID 1 信号转发/子进程回收；入口等待 ASR WebSocket 握手就绪后启动网关。任一子服务退出会终止另一个，再以非零状态退出，交给 `unless-stopped` 重启策略。显式 stop 转发 SIGTERM，等待最多 8 秒后仅终止自己创建的子进程组；Compose 总等待 20 秒。原网关 cleanup 会关闭 HTTP session 与日志线程。

```sh
docker compose -f deployment/compose.yaml stop
```

healthcheck 同时检查两个 PID、ASR 的真实 WebSocket 握手和网关 `/health`。它不发送音频、不转写、不播放、不访问付费云服务。`healthy` 只说明服务可达，不证明云端识别或 R1 声学表现。Docker 不因单纯 `unhealthy` 自动重启；子进程退出由监督器处理，卡住时需根据诊断人工处理。官方 [`init` 说明](https://docs.docker.com/reference/compose-file/services/#init)解释其进程回收作用。

网页结构化日志仍默认关闭，开启后才写 `/data/diagnostic-logs`，沿用容量、脱敏和 generation 栅栏。子服务 stdout/stderr 也沿用原实现，可能包含识别文字；Compose console 日志另限两份各 1 MB，不公开这些日志或卷备份。

## 为什么没有 HA add-on

此仓库已有 HA Container；它不提供 HA OS 的 Apps/add-ons 管理能力。这里是独立 Docker Compose 可选部署，不能把它当成可安装到现有 HA Container 的 add-on。见 [HA 官方安装类型说明](https://www.home-assistant.io/installation/#about-installation-types)。

## 本次验证边界

隔离测试报告由 `tools/run_checks.py gateway` 写入 ignored `reports/`；实际构建和健康结果见 GitHub Actions 的 container 分组。本机没有 Docker CLI/daemon，也没有 WSL Linux 发行版，**没有实际构建镜像、运行 Compose 或验证双架构二进制加载**。

已在 Windows Python 3.10 运行隔离测试：固定来源、模型缺失不联网、显式下载/校验/失败不覆盖、路径逃逸拒绝、GatewayConfig/secret-file、网页配置跨重启、双子进程退出清理、启动超时与健康检查前置条件。另通过官方 Compose JSON Schema 检查两个 YAML，并核对固定 Python 依赖存在 CPython 3.12 的 ARM64/amd64 manylinux wheels。Schema 验证不能代替 `docker compose config` 的插值和实际 runtime 检查。

```sh
python -m unittest discover -s deployment/tests -v
```

目标 Linux/Docker 环境还须执行上面的 config/build/bootstrap/verify/health/stop，并测试实际 SIGTERM、两个架构动态库加载与 R1 8080 桥接。未对当前 N1、HA、MA、队列或音量执行任何部署操作。
