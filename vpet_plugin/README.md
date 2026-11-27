# Ringo VPet 桥接插件

本插件匹配当前 Steam 版 VPet 的 .NET 10 接口。它在 `127.0.0.1:17889` 接收一行一个 JSON 指令，返回 `command`、`ok` 和 `error`。手势识别器尚未接入，先用命令行逐项验证。

## 编译与安装

在项目根目录运行(路径替换成实际路径)：

```powershell
.\.tools\dotnet\dotnet.exe build .\vpet_plugin\VPet.Ringo.csproj -p:VPetInstallDir='D:\steam\steamapps\common\VPet'
.\vpet_plugin\install.ps1 -VPetDir 'D:\steam\steamapps\common\VPet'
```

重启 VPet，在游戏设置的 MOD 页面找到 `RingoVPet`。代码插件未签名，首次加载需在 VPet 中手动允许该 MOD；不要修改游戏的全局安全设置。启动后检查 `127.0.0.1:17889` 是否可连接。

## 手动验收

使用 `uv run ringo-vpet send PET`，也可在 PowerShell 中先执行 `$env:PYTHONPATH='src'`，再执行 `python -m ring.apps.vpet send PET`。完整移动用 `uv run ringo-vpet move 30 10`，它在同一个连接中依次发送 `MOVE_START`、`MOVE_DELTA`、`MOVE_END`，并播放 VPet 原有提起与落下动画。单条 `MOVE_START` 的连接关闭时插件会主动终止移动状态。

先用 `uv run ringo-vpet send PING` 检查插件端口。可用桌宠命令：`SUMMON`、`FAREWELL`、`STUDY`、`PLAY_DEAD`、`PET`、`FEED`、`PANEL_TOGGLE`、`PANEL_NEXT`、`PANEL_PREV`。`PLAY_DEAD` 当前用原生睡眠动作表示。投喂使用第一种有图片的默认正餐或零食，并由 VPet 决定动画名；如果当前安装没有可用食物，返回 `no_food_available`。菜单指令操作 VPet 原有工具栏，不创建自定义面板。

戒指连接测试：运行 Ringo 工作台并连接戒指，再执行 `uv run ringo-vpet ringo --count 5`；仅查看连接状态可用 `uv run ringo-vpet ringo --status-only`。这些命令只显示数据，不执行桌宠动作。后续识别器可导入 `ring.apps.vpet.bridge.ringo_messages` 与 `VPetSession`，输出同一套指令。
