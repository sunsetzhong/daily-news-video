"""
预生成新闻与脚本（供多 voice 并行复用同一份输入）
"""

import json
import os
from pathlib import Path
from dataclasses import asdict, is_dataclass

from news_fetcher import NewsFetcher

def to_jsonable_items(items):
    normalized = []
    for item in items:
        if is_dataclass(item):
            normalized.append(asdict(item))
        elif isinstance(item, dict):
            normalized.append(item)
        else:
            normalized.append(getattr(item, "__dict__", {}))
    return normalized


def main():
    out_dir = Path(os.getenv("PREPARED_DIR", "prepared"))
    out_dir.mkdir(parents=True, exist_ok=True)

    use_mock = os.getenv('USE_MOCK_NEWS', 'false').lower() == 'true'
    fetcher = NewsFetcher()
    result = fetcher.fetch_all_news(use_mock=use_mock)

    script = result["script"]
    news_items = to_jsonable_items(result["news_items"])

    script_path = out_dir / "script.json"
    news_items_path = out_dir / "news_items.json"

    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    with open(news_items_path, "w", encoding="utf-8") as f:
        json.dump(news_items, f, ensure_ascii=False, indent=2)

    print(f"prepared script: {script_path}")
    print(f"prepared news_items: {news_items_path}")
    print(f"total_selected: {result.get('total_selected', len(news_items))}")


if __name__ == "__main__":
    main()
