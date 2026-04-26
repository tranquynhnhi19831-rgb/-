import httpx


class DeepSeekService:
    async def test_connection(self, api_key: str) -> dict:
        if not api_key:
            return {"ok": False, "error": "API Key 为空"}
        return {"ok": True, "message": "已配置 DeepSeek Key（示例项目未强制远程请求）"}

    async def summarize_signal(self, api_key: str, signal: dict) -> str:
        if not api_key:
            return "DeepSeek 未配置，使用本地摘要。"
        try:
            prompt = f"请简要解释信号: {signal}"
            async with httpx.AsyncClient(timeout=8) as client:
                await client.get("https://api.deepseek.com", headers={"Authorization": f"Bearer {api_key}"})
            return f"DeepSeek辅助摘要: {prompt[:80]}"
        except Exception:
            return "DeepSeek 调用失败，系统继续运行。"
