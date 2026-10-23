# anomaly-mod-monitor — 异常(Anomaly) 新MOD监控

监控 ModDB 上 S.T.A.L.K.E.R. Anomaly 分类（addons）的新发布与近期更新，对比缓存后只报增量。**ModDB 直连被 Cloudflare 挡**（2026-10-22 本机实测：无头 Chrome 拿列表页只得到挑战页、0 条），所以抓取这一步必须走真浏览器。

触发说法：「检查异常MOD」「异常有新MOD吗」。

## 跑一次
```bat
:: 1) 先起接收器（后台跑，等浏览器把数据投进来）
start /min "" py -3 D:\Alife\Storage\Skills\anomaly-mod-monitor\scripts\sink.py
:: 2) 浏览器打开列表页，跑下面那段抓取JS（抓完自己提交给 127.0.0.1:38472）
::    https://www.moddb.com/mods/stalker-anomaly/addons?orderBy=created
:: 3) 接收器退出码 0 之后，比对并落盘
py -3 D:\Alife\Storage\Skills\anomaly-mod-monitor\scripts\moddb_monitor.py --from-file D:\Alife\Storage\SkillData\moddb_grab.txt --update
```
回退写法（接收器起不来时）：让 JS 把结果 `return` 回来，用文件工具写进 `SkillData\moddb_grab.txt`，再跑第 3 步——代价是数据会进一次对话。

## 看退出码，别看 stdout
| 脚本 | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| `sink.py` | 已收到并落盘 | — | 收到了但没一行有效数据 | — | 超时没收到（`moddb_error.txt`） |
| `moddb_monitor.py` | 无变化，**只回一句「无新增/更新」，不去读文件** | 有变化，去读 `SkillData\moddb_report.txt` 汇报 | 抓到东西但解析不出条目 | 没抓到东西或读写失败（`moddb_error.txt`） | — |

两个脚本全程零回显，`--print` 才给人看。其它参数：`--hours 48`（默认24）、`--selftest --print`（离线自检，不碰真缓存）。

**报「无新增/更新」前先分清是哪一种**：每次跑都会把一行纯计数写进 `SkillData\moddb_status.txt`，例如
`10-22 15:40 [异常] 退出码0 抓到16 缓存已含16 窗口外0 新增0 更新0 窗口24小时`。
`抓到16 缓存已含16` = 抓到了、都是老熟人；`抓到0` 或退出码 2/3 = 抓取那一步出问题了。这行只有计数、没有条目名，读它不会把数据搬进对话。

## 抓取JS
```js
(() => {
  const rows = [], seen = new Set();
  document.querySelectorAll('.rowcontent, .row').forEach(row => {
    const a = row.querySelector('a[href*="/mods/stalker-anomaly/addons/"]');
    if (!a) return;
    const slug = (a.getAttribute('href').match(/addons\/([a-z0-9-]+)\/?$/) || [])[1];
    if (!slug || seen.has(slug)) return;
    const titleEl = row.querySelector('h4 a, h4, a');
    const t = row.querySelector('time[datetime]');
    seen.add(slug);
    rows.push(slug + ' :: ' + ((titleEl && titleEl.innerText) || '').trim().slice(0, 60)
      + ' :: ' + (t ? t.getAttribute('datetime') : ''));
  });
  const f = document.createElement('form');
  f.method = 'POST'; f.action = 'http://127.0.0.1:38472/'; f.style.display = 'none';
  const ta = document.createElement('textarea'); ta.name = 'data'; ta.value = rows.join('\n');
  f.appendChild(ta); document.body.appendChild(f); f.submit();
  return rows.length;      // 只回行数，不回数据
})();
```
每行是 `slug :: 标题 :: 绝对时间`。**标题在 `h4 a` 里**（2026-10-22 主人实跑纠正：我原来写的 `h3 a` 第一遍抓回来全是空标题）。`time[datetime]` 这条实测能拿到 `2026-10-20T23:07` 这种绝对时间（`SkillData\grab_tmp.txt` 里就是）；只拿到相对串时脚本会按 slug 判新增、并记 `[时间告警]`。标题整批抓空时 `[标题告警]` 会直接点出「多半是选择器没命中——标题在 h4 a 里」。

## 汇报
按 `moddb_report.txt` 原样转述：抬头是「最近N小时：新增 X 条、更新 Y 条（抓到…，窗口外…）」，下面编号列变化条目，每条 `序. 新|更 标题 - 月/日 时:分 - 链接`。告警行只有计数，照抄即可。

## 链接铁律（2026-09-12 主人定稿）
每条必须给真实可点的完整链接，禁占位符：`https://www.moddb.com/mods/stalker-anomaly/addons/{slug}`。

## 注意
- `[覆盖告警]` = 抓到的最旧一条还在窗口里，多半有下一页没抓：在页面上点分页再抓一次（分页参数本轮未实测，不写死），或把 `--hours` 调小。
- 判更新只认绝对时间**严格晚于**缓存里那条；缓存存页面原始绝对串（`mods[slug].updated`）。旧缓存只有相对串或 `date` 字段的，第一次走 `[回填]`，不会误报整页更新。
- 检查间隔建议 ≥2 小时；只记录信息，不下载 MOD。
