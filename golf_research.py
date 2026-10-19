"""Selected-period research diagnostics, not calibrated future-shot predictions."""

from __future__ import annotations

import collections
import math
import statistics

from golf_baselines import StrokeReference
from golf_data import average,number,percent,shot_finish
from golf_game import full_game_snapshot
from golf_history import period_statistics,summarize_series
from golf_research_store import PUTT_BINS,hole_signature,round_review_status,shot_signature,usable_shots

REFERENCES=(
    ("Shot Scope: GIR by handicap","https://shotscope.com/blog/practice-green/stats-and-data/amateur-golfers-greens-hit/"),
    ("Shot Scope: published 15-handicap averages","https://shotscope.com/blog/practice-green/game-improvement/reduce-your-handicap-15hcp/"),
    ("PGA: dispersion and target selection","https://www.pga.com/story/play-smarter-golf-gary-woodlands-winning-strategy-for-better-dispersion-alignment-and-control"),
    ("PGA: putting practice","https://www.pga.com/story/golf-tips-the-best-putting-drills-to-improve-your-stroke"),
    ("Arccos: why strokes gained adds context","https://www.arccosgolf.com/blogs/community/understanding-strokes-gained"),
    ("SCGA: Handicap Index and differentials","https://help.scga.org/knowledge/how-is-a-handicap-index-calculated"),
)


def count(value):
    value=number(value)
    return value if value is not None and value>=0 and float(value).is_integer() else None


def played_holes(round_):
    return [h for h in round_["holes"] if count(h.get("strokes")) is not None and h["strokes"]>0]


def canonical_lie(value):
    key="".join(c for c in str(value or "").casefold() if c.isalnum())
    return {"tee":"Tee","teebox":"Tee","fairway":"Fairway","rough":"Rough","bunker":"Bunker","sand":"Bunker", "green":"Green","puttinggreen":"Green","recovery":"Recovery","woods":"Recovery","trees":"Recovery"}.get(key,"Unknown")


def point(location,scale):
    if not isinstance(location,dict) or number(location.get("lat")) is None or number(location.get("lon")) is None:
        return None
    lat,lon=location["lat"]*scale,location["lon"]*scale
    return (lat,lon) if -90<=lat<=90 and -180<=lon<=180 and (lat!=0 or lon!=0) else None


def meters_between(a,b):
    lat1,lon1,lat2,lon2=map(math.radians,(*a,*b))
    value=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371008.8*2*math.asin(min(1,math.sqrt(max(0,value))))


def validated_scale(round_):
    results=[]
    for name,scale in (("degrees",1),("semicircles",180/(2**31)),("microdegrees",1e-6),("ten-millionths",1e-7)):
        errors=[]
        for _,shot,_ in usable_shots(round_):
            length=number(shot.get("meters"))
            start,end=point(shot.get("startLoc"),scale),point(shot.get("endLoc"),scale)
            if length is not None and length>20 and start and end:
                errors.append(abs(meters_between(start,end)-length)/length)
        if len(errors)>=3:
            results.append({"name":name,"scale":scale,"median_error":statistics.median(errors),"checked":len(errors)})
    best=min(results,key=lambda x:x["median_error"]) if results else None
    return best if best and best["median_error"]<=0.05 else None


def distance_band(value):
    if value is None:
        return "Unknown distance"
    for limit,label in ((50,"Under 50 yd"),(100,"50–100 yd"),(150,"100–150 yd"),(175,"150–175 yd"),(200,"175–200 yd"),(250,"200–250 yd")):
        if value<limit:
            return label
    return "250+ yd"


def shot_contexts(model,rounds,scope):
    records=[]
    validations=[]
    annotations=scope.get("shots",{})
    for r in rounds:
        validation=validated_scale(r)
        validations.append({"round_id":r["id"],"date":r["date"],"validation":validation})
        scale=validation["scale"] if validation else None
        for hole,shot,key in usable_shots(r):
            note=annotations.get(r["id"],{}).get(key,{})
            start_proxy=end_proxy=None
            if scale is not None:
                pin=point(hole.get("pinPosition"),scale)
                start,end=point(shot.get("startLoc"),scale),point(shot.get("endLoc"),scale)
                if pin and start:
                    value=meters_between(start,pin)/.9144
                    start_proxy=value if 0<value<=1200 else None
                if pin and end:
                    value=meters_between(end,pin)/.9144
                    end_proxy=value if 0<=value<=1200 else None
            states_current=note.get("source_signature")==shot_signature(r,hole,shot)
            verified=note.get("states_verified") is True and states_current
            start=note.get("start_yards") if verified else start_proxy
            club=str(shot.get("clubId") or 0)
            records.append({"round_id":r["id"],"date":r["date"],"course":r["course"],"hole":hole.get("holeNumber"),"key":key,
                            "role":str(shot.get("shotType") or "UNKNOWN"),"club_id":club,"club":model.club_label(club)[0],
                            "start_lie":note.get("start_lie") if verified else canonical_lie((shot.get("startLoc") or {}).get("lie")),
                            "end_lie":note.get("end_lie") if verified else canonical_lie((shot.get("endLoc") or {}).get("lie")),
                            "outcome":("green" if note.get("end_lie")=="Green" or note.get("holed") else "unknown" if note.get("end_lie")=="Unknown" else "miss") if verified else shot_finish(shot),
                            "intent":note.get("intent","Unknown"),"conditions":note.get("conditions","Unknown"),
                            "start_yards":start,"start_proxy":start_proxy,"end_proxy":end_proxy,"band":distance_band(start),
                            "distance_source":"Verified local states" if verified else "Recorded-pin proxy" if start_proxy is not None else "Unavailable",
                            "states_current":states_current,"state_signature":shot_signature(r,hole,shot),"note":note})
    return records,validations


def tracking_audit(model,rounds,scope):
    items=[]
    facts=collections.Counter()
    reviews=scope.get("reviews",{})
    def issue(key,severity,r,title,detail,hole=None,shot=None):
        items.append({"key":key,"severity":severity,"round_id":r["id"],"date":r["date"],"course":r["course"],"title":title,"detail":detail,
                      "hole":hole,"shot_key":shot,"review_status":reviews.get(key,"Unchecked")})
    for r in rounds:
        expected=r["holes_completed"] or 0
        facts["expected_holes"]+=expected
        facts["rounds"]+=1
        played=played_holes(r)
        facts["scored_holes"]+=len(played)
        pknown=sum(count(h.get("putts")) is not None for h in played)
        nknown=sum(count(h.get("penalties")) is not None for h in played)
        facts["putt_holes"]+=pknown
        facts["penalty_holes"]+=nknown
        if len(played)<expected:
            issue("score-holes:"+r["id"],"Missing",r,"Missing per-hole scores",f"Only {len(played)} of {expected} holes have usable scores; no missing score is treated as zero.")
        elif number(r["score"]) is not None and sum(h["strokes"] for h in played)!=r["score"]:
            issue("score-total:"+r["id"],"Check",r,"Score total differs from hole scores","Review the scorecard in Garmin. The app does not rewrite either total.")
        if pknown<expected:
            issue("putt-holes:"+r["id"],"Missing",r,"Missing scorecard putt entries",f"{pknown}/{expected} played holes have putt counts.")
        elif len(played)==expected and pknown==expected and number(r["putts"]) is not None and sum(h["putts"] for h in played)!=r["putts"]:
            issue("putt-total:"+r["id"],"Check",r,"Putt total differs from hole entries","Check the actual putting counts before drawing practice conclusions.")
        if nknown<expected:
            issue("penalty-holes:"+r["id"],"Missing",r,"Missing penalty entries",f"{nknown}/{expected} played holes have an explicit penalty count. Unknown is not zero.")
        for h in played:
            if count(h.get("par")) in (None,0):
                issue(f"par:{r['id']}:{h['number']}","Missing",r,"Missing hole par","This score can support a putting count, but not a double/triple-bogey classification without a valid par.",h["number"])
            p,n=count(h.get("putts")),count(h.get("penalties"))
            if p is not None and p>h["strokes"] or n is not None and n>h["strokes"]:
                issue(f"hole-counts:{r['id']}:{h['number']}","Check",r,"Impossible hole counts","A putt or penalty count exceeds the recorded hole score. Check and correct the source before using reference analysis.",h["number"])
        note=scope.get("rounds",{}).get(r["id"],{})
        if round_review_status(r,note,"putts_status")!="Verified":
            issue("verify-putts:"+r["id"],"Review",r,"Verify putting counts", "Compare scorecard totals with actual play; mark verified only after checking. GPS putt records are not a substitute.")
        if round_review_status(r,note,"penalties_status")!="Verified":
            issue("verify-penalties:"+r["id"],"Review",r,"Verify penalty counts","Check recorded penalties and classify their phase in the round journal; a fairway tag alone cannot locate a penalty.")
        shots=list(usable_shots(r))
        covered={h.get("holeNumber") for h,_,_ in shots if isinstance(h.get("holeNumber"),int) and 1<=h["holeNumber"]<=18}
        expected_numbers={h["number"] for h in played}
        if len(expected_numbers)==expected:
            covered &= expected_numbers
        facts["shot_holes"]+=min(expected,len(covered))
        if len(covered)<expected:
            missing=sorted(expected_numbers-covered) if len(expected_numbers)==expected else []
            suffix=" Missing holes: "+", ".join(map(str,missing))+"." if missing else ""
            issue("shot-holes:"+r["id"],"Missing",r,"Incomplete detailed-shot coverage",f"{len(covered)}/{expected} holes contain exported shots."+suffix)
        putt_shots=sum(s.get("shotType")=="PUTT" for _,s,_ in shots)
        if r["putts"] is not None and putt_shots!=r["putts"]:
            issue("gps-putts:"+r["id"],"Info",r,"GPS putts do not cover all scorecard putts",f"{putt_shots} GPS PUTT records versus {r['putts']} scorecard putts. Short-putt omissions or missing holes can explain this; it is not proof of a wrong scorecard.")
        for hole,shot,key in shots:
            if shot.get("shotType")=="PUTT":
                continue
            facts["nonputt_shots"]+=1
            if str(shot.get("clubId") or 0)=="0":
                facts["unassigned_shots"]+=1
                issue("club:"+r["id"]+":"+key,"Missing",r,"Unassigned shot club","Assign the actual club in Garmin and re-import. A display name cannot identify an unassigned shot.",hole.get("holeNumber"),key)
            if shot_finish(shot)=="unknown":
                facts["unknown_finishes"]+=1
                issue("finish:"+r["id"]+":"+key,"Missing",r,"Unknown shot ending lie","A missing finish is neither a target hit nor a miss.",hole.get("holeNumber"),key)
    facts["reviewed_rounds"]=sum(round_review_status(r,scope.get("rounds",{}).get(r["id"],{}),"putts_status")=="Verified" for r in rounds)
    facts["first_putt_notes"]=len(putting_context(rounds,scope)["holes"])
    return {"facts":dict(facts),"items":items}


def scoring_breakdown(rounds):
    by_par={}
    flags=collections.Counter()
    flag_costs={}
    big=[]
    holes=[]
    putting_holes=[]
    cap=0
    for r in rounds:
        for h in played_holes(r):
            par,strokes=count(h.get("par")),h["strokes"]
            if count(h.get("putts")) is not None and h["putts"]<=strokes:
                putting_holes.append(h)
            if par is None or par<=0:
                continue
            delta=strokes-par
            holes.append((r,h))
            row=by_par.setdefault(par,{"par":par,"scores":[],"double_only":0,"triple_plus":0})
            row["scores"].append(strokes)
            row["double_only"]+=delta==2
            row["triple_plus"]+=delta>=3
            cap+=max(0,delta-2)
            if delta>=2:
                p,t=count(h.get("penalties")),count(h.get("putts"))
                if p is not None and p>strokes:
                    p=None
                if t is not None and t>strokes:
                    t=None
                flag="Unknown tracking" if p is None or t is None else "Penalty + three-putt" if p>0 and t>=3 else "Penalty only" if p>0 else "Three-putt only" if t>=3 else "Neither flag recorded"
                flags[flag]+=1
                cost=flag_costs.setdefault(flag,{"holes":0,"gross_strokes":0,"over_par":0,"above_double":0})
                cost["holes"]+=1
                cost["gross_strokes"]+=strokes
                cost["over_par"]+=delta
                cost["above_double"]+=max(0,delta-2)
                big.append({"round_id":r["id"],"date":r["date"],"course":r["course"],"hole":h["number"],"par":par,"score":strokes,"to_par":delta,"putts":t,"penalties":p,"fairway":h.get("fairwayShotOutcome","Not recorded"),"flag":flag})
    pars=[]
    for par,row in sorted(by_par.items()):
        n=len(row["scores"])
        pars.append({"par":par,"holes":n,"average":average(row["scores"]),"double_only":row["double_only"],"triple_plus":row["triple_plus"],
                     "big_rate":100*(row["double_only"]+row["triple_plus"])/n})
    big.sort(key=lambda x:(x["to_par"],x["date"]),reverse=True)
    return {"scored_holes":len(holes),"big_holes":big,"flags":dict(flags),"flag_costs":flag_costs,"by_par":pars,"triple_plus":sum(r["triple_plus"] for r in pars),"cap_scenario":cap,
            "threeputts":sum(h["putts"]>=3 for h in putting_holes),"tracked_putt_holes":len(putting_holes)}


def putting_context(rounds,scope):
    grouped={}
    rows=[]
    for r in rounds:
        for h in played_holes(r):
            note=scope.get("holes",{}).get(r["id"],{}).get(str(h["number"]),{})
            bin_=note.get("first_putt_bin","Not recorded")
            putts=count(h.get("putts"))
            if bin_ not in PUTT_BINS[1:-1] or putts is None or not 0<putts<=h["strokes"] or note.get("source_signature")!=hole_signature(r,h):
                continue
            group=grouped.setdefault(bin_,{"bin":bin_,"holes":0,"threeputts":0,"putts":[],"short_returns":0})
            group["holes"]+=1
            group["threeputts"]+=putts>=3
            group["putts"].append(putts)
            group["short_returns"]+=note.get("missed_short_return") is True
            rows.append({"round_id":r["id"],"date":r["date"],"hole":h["number"],"bin":bin_,"putts":putts,**note})
    for group in grouped.values():
        group["rate"]=percent(group["threeputts"],group["holes"])
        group["average_putts"]=average(group["putts"])
    return {"groups":sorted(grouped.values(),key=lambda g:PUTT_BINS.index(g["bin"])),"holes":rows}


def approach_context(model,rounds,scope,green_attempts_only=False):
    records,validation=shot_contexts(model,rounds,scope)
    approaches=[r for r in records if r["role"]=="APPROACH" and (not green_attempts_only or r["intent"] not in ("Lay-up","Recovery"))]
    groups={}
    for r in approaches:
        key=(r["band"],r["start_lie"],r["club_id"])
        group=groups.setdefault(key,{"band":r["band"],"lie":r["start_lie"],"club":r["club"],"club_id":r["club_id"],"shots":0,"green":0,"miss":0,"unknown":0,"distances":[],"intent_unknown":0})
        group["shots"]+=1
        group[r["outcome"]]+=1
        group["intent_unknown"]+=r["intent"]=="Unknown"
        if r["start_yards"] is not None:
            group["distances"].append(r["start_yards"])
    for group in groups.values():
        group["rate"]=percent(group["green"],group["green"]+group["miss"])
        group["median_yards"]=statistics.median(group["distances"]) if group["distances"] else None
    return {"records":approaches,"groups":list(groups.values()),"validations":validation,"unknown_distance":sum(r["start_yards"] is None for r in approaches)}


def percentile(values,q):
    if not values:
        return None
    values=sorted(values)
    position=(len(values)-1)*q
    low=int(position)
    high=min(len(values)-1,low+1)
    return values[low]+(values[high]-values[low])*(position-low)


def practice_summary(model,scope):
    rows=scope.get("practice",[])
    carry={}
    chips={}
    for r in rows:
        if r.get("contact")=="Tracking error":
            continue
        key=(r["club_id"],r["role"],r.get("date",""),r.get("session",""),r.get("lie",""),r.get("conditions","Unknown"))
        if r["role"]=="Chip trial":
            group=chips.setdefault(key,{"club":model.club_label(r["club_id"])[0],"date":r.get("date",""),"session":r.get("session",""),"lie":r.get("lie",""),"conditions":r.get("conditions","Unknown"),"records":0,"green":0,"known":0,"finishes":[],"strokes":[]})
            group["records"]+=1
            group["green"]+=r.get("on_green")=="Yes"
            group["known"]+=r.get("on_green") in ("Yes","No")
            if number(r.get("finish_feet")) is not None:
                group["finishes"].append(r["finish_feet"])
            if number(r.get("strokes_to_finish")) is not None:
                group["strokes"].append(r["strokes_to_finish"])
        elif number(r.get("carry_yards")) is not None:
            group=carry.setdefault(key,{"club":model.club_label(r["club_id"])[0],"date":r.get("date",""),"role":r["role"],"session":r.get("session",""),"lie":r.get("lie",""),"conditions":r.get("conditions","Unknown"),"carries":[],"laterals":[],"mishits":0,"pairs":0,"paired_samples":[]})
            group["carries"].append(r["carry_yards"])
            group["mishits"]+=r.get("contact")=="Mishit"
            if number(r.get("lateral_yards")) is not None:
                group["laterals"].append(r["lateral_yards"])
                group["pairs"]+=1
                group["paired_samples"].append({"carry":r["carry_yards"],"lateral":r["lateral_yards"],"contact":r.get("contact","Normal attempt")})
    for r in carry.values():
        r.update(n=len(r["carries"]),median=percentile(r["carries"],.5),p10=percentile(r["carries"],.1),p90=percentile(r["carries"],.9),left_p10=percentile(r["laterals"],.1),right_p90=percentile(r["laterals"],.9))
    for r in chips.values():
        r.update(rate=percent(r["green"],r["known"]),median_finish=percentile(r["finishes"],.5),worst_finish=max(r["finishes"],default=None),mean_strokes=average(r["strokes"]))
    return {"records":rows,"carry":list(carry.values()),"chips":list(chips.values())}


def reference_results(model,rounds,scope):
    try:
        reference=StrokeReference.from_dict(scope.get("baseline"))
    except (ValueError,TypeError,KeyError):
        return {"reference":None,"error":"The saved reference is invalid; it was not used.","putting":[],"shots":[],"blocked":[]}
    putting,shots,blocked=[],[],[]
    if reference is None:
        return {"reference":None,"error":None,"putting":putting,"shots":shots,"blocked":blocked}
    contexts,_=shot_contexts(model,rounds,scope)
    by_round=collections.defaultdict(dict)
    for record in contexts:
        by_round[record["round_id"]][record["key"]]=record
    for r in rounds:
        verification=scope.get("rounds",{}).get(r["id"],{})
        holes={str(h["number"]):h for h in r["holes"]}
        for number_,h in holes.items():
            note=scope.get("holes",{}).get(r["id"],{}).get(number_,{})
            if note.get("first_putt_feet") is not None:
                try:
                    if round_review_status(r,verification,"putts_status")!="Verified" or count(h.get("putts")) is None or h["putts"]<=0:
                        raise ValueError("Verify nonzero scorecard putts first.")
                    if note.get("source_signature")!=hole_signature(r,h):
                        raise ValueError("The source hole changed since this note was saved; check and save it again.")
                    if count(h.get("strokes")) is None or not h["putts"]<=h["strokes"]:
                        raise ValueError("The hole's putts and total score are inconsistent.")
                    known=[count(x.get("putts")) for x in played_holes(r)]
                    if len(known)==r["holes_completed"] and all(x is not None for x in known) and number(r["putts"]) is not None and sum(known)!=r["putts"]:
                        raise ValueError("The round putt total disagrees with hole counts. Correct and re-import the source first.")
                    if note.get("distance_basis") not in ("Estimated","Measured"):
                        raise ValueError("Say whether the first-putt distance was estimated or measured.")
                    remaining=count(note.get("strokes_from_first_putt"))
                    if remaining is None:
                        raise ValueError("Log total strokes from first putt through hole-out, including any penalties or off-green recovery.")
                    if not h["putts"]<=remaining<=h["strokes"]:
                        raise ValueError("Strokes from first putt must be between the recorded putts and the hole score.")
                    expected=reference.lookup(note["first_putt_feet"]/3,"Green")
                    putting.append({"round_id":r["id"],"date":r["date"],"hole":h["number"],"putts":h["putts"],"strokes_to_finish":remaining,"expected":expected,"sg":expected-remaining,"basis":note.get("distance_basis","Not supplied")})
                except ValueError as exc:
                    blocked.append({"date":r["date"],"hole":h["number"],"reason":str(exc),"kind":"Putting"})
        shot_notes=scope.get("shots",{}).get(r["id"],{})
        allocations=collections.defaultdict(float)
        records=by_round[r["id"]]
        for record in records.values():
            penalty=count(record["note"].get("penalty_strokes"))
            if record["states_current"] and penalty is not None:
                allocations[str(record["hole"])]+=penalty
        for key,note in shot_notes.items():
            if not note.get("states_verified"):
                continue
            context=records.get(key)
            if context is None:
                blocked.append({"date":r["date"],"hole":"—","reason":"Annotated shot is not present in this export.","kind":"Shot"})
                continue
            h=holes.get(str(context["hole"]),{})
            try:
                if not context["states_current"]:
                    raise ValueError("The source shot changed since its states were checked; review and save it again.")
                if context["role"]=="PUTT":
                    raise ValueError("Use verified hole-level putting, not GPS putt states.")
                total=count(h.get("penalties"))
                if round_review_status(r,verification,"penalties_status")!="Verified" or total is None:
                    raise ValueError("Verify the hole's recorded penalties first.")
                if count(h.get("strokes")) is None or total>h["strokes"]:
                    raise ValueError("The hole's penalty count and score are inconsistent.")
                if not math.isclose(allocations[str(context["hole"])],total):
                    raise ValueError("Per-shot penalty allocations do not match the verified hole penalty total.")
                allocated=[x for x in records.values() if x["hole"]==context["hole"] and x["states_current"] and (x["note"].get("penalty_strokes") or 0)>0]
                if any(x["note"].get("review_status")!="Verified" for x in allocated):
                    raise ValueError("Verify each nonzero per-shot penalty allocation before using it.")
                value=reference.shot_value(note["start_yards"],note["start_lie"],note["end_yards"],note["end_lie"],note.get("penalty_strokes"),note.get("holed",False))
                shots.append({"round_id":r["id"],"date":r["date"],"hole":context["hole"],"club":context["club"],"role":context["role"],"sg":value,"intent":note.get("intent","Unknown")})
            except (ValueError,KeyError) as exc:
                blocked.append({"date":r["date"],"hole":context["hole"],"reason":str(exc),"kind":"Shot"})
    return {"reference":reference,"error":None,"putting":putting,"shots":shots,"blocked":blocked}


def rating_proxy(rounds):
    slots=[]
    for r in sorted((r for r in rounds if r["holes_completed"]==18 and not r["in_progress"]),key=lambda x:x["sort_date"]):
        rating,slope=number(r.get("course_rating")),number(r.get("slope_rating"))
        score=number(r.get("score"))
        value=113*(score-rating)/slope if rating is not None and 20<=rating<=100 and slope is not None and 55<=slope<=155 and score is not None and score>0 else None
        slots.append({"id":r["id"],"date":r["date"],"course":r["course"],"value":value})
    return summarize_series(slots,"Rating/slope-adjusted gross proxy","proxy strokes",False,"rating_proxy")


def research_snapshot(model,rounds,scope):
    audit=tracking_audit(model,rounds,scope)
    scoring=scoring_breakdown(rounds)
    stats=period_statistics(rounds)
    game=full_game_snapshot(model,rounds)
    facts=audit["facts"]
    rate=percent(scoring["threeputts"],scoring["tracked_putt_holes"])
    cards=[]
    if facts.get("shot_holes",0)<facts.get("expected_holes",0) or facts.get("unassigned_shots",0):
        cards.append({"title":"Trust the inputs before training EV", "evidence":f"Detailed shots cover {facts.get('shot_holes',0)}/{facts.get('expected_holes',0)} selected holes; {facts.get('unassigned_shots',0)} non-putting shots have no club.",
                      "action":"Review missing tags in Garmin, check scorecard counts, and import a larger detailed window if desired. Unknown records stay unknown.","kind":"audit"})
    if rate is not None:
        cards.append({"title":"Separate putting pace from short-putt misses","evidence":f"{scoring['threeputts']}/{scoring['tracked_putt_holes']} tracked putting holes had three or more putts ({rate:.1f}%). {facts.get('reviewed_rounds',0)}/{len(rounds)} selected rounds are locally marked putt-count verified.",
                      "action":"Check the counts, then log first-putt distance bins on successful holes as well as failures. Practise pace and short return-putt conversion separately.","kind":"journal"})
    if scoring["big_holes"]:
        group=max(scoring["by_par"],key=lambda x:(x["double_only"]+x["triple_plus"],x["big_rate"]))
        cards.append({"title":f"Review costly par-{group['par']:.0f} holes","evidence":f"Par {group['par']:.0f}s account for {group['double_only']+group['triple_plus']} recorded big holes, including {group['triple_plus']} triple-or-worse. Hole difficulty differs.",
                      "action":"Use the flag breakdown to distinguish penalties, three-putts and other problems. Tag penalty phase; a fairway hit does not prove a tee shot caused or avoided all trouble.","kind":"insights"})
    drivers=[r for r in game["tee"] if r["driver"]]
    if drivers:
        d=drivers[0]
        cards.append({"title":"Do not club down from FIR alone","evidence":f"Recorded {d['label']} tees: {d['hit']}/{d['fw_recorded']} attributed fairways. These are different situations, not a controlled driver-versus-wood experiment.",
                      "action":"Compare the next distance/lie and penalty risk. Use your normal dispersion and carry, not just a cleaner fairway percentage.","kind":"context"})
    cards.append({"title":"Calibrate carry without deleting human error","evidence":"On-course shot length includes roll and mixed intentions. Club success rates also face different distances and lies.",
                  "action":"Record measured carry and lateral miss in matched practice sessions. Keep normal mishits; exclude only genuine tracking errors. Separate full swings, partial pitches and recovery/lay-up intent.","kind":"practice"})
    if game["chip_shots"]:
        off=sum(r["chip"]["miss"] for r in game["wedges"])
        cards.append({"title":"Test chip options from matched lies","evidence":f"The exported wedge-chip sample has {game['chip_shots']} shots and {off} known off-green finishes. Fringe/GPS classification and intent need checking.",
                      "action":"When conditions allow, compare a lower-running club or putter with the lofted wedge from the same session/lie. Track finish distance and strokes to hole out, not on-green rate alone.","kind":"practice"})
    priorities={"audit":100,"journal":90 if rate is not None and rate>10 and scoring["tracked_putt_holes"]>=18 else 25,"insights":80,"practice":50,"context":40}
    cards.sort(key=lambda c:priorities[c["kind"]],reverse=True)
    return {"audit":audit,"scoring":scoring,"stats":stats,"game":game,"putting":putting_context(rounds,scope),"cards":cards,"threeputt_rate":rate,
            "benchmarks":{"gir_10":35.0,"gir_15":23.0,"threeputt_15":10.0},"rating_proxy":rating_proxy(rounds)}
