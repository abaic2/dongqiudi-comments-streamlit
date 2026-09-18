#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
懂球帝「数据分析」数据层
========================

实测可用的公开数据入口，两类：

【A】sport-data.dongqiudi.com（懂球帝网页版数据页真正在用的 JSON 服务，无需签名）
      —— 从 /_nuxt/*.js 里挖出来的，是「评分 / 阵容 / 赛程 / 榜单」的来源：
        · /data/standing?season_id=            积分榜
        · /data/ranking/person?type=person     球员榜可用类型（42 种指标）
        · /data/person_ranking?type=goals      球员榜数据
        · /dqd/team/schedule/{teamId}          球队赛程（含已结束比赛的 match_id）
        · /dqd/team/sample/{teamId}            球队资料（城市/成立年/球场/身价）
        · /dqd/v1/match/lineup/{matchId}  ★    比赛阵容：首发 11 人 + 每人 rate 评分
              → 首发 11 人 rate 的平均分即「球队评分」

【B】www.dongqiudi.com 的服务端渲染页面（JSON 服务不可用时的兜底）：

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
import json
import re
import urllib.parse
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


# ============================================================================
# 评分 / 阵容 / 赛程（sport-data.dongqiudi.com —— 懂球帝网页版数据页的真正数据源）
# ----------------------------------------------------------------------------
# 关键发现：比赛阵容接口 /dqd/v1/match/lineup/{matchId} 里，每名球员都带
# `rate` 字段（如 "7.9"），这就是**球员比赛评分**；lineups 恰好是**首发 11 人**。
# 因此：球队评分 = 首发 11 人 rate 的平均分。
# 球队 ID 映射：sport-data 用 "50000" + 网页版(www)球队 ID（www=513 → 50000513 阿森纳）。
# ============================================================================

SPORT_BASE = "https://sport-data.dongqiudi.com/soccer/biz"

SPORT_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.dongqiudi.com/data",
}


def sport_team_id(www_team_id):
    """网页版球队 ID → sport-data 球队 ID（实测规则：前缀 50000）。"""
    s = str(www_team_id or "").strip()
    if not s:
        return None
    return s if s.startswith("50000") else "50000" + s


def _sget(path, params=None, timeout=20):
    """请求 sport-data 接口，自动解包 {template, content} 信封（content 可能是 JSON 字符串）。"""
    q = {"app": "dqd", "version": "853", "platform": "ios", "language": "zh-cn"}
    q.update(params or {})
    url = f"{SPORT_BASE}/{path}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers=SPORT_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        d = json.loads(raw.decode("utf-8", "ignore"))
    c = d.get("content", d)
    if isinstance(c, str):
        try:
            c = json.loads(c)
        except Exception:  # noqa: BLE001
            pass
    return c


def _rate(v):
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def fetch_ranking_types(kind="person"):
    """榜单可用类型列表。kind: person / team。返回 [{"name","type"}...]"""
    c = _sget(f"data/ranking/{kind}", {"season_id": 27502, "type": kind})
    rows = c.get("data") if isinstance(c, dict) else c
    return [{"name": r.get("name"), "type": r.get("type")}
            for r in (rows or []) if isinstance(r, dict)]


def fetch_sport_ranking(season_id, kind="person", rtype="goals"):
    """sport-data 榜单数据（kind=person/team）。"""
    path = "data/person_ranking" if kind == "person" else "data/team_ranking"
    c = _sget(path, {"season_id": season_id, "type": rtype})
    rows = c.get("data") if isinstance(c, dict) else c
    return rows or []


def fetch_team_schedule(team_id, season=None):
    """球队赛程。status=Played 表示已结束（可用于取 match_id 查阵容评分）。"""
    params = {"season": season} if season else {}
    c = _sget(f"dqd/team/schedule/{team_id}", params)
    if not isinstance(c, dict):
        return []
    tid = str(team_id)
    out = []
    for m in c.get("data") or []:
        if not isinstance(m, dict) or not m.get("match_id"):
            continue
        out.append({
            "match_id": str(m.get("match_id")),
            "competition": m.get("competition_name") or "",
            "gameweek": m.get("gameweek") or m.get("round_name") or "",
            "home": m.get("team_A_name") or "",
            "away": m.get("team_B_name") or "",
            "home_id": str(m.get("team_A_id") or ""),
            "away_id": str(m.get("team_B_id") or ""),
            "score": (f"{m.get('fs_A')}-{m.get('fs_B')}"
                      if m.get("fs_A") not in (None, "") else ""),
            "start_play": m.get("start_play") or "",
            "status": m.get("status") or "",
            "is_home": str(m.get("team_A_id") or "") == tid,
        })
    return out


def _parse_player(p):
    """规整单个球员（含 rate 评分与单场 stats）。"""
    st = p.get("statistics") or {}
    stats = {}
    if isinstance(st, dict):
        for kv in st.get("keys") or []:
            if isinstance(kv, dict) and kv.get("type"):
                stats[kv["type"]] = kv.get("data")
    return {
        "id": p.get("person_id"),
        "name": p.get("person") or "",
        "shirt": p.get("shirtnumber") or "",
        "position": p.get("position") or "",
        "rate": _rate(p.get("rate")),
        "captain": bool(p.get("captain")),
        "mvp": bool(p.get("is_mvp")),
        "nationality": p.get("nationality_name") or "",
        "events": p.get("events") or [],
        "stats": stats,
    }


def _parse_side(t):
    if not isinstance(t, dict):
        return None
    starters = [_parse_player(p) for p in (t.get("lineups") or []) if isinstance(p, dict)]
    subs = [_parse_player(p) for p in (t.get("sub") or []) if isinstance(p, dict)]
    rated = [p["rate"] for p in starters if p.get("rate")]
    return {
        "team_id": str(t.get("team_id") or ""),
        "name": t.get("team_name") or "",
        "logo": t.get("team_logo") or "",
        "formation": t.get("formation") or "",
        "coach": t.get("team_coach") or "",
        "market_value": t.get("team_market_value") or "",
        "age": t.get("team_age") or "",
        "starters": starters,
        "subs": subs,
        "avg_rate": round(sum(rated) / len(rated), 2) if rated else None,
        "mvp": next((p["name"] for p in starters + subs if p.get("mvp")), ""),
    }


def fetch_match_lineup(match_id):
    """比赛阵容 + 评分。返回 {"base","status","A","B"}；A/B 含首发 11 人评分与平均分。"""
    d = _sget(f"dqd/v1/match/lineup/{match_id}")
    if not isinstance(d, dict):
        return {}
    persons = d.get("persons") or {}
    return {
        "base": d.get("base") or {},
        "status": d.get("match_status") or "",
        "A": _parse_side(persons.get("team_A")),
        "B": _parse_side(persons.get("team_B")),
        "sideline": d.get("sideline") or {},
    }


def fetch_team_profile(team_id):
    """球队资料：城市 / 成立年份 / 主场 / 容量 / 身价 / 排名。"""
    d = _sget(f"dqd/team/sample/{team_id}")
    if not isinstance(d, dict):
        return {}
    return {
        "name": d.get("team_name") or "",
        "en_name": d.get("team_en_name") or "",
        "logo": d.get("team_logo") or "",
        "country": d.get("country") or "",
        "city": d.get("city") or "",
        "founded": d.get("founded") or "",
        "venue": d.get("venue_name") or "",
        "capacity": d.get("venue_capacity") or "",
        "market_value": d.get("market_value") or "",
        "rank": d.get("rank") or "",
        "nickname": d.get("nickname") or "",
    }


# ---------------------------------------------------------------------------
# 球员能力值（sofifa / EA FC 数据，与懂球帝球员页「能力」板块同源）
#   /soccer/data/sofifa/v1/player_ability/{person_id}?app=dqd&lang=zh-cn
#   → data.average.val    总评（0~99）
#     data.bar_info[]     分组指标：进攻/技巧/移动/力量/心理/防守/守门，每组 3~5 项
#     data.redar[]        6 维雷达：非门将=速度/力量/防守/盘带/传球/射门
#                                     门将  =扑救/位置/速度/反应/开球/手型
#     data.star_bar[]     国际声望 / 逆足能力 / 花式技巧（1~5 星）
#     data.fields[]       各位置适配度（含注册位置 best_pos）
#     data.version        数据版本（如 "FC 26"）
# ---------------------------------------------------------------------------
SOFIFA_BASE = "https://sport-data.dongqiudi.com/soccer/data/sofifa/v1"

RADAR_DIMS = ["速度", "力量", "防守", "盘带", "传球", "射门"]        # 非门将 6 维
GK_DIMS = ["扑救", "位置", "速度", "反应", "开球", "手型"]           # 门将 6 维
ABILITY_GROUP_ORDER = ["进攻", "技巧", "移动", "力量", "心理", "防守", "守门"]


def fetch_player_ability(person_id):
    """球员能力值。

    返回 {version, avg, groups:[{组,合计,指标:[{指标,数值}]}], radar:[{name,val}],
          radar_map, dims（按 RADAR_DIMS/GK_DIMS 排好序的名字）, stars, positions,
          foot, reg_pos, is_gk}；该球员无能力数据时返回 {}。
    """
    if not person_id:
        return {}
    url = f"{SOFIFA_BASE}/player_ability/{person_id}?app=dqd&lang=zh-cn"
    req = urllib.request.Request(url, headers=SPORT_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        d = json.loads(raw.decode("utf-8", "ignore"))
    data = d.get("data") or {}
    if not data or not (data.get("average") or {}).get("val"):
        return {}
    groups = []
    for g in data.get("bar_info") or []:
        items = [{"指标": i.get("name"), "数值": _int(i.get("val"))}
                 for i in (g.get("detail") or []) if i.get("name")]
        if items:
            groups.append({"组": g.get("title") or "", "合计": _int(g.get("total")),
                           "指标": items})
    groups.sort(key=lambda x: (ABILITY_GROUP_ORDER.index(x["组"])
                              if x["组"] in ABILITY_GROUP_ORDER else 99))
    radar = [{"name": x.get("name"), "val": _int(x.get("val"))}
             for x in (data.get("redar") or []) if x.get("name")]
    rmap = {x["name"]: x["val"] for x in radar}
    is_gk = "扑救" in rmap
    order = GK_DIMS if is_gk else RADAR_DIMS
    return {
        "version": data.get("version") or "",
        "avg": _int((data.get("average") or {}).get("val")),
        "groups": groups,
        "radar": radar,
        "radar_map": rmap,
        "dims": [d0 for d0 in order if d0 in rmap],
        "stars": [{"name": s.get("name"), "val": _int(s.get("val"))}
                  for s in (data.get("star_bar") or []) if s.get("name")],
        "positions": sorted([{"name": p.get("name"), "val": _int(p.get("val"))}
                             for p in (data.get("fields") or []) if p.get("name")],
                            key=lambda x: -x["val"]),
        "foot": (data.get("foot_info") or {}).get("val") or "",
        "reg_pos": (data.get("good_pos") or {}).get("val") or "",
        "is_gk": is_gk,
    }


def fetch_players_ability(person_ids, workers=8):
    """并发批量抓取能力值。返回 {person_id(str): ability_dict}（无数据的为空 dict）。"""
    from concurrent.futures import ThreadPoolExecutor
    ids = [str(i) for i in (person_ids or []) if i]

    def one(pid):
        try:
            return pid, fetch_player_ability(pid)
        except Exception:  # noqa: BLE001
            return pid, {}

    out = {}
    if ids:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for pid, ab in ex.map(one, ids):
                out[pid] = ab
    return out


def fetch_team_ability(starters, workers=8):
    """以首发球员的能力值为基础，算出「球队能力评分」。

    球队能力评分 = 首发 11 人能力值（总评）的平均分（与比赛评分口径一致）。
    同时给出球队雷达（非门将 6 维均值）与门将雷达。

    返回 {players:[{id,name,position,shirt,rate,avg,radar,is_gk}],
          team_avg, radar:{维度:值}, radar_list:[{name,val}], gk_radar, gk_name,
          covered, total, groups_avg:{组:均值}}
    """
    starters = starters or []
    got = fetch_players_ability([p.get("id") for p in starters], workers=workers)

    players, avgs, gk_radar, gk_name = [], [], {}, ""
    group_sum = {}
    for p in starters:
        ab = got.get(str(p.get("id"))) or {}
        rmap = ab.get("radar_map") or {}
        is_gk = bool(ab.get("is_gk"))
        players.append({
            "id": p.get("id"), "name": p.get("name"), "position": p.get("position"),
            "shirt": p.get("shirt"), "rate": p.get("rate"),
            "avg": ab.get("avg"), "radar": rmap, "is_gk": is_gk,
        })
        if ab.get("avg"):
            avgs.append(ab["avg"])
        if is_gk and rmap:
            gk_radar, gk_name = rmap, p.get("name") or ""
            continue        # 门将的门前指标单独呈现，不混入球队分组均值
        for g in ab.get("groups") or []:
            if g.get("组") == "守门":     # 非门将的「守门」项只是占位低分，无参考意义
                continue
            vals = [i["数值"] for i in g["指标"] if i.get("数值")]
            if vals:
                group_sum.setdefault(g["组"], []).append(sum(vals) / len(vals))

    # 球队雷达：非门将球员的 6 维均值
    out_players = [q for q in players if not q.get("is_gk") and q.get("radar")]
    radar_list = []
    for dim in RADAR_DIMS:
        vs = [q["radar"][dim] for q in out_players if q["radar"].get(dim)]
        if vs:
            radar_list.append({"name": dim, "val": round(sum(vs) / len(vs))})
    covered = len(avgs)
    return {
        "players": players,
        "team_avg": round(sum(avgs) / len(avgs), 1) if avgs else None,
        "radar": {x["name"]: x["val"] for x in radar_list},
        "radar_list": radar_list,
        "gk_radar": gk_radar,
        "gk_name": gk_name,
        "covered": covered,
        "total": len(players),
        "groups_avg": {k: round(sum(v) / len(v), 1) for k, v in group_sum.items()},
    }


def fetch_team_ratings(team_id, limit=6):
    """抓球队最近 limit 场已结束比赛的阵容，汇总每名球员的场均评分。

    返回 {"matches":[...], "players":[{name,position,matches,avg_rate,best,ratings}],
          "team_avg": float|None}
    """
    sched = [m for m in fetch_team_schedule(team_id)
             if m.get("status") == "Played" and m["match_id"]]
    sched = list(reversed(sched))[:limit]          # 最近的在前
    matches, agg = [], {}
    for m in sched:
        try:
            lu = fetch_match_lineup(m["match_id"])
        except Exception:  # noqa: BLE001
            continue
        side = None
        for k in ("A", "B"):
            t = lu.get(k)
            if t and t.get("team_id") == str(team_id):
                side = t
                break
        if not side:
            continue
        matches.append({
            "match_id": m["match_id"],
            "label": f"{m['home']} {m['score']} {m['away']}".strip(),
            "competition": m["competition"],
            "start_play": m["start_play"],
            "avg_rate": side.get("avg_rate"),
            "formation": side.get("formation"),
            "mvp": side.get("mvp"),
        })
        for p in side.get("starters") or []:
            if not p.get("rate"):
                continue
            e = agg.setdefault(p["name"], {"name": p["name"], "id": p.get("id"),
                                           "position": p["position"], "ratings": []})
            e["ratings"].append(p["rate"])
    players = []
    for e in agg.values():
        rs = e["ratings"]
        players.append({
            "name": e["name"], "position": e["position"], "matches": len(rs),
            "avg_rate": round(sum(rs) / len(rs), 2), "best": max(rs), "ratings": rs,
            "id": e.get("id"),
        })
    players.sort(key=lambda x: (-x["matches"], -x["avg_rate"]))
    team_vals = [m["avg_rate"] for m in matches if m.get("avg_rate")]
    return {
        "matches": matches,
        "players": players,
        "team_avg": round(sum(team_vals) / len(team_vals), 2) if team_vals else None,
    }
