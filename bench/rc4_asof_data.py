#!/usr/bin/env python3
"""Validation data for as-of selection (bench/results/asof_selection_preregistration.md).

    python3 bench/rc4_asof_data.py --tempreason DIR --smoke SMOKE_STREAMS.json --out STREAMS.json

* TempReason L2 / L3 (public, HF tonytan48/TempReason; not committed): fresh
  samples that exclude every id the 2026-10-05 lead smoke sampled. One user per
  question; the question's fact_context sentences are Added as user turns of
  one session stamped 2024-06-01, as in the smoke.
* Synthetic dated profiles from NEW templates (not the smoke's): 10 English and
  10 Chinese streams, other attributes (phone carrier, car, manager, rent,
  club), other wording, other date formats. Values are stated without years
  and without correction words. Five dated as-of questions and one "now"
  question per stream.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
from pathlib import Path

SEED = 20261006


def ms(year: int, month: int, day: int, minute: int = 0) -> int:
    return int(dt.datetime(year, month, day, 9, minute, tzinfo=dt.timezone.utc).timestamp() * 1000)


def tempreason(path: Path, n: int, label: str, exclude: set[str]) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [row for row in rows if row["id"] not in exclude]
    sample = random.Random(SEED).sample(rows, n)
    streams = []
    for row in sample:
        facts = [f.strip() for f in row["fact_context"].split("\n") if f.strip()]
        messages = [{"role": "user", "content": f, "timestamp": ms(2024, 6, 1, i % 60)} for i, f in enumerate(facts)]
        streams.append({"id": f"{label}:{row['id']}", "adds": [messages],
                        "questions": [{"id": f"{label}:{row['id']}", "question": row["question"],
                                       "gold_answer": " or ".join(row["text_answers"]["text"]),
                                       "group": label, "dated": True}]})
    return streams


# --- synthetic, new templates -------------------------------------------------------
EN = [
    # (owner phrase, possessive for questions, carrier1, carrier2, car1, car2, manager1, manager2, rent1, rent2, club)
    ("I", "my", "Verizon", "T-Mobile", "Honda Civic", "Mazda CX-5", "Priya Raman", "Owen Clarke", "$1,450", "$1,610", "Riverside Rowing Club"),
    ("I", "my", "AT&T", "Mint Mobile", "Ford Focus", "Subaru Outback", "Hannah Weiss", "Marco Bellini", "$980", "$1,120", "Northside Chess Club"),
    ("I", "my", "Vodafone", "EE", "VW Golf", "Kia Niro", "Fatima Khan", "George Hale", "£1,050", "£1,190", "Hillcrest Running Club"),
    ("I", "my", "Telstra", "Optus", "Toyota Corolla", "Hyundai Ioniq", "Liam O'Neill", "Sofia Duarte", "A$520 a week", "A$585 a week", "Bayview Sailing Club"),
    ("I", "my", "Rogers", "Fido", "Nissan Leaf", "Tesla Model 3", "Chen Wei", "Amara Obi", "C$1,800", "C$2,050", "Lakeshore Climbing Gym"),
    ("my sister Elena", "Elena's", "O2", "Three", "Fiat 500", "Peugeot 208", "Rafael Mendes", "Ingrid Larsen", "€900", "€1,020", "Old Town Choir"),
    ("my roommate Kwame", "Kwame's", "Sprint", "Visible", "Chevy Malibu", "Ford Mustang", "Laura Kim", "Ben Ortiz", "$1,300", "$1,375", "Eastside Soccer League"),
    ("my uncle Farid", "Farid's", "Orange", "Free Mobile", "Renault Clio", "Citroën C4", "Nadia Haddad", "Paul Girard", "€750", "€820", "Lyon Cycling Club"),
    ("my coworker Mei", "Mei's", "Jio", "Airtel", "Maruti Swift", "Tata Nexon", "Arjun Mehta", "Sara Thomas", "₹28,000", "₹31,500", "Koramangala Book Club"),
    ("my neighbour Tomasz", "Tomasz's", "Play", "Orange Polska", "Skoda Fabia", "Toyota Yaris", "Ewa Nowak", "Piotr Zielinski", "3,100 zł", "3,400 zł", "Wawel Tennis Club"),
]
ZH = [
    ("我", "我", "中国移动", "中国联通", "比亚迪秦", "特斯拉Model Y", "刘洋", "周婷", "4500元", "5200元", "西湖读书会"),
    ("我", "我", "中国电信", "中国移动", "大众朗逸", "理想L7", "王磊", "陈静怡", "3800元", "4100元", "东湖羽毛球俱乐部"),
    ("我", "我", "中国联通", "中国广电", "丰田卡罗拉", "小鹏P7", "赵敏", "孙浩", "6000元", "6800元", "南山登山队"),
    ("我", "我", "中国移动", "中国电信", "本田思域", "蔚来ET5", "黄磊", "林晓", "2900元", "3300元", "滨江合唱团"),
    ("我", "我", "中国电信", "中国联通", "吉利帝豪", "极氪001", "郑凯", "何雪", "5100元", "5600元", "钟楼摄影社"),
    ("我姐姐小慧", "小慧", "中国联通", "中国移动", "长安CS75", "比亚迪汉", "马超", "李娜", "3500元", "3900元", "江南茶艺社"),
    ("我室友阿杰", "阿杰", "中国移动", "中国广电", "日产轩逸", "问界M7", "冯涛", "曹丽", "2600元", "2850元", "城北篮球队"),
    ("我舅舅老陈", "老陈", "中国电信", "中国移动", "别克英朗", "红旗H5", "杜鹏", "邓佳", "4200元", "4600元", "老年书法协会"),
    ("我同事雅雯", "雅雯", "中国联通", "中国电信", "马自达3", "零跑C11", "蒋文", "沈悦", "7200元", "7900元", "滨海游泳俱乐部"),
    ("我邻居大刘", "大刘", "中国移动", "中国联通", "现代伊兰特", "哪吒V", "田野", "罗欣", "3100元", "3450元", "社区围棋社"),
]
EN_FILLER = [("Any idea how long to boil an egg for a runny yolk?", "About six and a half minutes from boiling, then into cold water."),
             ("What's a polite way to decline a meeting?", "Thank them, say you can't make it, and offer an alternative time."),
             ("How often should I water a snake plant?", "Every two to three weeks; let the soil dry out completely."),
             ("Can you recommend a podcast about history?", "Try one that covers a single event per episode; they're easy to follow.")]
ZH_FILLER = [("煮溏心蛋要多久？", "水开后六分半，然后放进冷水里。"),
             ("怎么委婉地拒绝一个会议？", "先感谢邀请，说明时间冲突，再提出另一个时间。"),
             ("虎尾兰多久浇一次水？", "两到三周一次，等土完全干了再浇。"),
             ("推荐一个历史类的播客吧。", "可以找每期讲一个事件的，比较容易听下去。")]

EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]


def sessions(k: int) -> tuple[int, list[tuple[int, int, int]]]:
    year = 2022 + k % 3
    shift = k % 4
    return year, [(year, 2, 3 + shift), (year, 4, 11 + shift), (year, 5, 20 + shift), (year, 7, 8 + shift),
                  (year, 9, 14 + shift), (year, 10, 25 + shift)]


def en_stream(k: int) -> dict:
    who, poss, c1, c2, car1, car2, m1, m2, r1, r2, club = EN[k]
    year, days = sessions(k)
    self_ = who == "I"
    name = who.split()[-1]
    if self_:
        lines = [f"Just signed up with {c1} for my phone and joined the {club}. My manager at work is {m1}.",
                 f"My rent here is {r1} a month, which is fine for now. I'm driving a {car1} these days.",
                 f"Switched my phone over to {c2} this morning, the coverage is better.",
                 f"Sold the old car and picked up a {car2}. Also, {m2} is my manager now after the reshuffle.",
                 f"The landlord sent the renewal: rent goes to {r2} a month from now on."]
    else:
        lines = [f"{who[0].upper() + who[1:]} just signed up with {c1} for a phone plan and joined the {club}. "
                 f"{name}'s manager is {m1}.",
                 f"{name} pays {r1} a month in rent and drives a {car1}.",
                 f"{name} switched phone carriers to {c2} this morning; better coverage.",
                 f"{name} sold the old car and bought a {car2}. {m2} is {name}'s manager now after a reshuffle.",
                 f"{name}'s landlord sent the renewal: the rent goes to {r2} a month from now on."]
    filler = [EN_FILLER[k % 4], EN_FILLER[(k + 2) % 4]]
    texts = [(lines[0], "Nice, sounds like a busy week."), filler[0], (lines[1], "Good to know."),
             (lines[2], "Glad it's working out."), (lines[3], "Congrats on the new car!"), (lines[4], "Thanks for the update.")]
    texts = [texts[0], texts[2], texts[3], texts[4], texts[5], texts[1]]
    adds = [[{"role": "user", "content": u, "timestamp": ms(*days[i])},
             {"role": "assistant", "content": a, "timestamp": ms(*days[i], 1)}] for i, (u, a) in enumerate(texts)]
    # Session days: 0 carrier1/club/manager1, 1 rent1/car1, 2 carrier2, 3 car2/manager2, 4 rent2, 5 filler.
    d = days
    fmt = [lambda y, m, dd: f"{EN_MONTHS[m - 1]} {dd}, {y}",
           lambda y, m, dd: f"{dd} {EN_MONTHS[m - 1]} {y}",
           lambda y, m, dd: f"{y}/{m:02d}/{dd:02d}",
           lambda y, m, dd: f"{EN_MONTHS[m - 1][:3]}. {dd}, {y}"][k % 4]
    mid = lambda a, b: (a[0], a[1], min(28, a[2] + 10)) if a[1] != b[1] else a  # noqa: E731
    did = "was I" if self_ else f"was {name}"
    qs = [(f"Which phone carrier {did} with on {fmt(*mid(d[0], d[2]))}?", c1, True),
          (f"By {fmt(*mid(d[2], d[3]))}, what car {'did I' if self_ else f'did {name}'} drive?", car1, True),
          (f"Who was {poss} manager on {fmt(*mid(d[1], d[3]))}?", m1, True),
          (f"How much was {poss} monthly rent as of {fmt(*mid(d[3], d[4]))}?", r1, True),
          (f"What car {'was I' if self_ else f'was {name}'} driving in {EN_MONTHS[d[4][1] - 1]} {year}?", car2, True),
          (f"Which phone carrier {'am I' if self_ else f'is {name}'} with now?", c2, False)]
    return _stream(f"syn2-en-{k}", adds, qs)


def zh_stream(k: int) -> dict:
    who, poss, c1, c2, car1, car2, m1, m2, r1, r2, club = ZH[k]
    year, days = sessions(k + 1)
    self_ = who == "我"
    x = "我" if self_ else poss
    lines = [f"{who}刚办了{c1}的手机卡，还加入了{club}。{x}的领导是{m1}。",
             f"{x}现在每月房租{r1}，平时开一辆{car1}。",
             f"{x}今天早上把手机号转到{c2}了，信号好多了。",
             f"{x}把旧车卖了，换了一辆{car2}。部门调整以后，{x}的领导换成了{m2}。",
             f"房东发来续约合同，{x}的房租从现在起涨到每月{r2}。"]
    texts = [(lines[0], "听起来这周挺忙的。"), (lines[1], "了解了。"), (lines[2], "那就好。"),
             (lines[3], "恭喜换新车！"), (lines[4], "谢谢告诉我。"), ZH_FILLER[k % 4]]
    adds = [[{"role": "user", "content": u, "timestamp": ms(*days[i])},
             {"role": "assistant", "content": a, "timestamp": ms(*days[i], 1)}] for i, (u, a) in enumerate(texts)]
    d = days
    mid = lambda a, b: (a[0], a[1], min(28, a[2] + 10)) if a[1] != b[1] else a  # noqa: E731
    day = lambda t: f"{t[0]}年{t[1]}月{t[2]}日"  # noqa: E731
    qs = [(f"{day(mid(d[0], d[2]))}那天，{x}用的是哪家运营商？", c1, True),
          (f"到{day(mid(d[2], d[3]))}为止，{x}开的是什么车？", car1, True),
          (f"{day(mid(d[1], d[3]))}的时候，{x}的领导是谁？", m1, True),
          (f"截至{day(mid(d[3], d[4]))}，{x}每月房租是多少？", r1, True),
          (f"{year}年{d[4][1]}月，{x}开的是什么车？", car2, True),
          (f"{x}现在用的是哪家运营商？", c2, False)]
    return _stream(f"syn2-zh-{k}", adds, qs)


def _stream(sid: str, adds: list, qs: list) -> dict:
    lang = sid.split("-")[1]
    return {"id": sid, "adds": adds,
            "questions": [{"id": f"{sid}:q{i}", "question": q, "gold_answer": g,
                           "group": f"syn2-{lang}-{'dated' if dated else 'now'}", "dated": dated}
                          for i, (q, g, dated) in enumerate(qs)]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tempreason", required=True)
    parser.add_argument("--smoke", required=True, help="the smoke's asof_streams.json (ids to exclude)")
    parser.add_argument("--out", required=True)
    parser.add_argument("--n-l2", type=int, default=200)
    parser.add_argument("--n-l3", type=int, default=100)
    args = parser.parse_args()
    smoke = json.loads(Path(args.smoke).read_text(encoding="utf-8"))
    used = {q["id"].split(":", 1)[1] for s in smoke["tr_l2"] for q in s["questions"]}
    used |= {q["id"].split(":", 1)[1] for q in smoke["tr_l3_questions"]}
    data = Path(args.tempreason)
    out = {"tr_l2": tempreason(data / "test_l2.json", args.n_l2, "tr2-l2", used),
           "tr_l3": tempreason(data / "test_l3.json", args.n_l3, "tr2-l3", used),
           "synthetic": [en_stream(k) for k in range(len(EN))] + [zh_stream(k) for k in range(len(ZH))]}
    overlap = {s["id"].split(":", 1)[1] for s in out["tr_l2"] + out["tr_l3"]} & used
    assert not overlap, overlap
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"tr_l2 {len(out['tr_l2'])}, tr_l3 {len(out['tr_l3'])}, synthetic {len(out['synthetic'])} streams / "
          f"{sum(len(s['questions']) for s in out['synthetic'])} questions; {len(used)} smoke ids excluded")


if __name__ == "__main__":
    main()
