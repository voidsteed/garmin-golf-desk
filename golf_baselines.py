"""User-supplied expected-strokes references; no proprietary baseline is bundled."""

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from golf_research_store import LIES,numeric


@dataclass(frozen=True)
class StrokeReference:
    name: str
    population: str
    source: str
    points: tuple[tuple[str,float,float],...]

    @classmethod
    def from_csv(cls,path: Path,name,population,source,permission_confirmed=False):
        if not permission_confirmed:
            raise ValueError("Confirm you have permission to use this reference privately.")
        if any(not isinstance(v,str) or not v.strip() for v in (name,population,source)):
            raise ValueError("Give the reference a name, population/handicap label, and source/provenance.")
        if path.stat().st_size>2_000_000:
            raise ValueError("Reference CSV files must be smaller than 2 MB.")
        reader=csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig")))
        if not {"lie","distance_yards","expected_strokes"}.issubset(reader.fieldnames or []):
            raise ValueError("Use columns lie,distance_yards,expected_strokes. All distances, including green distances, are in yards.")
        points=[]
        for row in reader:
            if len(points)>=5000:
                raise ValueError("A reference may contain at most 5000 rows.")
            lie=str(row["lie"]).strip().title()
            if lie not in LIES:
                raise ValueError("Reference lies must be Tee, Fairway, Rough, Bunker, Green, or Recovery.")
            distance=numeric(row["distance_yards"],"reference distance",0.001,1200)
            expected=numeric(row["expected_strokes"],"expected strokes for a non-holed state",1,20)
            if distance is None or expected is None:
                raise ValueError("Every reference row needs a distance and expected-strokes value.")
            points.append((lie,distance,expected))
        reference=cls(str(name).strip()[:120],str(population).strip()[:100],str(source).strip()[:500],tuple(points))
        reference.validate()
        return reference

    def validate(self):
        if not self.points:
            raise ValueError("The reference contains no data.")
        grouped={}
        for lie,distance,value in self.points:
            if lie not in LIES or numeric(distance,"reference distance",0.001,1200) is None or numeric(value,"expected strokes",1,20) is None:
                raise ValueError("The reference contains an invalid row.")
            grouped.setdefault(lie,[]).append((distance,value))
        for lie,rows in grouped.items():
            rows.sort()
            if len(rows)<2 or len({d for d,_ in rows})!=len(rows):
                raise ValueError(f"Provide at least two distinct distances for {lie}, without duplicates.")
            if any(b[1]<a[1] for a,b in zip(rows,rows[1:])):
                raise ValueError(f"Expected strokes must not decrease with distance within {lie}; inspect or clean this reference first.")

    def lookup(self,distance_yards,lie,holed=False):
        if holed:
            return 0.0
        distance=numeric(distance_yards,"distance in yards",0.001,1200)
        if distance is None or lie not in LIES:
            raise ValueError("A known non-holed state needs a positive distance and recognized lie.")
        rows=sorted((d,v) for l,d,v in self.points if l==lie)
        if not rows or distance<rows[0][0] or distance>rows[-1][0]:
            raise ValueError(f"No supported {lie} reference at that distance. Extrapolation is disabled.")
        for d,v in rows:
            if distance==d:
                return v
        for (d1,v1),(d2,v2) in zip(rows,rows[1:]):
            if d1<=distance<=d2:
                return v1+(v2-v1)*(distance-d1)/(d2-d1)
        raise ValueError("Reference lookup was not supported.")

    def shot_value(self,start_yards,start_lie,end_yards,end_lie,penalty=0,holed=False):
        penalty=numeric(penalty,"immediate penalty strokes",0,4,True)
        if penalty is None:
            raise ValueError("Enter the immediate penalty explicitly, including zero.")
        return self.lookup(start_yards,start_lie)-1-penalty-self.lookup(end_yards,end_lie,holed)

    def to_dict(self):
        return {"name":self.name,"population":self.population,"source":self.source,"points":[list(p) for p in self.points]}

    @classmethod
    def from_dict(cls,data):
        if data is None:
            return None
        if not isinstance(data,dict) or any(not isinstance(data.get(k),str) or not data[k].strip() for k in ("name","population","source")) or not isinstance(data.get("points"),list) or len(data["points"])>5000:
            raise ValueError("The saved reference is incomplete.")
        points=tuple((str(p[0]),numeric(p[1],"reference distance",0.001,1200),numeric(p[2],"expected strokes",1,20)) for p in data["points"] if isinstance(p,(list,tuple)) and len(p)==3)
        if len(points)!=len(data["points"]):
            raise ValueError("The saved reference contains malformed rows.")
        result=cls(str(data["name"]),str(data.get("population","")),str(data["source"]),points)
        result.validate()
        return result
