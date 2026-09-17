#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
懂球帝评论爬虫 · Streamlit 演示版（可部署到 Streamlit Community Cloud）
========================================================================
把命令行版爬虫（dongqiudi_comments.py）包装成一个 Streamlit 交互应用：

  - 侧边栏输入懂球帝文章链接或 ID，点「爬取评论」即可看到评论列表 + 表情统计。
  - 复用同目录下的 dongqiudi_comments.crawl_article()，联网则真实抓取
    （优先网页版接口，失败自动回退 App 接口）。
  - 若无外网 / 接口变更导致抓取失败，自动回退到内置示例数据并显示提示横幅，
    保证界面始终可演示。

本地运行：
  pip install -r requirements.txt
  streamlit run app.py            # 默认 http://localhost:8501/

说明：
  Streamlit 没有“路由”概念——爬虫逻辑和界面运行在同一个进程里，
  点按钮时脚本重跑并直接调用 crawl_article()，因此不存在“前端找不到后端”的问题。
"""
import os
import sys
from datetime import datetime

import pandas as pd
import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import dongqiudi_comments as dqd  # noqa: E402

# ------------------------- 内置示例评论（兜底演示用） ------------------------
# 仅用于界面演示 / 接口不可用时的兜底。
SAMPLE = {
    "comments": [
        {"comment_id": "1", "content": "这算北美的欧冠吗？", "username": "火星球迷999号", "user_id": "1",
         "like_count": 12, "created_at": "2026-09-17 10:26:23", "sub_comment_count": 3,
         "emoji_stats": [{"key": "[笑哭]", "count": 3}], "source": "sample"},
        {"comment_id": "2", "content": "幼儿园比赛，勇夺冠军[姆巴佩笑][姆巴佩笑][姆巴佩笑]", "username": "尖椒鸡", "user_id": "2",
         "like_count": 45, "created_at": "2026-09-17 15:24:49", "sub_comment_count": 7,
         "emoji_stats": [{"key": "[姆巴佩笑]", "count": 5}, {"key": "[笑哭]", "count": 2}], "source": "sample"},
        {"comment_id": "3", "content": "见证老板生涯第48冠，太棒了，足够高兴一整天了", "username": "文鸯", "user_id": "3",
         "like_count": 88, "created_at": "2026-09-17 13:30:36", "sub_comment_count": 12,
         "emoji_stats": [{"key": "[大力神杯]", "count": 9}, {"key": "[金球]", "count": 6}], "source": "sample"},
        {"comment_id": "4", "content": "39岁了，1米69居然还能单挑后卫头球抢点破门，传奇确实难以形容了", "username": "国足不进世界杯永不改名", "user_id": "4",
         "like_count": 156, "created_at": "2026-09-17 21:51:00", "sub_comment_count": 21,
         "emoji_stats": [{"key": "[金球]", "count": 14}, {"key": "[大力神杯]", "count": 11}], "source": "sample"},
        {"comment_id": "5", "content": "恭喜梅西！！！永远的球王！！！", "username": "可爱的史努比", "user_id": "5",
         "like_count": 203, "created_at": "2026-09-17 21:51:51", "sub_comment_count": 33,
         "emoji_stats": [{"key": "[大力神杯]", "count": 30}, {"key": "[赞]", "count": 18}], "source": "sample"},
        {"comment_id": "6", "content": "这级别联赛，我们过去就能拿", "username": "东直门老酋长", "user_id": "6",
         "like_count": 9, "created_at": "2026-09-17 12:33:47", "sub_comment_count": 2,
         "emoji_stats": [{"key": "[捂脸]", "count": 4}], "source": "sample"},
        {"comment_id": "7", "content": "迈阿密的后防这场居然零封了，哈哈哈哈哈哈哈……", "username": "米兰0516", "user_id": "7",
         "like_count": 67, "created_at": "2026-09-17 21:58:58", "sub_comment_count": 9,
         "emoji_stats": [{"key": "[捂脸]", "count": 8}, {"key": "[笑哭]", "count": 5}], "source": "sample"},
        {"comment_id": "8", "content": "C罗球迷祝贺球王梅西夺得48座冠军", "username": "巴黎聖日門_美斯", "user_id": "8",
         "like_count": 134, "created_at": "2026-09-17 21:46:50", "sub_comment_count": 15,
         "emoji_stats": [{"key": "[大力神杯]", "count": 12}, {"key": "[赞]", "count": 9}], "source": "sample"},
        {"comment_id": "9", "content": "杯赛这么多的吗？一会一个？[修仙]", "username": "长尾鼠", "user_id": "9",
         "like_count": 22, "created_at": "2026-09-17 22:26:29", "sub_comment_count": 4,
         "emoji_stats": [{"key": "[修仙]", "count": 3}, {"key": "[笑哭]", "count": 2}], "source": "sample"},
        {"comment_id": "10", "content": "苏牙浪费机会比较多，跑位意识还是顶级", "username": "曼米巴", "user_id": "10",
         "like_count": 41, "created_at": "2026-09-17 19:56:42", "sub_comment_count": 6,
         "emoji_stats": [{"key": "[赞]", "count": 6}], "source": "sample"},
        {"comment_id": "11", "content": "竞争金球前五吧，老梅", "username": "巴萨发言人", "user_id": "11",
         "like_count": 78, "created_at": "2026-09-17 21:47:23", "sub_comment_count": 8,
         "emoji_stats": [{"key": "[金球]", "count": 10}], "source": "sample"},
        {"comment_id": "12", "content": "这不搞笑么", "username": "球迷2423002", "user_id": "12",
         "like_count": 3, "created_at": "2026-09-17 21:36:46", "sub_comment_count": 1,
         "emoji_stats": [], "source": "sample"},
    ]
}

SOURCE_LABEL = {"web": "网页版接口", "v2": "App 接口", "sample": "示例数据"}


# ------------------------- 纯函数：数据处理（可单测） ------------------------
def aggregate_emoji(comments):
    """聚合所有评论的表情表态，返回 {表情key: 总次数}。"""
    agg = {}
    for c in comments:
        stats = c.get("emoji_stats") or []
        if isinstance(stats, list):
            for e in stats:
                if isinstance(e, dict) and e.get("key"):
                    agg[e["key"]] = agg.get(e["key"], 0) + int(e.get("count", 0) or 0)
    return agg


def parse_time(ts):
    """尽力把 created_at 解析成 datetime；失败返回 None。"""
    if ts is None:
        return None
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        try:
            return datetime.fromtimestamp(ts / 1000) if ts > 1e11 else datetime.fromtimestamp(ts)
        except Exception:
            return None
    if isinstance(ts, str):
        s = ts.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue
    return None


def build_rows(comments):
    """把评论列表转成 DataFrame 友好的行。"""
    rows = []
    for c in comments:
        stats = c.get("emoji_stats") or []
        emoji_str = (
            " ".join(f"{e.get('key', '')}x{e.get('count', '')}"
                     for e in stats if isinstance(e, dict))
            if isinstance(stats, list) else ""
        )
        rows.append({
            "用户名": c.get("username") or "匿名",
            "评论内容": c.get("content", ""),
            "点赞": c.get("like_count") if c.get("like_count") is not None else 0,
            "回复数": c.get("sub_comment_count") if c.get("sub_comment_count") is not None else 0,
            "时间": c.get("created_at", ""),
            "表情表态": emoji_str,
        })
    return rows


def fetch_or_sample(text):
    """
    解析输入 -> 抓取评论；失败/空则回退示例数据。
    返回 (result, is_demo)：
      result 为 None 表示输入无法解析出文章 ID。
    """
    ids = dqd.extract_ids_from_args([text]) if text and text.strip() else []
    if not ids:
        return None, False
    aid = ids[0]
    try:
        r = dqd.crawl_article(aid, max_pages=50)
    except Exception as e:  # noqa: BLE001
        r = {"article_id": aid, "source": "failed", "total": 0, "comments": [], "error": str(e)}
    if (not r) or r.get("source") == "failed" or r.get("total", 0) == 0:
        return {
            "article_id": aid, "source": "sample", "total": len(SAMPLE["comments"]),
            "comments": SAMPLE["comments"], "demo": True,
        }, True
    r["demo"] = False
    return r, False


# ------------------------- UI（仅在 streamlit 运行时执行） -------------------
def main():
    st.set_page_config(page_title="懂球帝评论爬虫 Demo", page_icon="⚽", layout="wide")

    st.title("⚽ 懂球帝评论爬虫 · Streamlit Demo")
    st.caption(
        "粘贴懂球帝战报链接或文章 ID，抓取并可视化评论。"
        "联网将抓取真实评论（优先网页版接口，失败自动回退 App 接口）；"
        "无外网或接口变更时自动回退到示例数据，保证界面始终可演示。"
    )

    with st.sidebar:
        st.header("📥 输入")
        url = st.text_input(
            "文章链接 / ID",
            placeholder="https://www.dongqiudi.com/articles/6358712.html  或  6358712",
        )
        go = st.button("🚀 爬取评论", type="primary", use_container_width=True)
        st.divider()
        st.markdown("**说明**")
        st.markdown("- 支持整条链接或纯数字 ID\n- 数据仅供学习研究，请遵守网站规定")
        max_items = st.slider("列表展示条数", 10, 300, 60)

    # 用 session_state 缓存抓取结果，避免每次交互都重新爬
    if "result" not in st.session_state:
        st.session_state.result = None
    if "is_demo" not in st.session_state:
        st.session_state.is_demo = False

    if go:
        if not url or not url.strip():
            st.warning("请先在左侧输入文章链接或 ID。")
        else:
            with st.spinner("正在抓取评论…（若联网将拉取真实数据）"):
                res, demo = fetch_or_sample(url)
            if res is None:
                st.error("无法从输入解析出文章 ID，请粘贴懂球帝文章链接或纯数字 ID。")
            else:
                st.session_state.result = res
                st.session_state.is_demo = demo

    res = st.session_state.result
    if res is None:
        st.info("👈 在左侧输入懂球帝战报链接或文章 ID，点击「爬取评论」开始。")
        st.stop()

    if st.session_state.is_demo:
        st.warning(
            "⚠️ 当前为**演示数据**：未能抓到真实评论（可能本机无外网或接口已变更）。"
            "在联网环境运行本应用即可抓取真实评论。",
            icon="⚠️",
        )

    comments = res["comments"]
    source = res["source"]
    total = res["total"]

    # ---- 概览指标 ----
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("评论总数", total)
    c2.metric("数据来源", SOURCE_LABEL.get(source, source))
    times = [t for t in (parse_time(c.get("created_at")) for c in comments) if t]
    if times:
        c3.metric("最早评论", min(times).strftime("%m-%d %H:%M"))
        c4.metric("最新评论", max(times).strftime("%m-%d %H:%M"))
    else:
        c3.metric("最早评论", "—")
        c4.metric("最新评论", "—")

    # ---- 表情 / 表态 Top ----
    agg = aggregate_emoji(comments)
    if agg:
        st.subheader("🔥 表情 / 表态 Top 10")
        series = pd.Series(agg).sort_values(ascending=False).head(10)
        st.bar_chart(series)
    else:
        st.caption("该批评论无表情表态数据。")

    # ---- 热门评论卡片 ----
    rows = build_rows(comments)
    df = pd.DataFrame(rows)
    if not df.empty:
        df["点赞"] = pd.to_numeric(df["点赞"], errors="coerce").fillna(0).astype(int)
        hot = df.sort_values("点赞", ascending=False).head(8)
        st.subheader("💬 热门评论（按点赞排序）")
        for _, row in hot.iterrows():
            meta = f"👤 {row['用户名']}　👍 {row['点赞']}　💬 {row['回复数']}　🕒 {row['时间']}"
            if row["表情表态"]:
                meta += f"　{row['表情表态']}"
            st.markdown(f"> {row['评论内容']}\n\n_{meta}_")

    # ---- 全部评论表格 + 下载 ----
    st.subheader("📋 全部评论")
    st.dataframe(df.head(max_items), use_container_width=True, height=420)
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ 下载 CSV",
        csv,
        file_name=f"dongqiudi_{res['article_id']}.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
