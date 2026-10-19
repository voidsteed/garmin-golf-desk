"""Transparent practice targets, not estimated strokes gained or swing diagnoses."""

from golf_data import GolfSnapshot


def improvement_snapshot(model: GolfSnapshot, latest_three: bool = True, selected=None) -> dict:
    selected = (model.full_rounds[:3] if latest_three else model.full_rounds) if selected is None else selected
    full = [r for r in selected if r["holes_completed"]==18 and not r["in_progress"]]
    metrics = model.metrics(full)
    priorities = [
        {"key": "three_putts", "label": "Three-putt+ holes", "current": metrics["three_putts"], "goal": 2.0,
         "practice": "Putting pace: practise from 20, 30 and 40 feet, finishing inside three feet. Check that putts were tracked correctly."},
        {"key": "penalties", "label": "Recorded penalties", "current": metrics["penalties"], "goal": 1.0,
         "practice": "Keep it in play: pick a club and target that keep your normal miss away from penalty areas. Take the safe recovery."},
        {"key": "big_holes", "label": "Double-bogey+ holes", "current": metrics["big_holes"], "goal": 3.0,
         "practice": "Limit the big number: after trouble, choose the highest-percentage next shot rather than trying to win the lost stroke back."},
    ]
    priorities.sort(key=lambda p: (p["current"] is not None, max(0, p["current"]-p["goal"]) if p["current"] is not None else -1), reverse=True)
    approaches = model.approach_analysis(selected)
    known = [row for row in approaches["clubs"] if not row["unassigned"]]
    return {"rounds": full, "selected_rounds": selected, "metrics": metrics, "priorities": priorities, "approaches": approaches,
            "top_club": known[0] if known else None,
            "partial_penalty_tracking": any(r["penalty_coverage"] < r["holes_completed"] for r in selected)}
