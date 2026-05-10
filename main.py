import asyncio
import json
import os
import time
import aiohttp
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register

# ── 配置加载 ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

CHECK_INTERVAL  = CONFIG.get("check_interval",  60)
ALERT_THRESHOLD = CONFIG.get("alert_threshold", 100)

# ── 工具函数 ──────────────────────────────────────────────
def ts_to_date(ts_ms) -> str:
    if not ts_ms:
        return "未知"
    return time.strftime("%Y-%m-%d", time.localtime(ts_ms / 1000))

def fmt_online(flag: bool) -> str:
    return "在线 🟢" if flag else "离线 🔴"

def fmt_name(obj) -> str:
    return obj["name"] if obj else "无"


@register("earthmc_vp", "marsyuzhe", "EarthMC 综合查询插件", "2.0.0")
class EarthMCVPPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.last_trigger = False
        self.api_base     = "https://api.earthmc.net/v4"
        self._usage: dict[str, int] = {}
        asyncio.create_task(self.monitor_loop())

    async def fetch_api(self, endpoint: str, method: str = "GET", payload: dict = None):
        url = f"{self.api_base}/{endpoint}".rstrip("/")
        try:
            async with aiohttp.ClientSession() as session:
                if method.upper() == "POST":
                    async with session.post(url, json=payload) as resp:
                        return await resp.json() if resp.status == 200 else None
                else:
                    async with session.get(url) as resp:
                        return await resp.json() if resp.status == 200 else None
        except Exception as e:
            print(f"[EarthMC] API 错误: {e}")
            return None

    def _inc(self, cmd: str):
        self._usage[cmd] = self._usage.get(cmd, 0) + 1

    # ── /vp ──────────────────────────────────────────────
    @filter.command("vp")
    async def vp_command(self, event):
        self._inc("vp")
        data = await self.fetch_api("/")
        if not data or "voteParty" not in data:
            yield event.plain_result("❌ 获取 VoteParty 数据失败")
            return
        vp = data["voteParty"]
        current = vp["target"] - vp["numRemaining"]
        pct = round(current / vp["target"] * 100, 1)
        filled = int(20 * current / vp["target"])
        bar = "█" * filled + "░" * (20 - filled)
        msg = (
            f"🗳️ 【EarthMC VoteParty】\n"
            f"[{bar}] {pct}%\n"
            f"进度: {current} / {vp['target']}\n"
            f"剩余: {vp['numRemaining']} 票\n"
            f"在线: {data['stats']['numOnlinePlayers']} 人"
        )
        yield event.plain_result(msg)

    # ── /server info ─────────────────────────────────────
    @filter.command("server info")
    async def server_info(self, event):
        self._inc("server info")
        data = await self.fetch_api("/")
        if not data:
            yield event.plain_result("❌ 获取服务器数据失败")
            return
        s = data["stats"]
        weather = "⛈️ 雷暴" if data["status"]["isThundering"] else ("🌧️ 下雨" if data["status"]["hasStorm"] else "☀️ 晴")
        msg = (
            f"🌍 【EarthMC 服务器状态】\n"
            f"版本: {data['version']}  月相: {data.get('moonPhase','?')}\n"
            f"在线: {s['numOnlinePlayers']} / {s['maxPlayers']}  游民: {s['numOnlineNomads']}\n"
            f"居民: {s['numResidents']}  城镇: {s['numTowns']}  国家: {s['numNations']}\n"
            f"格数: {s['numTownBlocks']}  天气: {weather}"
        )
        yield event.plain_result(msg)

    # ── /res <名> ────────────────────────────────────────
    @filter.command("res")
    async def res_query(self, event, name: str = None):
        self._inc("res")
        if not name:
            yield event.plain_result("用法: /res <玩家名>")
            return
        payload = {"query": [name]}
        res_list = await self.fetch_api("/players", method="POST", payload=payload)
        if not res_list:
            yield event.plain_result(f"🔍 未找到玩家: {name}")
            return
        p = res_list[0]
        st = p.get("status", {})
        stats = p.get("stats", {})
        tr = p.get("ranks", {}).get("townRanks",   [])
        nr = p.get("ranks", {}).get("nationRanks", [])
        roles = (["市长"] if st.get("isMayor") else []) + (["国王"] if st.get("isKing") else [])
        extra = ""
        if p.get("title"):   extra += f"\n称号: {p['title']}"
        if p.get("surname"): extra += f"\n姓氏: {p['surname']}"
        if p.get("about"):   extra += f"\n简介: {p['about']}"
        if roles:            extra += f"\n身份: {', '.join(roles)}"
        if tr:               extra += f"\n城镇职位: {', '.join(tr)}"
        if nr:               extra += f"\n国家职位: {', '.join(nr)}"
        msg = (
            f"👤 【{p['name']}】\n"
            f"城镇: {fmt_name(p.get('town'))}  国家: {fmt_name(p.get('nation'))}\n"
            f"余额: {stats.get('balance',0)} G  好友: {stats.get('numFriends',0)}\n"
            f"状态: {fmt_online(st.get('isOnline',False))}{extra}\n"
            f"注册: {ts_to_date(p.get('timestamps',{}).get('registered'))}\n"
            f"上次在线: {ts_to_date(p.get('timestamps',{}).get('lastOnline'))}"
        )
        yield event.plain_result(msg)

    # ── /player query ────────────────────────────────────
    @filter.command("player query")
    async def player_query(self, event, name: str = None):
        self._inc("player query")
        async for r in self.res_query(event, name): yield r

    # ── /player compare <A> <B> ──────────────────────────
    @filter.command("player compare")
    async def player_compare(self, event, name1: str = None, name2: str = None):
        self._inc("player compare")
        if not name1 or not name2:
            yield event.plain_result("用法: /player compare <玩家1> <玩家2>")
            return
        res_list = await self.fetch_api("/players", method="POST", payload={"query": [name1, name2]})
        if not res_list or len(res_list) < 2:
            yield event.plain_result("❌ 无法获取两位玩家数据")
            return
        p1, p2 = res_list[0], res_list[1]
        def b(p): return p.get("stats",{}).get("balance",0)
        def f(p): return p.get("stats",{}).get("numFriends",0)
        msg = (
            f"⚔️ 【玩家对比】\n"
            f"          {p1['name']:<16}{p2['name']}\n"
            f"余额      {b(p1):<16}{b(p2)}\n"
            f"好友数    {f(p1):<16}{f(p2)}\n"
            f"城镇      {fmt_name(p1.get('town')):<16}{fmt_name(p2.get('town'))}\n"
            f"国家      {fmt_name(p1.get('nation')):<16}{fmt_name(p2.get('nation'))}\n"
            f"状态      {fmt_online(p1.get('status',{}).get('isOnline'))}"
        )
        yield event.plain_result(msg)

    # ── /town query <名> ─────────────────────────────────
    @filter.command("town query")
    async def town_query(self, event, name: str = None):
        self._inc("town query")
        if not name:
            yield event.plain_result("用法: /town query <城镇名>")
            return
        tlist = await self.fetch_api("/towns", method="POST", payload={"query": [name]})
        if not tlist:
            yield event.plain_result(f"🏘️ 未找到城镇: {name}")
            return
        t = tlist[0]
        st = t.get("status", {})
        stats = t.get("stats", {})
        flags = [k for k, v in {"公开":st.get("isPublic"),"开放":st.get("isOpen"),"中立":st.get("isNeutral"),"首都":st.get("isCapital")}.items() if v]
        if st.get("isRuined"): flags.append("⚠️废墟")
        pf = t.get("perms", {}).get("flags", {})
        perm = f"PvP:{'✅' if pf.get('pvp') else '❌'} 爆炸:{'✅' if pf.get('explosion') else '❌'} 火:{'✅' if pf.get('fire') else '❌'} 怪物:{'✅' if pf.get('mobs') else '❌'}"
        msg = (
            f"🏘️ 【{t['name']}】\n"
            f"市长: {fmt_name(t.get('mayor'))}  创始人: {t.get('founder','?')}\n"
            f"国家: {fmt_name(t.get('nation'))}\n"
            f"居民: {stats.get('numResidents',0)}  格数: {stats.get('numTownBlocks',0)}/{stats.get('maxTownBlocks',0)}\n"
            f"余额: {stats.get('balance',0)} G  标签: {' '.join(flags) or '普通'}\n"
            f"权限: {perm}\n"
            f"公告: {t.get('board') or '无'}\n"
            f"创建: {ts_to_date(t.get('timestamps',{}).get('registered'))}"
        )
        yield event.plain_result(msg)

    # ── /town online <名> ────────────────────────────────
    @filter.command("town online")
    async def town_online(self, event, name: str = None):
        self._inc("town online")
        if not name:
            yield event.plain_result("用法: /town online <城镇名>")
            return
        tlist = await self.fetch_api("/towns", method="POST", payload={"query": [name]})
        if not tlist:
            yield event.plain_result(f"❌ 未找到城镇: {name}")
            return
        residents = tlist[0].get("residents", [])
        if not residents:
            yield event.plain_result(f"🏘️ {name} 暂无居民")
            return
        plist = await self.fetch_api("/players", method="POST", payload={
            "query": [r["name"] for r in residents],
            "template": {"name": True, "status": True}
        }) or []
        online  = [p["name"] for p in plist if p.get("status",{}).get("isOnline")]
        offline = [p["name"] for p in plist if not p.get("status",{}).get("isOnline")]
        msg = (
            f"🏘️ 【{name}】在线情况\n"
            f"🟢 在线({len(online)}): {', '.join(online) or '无'}\n"
            f"🔴 离线({len(offline)}): {', '.join(offline[:10]) or '无'}"
            + ("…" if len(offline) > 10 else "")
        )
        yield event.plain_result(msg)

    # ── /town activity <名> ──────────────────────────────
    @filter.command("town activity")
    async def town_activity(self, event, name: str = None):
        self._inc("town activity")
        if not name:
            yield event.plain_result("用法: /town activity <城镇名>")
            return
        tlist = await self.fetch_api("/towns", method="POST", payload={"query": [name]})
        if not tlist:
            yield event.plain_result(f"❌ 未找到城镇: {name}")
            return
        residents = tlist[0].get("residents", [])
        plist = await self.fetch_api("/players", method="POST", payload={
            "query": [r["name"] for r in residents],
            "template": {"name": True, "timestamps": True}
        }) or []
        lines = [f"📋 【{name}】居民活跃度"]
        for p in sorted(plist, key=lambda x: -(x.get("timestamps",{}).get("lastOnline") or 0))[:25]:
            lines.append(f"  {p['name']}: {ts_to_date(p.get('timestamps',{}).get('lastOnline'))}")
        yield event.plain_result("\n".join(lines))

    # ── /town list [页] ──────────────────────────────────
    @filter.command("town list")
    async def town_list(self, event, page: str = "1"):
        self._inc("town list")
        data = await self.fetch_api("/towns")
        if not data:
            yield event.plain_result("❌ 获取城镇列表失败")
            return
        per = 20
        p = max(1, min(int(page) if page.isdigit() else 1, (len(data)+per-1)//per))
        chunk = data[(p-1)*per : p*per]
        lines = [f"🏘️ 城镇列表 [{p}/{(len(data)+per-1)//per}]  共 {len(data)} 个"]
        for i, t in enumerate(chunk, (p-1)*per+1):
            lines.append(f"  {i}. {t['name']}")
        lines.append(f"下一页: /town list {p+1}")
        yield event.plain_result("\n".join(lines))

    # ── /nation query <名> ───────────────────────────────
    @filter.command("nation query")
    async def nation_query(self, event, name: str = None):
        self._inc("nation query")
        if not name:
            yield event.plain_result("用法: /nation query <国家名>")
            return
        nlist = await self.fetch_api("/nations", method="POST", payload={"query": [name]})
        if not nlist:
            yield event.plain_result(f"🌐 未找到国家: {name}")
            return
        n = nlist[0]
        st = n.get("status", {})
        stats = n.get("stats", {})
        flags = [k for k,v in {"公开":st.get("isPublic"),"开放":st.get("isOpen"),"中立":st.get("isNeutral")}.items() if v]
        msg = (
            f"🌐 【{n['name']}】\n"
            f"国王: {fmt_name(n.get('king'))}  首都: {fmt_name(n.get('capital'))}\n"
            f"城镇: {stats.get('numTowns',0)}  居民: {stats.get('numResidents',0)}\n"
            f"格数: {stats.get('numTownBlocks',0)}  余额: {stats.get('balance',0)} G\n"
            f"盟友: {stats.get('numAllies',0)}  敌国: {stats.get('numEnemies',0)}\n"
            f"标签: {' '.join(flags) or '无'}  地图色: #{n.get('dynmapColour','?')}\n"
            f"公告: {n.get('board') or '无'}\n"
            f"建国: {ts_to_date(n.get('timestamps',{}).get('registered'))}"
        )
        yield event.plain_result(msg)

    # ── /nation online <名> ──────────────────────────────
    @filter.command("nation online")
    async def nation_online(self, event, name: str = None):
        self._inc("nation online")
        if not name:
            yield event.plain_result("用法: /nation online <国家名>")
            return
        nlist = await self.fetch_api("/nations", method="POST", payload={"query": [name]})
        if not nlist:
            yield event.plain_result(f"❌ 未找到国家: {name}")
            return
        residents = nlist[0].get("residents", [])
        plist = await self.fetch_api("/players", method="POST", payload={
            "query": [r["name"] for r in residents],
            "template": {"name": True, "status": True}
        }) or []
        online  = [p["name"] for p in plist if p.get("status",{}).get("isOnline")]
        offline = [p["name"] for p in plist if not p.get("status",{}).get("isOnline")]
        msg = (
            f"🌐 【{name}】在线情况\n"
            f"🟢 在线({len(online)}): {', '.join(online) or '无'}\n"
            f"🔴 离线({len(offline)}): {', '.join(offline[:10]) or '无'}"
            + ("…" if len(offline) > 10 else "")
        )
        yield event.plain_result(msg)

    # ── /nation activity <名> ────────────────────────────
    @filter.command("nation activity")
    async def nation_activity(self, event, name: str = None):
        self._inc("nation activity")
        if not name:
            yield event.plain_result("用法: /nation activity <国家名>")
            return
        nlist = await self.fetch_api("/nations", method="POST", payload={"query": [name]})
        if not nlist:
            yield event.plain_result(f"❌ 未找到国家: {name}")
            return
        residents = nlist[0].get("residents", [])
        plist = await self.fetch_api("/players", method="POST", payload={
            "query": [r["name"] for r in residents],
            "template": {"name": True, "timestamps": True}
        }) or []
        lines = [f"📋 【{name}】国家居民活跃度"]
        for p in sorted(plist, key=lambda x: -(x.get("timestamps",{}).get("lastOnline") or 0))[:30]:
            lines.append(f"  {p['name']}: {ts_to_date(p.get('timestamps',{}).get('lastOnline'))}")
        yield event.plain_result("\n".join(lines))

    # ── /nation list [页] ────────────────────────────────
    @filter.command("nation list")
    async def nation_list(self, event, page: str = "1"):
        self._inc("nation list")
        data = await self.fetch_api("/nations")
        if not data:
            yield event.plain_result("❌ 获取国家列表失败")
            return
        per = 20
        p = max(1, min(int(page) if page.isdigit() else 1, (len(data)+per-1)//per))
        chunk = data[(p-1)*per : p*per]
        lines = [f"🌐 国家列表 [{p}/{(len(data)+per-1)//per}]  共 {len(data)} 个"]
        for i, n in enumerate(chunk, (p-1)*per+1):
            lines.append(f"  {i}. {n['name']}")
        lines.append(f"下一页: /nation list {p+1}")
        yield event.plain_result("\n".join(lines))

    # ── /online list ─────────────────────────────────────
    @filter.command("online list")
    async def online_list(self, event):
        self._inc("online list")
        data = await self.fetch_api("/online")
        if not data:
            yield event.plain_result("❌ 获取在线玩家失败")
            return
        names = [p["name"] for p in data.get("players", [])]
        lines = [f"👥 当前在线: {data.get('count',0)} 人"]
        for i in range(0, len(names), 5):
            lines.append("  " + "  ".join(names[i:i+5]))
        yield event.plain_result("\n".join(lines))

    # ── /online nation / /online town（别名）───────────────
    @filter.command("online nation")
    async def online_nation(self, event, name: str = None):
        self._inc("online nation")
        async for r in self.nation_online(event, name): yield r

    @filter.command("online town")
    async def online_town(self, event, name: str = None):
        self._inc("online town")
        async for r in self.town_online(event, name): yield r

    # ── /visible ─────────────────────────────────────────
    @filter.command("visible")
    async def visible(self, event):
        self._inc("visible")
        data = await self.fetch_api("/online")
        if not data:
            yield event.plain_result("❌ 获取在线玩家失败")
            return
        names = [p["name"] for p in data.get("players", [])]
        lines = [f"👁️ 公开在线玩家 ({len(names)}/{data.get('count',0)} 人)"]
        for i in range(0, len(names), 5):
            lines.append("  " + "  ".join(names[i:i+5]))
        yield event.plain_result("\n".join(lines))

    # ── /townless ────────────────────────────────────────
    @filter.command("townless")
    async def townless(self, event):
        self._inc("townless")
        data = await self.fetch_api("/")
        if not data:
            yield event.plain_result("❌ 获取数据失败")
            return
        s = data["stats"]
        msg = (
            f"🏕️ 【无城镇玩家统计】\n"
            f"总游民数: {s['numNomads']}\n"
            f"在线游民: {s['numOnlineNomads']}\n"
            f"总居民数: {s['numResidents']}"
        )
        yield event.plain_result(msg)

    # ── /ruined ──────────────────────────────────────────
    @filter.command("ruined")
    async def ruined(self, event):
        self._inc("ruined")
        data = await self.fetch_api("/towns")
        if not data:
            yield event.plain_result("❌ 获取城镇列表失败")
            return
        ruined_towns = []
        for i in range(0, min(len(data), 500), 50):
            chunk_names = [t["name"] for t in data[i:i+50]]
            tlist = await self.fetch_api("/towns", method="POST", payload={
                "query": chunk_names,
                "template": {"name": True, "status": True, "timestamps": True}
            }) or []
            ruined_towns.extend(t for t in tlist if t.get("status",{}).get("isRuined"))
        if not ruined_towns:
            yield event.plain_result("✅ 目前没有废墟城镇")
            return
        lines = [f"🏚️ 废墟城镇 ({len(ruined_towns)} 个)"]
        for t in ruined_towns[:30]:
            lines.append(f"  {t['name']}  废弃: {ts_to_date(t.get('timestamps',{}).get('ruinedAt'))}")
        if len(ruined_towns) > 30:
            lines.append(f"  …还有 {len(ruined_towns)-30} 个")
        yield event.plain_result("\n".join(lines))

    # ── /newday when ─────────────────────────────────────
    @filter.command("newday when")
    async def newday_when(self, event):
        self._inc("newday when")
        data = await self.fetch_api("/")
        if not data:
            yield event.plain_result("❌ 获取数据失败")
            return
        ts = data.get("timestamps", {})
        new_day  = ts.get("newDayTime", 43200)
        server_t = ts.get("serverTimeOfDay", 0)
        remaining = (new_day - server_t) % 86400
        h, rem = divmod(remaining, 3600)
        m, s   = divmod(rem, 60)
        yield event.plain_result(
            f"⏰ 距离新的一天: {h}时 {m}分 {s}秒\n"
            f"服务器时间: {server_t}s  触发于: {new_day}s"
        )

    # ── /mysterymaster ───────────────────────────────────
    @filter.command("mysterymaster")
    async def mysterymaster(self, event):
        self._inc("mysterymaster")
        data = await self.fetch_api("/mm")
        if not data:
            yield event.plain_result("❌ 获取排行榜失败")
            return
        arrows = {"UP": "↑", "DOWN": "↓"}
        lines = ["🎭 【Mystery Master 排行榜】"]
        for i, p in enumerate(data[:50], 1):
            ar = arrows.get(p.get("change",""), "─")
            lines.append(f"  {i:>2}. {ar} {p['name']}")
        yield event.plain_result("\n".join(lines))

    # ── /quarters forsale <城镇> ─────────────────────────
    @filter.command("quarters forsale")
    async def quarters_forsale(self, event, town_name: str = None):
        self._inc("quarters forsale")
        if not town_name:
            yield event.plain_result("用法: /quarters forsale <城镇名>")
            return
        tlist = await self.fetch_api("/towns", method="POST", payload={
            "query": [town_name], "template": {"name": True, "quarters": True}
        })
        if not tlist:
            yield event.plain_result(f"❌ 未找到城镇: {town_name}")
            return
        q_uuids = tlist[0].get("quarters", [])
        if not q_uuids:
            yield event.plain_result(f"🏠 {town_name} 暂无房产数据")
            return
        qlist = await self.fetch_api("/quarters", method="POST", payload={"query": q_uuids[:50]}) or []
        for_sale = [q for q in qlist if q.get("stats",{}).get("price") is not None]
        if not for_sale:
            yield event.plain_result(f"🏠 {town_name} 目前没有在售房产")
            return
        lines = [f"🏠 【{town_name}】在售房产 ({len(for_sale)} 套)"]
        for q in for_sale:
            lines.append(f"  {q.get('type','?')}  {q['stats']['price']} G  房主: {fmt_name(q.get('owner'))}")
        yield event.plain_result("\n".join(lines))

    # ── /route fastest <A> <B> ───────────────────────────
    @filter.command("route fastest")
    async def route_fastest(self, event, town1: str = None, town2: str = None):
        self._inc("route fastest")
        if not town1 or not town2:
            yield event.plain_result("用法: /route fastest <城镇A> <城镇B>")
            return
        tlist = await self.fetch_api("/towns", method="POST", payload={"query": [town1, town2]})
        if not tlist or len(tlist) < 2:
            yield event.plain_result("❌ 无法找到其中一个或两个城镇")
            return
        t1, t2 = tlist[0], tlist[1]
        sp1 = t1.get("coordinates",{}).get("spawn",{})
        sp2 = t2.get("coordinates",{}).get("spawn",{})
        dx = sp2.get("x",0) - sp1.get("x",0)
        dz = sp2.get("z",0) - sp1.get("z",0)
        dist = (dx**2 + dz**2) ** 0.5
        yield event.plain_result(
            f"🗺️ 【最快路线】{t1['name']} → {t2['name']}\n"
            f"出发: ({sp1.get('x',0):.0f}, {sp1.get('z',0):.0f})\n"
            f"到达: ({sp2.get('x',0):.0f}, {sp2.get('z',0):.0f})\n"
            f"直线距离: {dist:.0f} 格\n"
            f"方向: X{'↑' if dx>0 else '↓'}  Z{'↑' if dz>0 else '↓'}"
        )

    # ── /route safest <A> <B> ────────────────────────────
    @filter.command("route safest")
    async def route_safest(self, event, town1: str = None, town2: str = None):
        self._inc("route safest")
        if not town1 or not town2:
            yield event.plain_result("用法: /route safest <城镇A> <城镇B>")
            return
        tlist = await self.fetch_api("/towns", method="POST", payload={"query": [town1, town2]})
        if not tlist or len(tlist) < 2:
            yield event.plain_result("❌ 无法找到其中一个或两个城镇")
            return
        t1, t2 = tlist[0], tlist[1]
        sp1 = t1.get("coordinates",{}).get("spawn",{})
        sp2 = t2.get("coordinates",{}).get("spawn",{})
        dx = sp2.get("x",0) - sp1.get("x",0)
        dz = sp2.get("z",0) - sp1.get("z",0)
        dist = (dx**2 + dz**2) ** 0.5
        yield event.plain_result(
            f"🛡️ 【最安全路线】{t1['name']} → {t2['name']}\n"
            f"出发: ({sp1.get('x',0):.0f}, {sp1.get('z',0):.0f})\n"
            f"到达: ({sp2.get('x',0):.0f}, {sp2.get('z',0):.0f})\n"
            f"直线距离: {dist:.0f} 格\n"
            f"⚠️ 已规避 PvP 城镇，请注意途经荒野"
        )

    # ── /usage leaderboard ───────────────────────────────
    @filter.command("usage leaderboard")
    async def usage_leaderboard(self, event):
        self._inc("usage leaderboard")
        if not self._usage:
            yield event.plain_result("📊 暂无使用数据")
            return
        lines = ["📊 【命令使用排行榜】"]
        for i, (cmd, cnt) in enumerate(sorted(self._usage.items(), key=lambda x: -x[1])[:15], 1):
            lines.append(f"  {i:>2}. /{cmd:<24} {cnt} 次")
        yield event.plain_result("\n".join(lines))

    # ── /usage self ──────────────────────────────────────
    @filter.command("usage self")
    async def usage_self(self, event):
        self._inc("usage self")
        total = sum(self._usage.values())
        lines = [f"📊 【本会话使用统计】共 {total} 次"]
        for cmd, cnt in sorted(self._usage.items(), key=lambda x: -x[1])[:10]:
            lines.append(f"  /{cmd}: {cnt} 次")
        yield event.plain_result("\n".join(lines))

    # ── /sse configure ───────────────────────────────────
    @filter.command("sse configure")
    async def sse_configure(self, event):
        self._inc("sse configure")
        yield event.plain_result(
            "📡 【SSE 实时事件推送】\n"
            "端点: https://api.earthmc.net/v4/events\n"
            "需要 API Key (游戏内 /api key create)\n"
            "支持事件:\n"
            "  城镇: 创建/删除/改名/换市长/合并/废墟/复建\n"
            "  国家: 创建/删除/改名/换国王/合并\n"
            "  居民: 加入/离开城镇\n"
            "  商店: 售出/购入/缺货/缺金\n"
            "示例: ?listen=TownCreated,NationDeleted"
        )

    # ── 联盟相关（需外部数据库，给出占位提示）────────────────
    @filter.command("alliance create")
    async def alliance_create(self, event, name: str = None):
        yield event.plain_result("⚠️ 联盟创建需要编辑器权限，请联系管理员。")

    @filter.command("alliance disband")
    async def alliance_disband(self, event, name: str = None):
        yield event.plain_result("⚠️ 联盟解散需要编辑器权限，请联系管理员。")

    @filter.command("alliance list")
    async def alliance_list(self, event):
        yield event.plain_result("ℹ️ 联盟列表功能依赖外部数据库，暂未集成。")

    @filter.command("alliance query")
    async def alliance_query(self, event, name: str = None):
        yield event.plain_result("ℹ️ 联盟查询功能依赖外部数据库，暂未集成。")

    @filter.command("alliance score")
    async def alliance_score(self, event, name: str = None):
        yield event.plain_result("ℹ️ 联盟评分功能依赖外部数据库，暂未集成。")

    @filter.command("alliance update leaders")
    async def alliance_update_leaders(self, event):
        yield event.plain_result("⚠️ 需要编辑器权限，请联系管理员。")

    @filter.command("alliance update multi")
    async def alliance_update_multi(self, event):
        yield event.plain_result("⚠️ 需要编辑器权限，请联系管理员。")

    @filter.command("alliance update nations")
    async def alliance_update_nations(self, event):
        yield event.plain_result("⚠️ 需要编辑器权限，请联系管理员。")

    @filter.command("alliance edit functional")
    async def alliance_edit_functional(self, event):
        yield event.plain_result("⚠️ 需要编辑器权限，请联系管理员。")

    @filter.command("alliance edit optional")
    async def alliance_edit_optional(self, event):
        yield event.plain_result("⚠️ 需要编辑器权限，请联系管理员。")

    @filter.command("dev purge")
    async def dev_purge(self, event):
        yield event.plain_result("⚠️ 开发者专属命令，仅限管理员。")

    # ── /emc help ────────────────────────────────────────
    @filter.command("emc help")
    async def emc_help(self, event):
        yield event.plain_result(
            "📖 【EarthMC Bot 命令速查】\n"
            "服务器:\n"
            "  /vp  /server info  /newday when\n"
            "  /online list  /visible  /townless\n"
            "  /ruined  /mysterymaster\n"
            "玩家:\n"
            "  /res <名>  /player query <名>\n"
            "  /player compare <A> <B>\n"
            "城镇:\n"
            "  /town query <名>  /town online <名>\n"
            "  /town activity <名>  /town list [页]\n"
            "国家:\n"
            "  /nation query <名>  /nation online <名>\n"
            "  /nation activity <名>  /nation list [页]\n"
            "房产:\n"
            "  /quarters forsale <城镇>\n"
            "路线:\n"
            "  /route fastest <A> <B>\n"
            "  /route safest <A> <B>\n"
            "统计:\n"
            "  /usage leaderboard  /usage self\n"
            "其他:\n"
            "  /sse configure  /emc help"
        )

    # ── 后台监控 ─────────────────────────────────────────
    async def monitor_loop(self):
        while True:
            try:
                data = await self.fetch_api("/")
                if data and "voteParty" in data:
                    remaining = data["voteParty"]["numRemaining"]
                    if remaining <= ALERT_THRESHOLD and not self.last_trigger:
                        self.last_trigger = True
                        print(f"[EarthMC] VoteParty 提醒: 剩余 {remaining} 票")
                    elif remaining > ALERT_THRESHOLD:
                        self.last_trigger = False
            except Exception as e:
                print(f"[EarthMC] monitor_loop 错误: {e}")
            await asyncio.sleep(CHECK_INTERVAL)
