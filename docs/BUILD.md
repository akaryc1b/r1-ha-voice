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
