"""Shared round selection and chronological, missing-aware trend statistics."""

from __future__ import annotations

import json
import math
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from golf_data import average, number, percent

MAX_HISTORY_COUNT = 10_000


def eligible_rounds(model, full_only=False):
    rounds = [r for r in model.rounds if not r["in_progress"] and r["holes_completed"] in ((18,) if full_only else (9,18))]
    return sorted(rounds,key=lambda r:(r["sort_date"],r["id"]),reverse=True)


@dataclass(frozen=True)
class RoundSelection:
    mode: str = "latest"
    count: int = 10
    ids: tuple[str,...] = ()
    full_only: bool = False

    def __post_init__(self):
        if self.mode not in {"latest","all","manual"}:
            raise ValueError("Choose latest, all, or manual games.")
        if isinstance(self.count,bool) or not isinstance(self.count,int) or not 1<=self.count<=MAX_HISTORY_COUNT:
            raise ValueError(f"Choose a game count from 1 to {MAX_HISTORY_COUNT}.")
        if not isinstance(self.full_only,bool) or not isinstance(self.ids,tuple) or len(self.ids)>MAX_HISTORY_COUNT or any(not isinstance(x,str) or len(x)>80 for x in self.ids):
            raise ValueError("Invalid round selection.")

    def resolve(self,model):
        available = eligible_rounds(model,self.full_only)
        if self.mode=="latest":
            return available[:self.count]
        if self.mode=="manual":
            chosen = set(self.ids)
            return [r for r in available if r["id"] in chosen]
        return available

    def label(self):
        return f"Last {self.count} games" if self.mode=="latest" else "All imported games" if self.mode=="all" else "Chosen games"

    def summary(self,model):
        selected = self.resolve(model)
        available = len(eligible_rounds(model,self.full_only))
        requested = self.count if self.mode=="latest" else len(set(self.ids)) if self.mode=="manual" else available
        return {"selected":len(selected),"available":available,"requested":requested,
                "shortfall":self.mode=="latest" and len(selected)<self.count,
                "oldest":selected[-1]["date"] if selected else "","newest":selected[0]["date"] if selected else ""}


def save_selection(path: Path, selection: RoundSelection, account_ids):
    data = {"version":1,"accounts":sorted(account_ids),"mode":selection.mode,"count":selection.count,
            "ids":list(selection.ids),"full_only":selection.full_only}
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    try:
        with temporary.open("x",encoding="utf-8") as handle:
            json.dump(data,handle)
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def load_selection(path: Path, account_ids):
    try:
        if path.stat().st_size>256_000:
            return RoundSelection()
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version")!=1 or not isinstance(data.get("ids",[]),list):
            return RoundSelection()
        same_account=data.get("accounts")==sorted(account_ids)
        if not same_account and data.get("mode")=="manual":
            return RoundSelection()
        # A generic last-N preference is not personal golf data and must survive
        # the first import changing an empty workspace into an identified account.
        ids=tuple(data.get("ids",[])) if same_account else ()
        return RoundSelection(data["mode"],data["count"],ids,data["full_only"])
    except (OSError,ValueError,TypeError,KeyError,AttributeError):
        return RoundSelection()


def period_statistics(rounds):
    full = [r for r in rounds if r["holes_completed"]==18]
    nine = [r for r in rounds if r["holes_completed"]==9]
    scoring = full if full else nine
    holes = 18 if full or not nine else 9
    def rate(hit,total):
        pairs = [(r[hit],r[total]) for r in rounds if number(r.get(hit)) is not None and number(r.get(total)) is not None and r[total]>0]
        return percent(sum(x for x,_ in pairs),sum(y for _,y in pairs))
    tracked = [h["putts"] for r in rounds for h in r["holes"] if number(h.get("putts")) is not None and h["putts"]>=0]
    return {"selected":len(rounds),"full_rounds":len(full),"nine_rounds":len(nine),"scoring_holes":holes,"scoring_games":len(scoring),
            "average_score":average([r["score"] for r in scoring]),"average_to_par":average([r["to_par"] for r in scoring]),
            "gir":rate("greens_hit","greens_recorded"),"fairways":rate("fairways_hit","fairways_recorded"),
            "putts":average([r["putts"] for r in scoring]),"putts_per_hole":average(tracked),
            "penalties":average([r["penalties"] for r in scoring]),
            "three_putts":average([r["three_putts"] for r in scoring if r["putt_coverage"]>=r["holes_completed"]]),
            "best":min((r["score"] for r in scoring if number(r["score"]) is not None),default=None)}


TREND_METRICS = {
    "score18":("Score · 18 holes","strokes",False,18),
    "score9":("Score · 9 holes","strokes",False,9),
    "gir":("Greens in regulation","%",True,None),
    "fairways":("Fairways hit","%",True,None),
    "putts_per_hole":("Putts per tracked hole","putts",False,None),
    "penalties18":("Penalties · 18 holes","strokes",False,18),
    "penalties9":("Penalties · 9 holes","strokes",False,9),
    "three_putts18":("Three-putt+ holes · 18 holes","holes",False,18),
    "three_putts9":("Three-putt+ holes · 9 holes","holes",False,9),
}


def trend_series(rounds,key):
    label,unit,higher_better,hole_kind = TREND_METRICS[key]
    ordered = sorted(rounds,key=lambda r:(r["sort_date"],r["id"]))
    slots = []
    excluded = 0
    for r in ordered:
        if hole_kind is not None and r["holes_completed"]!=hole_kind:
            excluded += 1
            continue
        value = None
        weight = 1
        if key.startswith("score"):
            value = number(r["score"])
        elif key in ("gir","fairways"):
            prefix = "greens" if key=="gir" else "fairways"
            value = percent(r[prefix+"_hit"],r[prefix+"_recorded"])
            weight = r[prefix+"_recorded"] if value is not None else 0
        elif key=="putts_per_hole":
            putts=[h["putts"] for h in r["holes"] if number(h.get("putts")) is not None and h["putts"]>=0]
            value = average(putts)
            weight = len(putts)
        elif key.startswith("penalties") and r["penalty_coverage"]>=r["holes_completed"]:
            value = number(r["penalties"])
        elif key.startswith("three_putts") and r["putt_coverage"]>=r["holes_completed"]:
            value = number(r["three_putts"])
        slots.append({"id":r["id"],"date":r["date"],"course":r["course"],"value":value,"weight":weight})
    return summarize_series(slots,label,unit,higher_better,key,excluded)


def summarize_series(slots,label,unit,higher_better,key="",excluded=0):
    points = [x for x in slots if x["value"] is not None]
    middle = len(slots)//2
    older = [x for x in slots[:middle] if x["value"] is not None]
    newer = [x for x in slots[middle:] if x["value"] is not None]
    change = weighted_mean(newer)-weighted_mean(older) if len(older)>=2 and len(newer)>=2 else None
    return {"key":key,"label":label,"unit":unit,"higher_better":higher_better,"slots":slots,"points":points,
            "missing":len(slots)-len(points),"excluded":excluded,"average":weighted_mean(points),
            "older_average":weighted_mean(older),"newer_average":weighted_mean(newer),"change":change,
            "improving":None if change is None or math.isclose(change,0,abs_tol=1e-9) else change>0 if higher_better else change<0}


def weighted_mean(slots):
    valid=[p for p in slots if number(p.get("value")) is not None and number(p.get("weight",1)) is not None and p.get("weight",1)>0]
    total=sum(p.get("weight",1) for p in valid)
    return sum(p["value"]*p.get("weight",1) for p in valid)/total if total else None


def moving_average(slots,window=5):
    if isinstance(window,bool) or not isinstance(window,int) or window<2:
        raise ValueError("Choose a rolling window of at least two games.")
    values = []
    for i in range(len(slots)):
        part = slots[max(0,i-window+1):i+1]
        values.append(weighted_mean(part) if len(part)==window and all(p["value"] is not None for p in part) else None)
    return values


def default_trend_keys(rounds):
    kinds=[str(n) for n in (18,9) if any(r["holes_completed"]==n for r in rounds)] or ["18"]
    return tuple(["score"+k for k in kinds]+["gir","fairways","putts_per_hole"]+["penalties"+k for k in kinds]+["three_putts"+k for k in kinds])
