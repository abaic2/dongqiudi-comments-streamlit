#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
懂球帝评论爬虫 · Streamlit 演示版（可部署到 Streamlit Community Cloud）
========================================================================
界面模拟懂球帝新闻列表，用户直接点选新闻即可爬取评论，并额外生成
「评论词云」与「情感分析」。

  - 顶部加载懂球帝新闻列表（无网络时自动回退内置示例新闻）。
  - 直接点选新闻卡片 → 抓取该篇评论（优先网页版接口，失败回退 App 接口）。
  - 无外网 / 接口变更导致抓取失败时，自动回退到内置示例评论并显示提示横幅。
  - 词云：对评论内容做中文分词统计，按词频渲染标签云（无需额外字体）。
  - 情感分析：SnowNLP 给出每条评论的情感分（0~1），聚合为正面/中性/负面分布。

本地运行：
  pip install -r requirements.txt
  streamlit run app.py            # 默认 http://localhost:8501/

说明：
  Streamlit 没有“路由”概念——爬虫逻辑和界面运行在同一个进程里，
  点按钮时脚本重跑并直接调用 crawl_article()，因此不存在“前端找不到后端”的问题。
"""
import os
import re
import ssl
import sys
import json
import urllib.request
from datetime import datetime

import pandas as pd
import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
try:
    import dongqiudi_comments as dqd  # noqa: E402
except ImportError:  # 适配 demo 目录（爬虫在父目录）
    sys.path.insert(0, os.path.dirname(HERE))
    import dongqiudi_comments as dqd  # noqa: E402

# ------------------------- 可选依赖（带兜底） -------------------------
try:
    import jieba
    jieba.setLogLevel(20)
    HAVE_JIEBA = True
except Exception:  # noqa: BLE001
    HAVE_JIEBA = False

try:
    from snownlp import SnowNLP
    HAVE_SNOWNLP = True
except Exception:  # noqa: BLE001
    HAVE_SNOWNLP = False


# ------------------------- 内置示例（兜底演示用） -------------------------
SAMPLE_NEWS = [
    {"id": "6358712", "title": "国足0-2不敌日本，世预赛出线形势告急", "cover": None, "time": "2小时前", "tag": "国家队"},
    {"id": "6359476", "title": "梅西任意球破门，迈阿密国际晋级季后赛", "cover": None, "time": "4小时前", "tag": "国际"},
    {"id": "6359021", "title": "英超焦点战：阿森纳3-1逆转曼联", "cover": None, "time": "6小时前", "tag": "英超"},
    {"id": "6358890", "title": "皇马2-0赫罗纳，稳居西甲榜首", "cover": None, "time": "8小时前", "tag": "西甲"},
    {"id": "6358765", "title": "欧冠1/4决赛抽签：拜仁再遇皇马", "cover": None, "time": "10小时前", "tag": "欧冠"},
    {"id": "6358633", "title": "中超第12轮：上海海港5-0大胜对手", "cover": None, "time": "12小时前", "tag": "中超"},
]

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

STOPWORDS = set(
    "的 了 是 在 我 你 他 她 它 我们 你们 他们 这 那 这个 那个 也 都 就 还 和 与 及 等 被 把 让 给 "
    "啊 吧 呢 吗 哦 呀 嘛 已经 一个 没有 不是 就是 还是 但是 因为 所以 自己 什么 怎么 这么 那么 "
    "现在 今天 一下 可以 这样 那样 这种 那种 其实 感觉 觉得 这场 那个 哪个 一个 我们 他们".split()
)

POS_WORDS = set(
    "赞 好 牛 厉害 支持 爱 赢 胜利 加油 恭喜 漂亮 强 棒 喜 开心 稳 优秀 精彩 牛逼 燃 绝杀 封神 "
    "无敌 完美 惊喜 争气 给力 高兴 期待 强势 霸气 稳了".split()
)
NEG_WORDS = set(
    "输 烂 垃圾 差 黑 骂 失望 生气 蠢 弱 惨 崩 坑 假 丑 坏 讨厌 恨 怒 丢人 耻辱 拉胯 不行 "
    "可惜 遗憾 气 郁闷 心烦 惨败 翻车 崩盘 毫无 无奈 心疼".split()
)


# ------------------------- 新闻列表获取（点选爬取） -------------------------
def fetch_news_list():
    """尝试从懂球帝接口获取新闻列表；失败则回退内置示例新闻。"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.dongqiudi.com/",
    }
    urls = [
        "https://www.dongqiudi.com/api/app/tab/2?action=1&type=body&version=500&plat=web",
        "https://api.dongqiudi.com/app/tab/recommend.json?action=1&version=500&plat=web",
    ]
    for u in urls:
        try:
            req = urllib.request.Request(u, headers=headers)
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
                data = json.loads(r.read().decode("utf-8", "ignore"))
            arts = parse_articles(data)
            if arts:
                return arts
        except Exception:  # noqa: BLE001
            continue
    return SAMPLE_NEWS


def parse_articles(data):
    items = []
    d = data.get("data") if isinstance(data, dict) else data
    if isinstance(d, dict):
        for k in ("article_list", "list", "items", "articles", "feed"):
            if isinstance(d.get(k), list):
                d = d[k]
                break
    if isinstance(d, list):
        items = d
    out = []
    for it in items[:30]:
        if not isinstance(it, dict):
            continue
        aid = str(it.get("article_id") or it.get("id") or "")
        title = it.get("title") or it.get("title2") or ""
        if not aid or not title:
            continue
        cover = it.get("thumb") or it.get("cover") or it.get("img") or it.get("image") or None
        t = it.get("published_at") or it.get("time") or it.get("label") or ""
        out.append({"id": aid, "title": title.strip(),
                    "cover": cover, "time": str(t), "tag": it.get("label") or ""})
    return out


# ------------------------- 纯函数：数据处理（可单测） ------------------------
def aggregate_emoji(comments):
    agg = {}
    for c in comments:
        stats = c.get("emoji_stats") or []
        if isinstance(stats, list):
            for e in stats:
                if isinstance(e, dict) and e.get("key"):
                    agg[e["key"]] = agg.get(e["key"], 0) + int(e.get("count", 0) or 0)
    return agg


def parse_time(ts):
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


def build_word_freq(comments, topn=60):
    """中文分词统计词频（词云数据源）。"""
    text = " ".join((c.get("content") or "") for c in comments)
    text = re.sub(r"\[[^\]]*\]", " ", text)  # 先去掉 [表情] 标签，避免被切碎混入
    if HAVE_JIEBA:
        toks = jieba.cut(text)
        words = [w for w in toks if len(w.strip()) > 1 and not re.fullmatch(r"[\s\W\d]+", w)]
    else:
        words = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    freq = {}
    for w in words:
        w = w.strip()
        if not w or w in STOPWORDS:
            continue
        if "[" in w or "]" in w:  # 兜底：含括号的一律跳过
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]", w):  # 单字跳过
            continue
        freq[w] = freq.get(w, 0) + 1
    return sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:topn]


def render_wordcloud(top):
    if not top:
        return '<p style="color:#888">暂无足够文本生成词云</p>'
    maxc = max(c for _, c in top)
    minc = min(c for _, c in top)
    spans = []
    for w, c in top:
        t = (c - minc) / (maxc - minc + 1e-9)
        size = 14 + int(t * 34)
        hue = int(210 - t * 210)
        weight = 500 + int(t * 400)
        spans.append(
            f'<span style="font-size:{size}px;color:hsl({hue},72%,46%);'
            f'font-weight:{weight};margin:3px 7px;display:inline-block;line-height:1.15">{w}</span>'
        )
    return (
        '<div style="padding:14px 10px;line-height:1.4;border:1px solid #eee;'
        'border-radius:10px;background:#fafafa">' + "".join(spans) + "</div>"
    )


def sentiment_score(text):
    """返回 0~1 的情感分。优先 SnowNLP，失败回退词典法。"""
    text = (text or "").strip()
    if HAVE_SNOWNLP and text:
        try:
            return float(SnowNLP(text).sentiments)
        except Exception:  # noqa: BLE001
            pass
    score = 0.0
    for w in re.findall(r"[\u4e00-\u9fff]{1,}", text):
        if w in POS_WORDS:
            score += 1
        elif w in NEG_WORDS:
            score -= 1
    return 0.5 + score * 0.12


def classify(s):
    if s >= 0.6:
        return "正面"
    if s <= 0.4:
        return "负面"
    return "中性"


def build_rows(comments):
    rows = []
    for c in comments:
        stats = c.get("emoji_stats") or []
        emoji_str = (
            " ".join(f"{e.get('key', '')}x{e.get('count', '')}"
                     for e in stats if isinstance(e, dict))
            if isinstance(stats, list) else ""
        )
        s = sentiment_score(c.get("content", ""))
        rows.append({
            "用户名": c.get("username") or "匿名",
            "评论内容": c.get("content", ""),
            "点赞": c.get("like_count") if c.get("like_count") is not None else 0,
            "回复数": c.get("sub_comment_count") if c.get("sub_comment_count") is not None else 0,
            "时间": c.get("created_at", ""),
            "表情表态": emoji_str,
            "情感": classify(s),
            "情感分": round(s, 2),
        })
    return rows


def fetch_or_sample(article_id):
    """抓取某篇文章评论；失败/空则回退示例数据。返回 (result, is_demo)。"""
    try:
        r = dqd.crawl_article(article_id, max_pages=50)
    except Exception as e:  # noqa: BLE001
        r = {"article_id": article_id, "source": "failed", "total": 0, "comments": [], "error": str(e)}
    if (not r) or r.get("source") == "failed" or r.get("total", 0) == 0:
        return {
            "article_id": article_id, "source": "sample",
            "total": len(SAMPLE["comments"]), "comments": SAMPLE["comments"], "demo": True,
        }, True
    r["demo"] = False
    return r, False


# ------------------------- UI（仅在 streamlit 运行时执行） -------------------
def main():
    st.set_page_config(page_title="懂球帝评论爬取 Demo", page_icon="⚽", layout="wide")
    st.markdown(
        """
        <style>
        .dqd-bar{padding:10px 16px;background:linear-gradient(135deg,#d51d2a,#ff6a3d);
            color:#fff;border-radius:10px;font-size:20px;font-weight:700;margin-bottom:12px;}
        .dqd-card-title{font-weight:600;font-size:15px;line-height:1.35;min-height:42px;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="dqd-bar">⚽ 懂球帝 · 新闻评论爬取 Demo</div>', unsafe_allow_html=True)
    st.caption(
        "像懂球帝一样浏览新闻列表，直接点选新闻即可爬取评论，并自动生成词云与情感分析。"
        "联网将抓取真实数据；无外网或接口变更时自动回退示例数据，保证界面始终可演示。"
    )

    # ---- session state ----
    if "news" not in st.session_state:
        st.session_state.news = None
    if "selected" not in st.session_state:
        st.session_state.selected = None
    if "sel_title" not in st.session_state:
        st.session_state.sel_title = ""
    if "results" not in st.session_state:
        st.session_state.results = {}

    # ---- 加载新闻列表 ----
    col_refresh, col_tip = st.columns([1, 3])
    with col_refresh:
        if st.button("🔄 加载 / 刷新新闻列表", use_container_width=True, type="primary"):
            with st.spinner("正在获取懂球帝新闻列表…"):
                st.session_state.news = fetch_news_list()
                st.session_state.selected = None
                st.session_state.results = {}

    if st.session_state.news is None:
        st.info("👆 点击「加载 / 刷新新闻列表」开始（无网络时自动使用内置示例新闻）。")
        # 也保留手动输入入口
        with st.expander("或手动输入文章 ID / 链接"):
            manual = st.text_input("文章链接或数字 ID", placeholder="6358712 或 articles/6358712.html")
            if st.button("爬取该文章"):
                ids = dqd.extract_ids_from_args([manual]) if manual.strip() else []
                if ids:
                    st.session_state.selected = ids[0]
        st.stop()

    news = st.session_state.news
    is_demo_news = (news is SAMPLE_NEWS)
    if is_demo_news:
        st.warning("⚠️ 当前为内置示例新闻（未能联网获取实时列表），评论数据也会是演示数据。", icon="⚠️")

    st.markdown("### 📰 选择一篇新闻，点击「爬取评论」")
    cols = st.columns(3)
    for i, art in enumerate(news):
        with cols[i % 3]:
            with st.container(border=True):
                if art.get("cover"):
                    try:
                        st.image(art["cover"], use_column_width=True)
                    except Exception:  # noqa: BLE001
                        pass
                else:
                    st.markdown(
                        '<div style="height:96px;background:linear-gradient(135deg,#d51d2a,#ff6a3d);'
                        'border-radius:8px;display:flex;align-items:center;justify-content:center;'
                        'color:#fff;font-size:34px">⚽</div>',
                        unsafe_allow_html=True,
                    )
                st.markdown(f'<div class="dqd-card-title">{art["title"]}</div>', unsafe_allow_html=True)
                meta = " · ".join([x for x in [art.get("tag"), art.get("time")] if x])
                st.caption(meta)
                if st.button("📥 爬取评论", key=f"btn_{art['id']}", use_container_width=True):
                    st.session_state.selected = art["id"]
                    st.session_state.sel_title = art["title"]

    # ---- 已选新闻的结果展示 ----
    sel = st.session_state.selected
    if not sel:
        st.stop()

    st.divider()
    st.markdown(f"## 📰 {st.session_state.get('sel_title', '')}")

    if sel not in st.session_state.results:
        with st.spinner("正在爬取评论（网页版 → App 接口 → 示例兜底）…"):
            res, demo = fetch_or_sample(sel)
            st.session_state.results[sel] = (res, demo)
    res, demo = st.session_state.results[sel]

    if demo:
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

    # ---- 词云 ----
    st.subheader("☁️ 评论词云")
    top = build_word_freq(comments)
    st.markdown(render_wordcloud(top), unsafe_allow_html=True)
    if HAVE_JIEBA:
        st.caption("（基于 jieba 中文分词统计词频，按频率渲染字号）")
    else:
        st.caption("（未安装 jieba，已用正则提取中文词；pip install jieba 可获得更准的分词）")

    # ---- 情感分析 ----
    st.subheader("💡 情感分析")
    scored = [sentiment_score(c.get("content", "")) for c in comments]
    if scored:
        avg = sum(scored) / len(scored)
        pos = sum(1 for s in scored if s >= 0.6)
        neg = sum(1 for s in scored if s <= 0.4)
        neu = len(scored) - pos - neg
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("平均情感分", f"{avg:.2f}")
        s2.metric("正面", f"{pos}（{pos / len(scored) * 100:.0f}%）")
        s3.metric("中性", f"{neu}（{neu / len(scored) * 100:.0f}%）")
        s4.metric("负面", f"{neg}（{neg / len(scored) * 100:.0f}%）")
        sdf = pd.DataFrame({"情感": ["正面", "中性", "负面"], "数量": [pos, neu, neg]})
        st.bar_chart(sdf.set_index("情感"))
        label = ("整体偏正面 😊" if avg >= 0.6 else
                 "整体偏负面 😟" if avg <= 0.4 else "整体中性 😐")
        st.success(f"情感倾向：{label}（情感分基于{'SnowNLP' if HAVE_SNOWNLP else '内置词典'}的启发式估计，仅供参考）")
    else:
        st.caption("没有可供分析的评论文本。")

    # ---- 表情 / 表态 Top ----
    agg = aggregate_emoji(comments)
    if agg:
        st.subheader("🔥 表情 / 表态 Top 10")
        series = pd.Series(agg).sort_values(ascending=False).head(10)
        st.bar_chart(series)

    # ---- 热门评论卡片 ----
    rows = build_rows(comments)
    df = pd.DataFrame(rows)
    if not df.empty:
        df["点赞"] = pd.to_numeric(df["点赞"], errors="coerce").fillna(0).astype(int)
        hot = df.sort_values("点赞", ascending=False).head(8)
        st.subheader("💬 热门评论（按点赞排序）")
        for _, row in hot.iterrows():
            meta = f"👤 {row['用户名']}　👍 {row['点赞']}　💬 {row['回复数']}　🕒 {row['时间']}　💡 {row['情感']}"
            if row["表情表态"]:
                meta += f"　{row['表情表态']}"
            st.markdown(f"> {row['评论内容']}\n\n_{meta}_")

    # ---- 全部评论表格 + 下载 ----
    st.subheader("📋 全部评论")
    max_items = st.slider("列表展示条数", 10, 300, 60, key="maxitems")
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
