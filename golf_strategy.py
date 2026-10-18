"""Conservative target-zone guidance, never a fabricated live-hole optimum."""

import math

from golf_game import full_game_snapshot


def optional_distance(value, name, maximum):
    if value is None or value=="":
        return None
    if isinstance(value,bool):
        raise ValueError(f"Enter a positive {name}.")
    try:
        result = float(value)
    except (ValueError,TypeError):
        raise ValueError(f"Enter a numeric {name}, or leave it blank.") from None
    if not math.isfinite(result) or not 0<result<=maximum:
        raise ValueError(f"Enter a positive {name} no greater than {maximum}.")
    return result


def build_shot_plan(model, phase="tee", club_id=None, hazard="Not supplied", conditions="Not supplied", target=None, carry=None, hazard_carry=None, putt=None, break_direction="Not supplied", wedge_role="Approach / pitch", pin="Not supplied"):
    if phase not in {"tee","approach","wedge","putting"}:
        raise ValueError("Choose tee, approach, wedge, or putting.")
    target = optional_distance(target,"target distance in yards",600)
    carry = optional_distance(carry,"normal carry in yards",450)
    hazard_carry = optional_distance(hazard_carry,"required hazard carry in yards",600)
    putt = optional_distance(putt,"putt length in feet",500)
    club = str(club_id or 0)
    name = model.club_label(club)[0]
    rounds = model.full_rounds[:3]
    game = full_game_snapshot(model,rounds)
    evidence, checks = [],[]
    miss_side = {"Left":"right-center","Right":"left-center","Short / front":"center with reliable clearance","Long / back":"front-center with room","Both sides":"widest safe center"}.get(hazard,"widest safe center")
    layup = phase!="putting" and carry is not None and hazard_carry is not None and carry<hazard_carry
    if phase=="tee":
        aim = f"Aim at the {miss_side} of a safe landing corridor, not automatically at the flag or the shortest route."
        decision = "Choose the club whose normal shot pattern fits that corridor. A shorter club is useful only if it actually reduces penalty risk."
        miss = "Accept a longer next shot rather than bringing a penalty area into your normal miss. After trouble, take one safe recovery."
        practice = "On the range, compare driver and your safer alternative by dispersion, not just the best or longest shot."
        row = next((r for r in game["tee"] if r["id"]==club),None)
        if row:
            evidence.append(f"Recent attributed {name} tees: {row['hit']}/{row['fw_recorded']} fairways, {row['left']} left and {row['right']} right. The sample may be incomplete.")
            if row["average_yards"] is not None:
                evidence.append(f"Recorded tee length averages {row['average_yards']:.0f} yd including roll. This is NOT a normal carry distance.")
    elif phase=="approach":
        aim = f"Aim at the {miss_side} of the green’s safe landing area. Favor the broad part of the green over an edge flag."
        decision = "Use reliable carry to reach that safe area. Do not choose a club from your longest tracked shot or an average that includes roll."
        miss = "Choose the unpenalized miss with room for a simple next shot. From a poor lie, enlarge the target or lay up instead of forcing the green."
        practice = "Check normal carry and strike consistency with this club, then practice to a broad green-sized target."
        row = next((r for r in model.approach_analysis(rounds)["clubs"] if r["id"]==club),None)
        if row:
            evidence.append(f"Recent {name} approaches: {row['green']} on green, {row['miss']} off green, {row['unknown']} unknown, from {row['approaches']} recorded shots. Small samples do not prove a swing fault.")
    elif phase=="wedge":
        if wedge_role=="Greenside chip":
            aim = "Pick a clear landing spot on the green first, then allow the ball to roll toward the hole. Do not aim every chip straight at the cup."
            decision = "With clear ground and enough green, consider a putter or lower-running chip. Use more loft when you must carry rough, a bunker, or an obstacle."
            miss = "Your first requirement is to finish on the green and leave a putt. Avoid the high-risk lofted shot when a simpler option fits."
            practice = "Practice the same landing spot with a lower-running club and your lofted wedge; compare how predictable the finish is."
        else:
            aim = f"Aim at the {miss_side} of the green, with enough margin to land on it. Do not chase a tucked flag just because you have a wedge."
            decision = "Use a rehearsed wedge swing with a known carry. A mixed average of chips and pitches is not a full-swing wedge distance."
            miss = "Keep the normal short or long miss out of penalties. If carry or contact is uncertain, choose a larger landing area."
            practice = "Build a simple carry chart for controlled partial swings using real practice shots, not on-course total-distance averages."
        row = next((r for r in game["wedges"] if r["id"]==club),None)
        if row:
            evidence.append(f"Recent {name} records: {row['approach']['shots']} approaches and {row['chip']['shots']} chips. Those roles are measured separately.")
    else:
        long_putt = putt is None or putt>20
        start = {"Breaks left":"right/high side of the hole","Breaks right":"left/high side of the hole","Straight":"center of the cup"}.get(break_direction)
        aim = f"Start the ball toward the {start}, using the break you read on the green." if start else "Read the green and choose a start line that matches your intended pace. Old scorecards cannot tell the app the current break."
        decision = "Prioritize distance control and a finish within roughly two to three feet, rather than an aggressive hole-out attempt." if long_putt else "Choose a clear start line and controlled hole-out pace. Do not change the line to compensate for an uncommitted stroke."
        miss = "Leave the simplest possible next putt. On a fast downhill putt, favor gentle arrival speed instead of a long comeback."
        practice = "Use a 20/30/40-foot ladder, then putt every ball out from its actual finish."
        if game["three_putts_per_full_round"] is not None:
            evidence.append(f"Your latest recorded full rounds average {game['three_putts_per_full_round']:.1f} three-putt-or-worse holes. Verify tracking, then prioritize pace and short-putt conversion.")
        checks.append("The exact amount of break requires the live slope, speed and your chosen pace; no fixed inches or aim coordinates are invented here.")
    if phase!="putting":
        if carry is None:
            checks.append("Enter a reliable normal carry if you want a distance check. The app deliberately does not fill this from total shot length.")
        if target is not None and carry is not None:
            difference = target-carry
            if difference>0:
                checks.append(f"The safe target is {difference:.0f} yd beyond the carry you entered. Choose a nearer safe target, another club, or a lay-up rather than requiring your best strike.")
            elif difference<0:
                checks.append(f"Your entered carry is {-difference:.0f} yd beyond this target. Choose a suitable club or rehearsed controlled shot; check the long miss.")
            else:
                checks.append("Entered carry matches target distance, but normal shot variation and conditions still need room.")
        if hazard_carry is not None and carry is not None:
            margin = carry-hazard_carry
            checks.append(f"Normal carry is {abs(margin):.0f} yd {'short of' if margin<0 else 'beyond'} the required hazard clearance. A positive margin is not a guarantee; include your real carry variation, wind and lie.")
        if hazard=="Both sides":
            checks.append("If your usual dispersion does not fit between both hazards, choose a different landing area, lay up, or consider a more suitable tee—not a perfect-shot gamble.")
        if conditions=="Headwind":
            checks.append("Headwind: confirm adjusted playing distance and allow more carry margin. Prefer controlled contact over swinging harder.")
        elif conditions=="Tailwind":
            checks.append("Tailwind: allow for release and check where the long miss finishes. Do not assume the same stopping distance.")
        elif conditions in ("Uphill","Downhill"):
            checks.append("Confirm elevation-adjusted playing distance on your watch or from the course; no automatic yardage correction is assumed.")
        elif conditions=="Poor lie":
            checks.append("Poor lie: prioritize clean contact and a larger safe target. Avoid a forced carry or a hero recovery.")
        if pin!="Not supplied":
            checks.append(f"Pin position supplied: {pin.lower()}. Attack it only if there is room for your normal dispersion; otherwise keep the safe-center plan.")
        aggregate = next((r for r in model.aggregate_clubs(True) if r["id"]==club),None)
        if aggregate:
            sides = [(k,aggregate[k]) for k in ("short","long","left","right") if aggregate[k] is not None]
            if sides:
                side,value = max(sides,key=lambda x:x[1])
                evidence.append(f"Garmin’s aggregate {name} green-miss categories are most often {side} ({value:.1f}% of outcomes). This is not restricted to the latest three rounds or a live dispersion map.")
    if layup:
        aim = "Do not attempt this forced carry with the normal carry entered. Lay up to a genuinely safe area or select a club with enough reliable carry and margin."
    return {"phase":phase,"club":name,"aim":aim,"decision":decision,"miss":miss,"practice":practice,"checks":checks,"evidence":evidence,
            "layup":layup,"diagram":{"phase":phase,"hazard":hazard,"break":break_direction,"pin":pin,"chip":wedge_role=="Greenside chip","layup":layup,"putt":putt},
            "limit":"Schematic, rule-based target-zone guide—not a live course map, measured aim point, or guaranteed handicap improvement."}
