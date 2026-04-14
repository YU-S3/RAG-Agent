import asyncio

from app.services.local_llm import LocalLLMClient


async def run() -> None:
    """验证本地 Ollama 模型连通性。"""

    client = LocalLLMClient("ollama", "http://127.0.0.1:11434", "qwen3:8b")
    result = await client.invoke("请用一句话回答：测试通过")
    assert result.model
    assert result.content
    print(result.model)
    print(result.content[:120])


if __name__ == "__main__":
    asyncio.run(run())
