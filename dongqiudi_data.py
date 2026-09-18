#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
懂球帝「数据分析」数据层
========================

实测可用的公开数据入口（全部走 www.dongqiudi.com 的服务端渲染页面，
不依赖需要签名鉴权的 api 搜索接口，因此部署环境同样可用）：

  - 联赛数据页  https://www.dongqiudi.com/data?cid={联赛ID}&tab={standings|team|person}
        · tab=standings  积分榜：# 球队 赛 胜 平 负 进/失 净胜 积分（含球队ID/队徽）
        · tab=team       球队进球榜：# 球队 进球
        · tab=person     球员榜（射手榜）：# 球员 球队 进球（含球员ID）
  - 球员详情页  https://www.dongqiudi.com/player/{球员ID}
        · 赛季数据表：赛季 俱乐部 上场 首发 进球 助攻 黄牌 红牌
        · 比赛记录表：日期 赛事 比赛 比分 结果 进球 助攻 评分 出场
        · 资料：身价 / 生日 / 国籍
  - 球队页      https://www.dongqiudi.com/team/{球队ID}
        · 球队近期新闻（/articles/{id}.html 链接）

联赛 ID（cid）实测自数据页的联赛列表；「英超」不在列表里，cid=4 由页面内嵌
payload 的 `"4","英超"` 推出。

零第三方依赖，仅用标准库。
"""

import gzip
import re
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

HTML_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 名称 -> cid（实测）。分组用于界面呈现。
FOOTBALL_LEAGUES = {
    "英超": 4, "西甲": 3, "意甲": 9, "德甲": 5, "法甲": 12,
    "欧冠": 6, "欧联": 14, "欧协联": 3904,
    "中超": 43, "中甲": 129, "中乙": 1535,
    "足协杯": 251, "亚冠精英": 226, "亚冠二级": 228,
    "沙特联": 197, "美职联": 26, "苏超(江苏)": 8647,
}
NATIONAL_LEAGUES = {
    "世界杯": 61, "亚洲杯": 225, "U17世界杯": 333, "U20女足世界杯": 408,
    "亚运男足": 434, "亚运女足": 761,
}
WOMEN_LEAGUES = {"女足亚冠": 937, "中女超": 1507}
ALL_LEAGUES = {**FOOTBALL_LEAGUES, **NATIONAL_LEAGUES, **WOMEN_LEAGUES}


# ----------------------------- 网络 & 解析工具 -----------------------------

def _get(url, timeout=20):
    req = urllib.request.Request(url, headers=HTML_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", "ignore")


def _text(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def _int(s):
    m = re.search(r"-?\d+", str(s or ""))
    return int(m.group(0)) if m else 0


def _thead(table_html):
    m = re.search(r"<thead.*?</thead>", table_html, re.S)
    if not m:
        return []
    return [_text(c) for c in re.findall(r"<th[^>]*>(.*?)</th>", m.group(0), re.S)]


def _dp_rows(html):
    return re.findall(r'<tr class="dp-row"[^>]*>(.*?)</tr>', html, re.S)


def _tr_cells(tr):
    return [_text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]


# ----------------------------- 联赛数据（积分榜 / 榜单） -----------------------------

def fetch_standings(cid):
    """积分榜。返回 [{"排名","球队","team_id","logo","赛","胜","平","负","进球","失球","净胜","积分"}...]"""
    html = _get(f"https://www.dongqiudi.com/data?cid={cid}&tab=standings")
    out = []
    for i, tr in enumerate(_dp_rows(html)):
        c = _tr_cells(tr)
        if len(c) < 9:
            continue
        tid = re.search(r'href="/team/(\d+)"', tr)
        logo = re.search(r'<img[^>]*?src="([^"]+)"', tr)
        gs = c[6].split("/") if "/" in c[6] else [c[6], ""]
        out.append({
            "排名": _int(c[0]) or (i + 1),
            "球队": c[1],
            "team_id": tid.group(1) if tid else None,
            "logo": logo.group(1) if logo else None,
            "赛": _int(c[2]), "胜": _int(c[3]), "平": _int(c[4]), "负": _int(c[5]),
            "进球": _int(gs[0]), "失球": _int(gs[1]) if len(gs) > 1 else 0,
            "净胜": _int(c[7]), "积分": _int(c[8]),
        })
    return out


def fetch_team_goals(cid):
    """球队进球榜。返回 [{"排名","球队","team_id","进球"}...]"""
    html = _get(f"https://www.dongqiudi.com/data?cid={cid}&tab=team")
    out = []
    for i, tr in enumerate(_dp_rows(html)):
        c = _tr_cells(tr)
        if len(c) < 3:
            continue
        tid = re.search(r'href="/team/(\d+)"', tr)
        out.append({
            "排名": _int(c[0]) or (i + 1),
            "球队": c[1],
            "team_id": tid.group(1) if tid else None,
            "进球": _int(c[2]),
        })
    return out


def fetch_person_rank(cid):
    """球员榜（射手榜）。返回 [{"排名","球员","player_id","球队","team_id","进球"}...]"""
    html = _get(f"https://www.dongqiudi.com/data?cid={cid}&tab=person")
    out = []
    for i, tr in enumerate(_dp_rows(html)):
        c = _tr_cells(tr)
        if len(c) < 4:
            continue
        pid = re.search(r'href="/(?:player|person)/(\d+)"', tr)
        tids = re.findall(r'href="/team/(\d+)"', tr)
        out.append({
            "排名": _int(c[0]) or (i + 1),
            "球员": c[1],
            "player_id": pid.group(1) if pid else None,
            "球队": c[2],
            "team_id": tids[0] if tids else None,
            "进球": _int(c[3]),
        })
    return out


# ----------------------------- 球员详情 -----------------------------

def fetch_player(pid):
    """球员详情：资料 + 赛季数据 + 比赛记录。"""
    html = _get(f"https://www.dongqiudi.com/player/{pid}")
    info = {}
    m = re.search(r"身价\s*([0-9.]+[万亿]?\s*欧)", html)
    if m:
        info["身价"] = re.sub(r"\s+", "", m.group(1))
    m = re.search(r"生日\s*(\d{4}-\d{2}-\d{2})", html)
    if m:
        info["生日"] = m.group(1)
    m = re.search(r"国籍\s*([\u4e00-\u9fff]{2,8})</", html)
    if m:
        info["国籍"] = m.group(1)

    seasons, matches = [], []
    for t in re.findall(r"<table.*?</table>", html, re.S):
        hs = _thead(t)
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S):
            cells = _tr_cells(tr)
            if cells:
                rows.append(cells)
        if not hs or not rows:
            continue
        # 第一行通常是表头文本行，丢掉
        rows = [r for r in rows if r[0] != hs[0]]
        dicts = [dict(zip(hs, r)) for r in rows if len(r) >= len(hs)]
        if "赛季" in hs and dicts:
            seasons = dicts
        elif "日期" in hs and dicts:
            matches = dicts
    return {"info": info, "seasons": seasons, "matches": matches}


# ----------------------------- 球队详情 -----------------------------

def fetch_team(tid):
    """球队页：近期新闻列表（id/标题/封面）。"""
    html = _get(f"https://www.dongqiudi.com/team/{tid}")
    news, seen = [], set()
    pat = re.compile(
        r'<a\b[^>]*?href=["\']([^"\']*?/articles/(\d+)\.html)["\'][^>]*>(.*?)</a>',
        re.I | re.S)
    for m in pat.finditer(html):
        aid = m.group(2)
        if aid in seen:
            continue
        title = _text(m.group(3))
        if len(title) < 4:
            continue
        seen.add(aid)
        back = html[max(0, m.start() - 1500):m.start()]
        cm = re.search(r'<img\b[^>]*?src=["\']([^"\']+\.(?:jpg|jpeg|png|webp))["\']', back, re.I)
        cover = cm.group(1) if cm else None
        if cover and cover.startswith("//"):
            cover = "https:" + cover
        news.append({"id": aid, "title": title, "cover": cover})
        if len(news) >= 20:
            break
    return {"news": news}


# ----------------------------- 派生指标（用于图表） -----------------------------

def enrich_standings(rows):
    """给积分榜补上场均指标，便于做『全方位』分析。"""
    out = []
    for r in rows:
        p = max(1, r.get("赛") or 1)
        out.append({
            **r,
            "场均积分": round(r["积分"] / p, 2),
            "场均进球": round(r["进球"] / p, 2),
            "场均失球": round(r["失球"] / p, 2),
            "胜率": round(r["胜"] / p * 100, 1),
        })
    return out
