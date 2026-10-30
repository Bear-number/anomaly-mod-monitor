# anomaly-mod-monitor（Alife 技能）

监控 ModDB 上 S.T.A.L.K.E.R. Anomaly 分类（addons）的新 MOD 发布与近期更新。用法、抓取 JS、退出码口径全在 **[SKILL.md](SKILL.md)**。

- 装法：解压到 `Alife\Storage\Skills\anomaly-mod-monitor\`（就是这个目录本体）
- ModDB 直连被 Cloudflare 挡（2026-10-30 复测：直连 `GET` 回 `403` + `Just a moment...`，无头 Chrome 也只拿到挑战页），所以抓取要真浏览器——现在由 `scripts/cdp_grab.py` 自己起一个非无头的 msedge/chrome（独立 user-data-dir、窗口挪到屏幕外），连 DevTools 调试口跑抽取 JS，抓到直接写 `SkillData\moddb_grab.txt`。`scripts/sink.py` 保留为兜底（人工开页面 + 本机一次性接收器），比对都是 `scripts/moddb_monitor.py`
- 抓取 JS 里标题取 `h4 a`（2026-10-23 实跑纠正：写 `h3 a` 会整批空标题）
- 三个脚本全程零回显：结果写 `Storage\SkillData\moddb_report.txt`，状态一行写 `moddb_status.txt`，失败写 `moddb_error.txt`，靠退出码带信号（monitor `0 无变化 / 1 有变化 / 2 解析不出 / 3 抓取读写失败或文件太旧`；cdp_grab `0 抓到写盘 / 2 一条没抽到 / 3 CF 挑战页没过 / 4 浏览器或 CDP 起不来 / 5 写盘失败`；sink `0 / 2 / 4`）；**参数用错一律退 9**，不和这些码混
- 缓存与抓取产物都在 `Storage\SkillData\`，不在本仓库里
- 离线自检：`py -3 scripts/moddb_monitor.py --selftest --print`（不联网、不碰真缓存）
