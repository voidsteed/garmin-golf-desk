"""Checkbox-based selection of any imported completed games."""

import tkinter as tk
from tkinter import messagebox,ttk

from golf_history import RoundSelection,eligible_rounds

WHITE,INK,MUTED,GREEN = "#FFFFFF","#15382E","#65766D","#137B56"
FONT="Segoe UI"


class RoundPicker(tk.Toplevel):
    def __init__(self,parent,model,selection):
        super().__init__(parent)
        self.withdraw()
        self.title("Choose games to analyze")
        self.configure(bg=WHITE)
        self.transient(parent)
        self.minsize(850,500)
        width=max(850,min(1080,parent.winfo_screenwidth()-100))
        height=max(500,min(760,parent.winfo_screenheight()-160))
        self.geometry(f"{width}x{height}+{max(20,parent.winfo_rootx()+80)}+{max(20,parent.winfo_rooty()+60)}")
        self.model=model
        self.result=None
        self.checked={r["id"] for r in selection.resolve(model)}
        self.full_only=tk.BooleanVar(value=selection.full_only)
        self.search=tk.StringVar()
        self.summary=tk.StringVar()
        heading=tk.Frame(self,bg=WHITE,padx=22,pady=18)
        heading.pack(fill="x")
        tk.Label(heading,text="Choose your games",font=(FONT,20,"bold"),fg=INK,bg=WHITE,anchor="w").pack(anchor="w")
        tk.Label(heading,text="Click a checkbox, double-click a row, or press Space. Statistics use only checked games, in date order.",font=(FONT,10),fg=MUTED,bg=WHITE,anchor="w",justify="left",wraplength=width-44).pack(anchor="w",pady=(7,0))
        tools=tk.Frame(self,bg=WHITE,padx=22)
        tools.pack(fill="x",pady=(0,14))
        ttk.Entry(tools,textvariable=self.search,width=40).pack(side="left",ipady=4)
        tk.Label(tools,text="Search course or date",font=(FONT,9),fg=MUTED,bg=WHITE).pack(side="left",padx=10)
        ttk.Checkbutton(tools,text="18-hole games only",variable=self.full_only,command=self.refresh).pack(side="right")
        table=tk.Frame(self,bg=WHITE,padx=22)
        table.pack(fill="both",expand=True)
        columns=("check","date","course","holes","score","greens","putts")
        self.tree=ttk.Treeview(table,columns=columns,show="headings",selectmode="browse")
        for key,title,width in (("check","✓",40),("date","Date",115),("course","Course",350),("holes","Holes",65),("score","Score",75),("greens","Greens",85),("putts","Putts",70)):
            self.tree.heading(key,text=title)
            self.tree.column(key,width=width,minwidth=min(width,60),anchor="w" if key=="course" else "center")
        bar=ttk.Scrollbar(table,orient="vertical",command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        bar.pack(side="right",fill="y")
        self.tree.pack(side="left",fill="both",expand=True)
        self.tree.bind("<Button-1>",self.click)
        self.tree.bind("<Double-1>",self.double_click)
        self.tree.bind("<space>",self.space)
        footer=tk.Frame(self,bg=WHITE,padx=22,pady=18)
        footer.pack(side="bottom",fill="x",before=table)
        tk.Label(footer,textvariable=self.summary,font=(FONT,10),fg=MUTED,bg=WHITE).pack(anchor="w",pady=(0,12))
        ttk.Button(footer,text="Select visible",command=self.select_visible).pack(side="left")
        ttk.Button(footer,text="Clear selection",command=self.clear).pack(side="left",padx=10)
        self.apply_button=ttk.Button(footer,text="Use selected games",command=self.apply)
        self.apply_button.pack(side="right")
        ttk.Button(footer,text="Cancel",command=self.cancel).pack(side="right",padx=10)
        self.search.trace_add("write",lambda *_:self.refresh())
        self.protocol("WM_DELETE_WINDOW",self.cancel)
        self.bind("<Escape>",lambda _:self.cancel())
        self.refresh()
        self.deiconify()
        self.grab_set()

    def refresh(self):
        eligible=eligible_rounds(self.model,self.full_only.get())
        query=self.search.get().strip().casefold()
        self.visible=[r for r in eligible if not query or query in (r["date"]+" "+str(r["course"])).casefold()]
        self.tree.delete(*self.tree.get_children())
        def value(x):
            return "—" if x is None else f"{x:.0f}"
        for r in self.visible:
            self.tree.insert("","end",iid=r["id"],values=("☑" if r["id"] in self.checked else "☐",r["date"],r["course"],r["holes_completed"],value(r["score"]),f"{value(r['greens_hit'])}/{value(r['greens_recorded'])}",value(r["putts"])))
        allowed={r["id"] for r in eligible}
        self.summary.set(f"{len(self.checked & allowed)} chosen · {len(self.visible)} shown · {len(eligible)} available. Search does not clear hidden choices.")

    def toggle(self,key):
        if not key:
            return
        if key in self.checked:
            self.checked.remove(key)
        else:
            self.checked.add(key)
        self.refresh()
        if self.tree.exists(key):
            self.tree.selection_set(key)
            self.tree.focus(key)

    def click(self,event):
        if self.tree.identify_column(event.x)=="#1":
            self.toggle(self.tree.identify_row(event.y))
            return "break"

    def double_click(self,event):
        if self.tree.identify_column(event.x)!="#1":
            self.toggle(self.tree.identify_row(event.y))
        return "break"

    def space(self,_=None):
        self.toggle(self.tree.focus())
        return "break"

    def select_visible(self):
        self.checked.update(r["id"] for r in self.visible)
        self.refresh()

    def clear(self):
        self.checked.clear()
        self.refresh()

    def apply(self):
        chosen=tuple(r["id"] for r in eligible_rounds(self.model,self.full_only.get()) if r["id"] in self.checked)
        if not chosen:
            messagebox.showinfo("Choose at least one game","Check the games you want to analyze, or cancel to keep the current selection.",parent=self)
            return
        self.result=RoundSelection(mode="manual",ids=chosen,full_only=self.full_only.get())
        self.destroy()

    def cancel(self):
        self.result=None
        self.destroy()
