"""从 aigengtu.com（梗鲸）抓取蓝色大肥鱼表情包。

用法：
    python tools/fetch_memes.py              # 抓全部 41 页
    python tools/fetch_memes.py --pages 5    # 只抓前 5 页
    python tools/fetch_memes.py --pages 5 --no-download   # 只抓元数据不下图
"""

from __future__ import annotations

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets" / "emo"
INDEX_PATH = ROOT / "assets" / "emo_index.json"

ARCHIVE = "https://aigengtu.com/archive?lang=zh&p={page}"
IMG_URL = "https://img.aigengtu.com/meme/{id}.webp"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
    "Referer": "https://aigengtu.com/",
}

# 群里用的表情包，这些内容一律不要
BLOCK_WORDS = [
    "性关系", "性行为", "做爱", "约炮", "裸", "色情", "强奸", "怀孕",
    "傻逼", "去死", "滚你", "你妈", "妈的", "他妈的",
    "自杀", "割腕", "跳楼",
]


def is_safe(caption: str) -> bool:
    low = caption.lower()
    return not any(w in low for w in BLOCK_WORDS)


def parse_page(html: str) -> list[dict]:
    items = []
    for chunk in html.split('<div class="ar-card">')[1:]:
        mid = re.search(r"meme/(\d+)\.webp", chunk)
        if not mid:
            continue
        cat = re.search(r'ar-cat">([^<]*)<', chunk)
        alt = re.search(r'ar-alt"[^>]*>([^<]*)<', chunk)
        items.append(
            {
                "id": mid.group(1),
                "category": (cat.group(1).strip() if cat else ""),
                "caption": (alt.group(1).strip() if alt else ""),
            }
        )
    return items


def fetch_meta(pages: int) -> list[dict]:
    all_items: dict[str, dict] = {}
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for p in range(1, pages + 1):
            try:
                r = client.get(ARCHIVE.format(page=p))
                r.raise_for_status()
                items = parse_page(r.text)
                for it in items:
                    all_items[it["id"]] = it
                print(f"  第 {p}/{pages} 页 -> {len(items)} 条（累计 {len(all_items)}）")
            except Exception as exc:
                print(f"  第 {p} 页失败: {exc}")
            time.sleep(0.4)
    return sorted(all_items.values(), key=lambda x: x["id"])


def download_one(client: httpx.Client, item: dict) -> tuple[str, bool, int]:
    path = OUT_DIR / f"{item['id']}.webp"
    if path.exists() and path.stat().st_size > 1000:
        return item["id"], True, path.stat().st_size
    try:
        r = client.get(IMG_URL.format(id=item["id"]))
        if r.status_code != 200 or len(r.content) < 1000:
            return item["id"], False, 0
        path.write_bytes(r.content)
        return item["id"], True, len(r.content)
    except Exception:
        return item["id"], False, 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=41)
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--allow-unsafe", action="store_true", help="不过滤敏感内容")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"抓取元数据（{args.pages} 页）...")
    items = fetch_meta(args.pages)
    total_found = len(items)

    if not args.allow_unsafe:
        safe = [it for it in items if is_safe(it["caption"])]
        print(f"共 {total_found} 张，过滤掉 {total_found - len(safe)} 张不适合群聊的")
        items = safe
    else:
        print(f"共 {total_found} 张（未过滤）")

    if not args.no_download:
        print(f"下载图片（{args.workers} 并发）...")
        ok = fail = 0
        total_bytes = 0
        with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = {pool.submit(download_one, client, it): it for it in items}
                for i, fut in enumerate(as_completed(futures), 1):
                    _, success, size = fut.result()
                    if success:
                        ok += 1
                        total_bytes += size
                    else:
                        fail += 1
                    if i % 100 == 0:
                        print(f"  进度 {i}/{len(items)}  成功 {ok}  失败 {fail}")
        print(f"下载完成：成功 {ok}，失败 {fail}，共 {total_bytes / 1024 / 1024:.1f} MB")

    # 只保留文件确实存在的条目
    kept = [it for it in items if (OUT_DIR / f"{it['id']}.webp").exists()] if not args.no_download else items
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"索引已写入 {INDEX_PATH}（{len(kept)} 条）")


if __name__ == "__main__":
    main()
