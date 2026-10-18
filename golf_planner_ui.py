"""Local course-management and transparent expected-score planning views."""

import tkinter as tk
from tkinter import ttk

from golf_charts import chart,text
from golf_ev import Outcome,ShotPlan,compare_plans
from golf_strategy import build_shot_plan

BG,WHITE,INK,MUTED,GREEN,MINT,BORDER = "#F3F6F3","#FFFFFF","#15382E","#65766D","#137B56","#E4F2E9","#DFE7DF"
FONT = "Segoe UI"


def label(parent,value,size=10,bold=False,color=INK,bg=WHITE,**kwargs):
    return tk.Label(parent,text=value,font=(FONT,size,"bold" if bold else "normal"),fg=color,bg=bg,anchor="w",justify="left",**kwargs)


def panel(parent,title,subtitle="",wraplength=1050):
    frame = tk.Frame(parent,bg=WHITE,highlightbackground=BORDER,highlightthickness=1)
    frame.pack(fill="x",pady=(0,18))
    label(frame,title,14,True).pack(anchor="w",padx=18,pady=(16,5))
    if subtitle:
        # Fixed wrapping avoids Tk geometry feedback when switching a long form
        # inside a scrolled, temporarily unmapped page.
        label(frame,subtitle,9,color=MUTED,wraplength=wraplength).pack(anchor="w",padx=18,pady=(0,14))
    return frame


def action(parent,title,callback,primary=False):
    return tk.Button(parent,text=title,command=callback,font=(FONT,10,"bold"),bg=GREEN if primary else MINT,
                     fg=WHITE if primary else INK,relief="flat",padx=16,pady=10,cursor="hand2")


def draw_target_zone(canvas,plan):
    canvas.delete("all")
    w,h = canvas.winfo_width(),canvas.winfo_height()
    d = plan["diagram"]
    cx,cy = w/2,115
    canvas.create_rectangle(15,12,w-15,h-20,fill="#EFF5E9",outline="")
    if d["phase"]=="tee":
        canvas.create_polygon(w*.3,h-35,w*.7,h-35,w*.78,40,w*.22,40,fill="#D0E9C6",outline="")
    canvas.create_oval(cx-108,cy-67,cx+108,cy+67,fill="#BCE0B2",outline="#86B77A",width=2)
    hazard = d["hazard"]
    if d["phase"]!="putting":
        if hazard in ("Left","Both sides"):
            canvas.create_rectangle(20,35,w*.19,h-55,fill="#F0C9BF",outline="")
            text(canvas,w*.10,65,"Trouble",8,anchor="center",color="#A24539")
        if hazard in ("Right","Both sides"):
            canvas.create_rectangle(w*.81,35,w-20,h-55,fill="#F0C9BF",outline="")
            text(canvas,w*.90,65,"Trouble",8,anchor="center",color="#A24539")
        if hazard in ("Short / front","Long / back"):
            y = 205 if hazard=="Short / front" else 32
            canvas.create_rectangle(w*.24,y,w*.76,y+20,fill="#F0C9BF",outline="")
            text(canvas,cx,y+10,"Trouble side supplied by you",8,anchor="center",color="#A24539")
    ball_x,ball_y = cx,h-55
    canvas.create_oval(ball_x-6,ball_y-6,ball_x+6,ball_y+6,fill=WHITE,outline=INK,width=2)
    if d["phase"]=="putting":
        hole_y = 90
        canvas.create_oval(cx-5,hole_y-4,cx+5,hole_y+4,fill=INK,outline="")
        start_x = cx+75 if d["break"]=="Breaks left" else cx-75 if d["break"]=="Breaks right" else cx
        canvas.create_line(cx,ball_y,start_x,170,cx,hole_y,fill=GREEN,width=3,smooth=True,arrow=tk.LAST)
        canvas.create_line(cx,ball_y,start_x,hole_y,fill=MUTED,dash=(5,4))
        if d["putt"] is None or d["putt"]>20:
            canvas.create_oval(cx-48,hole_y-38,cx+48,hole_y+38,outline=GREEN,dash=(4,3))
            text(canvas,cx+60,hole_y+30,"Pace / finish zone",9,color=GREEN)
        text(canvas,20,h-15,"Illustrative start line—not measured break.",8,color=MUTED)
    else:
        aim_x = cx+w*.10 if hazard=="Left" else cx-w*.10 if hazard=="Right" else cx
        aim_y = 142 if hazard=="Long / back" else cy
        if d["chip"] and d["phase"]=="wedge":
            aim_y = cy+38
        if d["layup"]:
            aim_y = h-110
        canvas.create_oval(aim_x-35,aim_y-24,aim_x+35,aim_y+24,fill=MINT,outline=GREEN,width=3)
        canvas.create_line(ball_x,ball_y-10,aim_x,aim_y+18,fill=GREEN,width=3,dash=(6,4),arrow=tk.LAST)
        text(canvas,aim_x,aim_y,"Lay-up zone" if d["layup"] else "Landing spot" if d["chip"] and d["phase"]=="wedge" else "Safe target",9,bold=True,anchor="center",color=GREEN)
        if d["pin"]!="Not supplied":
            pin = d["pin"].casefold()
            px = cx-70 if "left" in pin else cx+70 if "right" in pin else cx
            py = cy+42 if "front" in pin else cy-40 if "back" in pin else cy-20
            canvas.create_line(px,py-24,px,py,fill=INK,width=2)
            canvas.create_polygon(px,py-24,px+23,py-16,px,py-9,fill="#A24539",outline="")
            text(canvas,px,py+14,"Pin you supplied",8,color=MUTED,anchor="center")
        text(canvas,20,h-15,"Schematic target zones—not a current-hole map.",8,color=MUTED)


class StrategyView:
    def __init__(self,parent,model,state):
        self.model,self.state = model,state
        self.vars = {k:tk.StringVar(value=state.get(k,default)) for k,default in {
            "phase":"tee","hazard":"Not supplied","conditions":"Not supplied","pin":"Not supplied",
            "wedge_role":"Approach / pitch","break_direction":"Not supplied","target":"","carry":"","hazard_carry":"","putt":""}.items()}
        self.plan = None
        notice = panel(parent,"Plan the next shot, not the perfect shot.","Enter what you know about the current situation. This rule-based guide cannot see the live hole, hazards, wind or green slope. It does not prove positive EV.")
        label(notice,"Use the Expected score / EV tab to compare explicit probabilities and stroke costs. FIR and GIR are useful outcomes, not the complete scoring objective.",9,color=MUTED,wraplength=1050).pack(anchor="w",padx=18,pady=(0,16))
        columns = tk.Frame(parent,bg=BG)
        columns.pack(fill="x",pady=(0,18))
        columns.columnconfigure(1,weight=1)
        self.form = tk.Frame(columns,bg=WHITE,padx=18,pady=16,highlightbackground=BORDER,highlightthickness=1)
        self.form.grid(row=0,column=0,sticky="n",padx=(0,16))
        label(self.form,"SHOT SITUATION",10,True,color=MUTED).pack(anchor="w",pady=(0,10))
        phase = ttk.Combobox(self.form,values=("tee","approach","wedge","putting"),textvariable=self.vars["phase"],state="readonly",width=28)
        phase.pack(fill="x",ipady=3,pady=(0,12))
        phase.bind("<<ComboboxSelected>>",lambda _:self.fields())
        self.dynamic = tk.Frame(self.form,bg=WHITE)
        self.dynamic.pack(fill="x")
        self.error = label(self.form,"",9,color="#A24539",wraplength=285)
        self.error.pack(fill="x",pady=10)
        action(self.form,"Build shot plan",self.update,True).pack(fill="x")
        self.output = tk.Frame(columns,bg=BG)
        self.output.grid(row=0,column=1,sticky="nsew")
        diagram = panel(self.output,"A safer target zone","Not to scale. Colored trouble areas appear only when you supply a trouble side.",wraplength=500)
        self.canvas = chart(diagram,lambda c:draw_target_zone(c,self.plan) if self.plan else None,height=340)
        self.details = tk.Frame(self.output,bg=BG)
        self.details.pack(fill="x")
        self.fields()

    def add(self,title,key,values=None):
        label(self.dynamic,title,9,True).pack(anchor="w",pady=(9,5))
        widget = ttk.Combobox(self.dynamic,values=values,textvariable=self.vars[key],state="readonly",width=28) if values else ttk.Entry(self.dynamic,textvariable=self.vars[key],width=30)
        widget.pack(fill="x",ipady=3)

    def fields(self):
        for child in self.dynamic.winfo_children():
            child.destroy()
        phase = self.vars["phase"].get()
        self.choices = {}
        for key,club in self.model.clubs.items():
            kind = str(club.get("clubTypeId"))
            if key=="0" or club.get("deleted") or club.get("retired"):
                continue
            if phase=="putting" and kind!="23" or phase=="wedge" and kind not in {"19","20","21","22"} or phase not in {"putting","wedge"} and kind=="23":
                continue
            name = self.model.club_label(key)[0]
            if name in self.choices:
                name += " (alternative)"
            self.choices[name] = key
        if not self.choices:
            self.choices = {"No club imported":"0"}
        default = next(iter(self.choices))
        if phase=="tee":
            default = next((n for n,k in self.choices.items() if str(self.model.clubs.get(k,{}).get("clubTypeId"))=="1"),default)
        elif phase=="approach":
            top = next((r for r in self.model.approach_analysis()["clubs"] if not r["unassigned"]),None)
            if top:
                default = next((n for n,k in self.choices.items() if k==top["id"]),default)
        self.club_var = tk.StringVar(value=self.state.get("club_"+phase,default))
        if self.club_var.get() not in self.choices:
            self.club_var.set(default)
        label(self.dynamic,"Club",9,True).pack(anchor="w",pady=(0,5))
        ttk.Combobox(self.dynamic,values=list(self.choices),textvariable=self.club_var,state="readonly",width=28).pack(fill="x",ipady=3)
        if phase!="putting":
            self.add("Trouble / penalty side","hazard",("Not supplied","Left","Right","Short / front","Long / back","Both sides"))
            if phase=="wedge":
                self.add("Wedge shot role","wedge_role",("Approach / pitch","Greenside chip"))
            self.add("Safe landing target (yards, optional)","target")
            self.add("Your reliable normal carry (yards)","carry")
            self.add("Carry needed to clear hazard (yards)","hazard_carry")
            if phase in {"approach","wedge"}:
                self.add("Pin position you see","pin",("Not supplied","Center","Front-left","Front-right","Back-left","Back-right"))
        else:
            self.add("Putt length (feet, optional)","putt")
            self.add("Break from YOUR green read","break_direction",("Not supplied","Straight","Breaks left","Breaks right"))
        self.add("Conditions you observe","conditions",("Not supplied","Calm / level","Headwind","Tailwind","Uphill","Downhill","Poor lie"))
        self.update()

    def update(self):
        phase = self.vars["phase"].get()
        self.state.update({key:value.get() for key,value in self.vars.items()})
        self.state["club_"+phase] = self.club_var.get()
        kwargs = {key:value.get() for key,value in self.vars.items()}
        # Hidden fields from another shot phase must not change this phase's plan.
        if phase=="putting":
            for key in ("target","carry","hazard_carry"):
                kwargs[key] = None
        else:
            kwargs["putt"] = None
        if phase=="tee":
            kwargs["pin"] = "Not supplied"
        try:
            self.plan = build_shot_plan(self.model,club_id=self.choices[self.club_var.get()],**kwargs)
        except ValueError as exc:
            self.error.configure(text=str(exc))
            return
        self.error.configure(text="")
        for child in self.details.winfo_children():
            child.destroy()
        plan = self.plan
        frame = panel(self.details,"Your scoring plan",plan["limit"],wraplength=500)
        for title,key in (("AIM","aim"),("CLUB / PACE","decision"),("SAFE MISS","miss"),("PRACTICE","practice")):
            label(frame,title,9,True,color=GREEN).pack(anchor="w",padx=18,pady=(8,4))
            label(frame,plan[key],10,wraplength=500).pack(anchor="w",padx=18,pady=(0,9))
        for title,items in (("Checks before playing",plan["checks"]),("Your data as a reference",plan["evidence"])):
            if items:
                frame = panel(self.details,title)
                for item in items:
                    label(frame,"• "+item,9,color=MUTED,wraplength=500).pack(anchor="w",padx=18,pady=(0,12))
        if self.canvas.winfo_width()>150:
            draw_target_zone(self.canvas,plan)


class ExpectedValueView:
    def __init__(self,parent,model,state=None):
        self.model = model
        self.state = state if state is not None else {}
        self.example = self.state.get("example",False)
        note = panel(parent,"Compare expected strokes—not accuracy alone.","Your current export does not establish calibrated probabilities for a specific target, wind, lie or green. Enter scenario estimates, or load the clearly labeled worked example. No personal positive-EV claim is made from incomplete data.")
        label(note,"Include human error in mutually exclusive outcomes. Probabilities should reflect distance, dispersion, contact, lie, wind, hazards, recovery, fatigue/pressure, green speed and putting—not overlapping error percentages added together.",10,color=MUTED,wraplength=1070).pack(anchor="w",padx=18,pady=(0,16))
        inputs = panel(parent,"Two alternative plans for the same shot","Remaining strokes means play AFTER this shot and AFTER the explicit immediate penalty. A replay after stroke-and-distance belongs in remaining play; do not count it twice.")
        grid = tk.Frame(inputs,bg=WHITE)
        grid.pack(fill="x",padx=18,pady=(0,14))
        saved_names = self.state.get("names",("Current plan","Safer alternative"))
        self.names = [tk.StringVar(value=saved_names[0]),tk.StringVar(value=saved_names[1])]
        self.entries = []
        for col in range(8):
            grid.columnconfigure(col,weight=1 if col!=4 else 0)
        label(grid,"Outcome",10,True).grid(row=1,column=0,sticky="w",padx=(0,10),pady=10)
        for side,start in enumerate((1,5)):
            ttk.Entry(grid,textvariable=self.names[side],font=(FONT,11,"bold")).grid(row=0,column=start,columnspan=3,sticky="ew",padx=6,pady=5)
            for offset,heading in enumerate(("Probability %","Strokes left","Penalty")):
                label(grid,heading,9,True,color=MUTED).grid(row=1,column=start+offset,padx=5,sticky="w")
            values = []
            for row in range(4):
                fields = []
                for offset in range(3):
                    value = tk.StringVar(value=self.state.get("values",[[[""]*3 for _ in range(4)] for _ in range(2)])[side][row][offset])
                    ttk.Entry(grid,textvariable=value,width=11).grid(row=row+2,column=start+offset,sticky="ew",padx=5,pady=5,ipady=3)
                    fields.append(value)
                values.append(fields)
            self.entries.append(values)
        for row,title in enumerate(("Intended finish / holed","Playable miss / easy next putt","Mishit / recovery / hard next putt","Penalty / very poor finish")):
            label(grid,title,9,wraplength=190).grid(row=row+2,column=0,sticky="w",padx=(0,10),pady=5)
        controls = tk.Frame(inputs,bg=WHITE)
        controls.pack(fill="x",padx=18,pady=(0,14))
        self.error_radius,self.cost_radius = tk.StringVar(value=self.state.get("error_radius","5")),tk.StringVar(value=self.state.get("cost_radius","0.25"))
        label(controls,"Error-rate uncertainty (± percentage points)",9).grid(row=0,column=0,sticky="w",padx=(0,10),pady=5)
        ttk.Entry(controls,textvariable=self.error_radius,width=8).grid(row=0,column=1,pady=5)
        label(controls,"Remaining-stroke uncertainty (±)",9).grid(row=1,column=0,sticky="w",padx=(0,10),pady=5)
        ttk.Entry(controls,textvariable=self.cost_radius,width=8).grid(row=1,column=1,pady=5)
        self.error_outcome = tk.StringVar(value=self.state.get("error_outcome","Mishit / recovery"))
        label(controls,"Added errors go to",9).grid(row=0,column=2,sticky="w",padx=(25,8))
        ttk.Combobox(controls,textvariable=self.error_outcome,values=("Mishit / recovery","Penalty / very poor finish"),state="readonly",width=27).grid(row=0,column=3,sticky="w")
        actions = tk.Frame(inputs,bg=WHITE)
        actions.pack(fill="x",padx=18,pady=(0,18))
        action(actions,"Compare expected score",self.calculate,True).pack(side="left")
        action(actions,"Load worked example",self.load_example).pack(side="left",padx=10)
        action(actions,"Clear for my own estimates",self.clear).pack(side="left")
        self.message = label(inputs,"Enter two sets of probabilities totaling 100% each. Nothing is sent to Garmin.",9,color=MUTED,wraplength=1080)
        self.message.pack(anchor="w",padx=18,pady=(0,16))
        self.output = tk.Frame(parent,bg=BG)
        self.output.pack(fill="x")
        variables = self.names+[v for side in self.entries for row in side for v in row]+[self.error_radius,self.cost_radius,self.error_outcome]
        for variable in variables:
            variable.trace_add("write",lambda *_:self.save_state())
        if all(v.get().strip() for side in self.entries for row in side for v in row):
            self.calculate()

    def save_state(self):
        self.state.update({"names":[v.get() for v in self.names],"values":[[[v.get() for v in row] for row in side] for side in self.entries],
                           "error_radius":self.error_radius.get(),"cost_radius":self.cost_radius.get(),"error_outcome":self.error_outcome.get(),"example":self.example})

    def clear(self):
        self.example = False
        for side in self.entries:
            for row in side:
                for value in row:
                    value.set("")
        self.message.configure(text="Enter estimates for this situation. They are assumptions, not automatically learned personal probabilities.",fg=MUTED)
        for child in self.output.winfo_children():
            child.destroy()

    def load_example(self):
        self.example = True
        examples = (((50,1.9,0),(25,2.7,0),(15,3.6,0),(10,3.4,1)),((60,2.0,0),(30,2.5,0),(8,3.4,0),(2,3.5,1)))
        for side,rows in zip(self.entries,examples):
            for fields,values in zip(side,rows):
                for variable,value in zip(fields,values):
                    variable.set(str(value))
        self.calculate()

    def calculate(self):
        self.save_state()
        try:
            plans = []
            for i,rows in enumerate(self.entries):
                outcomes = tuple(Outcome(float(fields[0].get())/100,float(fields[1].get()),float(fields[2].get())) for fields in rows)
                plans.append(ShotPlan(self.names[i].get().strip()[:60] or f"Plan {i+1}",outcomes))
            index = 2 if self.error_outcome.get()=="Mishit / recovery" else 3
            result = compare_plans(plans[0],plans[1],float(self.error_radius.get())/100,float(self.cost_radius.get()),index)
        except (ValueError,TypeError) as exc:
            self.message.configure(text=str(exc) if all(v.get().strip() for side in self.entries for row in side for v in row) else "Complete all probability, remaining-stroke and penalty fields for both plans. Use 0 where appropriate.",fg="#A24539")
            return
        self.message.configure(text="WORKED EXAMPLE ONLY—not based on your personal performance probabilities." if self.example else "Scenario estimates only. Personal calibration and the current situation still need to be validated.",fg="#976123")
        for child in self.output.winfo_children():
            child.destroy()
        frame = panel(self.output,"Expected score under these assumptions","Lower is better. Positive EV here is expected strokes saved by the alternative versus your current plan—not money or a guarantee.")
        value = result["alternative_ev"]
        label(frame,f"Estimated alternative EV: {value:+.2f} strokes",21,True,color=GREEN if value>0 else INK).pack(anchor="w",padx=18,pady=(0,8))
        label(frame,f"Best nominal estimate: {result['best_estimate']}. Sensitivity range for alternative savings: {result['ev_low']:+.2f} to {result['ev_high']:+.2f} strokes.",10,wraplength=1070).pack(anchor="w",padx=18,pady=(0,12))
        label(frame,(f"{result['robust_preference']} remains preferred across the entered uncertainty bounds. This does not validate the probabilities themselves." if result["robust_preference"] else "The sensitivity bands overlap. There is no robust preference under these uncertainty assumptions, even if one nominal EV is positive."),10,color="#976123",wraplength=1070).pack(anchor="w",padx=18,pady=(0,12))
        chart(frame,lambda c:self.draw(c,result),height=220)
        label(frame,"Formula: 1 current stroke + Σ probability × (immediate penalty + expected remaining strokes). Stress tests shift probability between the intended finish and the selected bad outcome. Bands are sensitivity ranges, NOT statistical confidence intervals.",9,color=MUTED,wraplength=1070).pack(anchor="w",padx=18,pady=(0,18))

    def draw(self,canvas,result):
        canvas.delete("all")
        width = canvas.winfo_width()
        rows = (result["baseline"],result["alternative"])
        maximum = max(r["high"] for r in rows)+.5
        left,right = 190,width-150
        for i,row in enumerate(rows):
            y = 55+i*85
            name = row["name"] if len(row["name"])<25 else row["name"][:23]+"…"
            text(canvas,0,y,name,10,bold=True,width=180)
            canvas.create_rectangle(left,y-10,right,y+10,fill="#EDF1ED",outline="")
            canvas.create_rectangle(left,y-10,left+(right-left)*row["expected"]/maximum,y+10,fill=GREEN if i else "#BAC4BD",outline="")
            low,high = (left+(right-left)*row[k]/maximum for k in ("low","high"))
            canvas.create_line(low,y,high,y,fill=INK,width=2)
            for x in (low,high):
                canvas.create_line(x,y-17,x,y+17,fill=INK,width=2)
            text(canvas,right+12,y,f"{row['expected']:.2f} strokes",10,bold=True)
        text(canvas,0,200,"Whiskers show user-assumption sensitivity, not measured certainty.",9,color=MUTED)
