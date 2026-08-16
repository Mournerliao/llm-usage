"""LLM 用量采集器集合。每个采集器返回 list[Record]。"""
from dataclasses import dataclass, asdict
import json


@dataclass
class Record:
    source: str
    model: str
    date: str                 # YYYY-MM-DD（按运行者本地时区）
    requests: int
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict:
        return asdict(self)


def save_records(records, path):
    path = str(path)
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([r.to_dict() for r in records], f, ensure_ascii=False, indent=2)
