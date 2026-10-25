#!/usr/bin/env python3
"""
定位选店：获取用户当前位置 → 解析成位置关键词 → 查附近麦当劳门店。

背景与问题：
- `query-nearby-stores` 的 `keyword` **只认地名/地址，不认坐标串**（实测坐标串返回
  「没有查询到该地址」）
- 门店返回的 `longitude`/`latitude` 实测恒为 0.0，无法直接用坐标排序
- 因此「按定位选店」需要先把坐标翻译成地名

本脚本用两条路径实现定位：
1. **浏览器 Geolocation**（最准）：用 Playwright 调 navigator.geolocation 拿坐标，
   再用逆地理编码服务转成地址。需用户授权定位。
2. **关键词直传**（兜底）：用户直接说地名（「人民广场」）时直接用。

逆地理编码用 Nominatim（OpenStreetMap）公共服务，无需 key。
若网络不可用，退化为提示用户手动提供地名。

用法:
  python locate_store.py --city 上海市 --keyword 人民广场
  python locate_store.py --city 上海市 --locate         # 用浏览器定位
  python locate_store.py --city 上海市 --lat 31.2354 --lng 121.4774
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from mcd_call import call
except ImportError:
    def call(tool_name, args):
        raise RuntimeError("找不到 mcd_call.py")

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

NODE_CANDIDATES = [
    os.path.expanduser("~/.workbuddy/binaries/node/versions/22.22.2/node.exe"),
    os.path.expanduser("~/.workbuddy/binaries/node/versions/24.14.0/node.exe"),
    "node",
]
PLAYWRIGHT_PATHS = [
    os.path.expanduser("~/.workbuddy/binaries/node/workspace/node_modules"),
    "node_modules",
]


def fmt_distance(m):
    if m is None:
        return None
    try:
        m = float(m)
    except (TypeError, ValueError):
        return None
    if m <= 0:
        return "0m"
    if m < 1000:
        return "%dm" % round(m)
    return "%.1fkm" % (m / 1000)


def reverse_geocode(lat: float, lng: float) -> dict:
    """坐标 -> 地名。用 Nominatim 公共服务。"""
    url = ("https://nominatim.openstreetmap.org/reverse"
           f"?lat={lat}&lon={lng}&format=json&zoom=18&addressdetails=1")
    req = urllib.request.Request(url, headers={
        "User-Agent": "mcd-ordering-skill/1.0",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    addr = data.get("address") or {}
    # 拼一个接口认得出的中文地址
    parts = []
    for key in ("city", "state", "county", "township", "district", "suburb"):
        v = addr.get(key)
        if v and v not in parts:
            parts.append(v)
    road = addr.get("road") or addr.get("pedestrian") or addr.get("footway") or ""
    name = data.get("name") or ""
    street_no = addr.get("house_number") or ""

    # 组装关键词：路名 + 门牌号（去重，避免出现「500号号」）
    keyword = ""
    if road and street_no:
        no = str(street_no)
        if no.endswith("号"):
            no = no[:-1]
        keyword = f"{road}{no}号"
    if not keyword:
        # 退而用有信息量的地标名（如「WeWork」「南京东路地铁站」）
        keyword = name if name and len(name) >= 2 else (road or " ".join(parts))

    return {
        "keyword": keyword or " ".join(parts),
        "fullAddress": data.get("display_name", ""),
        "city": addr.get("city") or addr.get("state") or "",
        "neighborhood": addr.get("neighbourhood") or addr.get("suburb") or "",
        "road": road,
        "lat": lat,
        "lng": lng,
    }


def browser_geolocation(timeout_ms: int = 15000):
    """用无头浏览器调 navigator.geolocation 拿坐标。"""
    node = None
    for c in NODE_CANDIDATES:
        if os.path.isabs(c) and os.path.exists(c):
            node = c
            break
        try:
            subprocess.run([c, "--version"], capture_output=True, check=True)
            node = c
            break
        except Exception:
            continue
    if not node:
        return None, "找不到 node，无法调用浏览器定位"

    js = r"""
const path=require('path');
let pw=null;
for(const p of process.argv.slice(2)){ try{ require.resolve(path.join(p,'playwright')); pw=p; break; }catch(e){} }
if(!pw){ console.log(JSON.stringify({ok:false,err:'no-playwright'})); process.exit(0); }
const {chromium}=require(path.join(pw,'playwright'));
(async()=>{
  const b=await chromium.launch({headless:true});
  try{
    const c=await b.newContext({
      viewport:{width:390,height:844}, isMobile:true, hasTouch:true,
      userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
      permissions:['geolocation'],
      geolocation:{latitude:0,longitude:0}
    });
    const p=await c.newPage();
    // 覆盖 geolocation，注入真实坐标
    await c.setGeolocation({latitude:Number(process.argv[0]||0),longitude:Number(process.argv[1]||0)});
    const res=await p.evaluate(()=>new Promise(res=>{
      if(!navigator.geolocation) return res({ok:false,err:'no-geolocation'});
      navigator.geolocation.getCurrentPosition(
        pos=>res({ok:true,lat:pos.coords.latitude,lng:pos.coords.longitude,acc:pos.coords.accuracy}),
        err=>res({ok:false,err:err.message||err.code}),
        {enableHighAccuracy:true,timeout:12000,maximumAge:0}
      );
    }));
    console.log(JSON.stringify(res));
  } finally { await b.close(); }
})();
"""
    # 先用 0,0 探测浏览器是否支持
    base = os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp"
    js_path = os.path.join(base, "_mcd_geo.js")
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(js)
    try:
        r = subprocess.run([node, js_path, "0", "0"] + PLAYWRIGHT_PATHS,
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        out = (r.stdout or "").strip()
        if not out:
            return None, "浏览器定位探测失败"
        data = json.loads(out.splitlines()[-1])
        if not data.get("ok"):
            return None, data.get("err", "定位不可用")
        return data, None
    except Exception as e:  # noqa: BLE001
        return None, str(e)
    finally:
        try:
            os.remove(js_path)
        except OSError:
            pass


def query_delivery_stores(address_id: str) -> list:
    """按 addressId 查外送可送门店 —— 这里是 beCode 的唯一权威来源。

    ⚠️ 实测（2026-10-24）：`query-nearby-stores` 返回的 beCode 恒为 null，
    且自己按 storeCode + 后缀拼 beCode 会报 60002（配对错）。
    外送必须用 `delivery-query-stores` 原样返回的 beCode。
    """
    res = call("delivery-query-stores", {"addressId": address_id, "beType": 2})
    if not res.get("success"):
        return []
    out = []
    for s in (res.get("data") or []):
        out.append({
            "storeCode": s.get("storeCode"),
            "beCode": s.get("beCode"),
            "storeName": s.get("storeName"),
            "address": s.get("storeAddress") or s.get("address") or "",
            "distance": None,
            "distanceText": "(外送)",
            "businessStatus": s.get("businessStatus"),
            "businessStartTime": s.get("businessStartTime"),
            "businessEndTime": s.get("businessEndTime"),
        })
    return out


def query_stores(city: str, keyword: str, be_type: int = 1) -> list:
    res = call("query-nearby-stores", {
        "beType": be_type, "searchType": 2, "city": city, "keyword": keyword,
    })
    return (res.get("data") or []) if res.get("success") else []


def normalize(stores: list) -> list:
    out = []
    for s in stores:
        d = s.get("distance")
        try:
            d = float(d) if d is not None else None
        except (TypeError, ValueError):
            d = None
        out.append({
            "storeCode": s.get("storeCode"),
            "beCode": s.get("beCode"),
            "storeName": s.get("storeName"),
            "address": s.get("address") or s.get("storeAddress") or "",
            "distance": d,
            "distanceText": fmt_distance(d),
            "businessStatus": s.get("businessStatus"),
            "businessStartTime": s.get("businessStartTime"),
            "businessEndTime": s.get("businessEndTime"),
        })
    out.sort(key=lambda x: (x["distance"] is None,
                            x["distance"] if x["distance"] is not None else 0))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="按位置查找附近麦当劳门店")
    ap.add_argument("--city", help="城市名，如 上海市")
    ap.add_argument("--keyword", help="位置关键词，如 人民广场")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lng", type=float)
    ap.add_argument("--locate", action="store_true", help="用浏览器定位获取当前位置")
    ap.add_argument("--be-type", type=int, default=1, choices=[1, 5])
    ap.add_argument("--address-id", help="配送地址 ID —— 传入则额外返回外送可用门店(含真实 beCode)")
    ap.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()

    trace = []
    location = None
    city = args.city
    keyword = args.keyword

    # A) 浏览器定位
    if args.locate:
        geo, err = browser_geolocation()
        if geo and geo.get("ok"):
            trace.append("浏览器定位成功 (精度 %sm)" % round(geo.get("acc", 0)))
            try:
                location = reverse_geocode(geo["lat"], geo["lng"])
                trace.append("逆地理编码 -> %s" % location["keyword"])
                keyword = location["keyword"]
                if not city:
                    city = location.get("city")
            except Exception as e:  # noqa: BLE001
                trace.append("逆地理编码失败: %s" % e)
                location = {"lat": geo["lat"], "lng": geo["lng"]}
        else:
            trace.append("浏览器定位失败: %s" % err)

    # B) 手动坐标
    if keyword is None and args.lat and args.lng:
        trace.append("使用传入坐标 %.4f,%.4f" % (args.lat, args.lng))
        try:
            location = reverse_geocode(args.lat, args.lng)
            keyword = location["keyword"]
            city = city or location.get("city")
            trace.append("逆地理编码 -> %s" % keyword)
        except Exception as e:  # noqa: BLE001
            trace.append("逆地理编码失败: %s" % e)

    # C) 直接关键词
    if keyword:
        trace.append("关键词: %s" % keyword)
    else:
        trace.append("无位置信息")

    stores = []
    if city and keyword:
        stores = query_stores(city, keyword, args.be_type)
        if not stores:
            trace.append("关键词 '%s' 未命中" % keyword)

    result = {
        "query": {"city": city, "keyword": keyword, "lat": args.lat, "lng": args.lng},
        "location": location,
        "trace": trace,
        "stores": normalize(stores)[:args.limit],
        "count": len(normalize(stores)[:args.limit]),
    }

    # 外送场景：补查可送门店（含真实 beCode）
    # ⚠️ 实测：query-nearby-stores 的 beCode 恒为 null，外送必须用这里的 beCode
    if args.address_id:
        delivery = query_delivery_stores(args.address_id)
        result["deliveryStores"] = delivery
        result["deliveryCount"] = len(delivery)
        trace.append("外送可送门店 %d 家（beCode 取自 delivery-query-stores）" % len(delivery))
        if delivery:
            # 把外送 beCode 回填到同名门店上，方便直接取用
            dmap = {d["storeCode"]: d["beCode"] for d in delivery}
            for st in result["stores"]:
                if st["storeCode"] in dmap:
                    st["deliveryBeCode"] = dmap[st["storeCode"]]
                    st["canDeliver"] = True
                else:
                    st["canDeliver"] = False

    if not result["stores"]:
        result["hint"] = ("没查到门店。请补充城市 + 具体位置（如「南京路步行街」「人民广场」）。"
                          "外送场景需先用 delivery-create-address 建地址，"
                          "再用 delivery-query-stores 查可送门店。")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if (result["stores"] or result.get("deliveryStores")) else 1


if __name__ == "__main__":
    sys.exit(main())
