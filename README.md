# BoxProxy 定制回编译工程

包名 `com.boxproxy.box`。仓库中的 `decompiled/` 是 **26.11.05.d5c365e / versionCode 139** 的迁移基线，
不是当前 GitHub Actions APK 的输入。CI 的目标是 **26.11.16.25abc84 / versionCode 171 / arm64-v8a**：
从固定的 `upstream/26.11.16.25abc84` 快照生成完整迁移候选后再回编译，并校验版本号为 171。

已将旧定制的 VPN/非 root、root 修复、初始化/权限、配置历史与恢复、编辑器/可视化/锚点、
内核 fork 下载、schema、内置配置、IPv6 和开机/电池设置迁入新版，同时保留上游新界面和规则功能。

- [139 迁移基线的范围与报告](upstream/26.11.05.d5c365e/migration/README.md)
- [171 完整迁移计划](upstream/26.11.16.25abc84/migration/full.json)
- [VPN / 编辑器源码与工具链](vpn-src/README.md)

## 本地构建

要复现 **171**，先显式生成迁移候选，再将 `PROJECT_DIR` 指向它。`scripts/build.sh` 不带参数时仍默认构建 139 的 `decompiled/`。

```sh
python3 scripts/migrate_upstream.py \
  --snapshot upstream/26.11.16.25abc84 \
  --output .tools/local-171
PROJECT_DIR=.tools/local-171/decompiled \
  OUT_DIR=.tools/local-171-build bash scripts/build.sh
```

本地已完成回编译和包信息校验的 APK 是 `.tools/build-171/BoxProxy-26.11.16.25abc84-unsigned.apk`（versionCode 171；SHA-256
`1219aac0a661382d4a36821816423c7917f49f68961ed0f98c79d31ec8bc92ae`）。它是**未对齐、未签名**的本地回编译产物，
不等同于 GitHub Actions 的 APK artifact，也没有安装到设备验证。

## CI 产物与设备验证

`Build APK` 工作流也会自行从固定 171 快照生成迁移候选（不会读取 `decompiled/`），然后执行回编译、对齐、签名并上传 APK。
CI artifact 是签名后的产物：使用仓库签名 Secrets（若已配置），否则使用临时 debug 密钥；签名模式会写入构建摘要。
这与本地 unsigned APK 的对齐/签名状态不同，也不代表真机兼容性已经验证。

**Android root/非 root 真机、VPN/DNS/IPv6/开机与电池限制，以及同签名覆盖升级验证仍待设备和原签名密钥验证。**
