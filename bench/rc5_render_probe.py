#!/usr/bin/env python3
"""rc5 render-language probe (bench/results/rc5_language_neutral_preregistration.md, B.3).

24 explicit updates written for this probe (en, fr, de, es, zh, ja; 4 each),
each a two-turn chunk (an assistant line, then the user's update). Stage 1 and
stage 2 run in-process (app.updates.detect_or_none, gpt-4o-mini through the
proxy); for every record the probe reports the two language tags, whether
renderable() accepts it, and -- a bench-side check, not in the service -- a
separate gpt-4o-mini verdict on whether the rendered sentence is in the same
language as the user's turn.

    python3 bench/rc5_render_probe.py --out FILE
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

PROBES = {
    "en": ["Correction: my dentist appointment is on Thursday, not Tuesday.",
           "Please change my emergency contact to my brother Daniel.",
           "Update: my locker number is 214 now, not 118.",
           "I gave you the wrong postcode earlier — it's 90210."],
    "fr": ["Correction : mon rendez-vous chez le dentiste est jeudi, pas mardi.",
           "Merci de changer mon contact d'urgence : c'est mon frère Daniel maintenant.",
           "Mise à jour : mon numéro de casier est désormais le 214, plus le 118.",
           "Je t'ai donné le mauvais code postal tout à l'heure, c'est 69004."],
    "de": ["Korrektur: Mein Zahnarzttermin ist am Donnerstag, nicht am Dienstag.",
           "Bitte ändere meinen Notfallkontakt auf meinen Bruder Daniel.",
           "Aktualisierung: Meine Schließfachnummer ist jetzt 214, nicht mehr 118.",
           "Ich habe dir vorhin die falsche Postleitzahl gegeben, sie lautet 80331."],
    "es": ["Corrección: mi cita con el dentista es el jueves, no el martes.",
           "Por favor, cambia mi contacto de emergencia a mi hermano Daniel.",
           "Actualización: mi número de taquilla ahora es el 214, ya no el 118.",
           "Antes te di mal el código postal, es el 28013."],
    "zh": ["更正一下：我的牙医预约是周四，不是周二。",
           "请把我的紧急联系人改成我哥哥丹尼尔。",
           "更新：我的储物柜号码现在是214，不是118了。",
           "我刚才把邮编说错了，应该是200031。"],
    "ja": ["訂正です：歯医者の予約は火曜日ではなく木曜日です。",
           "緊急連絡先を兄のダニエルに変更してください。",
           "更新：ロッカー番号は118ではなく、今は214です。",
           "さっき郵便番号を間違えました。正しくは150-0002です。"],
}
CHECK = ("Answer with one word, yes or no: is sentence B written in the same language as sentence A?\n"
         "A: {a}\nB: {b}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    from app import store, updates
    from rc4_study import complete

    def one(job):
        lang, number, text = job
        digest = f"{abs(hash((lang, number))) % 16**16:016x}"
        items = [store.Item(id=f"{digest}-r0", kind="raw", parent_id=None,
                            content="[2025-03-02 10:00] Assistant: Noted, I have saved that.", created_at=None),
                 store.Item(id=f"{digest}-r1", kind="raw", parent_id=None,
                            content=f"[2025-03-02 10:01] I: {text}", created_at=None)]
        records = updates.detect_or_none(items) or []
        out = []
        for record in records:
            rendered = updates.renderable(record, items[1].content)
            verdict = None
            if record.get("statement"):
                verdict = complete(CHECK.format(a=text, b=record["statement"]), "rc5-render-check", 5)
            out.append({"lang": lang, "probe": number, "turn": text, "statement": record.get("statement"),
                        "statement_language": record.get("statement_language"),
                        "current_language": record.get("current_language"), "renderable": rendered,
                        "same_language_check": (verdict or "").strip().lower().startswith("yes"),
                        "subject": record["subject"], "relative": record["relative"]})
        return out or [{"lang": lang, "probe": number, "turn": text, "statement": None, "renderable": False}]

    jobs = [(lang, n, text) for lang, texts in PROBES.items() for n, text in enumerate(texts)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = [row for result in pool.map(one, jobs) for row in result]
    Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    for lang in PROBES:
        sub = [r for r in rows if r["lang"] == lang]
        recs = [r for r in sub if r.get("statement")]
        print(f"{lang}: records {len(recs)}/{len(PROBES[lang])}; rendered {sum(r['renderable'] for r in recs)}; "
              f"tags equal {sum(r.get('statement_language') == r.get('current_language') for r in recs)}; "
              f"check says same language {sum(r['same_language_check'] for r in recs)}; "
              f"rendered but check says different {sum(r['renderable'] and not r['same_language_check'] for r in recs)}")


if __name__ == "__main__":
    main()
