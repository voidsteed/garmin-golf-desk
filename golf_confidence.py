"""Role-specific recorded success/miss counts; not a universal club-quality score."""

import math

from golf_game import full_game_snapshot
from golf_history import summarize_series

ROLES = ("Approaches","Tee fairways","Wedge chips","Putting")
MIN_CLASSIFIED_SHOTS = 10


def wilson_interval(hits,total):
    if not total:
        return None,None
    z=1.959963984540054
    p=hits/total
    denominator=1+z*z/total
    center=(p+z*z/(2*total))/denominator
    radius=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/denominator
    return max(0,100*(center-radius)),min(100,100*(center+radius))


def club_confidence(model,rounds,role="Approaches",show_empty=False):
    if role not in ROLES:
        raise ValueError("Choose a shot role.")
    game=full_game_snapshot(model,rounds)
    raw=[]
    if role=="Approaches":
        analysis=model.approach_analysis(rounds)
        raw=[{"id":r["id"],"hits":r["green"],"misses":r["miss"],"unknown":r["unknown"]} for r in analysis["clubs"]]
        definition="Hit = on-green approach finish; miss = known off-green finish. Not the same as GIR or strokes gained."
    elif role=="Tee fairways":
        raw=[{"id":r["id"],"hits":r["hit"],"misses":r["left"]+r["right"],"unknown":r["unknown"]} for r in game["tee"] if r["fw_recorded"] or r["unknown"]]
        definition="Hit = recorded fairway on a par-4/5; miss = left/right. Par-3 tees and ambiguous re-tees are not fairway attempts."
    elif role=="Wedge chips":
        raw=[{"id":r["id"],"hits":r["chip"]["green"],"misses":r["chip"]["miss"],"unknown":r["chip"]["unknown"]} for r in game["wedges"] if r["chip"]["shots"]]
        definition="Hit = chip finishes on green; miss = known off-green finish. This does not measure up-and-down success."
    else:
        putter=next((key for key,c in model.clubs.items() if str(c.get("clubTypeId"))=="23" and not c.get("retired") and not c.get("deleted")),None)
        raw=[{"id":putter or "putter","hits":sum(r["one"]+r["two"] for r in game["putting"]),"misses":sum(r["three_plus"] for r in game["putting"]),
              "unknown":sum(max(0,r["holes"]-r["tracked"]) for r in game["putting"])}]
        definition="Hit = a putting hole completed in one or two putts; miss = three or more. Zero-putt chip-ins are not attributed to the putter."
    if show_empty and role!="Putting":
        present={r["id"] for r in raw}
        for key,c in model.clubs.items():
            kind=str(c.get("clubTypeId"))
            if key=="0" or key in present or c.get("deleted") or c.get("retired") or kind=="23":
                continue
            if role=="Wedge chips" and kind not in {"19","20","21","22"}:
                continue
            raw.append({"id":key,"hits":0,"misses":0,"unknown":0})
    rows=[]
    for r in raw:
        total=r["hits"]+r["misses"]
        label=model.club_label(r["id"])[0] if r["id"]!="putter" else "Putter (scorecards)"
        low,high=wilson_interval(r["hits"],total)
        rows.append({**r,"label":label,"classified":total,"records":total+r["unknown"],"rate":100*r["hits"]/total if total else None,
                     "low":low,"high":high,"enough":total>=MIN_CLASSIFIED_SHOTS and r["id"]!="0","unassigned":r["id"]=="0"})
    rows.sort(key=lambda r:(r["unassigned"],not r["enough"],-(r["low"] or 0),-r["classified"],r["label"]))
    reliable=[r for r in rows if r["enough"]]
    known=[r for r in rows if not r["unassigned"]]
    return {"role":role,"rows":rows,"definition":definition,"strongest":reliable[0] if reliable else None,
            "most_misses":max(known,key=lambda r:r["misses"]) if known and any(r["misses"] for r in known) else None,
            "hits":sum(r["hits"] for r in rows),"misses":sum(r["misses"] for r in rows),"unknown":sum(r["unknown"] for r in rows),
            "unassigned":sum(r["records"] for r in rows if r["unassigned"]),"shot_holes":game["shot_holes"],"expected_holes":game["expected_holes"],
            "putting_holes":game["tracked_putting_holes"]}


def club_history(model,rounds,role,club_id):
    rate_slots,miss_slots=[],[]
    name=model.club_label(club_id)[0] if club_id!="putter" else "Putter (scorecards)"
    for r in sorted(rounds,key=lambda x:(x["sort_date"],x["id"])):
        result=club_confidence(model,[r],role)
        row=next((x for x in result["rows"] if x["id"]==club_id),None)
        valid=row is not None and row["classified"]>0
        meta={"id":r["id"],"date":r["date"],"course":r["course"],"classified":row["classified"] if row else 0,"hits":row["hits"] if row else 0}
        rate_slots.append({**meta,"value":row["rate"] if valid else None,"weight":row["classified"] if valid else 0})
        miss_slots.append({**meta,"value":row["misses"] if valid else None})
    return {"rate":summarize_series(rate_slots,name+" · target-hit rate","%",True,"club_rate"),
            "misses":summarize_series(miss_slots,name+" · recorded misses","misses",False,"club_misses")}
