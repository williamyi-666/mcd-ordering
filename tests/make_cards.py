#!/usr/bin/env python3
"""生成演示视频的片头卡与结尾卡（麦当劳品牌色 + 中文排版）。"""
import os
from PIL import Image, ImageDraw, ImageFont

T = r"C:/Users/Administrator/AppData/Local/Temp/rec"
W, H = 1280, 720

BRAND = {
    "bg": (15, 13, 12),
    "gold": (255, 188, 13),
    "cream": (232, 228, 220),
    "gray": (138, 131, 120),
    "red": (226, 74, 74),
    "brown": (74, 27, 12),
    "green": (99, 153, 34),
    "tan": (250, 199, 117),
}


def font(size, bold=False):
    candidates = [
        r"C:/Windows/Fonts/msyhbd.ttc" if bold else r"C:/Windows/Fonts/msyh.ttc",
        r"C:/Windows/Fonts/simhei.ttf",
        r"C:/Windows/Fonts/msyh.ttc",
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()


def bg_gradient(img):
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(15 + 12 * t)
        g = int(13 + 8 * t)
        b = int(12 + 6 * t)
        d.line([(0, y), (W, y)], fill=(r, g, b))
    # 右上角麦当劳金拱门弧光
    d.arc([W - 420, -220, W + 120, 300], 180, 360, fill=(38, 28, 22), width=26)
    d.arc([W - 380, -180, W + 80, 260], 180, 360, fill=(28, 21, 17), width=18)


def intro():
    img = Image.new("RGB", (W, H), BRAND["bg"])
    bg_gradient(img)
    d = ImageDraw.Draw(img)

    # 顶部小标
    f_sm = font(20)
    d.text((80, 96), "MCDORDERING  ·  WORKBUDDY  SKILL", font=f_sm, fill=BRAND["gray"])

    # 主标题
    f_t = font(72, bold=True)
    d.text((80, 190), "麦当劳一句话点餐", font=f_t, fill=BRAND["cream"])
    f_t2 = font(46, bold=True)
    d.text((80, 296), "mcd-ordering", font=f_t2, fill=BRAND["gold"])

    # 分隔线
    d.rectangle([80, 372, 300, 378], fill=BRAND["gold"])

    # 能力标签
    f_c = font(30)
    caps = ["人数", "忌口", "搭配", "优惠券", "下单"]
    x = 80
    for c in caps:
        w = d.textlength(c, font=f_c)
        d.rounded_rectangle([x, 420, x + w + 36, 480], 8, outline=BRAND["tan"], width=2)
        d.text((x + 18, 433), c, font=f_c, fill=BRAND["tan"])
        x += w + 52

    # 底部说明
    f_b = font(22)
    d.text((80, 540), "演示数据全部来自麦当劳 MCP 真实接口", font=f_b, fill=BRAND["gray"])
    d.text((80, 578), "2026-10-24  ·  上海南京路", font=f_b, fill=BRAND["gray"])

    # 右侧像素元素装饰
    px = 940
    d.rectangle([px, 200, px + 40, 240], fill=BRAND["brown"])       # 可乐
    d.rectangle([px + 44, 200, px + 84, 240], fill=BRAND["tan"])     # 汉堡
    d.rectangle([px, 250, px + 40, 290], fill=BRAND["gold"])         # 薯条
    d.rectangle([px + 44, 250, px + 84, 290], fill=BRAND["green"])   # 派
    d.rectangle([px, 300, px + 40, 340], fill=BRAND["red"])          # 番茄
    d.rectangle([px + 44, 300, px + 84, 340], fill=BRAND["cream"])   # 奶

    img.save(os.path.join(T, "intro.png"))
    print("intro.png ok")


def outro():
    img = Image.new("RGB", (W, H), BRAND["bg"])
    bg_gradient(img)
    d = ImageDraw.Draw(img)

    f_t = font(64, bold=True)
    d.text((80, 210), "一句话，点完就走", font=f_t, fill=BRAND["cream"])

    f_g = font(34, bold=True)
    d.text((80, 310), "mcd-ordering", font=f_g, fill=BRAND["gold"])

    d.rectangle([80, 380, 300, 386], fill=BRAND["gold"])

    f_c = font(26)
    lines = [
        "外送 / 到店自取 / 得来速  三种场景",
        "忌口满足不了会明说，不静默降级",
        "优惠券自动领 + 择优 + 有效期提醒",
        "算价后停下等你确认，绝不自动下单",
    ]
    y = 430
    for ln in lines:
        d.text((80, y), "·  " + ln, font=f_c, fill=BRAND["gray"])
        y += 46

    f_b = font(22)
    d.text((80, 640), "~/.workbuddy/skills/mcd-ordering/", font=f_b, fill=BRAND["gray"])

    img.save(os.path.join(T, "outro.png"))
    print("outro.png ok")


def section():
    """章节卡：游戏演示"""
    img = Image.new("RGB", (W, H), BRAND["bg"])
    bg_gradient(img)
    d = ImageDraw.Draw(img)
    f_t = font(60, bold=True)
    d.text((80, 280), "附赠：McDCraft 随点随玩", font=f_t, fill=BRAND["cream"])
    f_s = font(28)
    d.text((80, 372), "麦当劳 × 我的世界风体素跑酷", font=f_s, fill=BRAND["gold"])
    d.rectangle([80, 428, 300, 434], fill=BRAND["gold"])
    f_b = font(22)
    d.text((80, 480), "收集可乐 / 汉堡 / 薯条，躲开倒垃圾工，3 个可合成升级版", font=f_b, fill=BRAND["gray"])
    img.save(os.path.join(T, "section_game.png"))
    print("section_game.png ok")


if __name__ == "__main__":
    intro()
    section()
    outro()
