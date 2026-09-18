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
from concurrent.futures import ThreadPoolExecutor
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

try:
    import dongqiudi_data as DD  # noqa: E402  功能二：数据分析数据层
except ImportError:  # 适配 demo 目录
    sys.path.insert(0, os.path.dirname(HERE))
    import dongqiudi_data as DD  # noqa: E402

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
    {"id": "6358712", "title": "国足0-2不敌日本，世预赛出线形势告急", "cover": None,
     "time": "2小时前", "tag": "国家队", "league": "国家队", "comments": 2841},
    {"id": "6359476", "title": "梅西任意球破门，迈阿密国际晋级季后赛", "cover": None,
     "time": "4小时前", "tag": "国际", "league": "国际", "comments": 1520},
    {"id": "6359021", "title": "英超焦点战：阿森纳3-1逆转曼联", "cover": None,
     "time": "6小时前", "tag": "英超", "league": "英超", "comments": 3362},
    {"id": "6358890", "title": "皇马2-0赫罗纳，稳居西甲榜首", "cover": None,
     "time": "8小时前", "tag": "西甲", "league": "西甲", "comments": 1204},
    {"id": "6358765", "title": "欧冠1/4决赛抽签：拜仁再遇皇马", "cover": None,
     "time": "10小时前", "tag": "欧冠", "league": "欧冠", "comments": 986},
    {"id": "6358633", "title": "中超第12轮：上海海港5-0大胜对手", "cover": None,
     "time": "12小时前", "tag": "中超", "league": "中超", "comments": 745},
]

# 标签筛选：五大联赛强队 + 知名国家队 + 主要赛事/联赛
NEWS_TAGS = [
    # 赛事 / 联赛
    "英超", "意甲", "西甲", "德甲", "法甲", "欧冠", "欧联", "中超", "世界杯",
    # 五大联赛强队
    "曼城", "利物浦", "阿森纳", "切尔西", "曼联", "热刺", "皇马", "巴萨", "马竞",
    "拜仁", "多特", "尤文", "国米", "AC米兰", "那不勒斯", "巴黎",
    # 知名国家队
    "国足", "阿根廷", "巴西", "法国", "英格兰", "西班牙", "德国", "葡萄牙",
    "荷兰", "意大利", "日本", "韩国",
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

# 词云停用词：通用词 / 口语填充词 / 指代词 / 连接词 / 泛化名词一律过滤，
# 让足球相关词（球队、球员、位置、战术、赛事）在词云里凸显出来。
STOPWORDS = set("""
的 了 是 在 我 你 他 她 它 咱 咱们 我们 你们 他们 她们 大家 人家 别人 有人 自己
这 那 这个 那个 这些 那些 这种 那种 这里 那里 这边 那边 这样 那样 类似 之类 等等 其他 其它 别的 各种 各个
也 都 就 还 又 再 才 却 很 太 更 最 挺 蛮 真 假 有些 有点 一些 一点 一下 一直 一旦 一定 一样 一起 一般 一向
和 与 及 以及 或 或者 还是 而且 并且 而 但 但是 不过 可是 然而 只是 只有 只要 就是 即使 虽然 尽管 即使
如果 假如 要是 因为 由于 所以 因此 于是 然后 接着 最后 首先 其次 另外 此外 总之 反正 毕竟 其实 确实 的确
当然 显然 果然 竟然 居然 难道 也许 大概 大约 差不多 几乎 完全 非常 特别 比较 相当 稍微 十分 尤其 格外 同样
被 把 让 给 对 对于 关于 按 按照 随着 通过 根据 靠 拿 比 像 好像 似乎 如同
啊 吧 呢 吗 哦 呀 嘛 哇 嗯 唉 哎 呵 哈 咦 噢
已经 曾经 正在 将要 现在 今天 明天 昨天 当时 本来 原来 后来 之后 之前 以后 以前 如今 目前 当前 时候 时间
可以 可能 应该 必须 需要 能够 想 想要 想着 觉得 感觉 认为 以为 希望 期盼 期待 知道 明白 清楚 记得
什么 怎么 怎样 这么 那么 如何 为什么 哪里 哪儿 哪个 哪些 谁 多少 几个 多久 干嘛
事情 地方 东西 问题 情况 方面 关系 结果 原因 样子 方式 方法 办法 意思 想法 意见 内容 部分 全部 整个
对手 回来 出去 进来 上来 下来 起来 过来 开始 结束 继续 保持 具备 拥有 存在 出现 发生 变成 成为 进行 采取
水平 能力 发挥 含金量 实力 心情 感受 态度 状态 期望 期待值 作用 影响 意义 价值 想法 感受
开心 高兴 难过 生气 郁闷 无奈 可惜 遗憾 失望 喜欢 讨厌 不错 亮眼 太强 挺好 很好 好看 强吗
终于 自信 差点 开张 找回 对面 一次 一场 这队 不吃 好的 加油 一场 这场 那场 上半场 下半场
一个 两个 三个 四个 几个 第一 第二 第三 一遍 一半 一边 一样 一支 两支 三支 几支 这种 这些
不是 不会 不能 不要 没有 没人 没错 不行 不好 不了 不止 不错 不如
真的 真是 容易 一致 一向 一旦 一点 一定 一样
年轻 年老 小孩 孩子 小伙 大哥 兄弟 朋友 人们 网友 球迷们
似乎 仿佛 简直 干脆 索性 偏偏 恰好 正好 刚好 恐怕 兴许 或许 难免 免得 省得
三支 两支 一支 这几 那几 上下 左右 前后 内外 中间 旁边 周围 附近 之一 之间 之中 之内 之外
对外 对内 正义 一块 一起 直接 基本 肯定 自然 必然 其实 上面 下面 里面 外面 前面 后面
""".split())

# 足球相关词保护集：即使与停用词冲突也一律保留，避免误删专业词
FOOTBALL_TERMS = set("""
足球 比赛 联赛 杯赛 欧冠 欧联 亚冠 世界杯 欧洲杯 世预赛 预选赛 淘汰赛 小组赛 决赛 半决赛 附加赛
英超 西甲 意甲 德甲 法甲 中超 中甲 荷甲 葡超 苏超 土超 俄超 法乙 英冠 美职联 日职 韩K联 沙特联
球队 球员 球星 新援 老将 小将 青训 梯队 首发 替补 阵容 阵型 主帅 主教练 教练 领队 队长 门将 守门员
后卫 中卫 中后卫 边后卫 边卫 中场 后腰 前腰 边前卫 前锋 中锋 边锋 影锋 攻击手 核心
进球 破门 得分 射门 射正 打门 头球 任意球 点球 角球 定位球 越位 犯规 黄牌 红牌 手球 乌龙
助攻 传球 直塞 长传 传中 解围 抢断 拦截 封堵 扑救 扑出 门线 单刀 反击 快攻 控球 控场 组织 串联
防守 进攻 攻防 后防 防线 前场 中场 后场 禁区 边路 中路 肋部 二点 补位 跑位 站位 拼抢 逼抢 压迫
半场 全场 上下半场 补时 加时 点球大战 净胜球 积分 排名 榜首 垫底 保级 争冠 夺冠 冠军 亚军 季军
升班马 升班 降级 转会 引援 租借 合同 身价 年薪 解约 免签 续约
战术 打法 阵型 三中卫 四后卫 五后卫 高位 摆大巴 传控 防反 快反 边中结合 推进 起球
大胜 惨败 逆转 绝杀 绝平 扳平 反超 领先 落后 平局 完胜 零封 横扫 血洗 险胜 惜败
状态 手感 体能 伤病 伤退 复出 轮换 磨合 化学反应 天赋 潜力 新星 妖人
锋线 中场线 后防 门线 前腰 后腰 边锋 中锋 边卫 中场
""".split())

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


# App tab feed：扫描 1-200 实测「有内容」的栏目（label 作为该文所属联赛/栏目标签）。
# 已排除非新闻栏目：66 主贴跳转 / 68 装备 / 101 关注 / 119 海报。
# 全部合并去重后约 285 条新闻，搜索与标签筛选都基于这个语料。
APP_FEED_TABS = [1, 3, 4, 5, 6, 11, 12, 13, 37, 43, 55, 56, 57, 58, 59,
                 71, 99, 100, 103, 107, 109, 110, 113, 114, 120, 172, 176]

FEED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


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


def _fetch_tab(tab):
    """抓取单个 tab（供线程池调用）。返回 (label, articles)，失败返回 (None, [])。"""
    try:
        data = _http_get_json(
            f"https://api.dongqiudi.com/app/tabs/iphone/{tab}.json?version=177",
            FEED_HEADERS,
        )
    except Exception:  # noqa: BLE001
        return None, []
    return (data or {}).get("label") or "", parse_feed(data)


def fetch_comment_count(article_id):
    """从 www 文章页解析评论总数（commentTotal）。

    走 www.dongqiudi.com，不依赖可能被部署环境拦截的 api 域名，因此更可靠。
    """
    try:
        h = dict(FEED_HEADERS)
        h["Accept"] = "text/html,application/xhtml+xml,*/*;q=0.8"
        html = _http_get_text(f"https://www.dongqiudi.com/articles/{article_id}.html", h)
        m = re.search(r"commentTotal[:=\"\s]+(\d+)", html)
        return int(m.group(1)) if m else None
    except Exception:  # noqa: BLE001
        return None


def parse_related_news(html):
    """从文章页 HTML 里抽取「相关推荐」relatedNews（含较早的文章）。"""
    i = html.find("relatedNews:[")
    if i < 0:
        return []
    j = html.find("]", i)
    if j < 0:
        return []
    seg = html[i:j + 1]
    out = []
    pat = re.compile(r'\{id:"(\d+)",title:"(.*?)",time:"(.*?)",thumb:"(.*?)"\}', re.S)
    for m in pat.finditer(seg):
        aid, title, tstr, thumb = m.groups()
        cover = thumb.replace("\\u002F", "/").replace("\\/", "/") if thumb else None
        if not cover or not str(cover).startswith("http"):
            cover = None
        out.append({"id": aid, "title": title.strip(), "cover": cover, "time": tstr,
                    "tag": "", "league": "", "raw_time": tstr, "comments": None})
    return out


def extend_pool_with_related(article_id):
    """打开一篇文章时，把它页内的「相关推荐」并入新闻池 —— 渐进扩大可搜索范围。"""
    try:
        h = dict(FEED_HEADERS)
        h["Accept"] = "text/html,application/xhtml+xml,*/*;q=0.8"
        html = _http_get_text(f"https://www.dongqiudi.com/articles/{article_id}.html", h)
    except Exception:  # noqa: BLE001
        return 0
    related = parse_related_news(html)
    news, is_demo = st.session_state.news
    seen = {a["id"] for a in news}
    added = 0
    for a in related:
        if a["id"] in seen:
            continue
        seen.add(a["id"])
        news.append(a)
        added += 1
    st.session_state.news = (news, is_demo)
    st.session_state.related_added = added
    return added


def enrich_comment_counts(items):
    """给「评论数未知」的新闻补评论数（并发 + 会话内缓存，通常只补当前页）。"""
    if "cnt_cache" not in st.session_state:
        st.session_state.cnt_cache = {}
    cache = st.session_state.cnt_cache
    todo = [a for a in items if a.get("comments") is None and a["id"] not in cache]
    if todo:
        try:
            with ThreadPoolExecutor(max_workers=8) as ex:
                got = list(ex.map(lambda x: fetch_comment_count(x["id"]), todo))
            for a, c in zip(todo, got):
                cache[a["id"]] = c
        except Exception:  # noqa: BLE001
            pass
    for a in items:
        if a.get("comments") is None and cache.get(a["id"]) is not None:
            a["comments"] = cache[a["id"]]


def fetch_news_list(deep=False):
    """获取懂球帝实时新闻列表。

    主源：App tab feed `api.dongqiudi.com/app/tabs/iphone/{tab}.json`
      - deep=False（默认）：只抓 APP_FEED_TABS 这批评分较高的栏目 → 约 2 秒、260+ 条
      - deep=True：扫描 1-400 全部栏目 → 约 30 秒、1300+ 条（用户点「深度抓取」时才用）

      注：该接口的 prev/page/before 参数实测**不会真正翻页**（永远返回同一页），
          所以只能靠"多栏目合并"来扩量，不能靠翻页。
    兜底：官网首页 HTML（约 25 条）
    再失败 → 内置示例

    返回 (news_list, is_demo)：
      - 抓到文章 -> (真实列表, False)
      - 全部失败 -> (内置示例, True)，由调用方显示 ⚠️，绝不假装实时。
    """
    # ---- 主源：多个 tab 并发抓取后合并去重（单 tab 失败不影响其它）----
    tabs = range(1, 401) if deep else APP_FEED_TABS
    arts, seen = [], set()
    try:
        with ThreadPoolExecutor(max_workers=16 if deep else 10) as ex:
            for label, items in ex.map(_fetch_tab, tabs):
                for a in items:
                    if a["id"] in seen:
                        continue
                    seen.add(a["id"])
                    a["league"] = label or ""
                    arts.append(a)
    except Exception:  # noqa: BLE001
        pass
    if arts:
        return arts, False

    # ---- 兜底：官网首页 HTML（该页面无 league 字段）----
    h2 = dict(FEED_HEADERS)
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


# 首页锚点文本里会混入的栏目名，用于清理标题尾部
HOME_CATS = set("""
足球 中国足球 国内 国际 五洲 英超 英冠 意甲 意乙 西甲 西乙 德甲 德乙 法甲 法乙 荷甲 葡超 苏超
土超 俄超 中超 中甲 亚冠 欧冠 欧联 欧协联 世界杯 欧洲杯 世预赛 亚洲杯 美洲杯 国家队 国足
美职联 日职 韩K联 沙特联 综合 集锦 闲情 专题 深度 评论 观点 数据 视频 图片 转会 伤病 电竞
篮球 NBA CBA 网球 F1 高尔夫 排球 乒乓球 羽毛球 赛车 综合体育
""".split())


def parse_homepage(html):
    """从官网首页 HTML 中稳健抽取 /articles/{id}.html 文章卡片（含标题/封面/评论数）。

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
        txt = re.sub(r"<[^>]+>", " ", raw)
        txt = re.sub(r"\s+", " ", txt).strip()
        # 评论数：首页有两种写法 ——「· 1971 评论」和「534 评」
        cnt_m = re.search(r"(?:·\s*)?(\d+)\s*评(?:论)?", txt)
        comments = int(cnt_m.group(1)) if cnt_m else None
        # 清理标题：尾部日期 / 评论数 / 相对时间，开头的「足球」大类
        text = re.sub(r"\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}.*$", "", txt).strip()
        text = re.sub(r"(?:·\s*)?\d+\s*评(?:论)?.*$", "", text).strip()
        text = re.sub(r"(刚刚|分钟前|小时前|天前).*$", "", text).strip()
        text = re.sub(r"^足球\s*", "", text).strip()
        text = re.sub(r"^[·\-–—\s]+", "", text)
        text = re.sub(r"[·\-–—\s]+$", "", text).strip()
        # 去掉尾部残留的栏目名（如「早报：… 英超 意甲」）
        parts = text.split()
        while len(parts) > 1 and parts[-1] in HOME_CATS:
            parts.pop()
        text = " ".join(parts).strip()
        if len(text) < 4:
            text = f"懂球帝文章 #{aid}"
        # 往前 2000 字符找封面图
        back = html[max(0, m.start() - 2000):m.start()]
        cm = re.search(r'<img\b[^>]*?src=["\']([^"\']+\.(?:jpg|jpeg|png|webp))["\']', back, re.IGNORECASE)
        cover = cm.group(1) if cm else None
        if cover and cover.startswith("//"):
            cover = "https:" + cover
        out.append({"id": aid, "title": text, "cover": cover, "time": "",
                    "tag": "", "raw_time": None, "comments": comments})
        if len(out) >= 40:
            break
    # 2) 兜底：宽松匹配任何 /articles/{id}.html
    if not out:
        for m in re.finditer(r'(?:href=["\']?|"/)(?:https?://[^\s"\']*?)?/articles/(\d+)\.html', html):
            aid = m.group(1)
            if aid in seen:
                continue
            seen.add(aid)
            out.append({"id": aid, "title": f"懂球帝文章 #{aid}", "cover": None, "time": "",
                        "tag": "", "raw_time": None, "comments": None})
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
    """中文分词统计词频（词云数据源）。

    过滤策略：只要不是「足球相关词」，命中通用停用词表（这种/一样/对手/希望/时候…）
    就丢弃，让词云留下球队、球员、位置、战术、赛事等有信息量的词。
    """
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
        if not w or "[" in w or "]" in w:  # 空 / 含括号的一律跳过
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]", w):  # 单字跳过
            continue
        if w not in FOOTBALL_TERMS and w in STOPWORDS:  # 足球词保护，其余通用词过滤
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


# ========================= 功能二：数据分析（ECharts） =======================
# 用 st.components.v1.html + CDN（三源回退）渲染 ECharts，无需额外 Python 依赖。
_ECHARTS_TPL = """
<div id="ec" style="width:100%;height:__HEIGHT__px"></div>
<script src="https://cdn.staticfile.org/echarts/5.5.0/echarts.min.js"></script>
<script>window.echarts||document.write('<script src="https://cdn.bootcdn.net/ajax/libs/echarts/5.5.0/echarts.min.js"><\\/script>');</script>
<script>window.echarts||document.write('<script src="https://unpkg.com/echarts@5.5.0/dist/echarts.min.js"><\\/script>');</script>
<script>
(function(){
  var el=document.getElementById('ec');
  if(!window.echarts){el.innerHTML='<div style="padding:24px;color:#8a9099;font-size:13px">'
    +'图表库加载失败：需要联网加载 ECharts（已依次尝试 staticfile / bootcdn / unpkg）。</div>';return;}
  var c=echarts.init(el);
  c.setOption(__OPTION__);
  window.addEventListener('resize',function(){c.resize();});
})();
</script>
"""

_RED = "#d51d2a"
_RED2 = "#ff5a3c"
_GREY = "#9ca3af"
_GRID = {"lineStyle": {"color": "#eef0f3"}}

LEAGUE_GROUPS = {
    "欧洲五大联赛 / 欧战": ["英超", "西甲", "意甲", "德甲", "法甲", "欧冠", "欧联", "欧协联"],
    "国际大赛 / 国家队": ["世界杯", "亚洲杯", "U17世界杯", "U20女足世界杯"],
    "中国联赛 / 杯赛": ["中超", "中甲", "中乙", "足协杯", "亚冠精英", "亚冠二级"],
    "其他联赛": ["沙特联", "美职联", "苏超(江苏)"],
}

# 球员评分·能力榜：汇总场次选项（None = 整个赛季，取该赛季全部已结束比赛）
_RT_OPTS = {
    "近 3 场": 3, "近 5 场": 5, "近 8 场": 8, "近 10 场": 10,
    "近 15 场": 15, "近 20 场": 20, "近 30 场": 30,
    "整个赛季（全部已结束场次）": None,
}


def echarts(option, height=380):
    """渲染一个 ECharts 图表。

    用 st.iframe 承载（它会自动识别 HTML 字符串并允许执行 JS）。
    注：旧的 st.components.v1.html 已标记「2026-06-01 后移除」，故不再使用。
    """
    opt = json.dumps(option, ensure_ascii=False)
    html = _ECHARTS_TPL.replace("__HEIGHT__", str(height)).replace("__OPTION__", opt)
    st.iframe(html, height=height + 14)


def _cached(key, fn, *args):
    """会话内缓存，避免同一份数据反复请求。点「重新拉取数据」可清空。"""
    if "data_cache" not in st.session_state:
        st.session_state.data_cache = {}
    cache = st.session_state.data_cache
    if key not in cache:
        cache[key] = fn(*args)
    return cache[key]


def _team_pack(team_id, season=None, form_limit=6):
    """赛果预测用：某队「最近一场首发的能力值」+「近期状态」。"""
    sched = [m for m in DD.fetch_team_schedule(team_id, season=season)
             if m.get("status") == "Played" and m.get("match_id")]
    ability, side_name = {}, ""
    if sched:
        last = sched[-1]
        ids = set(DD.sport_team_id_variants(team_id))
        ids.update(str(x) for x in (last.get("my_ids") or []) if x)
        ids.discard("")
        try:
            lu = DD.fetch_match_lineup(last["match_id"])
            side = next((lu.get(k) for k in ("A", "B")
                         if lu.get(k) and str(lu[k].get("team_id")) in ids), None)
            if side:
                ability = DD.fetch_team_ability(side["starters"], side["name"])
                side_name = side["name"] or ""
        except Exception:  # noqa: BLE001
            pass
    form = DD.fetch_team_form(team_id, limit=form_limit, season=season)
    return {"ability": ability, "form": form, "name": side_name,
            "last_match": sched[-1] if sched else None}


def _season_picker(team_id, key, label="赛季"):
    """历史赛季下拉（默认当前赛季）。返回 (season 值, 展示名)。"""
    try:
        seasons = _cached(f"seasons_{team_id}", DD.fetch_team_seasons, team_id)
    except Exception:  # noqa: BLE001
        seasons = []
    if not seasons:
        return None, ""
    opts = [s["name"] for s in seasons]
    idx = next((i for i, s in enumerate(seasons) if s["current"]), 0)
    pick = st.selectbox(label, opts, index=idx, key=key,
                        help="可选历史赛季（数据来自懂球帝赛程接口）")
    return next((s["season"] for s in seasons if s["name"] == pick), None), pick


def chart_points(rows, top=12):
    d = rows[:top]
    return {
        "grid": {"left": 46, "right": 18, "top": 28, "bottom": 76},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": [r["球队"] for r in d],
                  "axisLabel": {"rotate": 40, "fontSize": 11, "color": "#6b7280"}},
        "yAxis": {"type": "value", "splitLine": _GRID,
                  "axisLabel": {"color": "#6b7280"}},
        "series": [{"type": "bar", "name": "积分", "data": [r["积分"] for r in d],
                    "itemStyle": {"color": _RED, "borderRadius": [4, 4, 0, 0]},
                    "label": {"show": True, "position": "top", "fontSize": 10,
                              "color": "#6b7280"}}],
    }


def chart_goals(rows, top=10):
    d = rows[:top]
    return {
        "legend": {"top": 0, "textStyle": {"fontSize": 12}},
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 46, "right": 18, "top": 40, "bottom": 76},
        "xAxis": {"type": "category", "data": [r["球队"] for r in d],
                  "axisLabel": {"rotate": 40, "fontSize": 11, "color": "#6b7280"}},
        "yAxis": {"type": "value", "splitLine": _GRID},
        "series": [
            {"name": "进球", "type": "bar", "data": [r["进球"] for r in d],
             "itemStyle": {"color": _RED, "borderRadius": [3, 3, 0, 0]}},
            {"name": "失球", "type": "bar", "data": [r["失球"] for r in d],
             "itemStyle": {"color": _GREY, "borderRadius": [3, 3, 0, 0]}},
        ],
    }


def chart_scorers(rows, top=15):
    d = list(reversed(rows[:top]))
    return {
        "grid": {"left": 100, "right": 36, "top": 16, "bottom": 24},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "value", "splitLine": _GRID},
        "yAxis": {"type": "category", "data": [r["球员"] for r in d],
                  "axisLabel": {"fontSize": 11, "color": "#15181d"}},
        "series": [{"type": "bar", "name": "进球", "data": [r["进球"] for r in d],
                    "itemStyle": {"color": _RED2, "borderRadius": [0, 4, 4, 0]},
                    "label": {"show": True, "position": "right", "fontSize": 10,
                              "color": "#6b7280"}}],
    }


def chart_pie(pairs, top=8):
    items = sorted(pairs, key=lambda x: -x[1])
    d = items[:top]
    rest = sum(c for _, c in items[top:])
    if rest > 0:
        d = d + [("其他", rest)]
    return {
        "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
        "legend": {"bottom": 0, "type": "scroll", "textStyle": {"fontSize": 11}},
        "series": [{"type": "pie", "radius": ["40%", "66%"], "center": ["50%", "43%"],
                    "data": [{"name": k, "value": v} for k, v in d],
                    "label": {"fontSize": 11},
                    "itemStyle": {"borderColor": "#fff", "borderWidth": 2}}],
    }


def chart_compare(rows, teams):
    d = sorted([r for r in rows if r["球队"] in teams], key=lambda r: -r["积分"])
    return {
        "legend": {"top": 0, "textStyle": {"fontSize": 12}},
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 46, "right": 18, "top": 40, "bottom": 56},
        "xAxis": {"type": "category", "data": [r["球队"] for r in d],
                  "axisLabel": {"rotate": 30, "fontSize": 11}},
        "yAxis": {"type": "value", "splitLine": _GRID},
        "series": [
            {"name": "积分", "type": "bar", "data": [r["积分"] for r in d],
             "itemStyle": {"color": _RED, "borderRadius": [3, 3, 0, 0]}},
            {"name": "进球", "type": "bar", "data": [r["进球"] for r in d],
             "itemStyle": {"color": _RED2, "borderRadius": [3, 3, 0, 0]}},
            {"name": "失球", "type": "bar", "data": [r["失球"] for r in d],
             "itemStyle": {"color": _GREY, "borderRadius": [3, 3, 0, 0]}},
        ],
    }


def chart_player_seasons(seasons, top=10):
    d = list(reversed(seasons[:top]))

    def n(k):
        return [DD._int(s.get(k)) for s in d]

    return {
        "legend": {"top": 0, "textStyle": {"fontSize": 12}},
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 46, "right": 18, "top": 40, "bottom": 62},
        "xAxis": {"type": "category", "data": [s.get("赛季", "") for s in d],
                  "axisLabel": {"rotate": 35, "fontSize": 10, "color": "#6b7280"}},
        "yAxis": {"type": "value", "splitLine": _GRID},
        "series": [
            {"name": "上场", "type": "bar", "data": n("上场"),
             "itemStyle": {"color": "#e6ebf2", "borderRadius": [3, 3, 0, 0]}},
            {"name": "进球", "type": "line", "smooth": True, "data": n("进球"),
             "itemStyle": {"color": _RED}, "lineStyle": {"width": 3}},
            {"name": "助攻", "type": "line", "smooth": True, "data": n("助攻"),
             "itemStyle": {"color": _RED2}, "lineStyle": {"width": 2}},
        ],
    }


def chart_player_rating(players, top=15):
    """球员场均评分（横向柱）。"""
    d = list(reversed(players[:top]))
    return {
        "grid": {"left": 96, "right": 44, "top": 16, "bottom": 24},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "value", "min": 5, "max": 10, "splitLine": _GRID},
        "yAxis": {"type": "category", "data": [p["name"] for p in d],
                  "axisLabel": {"fontSize": 11, "color": "#15181d"}},
        "series": [{"type": "bar", "name": "场均评分", "data": [p["avg_rate"] for p in d],
                    "itemStyle": {"color": _RED, "borderRadius": [0, 4, 4, 0]},
                    "label": {"show": True, "position": "right", "fontSize": 10,
                              "color": "#6b7280"}}],
    }


def chart_lineup_compare(A, B):
    """两队首发 11 人评分对比。"""
    a, b = A.get("starters") or [], B.get("starters") or []
    n = max(len(a), len(b))
    return {
        "legend": {"top": 0, "textStyle": {"fontSize": 12}},
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 46, "right": 18, "top": 46, "bottom": 40},
        "xAxis": {"type": "category", "data": [f"第{i + 1}人" for i in range(n)],
                  "axisLabel": {"fontSize": 11, "color": "#6b7280"}},
        "yAxis": {"type": "value", "min": 4, "max": 10, "splitLine": _GRID},
        "series": [
            {"name": f"{A.get('name')}（首发均分 {A.get('avg_rate')}）", "type": "bar",
             "data": [p.get("rate") for p in a],
             "itemStyle": {"color": _RED, "borderRadius": [3, 3, 0, 0]}},
            {"name": f"{B.get('name')}（首发均分 {B.get('avg_rate')}）", "type": "bar",
             "data": [p.get("rate") for p in b],
             "itemStyle": {"color": "#4b7bec", "borderRadius": [3, 3, 0, 0]}},
        ],
    }


def chart_rating_trend(matches, team_name=""):
    """球队首发均分走势（场次多时改用「日期 + 对手」短标签并自动抽稀）。"""
    d = list(reversed(matches))
    n = len(d)
    dense = n > 22

    def _short(m):
        date = (m.get("start_play") or "")[5:10]
        lab = re.sub(r"（[^）]*）\s*$", "", m.get("label") or "").strip()
        opp = ""
        if team_name and team_name in lab:
            rest = lab.replace(team_name, " ").strip()
            rest = re.sub(r"\d+\s*[-:]\s*\d+", " ", rest)
            opp = rest.strip()[:5]
        return f"{date}\n{opp}" if opp else date

    return {
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 46, "right": 18, "top": 26,
                 "bottom": 60 if dense else 78},
        "xAxis": {"type": "category",
                  "data": [_short(m) if dense else m["label"] for m in d],
                  "axisLabel": {"rotate": 0 if dense else 32,
                                "lineHeight": 11,
                                "fontSize": 9 if dense else 10,
                                "interval": max(1, n // 14) if dense else 0,
                                "color": "#6b7280"}},
        "yAxis": {"type": "value", "min": 5, "max": 10, "splitLine": _GRID},
        "series": [{"type": "line", "name": "首发均分", "smooth": True,
                    "data": [m["avg_rate"] for m in d],
                    "itemStyle": {"color": _RED},
                    "lineStyle": {"width": 2 if dense else 3},
                    "symbolSize": 3 if dense else 6,
                    "label": {"show": not dense, "fontSize": 10, "color": "#6b7280"}}],
    }


# ---------------- 能力值（传球 / 身体 / 射门…）相关图表 ----------------
_AB_COLORS = [_RED, _RED2, "#f2a33c", "#4b7bec", "#8e7cf0", "#2fb886", "#8a94a6"]
_BLUE = "#4b7bec"


def chart_radar(dims, series, maxv=100, height_hint=0):
    """雷达图。dims: 维度名列表；series: [{"name": str, "data": [数值...]}]。"""
    return {
        "color": [_RED, _BLUE, "#f2a33c"],
        "tooltip": {},
        "legend": {"top": 0, "textStyle": {"fontSize": 12}} if len(series) > 1 else {"show": False},
        "radar": {
            "indicator": [{"name": n, "max": maxv} for n in dims],
            "radius": "62%", "center": ["50%", "56%"],
            "axisName": {"color": "#6b7280", "fontSize": 11},
            "splitArea": {"areaStyle": {"color": ["#ffffff", "#fafbfc"]}},
            "splitLine": {"lineStyle": {"color": "#e9ebef"}},
            "axisLine": {"lineStyle": {"color": "#e9ebef"}},
        },
        "series": [{
            "type": "radar",
            "data": [{"name": s.get("name"), "value": s.get("data"),
                      "areaStyle": {"opacity": 0.18},
                      "lineStyle": {"width": 2}, "symbolSize": 5} for s in series],
        }],
    }


def chart_ability_groups(groups):
    """能力值分组明细（按「进攻/技巧/移动/力量/心理/防守…」着色，长条横排）。"""
    cats = [it["指标"] for g in groups for it in g["指标"]]
    series = []
    for i, g in enumerate(groups):
        n = len(g["指标"])
        start = sum(len(x["指标"]) for x in groups[:i])
        data = [None] * len(cats)
        for k, it in enumerate(g["指标"]):
            data[start + k] = it["数值"]
        series.append({"name": g["组"], "type": "bar", "data": data,
                       "itemStyle": {"color": _AB_COLORS[i % len(_AB_COLORS)],
                                     "borderRadius": [0, 4, 4, 0]},
                       "label": {"show": True, "position": "right", "fontSize": 10,
                                 "color": "#6b7280"}})
    return {
        "color": _AB_COLORS,
        "legend": {"top": 0, "textStyle": {"fontSize": 11}},
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 78, "right": 44, "top": 40, "bottom": 18},
        "xAxis": {"type": "value", "max": 100, "splitLine": _GRID,
                  "axisLabel": {"fontSize": 10, "color": "#9ca3af"}},
        "yAxis": {"type": "category", "data": list(reversed(cats)),
                  "axisLabel": {"fontSize": 10.5, "color": "#15181d"}},
        "series": [{**s, "data": list(reversed(s["data"]))} for s in series],
    }


def chart_ability_compare(A, B):
    """两队首发 11 人「能力值」对比（A/B 为 fetch_team_ability 结果）。"""
    a = A.get("players") or []
    b = B.get("players") or []

    def short(q, n=4):
        s = (q or {}).get("name") or ""
        return s if len(s) <= n else s[:n]

    n = max(len(a), len(b))
    return {
        "legend": {"top": 0, "textStyle": {"fontSize": 12}},
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 46, "right": 18, "top": 46, "bottom": 56},
        "xAxis": {"type": "category",
                  "data": [f"{(a[i] if i < len(a) else {}).get('position', '')}\n"
                           f"{short(a[i] if i < len(a) else {})}\n"
                           f"{short(b[i] if i < len(b) else {})}"
                           for i in range(n)],
                  "axisLabel": {"fontSize": 8.5, "lineHeight": 11,
                                "color": "#6b7280", "interval": 0, "rotate": 0}},
        "yAxis": {"type": "value", "max": 100, "splitLine": _GRID},
        "series": [
            {"name": f"{A.get('name')}（首发能力 {A.get('team_avg')}）", "type": "bar",
             "data": [q.get("avg") for q in a],
             "itemStyle": {"color": _RED, "borderRadius": [3, 3, 0, 0]}},
            {"name": f"{B.get('name')}（首发能力 {B.get('team_avg')}）", "type": "bar",
             "data": [q.get("avg") for q in b],
             "itemStyle": {"color": _BLUE, "borderRadius": [3, 3, 0, 0]}},
        ],
    }


def chart_ability_rank(items, top=15):
    """球员能力值（总评）横向柱。items: [{"name","avg"}]（内部按能力降序取前 top）。"""
    rows = sorted([x for x in items if x.get("avg")], key=lambda x: -x["avg"])[:top]
    d = list(reversed(rows))
    return {
        "grid": {"left": 92, "right": 46, "top": 16, "bottom": 24},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "value", "min": 50, "max": 100, "splitLine": _GRID},
        "yAxis": {"type": "category", "data": [p["name"] for p in d],
                  "axisLabel": {"fontSize": 11, "color": "#15181d"}},
        "series": [{"type": "bar", "name": "能力值", "data": [p["avg"] for p in d],
                    "itemStyle": {"color": _RED2, "borderRadius": [0, 4, 4, 0]},
                    "label": {"show": True, "position": "right", "fontSize": 10,
                              "color": "#6b7280"}}],
    }


def chart_indicators_compare(ia, ib=None, name_a="", name_b="", group_color=True):
    """各指标平均分对比（横向柱，按「进攻/技巧/移动…」分组着色或双色对比）。

    ia / ib: [{"组","指标","数值"}]（来自 fetch_team_ability 的 indicators_avg）。
    """
    ib = ib or []
    base = ia or ib
    if not base:
        return {"series": []}
    cats, order, groups = [], [], []
    for it in base:
        order.append(it["指标"])
        cats.append(f"{it['指标']}")
        groups.append(it.get("组") or "")
    ma = {it["指标"]: it["数值"] for it in ia}
    mb = {it["指标"]: it["数值"] for it in ib}

    def _rev(seq):
        return list(reversed(seq))

    if ia and ib:
        series = [
            {"name": name_a or "主队", "type": "bar", "data": _rev([ma.get(k) for k in order]),
             "itemStyle": {"color": _RED, "borderRadius": [0, 3, 3, 0]}},
            {"name": name_b or "客队", "type": "bar", "data": _rev([mb.get(k) for k in order]),
             "itemStyle": {"color": _BLUE, "borderRadius": [0, 3, 3, 0]}},
        ]
        color = [_RED, _BLUE]
    else:
        src = ma if ia else mb
        series = [{"type": "bar", "name": "指标平均分",
                   "data": _rev([src.get(k) for k in order]),
                   "itemStyle": {"color": _RED2, "borderRadius": [0, 3, 3, 0]},
                   "label": {"show": True, "position": "right", "fontSize": 9.5,
                             "color": "#6b7280"}}]
        color = [_RED2]
    n = len(order)
    return {
        "color": color,
        "legend": ({"top": 0, "textStyle": {"fontSize": 12}} if (ia and ib)
                   else {"show": False}),
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 84, "right": 52, "top": 40 if (ia and ib) else 16,
                 "bottom": 18},
        "xAxis": {"type": "value", "max": 100, "splitLine": _GRID,
                  "axisLabel": {"fontSize": 10, "color": "#9ca3af"}},
        "yAxis": {"type": "category", "data": _rev(cats),
                  "axisLabel": {"fontSize": 10, "color": "#15181d"}},
        "series": series,
    }


def chart_win_prob(pred, home_name, away_name):
    """胜平负概率（100% 堆叠横条）。"""
    seg = [(f"{home_name} 胜", pred.get("p_home"), _RED),
           ("平局", pred.get("p_draw"), "#f2a33c"),
           (f"{away_name} 胜", pred.get("p_away"), _BLUE)]
    return {
        "tooltip": {"trigger": "axis"},
        "legend": {"top": 0, "textStyle": {"fontSize": 12}},
        "grid": {"left": 12, "right": 12, "top": 44, "bottom": 22},
        "xAxis": {"type": "value", "max": 100, "show": False},
        "yAxis": {"type": "category", "data": [""], "show": False},
        "series": [{
            "name": nm, "type": "bar", "stack": "p", "data": [v],
            "itemStyle": {"color": c},
            "label": {"show": True, "position": "inside", "color": "#fff",
                      "fontSize": 12, "fontWeight": "bold", "formatter": "{c}%"},
        } for nm, v, c in seg],
    }


def chart_score_matrix(pred, home_name, away_name, nmax=5):
    """比分概率热力图（0~nmax 球）。"""
    n = nmax + 1
    grid = pred.get("grid") or []
    data = []
    for i in range(n):
        for j in range(n):
            v = grid[i][j] if (i < len(grid) and j < len(grid[i])) else 0
            data.append([i, j, round(v, 1)])
    hi = max((d[2] for d in data), default=1) or 1
    return {
        "tooltip": {"trigger": "item"},
        "grid": {"left": 58, "right": 20, "top": 18, "bottom": 66},
        "xAxis": {"type": "category", "data": [str(i) for i in range(n)],
                  "name": f"{home_name} 进球", "nameLocation": "middle",
                  "nameGap": 28, "nameTextStyle": {"fontSize": 11, "color": "#6b7280"},
                  "splitArea": {"show": True}},
        "yAxis": {"type": "category", "data": [str(j) for j in range(n)],
                  "name": f"{away_name} 进球", "nameLocation": "middle",
                  "nameGap": 38, "nameTextStyle": {"fontSize": 11, "color": "#6b7280"},
                  "splitArea": {"show": True}},
        "visualMap": {"min": 0, "max": round(hi, 1), "calculable": True,
                      "orient": "horizontal", "left": "center", "bottom": 4,
                      "itemWidth": 12, "itemHeight": 90,
                      "textStyle": {"fontSize": 10, "color": "#6b7280"},
                      "inRange": {"color": ["#fff7f7", "#fbd5d5", "#ef8a8a",
                                            "#d51d2a", "#7d0c16"]}},
        "series": [{"type": "heatmap", "data": data,
                    "label": {"show": True, "fontSize": 9, "color": "#15181d",
                              "formatter": "{c}%"},
                    "emphasis": {"itemStyle": {"shadowBlur": 8,
                                               "shadowColor": "rgba(0,0,0,.28)"}}}],
    }


def chart_ability_vs_rate(sides):
    """能力值 vs 本场评分 散点（sides: [{"name","players"}]）。

    落在右上=能力强且发挥好；左上=能力强但没发挥；右下=发挥超水平。
    """
    series = []
    for i, sd in enumerate(sides):
        pts = [[q.get("avg"), q.get("rate"), q.get("name")]
               for q in (sd.get("players") or []) if q.get("avg") and q.get("rate")]
        series.append({
            "name": sd.get("name"), "type": "scatter",
            "data": [{"value": [p[0], p[1]], "name": p[2]} for p in pts],
            "symbolSize": 11,
            "itemStyle": {"color": _RED if i == 0 else _BLUE, "opacity": .85},
            "label": {"show": True, "position": "top", "fontSize": 9,
                      "color": "#6b7280", "formatter": "{b}"},
            "labelLayout": {"hideOverlap": True},
        })
    return {
        "color": [_RED, _BLUE],
        "legend": {"top": 0, "textStyle": {"fontSize": 12}},
        "tooltip": {"trigger": "item",
                    "formatter": "{b}：能力 {c0} ／ 本场评分 {c1}"},
        "grid": {"left": 52, "right": 26, "top": 44, "bottom": 46},
        "xAxis": {"type": "value", "name": "能力值", "min": 60, "max": 95,
                  "nameTextStyle": {"fontSize": 11, "color": "#9ca3af"},
                  "splitLine": _GRID, "axisLabel": {"fontSize": 10, "color": "#9ca3af"}},
        "yAxis": {"type": "value", "name": "本场评分", "min": 5, "max": 10,
                  "nameTextStyle": {"fontSize": 11, "color": "#9ca3af"},
                  "splitLine": _GRID, "axisLabel": {"fontSize": 10, "color": "#9ca3af"}},
        "series": [s for s in series if s["data"]],
    }


# ------------------------- UI（仅在 streamlit 运行时执行） -------------------
def main():
    st.set_page_config(page_title="懂球帝 · 评论爬取 + 数据分析", page_icon="⚽", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(render_hero(), unsafe_allow_html=True)

    # ---- 顶部功能切换：功能一 评论爬取 / 功能二 数据分析 ----
    mode = st.pills("功能", ["📰 评论爬取", "📊 数据分析"], selection_mode="single",
                    default="📰 评论爬取", key="app_mode", label_visibility="collapsed")
    if mode and "数据分析" in mode:
        page_data()
    else:
        page_scrape()


def page_scrape():
    """功能一：新闻评论爬取 + 词云 + 情感分析。"""
    # ---- session state ----
    for key in ("news", "selected", "sel_title", "results"):
        if key not in st.session_state:
            st.session_state[key] = (None if key in ("news", "selected") else
                                     ("" if key == "sel_title" else {}))
    if "page" not in st.session_state:
        st.session_state.page = 1
    if "last_query" not in st.session_state:
        st.session_state.last_query = ""
    if "last_tag" not in st.session_state:
        st.session_state.last_tag = None

    # 支持 ?sel=<文章ID> 直接打开某篇的分析（可分享链接）
    _qp_sel = st.query_params.get("sel")
    if _qp_sel and not st.session_state.selected:
        st.session_state.selected = str(_qp_sel)

    # ---- 首次自动拉取真实新闻 ----
    if st.session_state.news is None:
        with st.spinner("正在获取懂球帝实时新闻…"):
            st.session_state.news = fetch_news_list()

    # 打开过文章 → 把该文「相关推荐」并入新闻池（提前执行，保证下面的条数一致）
    _sel_now = st.session_state.get("selected")
    if _sel_now and st.session_state.get("related_for") != _sel_now:
        st.session_state.related_for = _sel_now
        try:
            extend_pool_with_related(_sel_now)
        except Exception:  # noqa: BLE001
            pass

    # ---- 工具栏：刷新按钮（左） + 状态提示（右） ----
    c_btn, c_deep, c_status = st.columns([1, 1.15, 3], gap="medium")
    with c_btn:
        if st.button("🔄 刷新实时新闻", width="stretch", type="primary"):
            with st.spinner("正在重新获取懂球帝实时新闻…"):
                st.session_state.news = fetch_news_list()
                st.session_state.selected = None
                st.session_state.results = {}
                st.session_state.page = 1
                st.rerun()
    with c_deep:
        if st.button("📚 深度抓取全部栏目", width="stretch",
                     help="扫描懂球帝 1-400 号全部栏目，约 30 秒，可拿到 1300+ 条新闻"):
            with st.spinner("正在深度抓取全部栏目（约 30 秒，请稍候）…"):
                st.session_state.news = fetch_news_list(deep=True)
                st.session_state.selected = None
                st.session_state.results = {}
                st.session_state.page = 1
                st.rerun()
    news, is_demo_news = st.session_state.news
    with c_status:
        if is_demo_news:
            st.warning("⚠️ 未能联网获取实时新闻，当前为内置示例新闻。", icon="⚠️")
        else:
            st.success(f"✅ 已加载 {len(news)} 条懂球帝实时新闻 —— "
                       f"可用搜索 / 标签筛选，点选卡片即可爬取评论。", icon="✅")

    # ---- 新闻区：标题 + 搜索 + 标签 + 每页条数 ----
    src_name = ("App 接口 · 多栏目合并" if any(a.get("league") for a in news)
                else ("内置示例" if is_demo_news else "官网首页"))
    st.markdown(f'<div class="dqd-section-title">📰 实时新闻 · 点选一篇爬取评论'
                f'<span class="dqd-src">数据源：{esc(src_name)}</span></div>',
                unsafe_allow_html=True)

    c_q, c_page = st.columns([3, 1], gap="medium")
    with c_q:
        q = st.text_input("搜索新闻", key="news_query", label_visibility="collapsed",
                          placeholder="🔍 搜索全部新闻标题（如：曼城 / 皇马 / 国足）")
    with c_page:
        per_page = st.selectbox("每页条数", [9, 12, 18, 24], index=1,
                                key="per_page", label_visibility="collapsed")

    # ---- 快捷标签：点一下只看相关新闻（再点一次取消）----
    st.markdown('<div class="dqd-taglabel">⚡ 快捷标签 · 点一下只看相关新闻</div>',
                unsafe_allow_html=True)
    tag = st.pills("标签", NEWS_TAGS, selection_mode="single", key="tag_pick",
                   label_visibility="collapsed")

    # ---- 搜索范围说明 + 按链接/ID 直接打开（查任意历史文章）----
    st.caption(f"🔎 搜索与标签只覆盖「当前已加载的 {len(news)} 条新闻」——"
               f"懂球帝未开放按关键词检索历史的接口（网页搜索页 403、App 搜索接口需签名）。"
               f"想查更早的文章，可用下面的方式直接打开。")
    with st.expander("🔗 按链接 / 文章 ID 直接打开（可打开任意历史文章）"):
        raw_in = st.text_input(
            "粘贴懂球帝文章链接或 ID", key="direct_input",
            placeholder="例如 6361288，或 https://www.dongqiudi.com/articles/6361288.html")
        cgo, ctip = st.columns([1, 3], gap="medium")
        with cgo:
            go = st.button("打开并抓取评论", key="direct_go", width="stretch")
        with ctip:
            st.caption("文章 ID 就在链接里：/articles/**6361288**.html")
        if go and (raw_in or "").strip():
            _ids = dqd.extract_ids_from_args([raw_in.strip()])
            if _ids:
                st.session_state.selected = _ids[0]
                st.session_state.sel_title = f"文章 #{_ids[0]}"
                st.rerun()
            else:
                st.warning("没识别出文章 ID，请检查输入。")

    # 关键词 / 标签变化 → 回到第 1 页
    if (st.session_state.last_query != q) or (st.session_state.get("last_tag") != tag):
        st.session_state.last_query = q
        st.session_state.last_tag = tag
        st.session_state.page = 1

    qn = (q or "").strip().lower()
    tn = (tag or "").strip().lower()

    def _hit(a):
        if tn:  # 标签优先级最高：先按栏目/联赛匹配，再按标题匹配
            return (tn in str(a.get("league") or "").lower()) or (tn in a["title"].lower())
        if qn:  # 搜索覆盖「全部已加载新闻」
            return (qn in a["title"].lower()
                    or qn in str(a.get("tag") or "").lower()
                    or qn in str(a.get("league") or "").lower())
        return True

    filtered = [a for a in news if _hit(a)]
    total_pages = max(1, (len(filtered) + per_page - 1) // per_page)
    page = min(max(1, int(st.session_state.page)), total_pages)
    st.session_state.page = page
    page_items = filtered[(page - 1) * per_page: page * per_page]
    enrich_comment_counts(page_items)  # 缺评论数的卡片并发补齐（会话内缓存）

    # ---- 新闻网格（3 列卡片，按当前页渲染）----
    if not filtered:
        cond = f'标签「{esc(tag)}」' if tn else f'关键词「{esc(q)}」'
        st.markdown(f'<div class="dqd-hint">已加载的 {len(news)} 条新闻里没有匹配 {cond} 的内容。'
                    f'可以：① 换个条件；② 点「🔄 刷新实时新闻」拉最新；'
                    f'③ 点「📚 深度抓取全部栏目」把语料扩到 1300+ 条再搜。</div>',
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
                    # 分类优先显示栏目/联赛（App 源的 category 一律是「足球」，信息量低）
                    meta = " · ".join([x for x in
                                       [art.get("league") or art.get("tag"), art.get("time")] if x])
                    cnt = art.get("comments")
                    badge = (f'<span class="dqd-cnt">💬 {cnt:,} 条评论</span>'
                             if cnt is not None else
                             '<span class="dqd-cnt none">💬 —</span>')
                    st.markdown(
                        f'<div class="dqd-metarow">'
                        f'<span class="dqd-meta">{esc(meta or "懂球帝")}</span>{badge}</div>',
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
            if tn:
                info += f"　·　标签「{esc(tag)}」"
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

    if st.session_state.get("related_added"):
        st.caption(f"🔗 已从该文「相关推荐」补充 "
                   f"{st.session_state.related_added} 条新闻到搜索池。")

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


def page_data():
    """功能二：联赛 / 球队 / 球员 全方位数据分析（ECharts）。"""
    st.markdown('<div class="dqd-section-title">📊 数据分析 · 联赛 / 球队 / 球员</div>',
                unsafe_allow_html=True)

    c1, c2, c3 = st.columns([1.2, 1.2, 1.6], gap="medium")
    with c1:
        grp = st.selectbox("分组", list(LEAGUE_GROUPS.keys()), key="dt_group")
    with c2:
        league = st.selectbox("联赛", LEAGUE_GROUPS[grp], key="dt_league")
    with c3:
        st.caption("数据来自懂球帝公开数据页；同一联赛首次加载约 1 秒，之后走缓存。")
        if st.button("🔄 重新拉取数据", key="dt_reload", width="stretch"):
            st.session_state.data_cache = {}
            st.rerun()

    cid = DD.ALL_LEAGUES.get(league)
    if not cid:
        st.warning("该联赛暂无数据。")
        return
    try:
        with st.spinner(f"正在加载「{league}」数据…"):
            st_rows = _cached(f"st_{cid}", DD.fetch_standings, cid)
            sc_rows = _cached(f"sc_{cid}", DD.fetch_person_rank, cid)
            _cached(f"tm_{cid}", DD.fetch_team_goals, cid)
    except Exception as e:  # noqa: BLE001
        st.error(f"数据加载失败：{type(e).__name__}: {e}")
        return
    if not st_rows:
        st.info(f"「{league}」暂无积分榜数据（赛事可能未开始 / 已结束）。")
        return
    st_rows = DD.enrich_standings(st_rows)

    tot_gf = sum(r["进球"] for r in st_rows)
    played = sum(r["赛"] for r in st_rows) // 2
    st.markdown(render_stat_tiles([
        (len(st_rows), f"{league} 参赛队", "red"),
        (played, "已赛场次", ""),
        (tot_gf, "总进球", ""),
        (round(tot_gf / max(1, played), 2), "场均进球", ""),
    ]), unsafe_allow_html=True)

    t1, t2, t_rt, t_pr, t_pred, t3, t4, t5 = st.tabs([
        "📋 积分榜", "⚽ 射手榜", "🎯 阵容 · 评分与能力", "📈 球员评分 · 能力榜",
        "🔮 赛果预测", "⚖️ 球队对比", "🏟️ 球队详情", "👤 球员详情"])

    # ---------- 1) 积分榜 ----------
    with t1:
        cc1, cc2 = st.columns(2, gap="large")
        with cc1:
            with st.container(border=True, key="dt_p_points"):
                st.markdown(render_h("积分 Top 12"), unsafe_allow_html=True)
                echarts(chart_points(st_rows, 12), 360)
        with cc2:
            with st.container(border=True, key="dt_p_goals"):
                st.markdown(render_h("进 / 失球对比 Top 10"), unsafe_allow_html=True)
                echarts(chart_goals(st_rows, 10), 360)
        with st.container(border=True, key="dt_p_table"):
            st.markdown(render_h("积分榜明细（含场均指标）"), unsafe_allow_html=True)
            df = pd.DataFrame(st_rows)[["排名", "球队", "赛", "胜", "平", "负", "进球",
                                        "失球", "净胜", "积分", "场均积分", "场均进球",
                                        "场均失球", "胜率"]]
            st.dataframe(df, width="stretch", height=430, hide_index=True)

    # ---------- 2) 射手榜 ----------
    with t2:
        if not sc_rows:
            st.info("暂无球员榜单数据。")
        else:
            cc1, cc2 = st.columns([1.35, 1], gap="large")
            with cc1:
                with st.container(border=True, key="dt_p_scorers"):
                    st.markdown(render_h("射手榜 Top 15"), unsafe_allow_html=True)
                    echarts(chart_scorers(sc_rows, 15), 430)
            with cc2:
                with st.container(border=True, key="dt_p_pie"):
                    st.markdown(render_h("进球来源球队分布"), unsafe_allow_html=True)
                    agg = {}
                    for r in sc_rows:
                        agg[r["球队"]] = agg.get(r["球队"], 0) + r["进球"]
                    echarts(chart_pie(list(agg.items()), 8), 430)
            with st.container(border=True, key="dt_p_scoretable"):
                st.markdown(render_h("射手榜明细"), unsafe_allow_html=True)
                st.dataframe(pd.DataFrame(sc_rows)[["排名", "球员", "球队", "进球"]],
                             width="stretch", height=400, hide_index=True)

    # ---------- 阵容与评分：首发 11 人评分 + 球队评分（首发均分）----------
    with t_rt:
        teams_sd = [(r["球队"], DD.sport_team_id(r.get("team_id")))
                    for r in st_rows if r.get("team_id")]
        if not teams_sd:
            st.info("暂无球队 ID，无法加载阵容与评分。")
        else:
            st.caption("**球队评分口径**：以首发 11 人的**能力值**（FC 系列数据，含传球 / 身体 / "
                       "射门等各项指标）为基础，取 11 人**总评的平均分**；同时给出该场**首发 11 人"
                       "比赛评分的平均分**作为对照。")
            tn = st.selectbox("选择球队", [t for t, _ in teams_sd], key="dt_rating_team")
            tid = dict(teams_sd)[tn]
            season, season_label = _season_picker(tid, "dt_rt_season")
            try:
                with st.spinner("正在加载球队赛程…"):
                    sched = _cached(f"sched_{tid}_{season}", DD.fetch_team_schedule,
                                    tid, season)
            except Exception as e:  # noqa: BLE001
                st.error(f"赛程加载失败：{type(e).__name__}: {e}")
                sched = []
            played = [m for m in sched if m.get("status") == "Played"]
            if not played:
                st.info(f"「{tn}」在 {season_label or '当前赛季'} 暂无已结束的比赛，"
                        f"换个赛季或球队试试。")
            else:
                st.caption(f"当前查看：**{season_label}** · 已结束 {len(played)} 场")
                opts = {}
                for m in list(reversed(played))[:20]:
                    opts[f"{m['start_play'][:10]}　{m['home']} {m['score']} {m['away']}"
                         f"（{m['competition']}）"] = m
                lab = st.selectbox("选择比赛（最近 20 场已结束）", list(opts.keys()),
                                   key="dt_match")
                mid = opts[lab]["match_id"]
                try:
                    with st.spinner("正在加载比赛阵容与评分…"):
                        lu = _cached(f"lineup_{mid}", DD.fetch_match_lineup, mid)
                except Exception as e:  # noqa: BLE001
                    st.error(f"阵容加载失败：{type(e).__name__}: {e}")
                    lu = {}
                A, B = lu.get("A"), lu.get("B")
                if A and B:
                    # ---- 以首发 11 人能力值为基础的球队评分 ----
                    try:
                        with st.spinner("正在加载首发 11 人能力值（传球 / 身体 / 射门…）…"):
                            abA = _cached(f"ab_{mid}_A", DD.fetch_team_ability,
                                          A["starters"], A.get("name") or "")
                            abB = _cached(f"ab_{mid}_B", DD.fetch_team_ability,
                                          B["starters"], B.get("name") or "")
                    except Exception as e:  # noqa: BLE001
                        st.warning(f"能力值加载失败（其余功能不受影响）：{type(e).__name__}: {e}")
                        abA, abB = {"players": []}, {"players": []}

                    st.markdown(render_stat_tiles([
                        (abA.get("team_avg") or "—", f"{A.get('name')} 球队能力评分", "red"),
                        (abB.get("team_avg") or "—", f"{B.get('name')} 球队能力评分", ""),
                        (A.get("avg_rate") or "—", f"{A.get('name')} 首发评分", "red"),
                        (B.get("avg_rate") or "—", f"{B.get('name')} 首发评分", ""),
                    ]), unsafe_allow_html=True)
                    st.caption(f"能力评分 = 首发 11 人能力值总评的平均分，基于 FC 系列数据"
                               f"（{abA.get('covered', 0)}/{abA.get('total', 0)} 人与 "
                               f"{abB.get('covered', 0)}/{abB.get('total', 0)} 人有能力数据）。")

                    # ---- 球队能力雷达对比 + 门将雷达 ----
                    rA = abA.get("radar_list") or []
                    rB = abB.get("radar_list") or []
                    if rA or rB:
                        cc_ra, cc_rb = st.columns([1.15, 1], gap="large")
                        with cc_ra:
                            with st.container(border=True, key="dt_p_ability_radar"):
                                st.markdown(render_h("两队首发能力雷达对比（非门将 6 维均值）"),
                                            unsafe_allow_html=True)
                                dims = [x["name"] for x in (rA or rB)]
                                echarts(chart_radar(dims, [
                                    {"name": A.get("name"),
                                     "data": [(abA.get("radar") or {}).get(d) for d in dims]},
                                    {"name": B.get("name"),
                                     "data": [(abB.get("radar") or {}).get(d) for d in dims]},
                                ]), 380)
                        with cc_rb:
                            with st.container(border=True, key="dt_p_gk_radar"):
                                g1, g2 = abA.get("gk_radar") or {}, abB.get("gk_radar") or {}
                                gk_dims = list(g1.keys()) or list(g2.keys())
                                if gk_dims:
                                    st.markdown(render_h("门将能力对比"),
                                                unsafe_allow_html=True)
                                    echarts(chart_radar(gk_dims, [
                                        {"name": f"{A.get('name')} · {abA.get('gk_name') or '门将'}",
                                         "data": [g1.get(d) for d in gk_dims]},
                                        {"name": f"{B.get('name')} · {abB.get('gk_name') or '门将'}",
                                         "data": [g2.get(d) for d in gk_dims]},
                                    ]), 380)
                                else:
                                    st.markdown(render_h("门将能力对比"), unsafe_allow_html=True)
                                    st.caption("该场门将能力数据缺失。")

                    with st.container(border=True, key="dt_p_lineup_chart"):
                        st.markdown(render_h("两队首发 11 人比赛评分对比"), unsafe_allow_html=True)
                        echarts(chart_lineup_compare(A, B), 380)

                    with st.container(border=True, key="dt_p_ability_chart"):
                        st.markdown(render_h("两队首发 11 人能力值对比"), unsafe_allow_html=True)
                        echarts(chart_ability_compare(abA, abB), 400)

                    with st.container(border=True, key="dt_p_ability_scatter"):
                        st.markdown(render_h("能力值 × 本场评分（谁没发挥出来？）"),
                                    unsafe_allow_html=True)
                        st.caption("右上＝能力强且发挥好；**左上＝能力强但本场没发挥**；右下＝超水平发挥。")
                        echarts(chart_ability_vs_rate([
                            {"name": A.get("name"), "players": abA.get("players") or []},
                            {"name": B.get("name"), "players": abB.get("players") or []},
                        ]), 420)

                    cA, cB = st.columns(2, gap="large")
                    for col, t, ab in ((cA, A, abA), (cB, B, abB)):
                        with col:
                            with st.container(border=True, key=f"dt_p_side_{t.get('team_id')}"):
                                st.markdown(render_h(
                                    f"{t['name']} · 首发 11 人（能力 {ab.get('team_avg')} ／ "
                                    f"评分 {t['avg_rate']}）"), unsafe_allow_html=True)
                                amap = {q.get("name"): q for q in (ab.get("players") or [])}
                                df = pd.DataFrame([{
                                    "号码": p["shirt"], "位置": p["position"], "球员": p["name"],
                                    "能力值": (amap.get(p["name"]) or {}).get("avg"),
                                    "本场评分": p["rate"],
                                    "队长": "✓" if p["captain"] else "",
                                    "MVP": "★" if p["mvp"] else "",
                                } for p in t["starters"]])
                                st.dataframe(df, width="stretch", hide_index=True, height=430)
                                st.caption(f"主帅：{t['coach'] or '—'}　·　平均年龄："
                                           f"{t['age'] or '—'}　·　全场最佳：{t['mvp'] or '—'}")
                    if lu.get("base"):
                        b = lu["base"]
                        st.caption(f"场地：{b.get('field') or '—'}　·　天气："
                                   f"{b.get('weather') or '—'}　·　主裁：{b.get('referee') or '—'}")

                    # ---- 分组能力均值对比（进攻/技巧/移动/力量/心理/防守）----
                    ga, gb = abA.get("groups_avg") or {}, abB.get("groups_avg") or {}
                    if ga or gb:
                        with st.container(border=True, key="dt_p_ability_group"):
                            st.markdown(render_h("两队能力分组均值对比"), unsafe_allow_html=True)
                            gdims = [g for g in DD.ABILITY_GROUP_ORDER
                                     if g in ga or g in gb]
                            echarts({
                                "color": [_RED, _BLUE],
                                "legend": {"top": 0, "textStyle": {"fontSize": 12}},
                                "tooltip": {"trigger": "axis"},
                                "grid": {"left": 46, "right": 18, "top": 44, "bottom": 30},
                                "xAxis": {"type": "category", "data": gdims,
                                          "axisLabel": {"fontSize": 11, "color": "#6b7280"}},
                                "yAxis": {"type": "value", "max": 100, "splitLine": _GRID},
                                "series": [
                                    {"name": A.get("name"), "type": "bar",
                                     "data": [ga.get(g) for g in gdims],
                                     "itemStyle": {"color": _RED, "borderRadius": [3, 3, 0, 0]},
                                     "label": {"show": True, "position": "top",
                                               "fontSize": 10, "color": "#6b7280"}},
                                    {"name": B.get("name"), "type": "bar",
                                     "data": [gb.get(g) for g in gdims],
                                     "itemStyle": {"color": _BLUE, "borderRadius": [3, 3, 0, 0]},
                                     "label": {"show": True, "position": "top",
                                               "fontSize": 10, "color": "#6b7280"}},
                                ],
                            }, 360)
                            st.caption("分组均值取该队**非门将首发**在该组各项指标的平均分"
                                       "（门将的门前指标另见图）。")

                    # ---- 各指标平均分（28 项，传球 / 身体 / 射门…）----
                    ia = abA.get("indicators_avg") or []
                    ib = abB.get("indicators_avg") or []
                    if ia or ib:
                        with st.container(border=True, key="dt_p_indicators"):
                            st.markdown(render_h("两队各指标平均分对比（非门将首发逐项平均）"),
                                        unsafe_allow_html=True)
                            echarts(chart_indicators_compare(ia, ib, A.get("name") or "",
                                                             B.get("name") or ""), 820)
                            st.caption("逐项平均分 = 该队非门将首发球员在此指标上数值的平均值"
                                       "（共 28 项，已排除门将占位项）。")
                            if ia:
                                dfi = pd.DataFrame({
                                    "组": [x["组"] for x in ia],
                                    "指标": [x["指标"] for x in ia],
                                    (A.get("name") or "主队"): [x["数值"] for x in ia],
                                })
                                if ib:
                                    mp = {x["指标"]: x["数值"] for x in ib}
                                    dfi[B.get("name") or "客队"] = [mp.get(x["指标"]) for x in ia]
                                    dfi["差值"] = [round(x["数值"] - (mp.get(x["指标"]) or 0), 1)
                                                   for x in ia]
                                st.dataframe(dfi, width="stretch", hide_index=True,
                                             height=320)

                    # ---- 单名球员的能力明细 ----
                    allp = {q.get("name"): q for q in (abA.get("players") or [])
                            + (abB.get("players") or []) if q.get("avg")}
                    if allp:
                        with st.container(border=True, key="dt_p_ability_one"):
                            st.markdown(render_h("单名球员能力明细（传球 / 身体 / 射门…）"),
                                        unsafe_allow_html=True)
                            who = st.selectbox("选择球员", sorted(allp.keys()),
                                               key="dt_ability_player")
                            pid = allp[who].get("id")
                            one = _cached(f"abp_{pid}", DD.fetch_player_ability, pid)
                            if not one:
                                st.info("该球员暂无能力值数据。")
                            else:
                                st.markdown(render_stat_tiles([
                                    (one.get("avg"), f"{who} 能力总评", "red"),
                                    (one.get("version") or "—", "数据版本", ""),
                                    (one.get("reg_pos") or "—", "注册位置", ""),
                                    (one.get("foot") or "—", "惯用脚", ""),
                                ]), unsafe_allow_html=True)
                                o1, o2 = st.columns([1, 1.25], gap="large")
                                with o1:
                                    echarts(chart_radar(one.get("dims") or [], [
                                        {"name": who, "data": [one["radar_map"].get(d)
                                                               for d in (one.get("dims") or [])]}
                                    ]), 620)
                                with o2:
                                    echarts(chart_ability_groups(one.get("groups") or []), 620)
                                st.dataframe(pd.DataFrame([{
                                    "组": g["组"], "指标": it["指标"], "数值": it["数值"],
                                } for g in (one.get("groups") or []) for it in g["指标"]]),
                                    width="stretch", hide_index=True, height=300)
                                cap = []
                                if one.get("stars"):
                                    cap.append("星级：" + "　".join(
                                        f"{s['name']} {'★' * s['val']}" for s in one["stars"]))
                                if one.get("positions"):
                                    cap.append("位置适配：" + "　".join(
                                        f"{p['name']} {p['val']}" for p in one["positions"][:6]))
                                if cap:
                                    st.caption("　·　".join(cap))
                else:
                    st.info("该场暂无阵容评分数据（可能未开赛或数据未生成）。")

    # ---------- 球员评分榜：多场汇总的场均评分 ----------
    with t_pr:
        teams_sd = [(r["球队"], DD.sport_team_id(r.get("team_id")))
                    for r in st_rows if r.get("team_id")]
        if not teams_sd:
            st.info("暂无球队 ID。")
        else:
            cc1, cc2, cc3 = st.columns([2, 1, 1], gap="medium")
            with cc1:
                tn = st.selectbox("选择球队", [t for t, _ in teams_sd], key="dt_rt_team")
            tid = dict(teams_sd)[tn]
            with cc2:
                nlab = st.selectbox("汇总场次", list(_RT_OPTS.keys()), index=1,
                                    key="dt_rt_n",
                                    help="选「整个赛季」会统计该赛季全部已结束比赛"
                                         "（首次约需几秒）")
            n = _RT_OPTS[nlab]
            with cc3:
                season, season_label = _season_picker(tid, "dt_pr_season")
            span = nlab if n else "整个赛季"
            try:
                with st.spinner(f"正在抓取「{tn}」{season_label or '当前赛季'} {span}"
                                f"的阵容评分…"):
                    rk = _cached(f"ratings_{tid}_{n or 'all'}_{season}",
                                 DD.fetch_team_ratings, tid, n, season)
            except Exception as e:  # noqa: BLE001
                st.error(f"评分加载失败：{type(e).__name__}: {e}")
                rk = {}
            players, matches = rk.get("players") or [], rk.get("matches") or []
            if not players:
                st.info(f"「{tn}」在 {season_label or '当前赛季'} 暂无可汇总的评分数据，"
                        f"换个赛季或球队试试。")
            else:
                try:
                    with st.spinner("正在加载球员能力值…"):
                        abmap = _cached(f"ablist_{tid}_{n}",
                                        DD.fetch_players_ability,
                                        [p.get("id") for p in players])
                except Exception:  # noqa: BLE001
                    abmap = {}
                for p in players:
                    p["ability"] = (abmap.get(str(p.get("id"))) or {}).get("avg")
                with_ab = [p for p in players if p.get("ability")]
                team_ability = (round(sum(p["ability"] for p in with_ab) / len(with_ab), 1)
                                if with_ab else None)
                st.markdown(render_stat_tiles([
                    (rk.get("team_avg") or "—", f"{tn} 场均首发评分", "red"),
                    (team_ability or "—", f"{tn} 球员能力均值", "red"),
                    (len(matches), "本次统计场次", ""),
                    (rk.get("played_total", len(matches)), "该赛季已结束场次", ""),
                ]), unsafe_allow_html=True)
                st.caption(f"赛季 **{season_label or '当前'}** · 区间 **{span}** · "
                           f"共统计 {rk.get('used', len(matches))} / "
                           f"{rk.get('played_total', len(matches))} 场已结束比赛"
                           f"（含杯赛 / 洲际赛）。")
                cc3, cc4 = st.columns([1.2, 1], gap="large")
                with cc3:
                    with st.container(border=True, key="dt_p_pr_bar"):
                        st.markdown(render_h("球员场均评分 Top 15"), unsafe_allow_html=True)
                        echarts(chart_player_rating(players, 15), 430)
                with cc4:
                    with st.container(border=True, key="dt_p_pr_trend"):
                        st.markdown(render_h("球队首发均分走势"), unsafe_allow_html=True)
                        echarts(chart_rating_trend(matches, tn),
                                430 if len(matches) <= 22 else 500)
                if with_ab:
                    cc5, cc6 = st.columns([1, 1], gap="large")
                    with cc5:
                        with st.container(border=True, key="dt_p_pr_ability"):
                            st.markdown(render_h("球员能力值 Top 15（传球 / 身体 / 射门…）"),
                                        unsafe_allow_html=True)
                            echarts(chart_ability_rank(
                                [{"name": p["name"], "avg": p["ability"]} for p in players],
                                15), 430)
                    with cc6:
                        with st.container(border=True, key="dt_p_pr_summary"):
                            st.markdown(render_h("球队能力结构（按指标组）"),
                                        unsafe_allow_html=True)
                            gsum = {}
                            for p in with_ab:
                                ab = abmap.get(str(p.get("id"))) or {}
                                if ab.get("is_gk"):
                                    continue
                                for g in ab.get("groups") or []:
                                    if g.get("组") == "守门":
                                        continue
                                    vals = [i["数值"] for i in g["指标"] if i.get("数值")]
                                    if vals:
                                        gsum.setdefault(g["组"], []).append(
                                            sum(vals) / len(vals))
                            gdims = [g for g in DD.ABILITY_GROUP_ORDER if g in gsum]
                            if gdims:
                                echarts({
                                    "tooltip": {"trigger": "axis"},
                                    "grid": {"left": 46, "right": 18, "top": 24, "bottom": 30},
                                    "xAxis": {"type": "category", "data": gdims,
                                              "axisLabel": {"fontSize": 11, "color": "#6b7280"}},
                                    "yAxis": {"type": "value", "max": 100, "splitLine": _GRID},
                                    "series": [{
                                        "type": "bar", "name": "分组均值",
                                        "data": [round(sum(gsum[g]) / len(gsum[g]), 1)
                                                 for g in gdims],
                                        "itemStyle": {"color": _RED, "borderRadius": [3, 3, 0, 0]},
                                        "label": {"show": True, "position": "top",
                                                  "fontSize": 10, "color": "#6b7280"}}],
                                }, 430)
                            else:
                                st.caption("暂无可汇总的分组能力数据。")
                with st.container(border=True, key="dt_p_pr_table"):
                    st.markdown(render_h("球员场均评分 / 能力值明细"), unsafe_allow_html=True)
                    st.dataframe(pd.DataFrame([{
                        "球员": p["name"], "位置": p["position"], "出场": p["matches"],
                        "能力值": p.get("ability"), "场均评分": p["avg_rate"], "最高": p["best"],
                        "各场评分": (" / ".join(str(x) for x in p["ratings"][:24])
                                     + ("　…（共 %d 场）" % len(p["ratings"])
                                        if len(p["ratings"]) > 24 else "")),
                    } for p in sorted(players, key=lambda x: -(x.get("ability") or 0))]),
                        width="stretch", hide_index=True, height=420)
                with st.container(border=True, key="dt_p_pr_matches"):
                    st.markdown(render_h("统计到的比赛"), unsafe_allow_html=True)
                    st.dataframe(pd.DataFrame([{
                        "比赛": m["label"], "赛事": m["competition"], "时间": m["start_play"][:16],
                        "阵型": m["formation"], "首发均分": m["avg_rate"], "MVP": m["mvp"],
                    } for m in matches]), width="stretch", hide_index=True,
                        height=260 if len(matches) <= 24 else 460)

    # ---------- 赛果预测：胜率 + 比分 ----------
    with t_pred:
        st.caption("**预测模型（启发式，非赔率，仅供参考）**：先用首发 11 人的能力值推出"
                   "**进攻 / 防守 / 门将指数**，再与两队**近期场均进失球**按权重混合"
                   "（小样本噪声已做向均值收缩），得到各自的期望进球；"
                   "最后用**泊松分布**算出胜平负与各比分的概率。"
                   "「近期状态权重」可调：0% 完全看能力值，100% 更看重近期战绩。")
        names_all = [r["球队"] for r in st_rows]
        tmap = {r["球队"]: r.get("team_id") for r in st_rows}
        if len(names_all) < 2:
            st.info("该联赛球队不足 2 支，无法做赛果预测。")
        else:
            c1, c2, c3 = st.columns([1.1, 1.1, 1], gap="medium")
            with c1:
                hname = st.selectbox("主队", names_all, index=0, key="pd_home")
            with c2:
                aname = st.selectbox("客队", names_all, index=1, key="pd_away")
            hid, aid = tmap.get(hname), tmap.get(aname)
            with c3:
                season, season_label = (_season_picker(hid, "pd_season")
                                        if hid else (None, ""))
            c4, c5 = st.columns([1, 1], gap="medium")
            with c4:
                fw = st.slider("近期状态权重（%）", 0, 100, 40, 5, key="pd_formw")
            with c5:
                fl = st.selectbox("近期场次", [4, 6, 8, 10], index=1, key="pd_formn",
                                  help="计算「近期场均进失球」取最近几场")

            if not hid or not aid:
                st.info("缺少球队 ID，无法预测。")
            elif hname == aname:
                st.warning("主队和客队不能是同一支球队。")
            else:
                base = DD.league_goal_baseline(st_rows)
                try:
                    with st.spinner("正在计算预测（读取能力值与近期状态）…"):
                        hp = _cached(f"pk_{hid}_{season}_{fl}", _team_pack, hid, season, fl)
                        ap = _cached(f"pk_{aid}_{season}_{fl}", _team_pack, aid, season, fl)
                except Exception as e:  # noqa: BLE001
                    st.error(f"预测数据加载失败：{type(e).__name__}: {e}")
                    hp = ap = {}
                pred = DD.poisson_predict(hp.get("ability") or {}, hp.get("form") or {},
                                          ap.get("ability") or {}, ap.get("form") or {},
                                          baseline=base, form_weight=fw / 100.0)
                best = pred["top_scores"][0]["score"] if pred["top_scores"] else "—"
                st.markdown(render_stat_tiles([
                    (f"{pred['p_home']}%", f"{hname} 胜", "red"),
                    (f"{pred['p_draw']}%", "平局", ""),
                    (f"{pred['p_away']}%", f"{aname} 胜", ""),
                    (best, "最可能比分", "red"),
                ]), unsafe_allow_html=True)
                st.caption(f"期望进球　{hname} **{pred['lambda_home']}** ／ {aname} "
                           f"**{pred['lambda_away']}**　·　联赛基线（每队每场）"
                           f"{base} 球　·　近期状态权重 {fw}%　·　赛季 "
                           f"{season_label or '当前'}")

                p1, p2 = st.columns([1, 1.2], gap="large")
                with p1:
                    with st.container(border=True, key="pd_prob"):
                        st.markdown(render_h("胜平负概率"), unsafe_allow_html=True)
                        echarts(chart_win_prob(pred, hname, aname), 170)
                        st.dataframe(pd.DataFrame([
                            {"比分": s["score"], "概率": f"{s['p']:.1f}%"}
                            for s in pred["top_scores"]]),
                            width="stretch", hide_index=True, height=230)
                with p2:
                    with st.container(border=True, key="pd_matrix"):
                        st.markdown(render_h("比分概率矩阵（行=客队进球，列=主队进球）"),
                                    unsafe_allow_html=True)
                        echarts(chart_score_matrix(pred, hname, aname), 430)

                hs, as_ = pred["strength"]["home"], pred["strength"]["away"]
                hf, af = hp.get("form") or {}, ap.get("form") or {}
                hab, aab = hp.get("ability") or {}, ap.get("ability") or {}
                with st.container(border=True, key="pd_basis"):
                    st.markdown(render_h("预测依据"), unsafe_allow_html=True)

                    def _s(v):
                        return "—" if v is None or v == "" else str(v)

                    st.dataframe(pd.DataFrame([
                        {"项目": "球队能力评分（首发11人均值）",
                         hname: _s(hab.get("team_avg")), aname: _s(aab.get("team_avg"))},
                        {"项目": "进攻指数", hname: _s(hs.get("attack")),
                         aname: _s(as_.get("attack"))},
                        {"项目": "防守指数", hname: _s(hs.get("defense")),
                         aname: _s(as_.get("defense"))},
                        {"项目": "门将指数", hname: _s(hs.get("gk")), aname: _s(as_.get("gk"))},
                        {"项目": f"近期战绩（近{fl}场）",
                         hname: f"{hf.get('w', 0)}胜{hf.get('d', 0)}平{hf.get('l', 0)}负",
                         aname: f"{af.get('w', 0)}胜{af.get('d', 0)}平{af.get('l', 0)}负"},
                        {"项目": "近期场均进球", hname: _s(hf.get("gf_pg")),
                         aname: _s(af.get("gf_pg"))},
                        {"项目": "近期场均失球", hname: _s(hf.get("ga_pg")),
                         aname: _s(af.get("ga_pg"))},
                        {"项目": "近期场均积分", hname: _s(hf.get("ppg")),
                         aname: _s(af.get("ppg"))},
                        {"项目": "进攻系数（越大越强）", hname: _s(hs.get("atk_mult")),
                         aname: _s(as_.get("atk_mult"))},
                        {"项目": "防守系数（越大越稳）", hname: _s(hs.get("def_mult")),
                         aname: _s(as_.get("def_mult"))},
                    ]), width="stretch", hide_index=True, height=396)

                hia = hab.get("indicators_avg") or []
                aia = aab.get("indicators_avg") or []
                if hia or aia:
                    with st.container(border=True, key="pd_indicators"):
                        st.markdown(render_h("两队各指标平均分对比（预测所用的能力值基础）"),
                                    unsafe_allow_html=True)
                        echarts(chart_indicators_compare(hia, aia, hname, aname), 820)

                if (hf.get("matches") or af.get("matches")):
                    with st.container(border=True, key="pd_form"):
                        st.markdown(render_h("近期状态（最近在前）"), unsafe_allow_html=True)
                        f1, f2 = st.columns(2, gap="large")
                        for col, nm, f in ((f1, hname, hf), (f2, aname, af)):
                            with col:
                                st.markdown(render_h(f"{nm} · 近 {fl} 场（"
                                                     f"场均进 {f.get('gf_pg')} / 失 "
                                                     f"{f.get('ga_pg')}）"),
                                            unsafe_allow_html=True)
                                st.dataframe(pd.DataFrame([{
                                    "日期": m["start_play"][:10], "赛事": m["competition"],
                                    "比赛": m["label"], "结果": m["result"],
                                } for m in (f.get("matches") or [])]),
                                    width="stretch", hide_index=True, height=280)

    # ---------- 5) 球队对比 ----------
    with t3:
        names_all = [r["球队"] for r in st_rows]
        pick = st.multiselect("选择要对比的球队（默认前 6 名）", names_all,
                              default=names_all[:6], key="dt_cmp")
        if pick:
            with st.container(border=True, key="dt_p_cmp"):
                st.markdown(render_h("球队指标对比：积分 / 进球 / 失球"), unsafe_allow_html=True)
                echarts(chart_compare(st_rows, pick), 400)
            sub = [r for r in st_rows if r["球队"] in pick]
            st.dataframe(pd.DataFrame(sub)[["排名", "球队", "赛", "胜", "平", "负", "进球",
                                            "失球", "净胜", "积分", "场均积分", "场均进球",
                                            "场均失球", "胜率"]],
                         width="stretch", hide_index=True)
        else:
            st.info("请至少选择一支球队。")

    # ---------- 6) 球队详情 ----------
    with t4:
        teams = [r for r in st_rows if r.get("team_id")]
        if not teams:
            st.info("暂无球队 ID，无法加载球队详情。")
        else:
            tn = st.selectbox("选择球队", [r["球队"] for r in teams], key="dt_team")
            row = next(r for r in teams if r["球队"] == tn)
            st.markdown(render_stat_tiles([
                (f"第 {row['排名']} 名", "当前排名", "red"),
                (row["积分"], "积分", ""),
                (f"{row['胜']}胜{row['平']}平{row['负']}负", "战绩", ""),
                (f"{row['进球']}/{row['失球']}", "进 / 失球", ""),
            ]), unsafe_allow_html=True)
            cL, cR = st.columns(2, gap="large")
            with cL:
                with st.container(border=True, key="dt_p_teamplayers"):
                    st.markdown(render_h("该队射手榜球员"), unsafe_allow_html=True)
                    tp = [r for r in sc_rows if r["球队"] == tn]
                    if tp:
                        echarts(chart_scorers(tp, min(10, len(tp))), 320)
                    else:
                        st.caption("该队暂无球员进入射手榜。")
            with cR:
                with st.container(border=True, key="dt_p_teamnews"):
                    st.markdown(render_h("球队近期新闻"), unsafe_allow_html=True)
                    try:
                        tinfo = _cached(f"team_{row['team_id']}", DD.fetch_team,
                                        row["team_id"])
                    except Exception:  # noqa: BLE001
                        tinfo = {"news": []}
                    if tinfo.get("news"):
                        for n in tinfo["news"][:8]:
                            st.markdown(
                                f'<div class="dqd-hot"><div class="c">{esc(n["title"])}</div>'
                                f'<div class="m">🗞️ 文章 ID：{n["id"]}</div></div>',
                                unsafe_allow_html=True)
                    else:
                        st.caption("暂无该队新闻。")
            st.caption("提示：想分析某条新闻的评论，可切到「📰 评论爬取」，"
                       "用「按链接 / 文章 ID 直接打开」粘贴上面的文章 ID。")

    # ---------- 7) 球员详情 ----------
    with t5:
        opts = {f"{r['球员']}（{r['球队']} · {r['进球']}球）": r
                for r in sc_rows if r.get("player_id")}
        if not opts:
            st.info("暂无可选球员（需要射手榜数据）。")
        else:
            label = st.selectbox("选择球员（射手榜）", list(opts.keys()), key="dt_player")
            sel = opts[label]
            try:
                with st.spinner("正在加载球员数据…"):
                    info = _cached(f"pl_{sel['player_id']}", DD.fetch_player,
                                   sel["player_id"])
            except Exception as e:  # noqa: BLE001
                st.error(f"球员数据加载失败：{type(e).__name__}: {e}")
                return
            meta = info.get("info") or {}
            try:
                with st.spinner("正在加载能力值…"):
                    ab = _cached(f"abp2_{sel['player_id']}", DD.fetch_player_ability,
                                 sel["player_id"])
            except Exception:  # noqa: BLE001
                ab = {}
            st.markdown(render_stat_tiles([
                (ab.get("avg") or "—", f"{sel['球员']} 能力总评", "red"),
                (sel["球队"], "效力球队", ""),
                (meta.get("身价", "—"), "身价", ""),
                (ab.get("version") or meta.get("国籍", "—"), "数据版本 / 国籍", ""),
            ]), unsafe_allow_html=True)

            # ---- 能力值：雷达 + 分组指标（传球 / 身体 / 射门…）----
            if ab:
                o1, o2 = st.columns([1, 1.25], gap="large")
                with o1:
                    with st.container(border=True, key="dt_p_pl_radar"):
                        st.markdown(render_h(f"{sel['球员']} · 能力雷达"),
                                    unsafe_allow_html=True)
                        dims = ab.get("dims") or []
                        echarts(chart_radar(dims, [
                            {"name": sel["球员"],
                             "data": [ab["radar_map"].get(d) for d in dims]}
                        ]), 620)
                        st.caption(f"注册位置：{ab.get('reg_pos') or '—'}　·　惯用脚："
                                   f"{ab.get('foot') or '—'}　·　数据版本："
                                   f"{ab.get('version') or '—'}")
                with o2:
                    with st.container(border=True, key="dt_p_pl_groups"):
                        st.markdown(render_h("各项指标（进攻 / 技巧 / 移动 / 力量 / 心理 / 防守…）"),
                                    unsafe_allow_html=True)
                        echarts(chart_ability_groups(ab.get("groups") or []), 620)
                with st.container(border=True, key="dt_p_pl_abtable"):
                    st.markdown(render_h("能力指标明细（按组）"), unsafe_allow_html=True)
                    st.dataframe(pd.DataFrame([{
                        "组": g["组"], "合计": g["合计"],
                        "指标": it["指标"], "数值": it["数值"],
                    } for g in (ab.get("groups") or []) for it in g["指标"]]),
                        width="stretch", hide_index=True, height=320)
                cap = []
                if ab.get("stars"):
                    cap.append("星级：" + "　".join(
                        f"{s['name']} {'★' * s['val']}" for s in ab["stars"]))
                if ab.get("positions"):
                    cap.append("位置适配：" + "　".join(
                        f"{p['name']} {p['val']}" for p in ab["positions"][:8]))
                if cap:
                    st.caption("　·　".join(cap))
            else:
                st.info("该球员暂无能力值数据（FC 系列数据未覆盖）。")

            seasons = info.get("seasons") or []
            matches = info.get("matches") or []
            if seasons:
                with st.container(border=True, key="dt_p_pltrend"):
                    st.markdown(render_h("多赛季数据趋势（上场 / 进球 / 助攻）"),
                                unsafe_allow_html=True)
                    echarts(chart_player_seasons(seasons, 10), 370)
                with st.container(border=True, key="dt_p_pltable"):
                    st.markdown(render_h("赛季数据明细"), unsafe_allow_html=True)
                    st.dataframe(pd.DataFrame(seasons), width="stretch", height=320,
                                 hide_index=True)
            if matches:
                with st.container(border=True, key="dt_p_plmatches"):
                    st.markdown(render_h("近期比赛记录"), unsafe_allow_html=True)
                    st.dataframe(pd.DataFrame(matches), width="stretch", height=320,
                                 hide_index=True)
            if not seasons and not matches:
                st.info("该球员暂无详细数据。")


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
  margin:20px 0 12px;padding-left:10px;border-left:4px solid var(--dqd-red);
  display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;}
.dqd-src{font-size:12px;font-weight:600;color:var(--muted);}
/* 标签筛选标题 */
.dqd-taglabel{font-size:13px;font-weight:700;color:var(--muted);margin:10px 0 4px;}
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
/* 卡片底部：分类/时间 + 评论数角标 */
.dqd-metarow{display:flex;align-items:center;justify-content:space-between;
  gap:8px;margin-top:2px;}
.dqd-cnt{font-size:12px;font-weight:700;color:var(--dqd-red);background:#fdeaea;
  border:1px solid #f5c2c2;border-radius:999px;padding:2px 10px;white-space:nowrap;}
.dqd-cnt.none{color:#9aa1ab;background:#f6f7f9;border-color:var(--line);font-weight:400;}

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
