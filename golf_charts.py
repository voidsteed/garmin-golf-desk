"""Canvas charts showing actual counts and explicitly labeled aggregate categories."""

import math
import tkinter as tk

from golf_history import moving_average

WHITE, INK, MUTED = "#FFFFFF", "#15382E", "#65766D"
GREEN, MINT, AMBER, ORANGE, GREY = "#137B56", "#E4F2E9", "#C78C37", "#DBA55A", "#BAC4BD"
FONT = "Segoe UI"


def text(canvas, x, y, value, size=9, color=INK, bold=False, anchor="w", **kwargs):
    return canvas.create_text(x, y, text=value, fill=color, font=(FONT,size,"bold" if bold else "normal"), anchor=anchor, **kwargs)


def chart(parent, draw, height=260, padx=18, pady=(0,16)):
    canvas = tk.Canvas(parent,bg=WHITE,height=height,highlightthickness=0)
    canvas.pack(fill="x",padx=padx,pady=pady)
    canvas.bind("<Configure>",lambda _: draw(canvas) if canvas.winfo_width()>150 else None)
    return canvas


def draw_priorities(canvas, rows):
    canvas.delete("all")
    w = canvas.winfo_width()
    left, right = 210, w-110
    if right <= left:
        left = 155
    maximum = max(6, math.ceil(max((r["current"] or 0 for r in rows),default=0)+1))
    for i,row in enumerate(rows):
        y = 42+i*62
        text(canvas,0,y,row["label"],10,bold=True)
        canvas.create_rectangle(left,y-9,right,y+9,fill="#EDF1ED",outline="")
        if row["current"] is not None:
            end = left+(right-left)*row["current"]/maximum
            color = GREEN if row["current"]<=row["goal"] else AMBER
            canvas.create_rectangle(left,y-9,end,y+9,fill=color,outline="")
            text(canvas,right+12,y,f"{row['current']:.1f} now",10,color=color,bold=True)
        else:
            text(canvas,right+12,y,"No data",9,color=MUTED)
        goal_x = left+(right-left)*row["goal"]/maximum
        canvas.create_line(goal_x,y-15,goal_x,y+15,fill=GREEN,width=3)
        text(canvas,goal_x,y+26,f"goal {row['goal']:.0f}",8,color=GREEN,anchor="center")
    text(canvas,0,234,"Per 18-hole round · starter practice goals, not handicap benchmarks",9,color=MUTED)


def draw_approach_bars(canvas, analysis):
    canvas.delete("all")
    w = canvas.winfo_width()
    rows = [r for r in analysis["clubs"] if not r["unassigned"]][:7]
    if not rows:
        text(canvas,w/2,130,"Import detailed shots to compare approach clubs.",11,color=MUTED,anchor="center")
        return
    left, right = 130, w-120
    maximum = max(r["approaches"] for r in rows)
    for i,row in enumerate(rows):
        y = 52+i*43
        text(canvas,0,y,row["label"],10,bold=i==0,width=125)
        x = left
        canvas.create_rectangle(left,y-9,right,y+9,fill="#EDF1ED",outline="")
        for key,color in (("green",GREEN),("miss",ORANGE),("unknown",GREY)):
            end = x+(right-left)*row[key]/maximum
            if row[key]:
                canvas.create_rectangle(x,y-9,end,y+9,fill=color,outline="")
            x = end
        text(canvas,right+10,y,f"{row['miss']} off / {row['approaches']}",9,bold=i==0)
    x = 0
    for name,color in (("On green",GREEN),("Off green",ORANGE),("Unknown",GREY)):
        canvas.create_rectangle(x,10,x+10,20,fill=color,outline="")
        text(canvas,x+16,15,name,8,color=MUTED)
        x += 122
    footer = 68+43*len(rows)
    text(canvas,0,footer,f"{analysis['unassigned']} approaches have no club assigned; these are not attributed to a named club.",8,color=MUTED,width=max(250,w-10))


def draw_miss_pattern(canvas, row):
    canvas.delete("all")
    w,h = canvas.winfo_width(),canvas.winfo_height()
    if not row:
        text(canvas,w/2,h/2,"No directional club statistics available.",10,color=MUTED,anchor="center")
        return
    cx,cy = w/2,h/2
    spread = min(168,w/2-66)
    canvas.create_oval(cx-92,cy-62,cx+92,cy+62,fill=MINT,outline="#9ECBB0",width=2)
    canvas.create_line(cx,cy-28,cx,cy+8,fill=INK,width=2)
    canvas.create_polygon(cx,cy-28,cx+26,cy-20,cx,cy-10,fill=GREEN,outline="")
    canvas.create_oval(cx-5,cy+4,cx+5,cy+9,fill=INK,outline="")
    value = "—" if row["green_percent"] is None else f"{row['green_percent']:.1f}%"
    text(canvas,cx,cy+31,f"Green {value}",11,color=GREEN,bold=True,anchor="center")
    candidates = [(k,row.get(k)) for k in ("short","long","left","right") if row.get(k) is not None]
    most = max(candidates,key=lambda x:x[1])[0] if candidates else None
    locations = {"long":(cx,cy-132),"short":(cx,cy+132),"left":(cx-spread,cy),"right":(cx+spread,cy)}
    for key,(x,y) in locations.items():
        is_big = key == most
        fill = "#FFF0D7" if is_big else "#F2F5F1"
        value = row.get(key)
        value = "—" if value is None else f"{value:.1f}%"
        canvas.create_rectangle(x-56,y-28,x+56,y+28,fill=fill,outline="#E5C48D" if is_big else "#DDE7DE")
        text(canvas,x,y-10,key.capitalize(),9,bold=is_big,anchor="center")
        text(canvas,x,y+11,value,12,color="#976123" if is_big else INK,bold=True,anchor="center")


def draw_hole_heatmap(canvas, rounds):
    canvas.delete("all")
    w = canvas.winfo_width()
    rounds = rounds[:6]
    left,top = 232,38
    cell = (w-left-8)/18
    for n in range(1,19):
        text(canvas,left+(n-.5)*cell,15,str(n),9,color=MUTED,bold=True,anchor="center")
    for i,round_ in enumerate(rounds):
        y = top+i*52
        course = str(round_["course"])
        course = course if len(course)<27 else course[:25]+"…"
        text(canvas,0,y+9,round_["date"]+f"  ·  {round_['score']:.0f}",9,bold=True)
        text(canvas,0,y+28,course,8,color=MUTED)
        holes = {r["number"]:r for r in round_["holes"]}
        for n in range(1,19):
            delta = holes.get(n,{}).get("to_par")
            fill = "#EDF0ED" if delta is None else "#DCEAF5" if delta<0 else MINT if delta==0 else "#F6EDCB" if delta==1 else "#F2CCA1" if delta==2 else "#EAA79A"
            x = left+(n-1)*cell
            canvas.create_rectangle(x+2,y,x+cell-2,y+36,fill=fill,outline=WHITE)
            caption = "—" if delta is None else "E" if delta==0 else f"{delta:+.0f}"
            text(canvas,x+cell/2,y+18,caption,9,bold=delta is not None and delta>=2,anchor="center")
    y = top+len(rounds)*52+14
    x = 0
    for name,color in (("Under par","#DCEAF5"),("Par",MINT),("Bogey","#F6EDCB"),("Double","#F2CCA1"),("Triple+","#EAA79A")):
        canvas.create_rectangle(x,y,x+12,y+12,fill=color,outline="")
        text(canvas,x+18,y+6,name,8,color=MUTED)
        x += 135


def draw_tee_bars(canvas, rows):
    canvas.delete("all")
    w = canvas.winfo_width()
    eligible = [r for r in rows if r["fw_recorded"] or r["unknown"]][:7]
    x = 0
    for name,color in (("Fairway",GREEN),("Left",ORANGE),("Right","#C57452"),("Unknown",GREY)):
        canvas.create_rectangle(x,8,x+10,18,fill=color,outline="")
        text(canvas,x+16,13,name,8,color=MUTED)
        x += 120
    if not eligible:
        text(canvas,0,85,"No attributed par-4/5 tee outcomes are available yet.",11,color=MUTED)
        return
    maximum = max(r["fw_recorded"]+r["unknown"] for r in eligible)
    left,right = 145,w-170
    for i,row in enumerate(eligible):
        y = 52+i*43
        text(canvas,0,y,row["label"],10,bold=row["driver"],width=140)
        x = left
        for key,color in (("hit",GREEN),("left",ORANGE),("right","#C57452"),("unknown",GREY)):
            end = x+(right-left)*row[key]/maximum
            if row[key]:
                canvas.create_rectangle(x,y-9,end,y+9,fill=color,outline="")
            x = end
        rate = "—" if row["fw_percent"] is None else f"{row['fw_percent']:.1f}%"
        text(canvas,right+12,y,f"{row['hit']}/{row['fw_recorded']} · {rate}",9)


def draw_putting_bars(canvas, rows):
    canvas.delete("all")
    kind=18 if any(r["holes"]==18 for r in rows) else 9
    rows=sorted((r for r in rows if r["holes"]==kind),key=lambda r:(r.get("sort_date",r["date"]),r.get("round_id","")))
    w,h = canvas.winfo_width(),canvas.winfo_height()
    if not rows:
        text(canvas,20,60,"No putting scorecards yet.",11,color=MUTED)
        return
    left,right,top,bottom = 38,w-20,28,h-55
    maximum = max(4,max((r["three_plus"] for r in rows),default=0)+1)
    for n in range(maximum+1):
        y = bottom-(bottom-top)*n/maximum
        canvas.create_line(left,y,right,y,fill="#E9EEE8")
        text(canvas,left-10,y,str(n),8,color=MUTED,anchor="e")
    if kind==18:
        goal_y = bottom-(bottom-top)*2/maximum
        canvas.create_line(left,goal_y,right,goal_y,fill=GREEN,dash=(5,4),width=2)
        text(canvas,right,goal_y-12,"18-hole goal: ≤2",8,color=GREEN,anchor="e")
    gap = (right-left)/len(rows)
    for i,row in enumerate(rows):
        x = left+gap*(i+.5)
        complete = row["tracked"]==row["holes"]
        value = row["three_plus"]
        y = bottom-(bottom-top)*value/maximum
        canvas.create_rectangle(x-gap*.22,y,x+gap*.22,bottom,fill=GREEN if complete and kind==18 and value<=2 else ORANGE if complete else GREY,outline="")
        if len(rows)<=15:
            text(canvas,x,y-14,str(value)+("" if complete else "*"),10,bold=True,anchor="center")
        if i in (0,len(rows)-1) or i%max(1,math.ceil(len(rows)/5))==0:
            text(canvas,x,bottom+19,row["date"][5:],8,color=MUTED,anchor="center")


def draw_history_trend(canvas,series,window=5,on_round=None):
    canvas.delete("all")
    w,h=canvas.winfo_width(),canvas.winfo_height()
    if w<160 or h<100:
        return
    slots=series["slots"]
    values=[p["value"] for p in slots if p["value"] is not None]
    if not values:
        text(canvas,w/2,h/2,"No recorded data for this metric in the selected games.",10,color=MUTED,anchor="center",width=w-35)
        canvas._trend_points=[]
        return
    if series["unit"]=="%":
        low,high=0,100
    elif series["key"].startswith("score"):
        low=max(0,math.floor(min(values)-3))
        high=math.ceil(max(values)+3)
    else:
        low=0
        high=max(1,max(values)*1.2)
    left,right,top,bottom=48,w-25,30,h-53
    y_for=lambda value:bottom-(value-low)/(high-low)*(bottom-top)
    for i in range(5):
        value=low+(high-low)*i/4
        y=y_for(value)
        canvas.create_line(left,y,right,y,fill="#E9EEE8")
        caption=f"{value:.1f}" if high<=5 else f"{value:.0f}"
        text(canvas,left-9,y,caption,8,color=MUTED,anchor="e")
    coordinates=[]
    for i,p in enumerate(slots):
        x=(left+right)/2 if len(slots)==1 else left+(right-left)*i/(len(slots)-1)
        coordinates.append((x,y_for(p["value"]) if p["value"] is not None else None,p))
    def lines(points,color,width,dash=None):
        segment=[]
        for x,y in points+[(None,None)]:
            if y is None:
                if len(segment)>=4:
                    canvas.create_line(*segment,fill=color,width=width,**({"dash":dash} if dash else {}))
                segment=[]
            else:
                segment.extend((x,y))
    lines([(x,y) for x,y,_ in coordinates],GREEN,2)
    if window:
        rolling=moving_average(slots,window)
        lines([(coordinates[i][0],y_for(v) if v is not None else None) for i,v in enumerate(rolling)],AMBER,3,(5,3))
    for i,(x,y,p) in enumerate(coordinates):
        if y is not None:
            canvas.create_oval(x-3,y-3,x+3,y+3,fill=GREEN,outline=WHITE)
        else:
            text(canvas,x,bottom-6,"?",8,color=MUTED,anchor="center")
        if i in (0,len(slots)-1) or i%max(1,math.ceil(len(slots)/4))==0:
            text(canvas,x,bottom+18,p["date"][5:],8,color=MUTED,anchor="center")
    last=next((p for p in reversed(coordinates) if p[1] is not None),None)
    if last:
        x,y,p=last
        text(canvas,x,min(bottom-10,max(top-13,y-14)),f"{p['value']:.1f}"+("%" if series["unit"]=="%" else ""),9,color=GREEN,bold=True,anchor="center")
    pooled=series["unit"]=="%" or series["key"]=="putts_per_hole"
    text(canvas,left,h-12,"● Recorded game"+(f"    - - {window}-game {'pooled rate' if pooled else 'rolling mean'}" if window else ""),8,color=MUTED)
    canvas._trend_points=coordinates
    def nearest(event):
        if not coordinates or not left-10<=event.x<=right+10 or not top-20<=event.y<=bottom+15:
            return None
        index=round((event.x-left)/(right-left)*(len(coordinates)-1)) if len(coordinates)>1 else 0
        return coordinates[max(0,min(len(coordinates)-1,index))]
    def hover(event):
        canvas.delete("hover")
        point=nearest(event)
        if point:
            p=point[2]
            value="Not recorded" if p["value"] is None else f"{p['value']:.2f} {series['unit']}"
            if "classified" in p:
                value+=f" · {p['hits']}/{p['classified']} target hits"
            canvas.create_text(w-12,8,text=f"{p['date']} · {value}",font=(FONT,8),fill=INK,anchor="ne",tags="hover")
    canvas.bind("<Motion>",hover)
    canvas.bind("<Leave>",lambda _:canvas.delete("hover"))
    if on_round:
        canvas.bind("<Button-1>",lambda e:on_round(nearest(e)[2]["id"]) if nearest(e) else None)


def draw_club_confidence(canvas,report):
    canvas.delete("all")
    rows=report["rows"]
    w=canvas.winfo_width()
    if not rows:
        text(canvas,20,65,"No recorded club outcomes for this role in the selected games.",11,color=MUTED,width=w-40)
        return
    maximum=max(1,max(r["records"] for r in rows))
    left,right=185,w-240
    for x,title,color in ((0,"Target hits",GREEN),(145,"Target misses",ORANGE),(300,"Unknown",GREY)):
        canvas.create_rectangle(x,9,x+10,19,fill=color,outline="")
        text(canvas,x+16,14,title,8,color=MUTED)
    for i,row in enumerate(rows):
        y=53+43*i
        text(canvas,0,y,row["label"],10,bold=row["enough"],width=175)
        canvas.create_rectangle(left,y-9,right,y+9,fill="#EDF1ED",outline="")
        x=left
        for key,color in (("hits",GREEN),("misses",ORANGE),("unknown",GREY)):
            end=x+(right-left)*row[key]/maximum
            if row[key]:
                canvas.create_rectangle(x,y-9,end,y+9,fill=color,outline="")
            x=end
        rate="—" if row["rate"] is None else f"{row['rate']:.0f}%"+("*" if row["classified"]<10 else "")
        hits_word="hit" if row["hits"]==1 else "hits"
        misses_word="miss" if row["misses"]==1 else "misses"
        text(canvas,right+12,y,f"{row['hits']} {hits_word} · {row['misses']} {misses_word} · {rate}",9,color=MUTED if row["unassigned"] else INK)


def draw_putting_drill(canvas):
    canvas.delete("all")
    w,h = canvas.winfo_width(),canvas.winfo_height()
    cx,cy = w*.7,82
    canvas.create_oval(cx-65,cy-50,cx+65,cy+50,fill=MINT,outline=GREEN,width=2,dash=(4,3))
    canvas.create_oval(cx-5,cy-4,cx+5,cy+4,fill=INK,outline="")
    text(canvas,cx,cy+30,"3-foot finish zone",9,color=GREEN,anchor="center")
    for i,feet in enumerate((20,30,40)):
        x,y = w*.18+i*30,175+i*42
        canvas.create_oval(x-6,y-6,x+6,y+6,fill=WHITE,outline=INK,width=2)
        canvas.create_line(x+10,y-8,cx-18,cy+8,fill=GREY,dash=(5,4),arrow=tk.LAST)
        text(canvas,x-12,y,f"{feet} ft",10,bold=True,anchor="e")
    text(canvas,15,h-22,"Practice diagram—not a map of your putts. Putt every ball out.",8,color=MUTED,width=w-25)


def draw_wedge_bars(canvas, rows):
    canvas.delete("all")
    w = canvas.winfo_width()
    lines = [(r,role) for r in rows for role in ("approach","chip") if r[role]["shots"]]
    if not lines:
        text(canvas,20,60,"No tracked wedge approaches or chips in this sample.",11,color=MUTED)
        return
    maximum = max(r[role]["shots"] for r,role in lines)
    left,right = 245,w-130
    for i,(row,role) in enumerate(lines):
        y = 30+i*42
        text(canvas,0,y,f"{row['label']} · {'approach' if role=='approach' else 'chip'}",10,width=235)
        x = left
        for key,color in (("green",GREEN),("miss",ORANGE),("unknown",GREY)):
            end = x+(right-left)*row[role][key]/maximum
            if row[role][key]:
                canvas.create_rectangle(x,y-9,end,y+9,fill=color,outline="")
            x = end
        text(canvas,right+10,y,f"{row[role]['green']}/{row[role]['shots']} on green",9)
