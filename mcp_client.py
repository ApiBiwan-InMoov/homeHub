#!/usr/bin/env python3
"""
Minimal MCP client for HomeHub (Python, Pi-friendly).

Features:
- Fetches the manifest from HomeHub (/llm/mcp/manifest or custom URL)
- Lists tools and basic endpoints
- Invokes a tool by name (best-effort) using its method/url from manifest
- Simple prompt-to-generate helper using /llm/generate

Usage examples:
  python mcp_client.py --host http://localhost:8080 manifest
  python mcp_client.py --host http://localhost:8080 tools
  python mcp_client.py --host http://localhost:8080 call toggle_relay --params '{"relay":1}'
  python mcp_client.py --host http://localhost:8080 generate "Bonjour, résume la météo"

Notes:
- No extra deps beyond 'requests' (already in requirements.txt)
- Keep commands short; this is not a full MCP runtime, just a helper
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

import requests


def fetch_manifest(base: str) -> Dict[str, Any]:
    url = base.rstrip("/") + "/llm/mcp/manifest"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()


def list_tools(manifest: Dict[str, Any]) -> None:
    tools = manifest.get("tools", []) or []
    if not tools:
        print("No tools in manifest.")
        return
    for t in tools:
        name = t.get("name", "(unnamed)")
        method = t.get("method", "GET")
        url = t.get("url", "")
        desc = t.get("description", "")
        params = t.get("params", {})
        print(f"- {name} [{method}] {url}\n    desc: {desc}\n    params: {params}")


def call_tool(base: str, manifest: Dict[str, Any], tool_name: str, params: Dict[str, Any]) -> None:
    tools = manifest.get("tools", []) or []
    tool = next((t for t in tools if t.get("name") == tool_name), None)
    if not tool:
        raise SystemExit(f"Tool '{tool_name}' not found in manifest")

    method = (tool.get("method") or "GET").upper()
    url_tpl = tool.get("url") or ""

    # Substitute path params {key}
    url = url_tpl
    for k, v in params.items():
        placeholder = "{" + k + "}"
        if placeholder in url:
            url = url.replace(placeholder, str(v))

    full_url = base.rstrip("/") + url

    if method == "GET":
        r = requests.get(full_url, params={k: v for k, v in params.items() if "{"+k+"}" not in url_tpl}, timeout=15)
    else:
        r = requests.request(method, full_url, json=params, timeout=15)

    try:
        r.raise_for_status()
    except Exception:
        print(f"HTTP {r.status_code}: {r.text}")
        raise

    try:
        print(json.dumps(r.json(), indent=2, ensure_ascii=False))
    except Exception:
        print(r.text)


def generate(base: str, prompt: str, max_tokens: int = 256) -> None:
    url = base.rstrip("/") + "/llm/generate"
    r = requests.post(url, json={"prompt": prompt, "max_tokens": max_tokens}, timeout=30)
    r.raise_for_status()
    j = r.json()
    print(j.get("text") or json.dumps(j, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="Minimal MCP client for HomeHub")
    ap.add_argument("command", choices=["manifest", "tools", "call", "generate", "trace"], help="Action à exécuter")
    ap.add_argument("value", nargs="?", help="prompt (pour generate) ou nom du tool (pour call)")
    ap.add_argument("--host", default="http://localhost:8080", help="URL base de HomeHub (ex: http://localhost:8080)")
    ap.add_argument("--params", default="{}", help="JSON des paramètres pour call")
    ap.add_argument("--max-tokens", type=int, default=256, help="max tokens pour generate")
    args = ap.parse_args()

    try:
        manifest = fetch_manifest(args.host)
    except Exception as e:
        raise SystemExit(f"Failed to fetch manifest: {e}")

    if args.command == "manifest":
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        return

    if args.command == "tools":
        list_tools(manifest)
        return

    if args.command == "call":
        if not args.value:
            raise SystemExit("Specify tool name to call")
        try:
            params = json.loads(args.params)
        except Exception as e:
            raise SystemExit(f"Invalid params JSON: {e}")
        call_tool(args.host, manifest, args.value, params)
        return

    if args.command == "generate":
        prompt = args.value or ""
        if not prompt.strip():
            raise SystemExit("Provide a prompt for generate")
        generate(args.host, prompt, args.max_tokens)
        return

    if args.command == "trace":
        # Step-by-step trace: show manifest summary, chosen tool, request/response
        print("[1/4] Fetching manifest…")
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        if not args.value:
            raise SystemExit("Specify tool name to trace (value argument)")
        try:
            params = json.loads(args.params)
        except Exception as e:
            raise SystemExit(f"Invalid params JSON: {e}")
        print("[2/4] Tool:", args.value)
        print("[3/4] Params:", json.dumps(params, ensure_ascii=False))
        print("[4/4] Response:")
        call_tool(args.host, manifest, args.value, params)
        return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)