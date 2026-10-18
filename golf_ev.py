"""Expected-score comparisons under explicit, mutually exclusive assumptions."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Outcome:
    probability: float
    remaining_strokes: float
    penalty_strokes: float = 0


@dataclass(frozen=True)
class ShotPlan:
    name: str
    outcomes: tuple[Outcome, ...]


def validate_plan(plan):
    if len(plan.outcomes)<2:
        raise ValueError("A plan needs at least two mutually exclusive outcomes.")
    for outcome in plan.outcomes:
        values = (outcome.probability,outcome.remaining_strokes,outcome.penalty_strokes)
        if any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) for v in values):
            raise ValueError("Probabilities and stroke costs must be finite numbers.")
        if not 0<=outcome.probability<=1 or not 0<=outcome.remaining_strokes<=20 or not 0<=outcome.penalty_strokes<=4:
            raise ValueError("Probabilities must be 0–100%; remaining strokes 0–20; penalty strokes 0–4.")
    total = sum(o.probability for o in plan.outcomes)
    if not math.isclose(total,1,abs_tol=0.000001):
        raise ValueError(f"{plan.name}: outcome probabilities total {100*total:.1f}%, not 100%. Do not double-count overlapping errors.")


def expected_strokes(plan):
    validate_plan(plan)
    # The current stroke is counted exactly once. Remaining excludes that stroke
    # and the explicit immediate penalty, but includes all subsequent play.
    return 1+sum(o.probability*(o.remaining_strokes+o.penalty_strokes) for o in plan.outcomes)


def shift_error(plan, amount, error_index=2):
    validate_plan(plan)
    if not 0<error_index<len(plan.outcomes):
        raise ValueError("Choose a non-success outcome for the error stress test.")
    good,bad = plan.outcomes[0],plan.outcomes[error_index]
    amount = min(amount,good.probability) if amount>=0 else -min(-amount,bad.probability)
    values = list(plan.outcomes)
    values[0] = Outcome(good.probability-amount,good.remaining_strokes,good.penalty_strokes)
    values[error_index] = Outcome(bad.probability+amount,bad.remaining_strokes,bad.penalty_strokes)
    return ShotPlan(plan.name,tuple(values))


def plan_sensitivity(plan,error_radius=0.05,remaining_uncertainty=0.25,error_index=2):
    validate_plan(plan)
    if not math.isfinite(error_radius) or not 0<=error_radius<=0.5 or not math.isfinite(remaining_uncertainty) or not 0<=remaining_uncertainty<=3:
        raise ValueError("Error uncertainty must be 0–50 percentage points and remaining-stroke uncertainty 0–3.")
    lows,highs = [],[]
    for shift in (-error_radius,0,error_radius):
        scenario = shift_error(plan,shift,error_index)
        lows.append(1+sum(o.probability*(max(0,o.remaining_strokes-remaining_uncertainty)+o.penalty_strokes) for o in scenario.outcomes))
        highs.append(1+sum(o.probability*((o.remaining_strokes+remaining_uncertainty if o.remaining_strokes>0 else 0)+o.penalty_strokes) for o in scenario.outcomes))
    return {"name":plan.name,"expected":expected_strokes(plan),"low":min(lows),"high":max(highs),
            "higher_error_expected":expected_strokes(shift_error(plan,error_radius,error_index))}


def compare_plans(baseline,alternative,error_radius=0.05,remaining_uncertainty=0.25,error_index=2):
    first = plan_sensitivity(baseline,error_radius,remaining_uncertainty,error_index)
    second = plan_sensitivity(alternative,error_radius,remaining_uncertainty,error_index)
    best = first if first["expected"]<=second["expected"] else second
    robust = first["name"] if first["high"]<second["low"] else second["name"] if second["high"]<first["low"] else None
    return {"baseline":first,"alternative":second,"best_estimate":best["name"],
            "alternative_ev":first["expected"]-second["expected"],
            "ev_low":first["low"]-second["high"],"ev_high":first["high"]-second["low"],
            "robust_preference":robust,"kind":"User-assumption sensitivity range, not a statistical confidence interval"}
