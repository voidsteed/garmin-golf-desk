"""Private account-scoped research notes; never changes Garmin exports."""

from __future__ import annotations

import copy
import contextlib
import hashlib
import json
import math
import os
import uuid
from datetime import date
from pathlib import Path

PUTT_BINS=("Not recorded","0–6 ft","6–15 ft","15–30 ft","30–60 ft","60+ ft","No putt")
CHECK_STATUSES=("Unchecked","Verified","Needs correction")
PENALTY_PHASES=("Unknown","Tee","Approach","Short game","Putting","Multiple")
PENALTY_REASONS=("Unknown","Execution","Decision / target","Rule / procedure","Multiple")
INTENTS=("Unknown","Full swing","Controlled partial","Lay-up","Recovery","Chip","Pitch","Other")
CONDITIONS=("Unknown","Calm / level","Headwind","Tailwind","Crosswind","Uphill","Downhill","Poor lie")
LIES=("Tee","Fairway","Rough","Bunker","Green","Recovery")


class ResearchStoreError(Exception):
    pass


def account_key(model):
    values=sorted(model.account_identities)
    payload={"type":"account","ids":values} if values else {"type":"unidentified","sources":sorted(str(p) for p in model.sources)} if model.sources else {"type":"unassigned-workspace"}
    identity=json.dumps(payload,sort_keys=True,separators=(",",":"))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def numeric(value,label,low=0,high=1000,integer=False):
    if value in (None,""):
        return None
    if isinstance(value,bool):
        raise ValueError(f"{label} must be a number.")
    try:
        result=float(value)
    except (TypeError,ValueError):
        raise ValueError(f"Enter a numeric {label}, or leave it blank.") from None
    if not math.isfinite(result) or not low<=result<=high or integer and not result.is_integer():
        raise ValueError(f"{label} must be {'a whole number ' if integer else ''}between {low} and {high}.")
    return int(result) if integer else result


def choice(value,allowed,label):
    if value not in allowed:
        raise ValueError(f"Choose a valid {label}.")
    return value


def putt_bin(feet):
    return next((label for limit,label in ((6,"0–6 ft"),(15,"6–15 ft"),(30,"15–30 ft"),(60,"30–60 ft")) if feet<=limit),"60+ ft")


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")).hexdigest()


def usable_shots(round_):
    seen=set()
    for hole in round_["shots"].get("holeShots",[]):
        if not isinstance(hole,dict) or not isinstance(hole.get("shots"),list):
            continue
        for index,shot in enumerate(hole["shots"]):
            if not isinstance(shot,dict) or shot.get("excludeFromStats") or shot.get("autoShotType") not in (None,"USED"):
                continue
            identifier=shot.get("id")
            order=shot.get("shotOrder") if shot.get("shotOrder") is not None else f"index-{index}"
            key=str(identifier) if isinstance(identifier,(str,int)) and not isinstance(identifier,bool) else f"hole-{hole.get('holeNumber')}-order-{order}"
            if key not in seen:
                seen.add(key)
                yield hole,shot,key


def round_signatures(round_):
    common=[round_["id"],round_["holes_completed"],round_["score"]]
    holes=sorted(round_["holes"],key=lambda h:h["number"])
    return {
        "putts_status":digest([common,round_["putts"],[[h["number"],h.get("strokes"),h.get("putts")] for h in holes]]),
        "penalties_status":digest([common,[[h["number"],h.get("strokes"),h.get("penalties")] for h in holes]]),
        "pin_status":digest([common,[[h.get("holeNumber"),h.get("pinPosition")] for h in round_["shots"].get("holeShots",[]) if isinstance(h,dict)]]),
    }


def round_review_status(round_,note,field):
    status=note.get(field,"Unchecked")
    if status=="Verified" and note.get("source_signatures",{}).get(field)!=round_signatures(round_)[field]:
        return "Unchecked"
    return status


def hole_signature(round_,hole):
    return digest([round_["id"],round_["date"],round_["course"],{k:hole.get(k) for k in ("number","par","strokes","putts","penalties")}])


def shot_signature(round_,hole,shot):
    return digest([round_["id"],hole.get("holeNumber"),hole.get("pinPosition"),shot])


def _reject_constant(_):
    raise ValueError("Non-finite journal value")


def _validate_data(data):
    if not isinstance(data,dict) or data.get("version")!=1 or not isinstance(data.get("accounts"),dict):
        raise ValueError("Unsupported research journal")
    for scope in data["accounts"].values():
        if not isinstance(scope,dict):
            raise ValueError("Invalid account notes")
        for field in ("rounds","holes","shots","reviews"):
            if not isinstance(scope.get(field,{}),dict):
                raise ValueError("Invalid note collection")
        if any(not isinstance(note,dict) for note in scope.get("rounds",{}).values()):
            raise ValueError("Invalid round note")
        for note in scope.get("rounds",{}).values():
            for field in ("putts_status","penalties_status","pin_status"):
                if field in note and note[field] not in CHECK_STATUSES:
                    raise ValueError("Invalid review status")
            if not isinstance(note.get("source_signatures",{}),dict):
                raise ValueError("Invalid source review")
        for field in ("holes","shots"):
            for group in scope.get(field,{}).values():
                if not isinstance(group,dict) or any(not isinstance(note,dict) for note in group.values()):
                    raise ValueError("Invalid hole or shot note")
        for group in scope.get("holes",{}).values():
            for note in group.values():
                if note.get("first_putt_feet") is not None and not isinstance(note["first_putt_feet"],(int,float)):
                    raise ValueError("Invalid saved putting distance")
                numeric(note.get("first_putt_feet"),"first-putt distance",0.1,500)
                if note.get("first_putt_bin","Not recorded") not in PUTT_BINS or note.get("distance_basis","Not supplied") not in ("Not supplied","Estimated","Measured") or note.get("penalty_phase","Unknown") not in PENALTY_PHASES or note.get("penalty_reason","Unknown") not in PENALTY_REASONS:
                    raise ValueError("Invalid hole context")
                if note.get("strokes_from_first_putt") is not None and not isinstance(note["strokes_from_first_putt"],(int,float)):
                    raise ValueError("Invalid hole-out count")
                numeric(note.get("strokes_from_first_putt"),"strokes from first putt",1,30,True)
                if not isinstance(note.get("missed_short_return",False),bool):
                    raise ValueError("Invalid short-putt flag")
        for group in scope.get("shots",{}).values():
            for note in group.values():
                for field,low,high in (("start_yards",0.01,1200),("end_yards",0,1200),("penalty_strokes",0,4)):
                    if note.get(field) is not None and not isinstance(note[field],(int,float)):
                        raise ValueError("Invalid saved shot measurement")
                    numeric(note.get(field),field,low,high,field=="penalty_strokes")
                if any(not isinstance(note.get(field,False),bool) for field in ("states_verified","holed")):
                    raise ValueError("Invalid shot verification")
                for field,values,default in (("start_lie",("Unknown",)+LIES,"Unknown"),("end_lie",("Unknown",)+LIES,"Unknown"),("intent",INTENTS,"Unknown"),("conditions",CONDITIONS,"Unknown"),("review_status",CHECK_STATUSES,"Unchecked")):
                    if note.get(field,default) not in values:
                        raise ValueError("Invalid shot context")
        if any(status not in CHECK_STATUSES for status in scope.get("reviews",{}).values()):
            raise ValueError("Invalid audit acknowledgment")
        practices=scope.get("practice",[])
        if not isinstance(practices,list) or any(not isinstance(r,dict) or not isinstance(r.get("id"),str) or r.get("role") not in ("Full swing","Controlled pitch","Chip trial") or not isinstance(r.get("club_id"),str) for r in practices):
            raise ValueError("Invalid practice records")
        if len({r["id"] for r in practices})!=len(practices):
            raise ValueError("Duplicate practice records")
        for record in practices:
            if not isinstance(record.get("date"),str) or record.get("conditions","Unknown") not in CONDITIONS or record.get("contact","Normal attempt") not in ("Normal attempt","Mishit","Tracking error") or record.get("on_green","Unknown") not in ("Unknown","Yes","No"):
                raise ValueError("Invalid practice context")
            date.fromisoformat(record["date"])
            if any(not isinstance(record.get(field,""),str) for field in ("session","lie")):
                raise ValueError("Invalid practice labels")
            for field,low,high in (("carry_yards",0,450),("lateral_yards",-300,300),("finish_feet",0,500),("strokes_to_finish",1,15)):
                if record.get(field) is not None and not isinstance(record[field],(int,float)):
                    raise ValueError("Invalid saved measurement")
                numeric(record.get(field),field,low,high,field=="strokes_to_finish")
        if scope.get("baseline") is not None and not isinstance(scope["baseline"],dict):
            raise ValueError("Invalid reference collection")


class ResearchStore:
    def __init__(self,path: Path):
        self.path=path
        self.error=None
        self.revision=None
        self.data={"version":1,"accounts":{}}
        try:
            if path.exists():
                if path.stat().st_size>10_000_000:
                    raise ValueError
                raw=path.read_bytes()
                data=json.loads(raw.decode("utf-8"),parse_constant=_reject_constant)
                _validate_data(data)
                self.data=data
                self.revision=hashlib.sha256(raw).hexdigest()
        except (OSError,ValueError,TypeError,KeyError):
            self.error="Research notes could not be opened. The existing file has not been replaced; back it up and inspect it before continuing."

    def scope(self,model):
        return copy.deepcopy(self.data["accounts"].get(account_key(model),{}))

    def _change(self,model,update):
        if self.error:
            raise ResearchStoreError(self.error)
        before=copy.deepcopy(self.data)
        scoped=self.data["accounts"].setdefault(account_key(model),{})
        temporary=self.path.with_name(self.path.name+"."+uuid.uuid4().hex+".tmp")
        try:
            self._check_revision()
            update(scoped)
            _validate_data(self.data)
            serialized=json.dumps(self.data,indent=2,ensure_ascii=False,allow_nan=False)
            if len(serialized.encode("utf-8"))>10_000_000:
                raise ValueError("Journal size limit")
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with temporary.open("x",encoding="utf-8",newline="\n") as handle:
                handle.write(serialized)
            self._check_revision()
            os.replace(temporary,self.path)
            self.revision=hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        except ResearchStoreError:
            self.data=before
            raise
        except (OSError,ValueError,TypeError,KeyError,AttributeError):
            self.data=before
            raise ResearchStoreError("Research notes could not be saved. Existing notes and Garmin data were kept.") from None
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)

    def _check_revision(self):
        current=hashlib.sha256(self.path.read_bytes()).hexdigest() if self.path.exists() else None
        if current!=self.revision:
            raise ResearchStoreError("Research notes changed in another window. Use Data & privacy → Reload saved data before saving; the newer notes have not been overwritten.")

    def round_note(self,model,round_id):
        note=self.scope(model).get("rounds",{}).get(str(round_id),{})
        round_=next((r for r in model.rounds if r["id"]==str(round_id)),None)
        if round_:
            for field in ("putts_status","penalties_status","pin_status"):
                note[field]=round_review_status(round_,note,field)
        return note

    def hole_note(self,model,round_id,hole):
        return self.scope(model).get("holes",{}).get(str(round_id),{}).get(str(hole),{})

    def shot_note(self,model,round_id,shot_key):
        return self.scope(model).get("shots",{}).get(str(round_id),{}).get(str(shot_key),{})

    def save_round(self,model,round_id,values):
        data={key:choice(values.get(key,"Unchecked"),CHECK_STATUSES,key) for key in ("putts_status","penalties_status","pin_status")}
        data["note"]=str(values.get("note","")).strip()[:1500]
        round_=next((r for r in model.rounds if r["id"]==str(round_id)),None)
        data["source_signatures"]=round_signatures(round_) if round_ else {}
        self._change(model,lambda s:s.setdefault("rounds",{}).__setitem__(str(round_id),data))

    def save_hole(self,model,round_id,hole,values):
        feet=numeric(values.get("first_putt_feet"),"first-putt distance in feet",0.1,500)
        data={"first_putt_feet":feet,"first_putt_bin":putt_bin(feet) if feet is not None else choice(values.get("first_putt_bin","Not recorded"),PUTT_BINS,"first-putt distance bin"),
              "distance_basis":choice(values.get("distance_basis","Not supplied"),("Not supplied","Estimated","Measured"),"distance basis"),
              "penalty_phase":choice(values.get("penalty_phase","Unknown"),PENALTY_PHASES,"penalty phase"),
              "penalty_reason":choice(values.get("penalty_reason","Unknown"),PENALTY_REASONS,"penalty reason"),
              "missed_short_return":bool(values.get("missed_short_return",False)),"note":str(values.get("note","")).strip()[:1500]}
        data["strokes_from_first_putt"]=numeric(values.get("strokes_from_first_putt"),"total strokes from first putt through hole-out",1,30,True)
        if feet is not None and data["distance_basis"]=="Not supplied":
            raise ValueError("Say whether the first-putt distance was estimated or measured.")
        round_=next((r for r in model.rounds if r["id"]==str(round_id)),None)
        source_hole=next((h for h in round_["holes"] if str(h["number"])==str(hole)),None) if round_ else None
        data["source_signature"]=hole_signature(round_,source_hole) if source_hole else None
        self._change(model,lambda s:s.setdefault("holes",{}).setdefault(str(round_id),{}).__setitem__(str(hole),data))

    def save_shot(self,model,round_id,shot_key,values):
        start=numeric(values.get("start_yards"),"start distance in yards",0.01,1200)
        end=numeric(values.get("end_yards"),"end distance in yards",0,1200)
        holed=bool(values.get("holed",False))
        if end==0 and not holed:
            raise ValueError("Zero remaining distance requires an explicitly holed shot.")
        verified=bool(values.get("states_verified",False))
        start_lie=values.get("start_lie","Unknown")
        end_lie=values.get("end_lie","Unknown")
        if verified and (start is None or start_lie not in LIES or not holed and (end is None or end_lie not in LIES)):
            raise ValueError("Verified shot states need start distance/lie and end distance/lie, or an explicitly holed finish.")
        data={"intent":choice(values.get("intent","Unknown"),INTENTS,"shot intent"),
              "target":choice(values.get("target","Unknown"),("Unknown","Safe center","Flag","Landing zone","Other"),"intended target"),
              "conditions":choice(values.get("conditions","Unknown"),CONDITIONS,"conditions"),
              "review_status":choice(values.get("review_status","Unchecked"),CHECK_STATUSES,"review status"),
              "start_yards":start,"end_yards":0 if holed else end,"start_lie":choice(start_lie,("Unknown",)+LIES,"start lie"),
              "end_lie":choice(end_lie,("Unknown",)+LIES,"end lie"),"holed":holed,"states_verified":verified,
              "penalty_strokes":numeric(values.get("penalty_strokes"),"immediate penalty strokes",0,4,True),
              "note":str(values.get("note","")).strip()[:1500]}
        round_=next((r for r in model.rounds if r["id"]==str(round_id)),None)
        source=next(((h,s) for h,s,key in usable_shots(round_) if key==str(shot_key)),None) if round_ else None
        if verified and source is None:
            raise ValueError("Choose a shot present in the imported game before verifying its states.")
        data["source_signature"]=shot_signature(round_,*source) if source else None
        self._change(model,lambda s:s.setdefault("shots",{}).setdefault(str(round_id),{}).__setitem__(str(shot_key),data))

    def save_review(self,model,item_key,status):
        choice(status,CHECK_STATUSES,"review status")
        self._change(model,lambda s:s.setdefault("reviews",{}).__setitem__(str(item_key),status))

    def add_practice(self,model,values):
        role=choice(values.get("role"),("Full swing","Controlled pitch","Chip trial"),"practice role")
        day=str(values.get("date") or date.today().isoformat())
        try:
            if date.fromisoformat(day).isoformat()!=day:
                raise ValueError
        except ValueError:
            raise ValueError("Use YYYY-MM-DD for the practice date.") from None
        carry=numeric(values.get("carry_yards"),"measured carry in yards",0,450)
        if role!="Chip trial" and carry is None:
            raise ValueError("Enter measured carry for a full-swing or controlled-pitch attempt. Do not substitute total GPS length.")
        club=str(values.get("club_id") or "")
        if not club or club=="0" or club not in model.clubs:
            raise ValueError("Choose an imported named club for this practice record.")
        if not str(values.get("session","")).strip():
            raise ValueError("Give this matched session / target a label so unrelated attempts are not silently pooled.")
        if role=="Chip trial" and not str(values.get("lie","")).strip():
            raise ValueError("Describe the chip-trial lie so matched comparisons remain meaningful.")
        data={"id":uuid.uuid4().hex,"date":day,"club_id":club,"role":role,"session":str(values.get("session","")).strip()[:100],
              "lie":str(values.get("lie","")).strip()[:80],"conditions":choice(values.get("conditions","Unknown"),CONDITIONS,"conditions"),
              "contact":choice(values.get("contact","Normal attempt"),("Normal attempt","Mishit","Tracking error"),"contact tag"),
              "carry_yards":carry,"lateral_yards":numeric(values.get("lateral_yards"),"lateral miss in yards",-300,300),
              "on_green":choice(values.get("on_green","Unknown"),("Unknown","Yes","No"),"on-green result"),
              "finish_feet":numeric(values.get("finish_feet"),"finish distance in feet",0,500),
              "strokes_to_finish":numeric(values.get("strokes_to_finish"),"total strokes including the chip",1,15,True)}
        self._change(model,lambda s:s.setdefault("practice",[]).append(data))
        return data["id"]

    def delete_practice(self,model,record_id):
        self._change(model,lambda s:s.__setitem__("practice",[r for r in s.get("practice",[]) if r.get("id")!=record_id]))

    def save_baseline(self,model,reference):
        self._change(model,lambda s:s.__setitem__("baseline",reference))
