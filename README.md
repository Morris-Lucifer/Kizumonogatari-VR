# Kizumonogatari VR — Quest 3 兼容项目

为 PS4《伤物語VR》（CUSA09079，游戏 APP_VER 01.00）提供 Quest 3 本地运行支持。
当前版本为 **0.1.7 实验诊断版**，基于 FGO-VR、AstroQuest 和 shadPS4。

**运行只需本项目的 APK 和《伤物语 VR》游戏本体，不需要《FGO VR》游戏本体。**
APK 是适配运行程序，不包含游戏资源。安装后，把自己拥有的已解包《伤物语 VR》数据
复制到头显。准备完成后，画面在 Quest 本地生成，无需 PC 串流。
APK 的 0.1.7 是适配程序版本，不是 PS4 游戏更新版本。

直接游玩可下载 Releases 中的 APK，无需克隆源码或安装 FGO APK。
克隆仓库用于自行构建；构建脚本所需的 FGO APK 只是公共运行组件的来源，
与 FGO 游戏本体无关。

## 安装到 Quest 3

需要自己的 CUSA09079 已解包本体，目录中直接包含 `eboot.bin`，以及 Quest 左右实体 Touch 手柄。
应用包名为 `com.kizuvr.quest`，在头显中显示为 `Kizumonogatari VR (Test)`。

启用头显开发者模式，连接 USB，并在头显里允许 USB 调试。
使用 Android platform-tools 的 `adb`，以下命令假定只连接一台已授权设备。
多设备时在每条 `adb` 后加入 `-s <设备序列号>`。

从仓库的 Releases 页面下载 `Kizumonogatari-VR-0.1.7-Quest3-Diagnostics.apk`，
在 APK 所在目录打开 PowerShell，执行以下命令。

```powershell
adb devices
adb install -r .\Kizumonogatari-VR-0.1.7-Quest3-Diagnostics.apk
adb shell mkdir -p /data/local/tmp/kizuvr/games
adb push "C:\YourGame\CUSA09079" /data/local/tmp/kizuvr/games/
adb shell chmod -R a+rX /data/local/tmp/kizuvr/games/CUSA09079
adb shell am start -n com.kizuvr.quest/com.fgovr.quest.MainActivity
```

把示例中的 `C:\YourGame\CUSA09079` 换成自己的本体路径。最终必须能访问：

```text
/data/local/tmp/kizuvr/games/CUSA09079/eboot.bin
```

只有 APK 而没有《伤物语 VR》游戏数据时，不能进入游戏。
本项目 APK 已包含所需运行库，头显上无需另外安装 FGO APK。
`com.fgovr.quest.MainActivity` 是保留的内部类名，应用包名实际是 `com.kizuvr.quest`。

下载后的 APK 可使用 [SHA256SUMS](releases/v0.1.7/SHA256SUMS) 核对；
应用版本和组件哈希记录在 [manifest.json](releases/v0.1.7/manifest.json)。
PowerShell 中可执行：

```powershell
Get-FileHash .\Kizumonogatari-VR-0.1.7-Quest3-Diagnostics.apk -Algorithm SHA256
```

## 控制

人物互动场景中，移动右侧实体手柄控制游戏右手。左右摇杆同时按下可重新居中。
原有菜单通道保留右 A = Cross、右 B = Square、左 X = Circle、左 Y = Triangle。

Move 交互通道将各手的 A/X 映射为 Cross，B/Y 为 Circle，侧面握把为 Move 键，
扳机提供模拟量。单独按摇杆为 Square，摇杆向上为 Triangle。
这些是代码中的映射；游戏是否使用每一个键取决于具体场景，尚未逐项验收。

## 配置、退出与更新

配置文件位于 `/sdcard/Android/data/com.kizuvr.quest/files/vrhost.txt`。
示例是 [config/vrhost.example.txt](config/vrhost.example.txt)。
首次启动产生应用目录后，可按需将其中设置合入自己的配置；`stats=0` 关闭常驻统计面板。
保留自己已有的其他配置项。诊断日志仍可能写入 `core.log` 和 `host.log`。

退出时使用 Quest 右侧系统键打开系统界面并退出应用。若应用无响应，电脑端可执行：

```powershell
adb shell am force-stop com.kizuvr.quest
```

同签名版本使用 `adb install -r` 更新，不必卸载。自己重新构建的 APK 默认会使用新生成的
开发签名，不能直接覆盖另一把密钥签名的版本。不要为解决签名错误直接卸载而丢失应用数据；
需要更新现有安装时，应使用同一签名并先备份自己的数据。

## 已知问题

- 玻璃碎裂/场景切换性能较差，曾观察到约 14–25 fps 的 10 秒区间；
  一个 5 秒核心区间约 6.4 fps。该数据不是全部场景平均帧率。
- 影片仍有轻微闪动的佩戴者反馈，原因未确认。
- 所有按键/握把交互、物理震动、精细位置校准和重复运行稳定性未全部验收。
- PCVR、其他 Quest 型号、其他游戏版本和裸手交互未验证。

<details>
<summary>展开版本说明与验证结果</summary>

### 0.1.7 实验诊断版

此版本保留启动/GC 信号/互斥锁等待修复、影片缓冲生命周期和快照上传修复，
并提供 Quest Touch 到 PS Move 的独立输入映射。
0.1.7 调整了主手对应关系，去掉额外的 90 度旋转；佩戴者确认左右对应和方向正常。

### Quest 3 验证结果（2026-10-16）

- ARM64 核心和 Android 主程序构建成功；APK 签名、对齐及设备文件哈希核对通过。
- 对照测试复现了旧 Move 接口不返回手柄、旧左右映射错误；修正版测试通过。
- 实际核心/主程序测试覆盖两手独立数据、居中、断连、追踪丢失、句柄及震动路由。
- 佩戴者确认模型出现，0.1.7 的左右对应和方向正常。
- 此前 0.1.5 的佩戴者测试确认首个场景切换通过，主要影片闪烁基本消失；
  该轮前台日志到达影片 EOF，之后记录正常退出。这不等于多次运行均稳定。
- 0.1.7 的 90 秒只读前台采集没有记录原生致命错误。

</details>

## 从源码构建

<details>
<summary>展开 Windows 构建步骤、回归测试与日志采集</summary>

克隆仓库，或下载源码 ZIP 并解压。在仓库根目录打开 PowerShell，
按以下步骤准备依赖、编译并生成 Quest APK。

### 前提与固定输入

- Windows x64、Git、Python 3.12、7-Zip。
- CMake 与 Ninja 可在 PATH 中，也可通过 `KIZU_CMAKE`、`KIZU_NINJA` 指定完整路径。
  未找到时回退到 Visual Studio 2022 Community 的随附工具。
- 核心使用固定 LLVM 21.1.8 和 Debian 13 ARM64 sysroot。
- Android 主程序使用 NDK r29；SDK/JDK 使用 `upstream/android-tools-lock.json` 中的版本和哈希。
- 来源提交见 `upstream/kizu-provenance.json`，依赖包见 `upstream/arm64-sysroot-lock.json`。
- C++ 回归测试使用 WSL Ubuntu 的 `g++`。

所有命令从仓库根目录执行。脚本将下载的依赖和构建产物写入 `evidence/`。
游戏数据按上方的安装步骤另行准备。

### 准备

```powershell
py -3.12 ports/kizumonogatari/prepare_tools.py
py -3.12 ports/kizumonogatari/prepare_runtime.py all
py -3.12 ports/kizumonogatari/prepare_native.py source
py -3.12 ports/kizumonogatari/prepare_native.py llvm
py -3.12 ports/kizumonogatari/prepare_native.py sysroot
py -3.12 ports/kizumonogatari/prepare_native.py fex
py -3.12 ports/kizumonogatari/prepare_native.py ffmpeg
py -3.12 ports/kizumonogatari/apply_diagnostics.py
```

`prepare_runtime.py` 自动下载并校验固定的 FGO 0.2.0 适配 APK 和 NDK r29。
这里的 FGO APK 不含 FGO 游戏数据：打包脚本从中提取加载器和运行库，
并将这些组件打包进伤物语 APK。自行编译也不需要 FGO 游戏本体，
不需要把 FGO APK 安装到头显。
基础 APK SHA-256 为 `4a2864ba007c98f50379dc0f4d57cbc7b95b72104d4544cb66f12802f30ca754`，
它提供未改动的 Android 加载器和 Linux/Turnip 运行库。
默认路径为 `evidence/runtime-base/FGO-VR-0.2.0-Quest3.apk`；也可设置 `KIZU_BASE_APK`
使用另一位置的同一份文件，哈希检查仍然生效。
`prepare_runtime.py all --verify-only` 只检查本地依赖。

LLVM 解压使用 `C:\Program Files\7-Zip\7z.exe`。如果 7-Zip 安装在其他位置，
修改 `ports/kizumonogatari/prepare_native.py` 中的工具路径。

### 构建并打包

```powershell
py -3.12 ports/kizumonogatari/build_native.py font
py -3.12 ports/kizumonogatari/build_native.py fex
py -3.12 ports/kizumonogatari/build_native.py harness
py -3.12 ports/kizumonogatari/build_native.py core
py -3.12 ports/kizumonogatari/build_android_host.py

$kizuCore = Get-Content evidence/kizu-native/latest-native.json | ConvertFrom-Json
$kizuHost = Get-Content evidence/kizu-native/latest-android-host.json | ConvertFrom-Json
py -3.12 ports/kizumonogatari/build_host.py --core $kizuCore.core --native-manifest (Join-Path (Split-Path $kizuCore.core) 'manifest.json') --host-library $kizuHost.library --host-manifest (Join-Path (Split-Path $kizuHost.library) 'manifest.json')
```

打包器核对核心与主程序文件哈希和协议头哈希，执行 APK 签名及对齐检查。
完成后，终端会输出 APK 路径；也可读取
`evidence/kizu-quest-20261015/latest-build.json` 中的 `apk` 字段定位安装包。
自行构建使用脚本生成的开发签名，覆盖已有安装需要相同签名。

JNI 类名中保留的 `fgovr` 和 FGO 基础补丁文件名是当前依赖关系的一部分，不能全局替换。

### 测试与日志

准备并应用补丁后，可执行：

```powershell
py -3.12 ports/kizumonogatari/native/move_controller_test.py
py -3.12 ports/kizumonogatari/native/move_controller_test.py --baseline
py -3.12 ports/kizumonogatari/native/touch_move_test.py
py -3.12 ports/kizumonogatari/native/mutex_signal_wait_test.py
py -3.12 ports/kizumonogatari/native/video_frame_lifetime_test.py
```

`--baseline` 的 Move 对照预期旧接口失败，并将符合预期的失败记为测试成功。
基线源码位于 `tests/fixtures/`。

佩戴者正在体验时只采集日志：

```powershell
py -3.12 ports/kizumonogatari/capture_foreground.py --seconds 90 --adb "C:\Android\platform-tools\adb.exe"
```

`--serial` 可选；只有一台已授权设备时自动选择。也可使用 `KIZU_ADB` 和 `ANDROID_SERIAL`。
无人佩戴、应用已停止时才运行 `device_test.py`；它会启动后台测试并在结束后停止应用，
不能与正常游戏进程重叠。

### 源码结构

保留目录层级：脚本通过 `ports/kizumonogatari/` 的相对位置确定仓库根目录。

| 目录 | 内容 |
| --- | --- |
| `ports/kizumonogatari/` | 伤物语核心/Android 主程序补丁、构建工具、诊断与测试 |
| `patches/` | 仍被使用的 FGO Quest 基础补丁和 FEX 构建支持 |
| `source_snapshot/quest/` | 基础 Quest 修改快照，供主程序构建使用 |
| `build_reference/` | 当前构建脚本依赖的 CMake 模板和 Debian 归档解析辅助工具 |
| `upstream/` | 固定提交、工具版本、依赖哈希及保留的原始许可证说明 |
| `tests/fixtures/` | 不含游戏数据的 Move API 基线测试源码 |
| `config/` | 可选配置示例 |
| `releases/` | APK 哈希与版本清单 |

源码准备顺序为固定 AstroQuest 基线 → FGO Quest 完整补丁 → 本项目核心补丁；
Android 主程序另外应用 `host/move-input.patch`。不要重复叠加基础补丁。

### 工具入口

- `native/*.patch` 和配套头文件：模拟器兼容修复。
- `host/move-input.patch`：Android 主程序的独立 Touch-to-Move 输入映射。
- `prepare_*.py`：下载固定版本依赖，准备基础源码。
- `build_*.py`：编译、打包运行程序并检查主程序与核心的协议一致性。
- `native/*test*`：使用测试夹具验证实际代码。
- `capture_foreground.py`：采集佩戴者正在运行的游戏日志，不启动或停止应用。
- `device_test.py`：无人佩戴时运行的后台测试，不与正常游戏进程同时运行。

</details>

## 来源与许可

- [FGO-VR](https://github.com/saberwatchmanga/FGO-VR)：继承的 Quest 基础适配。
- [AstroQuest](https://github.com/bigmak94/AstroQuest)：固定提交与组件版本记录在
  [来源记录](upstream/kizu-provenance.json)。
- [shadPS4](https://github.com/shadps4-emu/shadPS4)、[FEX](https://github.com/FEX-Emu/FEX)
  及其他依赖继续适用各自的许可证。

源码沿用 GPL-2.0-or-later，许可证正文保留在 [LICENSE](LICENSE) 和
[upstream/LICENSE](upstream/LICENSE)。项目不包含游戏资源、PS4 PKG、固件、主机密钥、
用户存档或签名密钥。原作与角色归各自权利人所有，本项目为非官方兼容适配。

<details>
<summary>展开第三方组件与许可证声明</summary>

Kizumonogatari-VR replaces the emulator and Android input host while retaining
baseline runtime components including FEX, OpenXR, libc++, glibc, GCC runtime
libraries and Mesa Turnip. Inherited source notices and GPL-2.0-or-later
source declarations are retained. Component-specific source and notice
requirements continue to apply when distributing an APK.

The `tests/fixtures/move_baseline.cpp` file is an unmodified GPL-covered emulator
source fixture; it contains no game code or assets. Build tools are downloaded
from their publishers using the versions and hashes recorded under `upstream/`.

以下保留 AstroQuest 的上游第三方声明。其中 “this repository” 指
[AstroQuest](https://github.com/bigmak94/AstroQuest)，组件路径相对其源码树；
PC 构建条目描述上游组件，不代表本项目提供 PCVR 版本。

### Third-party notices

AstroQuest itself is licensed under GPL-2.0-or-later (see [LICENSE](upstream/LICENSE)). The release files
also contain, or are built with, the following parts made by others. Each keeps its own license;
the source of every part is listed with it.

#### Quest app (`AstroQuest-<version>-Quest3.apk`)

| Part | License | Source |
| --- | --- | --- |
| The emulator (`shadps4-arm64-fex` in `assets/runtime.zip`): shadPS4 with the shadps4-arm64 changes and this project's | GPL-2.0-or-later | this repository, `shadps4-arm64-main/` (from [zenithblue-oss/shadps4-arm64](https://github.com/zenithblue-oss/shadps4-arm64), based on [shadPS4](https://github.com/shadps4-emu/shadPS4)) |
| The libraries built into the emulator (`shadps4-arm64-main/externals`: SDL3, fmt, Boost, glslang, sirit, Vulkan Memory Allocator, zlib-ng, xxHash, FFmpeg's core and others) | their own licenses (zlib, MIT, BSL-1.0, BSD, LGPL...), in each folder | the submodules listed in [.gitmodules](upstream/.gitmodules) |
| FEXCore, linked into the emulator | MIT | [FEX-Emu/FEX](https://github.com/FEX-Emu/FEX), fetched and patched by `shadps4-arm64-main/runtime/scripts/build-fexcore-smoke-aarch64.sh` |
| The app (`libastrovr.so`, `classes.dex`) and `libkgsl_compat.so` | GPL-2.0-or-later | this repository, `quest-host/` |
| LLVM libc++, linked into `libastrovr.so` | Apache-2.0 WITH LLVM-exception | [Android NDK](https://developer.android.com/ndk) / [LLVM](https://github.com/llvm/llvm-project) |
| Khronos OpenXR loader for Android 1.1.63 (`libopenxr_loader.so`) | Apache-2.0 | [KhronosGroup/OpenXR-SDK-Source](https://github.com/KhronosGroup/OpenXR-SDK-Source), release 1.1.63 |
| The GNU C Library 2.41 and its dynamic loader (`libc.so.6`, `libm`, `libdl`, `libpthread`, `librt`, `libresolv`, `libutil`, `ld-linux-aarch64.so.1`, the latter shipped as `libastro_ld.so`) | LGPL-2.1-or-later | Debian 13 `glibc` source package, with the Android compatibility patches in `shadps4-arm64-main/runtime/patches/glibc-android-sysvshm/` and `runtime/scripts/glibc-android-seccomp.mjs` |
| GCC runtime (`libstdc++.so.6`, `libgcc_s.so.1`) | GPL-3.0-or-later WITH GCC-exception-3.1 | Debian 13 `gcc-14` source package |
| X11 and XCB client libraries, libxkbcommon, libxshmfence, libdrm, libexpat, libffi, libwayland-client | MIT / X11 | Debian 13 source packages of the same names |
| libsystemd, libudev | LGPL-2.1-or-later | Debian 13 `systemd` source package |
| libdbus-1 | AFL-2.1 or GPL-2.0-or-later | Debian 13 `dbus` source package |
| libcap | BSD-3-Clause or GPL-2.0-only | Debian 13 `libcap2` source package |
| libuuid | BSD-3-Clause | Debian 13 `util-linux` source package |
| zlib | Zlib | Debian 13 `zlib` source package |
| Vulkan loader (`libvulkan.so.1`), SPIRV-Tools | Apache-2.0 | [KhronosGroup/Vulkan-Loader](https://github.com/KhronosGroup/Vulkan-Loader), [KhronosGroup/SPIRV-Tools](https://github.com/KhronosGroup/SPIRV-Tools), as packaged by Debian 13 |
| Mesa Turnip Vulkan driver for Adreno (`libvulkan_freedreno.so`) | MIT | [Vauzi-17/mesa-tu8](https://github.com/Vauzi-17/mesa-tu8), branch `gen8`, commit `9e646d59830fa220fff9a94ef2ed4a6ce418e254`, with Bachata S4's `kgsl-zero-timeout-poll` patch |

The Linux runtime (everything from glibc to the Turnip driver above) is taken unchanged from
the [Bachata S4 v0.2.4](https://github.com/JICA98/Bachata-S4/releases/tag/v0.2.4) release,
whose notice (`shadps4-arm64-main/NOTICE.android-runtime.md`) and lock files
(`shadps4-arm64-main/runtime/locks/`) record the exact packages.

#### PC build (`AstroQuest-<version>-PC-VR-Windows.zip`)

| Part | License | Source |
| --- | --- | --- |
| The emulator (`shadps4.exe`) and the launcher (`launch.ps1`, `Play Astro Bot VR.bat`) | GPL-2.0-or-later | this repository |
| The libraries built into the emulator (`shadps4-arm64-main/externals`) | their own licenses, in each folder | the submodules listed in [.gitmodules](upstream/.gitmodules) |
| Khronos OpenXR loader 1.1.63, built into the emulator | Apache-2.0 | `shadps4-arm64-main/externals/openxr-sdk` ([KhronosGroup/OpenXR-SDK](https://github.com/KhronosGroup/OpenXR-SDK), release 1.1.63) |
| PkgTool and LibOrbisPkg 0.2.231 (`pc-vr/pkgtool`), unchanged: the launcher runs it to unpack a game package | LGPL-3.0 | [maxton/LibOrbisPkg](https://github.com/maxton/LibOrbisPkg), release [v0.2](https://github.com/maxton/LibOrbisPkg/releases/tag/v0.2) |

The emulator needs the Microsoft Visual C++ runtime, which is not included: it comes with the
[Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe).

#### Source of the GPL and LGPL parts

The source of AstroQuest itself is this repository, at the tag of each release. For the GPL
and LGPL parts made by others (the Linux runtime in the Quest app, the libraries built into
the emulators from `shadps4-arm64-main/externals`, and PkgTool), a copy of the exact source
used is available on request for three years from each release: open an issue on this
repository.

#### Not included

No part of ASTRO BOT Rescue Mission, of the PlayStation 4 system software, or any key or other
copyrighted console file is part of this repository or of its releases.

</details>
