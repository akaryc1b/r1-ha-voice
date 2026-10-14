# R1 客户端构建与安装

日常更换云端 ASR、TTS 音色和接口只需 8080 页面配置。修改设备端代码后，再按本页构建客户端。

## 构建前提

- Python 3.10+、JDK 11、Android SDK Platform 29、Build Tools 29.0.3。
- smali / baksmali 工具由 `device/download_build_tools.py` 按固定 SHA256 下载。
- 自己保存的、匹配 `device/base-apk.json` 输入清单的 R1 APK。

`base-apk.json` 是受版本控制的构建输入契约，包含允许源 APK 的哈希、DEX 前缀和签名条目身份。当前仅支持已验证具有完整初始挂钩的备份。旧 6cd76… APK 缺少这些挂钩，保留来源信息但不作为可构建输入；任意原厂或未知魔改固件不自动兼容。

已有设备可查询并备份安装包：

```sh
adb -s 你的R1地址:5555 shell sh /system/bin/pm path com.phicomm.speaker.device
adb -s 你的R1地址:5555 pull 返回的实际base.apk路径 自己的备份目录/base.apk
```

## 构建

```powershell
python "device\download_build_tools.py"
python "device\build_client.py" --base-apk "自己的匹配备份.apk" --java-home "自己的JDK11目录" --android-sdk "自己的AndroidSDK目录"
```

每次构建使用新的临时工作目录，从已校验 APK 重新反编译。自有类重新编译，厂商 SDK 桩只参与编译；旧 smali 或 classes 缓存不会作为输入。

入口统一执行 hook pipeline：先校验签名和预期位置，再在临时副本注入，验证幂等，全部成功后写入。失败不会把半套修改留在输入目录。

输出在被 Git 忽略的 `device/build/`，包括新 APK 和 `build-report.json`。报告描述本次产物，不作为公开仓库中的固定测试成绩。源输入契约与构建报告用途不同，不能互相替代。

## 覆盖安装与恢复

```sh
python tools/flash_r1.py --serial 你的R1地址:5555
python tools/flash_r1.py --serial 你的R1地址:5555 --apply
```

默认只读检查；ADB 不在 PATH 时使用 `--adb`。`--apply` 会先保存当前 APK 备份，再传输、校验、执行覆盖安装。保留 Android 的签名检查，不卸载、不清数据。失败时保留备份，按工具给出的恢复命令处理。

安装前另外备份 R1 与 N1 配置。安装后检查设置回读、真实收音、暂停、问答和播报；构建或 JVM 测试成功不能代替 Android ART 与实际设备验收。

## 源码入口

网页源文件在 `device/web/`。`VoiceConfigPage.java` 由生成器生成。意图规则源在 `gateway/intent-rules.json`，音乐核心表由 HA 句式生成，再通过 `tools/generate_intent_rules.py` 编入 Java；不维护第二套正则。

构建本身不会安装到设备；覆盖安装需另行执行。完整检查入口和报告位置见 [TESTING.md](TESTING.md)。
