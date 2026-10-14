# 在 HACS 安装 R1 播放卡片

仓库根目录的 `r1-ha-voice.js` 是唯一的卡片源码，`hacs.json` 指向此文件。自定义元素名仍为 `r1-player-card`。

## 安装

1. 在 HACS 的自定义仓库中添加 `https://github.com/akaryc1b/r1-ha-voice`，类型选择 Dashboard / 仪表盘。
2. 下载该仓库的卡片。
3. 检查 HA 的仪表盘资源中是否已有 `/hacsfiles/r1-ha-voice/r1-ha-voice.js`，资源类型为 JavaScript Module；已有时不重复添加。
4. 按 [HA 配置说明](../ha/README.md) 渲染并导入音乐脚本、传感器及面板。

HACS 负责安装卡片文件，HA 音乐脚本、MA 授权和 R1 固件仍需分别配置。此仓库作为自定义仓库使用，未申请加入 HACS 默认目录。

示例卡片：

```yaml
type: custom:r1-player-card
entity: media_player.r1_apple_music
r1_url: http://192.168.1.3:8080/
temperature: sensor.你的卧室温度
humidity: sensor.你的卧室湿度
```

替换实体和音箱地址。`r1_url` 支持 HTTP / HTTPS，默认是示例 R1 地址，不接受携带账号密码的 URL。地址直接赋给链接，不作为 HTML 插入。

## 从旧手动资源迁移

以前手动安装的 `/local/r1-player-card.js` 与 HACS 版本使用相同元素名。改用 HACS 时，从 HA 仪表盘资源中移除旧资源登记，保留新的一个资源，再刷新浏览器；无需删除播放器、脚本或音乐库。

继续手动安装也可以：把仓库根 `r1-ha-voice.js` 复制为 `/config/www/r1-ha-voice.js`，登记 `/local/r1-ha-voice.js`，类型同样为 JavaScript Module。两种方式择一。

卡片仅在连接页面、浏览器可见且正在播放时更新进度定时器；暂停、待机、隐藏或离开页面时停止定时器。重新显示页面会立即刷新进度。

目录和默认分支下载方式按 [HACS Dashboard 官方规范](https://hacs.dev/docs/publish/plugin/)；manifest 字段见 [HACS 通用规范](https://hacs.dev/docs/publish/start/)。
