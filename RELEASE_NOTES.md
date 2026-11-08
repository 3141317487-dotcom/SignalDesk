# SignalDesk v1.0.0

Windows 10/11 x64 数据集查看器，无需 Python。

下载 `SignalDesk-v1.0.0-windows-x64.zip`，完整解压后双击 `SignalDesk/SignalDesk.exe`。不要只复制 EXE，请保留 `_internal`。

- 支持波形与图片、手动选择数据集、CASE 情绪标签自动匹配。
- 多通道缩放、时间选区、原始数据 CSV 导出、PNG 图像导出、统计。
- 包含合成演示数据；真实 CASE 数据须另行从官方获取。
- 8 项读取与 GUI 功能测试通过。Windows 可执行文件另经启动和显示验证。
- 初始版本未代码签名。下载后可用 PowerShell `Get-FileHash 文件名 -Algorithm SHA256` 对照 SHA256SUMS.txt。

源码采用 MIT 许可证，依赖许可证包含在发行包内。
