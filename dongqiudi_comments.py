#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
懂球帝评论爬虫（新闻 / 战报 / 文章通用）
================================================

功能：
  给定一篇或多篇懂球帝文章（战报）的 URL 或 ID，爬取该文章下的全部评论，
  输出为 JSON（按文章分文件）和一份合并的 CSV。

接口说明（实测 2026-09）：
  - 主接口（网页版）：https://api.dongqiudi.com/comment/list/{id}?plat=web&page=N&count=50
        返回字段更完整（含 user.username / like / sub_comment_count 等）。
        注意：该接口有反爬，需要带浏览器 UA + Referer，否则返回 403。
  - 兜底接口（App 老版）：https://api.dongqiudi.com/v2/article/{id}/comment?sort=down&version=177
        已验证可用，返回 content / created_at / id / comment_statement_list（表情统计）
        以及 next（下一页 URL，含时间戳）。但该接口的主评论**不含作者名**。
  本脚本优先尝试主接口；若失败（403 / 异常 / 无评论字段）则自动回退到兜底接口。

使用：
  # 直接传文章 ID
  python dongqiudi_comments.py 6358712 6359476

  # 从文件批量读取（每行一个 URL 或纯数字 ID）
  python dongqiudi_comments.py --file ids.txt

  # 从某个懂球帝列表页（首页 / 标签页）自动发现文章并爬取
  python dongqiudi_comments.py --page "https://www.dongqiudi.com/"

  # 其它选项
  --out DIR        输出目录（默认 ./dongqiudi_output）
  --delay SEC      每篇文章之间的间隔秒数（默认 1.5）
  --max-pages N    单篇最多翻页数（默认 200，足够覆盖绝大多数战报）
  --format {both,json,csv}

⚠️ 使用须知 / 合规提示：
  - 本脚本仅用于个人学习、数据研究；请自觉遵守网站 robots.txt 与《数据安全法》等相关规定，
    不要将抓取的数据用于商业用途或对外分发。
  - 已内置随机延时与重试，请不要把 delay 设得过小、不要高频并发请求，以免给服务器造成压力。
  - 若网站调整接口导致 403 持续，请降低频率或暂停使用。

零第三方依赖，使用 Python 3.8+ 标准库即可运行。
"""

import argparse
import csv
import gzip
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

# ----------------------------- 配置 -----------------------------------------

WEB_HOST = "https://api.dongqiudi.com"
WEB_REFERER = "https://www.dongqiudi.com/"
APP_VERSION = "177"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    # 不要主动声明 gzip，避免手动解压麻烦；服务器通常会回明文 JSON
}

ID_RE = re.compile(r"(?:/articles/|/article/|/news/|/a/|id=)(\d{4,})")
HTML_ARTICLE_RE = re.compile(r"/articles/(\d{4,})\.html")

# ----------------------------- 网络层 ---------------------------------------

def fetch_json(url, timeout=15, retries=3):
    """用 urllib 抓取 JSON，带重试与 gzip 容错。失败抛异常。"""
    headers = dict(DEFAULT_HEADERS)
    # 网页版接口需要 Referer，否则 403
    if "comment/list" in url:
        headers["Referer"] = WEB_REFERER
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if raw[:2] == b"\x1f\x8b":  # gzip
                    raw = gzip.decompress(raw)
                text = raw.decode("utf-8", errors="replace")
                return json.loads(text)
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code} for {url}"
            # 403 直接放弃重试（带 Referer 仍失败说明被拦）
            if e.code == 403:
                raise
            time.sleep(1.5 * attempt)
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(1.5 * attempt)
    raise RuntimeError(f"fetch failed after {retries} retries: {last_err}")


# ----------------------------- 单篇文章爬取 ----------------------------------

def _normalize_web(raw, user_map):
    user = raw.get("user") or {}
    uid = user.get("id")
    username = user.get("username")
    # 极端情况下用户对象可能只在 user_map 里
    if (not username) and uid and str(uid) in user_map:
        username = user_map.get(str(uid))
    return {
        "comment_id": str(raw.get("id")),
        "content": raw.get("content", ""),
        "username": username,
        "user_id": str(uid) if uid is not None else None,
        "like_count": raw.get("like"),
        "created_at": raw.get("created_at"),
        "sub_comment_count": raw.get("sub_comment_count"),
        "emoji_stats": raw.get("comment_statement_list") or raw.get("comment_like_list"),
        "source": "web",
    }


def _normalize_v2(raw, user_map):
    uid = raw.get("user_id") or (raw.get("user") or {}).get("id")
    username = None
    if uid and str(uid) in user_map:
        username = user_map.get(str(uid))
    return {
        "comment_id": str(raw.get("id")),
        "content": raw.get("content", ""),
        "username": username,
        "user_id": str(uid) if uid is not None else None,
        "like_count": None,
        "created_at": raw.get("created_at"),
        "sub_comment_count": None,
        "emoji_stats": raw.get("comment_statement_list"),
        "source": "v2",
    }


def crawl_article(article_id, max_pages=200, request_delay=0.5):
    """
    爬取单篇文章的全部评论。
    先试网页版，失败回退 v2。返回 dict:
        {"article_id", "source", "total", "comments": [...]}
    """
    # ---- 尝试网页版 ----
    web_comments = []
    try:
        page = 1
        while page <= max_pages:
            url = (
                f"{WEB_HOST}/comment/list/{article_id}?"
                f"plat=web&page={page}&count=50"
            )
            data = fetch_json(url)
            cl = (data.get("data") or {}).get("comment_list") or []
            if not cl:
                break
            for c in cl:
                web_comments.append(_normalize_web(c, {}))
            if len(cl) < 50:
                break
            page += 1
            time.sleep(request_delay + random.uniform(0, 0.3))
        if web_comments:
            return {
                "article_id": str(article_id),
                "source": "web",
                "total": len(web_comments),
                "comments": web_comments,
            }
    except Exception as e:  # noqa: BLE001
        print(f"  [网页版接口不可用: {e}，回退 v2 接口]", file=sys.stderr)

    # ---- 回退 v2 接口 ----
    v2_comments = []
    user_map = {}
    try:
        next_url = (
            f"{WEB_HOST}/v2/article/{article_id}/comment?"
            f"sort=down&version={APP_VERSION}"
        )
        pages = 0
        while next_url and pages < max_pages:
            data = fetch_json(next_url)
            d = data.get("data") or {}
            # 建立 user_map（v2 把用户名单独列出，部分评论可能带 user_id 可关联）
            for u in d.get("user_list") or []:
                user_map[str(u.get("id"))] = u.get("username")
            cl = d.get("comment_list") or []
            if not cl:
                break
            for c in cl:
                v2_comments.append(_normalize_v2(c, user_map))
            nxt = d.get("next")
            if not nxt:
                break
            next_url = nxt
            pages += 1
            time.sleep(request_delay + random.uniform(0, 0.3))
        return {
            "article_id": str(article_id),
            "source": "v2",
            "total": len(v2_comments),
            "comments": v2_comments,
        }
    except Exception as e:  # noqa: BLE001
        print(f"  [v2 接口也失败: {e}]", file=sys.stderr)
        return {
            "article_id": str(article_id),
            "source": "failed",
            "total": 0,
            "comments": [],
        }


# ----------------------------- 输出 -----------------------------------------

CSV_FIELDS = [
    "article_id", "comment_id", "username", "user_id", "content",
    "like_count", "sub_comment_count", "created_at", "emoji_stats", "source",
]


def write_outputs(results, out_dir, fmt="both"):
    os.makedirs(out_dir, exist_ok=True)
    # 每篇一个 JSON
    for r in results:
        if fmt in ("both", "json"):
            path = os.path.join(out_dir, f"article_{r['article_id']}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(r, f, ensure_ascii=False, indent=2)

    # 合并 CSV
    if fmt in ("both", "csv"):
        csv_path = os.path.join(out_dir, "all_comments.csv")
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            w.writeheader()
            for r in results:
                for c in r["comments"]:
                    row = dict(c)
                    if isinstance(row.get("emoji_stats"), list):
                        row["emoji_stats"] = " ".join(
                            f"{e.get('key','')}x{e.get('count','')}"
                            for e in row["emoji_stats"]
                            if isinstance(e, dict)
                        )
                    row["article_id"] = r["article_id"]
                    w.writerow({k: row.get(k, "") for k in CSV_FIELDS})
        return csv_path
    return None


# ----------------------------- 输入解析 --------------------------------------

def extract_ids_from_args(values):
    ids = []
    for v in values:
        m = ID_RE.search(v)
        if m:
            ids.append(m.group(1))
        elif v.strip().isdigit():
            ids.append(v.strip())
    return ids


def discover_from_page(page_url):
    """从列表页 HTML 中提取文章 ID。"""
    html = ""
    try:
        headers = dict(DEFAULT_HEADERS)
        headers["Referer"] = WEB_REFERER
        req = urllib.request.Request(page_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            html = raw.decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        print(f"  [列表页抓取失败: {e}]", file=sys.stderr)
        return []
    return HTML_ARTICLE_RE.findall(html)


# ----------------------------- 主流程 ----------------------------------------

def main():
    ap = argparse.ArgumentParser(description="懂球帝评论爬虫")
    ap.add_argument("ids", nargs="*", help="文章 URL 或数字 ID（可多个）")
    ap.add_argument("--file", help="每行一个 URL / ID 的文本文件")
    ap.add_argument("--page", help="从懂球帝列表页自动发现文章并爬取")
    ap.add_argument("--out", default="./dongqiudi_output", help="输出目录")
    ap.add_argument("--delay", type=float, default=1.5, help="每篇文章间隔秒数")
    ap.add_argument("--max-pages", type=int, default=200, help="单篇最大翻页数")
    ap.add_argument("--format", choices=["both", "json", "csv"], default="both")
    args = ap.parse_args()

    article_ids = []
    if args.ids:
        article_ids += extract_ids_from_args(args.ids)
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            article_ids += extract_ids_from_args(
                [line.strip() for line in f if line.strip() and not line.startswith("#")]
            )
    if args.page:
        print(f"[*] 从列表页发现文章: {args.page}")
        article_ids += discover_from_page(args.page)

    # 去重保序
    seen, unique = set(), []
    for i in article_ids:
        if i not in seen:
            seen.add(i)
            unique.append(i)
    article_ids = unique

    if not article_ids:
        print("未提供任何文章 ID。用法见脚本顶部注释。", file=sys.stderr)
        sys.exit(1)

    print(f"[*] 共 {len(article_ids)} 篇文章待爬取")

    results = []
    for idx, aid in enumerate(article_ids, 1):
        print(f"[*] ({idx}/{len(article_ids)}) 爬取文章 {aid} ...")
        r = crawl_article(aid, max_pages=args.max_pages)
        print(f"    来源={r['source']}  评论数={r['total']}")
        results.append(r)
        if idx < len(article_ids):
            time.sleep(args.delay + random.uniform(0, 0.5))

    csv_path = write_outputs(results, args.out, args.format)
    total = sum(r["total"] for r in results)
    print(f"[完成] 共爬取 {len(results)} 篇，{total} 条评论。")
    print(f"        输出目录: {os.path.abspath(args.out)}")
    if csv_path:
        print(f"        合并 CSV: {csv_path}")


if __name__ == "__main__":
    main()
