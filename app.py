#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
懂球帝评论爬虫 · Streamlit 演示版（可部署到 Streamlit Community Cloud）
========================================================================
界面模拟懂球帝新闻列表，用户直接点选新闻即可爬取评论，并额外生成
「评论词云」与「情感分析」。

  - 顶部加载懂球帝**实时**新闻列表（移动端 feed 接口 + 首页 HTML 兜底，
    全部失败才回退内置示例新闻）。
  - 直接点选新闻卡片 → 抓取该篇评论（优先网页版接口，失败回退 App 接口）。
  - 无外网 / 接口变更导致抓取失败时，自动回退到内置示例评论并显示提示横幅。
  - 词云：对评论内容做中文分词统计，按词频渲染标签云（无需额外字体）。
  - 情感分析：SnowNLP 给出每条评论的情感分（0~1），聚合为正面/中性/负面分布。

本地运行：
  pip install -r requirements.txt
  streamlit run app.py            # 默认 http://localhost:8501/
"""
import os
import re
import ssl
import sys
import json
import gzip
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

SOURCE_LABEL = {"v2": "App 接口（全量）", "webpage": "网页首屏", "sample": "示例数据"}

STOPWORDS = set(
    "的 了 是 在 我 你 他 她 它 我们 你们 他们 这 那 这个 那个 也 都 就 还 和 与 及 等 被 把 让 给 "
    "啊 吧 呢 吗 哦 呀 嘛 已经 一个 没有 不是 就是 还是 但是 因为 所以 自己 什么 怎么 这么 那么 "
    "现在 今天 一下 可以 这样 那样 这种 那种 其实 感觉 觉得 这场 那个 哪个 一个 我们 他们".split()
)

# 词典里的多字词（如"牛逼""拉胯"）会整体命中，不会被切碎误判
POS_WORDS = set(
    "赞 好 牛 强 棒 稳 猛 硬 燃 爽 美 神 喜 爱 挺 顶 冲 拼 绝杀 封神 世界波 神仙球 "
    "厉害 优秀 精彩 漂亮 完美 惊艳 惊喜 霸气 强势 稳健 靠谱 出色 出彩 亮眼 亮了 "
    "给力 争气 长脸 提气 解气 过瘾 痛快 舒服 开心 高兴 快乐 欢喜 欣喜 欣慰 激动 感动 "
    "期待 希望 可期 潜力 天赋 天才 妖星 新星 崛起 进步 提升 回暖 复苏 逆转 翻盘 "
    "取胜 获胜 拿下 制胜 晋级 出线 夺冠 冠军 登顶 完胜 碾压 统治 压制 吊打 完爆 "
    "热血 泪目 破防 震撼 燃爆 炸裂 火爆 无敌 传奇 史诗 神迹 神勇 神了 犀利 凌厉 "
    "生猛 强悍 勇猛 团结 拼搏 血性 斗志 坚韧 顽强 不屈 好样的 干得漂亮 未来可期 "
    "支持 力挺 看好 喜欢 最爱 恭喜 祝贺 可喜可贺 加油 稳了 牛逼 牛叉 太强 真香 "
    "不错 不赖 满意 放心 安心 治愈 享受 叹为观止 精彩绝伦 无可挑剔 "
    "开门红 首胜 连胜 全胜 不败 零封 大胜 好球 妙传 神扑 扑救 封堵 过人 突破 助攻 "
    "进球 破门 得分 领先 反超 扳平 帽子戏法 梅开二度 世界级 顶级 一流 巨星 球王 大师 "
    "真香 爷青回 稳如老狗 太秀了 秀 666 服气 甘拜下风 心服口服".split()
)
NEG_WORDS = set(
    "输 烂 差 弱 惨 崩 坑 假 黑 丑 坏 菜 水 废 渣 屎 臭 怒 恨 烦 痛 败 亏 "
    "垃圾 糟糕 差劲 拙劣 低劣 菜鸡 废物 烂队 烂货 恶心 下作 肮脏 脏球 恶意 "
    "黑哨 黑幕 假球 造假 演戏 剧本 内定 操纵 贿赂 偏哨 误判 错判 漏判 争议 争议判罚 "
    "失望 绝望 心寒 寒心 心碎 难过 难受 伤心 痛心 痛苦 悲伤 揪心 扎心 心塞 心疼 "
    "生气 愤怒 气愤 恼火 火大 暴怒 气人 气死 来气 窝火 憋屈 窝囊 憋闷 郁闷 "
    "愚蠢 蠢货 白痴 智障 脑残 弱智 傻逼 愚昧 无知 荒唐 荒谬 离谱 可笑 "
    "软弱 脆弱 不堪 无力 乏力 疲软 低迷 下滑 掉链子 拉胯 摆烂 摸鱼 消极 懈怠 懒散 "
    "惨败 凄惨 悲惨 惨淡 崩盘 崩溃 垮了 瓦解 崩塌 完蛋 完了 凉了 凉透 翻车 "
    "坑人 坑爹 坑货 拖累 拖后腿 累赘 负担 浪费 白瞎 白费 耽误 "
    "失误 犯错 送点 送分 送礼 散步 眼神防守 不积极 不作为 "
    "丢人 丢脸 现眼 出丑 耻辱 羞耻 尴尬 难堪 丢份 "
    "讨厌 反感 厌恶 唾弃 鄙视 看不起 嘲笑 嘲讽 讽刺 讥讽 喷子 吐槽 批评 指责 谴责 声讨 "
    "可惜 遗憾 惋惜 痛惜 无奈 无语 服了 醉了 麻了 佛了 "
    "伤病 受伤 伤退 报销 罚下 红牌 停赛 禁赛 下课 危机 隐患 乱象 混乱 "
    "不行 没戏 没救 完犊子 差评 差距 无力回天 一塌糊涂 乱七八糟 "
    "催眠 无聊 乏味 沉闷 慢吞吞 软绵绵 拖沓 松散 散漫 没劲 没意思 平淡 一言难尽 无话可说 "
    "呵呵 就这 打脸 摆大巴 龟缩 保守 懦弱 畏缩 怯场 软脚 软蛋 纸糊 豆腐渣 无耻 龌龊 卑鄙 "
    "假摔 跳水 卧草 拖延 拖延时间 无脑 离了大谱 寄了 摆完了 摆大烂".split()
)

# 否定词：命中位置前 3 字内出现即翻转情感（翻转后不再叠加程度副词）
NEGATORS = ["毫无", "并不", "并非", "绝不", "决不", "从不", "未曾", "未必", "不见得",
            "谈不上", "算不上", "不够", "不太", "不怎么", "没有", "不是", "不要", "不能",
            "不", "没", "无", "别", "非", "未", "否", "莫"]

# 程度副词：命中前出现则放大情感强度
INTENSIFIERS = [("爆表", 1.9), ("爆棚", 1.8), ("至极", 1.8), ("极度", 1.8), ("极", 1.8),
                ("爆", 1.7), ("万分", 1.7), ("无比", 1.7), ("极为", 1.7),
                ("太", 1.6), ("超", 1.6), ("巨", 1.6), ("非常", 1.6), ("绝对", 1.6), ("简直", 1.6),
                ("特别", 1.5), ("十分", 1.5), ("贼", 1.5), ("最", 1.5), ("分外", 1.5), ("尤为", 1.5),
                ("相当", 1.4), ("格外", 1.4), ("尤其", 1.4), ("实在", 1.4), ("着实", 1.4), ("顶", 1.4),
                ("真", 1.3), ("好", 1.3), ("很", 1.4)]

EMOJI_POS = ["👍", "👏", "🔥", "💪", "❤", "😍", "🎉", "🙌", "✨", "💯", "🏆", "😂", "🤣", "😊", "😁"]
EMOJI_NEG = ["😡", "😤", "😭", "🤮", "👎", "💩", "😠", "😞", "😔", "🙄", "🤬", "😒", "😢"]

# 长词优先匹配：保证"牛逼"整体命中，而不是只命中"牛"
_ALL_WORDS = sorted(POS_WORDS | NEG_WORDS, key=len, reverse=True)
WORD_RE = re.compile("(" + "|".join(re.escape(w) for w in _ALL_WORDS) + ")")


# ------------------------- 新闻列表获取（点选爬取） -------------------------
def _read_body(r):
    """读取响应体，自动处理 gzip。"""
    raw = r.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "ignore")


def _http_get_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=12, context=ctx) as r:
        return json.loads(_read_body(r))


def _http_get_text(url, headers):
    req = urllib.request.Request(url, headers=headers)
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=12, context=ctx) as r:
        return _read_body(r)


# App tab feed（实测有内容且去重后量最大的 tab）：
# 1=头条 3=英超 4=意甲 5=西甲 6=德甲 11=集锦 12=法甲 13=综合 37=闲情
APP_FEED_TABS = [1, 3, 4, 5, 6, 11, 12, 13, 37]


def parse_feed(data):
    """从 App tab feed JSON 抽取文章列表（含封面 / 分类 / 评论数）。"""
    out = []
    for it in (data or {}).get("articles") or []:
        if not isinstance(it, dict):
            continue
        aid = it.get("id")
        title = it.get("title") or it.get("share_title")
        if not aid or not title:
            continue
        cover = it.get("thumb")
        if cover and not str(cover).startswith("http"):
            cover = None
        out.append({
            "id": str(aid),
            "title": str(title).strip(),
            "cover": cover,
            "time": fmt_time(it.get("published_at") or it.get("created_at")),
            "raw_time": it.get("sort_timestamp") or it.get("created_at"),
            "tag": str(it.get("category") or ""),
            "comments": it.get("comments_total"),
        })
    return out


def fetch_news_list():
    """获取懂球帝实时新闻列表（实测可拿到 80+ 条）。

    主源：App tab feed `api.dongqiudi.com/app/tabs/iphone/{tab}.json`
          遍历多个内容 tab（头条/英超/意甲/西甲/德甲/集锦/法甲/综合/闲情）后去重。
          注：该接口的 prev/page/before 参数实测**不会真正翻页**（永远返回同一页），
              所以靠"多 tab"而不是"翻页"来扩量。
    兜底：官网首页 HTML（约 25 条）
    再失败 → 内置示例

    返回 (news_list, is_demo)：
      - 抓到文章 -> (真实列表, False)
      - 全部失败 -> (内置示例, True)，由调用方显示 ⚠️，绝不假装实时。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    # ---- 主源：多个 tab 合并去重（单 tab 失败不影响其它）----
    arts, seen = [], set()
    for tab in APP_FEED_TABS:
        try:
            data = _http_get_json(
                f"https://api.dongqiudi.com/app/tabs/iphone/{tab}.json?version=177",
                headers,
            )
        except Exception:  # noqa: BLE001
            continue
        for a in parse_feed(data):
            if a["id"] in seen:
                continue
            seen.add(a["id"])
            arts.append(a)
    if arts:
        return arts, False

    # ---- 兜底：官网首页 HTML ----
    h2 = dict(headers)
    h2["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    for site in ("https://www.dongqiudi.com/", "https://m.dongqiudi.com/"):
        try:
            home = parse_homepage(_http_get_text(site, h2))
            if home:
                return home, False
        except Exception:  # noqa: BLE001
            continue
    return SAMPLE_NEWS, True


def _pick(d, *keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def parse_articles(data):
    """从多种 JSON 布局中抽取文章列表。"""
    out = []
    d = data.get("data") if isinstance(data, dict) else data
    # 逐层寻找数组
    arr = None
    if isinstance(d, dict):
        for k in ("item_list", "article_list", "list", "items", "articles", "feed", "results", "rows"):
            if isinstance(d.get(k), list):
                arr = d[k]
                break
        if arr is None:
            # 某些接口把数组放在 data 直接是列表
            for v in d.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    arr = v
                    break
    elif isinstance(d, list):
        arr = d
    if not arr:
        return []
    seen = set()
    for it in arr[:40]:
        if not isinstance(it, dict):
            continue
        aid = str(_pick(it, "article_id", "id", "aid", "item_id") or "")
        title = _pick(it, "title", "title2", "name", "subject") or ""
        if not aid or not title or aid in seen:
            continue
        seen.add(aid)
        cover = _pick(it, "thumb", "cover", "img", "image", "pic", "image_url", "thumbnail")
        if cover and not str(cover).startswith("http"):
            cover = None
        raw_time = _pick(it, "published_at", "time", "show_time", "create_time", "date")
        out.append({
            "id": aid,
            "title": str(title).strip(),
            "cover": cover,
            "time": fmt_time(raw_time),
            "raw_time": raw_time,
            "tag": str(_pick(it, "label", "tag", "category", "label_name") or ""),
        })
    return out


def parse_homepage(html):
    """从官网首页 HTML 中稳健抽取 /articles/{id}.html 文章卡片（含标题/封面）。

    策略：优先用 <a href=".../articles/{id}.html">链接文本</a> 抽取（最可靠），
    链接文本里通常含「分类 标题 时间·评论数」，做必要清洗后保留标题；
    若锚点匹配失败，再用宽松正则兜底抓文章 ID。
    """
    out = []
    seen = set()
    # 1) 锚点链接抽取（兼容单/双引号、相对/绝对 URL）
    anchor = re.compile(
        r'<a\b[^>]*?href=["\']([^"\']*?/articles/(\d+)\.html)["\'][^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    for m in anchor.finditer(html):
        aid = m.group(2)
        if aid in seen:
            continue
        seen.add(aid)
        inner = m.group(3)
        # 优先取 class 含 title 的元素文本，否则取整段链接文本
        tm = re.search(r'class=["\'][^"\']*title[^"\']*["\']>(.*?)</', inner, re.IGNORECASE | re.DOTALL)
        raw = tm.group(1) if tm else inner
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()
        # 去除尾部/混杂的元数据：日期、评论数、相对时间
        text = re.sub(r"\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}.*$", "", text).strip()
        text = re.sub(r".*?·\s*\d+\s*评论.*$", "", text).strip()
        text = re.sub(r"\d+\s*评\s*.*$", "", text).strip()
        text = re.sub(r"(刚刚|分钟前|小时前|天前).*$", "", text).strip()
        if len(text) < 4:
            text = f"懂球帝文章 #{aid}"
        # 往前 2000 字符找封面图
        back = html[max(0, m.start() - 2000):m.start()]
        cm = re.search(r'<img\b[^>]*?src=["\']([^"\']+\.(?:jpg|jpeg|png|webp))["\']', back, re.IGNORECASE)
        cover = cm.group(1) if cm else None
        if cover and cover.startswith("//"):
            cover = "https:" + cover
        out.append({"id": aid, "title": text, "cover": cover, "time": "", "tag": "", "raw_time": None})
        if len(out) >= 40:
            break
    # 2) 兜底：宽松匹配任何 /articles/{id}.html
    if not out:
        for m in re.finditer(r'(?:href=["\']?|"/)(?:https?://[^\s"\']*?)?/articles/(\d+)\.html', html):
            aid = m.group(1)
            if aid in seen:
                continue
            seen.add(aid)
            out.append({"id": aid, "title": f"懂球帝文章 #{aid}", "cover": None, "time": "", "tag": "", "raw_time": None})
    # 去重保序
    uniq = {}
    for o in out:
        uniq.setdefault(o["id"], o)
    return list(uniq.values())[:40]


def fmt_time(raw):
    if raw in (None, ""):
        return ""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        try:
            dt = datetime.fromtimestamp(raw / 1000) if raw > 1e11 else datetime.fromtimestamp(raw)
            return dt.strftime("%m-%d %H:%M")
        except Exception:
            return ""
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%m-%d %H:%M")
        except Exception:
            continue
    return s[:16]


# ------------------------- 纯函数：数据处理（可单测） ------------------------
# v2 评论没有表情字段，改从正文里提取 emoji（覆盖两个常用码段）
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")


def aggregate_emoji(comments):
    """表情统计：兼容旧接口的 emoji_stats，同时从评论正文里提取 emoji。"""
    agg = {}
    for c in comments:
        stats = c.get("emoji_stats") or []
        if isinstance(stats, list):
            for e in stats:
                if isinstance(e, dict) and e.get("key"):
                    agg[e["key"]] = agg.get(e["key"], 0) + int(e.get("count", 0) or 0)
        for ch in EMOJI_RE.findall(c.get("content") or ""):
            agg[ch] = agg.get(ch, 0) + 1
    return agg


def aggregate_location(comments):
    """评论地区分布（v2 接口提供 iptext 字段）。"""
    agg = {}
    for c in comments:
        loc = (c.get("location") or "").strip()
        if loc:
            agg[loc] = agg.get(loc, 0) + 1
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
    """返回 0~1 的情感分。

    ⚠️ 旧实现用 re.findall(r"[\\u4e00-\\u9fff]{1,}") 切词，会把整段中文当成**一个**
    token（如"这场比赛真好看"），导致词典词永远匹配不上、几乎全部判为中性。
    现改为：用「长词优先」的正则在原文里直接匹配词典词，并对每个命中判断
    ① 前面是否有否定词（翻转）② 前面是否有程度副词（放大），最后再计入表情符号。
    """
    text = (text or "").strip()
    if not text:
        return 0.5
    if HAVE_SNOWNLP:
        try:
            return float(SnowNLP(text).sentiments)
        except Exception:  # noqa: BLE001
            pass

    raw = 0.0
    for m in WORD_RE.finditer(text):
        val = 1.0 if m.group(1) in POS_WORDS else -1.0
        prefix = text[max(0, m.start() - 3):m.start()]
        if any(prefix.endswith(n) for n in NEGATORS):
            # 否定翻转（如"不好""太差了没救"），略微衰减，且不再叠加程度副词
            val = -val * 0.9
        else:
            for adv, mult in INTENSIFIERS:
                if prefix.endswith(adv):
                    val *= mult
                    break
        raw += val

    for e in EMOJI_POS:
        raw += 0.5 * text.count(e)
    for e in EMOJI_NEG:
        raw -= 0.5 * text.count(e)

    if raw == 0:
        return 0.5
    # 平滑压缩到 0~1，避免长评论分数爆炸
    return 0.5 + 0.5 * (raw / (abs(raw) + 2.0))


def classify(s):
    """细分 5 档，避免大量评论被粗暴地归为『中性』。"""
    if s >= 0.72:
        return "强正面"
    if s >= 0.60:
        return "正面"
    if s > 0.40:
        return "中性"
    if s > 0.28:
        return "负面"
    return "强负面"


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
            "地区": c.get("location") or "",
            "情感": classify(s),
            "情感分": round(s, 2),
            "表情表态": emoji_str,
        })
    return rows


def fetch_or_sample(article_id):
    """抓取某篇文章评论；仅当所有来源全部失败才回退示例数据。返回 (result, is_demo)。

    source == "failed" 才视为演示数据；webpage/web/v2（即使是 0 条真实评论）都算真实数据，
    避免给「没评论的文章」塞假数据。
    """
    try:
        # max_pages=120：v2 每页 20 条 → 最多约 2400 条评论，足够覆盖绝大多数文章
        r = dqd.crawl_article(article_id, max_pages=120)
    except Exception as e:  # noqa: BLE001
        r = {"article_id": article_id, "source": "failed", "total": 0, "comments": [],
             "error": str(e), "reasons": [str(e)]}
    if (not r) or r.get("source") == "failed":
        return {
            "article_id": article_id, "source": "sample",
            "total": len(SAMPLE["comments"]), "comments": SAMPLE["comments"], "demo": True,
            "reasons": r.get("reasons") or [],
        }, True
    r["demo"] = False
    return r, False


# ------------------------- 小型 HTML 渲染辅助 -------------------------
def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def render_h(title):
    """板块标题（配合 st.container(border=True) 使用的首行标题）。"""
    return f'<div class="dqd-h">{title}</div>'


def render_sent_chips(avg, pos, neu, neg):
    """情感概览小卡（平均分 + 三档计数）。"""
    def chip(v, k, cls=""):
        c = f" {cls}" if cls else ""
        return f'<div class="dqd-chip{c}"><div class="v">{v}</div><div class="k">{k}</div></div>'
    return ('<div class="dqd-chips">'
            + chip(f"{avg:.2f}", "平均情感分")
            + chip(str(pos), "正面", "pos")
            + chip(str(neu), "中性", "neu")
            + chip(str(neg), "负面", "neg")
            + '</div>')


def render_hero():
    return """
    <div class="dqd-hero">
      <div class="logo">⚽</div>
      <div>
        <h1>懂球帝 · 新闻评论爬取 Demo</h1>
        <p>像懂球帝一样浏览实时新闻，点选新闻即可爬取评论，并自动生成词云与情感分析</p>
      </div>
    </div>
    """


def render_stat_tiles(stats):
    tiles = ""
    for v, k, cls in stats:
        tiles += f'<div class="dqd-stat {cls}"><div class="v">{esc(v)}</div><div class="k">{esc(k)}</div></div>'
    return f'<div class="dqd-stats">{tiles}</div>'


def render_sentiment_bar(pos, neu, neg, total):
    if total <= 0:
        return '<p style="color:#888">暂无可分析文本</p>'
    pp = pos / total * 100
    np_ = neu / total * 100
    ng = neg / total * 100
    return f"""
    <div class="dqd-sent">
      <div style="width:{pp:.1f}%;background:#16a34a">{pp:.0f}%</div>
      <div style="width:{np_:.1f}%;background:#9ca3af">{np_:.0f}%</div>
      <div style="width:{ng:.1f}%;background:#dc2626">{ng:.0f}%</div>
    </div>
    <div style="display:flex;justify-content:space-between;font-size:12px;color:#6b7280">
      <span>😊 正面 {pos}</span><span>😐 中性 {neu}</span><span>😟 负面 {neg}</span>
    </div>
    """


def render_emoji_bars(agg, top=10):
    if not agg:
        return '<p style="color:#888">无表情表态数据</p>'
    series = sorted(agg.items(), key=lambda x: -x[1])[:top]
    mx = max(c for _, c in series)
    rows = ""
    for k, c in series:
        pct = c / mx * 100
        rows += f"""
        <div class="dqd-ebar">
          <div class="lab">{esc(k)} <span style="color:#9ca3af">· {c}</span></div>
          <div class="track"><div class="fill" style="width:{pct:.0f}%"></div></div>
        </div>"""
    return rows


def render_hot(comments, topn=8):
    if not comments:
        return '<p style="color:#888">暂无评论</p>'
    rows = build_rows(comments)
    df = pd.DataFrame(rows)
    if df.empty:
        return '<p style="color:#888">暂无评论</p>'
    df["点赞"] = pd.to_numeric(df["点赞"], errors="coerce").fillna(0).astype(int)
    hot = df.sort_values("点赞", ascending=False).head(topn)
    html = ""
    for _, r in hot.iterrows():
        meta = (f"👤 {esc(r['用户名'])}　👍 {r['点赞']}　💬 {r['回复数']}　"
                f"🕒 {esc(r['时间'])}　💡 {esc(r['情感'])}（{r['情感分']}）")
        if r.get("地区"):
            meta += f"　📍 {esc(r['地区'])}"
        if r["表情表态"]:
            meta += f"　{esc(r['表情表态'])}"
        html += f"""
        <div class="dqd-hot">
          <div class="c">{esc(r['评论内容'])}</div>
          <div class="m">{meta}</div>
        </div>"""
    return html


# ------------------------- UI（仅在 streamlit 运行时执行） -------------------
def main():
    st.set_page_config(page_title="懂球帝评论爬取 Demo", page_icon="⚽", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    # ---- session state ----
    for key in ("news", "selected", "sel_title", "results"):
        if key not in st.session_state:
            st.session_state[key] = (None if key in ("news", "selected") else
                                     ("" if key == "sel_title" else {}))
    if "page" not in st.session_state:
        st.session_state.page = 1
    if "last_query" not in st.session_state:
        st.session_state.last_query = ""

    # 支持 ?sel=<文章ID> 直接打开某篇的分析（可分享链接）
    _qp_sel = st.query_params.get("sel")
    if _qp_sel and not st.session_state.selected:
        st.session_state.selected = str(_qp_sel)

    st.markdown(render_hero(), unsafe_allow_html=True)

    # ---- 首次自动拉取真实新闻 ----
    if st.session_state.news is None:
        with st.spinner("正在获取懂球帝实时新闻…"):
            st.session_state.news = fetch_news_list()

    # ---- 工具栏：刷新按钮（左） + 状态提示（右） ----
    c_btn, c_status = st.columns([1, 4], gap="medium")
    with c_btn:
        if st.button("🔄 刷新实时新闻", width="stretch", type="primary"):
            with st.spinner("正在重新获取懂球帝实时新闻…"):
                st.session_state.news = fetch_news_list()
                st.session_state.selected = None
                st.session_state.results = {}
                st.session_state.page = 1
                st.rerun()
    news, is_demo_news = st.session_state.news
    with c_status:
        if is_demo_news:
            st.warning("⚠️ 未能联网获取实时新闻，当前为内置示例新闻。", icon="⚠️")
        else:
            st.success(f"✅ 已加载 {len(news)} 条懂球帝实时新闻，点选卡片即可爬取评论。", icon="✅")

    # ---- 新闻区：搜索 + 每页条数 ----
    st.markdown('<div class="dqd-section-title">📰 实时新闻 · 点选一篇爬取评论</div>',
                unsafe_allow_html=True)
    c_q, c_page = st.columns([3, 1], gap="medium")
    with c_q:
        q = st.text_input("搜索新闻", key="news_query", label_visibility="collapsed",
                          placeholder="🔍 搜索新闻标题（如：亚冠 / 曼城 / 申花）")
    with c_page:
        per_page = st.selectbox("每页条数", [9, 12, 18, 24], index=1,
                                key="per_page", label_visibility="collapsed")

    # 关键词变化 → 回到第 1 页
    if st.session_state.last_query != q:
        st.session_state.last_query = q
        st.session_state.page = 1

    qn = (q or "").strip().lower()
    filtered = [a for a in news
                if (not qn)
                or qn in a["title"].lower()
                or qn in str(a.get("tag") or "").lower()]
    total_pages = max(1, (len(filtered) + per_page - 1) // per_page)
    page = min(max(1, int(st.session_state.page)), total_pages)
    st.session_state.page = page
    page_items = filtered[(page - 1) * per_page: page * per_page]

    # ---- 新闻网格（3 列卡片，按当前页渲染）----
    if not filtered:
        st.markdown(f'<div class="dqd-hint">没有匹配「{esc(q)}」的新闻，换个关键词试试。</div>',
                    unsafe_allow_html=True)
    else:
        cols = st.columns(3, gap="medium")
        for i, art in enumerate(page_items):
            with cols[i % 3]:
                with st.container(border=True, key=f"card_{art['id']}"):
                    if art.get("cover"):
                        try:
                            st.image(art["cover"], width="stretch")
                        except Exception:  # noqa: BLE001
                            st.markdown(PLACEHOLDER_COVER, unsafe_allow_html=True)
                    else:
                        st.markdown(PLACEHOLDER_COVER, unsafe_allow_html=True)
                    st.markdown(f'<div class="dqd-title">{esc(art["title"])}</div>',
                                unsafe_allow_html=True)
                    meta = " · ".join([x for x in [art.get("tag"), art.get("time")] if x])
                    if art.get("comments") is not None:
                        meta += f"　💬 {art['comments']}"
                    st.markdown(f'<div class="dqd-meta">{esc(meta or "懂球帝")}</div>',
                                unsafe_allow_html=True)
                    if st.button("📥 爬取评论", key=f"btn_{art['id']}", width="stretch"):
                        st.session_state.selected = art["id"]
                        st.session_state.sel_title = art["title"]

        # ---- 分页控件 ----
        pg1, pg2, pg3 = st.columns([1, 3, 1], gap="medium")
        with pg1:
            if st.button("‹ 上一页", key="pg_prev", width="stretch", disabled=(page <= 1)):
                st.session_state.page = page - 1
                st.rerun()
        with pg2:
            info = f"第 {page} / {total_pages} 页　·　共 {len(filtered)} 条"
            if qn:
                info += f"　·　关键词「{esc(q)}」"
            st.markdown(f'<div class="dqd-pageinfo">{info}</div>', unsafe_allow_html=True)
        with pg3:
            if st.button("下一页 ›", key="pg_next", width="stretch",
                         disabled=(page >= total_pages)):
                st.session_state.page = page + 1
                st.rerun()

    # ---- 未选择新闻时的引导 ----
    sel = st.session_state.selected
    if not sel:
        st.markdown('<div class="dqd-hint">👆 点击上方任意新闻卡片的「爬取评论」，'
                    '即可抓取该文评论并生成词云与情感分析</div>', unsafe_allow_html=True)
        st.stop()

    # ---- 已选新闻标题 ----
    st.markdown(f'<div class="dqd-sel-title">📰 {esc(st.session_state.get("sel_title", ""))}</div>',
                unsafe_allow_html=True)

    if sel not in st.session_state.results:
        with st.spinner("正在爬取评论（App 接口全量翻页 → 网页首屏兜底）…"):
            res, demo = fetch_or_sample(sel)
            st.session_state.results[sel] = (res, demo)
    res, demo = st.session_state.results[sel]

    # 注意：必须先赋值再判断，否则 elif 中的 total 未定义会抛 NameError
    comments = res["comments"]
    source = res["source"]
    total = res["total"]

    if demo:
        st.warning(
            "⚠️ 当前为**演示数据**：未能抓到真实评论。"
            "已依次尝试「文章页 → 网页接口 → App 接口」，均失败。",
            icon="⚠️",
        )
        reasons = res.get("reasons") or []
        if reasons:
            with st.expander("🔍 查看失败原因（排查用）"):
                for rr in reasons:
                    st.code(rr)
    elif total == 0:
        st.info("该文章当前没有评论（或评论已关闭），换一篇试试～")

    # ---- 概览磁贴 ----
    times = [t for t in (parse_time(c.get("created_at")) for c in comments) if t]
    earliest = min(times).strftime("%m-%d %H:%M") if times else "—"
    latest = max(times).strftime("%m-%d %H:%M") if times else "—"
    st.markdown(render_stat_tiles([
        (total, "评论总数", "red"),
        (SOURCE_LABEL.get(source, source), "数据来源", ""),
        (earliest, "最早评论", ""),
        (latest, "最新评论", ""),
    ]), unsafe_allow_html=True)

    # ---- 第一行：词云 ｜ 情感分析 ----
    a1, a2 = st.columns(2, gap="large")
    with a1:
        with st.container(border=True, key="panel_wordcloud"):
            st.markdown(render_h("☁️ 评论词云"), unsafe_allow_html=True)
            top = build_word_freq(comments)
            st.markdown(render_wordcloud(top), unsafe_allow_html=True)
            note = ("基于 jieba 中文分词统计词频，按频率渲染字号" if HAVE_JIEBA
                    else "未安装 jieba，已用正则提取中文词；pip install jieba 可获得更准的分词")
            st.markdown(f'<div class="dqd-note">（{esc(note)}）</div>', unsafe_allow_html=True)

    with a2:
        with st.container(border=True, key="panel_sent"):
            st.markdown(render_h(f"💡 情感分析 · 全部 {len(comments)} 条评论逐条赋分"),
                        unsafe_allow_html=True)
            scored = [sentiment_score(c.get("content", "")) for c in comments]
            if scored:
                avg = sum(scored) / len(scored)
                pos = sum(1 for s in scored if s >= 0.6)
                neg = sum(1 for s in scored if s <= 0.4)
                neu = len(scored) - pos - neg
                st.markdown(render_sent_chips(avg, pos, neu, neg), unsafe_allow_html=True)
                st.markdown(render_sentiment_bar(pos, neu, neg, len(scored)),
                            unsafe_allow_html=True)

                # 5 档细分：避免只用「正面/中性/负面」三档一笔带过
                lv = {}
                for s in scored:
                    k = classify(s)
                    lv[k] = lv.get(k, 0) + 1
                st.markdown(
                    '<div class="dqd-note">细分档位：' + "　".join(
                        f"{k} {lv.get(k, 0)}（{lv.get(k, 0) / len(scored) * 100:.0f}%）"
                        for k in ["强正面", "正面", "中性", "负面", "强负面"]
                    ) + '</div>', unsafe_allow_html=True)

                label = ("整体偏正面 😊" if avg >= 0.6 else
                         "整体偏负面 😟" if avg <= 0.4 else "整体中性 😐")
                src = "SnowNLP" if HAVE_SNOWNLP else "内置词典"
                st.markdown(
                    f'<div class="dqd-verdict">情感倾向：{label}'
                    f'<span class="src">（基于{src}的启发式估计，仅供参考）</span></div>',
                    unsafe_allow_html=True)
            else:
                st.caption("没有可供分析的评论文本。")

    # ---- 第二行：表情 / 地区 ｜ 热门评论 ----
    emoji_agg = aggregate_emoji(comments)
    loc_agg = aggregate_location(comments)
    # 优先地区分布（v2 主源提供、数据更密）；没有地区才退回表情；都没有给说明
    if loc_agg:
        side_title, side_html = "🌍 评论来源地区 Top 10", render_emoji_bars(loc_agg, 10)
    elif emoji_agg:
        side_title, side_html = "🔥 表情 / 表态 Top 10", render_emoji_bars(emoji_agg, 10)
    else:
        side_title = "🌍 评论来源地区"
        side_html = '<div class="dqd-note">该数据来源暂无地区 / 表情统计数据</div>'

    b1, b2 = st.columns(2, gap="large")
    with b1:
        with st.container(border=True, key="panel_side"):
            st.markdown(render_h(side_title), unsafe_allow_html=True)
            st.markdown(side_html, unsafe_allow_html=True)
    with b2:
        with st.container(border=True, key="panel_hot"):
            st.markdown(render_h("💬 热门评论 · 按点赞排序"), unsafe_allow_html=True)
            st.markdown(render_hot(comments, 6), unsafe_allow_html=True)

    # ---- 第三行：全部评论（整行）----
    with st.container(border=True, key="panel_all"):
        reported = res.get("reported_total")
        all_note = f"共抓取 {total} 条评论"
        if reported and reported > total:
            all_note += f"（接口自报总数 {reported}，含二级回复）"
        st.markdown(render_h(f"📋 全部评论 · {all_note}"), unsafe_allow_html=True)
        rows = build_rows(comments)
        df = pd.DataFrame(rows)
        if df.empty:
            st.caption("暂无评论数据。")
        else:
            n = len(df)
            if n > 60:
                max_items = st.slider("列表展示条数", 60, n, n, step=20, key="maxitems")
            else:
                max_items = n
            st.dataframe(df.head(max_items), width="stretch", height=460)
            st.download_button(
                f"⬇️ 下载全部 {n} 条评论（CSV）",
                df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"dongqiudi_{res['article_id']}.csv",
                mime="text/csv",
            )

    st.markdown('<div class="dqd-foot">数据来自懂球帝公开页面，仅供学习研究使用。</div>',
                unsafe_allow_html=True)


PLACEHOLDER_COVER = (
    '<div style="height:150px;background:linear-gradient(135deg,#d51d2a,#ff6a3d);'
    'border-radius:12px;display:flex;align-items:center;justify-content:center;'
    'color:#fff;font-size:46px">⚽</div>'
)

CSS = """
<style>
:root{
  --dqd-red:#d51d2a; --dqd-red2:#ff5a3c; --ink:#15181d; --muted:#6b7280;
  --bg:#f4f5f7; --card:#ffffff; --soft:#fafbfc; --line:#e9ebef;
  --radius:16px; --shadow:0 1px 3px rgba(16,24,40,.05), 0 8px 24px rgba(16,24,40,.05);
}
html,body,[data-testid="stAppViewContainer"]{background:var(--bg)!important;}
.block-container{max-width:1360px!important;margin:0 auto!important;
  padding:1.2rem 1.6rem 3rem!important;}

/* ---------- hero ---------- */
.dqd-hero{
  background:linear-gradient(120deg,var(--dqd-red),var(--dqd-red2));
  border-radius:var(--radius);padding:20px 26px;color:#fff;
  box-shadow:0 10px 30px rgba(213,29,42,.22);margin-bottom:14px;
  display:flex;align-items:center;gap:16px;
}
.dqd-hero .logo{font-size:38px;line-height:1;}
.dqd-hero h1{margin:0;font-size:22px;font-weight:800;letter-spacing:.5px;}
.dqd-hero p{margin:5px 0 0;opacity:.93;font-size:13px;}

/* ---------- 通用标题 ---------- */
.dqd-section-title{font-size:17px;font-weight:800;color:var(--ink);
  margin:20px 0 12px;padding-left:10px;border-left:4px solid var(--dqd-red);}
.dqd-h{display:flex;align-items:center;gap:8px;font-size:15px;font-weight:800;
  color:var(--ink);margin:0 0 12px;padding-bottom:10px;border-bottom:1px solid var(--line);}

/* ---------- 卡片：给 st.container 加 key 后，用官方 st-key-* 类名精准命中 ---------- */
[class*="st-key-card_"], [class*="st-key-panel_"]{
  background:var(--card)!important;
  border-radius:var(--radius)!important;
  box-shadow:var(--shadow)!important;
  transition:box-shadow .18s ease, transform .18s ease;
}
[class*="st-key-card_"]:hover{
  transform:translateY(-3px);box-shadow:0 12px 28px rgba(16,24,40,.12)!important;}

/* ---------- 新闻卡片 ---------- */
[data-testid="stImage"] img{height:150px;width:100%;object-fit:cover;
  border-radius:12px;display:block;}
.dqd-title{font-weight:700;font-size:15px;line-height:1.45;color:var(--ink);
  min-height:44px;margin:8px 0 4px;}
.dqd-meta{font-size:12px;color:var(--muted);}

/* ---------- 情感概览小卡 ---------- */
.dqd-chips{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:2px 0 14px;}
.dqd-chip{background:var(--soft);border:1px solid var(--line);border-radius:12px;
  padding:10px 4px;text-align:center;}
.dqd-chip .v{font-size:19px;font-weight:800;color:var(--ink);line-height:1.2;}
.dqd-chip .k{font-size:11px;color:var(--muted);margin-top:3px;}
.dqd-chip.pos .v{color:#16a34a;}
.dqd-chip.neg .v{color:#dc2626;}

/* ---------- 概览磁贴 ---------- */
.dqd-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:14px 0 4px;}
.dqd-stat{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  padding:16px;text-align:center;box-shadow:var(--shadow);}
.dqd-stat .v{font-size:22px;font-weight:800;color:var(--ink);}
.dqd-stat .k{font-size:12px;color:var(--muted);margin-top:3px;}
.dqd-stat.red .v{color:var(--dqd-red);}

/* ---------- 情感堆叠条 ---------- */
.dqd-sent{display:flex;height:26px;border-radius:999px;overflow:hidden;
  margin:4px 0 8px;background:#eef0f3;}
.dqd-sent>div{display:flex;align-items:center;justify-content:center;color:#fff;
  font-size:12px;font-weight:700;transition:width .4s ease;}

/* ---------- 文字说明 / 结论 ---------- */
.dqd-note{font-size:12px;color:var(--muted);line-height:1.65;}
.dqd-verdict{margin-top:12px;padding:10px 14px;border-radius:12px;font-size:14px;
  font-weight:700;color:var(--ink);background:#fef6f3;border:1px solid #f7ddd5;}
.dqd-verdict .src{font-weight:400;color:var(--muted);font-size:12px;margin-left:6px;}
.dqd-foot{margin:26px 0 6px;text-align:center;font-size:12px;color:#9aa1ab;}

/* ---------- 已选标题 / 引导 ---------- */
.dqd-sel-title{font-size:18px;font-weight:800;color:var(--ink);
  margin:26px 0 14px;padding:14px 18px;background:var(--card);border:1px solid var(--line);
  border-left:5px solid var(--dqd-red);border-radius:12px;box-shadow:var(--shadow);}
.dqd-hint{margin:18px 0;padding:16px 20px;background:var(--card);
  border:1px dashed #d8dbe0;border-radius:12px;color:var(--muted);font-size:14px;}
/* 分页信息条 */
.dqd-pageinfo{margin:0;padding:11px 14px;text-align:center;font-size:13px;
  font-weight:700;color:var(--ink);background:var(--card);border:1px solid var(--line);
  border-radius:12px;box-shadow:var(--shadow);}

/* ---------- 热门评论 ---------- */
.dqd-hot{background:var(--soft);border:1px solid var(--line);border-left:4px solid var(--dqd-red);
  border-radius:12px;padding:12px 14px;margin-bottom:10px;}
.dqd-hot:last-child{margin-bottom:0;}
.dqd-hot .c{font-size:14px;color:var(--ink);line-height:1.55;}
.dqd-hot .m{font-size:12px;color:var(--muted);margin-top:7px;}

/* ---------- 表情条 ---------- */
.dqd-ebar{margin:9px 0;}
.dqd-ebar .lab{font-size:13px;color:var(--ink);display:flex;justify-content:space-between;}
.dqd-ebar .track{background:#eef0f3;border-radius:999px;height:10px;overflow:hidden;margin-top:4px;}
.dqd-ebar .fill{background:linear-gradient(90deg,var(--dqd-red),var(--dqd-red2));
  height:100%;border-radius:999px;}

/* ---------- 按钮：默认描边，primary 实心 ---------- */
.stButton>button{border-radius:10px!important;font-weight:700!important;
  border:1px solid var(--dqd-red)!important;color:var(--dqd-red)!important;
  background:#fff!important;transition:background .15s ease;}
.stButton>button:hover{background:#fef2f2!important;}
.stButton>button:disabled{border-color:var(--line)!important;color:#b6bcc4!important;
  background:#f7f8fa!important;}
.stButton>button[kind="primary"]{
  background:linear-gradient(120deg,var(--dqd-red),var(--dqd-red2))!important;
  color:#fff!important;border:none!important;}
.stDownloadButton>button{border-radius:10px!important;font-weight:700!important;
  border:1px solid var(--line)!important;}
</style>
"""

if __name__ == "__main__":
    main()
