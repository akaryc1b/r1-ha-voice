# R1 客户端构建与覆盖安装

公开仓库主要保存环境说明和源码，不上传 APK、完整厂商 SDK、镜像、模型或工具 JAR。云端 ASR 模型的日常更换只需 8080 配置，不需要构建。

## 需要的开发环境

- Python 3.10 或更高。
- JDK 11（已验证）。
- Android SDK Platform 29 的 android.jar。
- Android Build Tools 29.0.3 的 D8。
- smali / baksmali 2.5.2 及其依赖；版本、Maven 下载地址和 SHA256 在 `device/build-tools.json`。
- 自己的匹配 R1 备份 APK，SHA256 应与 `device/build-report.json` 的 `apk_sha256` 相同。

## 取得本机 APK 备份

已有兼容安装时：

```sh
adb -s 192.168.1.3:5555 shell pm path com.phicomm.speaker.device
```

按返回的真实路径执行 `adb pull`，保存为 `device/r1-local-asr.apk`。不要照搬其他设备的 `/data/app/...` 路径。APK 被 `.gitignore` 排除，保留在自己的本地备份中。

此构建方式依赖本次已改造 APK 内的原生挂钩；不是从任意 R1 原厂 APK 自动生成全部改造。没有匹配备份时，不能绕过校验强行使用未知固件。

## 下载构建工具

```sh
python device/download_build_tools.py
```

下载后核对固定 SHA256，工具存入被忽略的 `device/tools/`。

## 构建

Windows 示例，按实际路径修改：

```powershell
python "device\build_client.py" `
  --base-apk "device\r1-local-asr.apk" `
  --java-home "C:\你的JDK11目录" `
  --android-sdk "C:\你的AndroidSDK目录"
```

也支持 JAVA_HOME、ANDROID_SDK_ROOT / ANDROID_HOME。脚本会先校验输入 APK，恢复其原生 DEX 挂钩，再编译自有 Java 源码与网页。

页面源文件是 `device/web/voice-card.html`、`voice-settings.js`、`voice-settings.css`，构建时生成 VoiceConfigPage.java，不需要手工编辑大段 Java 转义字符串。

输出 `device/r1-local-asr.apk` 与更新后的 `build-report.json`。DEX 重排或工具环境可能造成新 APK 哈希与原输入不同，安装以本次新报告为准。干净目录构建已经通过，不代表任意工具版本均经过验证。

## 覆盖安装

```sh
python tools/flash_r1.py --serial 192.168.1.3:5555
python tools/flash_r1.py --serial 192.168.1.3:5555 --apply
```

ADB 不在 PATH 时加 `--adb "实际路径"`。工具核对本机与设备端 SHA256、现有包名，使用 `pm install -r`，不执行卸载或清除数据。安装后检查 8080 设置回读与实际识别。

旧 APK、R1 配置与 N1 私密配置都应保留在仓库外。构建脚本不是绕过签名不匹配的方法。

补充验证边界：从当前已安装 APK 在干净目录提取 DEX 并重新构建已成功。该重建产物的额外 Android ART 检查因 ADB 传输在 90 秒超时，未执行完成；未安装此重建产物。现场已安装版本的 ART 校验、网页与识别测试此前通过。重建后应先完成设备端校验再覆盖安装。

本轮第一阶段客户端 f3c2d7a53b246d35e39aa2ac4174e409634f3a078d4fa2d0080497e31bd2fbe9 已完成设备端 SHA256、Android ART 校验和覆盖安装；8080 保存/刷新与两段播报已验证。上述干净重建产物的独立验证边界仍保留，不混为同一产物。

当前客户端291bdaf85ba595f66724e258fd555e7a207892b326c98a2d1c7efde51195d356已通过SHA256、Android ART及覆盖安装；新增播报切路音量补偿，真实唤醒日志确认普通音量与静音保护均生效。单次播报中调音回切由隔离测试覆盖，尚未做现场定句完整验收。


## 2026-10-14 单次续听客户端

当前安装SHA256：105942ceb9d625bd25a9b458fff13cd4e387bd9008e47e4d50de08d410017541。新增AsrRetryOnce状态机、唤醒取消挂钩、真实TTS完成续听及8080开关；正常音乐说法不再归一化成“播放音乐”。12项生命周期/16项归一化测试、Java编译、smali幂等/原方法还原、Android ART、覆盖安装及安装后SHA256通过。现场自动续听尚待验证，291版的旧听测不代表新版已完成所有听测。
