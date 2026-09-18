#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
懂球帝评论爬虫（新闻 / 战报 / 文章通用）
================================================

功能：
  给定一篇或多篇懂球帝文章（战报）的 URL 或 ID，爬取该文章下的全部评论，
  输出为 JSON（按文章分文件）和一份合并的 CSV。

接口说明（实测 2026-09）：
  - 主接口（App v2）：https://api.dongqiudi.com/v2/article/{id}/comment?sort=down&version=177
        **可翻页拿全量顶级评论**（响应里的 next 即下一页 URL，翻到 next 为空为止）。
        字段：id / content / created_at(绝对时间) / user_id / up_count(点赞) /
              reply_total(回复数) / iptext(地区)；用户名在 user_list 里按 id 映射
              （实测覆盖率 100%）。
  - 兜底（文章页服务端渲染）：https://www.dongqiudi.com/articles/{id}.html
        页面内直接渲染约第一页评论（约 100 条），含用户名/点赞/相对时间。
        v2 不可用时（例如部署环境 IP 被拦）走这条。
  - 已废弃：https://api.dongqiudi.com/comment/list/{id}?plat=web  —— 不带 Referer 也 403。
  本脚本优先走 v2 接口；失败则回退文章页解析。

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
from datetime import datetime, timedelta

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

# 注：原「网页版评论接口」(api.dongqiudi.com/comment/list) 已废弃（实测不带
# Referer 也 403），对应的 _normalize_web 已删除，避免留死代码。


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
        # v2 的点赞字段叫 up_count、回复数字段叫 reply_total（早期误当成没有，已修正）
        "like_count": raw.get("up_count") if raw.get("up_count") is not None else 0,
        "created_at": raw.get("created_at"),
        "sub_comment_count": raw.get("reply_total"),
        "emoji_stats": raw.get("comment_statement_list"),
        "location": raw.get("iptext"),
        "source": "v2",
    }


# ----------------------------- 文章页评论解析（主来源） -----------------------
# 懂球帝文章页 www/m.dongqiudi.com/articles/{id}.html 会服务端渲染真实评论，
# 该域名与新闻首页同域、未被 WAF 拦截，因此在 Streamlit Cloud 等部署环境也能用。
# 而 api.dongqiudi.com 的评论接口在部分云环境 IP 下会被 403，仅作本地兜底。

ARTICLE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def _strip_tags(s):
    """去除 HTML 标签，保留表情图片的 alt 文本。"""
    if not s:
        return ""
    s = re.sub(r'<img[^>]*class="face"[^>]*alt="([^"]*)"[^>]*>', r" \1 ", s)
    s = re.sub(r"<img[^>]*>", " ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _rel_to_dt(s):
    """把懂球帝的相对时间转成 datetime（转换失败返回 None）。"""
    s = (s or "").strip()
    now = datetime.now()
    if not s:
        return None
    m = re.match(r"^(\d+)\s*分钟前$", s)
    if m:
        return now - timedelta(minutes=int(m.group(1)))
    m = re.match(r"^(\d+)\s*小时前$", s)
    if m:
        return now - timedelta(hours=int(m.group(1)))
    m = re.match(r"^(\d+)\s*天前$", s)
    if m:
        return now - timedelta(days=int(m.group(1)))
    if s == "刚刚":
        return now
    m = re.match(r"^(今天|昨天)\s*(\d{1,2}):(\d{2})$", s)
    if m:
        base = now if m.group(1) == "今天" else now - timedelta(days=1)
        return base.replace(hour=int(m.group(2)), minute=int(m.group(3)), second=0, microsecond=0)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:  # noqa: BLE001
            continue
    return None


def _parse_page_comments(html, article_id):
    """从文章页 HTML 中抽取服务端渲染的评论列表。"""
    blocks = re.findall(
        r'<div class="comment-item"[^>]*>(.*?)(?=<div class="comment-item"[^>]*>|\Z)',
        html, re.S,
    )
    total = None
    m = re.search(r"commentTotal:(\d+)", html)
    if m:
        total = int(m.group(1))
    out = []
    for i, blk in enumerate(blocks):
        um = re.search(r'comment-item__user[^>]*>([^<]*)</span>', blk)
        lm = re.search(r'comment-item__likes[^>]*>([^<]*)</span>', blk)
        tm = re.search(r'comment-item__time[^>]*>([^<]*)</p>', blk)
        txm = re.search(r'comment-item__text[^>]*>(.*?)</div>', blk, re.S)
        user = um.group(1).strip() if um else ""
        like_txt = re.sub(r"[^0-9]", "", lm.group(1)) if lm else ""
        like = int(like_txt) if like_txt else 0
        tstr = tm.group(1).strip() if tm else ""
        text = _strip_tags(txm.group(1)) if txm else ""
        if not text and not user:
            continue
        if text in ("首页比赛数据 赛事",):
            continue
        dt = _rel_to_dt(tstr)
        out.append({
            "comment_id": f"{article_id}_{i}",
            "content": text,
            "username": user,
            "user_id": None,
            "like_count": like,
            "created_at": dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None,
            "sub_comment_count": None,
            "emoji_stats": None,
            "source": "webpage",
        })
    return out, total


def crawl_from_article_page(article_id, timeout=25, reasons=None):
    """从 www/m 文章页抓取并解析真实评论。失败抛异常，0 评论返回 ([], 0)。

    reasons: 可选 list，用于收集失败原因（部署环境排查是否被 WAF 拦截时很有用）。
    """
    last_err = None
    html = None
    if reasons is None:
        reasons = []
    for site in ("https://www.dongqiudi.com/articles/", "https://m.dongqiudi.com/articles/"):
        host = site.split("//")[1].split("/")[0]
        for attempt in range(1, 3):  # 每个域名重试 2 次
            try:
                req = urllib.request.Request(site + f"{article_id}.html", headers=ARTICLE_HEADERS)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read()
                    if raw[:2] == b"\x1f\x8b":
                        raw = gzip.decompress(raw)
                    html = raw.decode("utf-8", errors="replace")
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                code = getattr(e, "code", None)
                if code:
                    reasons.append(f"文章页 {host} 第{attempt}次: HTTP {code}")
                else:
                    reasons.append(f"文章页 {host} 第{attempt}次: {type(e).__name__}: {e}")
                time.sleep(1.0 * attempt)
        if html is not None:
            break
    if html is None:
        raise RuntimeError(f"article page fetch failed: {last_err}")
    return _parse_page_comments(html, article_id)


def crawl_article(article_id, max_pages=200, request_delay=0.2):
    """
    爬取单篇文章的全部评论。

    优先级（实测 2026-09 确定）：
      0) App v2 接口 api.dongqiudi.com/v2/article/{id}/comment
         —— 可**翻页拿全量顶级评论**，且含用户名（user_list 映射）、
            点赞（up_count）、回复数（reply_total）、绝对时间、地区（iptext）
         → source="v2"
      1) 文章页 www/m.dongqiudi.com/articles/{id}.html 服务端渲染评论
         —— 只渲染第一页（约 100 条），但同域、Cloud 上通常不被拦，作兜底
         → source="webpage"
      全部失败 → source="failed"（调用方据此回退示例数据）

    注：网页版评论接口 api.dongqiudi.com/comment/list 已废弃（不带 Referer 也 403），已移除。

    返回 dict: {"article_id", "source", "total", "comments": [...], "reported_total"}
      reported_total = 接口自报的总数（含二级回复），用于诚实展示"是否全量"。
    """
    aid = str(article_id)
    reasons = []

    # ---- 0) App v2 接口翻页（首选：可拿到全量顶级评论）----
    try:
        url = f"{WEB_HOST}/v2/article/{aid}/comment?sort=down&version={APP_VERSION}"
        raw_list, user_map, reported = [], {}, None
        pages = 0
        while url and pages < max_pages:
            data = fetch_json(url)
            d = data.get("data") or {}
            if reported is None and d.get("comment_total") is not None:
                reported = d.get("comment_total")
            for u in d.get("user_list") or []:
                uid = u.get("id")
                if uid is not None and u.get("username"):
                    user_map[str(uid)] = u["username"]
            cl = d.get("comment_list") or []
            if not cl:
                break
            raw_list.extend(cl)
            url = d.get("next")
            pages += 1
            if url:
                time.sleep(request_delay)

        if raw_list:
            # user_map 需收集完整后再归一化，保证用户名映射尽量全命中
            seen, comments = set(), []
            for c in raw_list:
                cid = str(c.get("id"))
                if cid in seen:
                    continue
                seen.add(cid)
                comments.append(_normalize_v2(c, user_map))
            return {
                "article_id": aid,
                "source": "v2",
                "total": len(comments),
                "comments": comments,
                "reported_total": reported,
            }
    except Exception as e:  # noqa: BLE001
        reasons.append(f"App v2 接口: {type(e).__name__}: {e}")
        print(f"  [v2 接口不可用: {e}，回退文章页]", file=sys.stderr)

    # ---- 1) 文章页服务端渲染评论（兜底，只含第一页）----
    try:
        page_comments, page_total = crawl_from_article_page(aid, reasons=reasons)
        if page_comments or page_total == 0:
            return {
                "article_id": aid,
                "source": "webpage",
                "total": len(page_comments),
                "comments": page_comments,
                "reported_total": page_total,
            }
    except Exception as e:  # noqa: BLE001
        reasons.append(f"文章页: {type(e).__name__}: {e}")
        print(f"  [文章页评论解析失败: {e}]", file=sys.stderr)

    # ---- 2) 全部失败 ----
    return {
        "article_id": aid,
        "source": "failed",
        "total": 0,
        "comments": [],
        "reasons": reasons,
    }


# ----------------------------- 输出 -----------------------------------------

CSV_FIELDS = [
    "article_id", "comment_id", "username", "user_id", "content",
    "like_count", "sub_comment_count", "created_at", "location", "emoji_stats", "source",
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
