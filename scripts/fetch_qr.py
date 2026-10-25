#!/usr/bin/env python3
"""
抓取麦当劳订单支付页的支付二维码图片。

背景：`payH5Url`（https://m.mcd.cn/mcp/scanToPay?orderId=xxx）是**手机端 H5 单页应用**，
内容由 JS 动态渲染，静态 HTML 里只有 `<div id="root">`，抓不到图片。
因此必须用无头浏览器渲染后再截图。

依赖：playwright（Node 侧安装），本脚本调用 node 执行渲染脚本。
若环境没有 playwright，会退化为「只输出链接 + 提示手动打开」。

用法:
  python fetch_qr.py <orderId> [输出路径]

输出:
  stdout 打印 PNG 的绝对路径；stderr 打印支付链接。
"""

import json
import os
import subprocess
import sys

PAY_URL = "https://m.mcd.cn/mcp/scanToPay?orderId={order_id}"

NODE_CANDIDATES = [
    os.path.expanduser("~/.workbuddy/binaries/node/versions/22.22.2/node.exe"),
    os.path.expanduser("~/.workbuddy/binaries/node/versions/24.14.0/node.exe"),
    "node",
]

PLAYWRIGHT_PATHS = [
    os.path.expanduser("~/.workbuddy/binaries/node/workspace/node_modules"),
    "node_modules",
]

# 渲染脚本（内联到临时文件执行）
RENDER_JS = r"""
const path = require('path');
const url = process.argv[2];
const out = process.argv[3];

let pwPath = null;
for (const p of process.argv.slice(4)) {
  try { require.resolve(path.join(p, 'playwright')); pwPath = p; break; } catch (e) {}
}
if (!pwPath) { console.error('PLAYWRIGHT_NOT_FOUND'); process.exit(3); }
const { chromium } = require(path.join(pwPath, 'playwright'));

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const ctx = await browser.newContext({
      viewport: { width: 390, height: 844 },
      deviceScaleFactor: 2,
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) ' +
                 'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
      isMobile: true, hasTouch: true,
    });
    const page = await ctx.newPage();
    await page.goto(url, { waitUntil: 'networkidle', timeout: 45000 });
    await page.waitForTimeout(2500);

    // 找最大的图片（支付二维码）
    const src = await page.evaluate(() => {
      const imgs = Array.from(document.querySelectorAll('img'));
      let best = null, area = 0;
      for (const im of imgs) {
        const a = im.naturalWidth * im.naturalHeight;
        if (a > area) { area = a; best = im.src; }
      }
      return best;
    });
    if (!src) { console.error('NO_IMAGE'); process.exit(4); }

    // 定位该图片的元素并单独截图（只截二维码，不带边框和文案）
    const box = await page.evaluate((s) => {
      const im = Array.from(document.querySelectorAll('img')).find(i => i.src === s);
      if (!im) return null;
      const r = im.getBoundingClientRect();
      return { x: r.x, y: r.y, width: r.width, height: r.height };
    }, src);

    if (box && box.width > 40 && box.height > 40) {
      await page.screenshot({ path: out, clip: box });
    } else {
      await page.screenshot({ path: out });
    }
    console.log(out);
  } finally {
    await browser.close();
  }
})();
"""


def find_node():
    for c in NODE_CANDIDATES:
        if os.path.isabs(c) and os.path.exists(c):
            return c
        try:
            subprocess.run([c, "--version"], capture_output=True, check=True)
            return c
        except Exception:
            continue
    return None


def decode_qr(img_path: str):
    """解码二维码内容。

    实测（2026-10-24）：麦当劳支付页的二维码内容是
    https://m.mcd.cn/mcp/jumpToApp?orderId=xxx
    —— 不是小程序码，最终跳麦当劳 APP 收银台。
    供人工核对与排查用。OpenCV 不可用时返回 None。
    """
    try:
        import cv2
    except ImportError:
        return None
    img = cv2.imread(img_path)
    if img is None:
        return None
    det = cv2.QRCodeDetector()
    for proc in (img, cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)):
        data, _, _ = det.detectAndDecode(proc)
        if data:
            return data
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    order_id = sys.argv[1].strip()
    out_path = sys.argv[2] if len(sys.argv) > 2 else None
    if out_path is None:
        base = os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp"
        out_path = os.path.join(base, f"mcd_pay_{order_id}.png")
    out_path = os.path.abspath(out_path)

    url = PAY_URL.format(order_id=order_id)
    node = find_node()
    if not node:
        print(f"找不到 node，无法渲染支付页。请手动打开: {url}", file=sys.stderr)
        return 2

    base = os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp"
    js_path = os.path.join(base, f"_mcd_qr_{order_id}.js")
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(RENDER_JS)

    cmd = [node, js_path, url, out_path] + PLAYWRIGHT_PATHS
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           timeout=120)
    except subprocess.TimeoutExpired:
        print(f"渲染超时。请手动打开: {url}", file=sys.stderr)
        return 5
    finally:
        try:
            os.remove(js_path)
        except OSError:
            pass

    if r.returncode != 0 or not os.path.exists(out_path):
        err = (r.stderr or "").strip().splitlines()
        print(f"渲染失败: {err[-1] if err else '未知错误'}", file=sys.stderr)
        print(f"请手动打开: {url}", file=sys.stderr)
        return 6

    print(out_path)
    # 附上二维码内容（实测是 jumpToApp 链接），便于人工核对
    decoded = decode_qr(out_path)
    if decoded:
        print("QR:" + decoded)
    print(url, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
