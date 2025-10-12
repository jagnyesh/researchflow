import asyncio

from app.services.text2sql import Text2SQLService


def test_text2sql_dummy():
    svc = Text2SQLService()
    sql = asyncio.get_event_loop().run_until_complete(svc.generate_sql("hemoglobin < 12"))
    assert "SELECT" in sql
