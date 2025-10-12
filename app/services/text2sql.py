import asyncio
from typing import Protocol


class Text2SQLProvider(Protocol):
    async def to_sql(self, prompt: str) -> str:  # pragma: no cover - interface
        ...


class DummyProvider:
    async def to_sql(self, prompt: str) -> str:
        # naive stub: map a few keywords to example SQL
        await asyncio.sleep(0.01)
        if "hemoglobin" in prompt.lower():
            return (
                "SELECT patient_id, value FROM observation "
                "WHERE code = 'hb' AND value < 12"
            )
        if "over 65" in prompt.lower() or ">65" in prompt:
            return "SELECT id, birthdate FROM patient WHERE age > 65"
        return "SELECT * FROM patient LIMIT 10"


class Text2SQLService:
    def __init__(self, provider: Text2SQLProvider | None = None):
        self.provider = provider or DummyProvider()

    async def generate_sql(self, prompt: str) -> str:
        return await self.provider.to_sql(prompt)
