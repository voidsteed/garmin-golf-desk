"""Offline golf analytics with explicit sample sizes and missing-data handling."""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from golf_clubs import GARMIN_CLUB_TYPE_NAMES


def number(value: Any) -> float | int | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def percent(hit: Any, total: Any) -> float | None:
    return 100 * hit / total if number(hit) is not None and number(total) is not None and total > 0 else None


def average(values: list[Any]) -> float | None:
    valid = [x for x in values if number(x) is not None]
    return statistics.mean(valid) if valid else None


def shot_finish(shot: dict[str, Any]) -> str:
    lie = str((shot.get("endLoc") or {}).get("lie") or "Unknown")
    normalized = "".join(c for c in lie.casefold() if c.isalnum())
    if normalized in ("green", "puttinggreen"):
        return "green"
    if normalized in {"rough", "fairway", "bunker", "sand", "water", "hazard", "fringe", "outofbounds", "teebox", "woods", "wastearea", "cartpath"}:
        return "miss"
    return "unknown"


def account_ids(data: dict[str, Any]) -> frozenset[str]:
    golf = data.get("golf", {})
    ids = {str(x["playerProfileId"]) for x in golf.get("scorecard_summaries", []) if isinstance(x, dict) and x.get("playerProfileId") not in (None, "")}
    if not ids:
        for entry in golf.get("scorecards", []):
            detail = entry.get("detail") if isinstance(entry, dict) else None
            if isinstance(detail, dict):
                for item in detail.get("scorecardDetails", []):
                    value = item.get("scorecard", {}).get("playerProfileId")
                    if value not in (None, ""):
                        ids.add(str(value))
    return frozenset(ids)


def read_export(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 50_000_000:
        raise ValueError("This export is too large to open safely.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("golf"), dict):
        raise ValueError("Choose a Golf Desk JSON export.")
    for key in ("scorecard_summaries", "scorecards"):
        if not isinstance(data["golf"].get(key, []), list):
            raise ValueError("This golf export has an unsupported structure.")
    return data


def catalog_labels(payload: Any) -> dict[str, str]:
    if isinstance(payload, dict):
        payload = payload.get("clubTypes", payload.get("types", payload.get("items", payload.get("data", []))))
    result = {}
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict) or item.get("valid") is False:
                continue
            key = item.get("clubTypeId", item.get("id", item.get("value")))
            label = item.get("name", item.get("displayName", item.get("label")))
            if key is not None and isinstance(label, str) and label.strip():
                result[str(key)] = label.strip()
    return result


def parse_round(summary: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    key = str(summary.get("id", summary.get("scorecardId", entry.get("scorecard_id", ""))))
    detail = entry.get("detail") if isinstance(entry.get("detail"), dict) else {}
    matching = [x for x in detail.get("scorecardDetails", []) if isinstance(x, dict) and str(x.get("scorecard", {}).get("id")) == key]
    record = matching[0] if matching else {}
    card = record.get("scorecard", {})
    stats = record.get("scorecardStats", {}).get("round", {})
    snapshots = detail.get("courseSnapshots", [])
    course = next((x for x in snapshots if x.get("courseSnapshotId") == card.get("courseSnapshotId")), snapshots[0] if snapshots else {})
    pars = summary.get("holePars", course.get("holePars", ""))
    pars = [int(x) for x in pars] if isinstance(pars, str) and pars.isdigit() else []
    merged_holes = {h["number"]: dict(h) for h in summary.get("holes", []) if isinstance(h, dict) and isinstance(h.get("number"), int)}
    for hole in card.get("holes", []):
        if isinstance(hole, dict) and isinstance(hole.get("number"), int):
            merged_holes.setdefault(hole["number"], {}).update(hole)
    holes = []
    for n, raw in sorted(merged_holes.items()):
        par = pars[n - 1] if 1 <= n <= len(pars) else None
        strokes = number(raw.get("strokes"))
        holes.append({**raw, "number": n, "par": par, "to_par": strokes - par if strokes is not None and par is not None else None})
    completed = card.get("holesCompleted", summary.get("holesCompleted", len(holes)))
    par = sum(h["par"] for h in holes) if holes and len(holes) == completed and all(h["par"] is not None for h in holes) else sum(pars) if len(pars) == completed and pars else None
    strokes = number(card.get("strokes", summary.get("strokes")))
    putt_coverage = sum(number(h.get("putts")) is not None for h in holes)
    penalty_coverage = sum(number(h.get("penalties")) is not None for h in holes)
    putts = number(stats.get("putts"))
    if putts is None and holes and putt_coverage == len(holes):
        putts = sum(h["putts"] for h in holes)
    fw_recorded = number(stats.get("fairwaysRecorded"))
    fw_hit = number(stats.get("fairwaysHit"))
    if not fw_recorded:
        outcomes = [h.get("fairwayShotOutcome") for h in holes if h.get("fairwayShotOutcome") in ("HIT", "LEFT", "RIGHT")]
        fw_recorded, fw_hit = (len(outcomes), outcomes.count("HIT")) if outcomes else (None, None)
    shots = entry.get("shots") if isinstance(entry.get("shots"), dict) else {}
    shot_holes = {h.get("holeNumber") for h in shots.get("holeShots", []) if isinstance(h, dict) and h.get("shots")}
    date = str(card.get("formattedStartTime", card.get("startTime", summary.get("startTime", ""))))
    return {
        "id": key, "date": date[:10], "sort_date": str(summary.get("startTime", date)),
        "course": summary.get("courseName", course.get("name", "Unnamed course")),
        "holes_completed": completed, "in_progress": bool(card.get("inProgress", summary.get("roundInProgress", False))),
        "score": strokes, "par": par, "to_par": strokes - par if strokes is not None and par is not None else None,
        "fairways_hit": fw_hit, "fairways_recorded": fw_recorded,
        "greens_hit": number(stats.get("greensInRegulation")), "greens_recorded": number(stats.get("greensRecorded")),
        "putts": putts, "putt_coverage": putt_coverage,
        "penalties": sum(h.get("penalties", 0) for h in holes if number(h.get("penalties")) is not None) if penalty_coverage else None,
        "penalty_coverage": penalty_coverage,
        "three_putts": sum(h.get("putts", 0) >= 3 for h in holes if number(h.get("putts")) is not None) if putt_coverage else None,
        "big_holes": [h for h in holes if h["to_par"] is not None and h["to_par"] >= 2],
        "holes": holes, "shots": shots, "shot_holes": len(shot_holes),
        "course_rating":number(card.get("teeBoxRating")),"slope_rating":number(card.get("teeBoxSlope")),"tee_box":str(card.get("teeBox") or ""),
    }


@dataclass
class GolfSnapshot:
    rounds: list[dict[str, Any]] = field(default_factory=list)
    clubs: dict[str, dict[str, Any]] = field(default_factory=dict)
    user_stats: dict[str, Any] = field(default_factory=dict)
    type_labels: dict[str, str] = field(default_factory=dict)
    local_labels: dict[str, str] = field(default_factory=dict)
    sources: list[Path] = field(default_factory=list)
    source_errors: list[dict[str, str]] = field(default_factory=list)
    latest_import: str = ""
    skipped_files: int = 0
    account_identities: frozenset[str] = frozenset()

    @property
    def full_rounds(self) -> list[dict[str, Any]]:
        return [r for r in self.rounds if r["holes_completed"] == 18 and not r["in_progress"] and r["score"] is not None]

    @property
    def latest_three(self) -> list[dict[str, Any]]:
        return [r for r in self.rounds if not r["in_progress"]][:3]

    def club_label(self, club_id: Any) -> tuple[str, str]:
        key = str(club_id)
        if key in ("0", "None", ""):
            return "Unassigned club", "No club was recorded"
        if self.local_labels.get(key):
            return self.local_labels[key], "Local label"
        club = self.clubs.get(key, {})
        if isinstance(club.get("name"), str) and club["name"].strip():
            return club["name"].strip(), "Garmin custom name"
        kind = str(club.get("clubTypeId", "?"))
        if kind in self.type_labels:
            return self.type_labels[kind], "Garmin type catalog"
        if kind in GARMIN_CLUB_TYPE_NAMES:
            return GARMIN_CLUB_TYPE_NAMES[kind], "Garmin standard club type"
        return "Unknown club", "Garmin did not provide a recognized club type"

    def metrics(self, selected: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        rounds = self.full_rounds if selected is None else [r for r in selected if r["holes_completed"] == 18 and not r["in_progress"] and r["score"] is not None]
        fw_hit = sum(r["fairways_hit"] or 0 for r in rounds if r["fairways_recorded"])
        fw_total = sum(r["fairways_recorded"] or 0 for r in rounds)
        gir_hit = sum(r["greens_hit"] or 0 for r in rounds if r["greens_recorded"])
        gir_total = sum(r["greens_recorded"] or 0 for r in rounds)
        return {"rounds": len(rounds), "average_score": average([r["score"] for r in rounds]),
                "average_to_par": average([r["to_par"] for r in rounds]),
                "fairways": percent(fw_hit, fw_total), "gir": percent(gir_hit, gir_total),
                "putts": average([r["putts"] for r in rounds]), "penalties": average([r["penalties"] for r in rounds]),
                "three_putts": average([r["three_putts"] if r["putt_coverage"] >= r["holes_completed"] else None for r in rounds]),
                "big_holes": average([len(r["big_holes"]) if len(r["holes"]) >= r["holes_completed"] and all(h["to_par"] is not None for h in r["holes"]) else None for r in rounds]),
                "best": min((r["score"] for r in rounds), default=None)}

    def aggregate_clubs(self, include_retired: bool = False) -> list[dict[str, Any]]:
        rows = []
        for key, club in self.clubs.items():
            if club.get("deleted") or club.get("retired") and not include_retired:
                continue
            stat = club.get("clubStats") or {}
            green = number(stat.get("percentGreenHit"))
            if green is None:
                continue
            label, origin = self.club_label(key)
            rows.append({"id": key, "label": label, "label_source": origin, "retired": bool(club.get("retired")),
                         "green_percent": green, "miss_percent": 100 - green,
                         "short": number(stat.get("percentGreenMissShort")), "long": number(stat.get("percentGreenMissLong")),
                         "left": number(stat.get("percentGreenMissLeft")), "right": number(stat.get("percentGreenMissRight")),
                         "all_shots": number(stat.get("shotsCount"))})
        return sorted(rows, key=lambda x: (x["green_percent"], x["label"]))

    def approach_analysis(self, selected: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        rounds = selected if selected is not None else self.latest_three
        rows = []
        grouped: dict[str, Counter] = {}
        shot_holes = sum(r["shot_holes"] for r in rounds)
        expected_holes = sum(r["holes_completed"] or 0 for r in rounds)
        for round_ in rounds:
            seen=set()
            for hole in round_["shots"].get("holeShots", []):
                for shot in hole.get("shots", []):
                    if not isinstance(shot, dict) or shot.get("shotType") != "APPROACH" or shot.get("excludeFromStats") or shot.get("autoShotType") not in (None, "USED"):
                        continue
                    shot_id=shot.get("id")
                    if isinstance(shot_id,(int,str)):
                        if shot_id in seen:
                            continue
                        seen.add(shot_id)
                    club = str(shot.get("clubId") or 0)
                    start, end = shot.get("startLoc") or {}, shot.get("endLoc") or {}
                    lie = str(end.get("lie") or "Unknown")
                    outcome = shot_finish(shot)
                    label, origin = self.club_label(club)
                    row = {"club_id": club, "club": label, "label_source": origin, "round_id": round_["id"], "course": round_["course"],
                           "date": round_["date"], "hole": hole.get("holeNumber"), "outcome": outcome, "end_lie": lie,
                           "start_lie": str(start.get("lie") or "Unknown"), "meters": number(shot.get("meters"))}
                    rows.append(row)
                    counter = grouped.setdefault(club, Counter())
                    counter["approaches"] += 1
                    counter[outcome] += 1
        clubs = []
        for key, counter in grouped.items():
            label, origin = self.club_label(key)
            known = counter["green"] + counter["miss"]
            clubs.append({"id": key, "label": label, "label_source": origin, **{k: counter[k] for k in ("approaches", "green", "miss", "unknown")},
                          "green_percent": percent(counter["green"], known), "unassigned": key == "0"})
        clubs.sort(key=lambda x: (x["unassigned"], -x["miss"], -x["approaches"]))
        return {"clubs": clubs, "shots": rows, "shot_holes": shot_holes, "expected_holes": expected_holes,
                "approaches": len(rows), "unassigned": sum(r["club_id"] == "0" for r in rows),
                "unknown_outcomes": sum(r["outcome"] == "unknown" for r in rows),
                "green_finishes": sum(r["outcome"] == "green" for r in rows)}


def snapshot_from_exports(exports: list[tuple[Path, dict[str, Any]]], local_labels: dict[str, str] | None = None, preferred: Path | None = None) -> GolfSnapshot:
    model = GolfSnapshot(local_labels=dict(local_labels or {}))
    if not exports:
        return model
    # Input order represents file order; the last import selects the account.
    primary = next((data for path, data in exports if path == preferred), exports[-1][1])
    identity = account_ids(primary)
    model.account_identities = identity
    matching = [(path, data) for path, data in exports if (account_ids(data) == identity and identity) or data is primary]
    model.skipped_files = len(exports) - len(matching)
    matching.sort(key=lambda item: str(item[1].get("exported_at_utc", "")))
    summaries: dict[str, dict[str, Any]] = {}
    details: dict[str, dict[str, Any]] = {}
    for path, data in matching:
        golf = data["golf"]
        model.sources.append(path)
        model.latest_import = str(data.get("exported_at_utc", model.latest_import))
        if isinstance(golf.get("user_stats"), dict) and golf["user_stats"]:
            model.user_stats = golf["user_stats"]
        clubs = golf.get("club_stats")
        if isinstance(clubs, dict):
            clubs = clubs.get("clubs", clubs.get("items", []))
        if isinstance(clubs, list):
            for club in clubs:
                if isinstance(club, dict) and club.get("id") is not None:
                    model.clubs[str(club["id"])] = club
        model.type_labels.update(catalog_labels(golf.get("club_types")))
        for summary in golf.get("scorecard_summaries", []):
            if isinstance(summary, dict) and summary.get("id", summary.get("scorecardId")) is not None:
                key = str(summary.get("id", summary.get("scorecardId")))
                summaries[key] = summary
        for entry in golf.get("scorecards", []):
            if not isinstance(entry, dict) or entry.get("scorecard_id") is None:
                continue
            key = str(entry["scorecard_id"])
            target = details.setdefault(key, {})
            for field_, value in entry.items():
                if value is not None:
                    target[field_] = value
            shots = entry.get("shots")
            if isinstance(shots, dict):
                for club in shots.get("clubDetails", []):
                    if isinstance(club, dict) and club.get("id") is not None:
                        # Keep aggregate statistics when shot metadata is minimal.
                        model.clubs.setdefault(str(club["id"]), {}).update({k: v for k, v in club.items() if k != "clubStats"})
        model.source_errors.extend(x for x in data.get("errors", []) if isinstance(x, dict))
    model.rounds = [parse_round(summary, details.get(key, {})) for key, summary in summaries.items()]
    model.rounds.sort(key=lambda r: r["sort_date"], reverse=True)
    return model


def load_snapshot(folder: Path, local_labels: dict[str, str] | None = None, preferred: Path | None = None) -> GolfSnapshot:
    entries = []
    skipped = 0
    paths = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime) if folder.exists() else []
    for path in paths:
        try:
            entries.append((path, read_export(path)))
        except (ValueError, OSError, KeyError, TypeError):
            skipped += 1
    model = snapshot_from_exports(entries, local_labels, preferred)
    model.skipped_files += skipped
    return model
