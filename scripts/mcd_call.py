#!/usr/bin/env python3
"""
麦当劳 MCP 直连调用脚本（Windows 兼容）

背景：WorkBuddy 的工具调用层会把整型参数降级为字符串，导致 mcd-mcp 的
beType / orderType / searchType / quantity 等字段全部校验失败。
本脚本绕过工具层，直接以 JSON-RPC 调用 https://mcp.mcd.cn。

同时解决两个编码坑：
1. 请求体中的中文必须用 \\uXXXX 转义（纯 ASCII）——服务端按 GBK 解码请求体，
   直接发 UTF-8 字节会让中文备注变成乱码。
2. 输出时统一 UTF-8，避免 Windows 控制台 GBK 导致的显示异常。

用法:
  python mcd_call.py <tool_name> '<json_args>'
  python mcd_call.py query-nearby-stores '{"beType":1,"searchType":2,"city":"上海市","keyword":"南京路"}'
  python mcd_call.py available-coupons '{}'

鉴权 token 从 ~/.workbuddy/mcp.json 的 mcpServers.mcd-mcp.headers.Authorization 读取。
"""

import json
import os
import sys
import urllib.request
import urllib.error

MCP_URL = "https://mcp.mcd.cn"
CONFIG_PATH = os.path.expanduser("~/.workbuddy/mcp.json")


def load_token() -> str:
    """从 mcp.json 读取 Bearer token。"""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        server = cfg.get("mcpServers", {}).get("mcd-mcp", {})
        auth = server.get("headers", {}).get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth
        return auth
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 读取 {CONFIG_PATH} 失败: {e}", file=sys.stderr)
        return os.environ.get("MCD_TOKEN", "")


# 服务端把「业务上正常、但 success=false」的情况也用 success=false 返回。
# 这些不是错误，调用方不该把它们当失败处理。
SOFT_FAILURES = {
    499: "暂无可领取的优惠券（不是错误，说明当前没有新券可领）",
    600050: "收藏餐厅列表为空（不是错误，需改用 searchType=2 按位置搜索）",
    600057: "门店可能已关闭或不在营业时间（需重新查可送门店换一家）",
}


def normalize_business_result(payload: dict) -> dict:
    """
    给「业务性失败」打上标记，让调用方能区分「真错误」和「正常但没结果」。

    - soft_fail=True  : 业务性返回，不是错误（如没券可领、门店打烊）
    - actionable=True : 需要换一种做法再试（如换门店、换搜索方式）
    """
    if not isinstance(payload, dict):
        return payload
    code = payload.get("code")
    if payload.get("success") is False and code in SOFT_FAILURES:
        out = dict(payload)
        out["soft_fail"] = True
        out["actionable"] = code in (600050, 600057)
        out["hint"] = SOFT_FAILURES[code]
        return out
    return payload


def call(tool_name: str, args: dict) -> dict:
    """调用一个 MCP 工具，返回解析后的结果。"""
    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args},
    }
    # ensure_ascii=True -> 所有中文转成 \uXXXX，规避服务端 GBK 解码问题
    body = json.dumps(payload, ensure_ascii=True).encode("ascii")

    req = urllib.request.Request(
        MCP_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": load_token(),
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "_body": e.read().decode("utf-8", "replace")}
    except Exception as e:  # noqa: BLE001
        return {"_error": str(e)}

    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}

    if "error" in envelope:
        return envelope

    result = envelope.get("result", {})
    text = ""
    for block in result.get("content", []):
        if block.get("type") == "text":
            text = block.get("text", "")
            break

    # 工具文本里混着说明与 JSON 负载，抽出那段 JSON
    start = text.find('{"success"')
    if start >= 0:
        try:
            payload = json.loads(text[start:text.rfind("}") + 1])
            return normalize_business_result(payload)
        except json.JSONDecodeError:
            pass
    # 某些工具（如 auto-bind-coupons）返回的是 Markdown 文本，JSON 在 structuredContent 里
    structured = result.get("structuredContent")
    if structured:
        return normalize_business_result(structured)
    return {"_text": text}


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    tool_name = sys.argv[1]
    raw_args = sys.argv[2] if len(sys.argv) > 2 else "{}"
    args = json.loads(raw_args)

    result = call(tool_name, args)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
