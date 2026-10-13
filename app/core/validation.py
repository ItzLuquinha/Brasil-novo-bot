from __future__ import annotations

MAX_SNOWFLAKE = 9_223_372_036_854_775_807


def parse_snowflake(value: str) -> int:
    text = str(value).strip()
    if not text.isdigit():
        raise ValueError("ID inválido. Use o ID completo do Discord.")
    result = int(text)
    if result < 1 or result > MAX_SNOWFLAKE:
        raise ValueError("ID inválido. O valor está fora do intervalo permitido.")
    return result


def clean_text(value: str, maximum: int) -> str:
    return " ".join(str(value).split())[:maximum]
