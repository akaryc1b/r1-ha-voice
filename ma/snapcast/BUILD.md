# 构建 API21 的 R1 Snapdroid 客户端

本目录不分发 APK/JAR 或签名密钥。使用 [Snapdroid 0.29.0.2 官方 APK](https://github.com/snapcast/snapdroid/releases/tag/v0.29.0.2)，其 SHA256 固定为 cd835c12ae3bf084ef06064333599040559a871fee48e83f3539e89224b40010；原包最低 API21，包含 ARMv7。

需要 Python 3.10+、JDK11、Android SDK build-tools（29.0.3 已测）、smali/baksmali 2.5.2 和自己的签名密钥。build-tools.json 固定 9 个工具 JAR 的 Maven 来源与 SHA；--download-tools 只在指定 tools-dir 下载并核对，不执行全局安装。

从自己的签名密钥读取密码环境变量 R1_SIGNING_PASSWORD；不要把密钥/密码放进 Git。使用参数传入所有本机路径：

~~~sh
python build_snapdroid.py \
  --source-apk "$SNAPDROID_OFFICIAL_APK" \
  --tools-dir "$SMALI_TOOLS_DIR" \
  --download-tools \
  --java-home "$JAVA_HOME" \
  --build-tools "$ANDROID_BUILD_TOOLS_DIR" \
  --keystore "$SIGNING_KEYSTORE" \
  --key-alias "$SIGNING_KEY_ALIAS" \
  --output "$OUTPUT_APK"
~~~

Windows PowerShell 可把命令写成一行，或将上面的续行反斜杠改成 PowerShell 的续行符；路径变量使用自己机器上的实际目录。

脚本校验官方 APK 和全部工具 SHA，在临时目录反汇编/组装，修改：

1. Settings.doResample() 返回 false，避免强制改成设备默认采样率。
2. Settings.persistStart(Context,Intent) 在明确 opt-in 时保存服务器/端口/自动启动。
3. SnapclientService.onStartCommand 在 null guard 后调用该辅助方法。
4. 禁止重采样时仍读取 Android `OUTPUT_FRAMES_PER_BUFFER` 并传入 native 环境，保持真实硬件 burst；不能因为关闭重采样而丢失这个独立参数。
5. 恢复原 `audioEngine` 偏好读取；上游 getter 固定返回 Auto。持久化启动可用 `EXTRA_PLAYER=oboe|opensl` 白名单保存，其他值忽略，默认仍为 Auto。

默认不镜像 native 日志。临时排查时加 `--native-log`，可从 `adb logcat -s SnapNative` 获取时钟、缓冲及重同步信息；日志可能包含服务器地址，仅保存在自己的诊断环境。此开关不改音频格式或缓冲设置。

签名后验证 APK，并核对原始非签名内容只有 classes.dex 改变。native 库、Manifest、资源保持上游内容。不会安装到任何设备，输出旁附 .build.json。

使用自己的证书后，不能直接覆盖官方签名安装包；同一测试证书构建的候选可以覆盖更新。不要因此卸载原 R1 语音助手或 MediaCenter；它们是其它包。

本地完整重新构建已经验证，但不同工具排序/签名证书可能导致 APK SHA 不同，不承诺二进制逐字节重现。上游 APK、构建工具和源差异有固定校验，具体构建以生成报告为准。

旧候选仅禁重采样时，会同时丢掉 burst 参数，R1 回退到192帧。修正后读取实际1024帧，Oboe缓冲384→2048帧；单项30秒对照的强制重同步61→5次，保持44.1kHz/16位/双声道、FLAC和500ms服务器缓冲。改善没有达到零重同步，现场听感仍需验收，不能把早期长播测试的系统零欠载等同于没有噼啪。

Snapclient0.29的Oboe在旧Android OpenSL无法读取呈现时间戳时使用固定50ms延迟估计，而R1 HAL报告128ms。该兼容性边界仍存在；增加服务器缓冲或改采样率应单独对照，不能盲目叠加参数。

本机还试过官方独立 `opensl` 引擎，44100Hz下启动即退出：`EngineObject::GetInterface` 返回 `SL_RESULT_PARAMETER_INVALID(2)`。已用参数恢复 `oboe`，不能把仅出现引擎名称的启动日志当成可播放。文档默认选择 `oboe`；独立 OpenSL 的失败与 Oboe 内部使用 OpenSL API 是两条不同路径。

最终现场保留候选 `11ecf428b5b92201aa9b7e044723c8d5e1d8921446dd7cbcfdbc5287a198f83d`，偏好已保存为 `oboe`，硬件burst1024；仅一个native实例及一条输出轨道。回退后30秒仍记录2次强制重同步和1次部分chunk不足，系统欠载计数未增加；随后用户在现场确认播放正常、没有噼啪声。该听测通过不等于后台计数为零，也不保证其他设备或网络环境相同，当前音乐参数已冻结。
