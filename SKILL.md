# anomaly-mod-monitor — 异常(Anomaly) 新MOD监控

监控 ModDB 上 S.T.A.L.K.E.R. Anomaly 分类（addons）的新发布与近期更新，对比缓存后只报增量。**ModDB 直连被 Cloudflare 挡**（2026-10-30 复测：直连 `GET` 回 `403` + `Just a moment...`；无头 Chrome 也是挑战页），所以抓取要真浏览器——现在**脚本自己起**，不用人开页面。

触发说法：「检查异常MOD」「异常有新MOD吗」。

## 跑一次（就两步）
```bat
py -3 D:\Alife\Storage\Skills\anomaly-mod-monitor\scripts\cdp_grab.py
py -3 D:\Alife\Storage\Skills\anomaly-mod-monitor\scripts\moddb_monitor.py --from-file D:\Alife\Storage\SkillData\moddb_grab.txt --update
```
`cdp_grab.py` 用**独立 user-data-dir** 起一个正常的（非无头）msedge/chrome，连它的 DevTools 调试口，导航到列表页后轮询 `Runtime.evaluate` 跑抽取 JS，抓到就写 `SkillData\moddb_grab.txt` 并把自己起的浏览器进程关掉（窗口挪到屏幕外，不抢你焦点）。2026-10-30 本机实测：连跑三次分别 47 / 47 / 45 条，全是 `2026-10-30T08:39:48+00:00` 这种绝对时间。

参数：`--pages 2`（连抓 `?page=1,2` 并按 slug 去重，默认 1）、`--timeout 100`、`--out`、`--browser`、`--print`。比对端：`--hours 48`、`--max-age 60`（**默认拒绝 60 分钟前的旧抓取文件**——旧文件冒充新结果会一路假报「无新增/更新」；确实要用旧的传 `--max-age 0`）、`--selftest --print`（离线自检，不碰真缓存）。

## 看退出码，别看 stdout
| 脚本 | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| `cdp_grab.py` | 抓到并写盘 | — | 页面有了但一条没抽到（改版/选择器没命中） | Cloudflare 挑战页没过（见兜底写法） | 浏览器起不来或 CDP 连不上 | 抓到但写盘失败 |
| `moddb_monitor.py` | 无变化，**只回一句「无新增/更新」，不去读文件** | 有变化，去读 `SkillData\moddb_report.txt` 汇报 | 抓到东西但解析不出条目 | 没抓到/读写失败/抓取文件太旧（`moddb_error.txt`） | — | — |

三个脚本的 `sink.py`/`cdp_grab.py`/`moddb_monitor.py` 全程零回显，`--print` 才给人看；**参数用错退 9（用法错误）**，不会和表里那些码混。

**报「无新增/更新」前先分清是哪一种**：每次跑都会把一行纯计数写进 `SkillData\moddb_status.txt`，例如
`10-30 11:07 [异常] 退出码1 抓到47 没变化20 窗口外14 新增11 更新5 窗口24小时`。
`抓到47 没变化20` 里 **`没变化` 是「与缓存一致、没写进报告的条数」**（不是「缓存里已有几条」，两者不是一回事：已知但更新过的会算进 `更新`）。`抓到0` 或退出码 2/3/4 = 抓取那一步出问题了。这行只有计数、没有条目名，读它不会把数据搬进对话。

## 兜底写法（`cdp_grab` 回 3 或被站点限流时）
真人开浏览器 `https://www.moddb.com/mods/stalker-anomaly/addons?sort=dateup-desc`，跑这段 JS（抓完自己 POST 给本机接收器）：
```js
(() => {
  const rows = [], seen = new Set();
  document.querySelectorAll('.rowcontent, .row').forEach(row => {
    const a = row.querySelector('a[href*="/mods/stalker-anomaly/addons/"]');
    if (!a) return;
    const slug = (a.getAttribute('href').match(/addons\/([a-z0-9-]+)\/?$/) || [])[1];
    if (!slug || seen.has(slug)) return;
    const titleEl = [...row.querySelectorAll('h4 a, h4, a')].find(e => (e.innerText || '').trim().length > 2) || row.querySelector('h4 a');
    const t = row.querySelector('time[datetime]');
    seen.add(slug);
    rows.push(slug + ' :: ' + ((titleEl && titleEl.innerText) || '').trim().slice(0, 60)
      + ' :: ' + (t ? t.getAttribute('datetime') : ''));
  });
  const f = document.createElement('form');
  f.method = 'POST'; f.action = 'http://127.0.0.1:38472/'; f.style.display = 'none';
  const ta = document.createElement('textarea'); ta.name = 'data'; ta.value = rows.join('\n');
  f.appendChild(ta); document.body.appendChild(f); f.submit();
})();
```
先起接收器再提交：`start /min "" py -3 D:\Alife\Storage\Skills\anomaly-mod-monitor\scripts\sink.py`。
**注意接收器是一次性的、覆盖写**：点分页再抓第二次会把第一页顶掉——要么每页各跑一次比对，要么直接用 `cdp_grab.py --pages N`。
（提交会导航走，所以别指望 JS 的返回值；行数看接收器回的那页，或直接看 grab 文件。）
CDP 与接收器用的是**同一种行格式**，`--from-file` 那边不用改。

## 汇报
按 `moddb_report.txt` 原样转述：抬头是「最近N小时：新增 X 条、更新 Y 条（抓到…，窗口外…）」，下面编号列变化条目，每条 `序. 新|更 标题〔中文名〕 - 月/日 时:分 - 链接`。告警行（`[标题告警]`／`[时间告警]`／`[回填]`／`[覆盖告警]`）只有计数，照抄即可。

**每条都要加中文名**：写在标题后面的全角`〔〕`里，只括中文名，原来那些字段（序号、新/更、时间、链接）一个字都不动。**原标题必须保留**——缓存按标题和 slug 对，删了就对不上了；中文名是给人看的第二份标签。
- 有通行译名就用通行译名：`Zone Metabolism: Physiology Overhaul` → 〔区域代谢：生理大修〕
- 没有通行译名就直译；专有名词、型号、缩写保留原文：`ZM_Raygun` → 〔ZM_射线枪〕、`PIT Fireteam` → 〔PIT 火力小队〕、`S.T.A.L.K.E.R.` 照抄不动
- 标题里的版本号、作者署名（`/ by R1nk1`）、更新标记（`[Update]`）不进中文名，但仍留在原标题里照抄
- 纯型号/缩写没有可译成分的（`MTCompressor`、`LEWDOOM`）就音译或留原文，别硬翻
- 拿不准就直译。**不要为了通顺编一个跟原名对不上的名字**——日报是给人找 MOD 用的，译名和原名对不上比没有译名更糟

## 链接铁律（2026-09-12 主人定稿）
每条必须给真实可点的完整链接，禁占位符：`https://www.moddb.com/mods/stalker-anomaly/addons/{slug}`。

## 注意
- `[覆盖告警]` = 抓到的最旧一条还在窗口里，多半有下一页没抓：`cdp_grab.py --pages 3` 重抓，或把 `--hours` 调小。
- 判更新只认绝对时间**严格晚于**缓存里那条；缓存存页面原始绝对串（`mods[slug].updated`）。旧缓存只有相对串或 `date` 字段的，第一次走 `[回填]`，不会误报整页更新。
- `SkillData\browser-moddb\` 是脚本自己的浏览器 profile（跟日常用的浏览器分开），超过一天的旧副本会自动清，最多留 5 个。
- 检查间隔建议 ≥2 小时；只记录信息，不下载 MOD。
