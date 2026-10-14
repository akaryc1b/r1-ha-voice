# 备份与回退

## GitHub 公开备份的边界

仓库保留当前安装方法、R1 构建记录、自有源码、构建/覆盖安装工具、模型与镜像来源校验值、MA 补丁、AirPlay 依赖清单与核对工具、HA 配置样例和验证结果。

不提交以下内容：

- `gateway.private.json`、`provider.private.json`、MA 授权文件、真实 API key。
- HA 的长期访问令牌、`secrets.yaml`、`.storage`、用户账户和设备配置数据库。
- Apple Music 账户授权、Cookie、CDM 私钥/设备授权资料。
- SSH 私钥、密码、用户录音、完整现场日志与原始私密网页快照。
- 完整 Docker 镜像和 N1 整盘文件。

因此 GitHub 备份可以恢复程序和安装流程，**不能自动恢复个人登录授权与整套 HA 数据**。公开配置中的实体和 IP 仍需按部署环境调整。

仓库不包含 APK、模型、运行库或 Docker 镜像二进制；这些安装素材与账号配置另存本地。

## 个人配置另存本地

当前部署应另行备份：

| 位置 | 内容 |
| --- | --- |
| N1 MA `/data` 对应的宿主目录 | MA 设置、授权、队列/音乐库数据库与供应商所需资料 |
| `/data/r1-cloud-voice/gateway.private.json` | 本轮统一网关配置及密钥 |
| 旧 `provider.private.json` / `ma-authorization.private` | 保留的迁移来源 |
| HA `/config` | `configuration.yaml`、packages、`.storage`、授权文件、中文语法与面板 |
| R1 `/sdcard/r1-local-asr.json` | 网关、识别、播报和通道配置 |
| R1 应用自身用户数据 | 原有 HA/AI 参数、唤醒词等；覆盖安装不会主动清除 |
| OpenWrt 两个 `/etc/init.d/r1-*` 服务 | 实际路径与本地 ASR 参数 |

使用 HA 自带备份或在停止相关容器后备份数据目录，以得到一致的数据库快照。私密备份保存到仓库外，不要通过关闭 `.gitignore` 强行上传。

## 回退网页/语音客户端

1. 保留当前设备配置和旧 APK。
2. 对相同包名/签名的已知可用 APK 执行覆盖安装；不要卸载再安装。
3. 只在确实需要时恢复 `/sdcard/r1-local-asr.json`，避免覆盖更新后的地址或唤醒词。

本次升级前的源文件与设备配置留在本地开发备份 `configurable-voice/before/`，不公开上传私密文件。源 APK 允许清单见 `device/base-apk.json`；新 APK 校验值以本地生成的 `device/build/build-report.json` 为准。

## 回退网关

升级前自行保留旧网关源码与配置。统一配置保存时会留 `gateway.previous.private.json`。

先停止 `/etc/init.d/r1-cloud-voice`，恢复匹配的一组 `voice_gateway.py`、`gateway_config.py` 和配置，再启动该服务。旧网关可能不识别新字段；不要混用半套版本。HA 不需要因此重装或删除。

## 核对与恢复 MA

在现有 MA 容器中核对六个优化文件：

```sh
docker exec r1-apple-music python /data/r1-cloud-voice/maintain_ma_optimizations.py --check
```

`--apply` 重装匹配的优化，`--restore` 恢复备份的原始六个源码文件。写入前全部校验哈希，未知源码会拒绝覆盖；修改后需要重启现有 MA 容器。

官方 AirPlay 缺失文件单独核对：

```sh
docker exec r1-apple-music python /data/r1-cloud-voice/airplay-restoration/maintain_airplay_provider.py
```

该工具需要本机已有的同版本恢复归档（公开仓库不含归档）；其 `--apply` 只恢复匹配版本的缺失文件，遇到已存在但内容不同的文件会停止。不会从 HA Alpine 复制二进制依赖到 MA Debian。

普通容器重启会保留其可写层内的源码修改；**删除重建或升级镜像会丢失这些修改**，需从持久数据中的维护包重新核对恢复。MA 版本升级后，不能直接把 2.10.6 的旧源码覆盖过去。

恢复 HA 配置应合并原有配置与授权文件，不通过复制仓库目录覆盖整个 `/config`。电脑控制的 SSH 私钥和主机校验信息需从自己的私密备份恢复。
