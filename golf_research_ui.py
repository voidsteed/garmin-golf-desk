"""Research coach, private measurement journal and reference-driven SG workbench."""

from __future__ import annotations

import csv
import tkinter as tk
import webbrowser
from datetime import date
from pathlib import Path
from tkinter import filedialog,messagebox,ttk

from golf_baselines import StrokeReference
from golf_data import number
from golf_charts import chart,draw_history_trend
from golf_research import REFERENCES,approach_context,practice_summary,putting_context,reference_results,research_snapshot,shot_contexts
from golf_research_charts import draw_big_hole_flags,draw_carry_samples,draw_par_mistakes,draw_putt_bins
from golf_research_store import CHECK_STATUSES,CONDITIONS,INTENTS,LIES,PENALTY_PHASES,PENALTY_REASONS,PUTT_BINS,ResearchStoreError,hole_signature,numeric

BG,WHITE,INK,MUTED,GREEN,AMBER=("#F3F6F3","#FFFFFF","#15382E","#65766D","#137B56","#976123")
FONT="Segoe UI"
VIEWS=("Research insights","Tracking audit","Round journal","Carry & chip practice","Approach context","Strokes-gained reference")


def text(parent,value,size=10,bold=False,color=INK,bg=WHITE,wrap=1050):
    widget=tk.Label(parent,text=value,font=(FONT,size,"bold" if bold else "normal"),fg=color,bg=bg,anchor="w",justify="left",wraplength=wrap)
    if wrap:
        binding=parent.bind("<Configure>",lambda e:widget.configure(wraplength=max(140,min(wrap,e.width-38))),add="+")
        def detach(event):
            if event.widget==widget:
                try:
                    parent.unbind("<Configure>",binding)
                except tk.TclError:
                    pass
        widget.bind("<Destroy>",detach,add="+")
    return widget


def wrap_panel(panel):
    header=panel.winfo_children()[0]
    for child in header.winfo_children():
        if isinstance(child,tk.Label):
            header.bind("<Configure>",lambda e,w=child:w.configure(wraplength=max(140,e.width-38)),add="+")
    return panel


def fmt(value,digits=1):
    return "—" if value is None else f"{value:.{digits}f}"


class ShotReview(tk.Toplevel):
    def __init__(self,parent,model,store,record):
        super().__init__(parent)
        self.title("Review shot context — local only")
        self.configure(bg=WHITE)
        self.transient(parent)
        self.resizable(False,False)
        self.saved=False
        self.store,self.model,self.record=store,model,record
        note=record["note"]
        body=tk.Frame(self,bg=WHITE,padx=22,pady=18)
        body.pack(fill="both",expand=True)
        text(body,f"{record['date']} · hole {record['hole']} · {record['club']}",15,True,wrap=650).grid(row=0,column=0,columnspan=4,sticky="w",pady=(0,8))
        text(body,"Local notes never edit Garmin. Verify actual states; GPS near a green is not precise putting distance.",9,color=MUTED,wrap=650).grid(row=1,column=0,columnspan=4,sticky="w",pady=(0,12))
        self.variables={}
        fields=(("intent","Intent",INTENTS),("target","Target",("Unknown","Safe center","Flag","Landing zone","Other")),
                ("conditions","Conditions",CONDITIONS),("review_status","Review",CHECK_STATUSES),
                ("start_yards","Start distance (yards)",None),("start_lie","Start lie",("Unknown",)+LIES),
                ("end_yards","End distance (yards; feet ÷ 3)",None),("end_lie","End lie",("Unknown",)+LIES),
                ("penalty_strokes","Immediate penalty strokes",None),("note","Note",None))
        for i,(key,label,values) in enumerate(fields):
            r,c=2+(i//2)*2,(i%2)*2
            default="Unknown" if values and "Unknown" in values else "Unchecked" if key=="review_status" else ""
            value=note.get(key,default)
            variable=tk.StringVar(value="" if value is None else str(value))
            self.variables[key]=variable
            text(body,label,9,True,wrap=300).grid(row=r,column=c,columnspan=2,sticky="w",pady=(4,4),padx=(0,14))
            widget=ttk.Combobox(body,textvariable=variable,values=values,state="readonly",width=29) if values else ttk.Entry(body,textvariable=variable,width=31)
            widget.grid(row=r+1,column=c,columnspan=2,sticky="ew",pady=(0,8),padx=(0,14),ipady=3)
        self.holed=tk.BooleanVar(value=note.get("holed",False))
        self.verified=tk.BooleanVar(value=note.get("states_verified",False) and record.get("states_current",False))
        if note.get("states_verified") and not record.get("states_current"):
            self.variables["review_status"].set("Unchecked")
        ttk.Checkbutton(body,text="Shot explicitly holed (end value becomes zero)",variable=self.holed).grid(row=12,column=0,columnspan=4,sticky="w",pady=5)
        ttk.Checkbutton(body,text="I checked the distances/lies for reference analysis",variable=self.verified).grid(row=13,column=0,columnspan=4,sticky="w",pady=5)
        text(body,"On-green distances should come from an actual check or explicit estimate, not an unverified GPS trace. Nonzero penalty allocations also need Review = Verified.",9,color=AMBER,wrap=650).grid(row=14,column=0,columnspan=4,sticky="w",pady=8)
        self.message=tk.StringVar()
        if note and not record.get("states_current",False):
            self.message.set("Source data changed since this note was saved. Its values are retained, but need a fresh check before reference analysis.")
        tk.Label(body,textvariable=self.message,bg=WHITE,fg=AMBER,font=(FONT,9),wraplength=650,justify="left").grid(row=15,column=0,columnspan=4,sticky="w",pady=5)
        actions=tk.Frame(body,bg=WHITE)
        actions.grid(row=16,column=0,columnspan=4,sticky="ew",pady=(8,0))
        ttk.Button(actions,text="Use GPS as unverified draft",command=self.draft).pack(side="left")
        ttk.Button(actions,text="Save local context",command=self.save).pack(side="right")
        ttk.Button(actions,text="Cancel",command=self.destroy).pack(side="right",padx=8)
        self.grab_set()

    def draft(self):
        r=self.record
        self.variables["start_yards"].set("" if r["start_proxy"] is None else f"{r['start_proxy']:.1f}")
        # Do not manufacture a putting distance from GPS at the green.
        self.variables["end_yards"].set("" if r["end_lie"]=="Green" or r["end_proxy"] is None else f"{r['end_proxy']:.1f}")
        self.variables["start_lie"].set(r["start_lie"])
        self.variables["end_lie"].set(r["end_lie"])
        self.verified.set(False)
        self.message.set("Draft only. End-on-green distance is intentionally blank; check or estimate the actual first putt.")

    def save(self):
        values={k:v.get() for k,v in self.variables.items()}
        values.update(holed=self.holed.get(),states_verified=self.verified.get())
        try:
            self.store.save_shot(self.model,self.record["round_id"],self.record["key"],values)
        except (ValueError,ResearchStoreError) as exc:
            self.message.set(str(exc))
            return
        self.saved=True
        self.destroy()


class ResearchCoachView:
    def __init__(self,app,parent,state):
        self.app,self.parent,self.state=app,parent,state
        self.model,self.rounds,self.store=app.model,app.selected_games(),app.research_store
        self.form_fields={}
        self.initial={}
        self.view=state.get("view",VIEWS[0])
        if self.view not in VIEWS:
            self.view=VIEWS[0]
        controls=tk.Frame(parent,bg=BG)
        controls.pack(fill="x",pady=(0,14))
        self.view_var=tk.StringVar(value=self.view)
        ttk.Combobox(controls,textvariable=self.view_var,values=VIEWS,state="readonly",width=30).pack(side="left",ipady=3)
        self.view_var.trace_add("write",self.change_view)
        text(controls,"Private research notes · Garmin records stay unchanged",9,color=MUTED,bg=BG,wrap=440).pack(side="left",padx=14)
        self.host=tk.Frame(parent,bg=BG)
        self.host.pack(fill="x")
        self.render()

    def dirty(self):
        return any(v.get()!=self.initial.get(k) for k,v in self.form_fields.items())

    def can_leave(self):
        if not self.dirty():
            return True
        if messagebox.askyesno("Unsaved research entries","Discard the unsaved research form entries? Saved notes and Garmin exports are kept.",parent=self.app.root,default="no"):
            for key,variable in self.form_fields.items():
                variable.set(self.initial[key])
            return True
        return False

    def remember_form(self):
        self.initial={k:v.get() for k,v in self.form_fields.items()}

    def mark_saved(self,prefix=""):
        for k,v in self.form_fields.items():
            if k.startswith(prefix):
                self.initial[k]=v.get()

    def change_view(self,*_):
        selected=self.view_var.get()
        if selected==self.view:
            return
        if not self.can_leave():
            self.view_var.set(self.view)
            return
        self.view=selected
        self.state["view"]=selected
        self.render()
        self.app.scroll.canvas.yview_moveto(0)

    def go(self,view,round_id=None,hole=None):
        if not self.can_leave():
            return
        if round_id is not None:
            self.state["round_id"]=round_id
        if hole is not None:
            self.state["hole"]=str(hole)
        if self.view==view:
            self.render()
            return
        self.view_var.set(view)

    def render(self):
        self.form_fields={}
        self.initial={}
        for child in self.host.winfo_children():
            child.destroy()
        self.scope=self.store.scope(self.model)
        if self.store.error:
            text(self.host,self.store.error,10,color=AMBER,bg=BG).pack(anchor="w",pady=(0,14))
        if not self.rounds and self.view not in ("Carry & chip practice","Strokes-gained reference"):
            self.app.empty_history(self.host)
            return
        self.report=research_snapshot(self.model,self.rounds,self.scope)
        {VIEWS[0]:self.insights,VIEWS[1]:self.audit,VIEWS[2]:self.journal,VIEWS[3]:self.practice,VIEWS[4]:self.context,VIEWS[5]:self.reference}[self.view]()

    def panel(self,title,subtitle=""):
        return wrap_panel(self.app.section(self.host,title,subtitle))

    def field(self,parent,label,key,initial="",values=None,row=None,column=0):
        variable=tk.StringVar(value="" if initial is None else str(initial))
        self.form_fields[key]=variable
        container=tk.Frame(parent,bg=WHITE)
        if row is None:
            container.pack(fill="x",padx=18,pady=(0,10))
        else:
            parent.columnconfigure(column,weight=1)
            container.grid(row=row,column=column,sticky="ew",padx=(0,14),pady=(0,10))
        text(container,label,9,True,wrap=460).pack(anchor="w",pady=(0,5))
        widget=ttk.Combobox(container,textvariable=variable,values=values,state="readonly",width=28) if values else ttk.Entry(container,textvariable=variable,width=30)
        widget.pack(fill="x",ipady=3)
        return variable

    def action(self,parent,label,callback):
        button=ttk.Button(parent,text=label,command=callback)
        button.pack(side="left",padx=(0,10))
        return button

    def message(self,parent,wrap=1050):
        var=tk.StringVar()
        widget=text(parent,"",9,color=AMBER,wrap=wrap)
        widget.configure(textvariable=var)
        widget.pack(fill="x",padx=18,pady=(0,14))
        return var

    def links(self):
        panel=self.panel("Research sources and limits","These are public methods and descriptive vendor cohorts, not matched experimental proof for your game. No proprietary expected-strokes table is bundled.")
        for name,url in REFERENCES:
            ttk.Button(panel,text=name,command=lambda link=url:webbrowser.open(link)).pack(anchor="w",padx=18,pady=(0,8))
        text(panel,"Use fixed rolling windows for learning, not just hand-picked good or bad rounds. Manual selections are useful for investigating a situation, not proving its future probability.",9,color=MUTED,wrap=1060).pack(anchor="w",padx=18,pady=(6,18))

    def insights(self):
        r=self.report
        b=r["scoring"]
        text(self.host,self.app.selected_description()+". Descriptive priorities and measurement tasks—not validated stroke-saving forecasts.",9,color=MUTED,bg=BG).pack(anchor="w",pady=(0,14))
        facts=r["audit"]["facts"]
        self.app.metrics_row(self.host,[("Double or worse",str(len(b["big_holes"])),f"over {b['scored_holes']} scored holes with par"),
                                      ("Three-putt+ holes",fmt(r["threeputt_rate"])+"%" if r["threeputt_rate"] is not None else "—",f"{b['threeputts']}/{b['tracked_putt_holes']} tracked putting holes"),
                                      ("Detailed coverage",f"{facts.get('shot_holes',0)}/{facts.get('expected_holes',0)}","selected holes with usable shots")])
        priorities=self.panel("Your next actions","Select a priority to see the evidence and a practical next step. Ordering is a transparent rule of thumb, not an estimated strokes-saved ranking.")
        tree=self.app.tree(priorities,[("order","Priority",70),("name","Focus",350),("source","Selected-game evidence",620)],height=max(3,len(r["cards"])))
        for i,card in enumerate(r["cards"]):
            tree.insert("","end",iid=str(i),values=(i+1,card["title"],card["evidence"]))
        evidence=self.message(priorities)
        actions=tk.Frame(priorities,bg=WHITE)
        actions.pack(fill="x",padx=18,pady=(0,18))
        target_button=self.action(actions,"Open selected task →",lambda:open_task())
        def selection(_=None):
            chosen=tree.selection()
            card=r["cards"][int(chosen[0])] if chosen else None
            if card:
                evidence.set(card["evidence"]+"\n\n"+card["action"])
                target_button.configure(state="disabled" if card["kind"]=="insights" else "normal")
            return card
        def open_task():
            card=selection()
            target={"audit":"Tracking audit","journal":"Round journal","practice":"Carry & chip practice","context":"Approach context"}.get(card["kind"]) if card else None
            if target:
                self.go(target)
        tree.bind("<<TreeviewSelect>>",selection)
        if r["cards"]:
            tree.selection_set("0")
            selection()
        flags=self.panel("Where expensive holes happen","Gold bars are double bogeys; red adds triple-or-worse. Flag categories below are mutually exclusive associations, not proof of cause or additive stroke savings.")
        plots=tk.Frame(flags,bg=WHITE)
        plots.pack(fill="x")
        for column,draw in enumerate((draw_par_mistakes,draw_big_hole_flags)):
            plots.columnconfigure(column,weight=1,uniform="mistake-plot")
            holder=tk.Frame(plots,bg=WHITE)
            holder.grid(row=0,column=column,sticky="nsew")
            chart(holder,lambda c,fn=draw:fn(c,b),height=max(260,80+55*len(b["by_par"])))
        text(flags,f"Hypothetical score scenario only: playing every triple-or-worse hole for double instead changes the recorded total by {b['cap_scenario']:.0f} strokes across {b['scored_holes']} scored holes. This is not a forecast, not strokes gained, and overlaps with putting/penalty opportunities.",9,color=AMBER).pack(anchor="w",padx=18,pady=(0,18))
        accounting=self.app.tree(flags,[("name","Exclusive big-hole group",260),("holes","Holes",80),("gross","Gross strokes",120),("over","Strokes over par",140),("cap","Strokes above double",170)],height=max(3,len(b["flag_costs"])))
        for name,cost in b["flag_costs"].items():
            accounting.insert("","end",values=(name,cost["holes"],fmt(cost["gross_strokes"],0),fmt(cost["over_par"],0),fmt(cost["above_double"],0)))
        text(flags,"Every big hole appears once in this score accounting. Its whole score is grouped by recorded flags, not causally assigned to them. Do not add these descriptive totals to separate putting or penalty 'savings'.",9,color=MUTED).pack(anchor="w",padx=18,pady=(0,12))
        ttk.Button(flags,text="Export exclusive score accounting",command=lambda:self.app.export_table(accounting,"big-hole-accounting.csv")).pack(anchor="w",padx=18,pady=(0,18))
        table=self.panel("Big-hole review queue","Review the shot sequence before blaming a club or assuming a fairway miss caused the entire score.")
        tree=self.app.tree(table,[("date","Date",100),("course","Course",230),("hole","Hole",55),("par","Par",50),("score","Score",60),("delta","Over par",75),("putts","Putts",60),("pen","Penalty",70),("source","Recorded flags",200)],height=min(10,max(3,len(b["big_holes"]))))
        lookup={}
        for i,item in enumerate(b["big_holes"]):
            key=str(i)
            lookup[key]=item
            tree.insert("","end",iid=key,values=(item["date"],item["course"],item["hole"],fmt(item["par"],0),fmt(item["score"],0),fmt(item["to_par"],0),fmt(item["putts"],0),fmt(item["penalties"],0),item["flag"]))
        actions=tk.Frame(table,bg=WHITE)
        actions.pack(fill="x",padx=18,pady=(0,18))
        def selected():
            ids=tree.selection()
            return lookup.get(ids[0]) if ids else None
        self.action(actions,"Open scorecard",lambda:self.app.go_round(selected()["round_id"]) if selected() else None)
        self.action(actions,"Journal this hole",lambda:self.go("Round journal",selected()["round_id"],selected()["hole"]) if selected() else None)
        self.action(actions,"Export breakdown",lambda:self.app.export_table(tree,"big-hole-research.csv"))
        putts=self.panel("What starts the three-putts?","First-putt bins include successful and unsuccessful holes. A missing bin is not counted as a short putt; chip-ins do not have a first putt.")
        chart(putts,lambda c:draw_putt_bins(c,r["putting"]["groups"]),height=max(150,60+42*len(r["putting"]["groups"])))
        text(putts,f"{len(r['putting']['holes'])} selected holes currently have a usable first-putt bin and scorecard count. Add the missing context in Round journal.",9,color=MUTED).pack(anchor="w",padx=18,pady=(0,18))
        benchmark=self.panel("Broad published benchmarks — context, not a diagnosis","Shot Scope lists 35% GIR for its 10-handicap sample, 23% GIR and about 10% three-putt holes for its 15-handicap sample. Cohorts, courses, tees and tracking differ.")
        text(benchmark,f"Your selected recorded GIR: {fmt(r['stats']['gir'])}%. Three-putt+ rate over tracked scorecard holes: {fmt(r['threeputt_rate'])}%. Check the inputs before assigning practice time from this comparison.",10,wrap=1060).pack(anchor="w",padx=18,pady=(0,18))
        rating=self.panel("Course difficulty matters","This gross-score proxy adjusts for the recorded rating/slope only: 113 × (gross score − rating) / slope. PCC and handicap-adjusted gross corrections are absent. It is NOT an official WHS differential or Handicap Index.")
        chart(rating,lambda c:draw_history_trend(c,r["rating_proxy"],self.app.rolling_window,self.app.go_round),height=270)
        text(rating,"For a full official WHS record, the best eight of the latest twenty differentials matter, with safeguards—not simply average gross score. The app does not relabel your Garmin handicap as a verified WHS index.",9,color=MUTED).pack(anchor="w",padx=18,pady=(0,18))
        self.links()

    def audit(self):
        audit=self.report["audit"]
        facts=audit["facts"]
        text(self.host,f"Tracking: scores {facts.get('scored_holes',0)}/{facts.get('expected_holes',0)} holes · putts {facts.get('putt_holes',0)} · explicit penalties {facts.get('penalty_holes',0)} · detailed shots {facts.get('shot_holes',0)}. Review acknowledgments never turn missing records into valid data.",10,bold=True,bg=BG).pack(anchor="w",pady=(0,16))
        panel=self.panel("Tracking audit and review queue","Verified here means reviewed locally, not corrected in Garmin. Known missing data remains missing until a corrected export is imported.")
        tree=self.app.tree(panel,[("severity","Type",85),("date","Date",105),("course","Course",220),("hole","Hole",55),("name","Check",260),("source","Review",130)],height=12)
        lookup={}
        for i,item in enumerate(audit["items"]):
            key=str(i)
            lookup[key]=item
            tree.insert("","end",iid=key,values=(item["severity"],item["date"],item["course"],item["hole"] or "—",item["title"],"Reviewed" if item["review_status"]=="Verified" else item["review_status"]),tags=("caution" if item["severity"]=="Missing" else "",))
        detail=tk.StringVar(value="Select a check to read why it matters.")
        tk.Label(panel,textvariable=detail,bg=WHITE,fg=MUTED,font=(FONT,10),wraplength=1060,justify="left",anchor="w").pack(fill="x",padx=18,pady=(0,12))
        def selected():
            ids=tree.selection()
            return lookup.get(ids[0]) if ids else None
        tree.bind("<<TreeviewSelect>>",lambda _:detail.set(selected()["detail"] if selected() else ""))
        actions=tk.Frame(panel,bg=WHITE)
        actions.pack(fill="x",padx=18,pady=(0,18))
        status=self.message(panel)
        def review():
            item=selected()
            if item:
                try:
                    self.store.save_review(self.model,item["key"],"Verified")
                    tree.set(tree.selection()[0],"source","Reviewed")
                    status.set("Acknowledged locally. This does not fix or hide the underlying tracking gap.")
                except ResearchStoreError as exc:
                    status.set(str(exc))
        def shot():
            item=selected()
            if not item:
                return
            if item["shot_key"] is None:
                self.go("Round journal",item["round_id"],item["hole"])
                return
            contexts,_=shot_contexts(self.model,self.rounds,self.store.scope(self.model))
            record=next((r for r in contexts if r["round_id"]==item["round_id"] and r["key"]==item["shot_key"]),None)
            if record:
                dialog=ShotReview(self.app.root,self.model,self.store,record)
                self.app.root.wait_window(dialog)
                if dialog.saved:
                    self.render()
        self.action(actions,"Mark reviewed, not fixed",review)
        self.action(actions,"Review context / journal",shot)
        self.action(actions,"Open scorecard",lambda:self.app.go_round(selected()["round_id"]) if selected() else None)
        self.action(actions,"Export audit",lambda:self.app.export_table(tree,"tracking-audit.csv"))
        readiness=self.panel("What these records can support","Historical counts and broad proxies are different from calibrated probabilities for the next shot.")
        for value in (
            "Putting research: verify scorecard counts and record first-putt distances, not just total putts.",
            "Club-specific research: assign the actual clubs in Garmin, and preserve ordinary mishits instead of deleting them.",
            "Strokes gained: supply a defensible reference and checked states. Unverified GPS green distances are never used as precise putting states.",
            "Positive-EV target choice: still needs representative error/intent/condition data and current hazard geometry. Reviewing this queue does not train that model."):
            text(readiness,"• "+value,10,wrap=1050).pack(anchor="w",padx=18,pady=(0,12))

    def journal(self):
        controls=tk.Frame(self.host,bg=BG)
        controls.pack(fill="x",pady=(0,16))
        choices={}
        for r in self.rounds:
            name=f"{r['date']} · {r['course']}"
            if name in choices:
                name+=f" ({len(choices)+1})"
            choices[name]=r["id"]
        rid=self.state.get("round_id")
        if rid not in choices.values():
            rid=self.rounds[0]["id"]
        r=next(x for x in self.rounds if x["id"]==rid)
        self.state["round_id"]=rid
        round_var=tk.StringVar(value=next(n for n,k in choices.items() if k==rid))
        round_picker=ttk.Combobox(controls,textvariable=round_var,values=list(choices),state="readonly",width=54)
        round_picker.pack(side="left",ipady=3)
        numbers=[str(h["number"]) for h in r["holes"] if number_is_valid(h.get("strokes"))]
        if not numbers:
            text(self.host,"No per-hole entries are available for this game. Re-import its scorecard before adding hole observations.",10,color=AMBER,bg=BG).pack(anchor="w")
            return
        current=self.state.get("hole")
        if current not in numbers:
            current=numbers[0]
        self.state["hole"]=current
        hole_var=tk.StringVar(value=current)
        text(controls,"Hole",9,True,bg=BG).pack(side="left",padx=(14,6))
        hole_picker=ttk.Combobox(controls,textvariable=hole_var,values=numbers,state="readonly",width=6)
        hole_picker.pack(side="left",ipady=3)
        def change_round(_):
            if not self.can_leave():
                round_var.set(next(n for n,k in choices.items() if k==rid))
                return
            self.state.update(round_id=choices[round_var.get()],hole=None)
            self.render()
        def change_hole(_):
            if not self.can_leave():
                hole_var.set(current)
                return
            self.state["hole"]=hole_var.get()
            self.render()
        round_picker.bind("<<ComboboxSelected>>",change_round)
        hole_picker.bind("<<ComboboxSelected>>",change_hole)
        hole=next(h for h in r["holes"] if str(h["number"])==current)
        text(self.host,f"Recorded score {fmt(hole.get('strokes'),0)} · putts {fmt(hole.get('putts'),0)} · penalties {fmt(hole.get('penalties'),0)}. Notes do not replace these source values; correct Garmin and re-import if they are wrong.",9,color=MUTED,bg=BG).pack(anchor="w",pady=(0,16))
        columns=tk.Frame(self.host,bg=BG)
        columns.pack(fill="x",pady=(0,18))
        for c in (0,1):
            columns.columnconfigure(c,weight=1,uniform="journal")
        left,right=tk.Frame(columns,bg=BG),tk.Frame(columns,bg=BG)
        left.grid(row=0,column=0,sticky="nsew",padx=(0,14))
        right.grid(row=0,column=1,sticky="nsew")
        round_panel=wrap_panel(self.app.section(left,"Verify this scorecard","Mark verified only after checking against actual play. GPS putt omissions alone do not prove a wrong total. A changed import requires rechecking the affected review."))
        note=self.store.round_note(self.model,rid)
        for field,label in (("putts_status","Putt counts"),("penalties_status","Penalty counts"),("pin_status","Recorded pin positions")):
            self.field(round_panel,label,"round_"+field,note.get(field,"Unchecked"),CHECK_STATUSES)
        self.field(round_panel,"Round review note","round_note",note.get("note",""))
        rstatus=self.message(round_panel,400)
        ractions=tk.Frame(round_panel,bg=WHITE)
        ractions.pack(fill="x",padx=18,pady=(0,18))
        def save_round():
            try:
                self.store.save_round(self.model,rid,{k.removeprefix("round_"):v.get() for k,v in self.form_fields.items() if k.startswith("round_")})
                self.mark_saved("round_")
                rstatus.set("Round review saved locally. Missing or inconsistent source data is not silently corrected.")
            except (ValueError,ResearchStoreError) as exc:
                rstatus.set(str(exc))
        self.save_round_action=save_round
        self.action(ractions,"Save round review",save_round)
        self.action(ractions,"Open scorecard",lambda:self.app.go_round(rid))
        panel=wrap_panel(self.app.section(right,"First-putt and penalty context","Record successful holes as well as failures. Exact distance is optional; say whether it is estimated or measured."))
        note=self.store.hole_note(self.model,rid,current)
        if note and note.get("source_signature")!=hole_signature(r,hole):
            text(panel,"Source values changed since this note was saved. Check the retained notes and save again before using them in research.",9,color=AMBER,wrap=400).pack(anchor="w",padx=18,pady=(0,12))
        self.field(panel,"First-putt distance bin","hole_first_putt_bin",note.get("first_putt_bin","Not recorded"),PUTT_BINS)
        self.field(panel,"First putt (feet, optional)","hole_first_putt_feet",note.get("first_putt_feet"))
        self.field(panel,"Distance basis","hole_distance_basis",note.get("distance_basis","Not supplied"),("Not supplied","Estimated","Measured"))
        self.field(panel,"Strokes from first putt through hole-out (optional)","hole_strokes_from_first_putt",note.get("strokes_from_first_putt"))
        text(panel,"Include the first putt and ALL later strokes/penalties, even off-green recoveries. Required only for first-putt sequence reference values; a bin alone still supports the three-putt chart.",9,color=MUTED,wrap=400).pack(anchor="w",padx=18,pady=(0,12))
        self.field(panel,"Penalty phase","hole_penalty_phase",note.get("penalty_phase","Unknown"),PENALTY_PHASES)
        self.field(panel,"Penalty reason","hole_penalty_reason",note.get("penalty_reason","Unknown"),PENALTY_REASONS)
        short=tk.BooleanVar(value=note.get("missed_short_return",False))
        self.form_fields["hole_missed_short_return"]=short
        ttk.Checkbutton(panel,text="A short return putt was missed",variable=short).pack(anchor="w",padx=18,pady=(0,12))
        self.field(panel,"Hole note","hole_note",note.get("note",""))
        hstatus=self.message(panel,400)
        actions=tk.Frame(panel,bg=WHITE)
        actions.pack(fill="x",padx=18,pady=(0,18))
        def save_hole():
            try:
                self.store.save_hole(self.model,rid,current,{k.removeprefix("hole_"):v.get() for k,v in self.form_fields.items() if k.startswith("hole_")})
                saved=self.store.hole_note(self.model,rid,current)
                self.form_fields["hole_first_putt_bin"].set(saved["first_putt_bin"])
                self.mark_saved("hole_")
                hstatus.set("Hole context saved. A bin is inferred from exact feet when supplied; it is not converted into invented SG.")
                refresh_summary()
            except (ValueError,ResearchStoreError) as exc:
                hstatus.set(str(exc))
        self.save_hole_action=save_hole
        self.action(actions,"Save hole context",save_hole)
        summary=tk.Frame(self.host,bg=BG)
        summary.pack(fill="x")
        def refresh_summary():
            for child in summary.winfo_children():
                child.destroy()
            data=putting_context(self.rounds,self.store.scope(self.model))
            panel=wrap_panel(self.app.section(summary,"Three-putts by starting distance","These denominators use current saved bins and recorded putts. Untagged or outdated notes are not assumed short or successful."))
            chart(panel,lambda c:draw_putt_bins(c,data["groups"]),height=max(160,60+42*len(data["groups"])))
            tree=self.app.tree(panel,[("name","First-putt bin",150),("holes","Holes",75),("three","3+ holes",90),("rate","3+ rate",100),("putts","Mean putts",110),("returns","Short-return flags",160)],height=max(3,min(6,len(data["groups"]))))
            for group in data["groups"]:
                tree.insert("","end",values=(group["bin"],group["holes"],group["threeputts"],fmt(group["rate"])+"%",fmt(group["average_putts"]),group["short_returns"]))
        refresh_summary()
        self.remember_form()

    def practice(self):
        text(self.host,"Practice measurements are separate from the selected on-course games and are scoped to this player account. Do not replace carry with total GPS distance, or remove ordinary mishits to make a pattern look better.",9,color=MUTED,bg=BG).pack(anchor="w",pady=(0,16))
        names={}
        for key,club in self.model.clubs.items():
            if key!="0" and not club.get("deleted") and not club.get("retired"):
                name=self.model.club_label(key)[0]
                base=name
                suffix=2
                while name in names:
                    name=f"{base} ({suffix})"
                    suffix+=1
                names[name]=key
        if not names:
            self.app.empty(self.host,"Import your account and bag first.","Practice measurements need an account-scoped club identity; no sample club measurements are substituted.")
            return
        entry=self.panel("Record a measured practice attempt","Keep the session/lie/conditions matched when comparing clubs. Full swings, partial pitches, and chip trials are analyzed separately.")
        grid=tk.Frame(entry,bg=WHITE)
        grid.pack(fill="x",padx=18,pady=(0,10))
        defaults=self.state.get("practice_defaults",{})
        fields=(
            ("date","Date (YYYY-MM-DD)",defaults.get("date",date.today().isoformat()),None),
            ("club","Club",defaults.get("club",next(iter(names))),tuple(names)),
            ("role","Shot role",defaults.get("role","Full swing"),("Full swing","Controlled pitch","Chip trial")),
            ("session","Matched session / target",defaults.get("session",""),None),
            ("lie","Lie / surface",defaults.get("lie",""),None),
            ("conditions","Conditions",defaults.get("conditions","Unknown"),CONDITIONS),
            ("contact","Contact tag","Normal attempt",("Normal attempt","Mishit","Tracking error")),
            ("carry_yards","Measured carry (yards)","",None),
            ("lateral_yards","Lateral error (yd; left −, right +)","",None),
            ("on_green","Chip ended on green","Unknown",("Unknown","Yes","No")),
            ("finish_feet","Chip finish distance (feet)","",None),
            ("strokes_to_finish","Chip trial: total strokes INCLUDING chip","",None),
        )
        for i,(key,title,value,options) in enumerate(fields):
            if key=="club" and value not in names:
                value=next(iter(names))
            self.field(grid,title,"practice_"+key,value,options,row=i//2,column=i%2)
        status=self.message(entry)
        actions=tk.Frame(entry,bg=WHITE)
        actions.pack(fill="x",padx=18,pady=(0,18))
        summaries=tk.Frame(self.host,bg=BG)
        summaries.pack(fill="x")
        def add():
            values={k.removeprefix("practice_"):v.get() for k,v in self.form_fields.items() if k.startswith("practice_")}
            values["club_id"]=names[values["club"]]
            try:
                self.store.add_practice(self.model,values)
            except (ValueError,ResearchStoreError) as exc:
                status.set(str(exc))
                return
            self.state["practice_defaults"]={k:values[k] for k in ("date","club","role","session","lie","conditions")}
            for key in ("carry_yards","lateral_yards","finish_feet","strokes_to_finish"):
                self.form_fields["practice_"+key].set("")
            self.form_fields["practice_contact"].set("Normal attempt")
            self.form_fields["practice_on_green"].set("Unknown")
            self.remember_form()
            status.set("Attempt saved privately. Normal mishits are included; only explicitly tagged tracking errors are excluded from summaries.")
            draw_summaries()
        self.add_practice_action=add
        self.action(actions,"Add practice attempt",add)
        def draw_summaries():
            for child in summaries.winfo_children():
                child.destroy()
            data=practice_summary(self.model,self.store.scope(self.model))
            carry=wrap_panel(self.app.section(summaries,"Carry gaps and real error spread","Empirical p10/median/p90 describe your recorded attempts, not a guaranteed carry or a learned penalty probability. Small samples cannot establish rare-error tails."))
            tree=self.app.tree(carry,[("club","Club",130),("name","Role / session / lie / conditions",310),("n","Attempts",75),("p10","Carry p10",90),("median","Median yd",90),("p90","Carry p90",90),("mishit","Mishits",75),("pairs","Paired errors",100)],height=min(8,max(3,len(data["carry"]))))
            plot_rows={}
            for i,row in enumerate(data["carry"]):
                key=str(i)
                plot_rows[key]=row
                tree.insert("","end",iid=key,values=(row["club"]," · ".join((row["role"],row["date"],row["session"],row["lie"],row["conditions"])),row["n"],fmt(row["p10"]),fmt(row["median"]),fmt(row["p90"]),row["mishits"],row["pairs"]),tags=("caution" if row["n"]<20 else "",))
            state={"row":next(iter(plot_rows.values()),None)}
            canvas=chart(carry,lambda c:draw_carry_samples(c,state["row"]),height=290)
            def select(_):
                ids=tree.selection()
                if ids:
                    state["row"]=plot_rows[ids[0]]
                    draw_carry_samples(canvas,state["row"])
            tree.bind("<<TreeviewSelect>>",select)
            text(carry,"Select one matched group to view paired carry/lateral attempts. No independent Gaussian ellipse, flight model, or current-hole EV is inferred.",9,color=MUTED).pack(anchor="w",padx=18,pady=(0,16))
            chip=wrap_panel(self.app.section(summaries,"Matched chip trials","Compare like session, lie, conditions and target—not all chips with one club against easier chips with another. Rotate clubs within the session to reduce order effects."))
            chips=self.app.tree(chip,[("club","Club",140),("name","Session / lie",250),("n","Trials",70),("green","On green",95),("median","Median leave ft",120),("worst","Worst leave ft",120),("strokes","Mean total strokes",140),("costn","Finish counts",100)],height=min(8,max(3,len(data["chips"]))))
            for row in data["chips"]:
                chips.insert("","end",values=(row["club"]," · ".join((row["date"],row["session"],row["lie"],row["conditions"])),row["records"],fmt(row["rate"])+"%" if row["rate"] is not None else "—",fmt(row["median_finish"]),fmt(row["worst_finish"]),fmt(row["mean_strokes"],2),len(row["strokes"])))
            text(chip,"Mean trial strokes includes the chip only when you explicitly log the total through hole-out. This is an observed practice comparison, not proven causal on-course EV.",9,color=MUTED).pack(anchor="w",padx=18,pady=(0,16))
            raw=wrap_panel(self.app.section(summaries,"Private practice records","Tracking-error tags stay in this audit list. Do not tag an ordinary poor strike as a tracking error just to clean the statistics."))
            records=self.app.tree(raw,[("date","Date",100),("club","Club",130),("name","Role / session",230),("carry","Carry yd",85),("lateral","Lateral yd",90),("source","Contact tag",150),("finish","Leave ft",85),("strokes","Total strokes",100)],height=7)
            ids={}
            for i,row in enumerate(reversed(data["records"])):
                key=str(i)
                ids[key]=row["id"]
                records.insert("","end",iid=key,values=(row["date"],self.model.club_label(row["club_id"])[0],row["role"]+" · "+row.get("session",""),fmt(row.get("carry_yards")),fmt(row.get("lateral_yards")),row.get("contact",""),fmt(row.get("finish_feet")),fmt(row.get("strokes_to_finish"),0)))
            buttons=tk.Frame(raw,bg=WHITE)
            buttons.pack(fill="x",padx=18,pady=(0,18))
            def delete():
                chosen=records.selection()
                if chosen and messagebox.askyesno("Remove practice attempt?","Remove only this selected local practice record? Garmin data and other records stay unchanged.",parent=self.app.root):
                    try:
                        self.store.delete_practice(self.model,ids[chosen[0]])
                        draw_summaries()
                    except ResearchStoreError as exc:
                        status.set(str(exc))
            self.action(buttons,"Delete selected local attempt",delete)
            self.action(buttons,"Export practice audit",lambda:self.app.export_table(records,"private-practice-records.csv"))
        draw_summaries()
        self.remember_form()


    def context(self):
        only=tk.BooleanVar(value=self.state.get("green_attempts_only",False))
        controls=tk.Frame(self.host,bg=BG)
        controls.pack(fill="x",pady=(0,14))
        def change():
            self.state["green_attempts_only"]=only.get()
            self.render()
        ttk.Checkbutton(controls,text="Exclude locally tagged lay-ups / recoveries",style="History.TCheckbutton",variable=only,command=change).pack(side="left")
        data=approach_context(self.model,self.rounds,self.scope,only.get())
        panel=self.panel("Compare the actual shot context","Distance bins use start-to-recorded-pin proxies only after endpoint-length consistency checks. That does not validate the actual cup location, map boundaries, or GPS putting accuracy. User-confirmed local states are labeled separately.")
        valid=sum(r["validation"] is not None for r in data["validations"])
        text(panel,f"{valid}/{len(data['validations'])} selected games have internally consistent coordinate scales. {data['unknown_distance']} of {len(data['records'])} approaches lack a usable starting-distance proxy. Unknowns are retained.",10,color=MUTED).pack(anchor="w",padx=18,pady=(0,16))
        grouped=self.app.tree(panel,[("club","Club",150),("name","Distance band",150),("lie","Starting lie",100),("n","Shots",65),("green","On green",80),("miss","Off green",80),("unknown","Unknown",80),("rate","Hit rate",90),("median","Median start yd",130),("intent","Intent unknown",125)],height=min(12,max(3,len(data["groups"]))))
        for row in sorted(data["groups"],key=lambda x:(x["band"],x["lie"],x["club"])):
            grouped.insert("","end",values=(row["club"],row["band"],row["lie"],row["shots"],row["green"],row["miss"],row["unknown"],fmt(row["rate"])+"%" if row["rate"] is not None else "—",fmt(row["median_yards"]),row["intent_unknown"]),tags=("caution" if row["shots"]<10 else "",))
        text(panel,"Do not conclude a long wood is a worse club than a wedge from these binary outcomes. The task, distance, lie, intent, and miss cost differ. There is no automatic current-shot probability or SG estimate here.",9,color=AMBER).pack(anchor="w",padx=18,pady=(0,18))
        records=self.panel("Approach review and intent notes","Record actual intent rather than reclassifying ordinary mishits as tracking errors. Local research filters do not rewrite the main Garmin-export statistics.")
        tree=self.app.tree(records,[("date","Date",100),("hole","Hole",55),("club","Club",140),("distance","Start yd",90),("lie","From",90),("end","Finish",90),("intent","Intent",140),("source","Distance basis",190)],height=10)
        lookup={}
        for i,row in enumerate(data["records"]):
            key=str(i)
            lookup[key]=row
            tree.insert("","end",iid=key,values=(row["date"],row["hole"],row["club"],fmt(row["start_yards"]),row["start_lie"],row["end_lie"],row["intent"],row["distance_source"]))
        actions=tk.Frame(records,bg=WHITE)
        actions.pack(fill="x",padx=18,pady=(0,18))
        def review():
            selected=tree.selection()
            if selected:
                dialog=ShotReview(self.app.root,self.model,self.store,lookup[selected[0]])
                self.app.root.wait_window(dialog)
                if dialog.saved:
                    self.render()
        self.action(actions,"Review selected shot / intent",review)
        self.action(actions,"Export context table",lambda:self.app.export_table(grouped,"approach-context.csv"))

    def reference(self):
        current=reference_results(self.model,self.rounds,self.scope)
        self.current_reference=current["reference"]
        if current["error"]:
            text(self.host,current["error"],10,color=AMBER,bg=BG).pack(anchor="w",pady=(0,14))
        reference=self.current_reference
        panel=self.panel("A reference-driven workbench, not invented personal SG","No proprietary expected-strokes reference is included. Import a reference you are allowed to use, with a named population/source. Format validation does not establish benchmark accuracy or personal calibration.")
        grid=tk.Frame(panel,bg=WHITE)
        grid.pack(fill="x",padx=18,pady=(0,8))
        self.field(grid,"Reference name","reference_name",reference.name if reference else "",row=0,column=0)
        self.field(grid,"Goal / population label","reference_population",reference.population if reference else "",row=0,column=1)
        self.field(panel,"Source / attribution","reference_source",reference.source if reference else "")
        permission=tk.BooleanVar(value=False)
        self.form_fields["reference_permission"]=permission
        ttk.Checkbutton(panel,text="I have permission to use this reference privately",variable=permission).pack(anchor="w",padx=18,pady=(0,12))
        status=self.message(panel)
        actions=tk.Frame(panel,bg=WHITE)
        actions.pack(fill="x",padx=18,pady=(0,16))
        results=tk.Frame(self.host,bg=BG)
        # The calculator is inserted before the selected-record results below.
        def template():
            path=filedialog.asksaveasfilename(parent=self.app.root,title="Save blank reference template",initialdir=str(self.app.data_dir),initialfile="expected-strokes-template.csv",defaultextension=".csv",filetypes=[("CSV","*.csv")])
            if path:
                try:
                    with open(path,"w",encoding="utf-8",newline="") as handle:
                        csv.writer(handle).writerow(("lie","distance_yards","expected_strokes"))
                    status.set("Saved headers only. No example numbers were supplied as real golf baselines.")
                except OSError:
                    status.set("The template could not be saved in that folder.")
        def import_reference():
            if not permission.get():
                status.set("Confirm permission to use the file, then choose it.")
                return
            path=filedialog.askopenfilename(parent=self.app.root,title="Import expected-strokes reference",filetypes=[("CSV","*.csv")])
            if not path:
                return
            try:
                imported=StrokeReference.from_csv(Path(path),self.form_fields["reference_name"].get(),self.form_fields["reference_population"].get(),self.form_fields["reference_source"].get(),True)
                if self.current_reference and not messagebox.askyesno("Replace this reference?","Replace only this account's saved expected-strokes reference? Round notes, practice records and Garmin exports stay unchanged.",parent=self.app.root):
                    return
                self.store.save_baseline(self.model,imported.to_dict())
                self.current_reference=imported
                self.mark_saved("reference_")
                status.set(f"Imported {len(imported.points)} user-supplied points. No extrapolation is permitted; provenance is displayed, not independently certified.")
                refresh_results()
            except (OSError,ValueError,ResearchStoreError) as exc:
                status.set(str(exc))
        self.action(actions,"Import permitted reference CSV",import_reference)
        self.action(actions,"Save blank CSV template",template)
        text(panel,"CSV columns: lie,distance_yards,expected_strokes. All reference distances are yards, including green distances (feet ÷ 3). Each lie needs at least two distinct supported distances and nondecreasing expected strokes. Holed is handled explicitly, not as a zero-distance interpolation row.",9,color=MUTED).pack(anchor="w",padx=18,pady=(0,18))
        calculator=self.panel("Evaluate one observed shot against the reference","This is an after-shot state comparison—not the probability that a proposed future target will succeed. Use checked distances/lies; don't infer precise green distances from GPS.")
        form=tk.Frame(calculator,bg=WHITE)
        form.pack(fill="x",padx=18,pady=(0,10))
        saved=self.state.get("sg_calculator",{})
        fields=(("start","Start distance",saved.get("start",""),None),("start_unit","Start unit",saved.get("start_unit","yards"),("yards","feet")),
                ("start_lie","Start lie",saved.get("start_lie","Fairway"),LIES),("end","End distance",saved.get("end",""),None),
                ("end_unit","End unit",saved.get("end_unit","yards"),("yards","feet")),("end_lie","End lie",saved.get("end_lie","Green"),LIES),
                ("penalty","Immediate penalty strokes",saved.get("penalty","0"),None))
        for i,(key,title,value,options) in enumerate(fields):
            self.field(form,title,"calc_"+key,value,options,row=i//3,column=i%3)
        holed=tk.BooleanVar(value=saved.get("holed",False))
        self.form_fields["calc_holed"]=holed
        ttk.Checkbutton(calculator,text="Shot explicitly holed",variable=holed).pack(anchor="w",padx=18,pady=(0,12))
        result=self.message(calculator)
        self.reference_result_message=result
        def calculate():
            try:
                if self.current_reference is None:
                    raise ValueError("Import a valid, appropriately sourced reference first. No substitute benchmark is invented.")
                values={k.removeprefix("calc_"):v.get() for k,v in self.form_fields.items() if k.startswith("calc_")}
                start=numeric(values["start"],"start distance",0.001,3600)
                end=None if holed.get() else numeric(values["end"],"end distance",0.001,3600)
                if values["start_unit"]=="feet" and start is not None:
                    start/=3
                if values["end_unit"]=="feet" and end is not None:
                    end/=3
                score=self.current_reference.shot_value(start,values["start_lie"],end,values["end_lie"],values["penalty"],holed.get())
                self.state["sg_calculator"]=values
                self.mark_saved("calc_")
                result.set(f"Reference shot value: {score:+.2f} strokes vs {self.current_reference.name}. Formula: V(start) − 1 current stroke − immediate penalty − V(end). This is conditional on the supplied states/reference, not proven positive EV for your next shot.")
            except (ValueError,KeyError) as exc:
                result.set(str(exc))
        self.calculate_reference_action=calculate
        row=tk.Frame(calculator,bg=WHITE)
        row.pack(fill="x",padx=18,pady=(0,18))
        self.action(row,"Calculate against saved reference",calculate)
        results.pack(fill="x")
        def refresh_results():
            for child in results.winfo_children():
                child.destroy()
            data=reference_results(self.model,self.rounds,self.store.scope(self.model))
            ref=data["reference"]
            panel=wrap_panel(self.app.section(results,"Supported selected-record analysis","Only current, user-confirmed records with supported reference distances are included. Never interpret this partial subset as whole-round SG, a calibrated future-shot model, or a handicap forecast."))
            title=f"Reference: {ref.name} · population label: {ref.population or 'not supplied'} · source: {ref.source}" if ref else "No saved reference. Add one only if you can provide a defensible source and permission."
            text(panel,title,10,True,wrap=1060).pack(anchor="w",padx=18,pady=(0,14))
            text(panel,f"Supported first-putt sequences: {len(data['putting'])}; supported non-putting shots: {len(data['shots'])}; attempted annotated records blocked: {len(data['blocked'])}. Unannotated or uncovered records are not assigned zero SG.",9,color=MUTED).pack(anchor="w",padx=18,pady=(0,14))
            tree=self.app.tree(panel,[("date","Date",105),("hole","Hole",55),("name","Record",200),("sg","Reference SG",115),("source","Basis / scope",250)],height=7)
            for r in data["putting"]:
                tree.insert("","end",values=(r["date"],r["hole"],f"From first putt: {r['strokes_to_finish']} strokes",f"{r['sg']:+.2f}",r["basis"]+" first distance; checked hole-out total"))
            for r in data["shots"]:
                tree.insert("","end",values=(r["date"],r["hole"],r["club"]+" · "+r["role"],f"{r['sg']:+.2f}","User-confirmed states / checked penalty allocation"))
            actions=tk.Frame(panel,bg=WHITE)
            actions.pack(fill="x",padx=18,pady=(0,16))
            self.action(actions,"Export supported subset",lambda:self.app.export_table(tree,"supported-reference-sg.csv"))
            if data["blocked"]:
                blockers=self.app.tree(panel,[("date","Date",100),("hole","Hole",55),("name","Type",100),("source","Why blocked",700)],height=min(8,max(3,len(data["blocked"]))))
                for r in data["blocked"]:
                    blockers.insert("","end",values=(r["date"],r["hole"],r["kind"],r["reason"]))
            text(panel,"A first-putt sequence uses explicit feet and all strokes through hole-out, including recoveries/penalties; it is not isolated putting SG if non-putting strokes follow. Do not sum it with overlapping later shots. Non-putting shots need checked states, an explicit immediate penalty (including zero), and reconciled verified hole penalties. No extrapolation is used.",9,color=AMBER).pack(anchor="w",padx=18,pady=(0,18))
            queue=wrap_panel(self.app.section(results,"Check observed shot states","Tee, approach, chip and recovery records can all be reviewed here. A GPS draft is never auto-verified, and changed source shots require a fresh check."))
            contexts,_=shot_contexts(self.model,self.rounds,self.store.scope(self.model))
            self.reference_shot_records=[record for record in contexts if record["role"]!="PUTT"]
            states=self.app.tree(queue,[("date","Date",100),("hole","Hole",55),("club","Club",140),("name","Role",120),("intent","Intent",140),("source","State review",220)],height=8)
            lookup={}
            for i,record in enumerate(self.reference_shot_records):
                key=str(i)
                lookup[key]=record
                review="Needs recheck" if record["note"].get("states_verified") and not record["states_current"] else "States checked" if record["note"].get("states_verified") else "Unchecked"
                states.insert("","end",iid=key,values=(record["date"],record["hole"],record["club"],record["role"],record["intent"],review))
            def check_shot():
                chosen=states.selection()
                if chosen and self.can_leave():
                    dialog=ShotReview(self.app.root,self.model,self.store,lookup[chosen[0]])
                    self.app.root.wait_window(dialog)
                    if dialog.saved:
                        refresh_results()
            actions=tk.Frame(queue,bg=WHITE)
            actions.pack(fill="x",padx=18,pady=(0,18))
            self.action(actions,"Review selected shot states",check_shot)
            self.action(actions,"Open first-putt journal",lambda:self.go("Round journal"))
        refresh_results()
        self.remember_form()


def number_is_valid(value):
    return number(value) is not None and value>0
