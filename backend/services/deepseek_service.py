from __future__ import annotations

import httpx


class DeepSeekService:
    async def test_connection(self, api_key: str, base_url: str = "https://api.deepseek.com", model: str = "deepseek-chat") -> dict:
        if not api_key:
            return {"ok": False, "error": "API Key 为空"}
        try:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "请回复: 连接成功"}],
                "temperature": 0.1,
                "max_tokens": 32,
            }
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(f"{base_url.rstrip('/')}/chat/completions", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=payload)
            r.raise_for_status()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def summarize_signal(self, api_key: str, base_url: str, model: str, signal: dict, market_summary: str, risk_summary: str) -> str:
        if not api_key:
            return "DeepSeek 未配置，使用本地交易理由。"
        try:
            content = (
                "你是量化助手，只能做解释不能做下单决策。"
                f"\n信号: {signal}"
                f"\n行情摘要: {market_summary}"
                f"\n风控状态: {risk_summary}"
                "\n请输出中文交易理由(80字内)。"
            )
            payload = {
                "model": model or "deepseek-chat",
                "messages": [{"role": "user", "content": content}],
                "temperature": 0.2,
                "max_tokens": 120,
            }
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.post(f"{base_url.rstrip('/')}/chat/completions", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=payload)
            r.raise_for_status()
            data = r.json()
            return (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip() or "DeepSeek 返回空内容"
        except Exception:
            return "DeepSeek 调用失败，已降级为本地理由。"
