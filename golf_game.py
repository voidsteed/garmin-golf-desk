"""Tee, putting and wedge statistics with separate shot roles and coverage."""

from collections import Counter
from statistics import median

from golf_data import average, number, percent, shot_finish


def full_game_snapshot(model, selected=None):
    rounds = model.latest_three if selected is None else selected
    tee, wedges, putting = {}, {}, []
    ambiguous = 0
    coverage = sum(r["shot_holes"] for r in rounds)
    expected = sum(r["holes_completed"] or 0 for r in rounds)
    for r in rounds:
        hole_meta = {h["number"]:h for h in r["holes"]}
        seen = set()
        for hole in r["shots"].get("holeShots",[]):
            valid = []
            for shot in hole.get("shots",[]):
                if not isinstance(shot,dict) or shot.get("excludeFromStats") or shot.get("autoShotType") not in (None,"USED"):
                    continue
                key = shot.get("id")
                if key is not None:
                    if key in seen:
                        continue
                    seen.add(key)
                valid.append(shot)
            tees = [s for s in valid if s.get("shotType")=="TEE" or (str((s.get("startLoc") or {}).get("lie") or "").casefold()=="teebox" and s.get("shotOrder")==1)]
            metadata = hole_meta.get(hole.get("holeNumber"),{})
            eligible_fw = metadata.get("par") is not None and metadata["par"]>=4
            if len(tees)>1 and eligible_fw:
                ambiguous += 1
            for shot in tees:
                key = str(shot.get("clubId") or 0)
                row = tee.setdefault(key,{"id":key,"tee_shots":0,"lengths":[],"hit":0,"left":0,"right":0,"unknown":0,"par3_tees":0})
                row["tee_shots"] += 1
                length = number(shot.get("meters"))
                if length is not None and length>0:
                    row["lengths"].append(length/0.9144)
                if metadata.get("par")==3:
                    row["par3_tees"] += 1
                if eligible_fw and len(tees)==1:
                    outcome = {"HIT":"hit","LEFT":"left","RIGHT":"right"}.get(metadata.get("fairwayShotOutcome"),"unknown")
                    row[outcome] += 1
            for shot in valid:
                key = str(shot.get("clubId") or 0)
                kind = model.clubs.get(key,{}).get("clubTypeId")
                if str(kind) not in {"19","20","21","22"}:
                    continue
                row = wedges.setdefault(key,{"id":key,"approach":Counter(),"chip":Counter(),"other":0,"approach_lengths":[],"chip_lengths":[]})
                role = {"APPROACH":"approach","CHIP":"chip"}.get(shot.get("shotType"))
                if role is None:
                    row["other"] += 1
                    continue
                row[role]["shots"] += 1
                row[role][shot_finish(shot)] += 1
                length = number(shot.get("meters"))
                if length is not None and length>=0:
                    row[role+"_lengths"].append(length/0.9144)
        counts = Counter()
        for hole in r["holes"]:
            putts = number(hole.get("putts"))
            if putts is not None and putts>=0:
                counts["tracked"] += 1
                counts["sum"] += putts
                counts["zero" if putts==0 else "one" if putts==1 else "two" if putts==2 else "three_plus"] += 1
                if putts>=4:
                    counts["four_plus"] += 1
        putting.append({"date":r["date"],"sort_date":r["sort_date"],"round_id":r["id"],"course":r["course"],"putts":r["putts"],"holes":r["holes_completed"],
                        "tracked":counts["tracked"],"tracked_sum":counts["sum"],"one":counts["one"],"two":counts["two"],
                        "three_plus":counts["three_plus"],"four_plus":counts["four_plus"],
                        "putts_per_hole":counts["sum"]/counts["tracked"] if counts["tracked"] else None})
    tee_rows = []
    for key,row in tee.items():
        label,origin = model.club_label(key)
        recorded = row["hit"]+row["left"]+row["right"]
        tee_rows.append({**row,"label":label,"label_source":origin,"fw_recorded":recorded,
                         "fw_percent":percent(row["hit"],recorded),"average_yards":average(row["lengths"]),
                         "median_yards":median(row["lengths"]) if row["lengths"] else None,
                         "driver":str(model.clubs.get(key,{}).get("clubTypeId"))=="1"})
    tee_rows.sort(key=lambda x:(not x["driver"],-x["tee_shots"],x["label"]))
    for key,club in model.clubs.items():
        if str(club.get("clubTypeId")) in {"19","20","21","22"} and not club.get("retired") and not club.get("deleted"):
            wedges.setdefault(key,{"id":key,"approach":Counter(),"chip":Counter(),"other":0,"approach_lengths":[],"chip_lengths":[]})
    wedge_rows = []
    for key,row in wedges.items():
        label,origin = model.club_label(key)
        item = {**row,"label":label,"label_source":origin}
        for role in ("approach","chip"):
            known = row[role]["green"]+row[role]["miss"]
            item[role+"_green_percent"] = percent(row[role]["green"],known)
            item[role+"_average_yards"] = average(row[role+"_lengths"])
        wedge_rows.append(item)
    wedge_rows.sort(key=lambda x:-(x["approach"]["shots"]+x["chip"]["shots"]))
    tracked = sum(x["tracked"] for x in putting)
    three_complete = [x["three_plus"] for x in putting if x["tracked"]==x["holes"] and x["holes"]==18]
    fw_hit = sum(r["fairways_hit"] or 0 for r in rounds if r["fairways_recorded"])
    fw_total = sum(r["fairways_recorded"] or 0 for r in rounds)
    putting_kind = 18 if any(r["holes_completed"]==18 for r in rounds) else 9
    return {"tee":tee_rows,"wedges":wedge_rows,"putting":putting,"shot_holes":coverage,"expected_holes":expected,
            "ambiguous_tee_holes":ambiguous,"fairway_percent":percent(fw_hit,fw_total),
            "average_putts":average([r["putts"] for r in rounds if r["holes_completed"]==putting_kind]),"average_putts_holes":putting_kind,"three_putts_per_full_round":average(three_complete),
            "tracked_putting_holes":tracked,"putts_per_tracked_hole":sum(x["tracked_sum"] for x in putting)/tracked if tracked else None,
            "chip_shots":sum(x["chip"]["shots"] for x in wedge_rows),"wedge_approaches":sum(x["approach"]["shots"] for x in wedge_rows)}
