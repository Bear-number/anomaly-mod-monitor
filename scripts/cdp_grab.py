#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""异常（ModDB）列表页的自动抓取——脚本自己起**真浏览器**，用 CDP 取数据，不用人开页面

为什么要真浏览器：ModDB 前面是 Cloudflare。2026-10-30 本机复测，直连 `GET` 回 `403` +
`Just a moment...`；无头 Chrome 拿到的也是挑战页（2026-10-22 实测）。而真人开浏览器一直抓得动，
所以这一步只能借真浏览器：用**独立的 user-data-dir** 起一个正常的（非无头）msedge/chrome 窗口，
连它的 DevTools 调试口，导航后轮询 `Runtime.evaluate` 跑抽取 JS，抓到就写盘、把自己起的那个
浏览器进程关掉。数据只在脚本与文件之间走，不进对话（和接收器解决的是同一个问题）。

抽取 JS 与 SKILL.md 里那段一致（ModDB 标题在 `h4 a`、绝对时间在 `time[datetime]`），输出每行
`slug :: 标题 :: 绝对时间`，直接交给 `moddb_monitor.py --from-file` 比对，格式与接收器落盘一致。

退出码：0 抓到并写盘 / 2 页面有了但一条都没抽到（改版或选择器没命中）/ 3 Cloudflare 挑战页没过去
        / 4 浏览器起不来或 CDP 连不上 / 5 抓到但写盘失败
全程零 stdout（`--print` 才回一行结论），失败原因写 `SkillData\cdp_moddb_error.txt`。

用法：
  py -3 cdp_grab.py --print            # 起浏览器、抓一页、写 grab 文件
  py -3 cdp_grab.py --pages 2          # 连抓 ?page=1,2（按 slug 去重后累加）
比对：py -3 moddb_monitor.py --from-file <out> --update
"""
import sys, os, json, time, socket, struct, base64, argparse, subprocess, shutil
import urllib.request
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

BASE = "https://www.moddb.com/mods/stalker-anomaly/addons?sort=dateup-desc"
DATA = r"D:\Alife\Storage\SkillData"
DEFAULT_OUT = os.path.join(DATA, "moddb_grab.txt")
ERROR = os.path.join(DATA, "cdp_moddb_error.txt")
PROFILE = os.path.join(DATA, "browser-moddb")
NAME = "异常"
SKILL = "anomaly-mod-monitor"

EXIT_OK = 0
EXIT_NO_ROWS = 2
EXIT_CHALLENGE = 3
EXIT_BROWSER = 4
EXIT_WRITE = 5
LOCAL_TZ = timezone(timedelta(hours=8))

# 页内抽取：一次把「行 + 页面状态」一起回出来，脚本才分得清「没抓到」和「被 CF 挡着」这两种失败
JS = r"""(() => {
  const rows = [], seen = new Set();
  document.querySelectorAll('.rowcontent, .row').forEach(row => {
    const a = row.querySelector('a[href*="/mods/stalker-anomaly/addons/"]');
    if (!a) return;
    const slug = (a.getAttribute('href').match(/addons\/([a-z0-9-]+)\/?$/) || [])[1];
    if (!slug || seen.has(slug)) return;
    const titleEl = [...row.querySelectorAll('h4 a, h4, a')].find(e => (e.innerText || '').trim().length > 2)
      || row.querySelector('h4 a');
    const t = row.querySelector('time[datetime]');
    seen.add(slug);
    rows.push(slug + ' :: ' + ((titleEl && titleEl.innerText) || '').trim().slice(0, 60)
      + ' :: ' + (t ? t.getAttribute('datetime') : ''));
  });
  return JSON.stringify({
    title: document.title,
    url: location.href,
    challenge: /just a moment|verifying|attention required/i.test(document.title)
      || !!document.querySelector('iframe[src*="challenges.cloudflare.com"], input[name="cf_chl_opt"]'),
    count: rows.length,
    text: rows.join('\n')
  });
})()"""


def write_error(reason, quiet):
    try:
        os.makedirs(DATA, exist_ok=True)
        with open(ERROR, "w", encoding="utf-8") as handle:
            handle.write(f"{datetime.now(LOCAL_TZ).isoformat()} [{SKILL}] cdp_grab：{reason}\n")
    except Exception:
        pass
    if not quiet:
        print(f"[{NAME}] cdp_grab 失败：{reason}")


def find_browser():
    """自己传 --browser 优先；否则按常见路径 + PATH 找 msedge/chrome"""
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for name in ("msedge", "chrome"):
        found = shutil.which(name)
        if found:
            candidates.insert(0, found)
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def run_profile(base_profile):
    """每次一个独立 profile：上一轮的浏览器进程还没退干净时，共用 profile 会让新起的实例直接附身到旧
    进程上、调试口根本不开（本机实测踩到）。留下 24 小时内的目录不碍事，超时的顺手清掉。"""
    stamp = datetime.now(LOCAL_TZ).strftime("%Y%m%d-%H%M%S")
    keep = []
    try:
        if os.path.isdir(base_profile):
            for name in os.listdir(base_profile):
                full = os.path.join(base_profile, name)
                if not os.path.isdir(full):
                    continue
                if time.time() - os.path.getmtime(full) > 86400:
                    shutil.rmtree(full, ignore_errors=True)
                else:
                    keep.append(full)
    except Exception:
        pass
    if len(keep) >= 6:
        for stale in sorted(keep)[:len(keep) - 5]:
            shutil.rmtree(stale, ignore_errors=True)
    return os.path.join(base_profile, stamp)


def launch(browser, port, profile, start_url):
    os.makedirs(profile, exist_ok=True)
    args = [browser, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
            "--no-first-run", "--no-default-browser-check", "--disable-session-crashed-bubble",
            "--window-size=1280,1000", "--window-position=-3200,-3200", "--new-window", start_url]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_browser(browser, base_profile, start_url, patience):
    """先用**固定 profile**：Nexus 那个列表页要靠它留下的 cookie 才渲染（每次换全新 profile 时
    十次有七八次只回壳子、0 条）。固定 profile 被上一轮没退干净的进程占着时调试口永远不起来，
    这时退到一次性 profile 再试一次——ModDB 两种都稳，Nexus 靠这条不掉链子。"""
    for profile in (base_profile, run_profile(base_profile)):
        port = free_port()
        process = launch(browser, port, profile, start_url)
        ws_url = wait_devtools(port, time.time() + patience)
        if ws_url:
            return process, Cdp(ws_url)
        try:
            process.terminate()
            process.wait(timeout=6)
        except Exception:
            process.kill()
    return None, None


def http_json(url, timeout=2.0):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "ignore"))


def wait_devtools(port, deadline):
    """浏览器冷启动要几秒；起来了才有 /json/version 和 page 目标"""
    while time.time() < deadline:
        try:
            http_json(f"http://127.0.0.1:{port}/json/version")
            pages = [target for target in http_json(f"http://127.0.0.1:{port}/json/list") if target.get("type") == "page"]
            if pages:
                return pages[0]["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.4)
    return None


class Cdp:
    """DevTools 协议最小客户端：handshake + 发文本帧 + 按 id 收回复（纯标准库，不装 websockets）"""

    def __init__(self, ws_url):
        parts = urlparse(ws_url)
        self.sock = socket.create_connection((parts.hostname, parts.port or 80), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        path = parts.path + (("?" + parts.query) if parts.query else "")
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {parts.hostname}:{parts.port}\r\n"
                           "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        self.buffer = b""
        self.fragments = b""
        while b"\r\n\r\n" not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("CDP handshake 断了")
            self.buffer += chunk
        head, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
        if b"101" not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError("CDP handshake 不是 101：" + head[:120].decode("ignore"))
        self.next_id = 0

    def _frame(self, payload):
        header = bytearray([0x81])
        length = len(payload)
        mask = os.urandom(4)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        header += mask
        return bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

    def send(self, method, params=None):
        self.next_id += 1
        call_id = self.next_id
        self.sock.sendall(self._frame(json.dumps({"id": call_id, "method": method, "params": params or {}}).encode()))
        while True:
            message = json.loads(self._read_message())
            if message.get("id") == call_id:
                if message.get("error"):
                    raise RuntimeError(f"{method}：{message['error'].get('message', message['error'])}")
                return message.get("result", {})

    def close_browser(self):
        try:
            self.send("Browser.close")
        except Exception:
            pass

    def evaluate(self, expression):
        result = self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        return (result.get("result") or {}).get("value")

    def _need(self, count):
        while len(self.buffer) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("CDP 连接被关掉")
            self.buffer += chunk
        taken, self.buffer = self.buffer[:count], self.buffer[count:]
        return taken

    def _read_message(self):
        while True:
            first, second = self._need(2)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._need(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._need(8))[0]
            payload = self._need(length) if length else b""
            opcode = first & 0x0F
            if opcode == 8:
                raise ConnectionError("CDP 那头把连接关了")
            if opcode == 9:
                self.sock.sendall(bytes([0x8A, 0x80 | len(payload)]) + payload)
                continue
            if opcode in (0, 1, 2):
                self.fragments += payload
                if first & 0x80:
                    text, self.fragments = self.fragments, b""
                    return text.decode("utf-8", "ignore")


def grab(cdp, deadline, settle):
    """轮着等页面出条目：真浏览器过 CF 也要几秒，一次没抓到就判失败太急"""
    last = None
    while time.time() < deadline:
        try:
            raw = cdp.evaluate(JS)
        except Exception:
            raw = None
        if raw:
            try:
                last = json.loads(raw)
            except Exception:
                last = None
            if last and last.get("count"):
                return last
        time.sleep(settle)
    return last


class ArgParser(argparse.ArgumentParser):
    """参数用错时 argparse 默认 exit(2)——那个码在本脚本里另有所指，会骗到读退出码的人；
    这里统一退成 9（用法错误），用法行照样给到 stderr，也不往 stdout 吐东西"""

    def error(self, message):
        sys.stderr.write("用法错误：" + message + "（看脚本开头的用法说明）\n")
        raise SystemExit(9)


def main(argv=None):
    parser = ArgParser(add_help=False)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--browser")
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--settle", type=float, default=2.0)
    parser.add_argument("--print", dest="echo", action="store_true")
    args = parser.parse_args(argv)
    quiet = not args.echo

    browser = args.browser or find_browser()
    if not browser:
        write_error("这台机器没找到 msedge/chrome，改走接收器那条老路子", quiet)
        return EXIT_BROWSER

    process = None
    rows = []
    seen_ids = set()
    status = {}
    try:
        process, cdp = open_browser(browser, PROFILE, BASE + "&page=1",
                                     min(max(20.0, args.settle * 6), args.timeout * 0.35))
        if cdp is None:
            write_error("起浏览器两次都等不到调试口（固定 profile 与一次性 profile 各一次）——"
                        "窗口被组策略拦了，或有别的实例占着 profile", quiet)
            return EXIT_BROWSER
        pages = max(1, min(args.pages, 10))
        per_page = max(15.0, args.timeout / pages)
        for page in range(1, pages + 1):
            if page > 1:
                cdp.send("Page.navigate", {"url": BASE + f"&page={page}"})
                time.sleep(max(2.0, args.settle))
            snapshot = grab(cdp, time.time() + per_page, args.settle)
            if not snapshot:
                write_error(f"第 {page} 页连页面状态都没拿到（多半卡在加载）", quiet)
                return EXIT_NO_ROWS
            status = snapshot
            for line in (snapshot.get("text") or "").splitlines():
                slug = line.split("::")[0].strip()
                if slug and slug not in seen_ids:
                    seen_ids.add(slug)
                    rows.append(line)
        if status.get("challenge"):
            write_error(f"Cloudflare 挑战页没过去（页面标题「{status.get('title')}」）"
                        "：先真人开一次浏览器把这站过了（同一个 profile 会记住），再跑这里；还不行就用接收器", quiet)
            return EXIT_CHALLENGE
        if not rows:
            write_error(f"页面有了但一条都没抽到（标题「{status.get('title')}」）——选择器跟页面改版对不上了", quiet)
            return EXIT_NO_ROWS
        try:
            os.makedirs(os.path.dirname(args.out), exist_ok=True)
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write("\n".join(rows) + "\n")
        except Exception as write_failure:
            write_error(f"抓到 {len(rows)} 条但写 {args.out} 失败：{write_failure}", quiet)
            return EXIT_WRITE
        try:
            if os.path.exists(ERROR):
                os.remove(ERROR)
        except Exception:
            pass
        if not quiet:
            print(f"[{NAME}] cdp_grab 抓到 {len(rows)} 条（{pages} 页）→ {args.out}")
        return EXIT_OK
    except Exception as crash:
        write_error(f"跑挂了：{crash.__class__.__name__} {crash}", quiet)
        return EXIT_BROWSER
    finally:
        if process is not None:
            try:
                cdp.close_browser()
            except Exception:
                pass
            try:
                process.terminate()
                process.wait(timeout=8)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass


if __name__ == "__main__":
    sys.exit(main())
