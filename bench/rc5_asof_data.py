#!/usr/bin/env python3
"""rc5 validation data for language-neutral as-of selection
(bench/results/rc5_language_neutral_preregistration.md).

    python3 bench/rc5_asof_data.py --tempreason DIR --exclude SMOKE.json RC4.json --out STREAMS.json

* TempReason L2 / L3 (public, not committed): fresh samples excluding every id
  the 2026-10-05 smoke and the rc4 study used. One user per question; its
  fact_context sentences are Added as user turns of one session stamped
  2024-06-01, as before.
* Synthetic dated profiles in English, French, German, Spanish, Chinese and
  Japanese (8 streams each), with attributes and wording used nowhere before
  (internet provider, bank, neighbourhood, personal trainer). Values are stated
  without years and without correction words. Five dated as-of questions and
  one "now" question per stream. The question dates rotate through three
  forms per language: month name with digits, entirely in words, and a native
  numeric form (US/EU numerals, 二〇二三年 / 二零二三年…号, Japanese era 令和).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
from pathlib import Path

SEED = 20261007


def ms(day: dt.date, minute: int = 0) -> int:
    return int(dt.datetime(day.year, day.month, day.day, 9, minute, tzinfo=dt.timezone.utc).timestamp() * 1000)


def tempreason(path: Path, n: int, label: str, exclude: set[str]) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [row for row in rows if row["id"] not in exclude]
    sample = random.Random(SEED).sample(rows, n)
    streams = []
    for row in sample:
        facts = [f.strip() for f in row["fact_context"].split("\n") if f.strip()]
        messages = [{"role": "user", "content": f, "timestamp": ms(dt.date(2024, 6, 1), i % 60)}
                    for i, f in enumerate(facts)]
        streams.append({"id": f"{label}:{row['id']}", "adds": [messages],
                        "questions": [{"id": f"{label}:{row['id']}", "question": row["question"],
                                       "gold_answer": " or ".join(row["text_answers"]["text"]),
                                       "group": label, "dated": True}]})
    return streams


# --- numbers and dates in words -----------------------------------------------------------
EN_ORD = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "eleventh",
          "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth", "nineteenth",
          "twentieth"] + [f"twenty-{o}" for o in ["first", "second", "third", "fourth", "fifth", "sixth", "seventh",
                                                   "eighth", "ninth"]] + ["thirtieth", "thirty-first"]
EN_YEAR = {2022: "two thousand twenty-two", 2023: "two thousand twenty-three", 2024: "two thousand twenty-four",
           2025: "two thousand twenty-five"}
EN_MON = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
FR_NUM = ["premier", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix", "onze", "douze", "treize",
          "quatorze", "quinze", "seize", "dix-sept", "dix-huit", "dix-neuf", "vingt", "vingt et un", "vingt-deux",
          "vingt-trois", "vingt-quatre", "vingt-cinq", "vingt-six", "vingt-sept", "vingt-huit", "vingt-neuf", "trente",
          "trente et un"]
FR_YEAR = {y: "deux mille " + w for y, w in zip(range(2022, 2026), ["vingt-deux", "vingt-trois", "vingt-quatre",
                                                                    "vingt-cinq"])}
FR_MON = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre",
          "décembre"]
DE_ORD = ["ersten", "zweiten", "dritten", "vierten", "fünften", "sechsten", "siebten", "achten", "neunten", "zehnten",
          "elften", "zwölften", "dreizehnten", "vierzehnten", "fünfzehnten", "sechzehnten", "siebzehnten",
          "achtzehnten", "neunzehnten", "zwanzigsten"] + [f"{u}undzwanzigsten" for u in
                                                         ["ein", "zwei", "drei", "vier", "fünf", "sechs", "sieben",
                                                          "acht", "neun"]] + ["dreißigsten", "einunddreißigsten"]
DE_YEAR = {y: "zweitausend" + w for y, w in zip(range(2022, 2026), ["zweiundzwanzig", "dreiundzwanzig",
                                                                   "vierundzwanzig", "fünfundzwanzig"])}
DE_MON = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November",
          "Dezember"]
ES_NUM = ["primero", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce", "trece",
          "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte", "veintiuno", "veintidós",
          "veintitrés", "veinticuatro", "veinticinco", "veintiséis", "veintisiete", "veintiocho", "veintinueve",
          "treinta", "treinta y uno"]
ES_YEAR = {y: "dos mil " + w for y, w in zip(range(2022, 2026), ["veintidós", "veintitrés", "veinticuatro",
                                                                "veinticinco"])}
ES_MON = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre"]
CJK_DIGIT = "〇一二三四五六七八九"


def cjk_small(n: int) -> str:
    """1..31 in Chinese/Japanese numerals (十四, 二十一, 三十)."""
    tens, ones = divmod(n, 10)
    return (("" if tens == 0 else ("十" if tens == 1 else CJK_DIGIT[tens] + "十"))
            + ("" if ones == 0 else CJK_DIGIT[ones])) or "〇"


def cjk_year(year: int, zero: str = "〇") -> str:
    return "".join(zero if c == "0" else CJK_DIGIT[int(c)] for c in str(year))


def day_text(lang: str, day: dt.date, form: int) -> str:
    y, m, d = day.year, day.month, day.day
    if lang == "en":
        return [f"{EN_MON[m - 1]} {d}, {y}", f"the {EN_ORD[d - 1]} of {EN_MON[m - 1]}, {EN_YEAR[y]}",
                f"{m}/{d}/{y}"][form]
    if lang == "fr":
        return [f"le {d} {FR_MON[m - 1]} {y}", f"le {FR_NUM[d - 1]} {FR_MON[m - 1]} {FR_YEAR[y]}",
                f"le {d:02d}/{m:02d}/{y}"][form]
    if lang == "de":
        return [f"am {d}. {DE_MON[m - 1]} {y}", f"am {DE_ORD[d - 1]} {DE_MON[m - 1]} {DE_YEAR[y]}",
                f"am {d:02d}.{m:02d}.{y}"][form]
    if lang == "es":
        return [f"el {d} de {ES_MON[m - 1]} de {y}", f"el {ES_NUM[d - 1]} de {ES_MON[m - 1]} de {ES_YEAR[y]}",
                f"el {d:02d}/{m:02d}/{y}"][form]
    if lang == "zh":
        return [f"{y}年{m}月{d}日", f"{cjk_year(y)}年{cjk_small(m)}月{cjk_small(d)}日",
                f"{cjk_year(y, '零')}年{cjk_small(m)}月{cjk_small(d)}号"][form]
    if lang == "ja":
        return [f"{y}年{m}月{d}日", f"{cjk_year(y)}年{cjk_small(m)}月{cjk_small(d)}日",
                f"令和{y - 2018}年{m}月{d}日"][form]
    raise ValueError(lang)


def month_text(lang: str, day: dt.date, form: int) -> str:
    y, m = day.year, day.month
    return {"en": [f"in {EN_MON[m - 1]} {y}", f"in {EN_MON[m - 1]} of {EN_YEAR[y]}"],
            "fr": [f"en {FR_MON[m - 1]} {y}", f"en {FR_MON[m - 1]} {FR_YEAR[y]}"],
            "de": [f"im {DE_MON[m - 1]} {y}", f"im {DE_MON[m - 1]} {DE_YEAR[y]}"],
            "es": [f"en {ES_MON[m - 1]} de {y}", f"en {ES_MON[m - 1]} de {ES_YEAR[y]}"],
            "zh": [f"{y}年{m}月", f"{cjk_year(y)}年{cjk_small(m)}月"],
            "ja": [f"{y}年{m}月", f"令和{y - 2018}年{m}月"]}[lang][form]


# --- profiles -------------------------------------------------------------------------------
# (isp1, isp2, bank1, bank2, hood1, hood2, coach1, coach2) per stream
VALUES = {
    "en": [("Xfinity", "Google Fiber", "Chase", "Ally Bank", "Ballard", "Capitol Hill", "Derek Moss", "Tanya Shah"),
           ("Spectrum", "Starlink", "Wells Fargo", "Capital One", "Logan Square", "Wicker Park", "Mike Dunn", "Ana Ruiz"),
           ("Verizon Fios", "Optimum", "Citibank", "Discover Bank", "Astoria", "Park Slope", "Kayla Ford", "Ravi Nair"),
           ("Cox", "AT&T Fiber", "Bank of America", "SoFi", "South End", "Dilworth", "Jon Pratt", "Lena Fox"),
           ("Frontier", "Ziply Fiber", "US Bank", "Marcus", "Hawthorne", "Alberta Arts", "Cody Lane", "Mia Chen"),
           ("Sonic", "Comcast", "Schwab Bank", "Chime", "Mission District", "Noe Valley", "Greg Hall", "Iris Park"),
           ("Mediacom", "T-Mobile Home Internet", "PNC", "Axos Bank", "Highland", "Five Points", "Sean Wolfe",
            "Nora Bell"),
           ("RCN", "Verizon 5G Home", "TD Bank", "Varo", "Allston", "Jamaica Plain", "Paul Reyes", "Dana Lowe")],
    "fr": [("Free", "Bouygues Telecom", "Crédit Agricole", "Boursorama", "la Croix-Rousse", "Confluence", "Julien Morel",
            "Inès Garnier"),
           ("SFR", "Orange", "BNP Paribas", "Hello bank!", "Montmartre", "Belleville", "Karim Benali", "Chloé Petit"),
           ("Bouygues Telecom", "Free", "Société Générale", "Fortuneo", "les Chartrons", "Saint-Michel",
            "Thomas Roux", "Léa Fontaine"),
           ("Orange", "Red by SFR", "LCL", "Crédit Mutuel", "le Panier", "la Joliette", "Hugo Lambert", "Sarah Mercier"),
           ("Sosh", "Free", "La Banque Postale", "Caisse d'Épargne", "Vieux Lille", "Wazemmes", "Nicolas Blanc",
            "Manon Girard"),
           ("Free", "SFR", "CIC", "BforBank", "le Capitole", "Saint-Cyprien", "Antoine Faure", "Camille Robin"),
           ("Orange", "Bouygues Telecom", "Banque Populaire", "N26", "l'Île de Nantes", "Chantenay", "Yanis Haddad",
            "Julie Marchand"),
           ("SFR", "Free", "Crédit du Nord", "Monabanq", "la Petite France", "Neudorf", "Mathieu Perrin",
            "Elsa Vidal")],
    "de": [("Telekom", "Vodafone", "Sparkasse", "DKB", "Prenzlauer Berg", "Friedrichshain", "Jonas Weber", "Lena Braun"),
           ("Vodafone", "1&1", "Deutsche Bank", "ING", "Schwabing", "Haidhausen", "Felix Wagner", "Mia Hoffmann"),
           ("O2", "Telekom", "Commerzbank", "N26", "Ehrenfeld", "Sülz", "Lukas Becker", "Hannah Schulz"),
           ("1&1", "M-net", "Volksbank", "Comdirect", "Altona", "Eimsbüttel", "Tim Schäfer", "Laura Koch"),
           ("NetCologne", "Vodafone", "Postbank", "Consorsbank", "Nippes", "Deutz", "Jan Richter", "Sophie Klein"),
           ("Telekom", "O2", "Targobank", "C24 Bank", "Bornheim", "Sachsenhausen", "Paul Wolf", "Emma Neumann"),
           ("Vodafone", "Telekom", "HypoVereinsbank", "Tomorrow Bank", "Plagwitz", "Connewitz", "Leon Schwarz",
            "Marie Zimmermann"),
           ("M-net", "1&1", "Santander Deutschland", "Norisbank", "Gostenhof", "St. Johannis", "Max Krüger",
            "Clara Hartmann")],
    "es": [("Movistar", "Digi", "Santander", "BBVA", "Malasaña", "Lavapiés", "Javier Ortega", "Lucía Romero"),
           ("Vodafone", "MásMóvil", "CaixaBank", "ING", "Gràcia", "Poblenou", "Pablo Navarro", "Marta Gil"),
           ("Orange", "Movistar", "Sabadell", "Openbank", "Triana", "Los Remedios", "Diego Serrano", "Elena Molina"),
           ("Jazztel", "O2", "Bankinter", "Unicaja", "Ruzafa", "El Cabanyal", "Sergio Castro", "Paula Ortiz"),
           ("Digi", "Vodafone", "Abanca", "EVO Banco", "Casco Viejo", "Indautxu", "Álvaro Rubio", "Sara Delgado"),
           ("Movistar", "Orange", "Kutxabank", "Ibercaja", "Gros", "Amara", "Raúl Marín", "Nuria Vega"),
           ("Pepephone", "Lowi", "BBVA", "Revolut", "El Carmen", "Benimaclet", "Iván Herrera", "Laura Cano"),
           ("Simyo", "Movistar", "Cajamar", "Santander", "Chamberí", "Arganzuela", "Adrián Peña", "Irene Soto")],
    "zh": [("中国电信宽带", "长城宽带", "招商银行", "工商银行", "朝阳区望京", "海淀区五道口", "张伟", "李婷"),
           ("中国联通宽带", "中国移动宽带", "建设银行", "浦发银行", "浦东张江", "徐汇田林", "王强", "赵雪"),
           ("中国移动宽带", "广电宽带", "农业银行", "兴业银行", "天河珠江新城", "越秀东山口", "刘杰", "陈媛"),
           ("长城宽带", "中国电信宽带", "中国银行", "平安银行", "南山科技园", "福田香蜜湖", "杨帆", "周敏"),
           ("广电宽带", "中国联通宽带", "交通银行", "中信银行", "西湖文三路", "滨江长河", "黄涛", "吴倩"),
           ("中国电信宽带", "中国移动宽带", "民生银行", "招商银行", "武侯玉林", "锦江春熙路", "徐斌", "孙丽"),
           ("中国联通宽带", "长城宽带", "光大银行", "华夏银行", "鼓楼新街口", "建邺河西", "马骏", "朱琳"),
           ("中国移动宽带", "中国电信宽带", "工商银行", "宁波银行", "江北观音桥", "渝中解放碑", "胡磊", "郭静")],
    "ja": [("NTTフレッツ光", "auひかり", "三菱UFJ銀行", "楽天銀行", "世田谷区三軒茶屋", "目黒区中目黒", "佐藤健", "鈴木愛"),
           ("ソフトバンク光", "ドコモ光", "みずほ銀行", "住信SBIネット銀行", "吉祥寺", "中野", "高橋翔", "田中美咲"),
           ("ドコモ光", "NURO光", "三井住友銀行", "PayPay銀行", "梅田", "天王寺", "伊藤大輔", "渡辺結衣"),
           ("auひかり", "ビッグローブ光", "ゆうちょ銀行", "りそな銀行", "天神", "博多", "山本拓也", "中村彩"),
           ("NURO光", "NTTフレッツ光", "りそな銀行", "ソニー銀行", "栄", "大須", "小林誠", "加藤真由"),
           ("ビッグローブ光", "ソフトバンク光", "楽天銀行", "三菱UFJ銀行", "元町", "三宮", "吉田悠", "山田花子"),
           ("eo光", "ドコモ光", "京都銀行", "セブン銀行", "四条烏丸", "北白川", "松本亮", "井上舞"),
           ("ドコモ光", "auひかり", "横浜銀行", "auじぶん銀行", "みなとみらい", "日吉", "木村蓮", "林さくら")],
}
OTHERS = {"en": ["my brother Nate", "my friend Priyanka"], "fr": ["ma sœur Agathe", "mon ami Lucas"],
          "de": ["meine Schwester Anja", "mein Freund Tobias"], "es": ["mi hermana Carmen", "mi amigo Óscar"],
          "zh": ["我表哥阿强", "我朋友小美"], "ja": ["兄の健太", "友人の美穂"]}

FILLER = {"en": ("How long should I steep green tea?", "About two to three minutes at around 80 °C."),
          "fr": ("Combien de temps faut-il laisser infuser un thé vert ?", "Deux à trois minutes, vers 80 °C."),
          "de": ("Wie lange sollte grüner Tee ziehen?", "Etwa zwei bis drei Minuten bei rund 80 °C."),
          "es": ("¿Cuánto tiempo hay que dejar reposar el té verde?", "Unos dos o tres minutos a unos 80 °C."),
          "zh": ("绿茶应该泡多久？", "大约两到三分钟，水温八十度左右。"),
          "ja": ("緑茶はどのくらい蒸らせばいいですか？", "80度くらいのお湯で2〜3分が目安です。")}


def lines_for(lang: str, who: str | None, v: tuple) -> tuple[list[str], list[str]]:
    """(user statements for sessions 0-4, assistant replies). *who* None = the user."""
    isp1, isp2, bank1, bank2, hood1, hood2, coach1, coach2 = v
    if lang == "en":
        if who is None:
            u = [f"We finally got home internet set up through {isp1}, and I opened my checking account at {bank1}.",
                 f"I'm living in {hood1} at the moment, and my personal trainer is {coach1}.",
                 f"Our internet is with {isp2} now; I moved the contract over this morning.",
                 f"I moved my savings and checking to {bank2} today, and I've started training with {coach2}.",
                 f"Big news: I moved, I live in {hood2} now."]
        else:
            n = who.split()[-1]
            u = [f"{who[0].upper() + who[1:]} got home internet through {isp1} and banks at {bank1}.",
                 f"{n} lives in {hood1} and trains with a personal trainer named {coach1}.",
                 f"{n}'s internet is with {isp2} now; the contract moved over this morning.",
                 f"{n} moved all accounts to {bank2} today and started training with {coach2}.",
                 f"{n} moved and lives in {hood2} now."]
        a = ["Sounds like a productive week.", "Good to know.", "Hope the connection is faster.", "Nice change.",
             "Congratulations on the move!"]
    elif lang == "fr":
        if who is None:
            u = [f"On a enfin la box internet chez {isp1}, et j'ai ouvert mon compte courant au {bank1}.",
                 f"En ce moment j'habite à {hood1}, et mon coach sportif s'appelle {coach1}.",
                 f"Notre internet est chez {isp2} maintenant, j'ai transféré l'abonnement ce matin.",
                 f"J'ai transféré tous mes comptes chez {bank2} aujourd'hui, et je m'entraîne avec {coach2}.",
                 f"Grande nouvelle : j'ai déménagé, j'habite à {hood2} maintenant."]
        else:
            n = who.split()[-1]
            u = [f"{who[0].upper() + who[1:]} a pris sa box internet chez {isp1} et a son compte au {bank1}.",
                 f"{n} habite à {hood1} et s'entraîne avec un coach qui s'appelle {coach1}.",
                 f"L'internet de {n} est chez {isp2} maintenant ; l'abonnement a été transféré ce matin.",
                 f"{n} a transféré tous ses comptes chez {bank2} aujourd'hui et s'entraîne avec {coach2}.",
                 f"{n} a déménagé et habite à {hood2} maintenant."]
        a = ["Belle semaine !", "C'est noté.", "J'espère que la connexion est meilleure.", "Beau changement.",
             "Félicitations pour le déménagement !"]
    elif lang == "de":
        if who is None:
            u = [f"Wir haben endlich Internet über {isp1}, und ich habe mein Girokonto bei der {bank1} eröffnet.",
                 f"Ich wohne gerade in {hood1}, und mein Personal Trainer ist {coach1}.",
                 f"Unser Internet läuft jetzt über {isp2}; ich habe den Vertrag heute Morgen umgestellt.",
                 f"Ich habe heute alle Konten zur {bank2} verlegt und trainiere jetzt mit {coach2}.",
                 f"Große Neuigkeit: Ich bin umgezogen und wohne jetzt in {hood2}."]
        else:
            n = who.split()[-1]
            u = [f"{who[0].upper() + who[1:]} hat Internet über {isp1} und ein Konto bei der {bank1}.",
                 f"{n} wohnt in {hood1} und trainiert mit einem Personal Trainer namens {coach1}.",
                 f"{n}s Internet läuft jetzt über {isp2}; der Vertrag wurde heute Morgen umgestellt.",
                 f"{n} hat heute alle Konten zur {bank2} verlegt und trainiert jetzt mit {coach2}.",
                 f"{n} ist umgezogen und wohnt jetzt in {hood2}."]
        a = ["Klingt nach einer vollen Woche.", "Gut zu wissen.", "Hoffentlich ist es schneller.",
             "Schöne Veränderung.", "Glückwunsch zum Umzug!"]
    elif lang == "es":
        if who is None:
            u = [f"Por fin tenemos internet en casa con {isp1}, y abrí mi cuenta corriente en {bank1}.",
                 f"Ahora mismo vivo en {hood1}, y mi entrenador personal es {coach1}.",
                 f"Nuestro internet es de {isp2} ahora; cambié el contrato esta mañana.",
                 f"Hoy pasé todas mis cuentas a {bank2} y empecé a entrenar con {coach2}.",
                 f"Gran noticia: me mudé, ahora vivo en {hood2}."]
        else:
            n = who.split()[-1]
            u = [f"{who[0].upper() + who[1:]} tiene internet con {isp1} y su cuenta en {bank1}.",
                 f"{n} vive en {hood1} y entrena con un entrenador personal llamado {coach1}.",
                 f"El internet de {n} es de {isp2} ahora; cambiaron el contrato esta mañana.",
                 f"{n} pasó todas sus cuentas a {bank2} hoy y empezó a entrenar con {coach2}.",
                 f"{n} se mudó y ahora vive en {hood2}."]
        a = ["¡Qué semana!", "Entendido.", "Ojalá vaya más rápido.", "Buen cambio.", "¡Enhorabuena por la mudanza!"]
    elif lang == "zh":
        x = "我" if who is None else who
        y = "我" if who is None else who[-2:]
        u = [f"{x}家终于装好了{isp1}，{y}还在{bank1}开了工资卡。",
             f"{y}现在住在{hood1}，{y}的私人教练是{coach1}。",
             f"{y}家的宽带现在是{isp2}了，今天早上办好的。",
             f"{y}今天把存款和工资卡都转到了{bank2}，现在跟{coach2}练。",
             f"大消息：{y}搬家了，现在住在{hood2}。"]
        a = ["这周挺充实的。", "知道了。", "希望网速快一点。", "不错的变化。", "恭喜乔迁！"]
    else:  # ja
        x = "私" if who is None else who
        y = "私" if who is None else who.split("の")[-1]
        u = [f"{x}の家はやっと{isp1}でネットがつながって、{bank1}で口座も開きました。",
             f"{y}は今{hood1}に住んでいて、パーソナルトレーナーは{coach1}さんです。",
             f"{y}の家のネットは今{isp2}です。今朝契約を切り替えました。",
             f"{y}は今日、口座を全部{bank2}に移して、{coach2}さんとトレーニングを始めました。",
             f"大ニュース：{y}は引っ越して、今は{hood2}に住んでいます。"]
        a = ["充実した一週間ですね。", "了解です。", "速くなるといいですね。", "いい変化ですね。", "引っ越しおめでとう！"]
    return u, a


def questions_for(lang: str, who: str | None, dates: list[str], month: str) -> list[str]:
    """Five dated questions (dates[0..3] are day phrases, *month* a month phrase) and one 'now' question."""
    if lang == "en":
        p, s = ("my", "I") if who is None else (who.split()[-1] + "'s", who.split()[-1])
        did = "did I" if who is None else f"did {s}"
        was = "was I" if who is None else f"was {s}"
        return [f"Which internet provider {did} have on {dates[0]}?", f"As of {dates[1]}, where {did} bank?",
                f"Who was {p} personal trainer on {dates[2]}?", f"Which neighborhood {was} living in on {dates[3]}?",
                f"Who provided {p} internet {month}?",
                f"Which neighborhood {'do I' if who is None else f'does {s}'} live in now?"]
    if lang == "fr":
        n = None if who is None else who.split()[-1]
        return [f"Quel fournisseur d'accès internet {'avais-je' if n is None else f'{n} avait-il'} {dates[0]} ?",
                f"Dans quelle banque {'étais-je' if n is None else f'{n} était-il'} {dates[1]} ?",
                f"Qui était {'mon' if n is None else f'le'} coach sportif{'' if n is None else f' de {n}'} {dates[2]} ?",
                f"Dans quel quartier {'habitais-je' if n is None else f'{n} habitait-il'} {dates[3]} ?",
                f"Chez qui était {'ma' if n is None else 'la'} connexion internet{'' if n is None else f' de {n}'} {month} ?",
                f"Dans quel quartier {'est-ce que j’habite' if n is None else f'{n} habite-t-il'} maintenant ?"]
    if lang == "de":
        n = None if who is None else who.split()[-1]
        return [f"Welchen Internetanbieter {'hatte ich' if n is None else f'hatte {n}'} {dates[0]}?",
                f"Bei welcher Bank {'war ich' if n is None else f'war {n}'} {dates[1]}?",
                f"Wer war {'mein' if n is None else f'{n}s'} Personal Trainer {dates[2]}?",
                f"In welchem Viertel {'wohnte ich' if n is None else f'wohnte {n}'} {dates[3]}?",
                f"Über wen lief {'mein' if n is None else f'{n}s'} Internet {month}?",
                f"In welchem Viertel {'wohne ich' if n is None else f'wohnt {n}'} jetzt?"]
    if lang == "es":
        n = None if who is None else who.split()[-1]
        return [f"¿Qué proveedor de internet {'tenía yo' if n is None else f'tenía {n}'} {dates[0]}?",
                f"¿En qué banco {'tenía mis cuentas' if n is None else f'tenía {n} sus cuentas'} {dates[1]}?",
                f"¿Quién era {'mi' if n is None else f'el'} entrenador personal{'' if n is None else f' de {n}'} {dates[2]}?",
                f"¿En qué barrio {'vivía yo' if n is None else f'vivía {n}'} {dates[3]}?",
                f"¿Quién {'me' if n is None else f'le'} daba internet{'' if n is None else f' a {n}'} {month}?",
                f"¿En qué barrio {'vivo' if n is None else f'vive {n}'} ahora?"]
    if lang == "zh":
        y = "我" if who is None else who[-2:]
        return [f"{dates[0]}那天，{y}家用的是哪家宽带？", f"截至{dates[1]}，{y}的存款在哪家银行？",
                f"{dates[2]}的时候，{y}的私人教练是谁？", f"{dates[3]}，{y}住在哪里？",
                f"{month}，{y}家的宽带是哪家的？", f"{y}现在住在哪里？"]
    y = "私" if who is None else who.split("の")[-1]
    return [f"{dates[0]}の時点で、{y}の家のネット回線はどこでしたか？", f"{dates[1]}の時点で、{y}の口座はどの銀行にありましたか？",
            f"{dates[2]}に、{y}のパーソナルトレーナーは誰でしたか？", f"{dates[3]}、{y}はどこに住んでいましたか？",
            f"{month}、{y}の家のネットはどこの回線でしたか？", f"{y}は今どこに住んでいますか？"]


def synthetic(lang: str, k: int) -> dict:
    v = VALUES[lang][k]
    who = None if k < 6 else OTHERS[lang][k - 6]
    year = 2022 + k % 4
    shift = k % 5
    days = [dt.date(year, 2, 3 + shift), dt.date(year, 4, 11 + shift), dt.date(year, 5, 20 + shift),
            dt.date(year, 7, 8 + shift), dt.date(year, 9, 14 + shift), dt.date(year, 10, 25 + shift)]
    u, a = lines_for(lang, who, v)
    texts = list(zip(u, a)) + [FILLER[lang]]
    adds = [[{"role": "user", "content": uu, "timestamp": ms(days[i])},
             {"role": "assistant", "content": aa, "timestamp": ms(days[i], 1)}] for i, (uu, aa) in enumerate(texts)]
    later = lambda d, n=10: d + dt.timedelta(days=n)  # noqa: E731 - strictly between two sessions
    asked = [later(days[0]), later(days[2]), later(days[1]), later(days[3])]
    phrases = [day_text(lang, day, (k + i) % 3) for i, day in enumerate(asked)]
    month = month_text(lang, days[4], k % 2)
    isp1, isp2, bank1, bank2, hood1, hood2, coach1, coach2 = v
    golds = [isp1, bank1, coach1, hood1, isp2, hood2]
    qs = questions_for(lang, who, phrases, month)
    sid = f"syn5-{lang}-{k}"
    return {"id": sid, "adds": adds,
            "questions": [{"id": f"{sid}:q{i}", "question": q, "gold_answer": g, "lang": lang,
                           "form": ["digits", "words", "native"][(k + i) % 3] if i < 4 else
                           ("month-digits" if k % 2 == 0 else "month-words") if i == 4 else "now",
                           "group": f"syn5-{lang}-{'dated' if i < 5 else 'now'}", "dated": i < 5}
                          for i, (q, g) in enumerate(zip(qs, golds))]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tempreason", required=True)
    parser.add_argument("--exclude", nargs="+", required=True, help="earlier streams files (smoke, rc4)")
    parser.add_argument("--out", required=True)
    parser.add_argument("--n-l2", type=int, default=150)
    parser.add_argument("--n-l3", type=int, default=100)
    args = parser.parse_args()
    used: set[str] = set()
    for path in args.exclude:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for key in ("tr_l2", "tr_l3"):
            used |= {q["id"].split(":", 1)[1] for s in data.get(key, []) for q in s["questions"]}
        used |= {q["id"].split(":", 1)[1] for q in data.get("tr_l3_questions", [])}
    root = Path(args.tempreason)
    out = {"tr_l2": tempreason(root / "test_l2.json", args.n_l2, "tr5-l2", used),
           "tr_l3": tempreason(root / "test_l3.json", args.n_l3, "tr5-l3", used),
           "synthetic": [synthetic(lang, k) for lang in VALUES for k in range(8)]}
    overlap = {s["id"].split(":", 1)[1] for s in out["tr_l2"] + out["tr_l3"]} & used
    assert not overlap, overlap
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"tr_l2 {len(out['tr_l2'])}, tr_l3 {len(out['tr_l3'])}, synthetic {len(out['synthetic'])} streams / "
          f"{sum(len(s['questions']) for s in out['synthetic'])} questions; {len(used)} earlier ids excluded")


if __name__ == "__main__":
    main()
