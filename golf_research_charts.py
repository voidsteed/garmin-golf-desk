"""Descriptive research charts; no fitted personal outcome probabilities."""

from golf_charts import GREEN,ORANGE,GREY,INK,MUTED,text


def draw_par_mistakes(canvas,breakdown):
    canvas.delete("all")
    rows=breakdown["by_par"]
    width=canvas.winfo_width()
    maximum=max((r["double_only"]+r["triple_plus"] for r in rows),default=1) or 1
    for i,row in enumerate(rows):
        y=45+i*55
        text(canvas,0,y,f"Par {row['par']:.0f}",10,bold=True)
        left,right=75,width-175
        split=left+(right-left)*row["double_only"]/maximum
        end=split+(right-left)*row["triple_plus"]/maximum
        canvas.create_rectangle(left,y-10,split,y+10,fill=ORANGE,outline="")
        canvas.create_rectangle(split,y-10,end,y+10,fill="#BB6656",outline="")
        text(canvas,right+10,y,f"{row['double_only']+row['triple_plus']}/{row['holes']} · {row['big_rate']:.1f}%",9)
        text(canvas,right+10,y+18,f"Mean score {row['average']:.2f}",8,color=MUTED)
    text(canvas,0,max(225,45+len(rows)*55),"Gold: double only · red: triple or worse. Hole difficulty varies.",8,color=MUTED,width=width-10)


def draw_big_hole_flags(canvas,breakdown):
    canvas.delete("all")
    width=canvas.winfo_width()
    keys=("Penalty + three-putt","Penalty only","Three-putt only","Neither flag recorded","Unknown tracking")
    maximum=max((breakdown["flags"].get(k,0) for k in keys),default=1) or 1
    for i,key in enumerate(keys):
        y=28+i*40
        value=breakdown["flags"].get(key,0)
        text(canvas,0,y,key,9,width=180)
        left,right=190,width-50
        canvas.create_rectangle(left,y-8,left+(right-left)*value/maximum,y+8,fill=GREY if key=="Unknown tracking" else ORANGE,outline="")
        text(canvas,right+10,y,str(value),10,bold=True)


def draw_putt_bins(canvas,groups):
    canvas.delete("all")
    width=canvas.winfo_width()
    if not groups:
        text(canvas,20,65,"Log first-putt bins on successful holes as well as three-putts to create useful denominators.",10,color=MUTED,width=width-40)
        return
    for i,row in enumerate(groups):
        y=32+i*42
        text(canvas,0,y,row["bin"],9)
        left,right=115,width-140
        rate=row["rate"] or 0
        canvas.create_rectangle(left,y-8,right,y+8,fill="#EDF1ED",outline="")
        canvas.create_rectangle(left,y-8,left+(right-left)*rate/100,y+8,fill=ORANGE,outline="")
        text(canvas,right+10,y,f"{row['threeputts']}/{row['holes']} · {rate:.0f}%",9)


def draw_carry_samples(canvas,row):
    canvas.delete("all")
    width,height=canvas.winfo_width(),canvas.winfo_height()
    samples=row.get("paired_samples",[]) if row else []
    if not samples:
        text(canvas,20,80,"Add measured carry AND signed lateral miss to plot real paired samples. No independent Gaussian ellipse is invented.",10,color=MUTED,width=width-40)
        return
    spread=max(10,max(abs(p["lateral"]) for p in samples)+5)
    maximum=max(1,max(p["carry"] for p in samples)+10)
    left,right,top,bottom=55,width-35,28,height-48
    x_for=lambda x:left+(x+spread)/(spread*2)*(right-left)
    y_for=lambda y:bottom-y/maximum*(bottom-top)
    canvas.create_line(x_for(0),top,x_for(0),bottom,fill=GREY,dash=(5,4))
    for i in range(5):
        y=maximum*i/4
        canvas.create_line(left,y_for(y),right,y_for(y),fill="#E9EEE8")
        text(canvas,left-8,y_for(y),f"{y:.0f}",8,color=MUTED,anchor="e")
    for point in samples:
        x,y=x_for(point["lateral"]),y_for(point["carry"])
        canvas.create_oval(x-4,y-4,x+4,y+4,fill=ORANGE if point["contact"]=="Mishit" else GREEN,outline="white")
    text(canvas,left,bottom+20,f"Left −{spread:.0f} yd",8,color=MUTED)
    text(canvas,right,bottom+20,f"Right +{spread:.0f} yd",8,color=MUTED,anchor="e")
    text(canvas,x_for(0),height-10,"Lateral miss from intended line · vertical axis = measured carry (yd)",8,color=MUTED,anchor="center")
