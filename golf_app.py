"""Golf Desk: a local Windows dashboard with private, remembered Garmin sign-in."""

from __future__ import annotations

import csv
import ctypes
import json
import logging
import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

# Isolated pythonw launch ignores the working directory and user-site packages;
# explicitly import only the application's own neighboring modules.
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from export_golf import MAX_DETAILED_ROUNDS,MAX_IMPORT_ROUNDS,round_count,save_export
from golf_data import GolfSnapshot, average, load_snapshot, percent, read_export
from golf_charts import chart, draw_approach_bars, draw_hole_heatmap, draw_miss_pattern, draw_priorities, draw_putting_bars, draw_putting_drill, draw_tee_bars, draw_wedge_bars,draw_history_trend,draw_club_confidence
from golf_coaching import improvement_snapshot
from golf_game import full_game_snapshot
from golf_planner_ui import ExpectedValueView,StrategyView
from golf_icon import tk_icon_data
from golf_service import SignInRequired, SyncCancelled, SyncError, sync_golf
from golf_store import SessionStore, SessionStoreError, app_data_dir
from golf_history import MAX_HISTORY_COUNT,RoundSelection,load_selection,save_selection,period_statistics,trend_series,default_trend_keys
from golf_history_ui import RoundPicker
from golf_confidence import ROLES,MIN_CLASSIFIED_SHOTS,club_confidence,club_history

TITLE = "Golf Desk · Garmin golf"
BG, WHITE, INK, MUTED = "#F3F6F3", "#FFFFFF", "#15382E", "#65766D"
GREEN, MINT, NAVY, BORDER = "#137B56", "#E4F2E9", "#122F26", "#DFE7DF"
AMBER, AMBER_BG, RED = "#976123", "#FFF4DF", "#A24539"
FONT = "Segoe UI"


def fmt(value, digits=1, suffix=""):
    return "—" if value is None else f"{value:.{digits}f}{suffix}"


def fmt_delta(value):
    return "—" if value is None else "E" if value==0 else f"{value:+.0f}"


def pretty_date(value):
    try:
        return date.fromisoformat(value[:10]).strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return "Date unavailable"


def label(parent, text="", size=10, bold=False, color=INK, bg=WHITE, **kwargs):
    return tk.Label(parent, text=text, font=(FONT, size, "bold" if bold else "normal"), fg=color, bg=bg, anchor="w", **kwargs)


def button(parent, text, command, primary=False, **kwargs):
    return tk.Button(parent, text=text, command=command, font=(FONT, 10, "bold"),
                     bg=GREEN if primary else WHITE, fg=WHITE if primary else INK,
                     activebackground="#0D6646" if primary else MINT,
                     activeforeground=WHITE if primary else INK, relief="flat", bd=0,
                     padx=17, pady=10, cursor="hand2", highlightthickness=1,
                     highlightbackground=GREEN if primary else BORDER, highlightcolor=GREEN, **kwargs)


def card(parent, **kwargs):
    return tk.Frame(parent, bg=WHITE, highlightbackground=BORDER, highlightthickness=1, **kwargs)


class ScrollPage(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=BG)
        self.window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))


class SyncDialog(tk.Toplevel):
    def __init__(self, parent, has_saved=False, rounds=20, shots=False, email_hint="", force_fresh=False):
        super().__init__(parent)
        self.withdraw()
        self.title("Update from Garmin")
        self.configure(bg=WHITE)
        self.resizable(False, False)
        self.transient(parent)
        self.result = None
        self.saved = tk.BooleanVar(value=has_saved and not force_fresh)
        self.remember = tk.BooleanVar(value=True)
        self.shots = tk.BooleanVar(value=shots)
        self.scope = tk.StringVar(value=str(rounds))
        self.email = tk.StringVar(value=email_hint)
        self.password = tk.StringVar()
        body = tk.Frame(self, bg=WHITE, padx=30, pady=26)
        body.pack(fill="both", expand=True)
        label(body, "Connect your golf", 22, True).pack(anchor="w")
        label(body, "Private sign-in · read-only golf import", color=MUTED).pack(anchor="w", pady=(6, 20))
        if has_saved:
            ttk.Checkbutton(body, text="Use remembered sign-in on this PC", variable=self.saved, command=self.toggle_credentials).pack(anchor="w", pady=(0, 12))
        self.fields = tk.Frame(body, bg=WHITE)
        self.fields.pack(fill="x")
        label(self.fields, "Garmin email", 10, True).pack(anchor="w", pady=(0, 6))
        self.email_entry = ttk.Entry(self.fields, textvariable=self.email, width=47, font=(FONT, 11))
        self.email_entry.pack(fill="x", ipady=6)
        label(self.fields, "Password", 10, True).pack(anchor="w", pady=(14, 6))
        self.password_entry = ttk.Entry(self.fields, textvariable=self.password, show="●", font=(FONT, 11))
        self.password_entry.pack(fill="x", ipady=6)
        label(self.fields, "Your password is sent to Garmin, never saved by Golf Desk.", 9, color=MUTED, wraplength=420).pack(anchor="w", pady=(6, 14))
        controls = tk.Frame(body, bg=WHITE)
        controls.pack(fill="x", pady=(8, 0))
        label(controls, "Latest scorecards to import", 10, True).pack(side="left")
        ttk.Combobox(controls, textvariable=self.scope, values=("3", "10", "20", "30", "50", "100", "200", "500", "1000"), state="normal", width=8).pack(side="right", ipady=4)
        ttk.Checkbutton(body, text="Include detailed shots and locations", variable=self.shots).pack(anchor="w", pady=(18, 4))
        label(body, f"Up to {MAX_IMPORT_ROUNDS} scorecards, or {MAX_DETAILED_ROUNDS} rounds with shot GPS positions. Larger imports take longer and can be canceled.", 9, color=MUTED, wraplength=420,justify="left").pack(anchor="w")
        ttk.Checkbutton(body, text="Remember this PC", variable=self.remember).pack(anchor="w", pady=(18, 4))
        label(body, "Windows-encrypted session tokens, not your password. Garmin may still require sign-in again. Unchecking removes this app’s saved sign-in after a successful login.", 9, color=MUTED, wraplength=420, justify="left").pack(anchor="w")
        notice = tk.Frame(body, bg=MINT, padx=12, pady=10)
        notice.pack(fill="x", pady=(18, 18))
        label(notice, "Unofficial integration. Your Garmin records will not be edited.", 9, color=GREEN, bg=MINT, wraplength=395, justify="left").pack(anchor="w")
        actions = tk.Frame(body, bg=WHITE)
        actions.pack(fill="x")
        button(actions, "Cancel", self.cancel).pack(side="left")
        button(actions, "Connect & import", self.submit, primary=True).pack(side="right")
        self.toggle_credentials()
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda _: self.cancel())
        self.bind("<Return>", lambda _: self.submit())
        self.update_idletasks()
        self.geometry(f"+{parent.winfo_rootx() + (parent.winfo_width()-self.winfo_reqwidth())//2}+{max(30, parent.winfo_rooty()+45)}")
        self.deiconify()
        self.grab_set()
        (self.email_entry if not self.saved.get() else self).focus_set()

    def toggle_credentials(self):
        state = "disabled" if self.saved.get() else "normal"
        self.email_entry.configure(state=state)
        self.password_entry.configure(state=state)

    def cancel(self):
        self.password.set("")
        self.result = None
        self.destroy()

    def submit(self):
        try:
            count=round_count(self.scope.get())
            if self.shots.get() and count>MAX_DETAILED_ROUNDS:
                raise ValueError(f"Choose at most {MAX_DETAILED_ROUNDS} detailed rounds, or untick detailed shots for a larger scorecard history.")
        except Exception as exc:
            messagebox.showinfo("Import size",str(exc),parent=self)
            return
        if not self.saved.get() and (not self.email.get().strip() or not self.password.get()):
            messagebox.showinfo("Sign-in needed", "Enter your Garmin email and password in this window.", parent=self)
            return
        credentials = None if self.saved.get() else {"email": self.email.get().strip(), "password": self.password.get()}
        self.result = {"rounds": count, "include_shots": self.shots.get(), "remember": self.remember.get(), "credentials": credentials}
        self.password.set("")
        self.destroy()


class MfaDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Garmin verification")
        self.transient(parent)
        self.configure(bg=WHITE)
        self.resizable(False, False)
        self.result = None
        self.secret = tk.StringVar()
        body = tk.Frame(self, bg=WHITE, padx=28, pady=24)
        body.pack()
        label(body, "One more step", 20, True).pack(anchor="w")
        label(body, "Enter the verification code Garmin sent you.\nDo not put the code in a chat.", 10, color=MUTED, justify="left").pack(anchor="w", pady=14)
        entry = ttk.Entry(body, textvariable=self.secret, show="●", width=32, font=(FONT, 14))
        entry.pack(fill="x", ipady=8)
        actions = tk.Frame(body, bg=WHITE)
        actions.pack(fill="x", pady=(20, 0))
        button(actions, "Cancel", self.cancel).pack(side="left")
        button(actions, "Verify", self.submit, primary=True).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Return>", lambda _: self.submit())
        self.bind("<Escape>", lambda _: self.cancel())
        self.geometry(f"+{parent.winfo_rootx()+400}+{parent.winfo_rooty()+180}")
        self.grab_set()
        entry.focus_set()

    def cancel(self):
        self.secret.set("")
        self.result = None
        self.destroy()

    def submit(self):
        if not self.secret.get().strip():
            return
        self.result = self.secret.get().strip()
        self.secret.set("")
        self.destroy()


class GolfApp:
    def __init__(self, export_dir: Path | None = None, data_dir: Path | None = None, visible=True, initial_page="overview"):
        logging.disable(logging.CRITICAL)
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(TITLE)
        self.root.configure(bg=BG)
        self.root.minsize(1200, 760)
        width = min(1480, self.root.winfo_screenwidth()-80)
        height = min(980, self.root.winfo_screenheight()-100)
        self.root.geometry(f"{width}x{height}+{max(20,(self.root.winfo_screenwidth()-width)//2)}+{max(20,(self.root.winfo_screenheight()-height)//2)}")
        self.icon = tk.PhotoImage(data=tk_icon_data())
        self.root.iconphoto(True, self.icon)
        self.data_dir = data_dir if data_dir is not None else app_data_dir()
        self.export_dir = export_dir if export_dir is not None else self.data_dir / "exports"
        self.store = SessionStore(self.data_dir / "garmin-session.dpapi")
        self.local_labels = self.read_labels()
        self.model = load_snapshot(self.export_dir, self.local_labels)
        self.history=load_selection(self.data_dir/"round-selection.json",self.model.account_identities)
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.closed = False
        self.page = "overview"
        self.approach_mode = "Selected games · shot data"
        self.approach_round = None
        self.selected_round = None
        self.pattern_club = None
        self.game_tab = "tee"
        self.improve_tab = "dashboard"
        self.strategy_state = {}
        self.ev_state = {}
        self.overview_tab="summary"
        self.rounds_tab="trends"
        self.rolling_window=5
        self.confidence_role="Approaches"
        self.confidence_sort="Evidence & sample"
        self.confidence_show_empty=False
        self.confidence_trend_club=None
        self.last_options = {"rounds": 20, "include_shots": False, "remember": True}
        self.mfa_pending = None
        self.mfa_dialog = None
        self.banner = tk.StringVar()
        self.status = tk.StringVar(value="Saved golf data is ready. No account connection is needed to browse.")
        self.session_status = tk.StringVar()
        self.configure_styles()
        self.build_shell()
        self.show_page(initial_page)
        self.refresh_session_status()
        self.root.bind_all("<MouseWheel>", self.on_wheel)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.report_callback_exception = self.callback_error
        self.poll_id = self.root.after(100, self.drain_events)
        if visible:
            self.root.deiconify()

    def configure_styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Treeview", background=WHITE, fieldbackground=WHITE, foreground=INK, font=(FONT, 10), rowheight=34, borderwidth=0)
        style.configure("Treeview.Heading", background="#ECF1EC", foreground=MUTED, font=(FONT, 9, "bold"), relief="flat", padding=(8, 10))
        style.map("Treeview", background=[("selected", "#D5EDDF")], foreground=[("selected", INK)])
        style.configure("TCheckbutton", background=WHITE, foreground=INK, font=(FONT, 10), padding=2)
        style.configure("History.TCheckbutton",background=BG,foreground=INK,font=(FONT,9),padding=2)
        style.configure("TCombobox", padding=5, font=(FONT, 10))
        style.configure("TEntry", padding=6)
        style.configure("Horizontal.TProgressbar", background=GREEN, troughcolor=MINT, borderwidth=0)

    def read_labels(self):
        path = self.data_dir / "club-labels.json"
        try:
            if path.stat().st_size > 100_000:
                return {}
            values = json.loads(path.read_text(encoding="utf-8")).get("labels", {})
            return {str(k): v[:60] for k, v in values.items() if isinstance(v, str) and v.strip()} if isinstance(values, dict) else {}
        except (OSError, ValueError, AttributeError):
            return {}

    def build_shell(self):
        self.sidebar = tk.Frame(self.root, bg=NAVY, width=248)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        brand = tk.Frame(self.sidebar, bg=NAVY, padx=22, pady=28)
        brand.pack(fill="x")
        tk.Label(brand, image=self.icon, bg=NAVY).pack(anchor="w")
        label(brand, "GOLF DESK", 16, True, "#F2F8F0", NAVY).pack(anchor="w", pady=(12, 2))
        label(brand, "Know your next shot.", 9, color="#A2BCAF", bg=NAVY).pack(anchor="w")
        self.nav = {}
        for key, text in (("overview", "Overview"), ("improve", "Improve my game"), ("rounds", "Rounds & trends"), ("clubs", "Approach clubs"), ("game", "Tee & short game"), ("privacy", "Data & privacy")):
            item = tk.Button(self.sidebar, text=text, command=lambda k=key: self.show_page(k), font=(FONT, 11),
                             bg=NAVY, fg="#BCD0C3", activebackground="#244B39", activeforeground=WHITE,
                             anchor="w", relief="flat", bd=0, padx=22, pady=15, cursor="hand2", highlightthickness=0)
            item.pack(fill="x", padx=12, pady=3)
            self.nav[key] = item
        footer = tk.Frame(self.sidebar, bg=NAVY, padx=24, pady=24)
        footer.pack(side="bottom", fill="x")
        label(footer, "YOUR PRIVATE WORKSPACE", 8, True, "#8EB59D", NAVY, wraplength=198).pack(anchor="w")
        tk.Label(footer, textvariable=self.session_status, bg=NAVY, fg="#BCD0C3", font=(FONT, 9), wraplength=198, justify="left", anchor="w").pack(fill="x", pady=(10, 16))
        label(footer, "Unofficial Garmin integration. Your Garmin records are never edited.", 8, color="#91AA9B", bg=NAVY, justify="left", wraplength=198).pack(anchor="w")
        main = tk.Frame(self.root, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        heading = tk.Frame(main, bg=BG, padx=28, pady=24)
        self.heading_frame=heading
        heading.pack(fill="x")
        actions = tk.Frame(heading, bg=BG)
        actions.pack(side="right", padx=(18, 0))
        button(actions, "Import JSON", self.import_export).pack(side="left", padx=(0, 10))
        self.sync_button = button(actions, "Update from Garmin", self.open_sync, primary=True)
        self.sync_button.pack(side="left")
        titles = tk.Frame(heading, bg=BG)
        titles.pack(side="left", fill="x", expand=True)
        self.title_label = label(titles, "", 23, True, bg=BG)
        self.title_label.pack(anchor="w")
        self.subtitle = label(titles, "", 10, color=MUTED, bg=BG)
        self.subtitle.pack(anchor="w", pady=(6, 0))
        heading.bind("<Configure>", lambda e: self.wrap_header(e.width, actions.winfo_reqwidth()))
        self.history_frame=tk.Frame(main,bg=BG,padx=28,pady=4)
        self.history_frame.pack(fill="x",pady=(0,12))
        history_controls=tk.Frame(self.history_frame,bg=BG)
        history_controls.pack(fill="x")
        label(history_controls,"GAMES",9,True,MUTED,BG).pack(side="left",padx=(0,12))
        self.history_choice=tk.StringVar()
        self.history_combo=ttk.Combobox(history_controls,textvariable=self.history_choice,state="readonly",width=23)
        self.history_combo.pack(side="left",ipady=3)
        self.history_combo.bind("<<ComboboxSelected>>",self.change_history_choice)
        self.choose_games_button=button(history_controls,"Choose games…",self.choose_games)
        self.choose_games_button.pack(side="left",padx=10)
        self.full_only_var=tk.BooleanVar(value=self.history.full_only)
        self.full_only_check=ttk.Checkbutton(history_controls,text="18-hole games only",style="History.TCheckbutton",variable=self.full_only_var,command=self.change_hole_filter)
        self.full_only_check.pack(side="left",padx=6)
        self.import_history_button=button(history_controls,"Import more games",lambda:self.open_sync(rounds=self.recommended_import_count()))
        self.history_info=tk.StringVar()
        tk.Label(self.history_frame,textvariable=self.history_info,bg=BG,fg=MUTED,font=(FONT,9),anchor="w",justify="left",wraplength=1110).pack(fill="x",pady=(7,0))
        self.progress_frame = tk.Frame(main, bg=BG, padx=28)
        self.progress_label = label(self.progress_frame, "", 10, color=GREEN, bg=BG)
        self.progress_label.pack(anchor="w")
        self.progress_bar = ttk.Progressbar(self.progress_frame, mode="indeterminate")
        self.progress_bar.pack(fill="x", pady=8)
        button(self.progress_frame, "Cancel update", self.cancel_sync).pack(anchor="e", pady=(0, 8))
        self.notice = tk.Frame(main, bg=MINT, padx=14, pady=10)
        tk.Label(self.notice, textvariable=self.banner, bg=MINT, fg=INK, font=(FONT, 10), wraplength=1120, anchor="w", justify="left").pack(fill="x")
        self.scroll = ScrollPage(main)
        self.scroll.pack(fill="both", expand=True, padx=(28, 16))
        bottom = tk.Frame(main, bg=BG, padx=28, pady=12)
        bottom.pack(fill="x")
        tk.Label(bottom, textvariable=self.status, bg=BG, fg=MUTED, font=(FONT, 9), anchor="w").pack(fill="x")

    def refresh_session_status(self):
        self.session_status.set("Sign-in remembered with Windows encryption." if self.store.exists else "Browsing local exports. Sign in once to enable remembered updates.")

    def selected_games(self):
        return self.history.resolve(self.model)

    def selected_description(self):
        info=self.history.summary(self.model)
        if not info["selected"]:
            return "No imported games match this selection."
        return f"{info['selected']} selected games · {pretty_date(info['oldest'])} to {pretty_date(info['newest'])}"

    def refresh_history_controls(self):
        values=[f"Last {n} games" for n in (3,5,10,20,30,50,100)]+["All imported games","Custom count…","Choose games…"]
        current=self.history.label()
        if current not in values:
            values.insert(0,current)
        self.history_combo.configure(values=values,state="disabled" if self.busy else "readonly")
        self.history_choice.set(current)
        self.full_only_var.set(self.history.full_only)
        self.choose_games_button.configure(state="disabled" if self.busy else "normal")
        self.full_only_check.state(["disabled"] if self.busy else ["!disabled"])
        info=self.history.summary(self.model)
        prefix=f"Showing {info['selected']} of {info['requested']} requested games ({info['available']} matching imported)." if info["shortfall"] else f"Showing {info['selected']} of {info['requested']} chosen games; some are filtered or unavailable." if self.history.mode=="manual" and info["selected"]<info["requested"] else self.selected_description()+"."
        self.history_info.set(prefix+" Account handicap, Garmin aggregate club stats and manual EV inputs are not period-filtered.")
        if info["shortfall"] and not self.busy:
            self.import_history_button.pack(side="right")
        else:
            self.import_history_button.pack_forget()

    def apply_history(self,selection):
        self.history=selection
        self.approach_round=None
        self.selected_round=None
        try:
            save_selection(self.data_dir/"round-selection.json",selection,self.model.account_identities)
        except OSError:
            self.status.set("The game selection is active, but could not be remembered on this PC.")
        self.show_page(self.page)

    def change_history_choice(self,_=None):
        choice=self.history_choice.get()
        if choice in ("Choose games…","Chosen games"):
            self.choose_games()
        elif choice=="Custom count…":
            initial=self.history.count if self.history.mode=="latest" else max(1,len(self.selected_games()))
            count=simpledialog.askinteger("Custom history","How many latest completed games should be analyzed?",initialvalue=initial,minvalue=1,maxvalue=MAX_HISTORY_COUNT,parent=self.root)
            if count is not None:
                self.apply_history(RoundSelection("latest",count,full_only=self.history.full_only))
        elif choice=="All imported games":
            self.apply_history(RoundSelection("all",full_only=self.history.full_only))
        elif choice.startswith("Last "):
            self.apply_history(RoundSelection("latest",int(choice.split()[1]),full_only=self.history.full_only))
        self.refresh_history_controls()

    def change_hole_filter(self):
        self.apply_history(RoundSelection(self.history.mode,self.history.count,self.history.ids,self.full_only_var.get()))

    def choose_games(self):
        if self.busy:
            return
        dialog=RoundPicker(self.root,self.model,self.history)
        self.root.wait_window(dialog)
        if dialog.result is not None:
            self.apply_history(dialog.result)
        else:
            self.refresh_history_controls()

    def recommended_import_count(self,shots=False):
        selected={r["id"] for r in self.selected_games()}
        depth=max((i+1 for i,r in enumerate(self.model.rounds) if r["id"] in selected),default=0)
        requested=self.history.count if self.history.mode=="latest" else depth or 20
        return min(MAX_DETAILED_ROUNDS if shots else MAX_IMPORT_ROUNDS,max(1,requested,depth))

    def empty_history(self,parent):
        if not self.model.rounds:
            self.empty(parent,"Your golf starts here.","Import saved scorecards or connect to Garmin. No sample performance is substituted.")
        else:
            frame=self.section(parent,"No games match this selection.","Choose different games or turn off the 18-hole-only filter to include imported 9-hole games.")
            button(frame,"Choose games…",self.choose_games).pack(anchor="w",padx=18,pady=(0,18))

    def wrap_header(self, width, actions_width):
        available = max(260, width-actions_width-90)
        self.title_label.configure(wraplength=available, justify="left")
        self.subtitle.configure(wraplength=available, justify="left")

    def show_notice(self, text):
        self.banner.set(text)
        if text:
            self.notice.pack(fill="x", padx=28, pady=(0, 14), before=self.scroll)
        else:
            self.notice.pack_forget()

    def show_page(self, key):
        self.page = key
        titles = {"overview": ("Your golf, at a glance.", "A clear picture from your saved scorecards."),
                  "improve": ("What to improve next.", "Visual priorities from your real rounds—not a swing diagnosis."),
                  "rounds": ("Your games, over time.", "Selected-game trends, rolling averages and individual scorecards."),
                  "clubs": ("Which approaches cost you?", "Keep recent shot outcomes separate from aggregate club statistics."),
                  "game": ("Your complete scoring game.", "Driver and tee shots, putting, and wedges—with their different roles kept separate."),
                  "privacy": ("Your data. Your control.", "Private sign-in, local exports, and clear limits.")}
        self.title_label.configure(text=titles[key][0])
        self.subtitle.configure(text=titles[key][1])
        self.refresh_history_controls()
        if key=="privacy":
            self.history_frame.pack_forget()
        else:
            self.history_frame.pack(fill="x",pady=(0,12),after=self.heading_frame)
        for name, item in self.nav.items():
            item.configure(bg="#244D3A" if name == key else NAVY, fg=WHITE if name == key else "#BCD0C3")
        for widget in self.scroll.body.winfo_children():
            widget.destroy()
        {"overview": self.render_overview, "improve": self.render_improve, "rounds": self.render_rounds, "clubs": self.render_clubs, "game": self.render_game, "privacy": self.render_privacy}[key](self.scroll.body)
        self.scroll.canvas.yview_moveto(0)

    def metrics_row(self, parent, items):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(0, 18))
        for index, (title, value, subtitle) in enumerate(items):
            row.columnconfigure(index, weight=1, uniform="metric")
            tile = card(row)
            tile.grid(row=0, column=index, sticky="nsew", padx=(0, 12 if index < len(items)-1 else 0))
            label(tile, title.upper(), 9, True, MUTED).pack(anchor="w", padx=18, pady=(16, 4))
            label(tile, value, 29, True).pack(anchor="w", padx=18)
            label(tile, subtitle, 9, color=MUTED, wraplength=225, justify="left").pack(anchor="w", padx=18, pady=(4, 16))

    def section(self, parent, title, subtitle=""):
        frame = card(parent)
        frame.pack(fill="x", pady=(0, 18))
        header = tk.Frame(frame, bg=WHITE, padx=18, pady=16)
        header.pack(fill="x")
        label(header, title, 14, True).pack(anchor="w")
        if subtitle:
            label(header, subtitle, 9, color=MUTED, wraplength=1080, justify="left").pack(anchor="w", pady=(5, 0))
        return frame

    def tree(self, parent, columns, height=6):
        wrap = tk.Frame(parent, bg=WHITE)
        wrap.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        tree = ttk.Treeview(wrap, columns=[x[0] for x in columns], show="headings", height=height)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        for name, title, width in columns:
            tree.heading(name, text=title, command=lambda c=name: self.sort_tree(tree, c))
            tree.column(name, width=width, minwidth=min(width, 65), anchor="w" if name in ("club", "course", "file", "name", "source") else "center", stretch=True)
        tree.tag_configure("highlight", background=MINT)
        tree.tag_configure("caution", background=AMBER_BG)
        tree.tag_configure("muted", foreground=MUTED)
        return tree

    def sort_tree(self, tree, column):
        def value(iid):
            text = tree.set(iid, column)
            try:
                return (0, float(str(text).replace("%", "").split("/")[0]))
            except ValueError:
                return (1, str(text).casefold())
        reverse = getattr(tree, "_sort", None) == (column, False)
        for index, iid in enumerate(sorted(tree.get_children(), key=value, reverse=reverse)):
            tree.move(iid, "", index)
        tree._sort = (column, reverse)

    def render_overview(self, body):
        tabs=tk.Frame(body,bg=BG)
        tabs.pack(fill="x",pady=(0,18))
        def choose(tab):
            self.overview_tab=tab
            self.show_page("overview")
        for key,title in (("summary","Selected-game overview"),("confidence","Club confidence")):
            button(tabs,title,lambda k=key:choose(k),primary=self.overview_tab==key).pack(side="left",padx=(0,10))
        if self.overview_tab=="confidence":
            self.render_confidence(body)
            return
        selected=self.selected_games()
        metrics=period_statistics(selected)
        coaching=self.model.metrics(selected)
        kind=metrics["scoring_holes"]
        self.metrics_row(body, [("Garmin handicap", fmt(self.model.user_stats.get("handicap")), "Garmin’s account summary"),
                                (f"{kind}-hole average score", fmt(metrics["average_score"]), f"{metrics['scoring_games']} selected {kind}-hole games"),
                                ("Greens in regulation", fmt(metrics["gir"], suffix="%"), "Weighted by recorded greens"),
                                (f"Putts / {kind}-hole game", fmt(metrics["putts"]), "Selected scorecards; lengths not mixed")])
        chart_row = tk.Frame(body, bg=BG)
        chart_row.pack(fill="x", pady=(0, 18))
        chart_row.columnconfigure(0, weight=2)
        chart_row.columnconfigure(1, weight=1)
        chart_card = card(chart_row)
        chart_card.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        label(chart_card, "Score trend", 14, True).pack(anchor="w", padx=18, pady=(18, 4))
        label(chart_card, f"Selected {kind}-hole scores · courses and tees differ", 9, color=MUTED).pack(anchor="w", padx=18)
        canvas = tk.Canvas(chart_card, bg=WHITE, height=300, highlightthickness=0)
        canvas.pack(fill="x", padx=10, pady=12)
        canvas.bind("<Configure>", lambda _: self.draw_chart(canvas))
        focus = card(chart_row)
        focus.grid(row=0, column=1, sticky="nsew")
        label(focus, "Your next scoring gains", 14, True).pack(anchor="w", padx=18, pady=(18, 12))
        for headline, text in (("Control the long putt", f"{fmt(coaching['three_putts'])} three-putt-or-worse holes per selected 18-hole game. Verify tracking, then work on pace."),
                               ("Keep the big number off", f"{fmt(coaching['big_holes'])} double-bogey-or-worse holes per selected 18-hole game. Favor the safe recovery."),
                               ("Check your club confidence", "Compare target hits, misses and sample sizes within the same shot role—not irons versus putts.")):
            label(focus, headline, 10, True).pack(anchor="w", padx=18, pady=(4, 3))
            label(focus, text, 9, color=MUTED, wraplength=310, justify="left").pack(anchor="w", padx=18, pady=(0, 9))
        button(focus, "Review approach clubs →", lambda: self.show_page("clubs")).pack(anchor="w", padx=18, pady=(4, 16))
        label(body, f"RECENT GAMES IN THIS SELECTION · showing {min(3,len(selected))} of {len(selected)}", 10, True, MUTED, BG).pack(anchor="w", pady=(3, 12))
        latest = tk.Frame(body, bg=BG)
        latest.pack(fill="x", pady=(0, 18))
        for i, r in enumerate(selected[:3]):
            latest.columnconfigure(i, weight=1, uniform="round")
            tile = card(latest)
            tile.grid(row=0, column=i, sticky="nsew", padx=(0, 12 if i < 2 else 0))
            label(tile, pretty_date(r["date"]), 9, color=MUTED).pack(anchor="w", padx=18, pady=(16, 8))
            label(tile, r["course"], 12, True, wraplength=300, justify="left", height=2).pack(anchor="w", padx=18)
            line = tk.Frame(tile, bg=WHITE)
            line.pack(fill="x", padx=18, pady=10)
            label(line, fmt(r["score"], 0), 30, True).pack(side="left")
            label(line, f"  {fmt_delta(r['to_par'])} to par · {r['holes_completed']} holes", 9, color=MUTED).pack(side="left")
            label(tile, f"Greens {fmt(r['greens_hit'], 0)}/{fmt(r['greens_recorded'], 0)}    Putts {fmt(r['putts'], 0)}    Penalties {fmt(r['penalties'], 0)}", 9, color=MUTED).pack(anchor="w", padx=18)
            button(tile, "Review round", lambda rid=r["id"]: self.go_round(rid)).pack(anchor="w", padx=18, pady=16)
        if not selected:
            self.empty_history(body)
        sample = f"{len(selected)} selected games: {metrics['full_rounds']} × 18 holes, {metrics['nine_rounds']} × 9 holes. Score and per-game putting averages use {kind}-hole games only; accuracy percentages use selected recorded holes."
        label(body, sample, 9, color=MUTED, bg=BG, wraplength=1100, justify="left").pack(anchor="w", pady=(0, 16))
        button(body,"Explore all selected-game trends →",lambda:self.open_rounds("trends")).pack(anchor="w",pady=(0,18))

    def draw_chart(self, canvas):
        selected=self.selected_games()
        kind=period_statistics(selected)["scoring_holes"]
        draw_history_trend(canvas,trend_series(selected,"score"+str(kind)),self.rolling_window,self.go_round)

    def render_confidence(self,body):
        selected=self.selected_games()
        controls=tk.Frame(body,bg=BG)
        controls.pack(fill="x",pady=(0,16))
        role=ttk.Combobox(controls,values=ROLES,state="readonly",width=24)
        role.set(self.confidence_role)
        role.pack(side="left",ipady=3)
        sorting=ttk.Combobox(controls,values=("Evidence & sample","Most misses","Hit rate","Club name"),state="readonly",width=23)
        sorting.set(self.confidence_sort)
        sorting.pack(side="left",padx=10,ipady=3)
        show_empty=tk.BooleanVar(value=self.confidence_show_empty)
        def change(_=None):
            self.confidence_role=role.get()
            self.confidence_sort=sorting.get()
            self.confidence_show_empty=show_empty.get()
            self.show_page("overview")
        role.bind("<<ComboboxSelected>>",change)
        sorting.bind("<<ComboboxSelected>>",change)
        ttk.Checkbutton(controls,text="Show clubs with no records",style="History.TCheckbutton",variable=show_empty,command=change).pack(side="left",padx=5)
        report=club_confidence(self.model,selected,self.confidence_role,self.confidence_show_empty)
        if self.confidence_sort=="Most misses":
            report["rows"].sort(key=lambda r:(r["unassigned"],-r["misses"],-r["classified"]))
        elif self.confidence_sort=="Hit rate":
            report["rows"].sort(key=lambda r:(r["unassigned"],r["rate"] is None,-(r["rate"] or 0),-r["classified"]))
        elif self.confidence_sort=="Club name":
            report["rows"].sort(key=lambda r:(r["unassigned"],r["label"]))
        label(body,f"Target hits: {report['hits']}     Misses: {report['misses']}     Unknown: {report['unknown']}     Clubs with 10+ records: {sum(r['enough'] for r in report['rows'])}",11,True,bg=BG,wraplength=1090,justify="left").pack(anchor="w",pady=(0,16))
        frame=self.section(body,"Which clubs are working for you?",report["definition"]+" * marks a small sample (fewer than 10 classified records).")
        chart(frame,lambda c:draw_club_confidence(c,report),height=max(160,78+43*len(report["rows"])))
        strongest=report["strongest"]
        if strongest:
            explanation=f"Most consistency evidence among recorded outcomes: {strongest['label']} — {strongest['hits']}/{strongest['classified']} target hits ({strongest['rate']:.1f}%). This is not a recommendation to use that club for a different distance or lie."
        else:
            explanation=f"No named club has {MIN_CLASSIFIED_SHOTS} classified records in this role and period. Treat the counts as review signals, not a reliable confidence ranking."
        label(frame,explanation,10,color=GREEN if strongest else AMBER,wraplength=1080,justify="left").pack(anchor="w",padx=18,pady=(0,14))
        worst=report["most_misses"]
        if worst:
            label(frame,f"Most recorded misses: {worst['label']} — {worst['misses']} misses from {worst['classified']} classified outcomes. Usage and shot difficulty affect this count.",10,color=MUTED,wraplength=1080,justify="left").pack(anchor="w",padx=18,pady=(0,14))
        coverage=f"Putting tracking: {report['putting_holes']}/{report['expected_holes']} selected holes." if self.confidence_role=="Putting" else f"Detailed-shot coverage: {report['shot_holes']}/{report['expected_holes']} selected holes."
        label(frame,coverage+f" {report['unassigned']} records have no club assignment. Missing tracking can bias observed rates.",9,color=MUTED,wraplength=1080,justify="left").pack(anchor="w",padx=18,pady=(0,18))
        table=self.section(body,"Hits, misses and sample sizes","Rate ranges are approximate 95% Wilson intervals for the recorded role, assuming broadly comparable shots. They are not psychological confidence, current-shot predictions, or evidence of positive EV.")
        tree=self.tree(table,[("club","Club",180),("hits","Target hits",85),("miss","Misses",70),("unknown","Unknown",75),("n","Classified",85),("rate","Hit rate",85),("range","Rate range",125),("source","Evidence",170)],height=min(12,max(3,len(report["rows"]))))
        for r in report["rows"]:
            interval="—" if r["low"] is None else f"{r['low']:.0f}–{r['high']:.0f}%"
            evidence="No records" if not r["records"] else "Unassigned" if r["unassigned"] else "Small sample (<10)" if not r["enough"] else "10+ classified records"
            tree.insert("","end",iid=r["id"],values=(r["label"],r["hits"],r["misses"],r["unknown"],r["classified"],fmt(r["rate"],suffix="%"),interval,evidence),tags=("muted" if r["unassigned"] or not r["records"] else "highlight" if strongest and r["id"]==strongest["id"] else "",))
        button(table,"Export club confidence comparison",lambda:self.export_table(tree,"selected-club-confidence.csv")).pack(anchor="w",padx=18,pady=(0,18))
        candidates=[r for r in report["rows"] if not r["unassigned"] and r["records"]]
        if candidates:
            controls=self.section(body,"How is this club changing?","Hit-rate and miss-count trends use only the selected games. A game with no classified records is a gap, not a 0% hit rate. Miss counts also depend on how often you used the club.")
            choices={}
            for row in candidates:
                name=row["label"]
                suffix=2
                while name in choices:
                    name=f"{row['label']} ({suffix})"
                    suffix+=1
                choices[name]=row["id"]
            if self.confidence_trend_club not in choices.values():
                self.confidence_trend_club=(strongest or worst or candidates[0])["id"]
            pick=ttk.Combobox(controls,values=list(choices),state="readonly",width=28)
            pick.set(next(name for name,key in choices.items() if key==self.confidence_trend_club))
            pick.pack(anchor="w",padx=18,pady=(0,16),ipady=3)
            holder=tk.Frame(controls,bg=WHITE)
            holder.pack(fill="x",padx=18,pady=(0,16))
            def draw_club_trends(_=None):
                self.confidence_trend_club=choices[pick.get()]
                for child in holder.winfo_children():
                    child.destroy()
                history=club_history(self.model,selected,self.confidence_role,self.confidence_trend_club)
                for i,series in enumerate(history.values()):
                    holder.columnconfigure(i,weight=1,uniform="clubtrend")
                    tile=tk.Frame(holder,bg=WHITE)
                    tile.grid(row=0,column=i,sticky="nsew",padx=(0,14 if i==0 else 0))
                    label(tile,series["label"],11,True).pack(anchor="w",pady=(0,8))
                    chart(tile,lambda c,s=series:draw_history_trend(c,s,self.rolling_window,self.go_round),height=250,padx=0)
                    label(tile,f"{len(series['points'])} games with classified outcomes; {series['missing']} without. Hover for per-game sample size.",8,color=MUTED,wraplength=450,justify="left").pack(anchor="w")
            pick.bind("<<ComboboxSelected>>",draw_club_trends)
            draw_club_trends()
        label(body,"Compare clubs within the same shot role. Longer clubs face different distances and lies; a higher target-hit rate alone is not a lower expected score.",9,color=MUTED,bg=BG,wraplength=1100,justify="left").pack(anchor="w",pady=(0,18))

    def render_improve(self, body):
        views = tk.Frame(body,bg=BG)
        views.pack(fill="x",pady=(0,18))
        def choose_view(tab):
            self.improve_tab = tab
            self.show_page("improve")
        for key,title in (("dashboard","Visual dashboard"),("strategy","Course strategy"),("ev","Expected score / EV")):
            button(views,title,lambda k=key:choose_view(k),primary=self.improve_tab==key).pack(side="left",padx=(0,10))
        if self.improve_tab=="strategy":
            self.strategy_view = StrategyView(body,self.model,self.strategy_state,selected=self.selected_games())
            return
        if self.improve_tab=="ev":
            self.ev_view = ExpectedValueView(body,self.model,self.ev_state)
            return
        toolbar = tk.Frame(body,bg=BG)
        toolbar.pack(fill="x",pady=(0,16))
        label(toolbar,self.selected_description(),9,color=MUTED,bg=BG,wraplength=550).pack(side="left")
        button(toolbar,"Review selected games →",lambda: self.open_rounds("trends")).pack(side="right")
        button(toolbar,"Full-game charts →",lambda:self.go_game()).pack(side="right",padx=10)
        coaching = improvement_snapshot(self.model,selected=self.selected_games())
        rounds, metrics = coaching["rounds"],coaching["metrics"]
        if not rounds:
            if self.selected_games():
                frame=self.section(body,"These starter goals use complete 18-hole games.","Your selection has no complete 18-hole games. Nine-hole games remain available in Rounds & trends, scorecards and per-hole statistics.")
                button(frame,"Open selected-game trends",lambda:self.open_rounds("trends")).pack(anchor="w",padx=18,pady=(0,18))
            else:
                self.empty_history(body)
            return
        sample = f"Practice goals: {len(rounds)} complete 18-hole games · {pretty_date(rounds[-1]['date'])} to {pretty_date(rounds[0]['date'])}. Shot charts use all selected games."
        label(body,sample,9,color=MUTED,bg=BG).pack(anchor="w",pady=(0,14))
        self.metrics_row(body,[("Scoring average",fmt(metrics["average_score"]),"Gross scores; courses and tees differ"),
                               ("Greens in regulation",fmt(metrics["gir"],suffix="%"),"Recorded greens, weighted by holes"),
                               ("Three-putt+ holes",fmt(metrics["three_putts"]),"Per round with complete putt tracking"),
                               ("Recorded penalties",fmt(metrics["penalties"]),"Per round; missing entries may undercount")])
        priorities = self.section(body,"Your practice priorities","Bars are your recorded averages; green markers are starter practice goals per 18-hole round. These categories overlap—do not add them up as stroke savings.")
        chart(priorities,lambda c:draw_priorities(c,coaching["priorities"]),height=260)
        focus = tk.Frame(priorities,bg=MINT,padx=14,pady=12)
        focus.pack(fill="x",padx=18,pady=(0,18))
        label(focus,"START HERE",9,True,GREEN,MINT).pack(anchor="w")
        label(focus,coaching["priorities"][0]["practice"],10,color=INK,bg=MINT,wraplength=1060,justify="left").pack(anchor="w",pady=(5,0))
        if coaching["partial_penalty_tracking"]:
            label(priorities,"Some penalty fields are missing in this sample. The penalty bar shows recorded entries, not a guaranteed complete count.",9,color=AMBER,wraplength=1070,justify="left").pack(anchor="w",padx=18,pady=(0,16))
        pair = tk.Frame(body,bg=BG)
        pair.pack(fill="x",pady=(0,18))
        pair.columnconfigure(0,weight=1,uniform="visual")
        pair.columnconfigure(1,weight=1,uniform="visual")
        approach_card,pattern_card = card(pair),card(pair)
        approach_card.grid(row=0,column=0,sticky="nsew",padx=(0,14))
        pattern_card.grid(row=0,column=1,sticky="nsew")
        label(approach_card,"Approach misses by club",14,True).pack(anchor="w",padx=18,pady=(18,5))
        label(approach_card,"Top seven by off-green finishes. Samples are small, and shot difficulty differs.",9,color=MUTED,wraplength=470,justify="left").pack(anchor="w",padx=18,pady=(0,8))
        analysis = coaching["approaches"]
        chart(approach_card,lambda c:draw_approach_bars(c,analysis),height=410)
        top = coaching["top_club"]
        if top:
            label(approach_card,f"{top['label']}: {top['miss']} off-green finishes from {top['approaches']} recorded approaches. This identifies a review target, not proof of a bad club.",10,color=INK,wraplength=470,justify="left").pack(anchor="w",padx=18,pady=(0,10))
        label(approach_card,f"COVERAGE {analysis['shot_holes']}/{analysis['expected_holes']} holes · {analysis['unassigned']} unassigned clubs · {analysis['unknown_outcomes']} unknown outcome(s). Missing data is never counted as a miss.",9,color=AMBER if analysis["shot_holes"]<analysis["expected_holes"] else MUTED,wraplength=470,justify="left").pack(anchor="w",padx=18,pady=(0,12))
        button(approach_card,"Open selected-game shot comparison →",lambda:self.go_approaches()).pack(anchor="w",padx=18,pady=(0,18))
        label(pattern_card,"Where do you miss the green?",14,True).pack(anchor="w",padx=18,pady=(18,5))
        label(pattern_card,"Garmin’s aggregate direction categories—not restricted to the selected games.",9,color=MUTED,wraplength=470,justify="left").pack(anchor="w",padx=18,pady=(0,8))
        aggregate = self.model.aggregate_clubs(include_retired=True)
        choices = {}
        for row in aggregate:
            name = row["label"]+(" (retired)" if row["retired"] else "")
            base,index = name,2
            while name in choices:
                name,index = f"{base} ({index})",index+1
            choices[name] = row
        available = {row["id"]:row for row in aggregate}
        if self.pattern_club not in available:
            self.pattern_club = top["id"] if top and top["id"] in available else next(iter(available),None)
        state = {"row":available.get(self.pattern_club)}
        selection = ttk.Combobox(pattern_card,values=list(choices),state="readonly",width=26)
        selection.set(next((name for name,row in choices.items() if row["id"]==self.pattern_club),"No club statistics"))
        selection.pack(anchor="w",padx=18,pady=(0,4))
        diagram = chart(pattern_card,lambda c:draw_miss_pattern(c,state["row"]),height=350)
        caption = label(pattern_card,"",10,color=INK,wraplength=470,justify="left")
        caption.pack(anchor="w",padx=18,pady=(0,10))
        def update_pattern(_=None):
            row = choices.get(selection.get())
            if row:
                state["row"],self.pattern_club = row,row["id"]
                candidates = [(key,row[key]) for key in ("short","long","left","right") if row.get(key) is not None]
                if candidates:
                    direction,value = max(candidates,key=lambda x:x[1])
                    caption.configure(text=f"Most common aggregate miss: {direction} ({value:.1f}%). Review normal carry, contact and club choice; this picture is not a swing diagnosis.")
                else:
                    caption.configure(text="Directional percentages are unavailable for this club.")
                if diagram.winfo_width()>150:
                    draw_miss_pattern(diagram,row)
        selection.bind("<<ComboboxSelected>>",update_pattern)
        update_pattern()
        label(pattern_card,"This is a category diagram, not a map of shot positions. Percentages are Garmin’s club-summary outcomes; approach-attempt sample sizes are not supplied.",9,color=MUTED,wraplength=470,justify="left").pack(anchor="w",padx=18,pady=(0,18))
        shown = rounds[:6]
        heat = self.section(body,"Where big numbers happen",f"{len(shown)} most recent rounds in this view. Each square shows strokes over par for that hole; holes from different courses are not directly comparable.")
        chart(heat,lambda c:draw_hole_heatmap(c,shown),height=90+52*len(shown))
        costly = [(r,h) for r in shown for h in r["big_holes"]]
        if costly:
            r,h = max(costly,key=lambda item:item[1]["to_par"])
            label(heat,f"Largest recorded hole here: {pretty_date(r['date'])}, hole {h['number']} at {r['course']} — {fmt(h['strokes'],0)} on par {h['par']} ({fmt(h.get('putts'),0)} putts, {fmt(h.get('penalties'),0)} recorded penalties).",10,color=MUTED,wraplength=1080,justify="left").pack(anchor="w",padx=18,pady=(0,18))

    def go_game(self, tab="tee"):
        self.game_tab = tab
        self.show_page("game")

    def go_strategy(self, phase="tee", club_id=None):
        self.improve_tab = "strategy"
        self.strategy_state["phase"] = phase
        if club_id is not None:
            self.strategy_state["club_"+phase] = self.model.club_label(club_id)[0]
        self.show_page("improve")

    def render_game(self, body):
        tools = tk.Frame(body,bg=BG)
        tools.pack(fill="x",pady=(0,16))
        label(tools,self.selected_description(),9,color=MUTED,bg=BG,wraplength=530).pack(side="left")
        button(tools,"Update detailed shots",lambda:self.open_sync(rounds=self.recommended_import_count(True),shots=True)).pack(side="right")
        button(tools,"Plan the next shot →",lambda:self.go_strategy({"tee":"tee","putting":"putting","wedges":"wedge"}[self.game_tab])).pack(side="right",padx=10)
        tabs = tk.Frame(body,bg=BG)
        tabs.pack(fill="x",pady=(0,18))
        def choose_tab(tab):
            self.game_tab = tab
            self.show_page("game")
        for key,title in (("tee","Tee shots & driver"),("putting","Putting"),("wedges","Wedges")):
            button(tabs,title,lambda k=key:choose_tab(k),primary=self.game_tab==key).pack(side="left",padx=(0,10))
        selected = self.selected_games()
        if not selected:
            self.empty_history(body)
            return
        game = full_game_snapshot(self.model,selected)
        label(body,f"{len(selected)} selected games · shot coverage {game['shot_holes']}/{game['expected_holes']} holes. Missing shot data is not treated as a failed shot.",9,color=MUTED,bg=BG,wraplength=1090).pack(anchor="w",pady=(0,16))
        if self.game_tab=="tee":
            self.render_tee(body,game)
        elif self.game_tab=="putting":
            self.render_putting(body,game)
        else:
            self.render_wedges(body,game)

    def render_tee(self, body, game):
        driver = next((r for r in game["tee"] if r["driver"]),None)
        self.metrics_row(body,[("Overall fairways",fmt(game["fairway_percent"],suffix="%"),"All recorded scorecard fairways"),
                               ("Driver fairway hit",fmt(driver["fw_percent"] if driver else None,suffix="%"),"Only holes with attributed driver tees"),
                               ("Driver shot length",fmt(driver["average_yards"] if driver else None,0," yd"),"Recorded average, including roll—not carry"),
                               ("Tracked tee shots",str(sum(r["tee_shots"] for r in game["tee"])),"Includes identifiable par-3 tee shots")])
        frame = self.section(body,"Where tee shots finish","Bars use recorded fairway/left/right outcomes on par-4/5 holes with one attributed tee shot. Par-3 tee shots do not have fairway percentages.")
        eligible = [r for r in game["tee"] if r["fw_recorded"] or r["unknown"]]
        chart(frame,lambda c:draw_tee_bars(c,game["tee"]),height=90+43*min(7,len(eligible)))
        detail = self.section(body,"Tee clubs and recorded distance","Shot length includes roll and can contain tracking outliers. It is not a stock carry distance. Par-3 tee approaches are included when explicitly recorded as starting on the tee.")
        tree = self.tree(detail,[("club","Club",190),("tees","Tee shots",85),("par3","Par-3 tees",85),("fw","FW hit/recorded",130),("rate","FW hit %",100),("avg","Avg length (yd)",125),("median","Median (yd)",115),("n","Length records",115)],height=min(9,max(3,len(game["tee"]))))
        for row in game["tee"]:
            tree.insert("","end",values=(row["label"],row["tee_shots"],row["par3_tees"],f"{row['hit']}/{row['fw_recorded']}" if row["fw_recorded"] else "—",fmt(row["fw_percent"],suffix="%"),fmt(row["average_yards"],0),fmt(row["median_yards"],0),len(row["lengths"])),tags=("highlight" if row["driver"] else "",))
        label(detail,f"{game['ambiguous_tee_holes']} hole(s) had multiple tee records; their fairway outcomes were not attributed to a club. Hole penalties are not automatically blamed on the tee shot.",9,color=MUTED,wraplength=1080,justify="left").pack(anchor="w",padx=18,pady=(0,14))
        button(detail,"Export tee comparison",lambda:self.export_table(tree,"tee-clubs.csv")).pack(anchor="w",padx=18,pady=(0,18))

    def render_putting(self, body, game):
        self.metrics_row(body,[(f"Putts / {game['average_putts_holes']}-hole game",fmt(game["average_putts"]),"Selected scorecards; lengths not mixed"),
                               ("Putts / tracked hole",fmt(game["putts_per_tracked_hole"],2),"Uses only holes with recorded putts"),
                               ("Three-putt+ holes",fmt(game["three_putts_per_full_round"]),"Per full round with complete tracking"),
                               ("Putting coverage",f"{game['tracked_putting_holes']} / {game['expected_holes']}","Scorecard holes with putt counts")])
        pair = tk.Frame(body,bg=BG)
        pair.pack(fill="x",pady=(0,18))
        for col in (0,1):
            pair.columnconfigure(col,weight=1,uniform="putting")
        history,drill = card(pair),card(pair)
        history.grid(row=0,column=0,sticky="nsew",padx=(0,14))
        drill.grid(row=0,column=1,sticky="nsew")
        label(history,"Three-putts to work on",14,True).pack(anchor="w",padx=18,pady=(18,6))
        label(history,f"All selected {game['average_putts_holes']}-hole games, oldest to newest. Other lengths remain in the table; the ≤2 starter goal applies to 18-hole games only.",9,color=MUTED,wraplength=470,justify="left").pack(anchor="w",padx=18,pady=(0,8))
        chart(history,lambda c:draw_putting_bars(c,game["putting"]),height=300)
        label(history,"* means incomplete tracking or a non-18-hole sample, not a directly comparable full round.",9,color=MUTED,wraplength=470,justify="left").pack(anchor="w",padx=18,pady=(0,18))
        label(drill,"A simple distance-control drill",14,True).pack(anchor="w",padx=18,pady=(18,6))
        label(drill,"Three balls each from 20, 30 and 40 feet. Aim to finish inside three feet.",9,color=MUTED,wraplength=470,justify="left").pack(anchor="w",padx=18,pady=(0,8))
        chart(drill,draw_putting_drill,height=300)
        frame = self.section(body,"Putting scorecards","These totals come from your scorecards, not incomplete auto-detected PUTT shot lists. Verify scorecard tracking before making putting your top practice priority.")
        tree = self.tree(frame,[("date","Date",110),("course","Course",260),("putts","Putts",70),("one","1-putts",75),("two","2-putts",75),("three","3+ holes",80),("four","4+ holes",80),("tracked","Tracked holes",115)],height=min(10,max(3,len(game["putting"]))))
        for row in game["putting"]:
            tree.insert("","end",values=(row["date"],row["course"],fmt(row["putts"],0),row["one"],row["two"],row["three_plus"],row["four_plus"],f"{row['tracked']}/{row['holes']}"),tags=("caution" if row["three_plus"]>2 or row["tracked"]<row["holes"] else "",))
        button(frame,"Export putting comparison",lambda:self.export_table(tree,"putting-rounds.csv")).pack(anchor="w",padx=18,pady=(0,18))

    def render_wedges(self, body, game):
        approach_green = sum(r["approach"]["green"] for r in game["wedges"])
        approach_known = sum(r["approach"]["green"]+r["approach"]["miss"] for r in game["wedges"])
        chip_green = sum(r["chip"]["green"] for r in game["wedges"])
        chip_known = sum(r["chip"]["green"]+r["chip"]["miss"] for r in game["wedges"])
        self.metrics_row(body,[("Wedge approaches",str(game["wedge_approaches"]),"Tracked APPROACH shots with wedges"),
                               ("Approaches on green",fmt(percent(approach_green,approach_known),suffix="%"),"Unknown finishes excluded from rate"),
                               ("Tracked wedge chips",str(game["chip_shots"]),"Chips are separate from approaches"),
                               ("Chips on green",fmt(percent(chip_green,chip_known),suffix="%"),"Not an up-and-down success rate")])
        frame = self.section(body,"Wedge approaches versus chips","Green = on green · amber = off green · grey = unknown. The same wedge can be used for very different shots, so those roles are not mixed.")
        lines = sum(bool(r[role]["shots"]) for r in game["wedges"] for role in ("approach","chip"))
        chart(frame,lambda c:draw_wedge_bars(c,game["wedges"]),height=max(140,60+42*lines))
        detail = self.section(body,"Your wedge data","Approach lengths may include partial swings and roll, not full-swing carry. Chip distances are shown separately. An on-green finish does not prove an up-and-down.")
        tree = self.tree(detail,[("club","Wedge",175),("an","Approaches",90),("ag","On green",95),("cn","Chips",65),("cg","Chip on green",120),("al","Approach avg yd",130),("cl","Chip avg yd",110),("other","Other shots",95)],height=min(9,max(3,len(game["wedges"]))))
        for row in game["wedges"]:
            tree.insert("","end",values=(row["label"],row["approach"]["shots"],fmt(row["approach_green_percent"],suffix="%"),row["chip"]["shots"],fmt(row["chip_green_percent"],suffix="%"),fmt(row["approach_average_yards"],0),fmt(row["chip_average_yards"],0),row["other"]))
        label(detail,"Recovery, bunker, putt, or unclassified wedge records are ‘Other shots’, not failed approaches or chips. Zero means no exported records, not necessarily no on-course use. These are outcomes, not strokes gained.",9,color=MUTED,wraplength=1080,justify="left").pack(anchor="w",padx=18,pady=(0,14))
        button(detail,"Export wedge comparison",lambda:self.export_table(tree,"wedge-stats.csv")).pack(anchor="w",padx=18,pady=(0,18))

    def go_round(self, rid):
        self.selected_round = rid
        self.rounds_tab="scorecards"
        self.show_page("rounds")

    def open_rounds(self,tab="trends"):
        self.rounds_tab=tab
        self.show_page("rounds")

    def render_rounds(self, body):
        self.trend_charts={}
        tabs=tk.Frame(body,bg=BG)
        tabs.pack(fill="x",pady=(0,18))
        for key,title in (("trends","Trend charts"),("scorecards","Scorecards")):
            button(tabs,title,lambda k=key:self.open_rounds(k),primary=self.rounds_tab==key).pack(side="left",padx=(0,10))
        rounds = self.selected_games()
        if not rounds:
            self.empty_history(body)
            return
        stats=period_statistics(rounds)
        kind=stats["scoring_holes"]
        coverage = self.model.approach_analysis(rounds)
        if self.rounds_tab=="trends":
            self.render_trends(body,rounds)
            return
        self.metrics_row(body, [(f"{kind}-hole score average", fmt(stats["average_score"]), f"{stats['scoring_games']} selected {kind}-hole games"),
                                ("Greens in regulation", fmt(stats["gir"],suffix="%"), "All selected recorded greens"),
                                (f"Putts / {kind}-hole game", fmt(stats["putts"]), "Selected scorecards; lengths not mixed"),
                                ("Shot-data coverage", f"{coverage['shot_holes']} / {coverage['expected_holes']}", "Holes with detailed shot records")])
        frame = self.section(body, "Round comparison", "Select a round below to review its scorecard. Recorded penalties may have missing entries.")
        tree = self.tree(frame, [("date","Date",105),("course","Course",300),("holes","Holes",55),("score","Score",90),("gir","Greens",80),("fw","Fairways",80),("putts","Putts",65),("pen","Pen.",60),("shots","Shot holes",80)], height=min(10,max(3,len(rounds))))
        for r in rounds:
            tree.insert("", "end", iid=r["id"], values=(pretty_date(r["date"]),r["course"],r["holes_completed"],f"{fmt(r['score'],0)} ({fmt_delta(r['to_par'])})",f"{fmt(r['greens_hit'],0)}/{fmt(r['greens_recorded'],0)}",f"{fmt(r['fairways_hit'],0)}/{fmt(r['fairways_recorded'],0)}",fmt(r["putts"],0),fmt(r["penalties"],0),f"{r['shot_holes']}/{r['holes_completed']}"))
        detail = tk.Frame(body, bg=BG)
        detail.pack(fill="x")
        def select(_=None):
            chosen = tree.selection()
            if chosen:
                self.selected_round = chosen[0]
                r = next(x for x in rounds if x["id"] == chosen[0])
                self.render_scorecard(detail, r)
        tree.bind("<<TreeviewSelect>>", select)
        if rounds:
            selected = self.selected_round if any(r["id"] == self.selected_round for r in rounds) else rounds[0]["id"]
            tree.selection_set(selected)
            self.render_scorecard(detail, next(r for r in rounds if r["id"] == selected))
        else:
            self.empty_history(body)

    def render_trends(self,body,rounds):
        controls=tk.Frame(body,bg=BG)
        controls.pack(fill="x",pady=(0,16))
        label(controls,"ROLLING AVERAGE",9,True,MUTED,BG).pack(side="left",padx=(0,10))
        rolling=ttk.Combobox(controls,values=("Off","3 games","5 games","10 games","20 games"),state="readonly",width=15)
        rolling.set(f"{self.rolling_window} games" if self.rolling_window else "Off")
        rolling.pack(side="left",ipady=3)
        def change(_):
            self.rolling_window=0 if rolling.get()=="Off" else int(rolling.get().split()[0])
            self.show_page("rounds")
        rolling.bind("<<ComboboxSelected>>",change)
        label(body,self.selected_description()+". Charts run oldest to newest. A rolling mean needs a complete window of recorded selected games; it never fills missing values with zero.",9,color=MUTED,bg=BG,wraplength=1090,justify="left").pack(anchor="w",pady=(0,15))
        self.trend_charts={}
        grid=None
        for i,key in enumerate(default_trend_keys(rounds)):
            if i%2==0:
                grid=tk.Frame(body,bg=BG)
                grid.pack(fill="x",pady=(0,18))
                grid.columnconfigure(0,weight=1,uniform="trend")
                grid.columnconfigure(1,weight=1,uniform="trend")
            series=trend_series(rounds,key)
            tile=card(grid)
            tile.grid(row=0,column=i%2,sticky="nsew",padx=(0,14 if i%2==0 else 0))
            label(tile,series["label"],13,True).pack(anchor="w",padx=18,pady=(16,5))
            mean_label="pooled rate" if series["unit"]=="%" or key=="putts_per_hole" else "game mean"
            label(tile,f"{len(series['points'])} recorded games · {mean_label} {fmt(series['average'],2)} {series['unit']}",9,color=MUTED).pack(anchor="w",padx=18,pady=(0,7))
            canvas=chart(tile,lambda c,s=series:draw_history_trend(c,s,self.rolling_window,self.go_round),height=250)
            self.trend_charts[key]=canvas
            if series["change"] is None:
                comparison="At least two recorded values in each half are needed for an older-versus-newer comparison."
            else:
                unit="percentage points" if series["unit"]=="%" else series["unit"]
                direction="lower" if series["change"]<0 else "higher" if series["change"]>0 else "unchanged"
                comparison=f"Recent half {abs(series['change']):.2f} {unit} {direction} than older half ({fmt(series['older_average'],2)} → {fmt(series['newer_average'],2)})." if round(series["change"],2)!=0 else f"Older and recent half means are effectively unchanged ({fmt(series['older_average'],2)} → {fmt(series['newer_average'],2)})."
            label(tile,comparison,9,color=GREEN if series["improving"] else MUTED,wraplength=470,justify="left").pack(anchor="w",padx=18,pady=(0,9))
            detail=f"{series['missing']} missing metric value(s); {series['excluded']} other-length game(s) excluded. Click a chart point to open its scorecard."
            label(tile,detail,8,color=MUTED,wraplength=470,justify="left").pack(anchor="w",padx=18,pady=(0,16))
        label(body,"These are descriptive trends, not proof of a swing or handicap change. Courses, tees, conditions and the games you chose can differ. Nine- and 18-hole gross scores are never averaged together.",9,color=MUTED,bg=BG,wraplength=1090,justify="left").pack(anchor="w",pady=(0,18))
        frame=self.section(body,"Selected-game trend data","Export the exact selected games, in chronological order, for your own analysis.")
        tree=self.tree(frame,[("date","Date",105),("course","Course",250),("holes","Holes",60),("score","Score",70),("gir","GIR %",85),("fw","FW %",85),("putts","Putts",70),("pen","Recorded pen.",110)],height=min(10,max(3,len(rounds))))
        for r in reversed(rounds):
            tree.insert("","end",iid=r["id"],values=(r["date"],r["course"],r["holes_completed"],fmt(r["score"],0),fmt(percent(r["greens_hit"],r["greens_recorded"])),fmt(percent(r["fairways_hit"],r["fairways_recorded"])),fmt(r["putts"],0),fmt(r["penalties"],0)))
        button(frame,"Export selected-game trends",lambda:self.export_table(tree,"selected-game-trends.csv")).pack(anchor="w",padx=18,pady=(0,18))

    def render_scorecard(self, parent, r):
        for child in parent.winfo_children():
            child.destroy()
        frame = self.section(parent, r["course"], f"{pretty_date(r['date'])} · Par {fmt(r['par'],0)} · Score {fmt(r['score'],0)}")
        grids = tk.Frame(frame, bg=WHITE)
        grids.pack(fill="x", padx=18, pady=(0, 16))
        holes = {h["number"]: h for h in r["holes"]}
        for side, start in enumerate((1,10)):
            grids.columnconfigure(side, weight=1, uniform="nine")
            nine = tk.Frame(grids, bg=BORDER)
            nine.grid(row=0,column=side,sticky="nsew",padx=(0,12 if side==0 else 0))
            for col, n in enumerate([None,*range(start,start+9)]):
                nine.columnconfigure(col, weight=1)
                for row, field_ in enumerate(("header","par","strokes","putts","penalties")):
                    h = holes.get(n,{})
                    bg, fg = WHITE, INK
                    if row == 0:
                        text, bg, fg = ("OUT" if side == 0 else "IN") if n is None else str(n), NAVY, WHITE
                    elif n is None:
                        text = {"par":"Par","strokes":"Score","putts":"Putts","penalties":"Pen."}[field_]
                        bg = "#F0F4EF"
                    else:
                        text = fmt(h.get(field_),0)
                        delta = h.get("to_par")
                        if field_ == "strokes" and delta is not None:
                            bg = "#FBE5DF" if delta >= 3 else AMBER_BG if delta >= 2 else MINT if delta <= 0 else WHITE
                    tk.Label(nine,text=text,bg=bg,fg=fg,font=(FONT,9,"bold" if row in (0,2) else "normal"),padx=5,pady=7).grid(row=row,column=col,sticky="nsew",padx=1,pady=1)
        text = "Big holes: " + "; ".join(f"#{h['number']}: {fmt(h['strokes'],0)} on par {h['par']} ({fmt(h.get('putts'),0)} putts, {fmt(h.get('penalties'),0)} penalties)" for h in r["big_holes"][:5]) if r["big_holes"] else "No double-bogey-or-worse holes are present in this scorecard."
        label(frame,text,10,color=MUTED,wraplength=1070,justify="left").pack(anchor="w",padx=18,pady=(0,14))
        button(frame,"Review this round’s approach shots →",lambda: self.go_approaches(r["id"])).pack(anchor="w",padx=18,pady=(0,18))

    def go_approaches(self, rid=None):
        self.approach_round = rid
        self.approach_mode = "Selected games · shot data"
        self.show_page("clubs")

    def render_clubs(self, body):
        toolbar = tk.Frame(body,bg=BG)
        toolbar.pack(fill="x",pady=(0,16))
        mode = ttk.Combobox(toolbar,values=("Selected games · shot data","Garmin aggregate club stats"),state="readonly",width=28)
        mode.set(self.approach_mode)
        mode.pack(side="left",ipady=3)
        def mode_changed(_):
            self.approach_mode = mode.get()
            self.show_page("clubs")
        mode.bind("<<ComboboxSelected>>",mode_changed)
        button(toolbar,"Update detailed shots",lambda: self.open_sync(rounds=self.recommended_import_count(True),shots=True)).pack(side="right")
        if self.approach_mode == "Garmin aggregate club stats":
            self.render_aggregate_clubs(body)
            return
        rounds = self.selected_games()
        selected = [r for r in rounds if r["id"] == self.approach_round] if self.approach_round else rounds
        if not selected:
            selected, self.approach_round = rounds, None
        choices = {"All selected games": None, **{f"{r['date']} · {r['course']}":r["id"] for r in rounds}}
        choice = ttk.Combobox(toolbar,values=list(choices),state="readonly",width=25)
        choice.set(next((k for k,v in choices.items() if v == self.approach_round),"All selected games"))
        choice.pack(side="left",padx=10,ipady=3)
        choice.bind("<<ComboboxSelected>>",lambda _: self.select_approach_round(choices[choice.get()]))
        analysis = self.model.approach_analysis(selected)
        misses = sum(x["miss"] for x in analysis["clubs"])
        self.metrics_row(body,[("Recorded approaches",str(analysis["approaches"]),"Garmin-classified APPROACH shots"),
                               ("Off-green finishes",str(misses),"Unknown outcomes are not misses"),
                               ("Unassigned club",str(analysis["unassigned"]),"These cannot identify a problem club"),
                               ("Coverage",f"{analysis['shot_holes']} / {analysis['expected_holes']}","Holes with exported shot data")])
        if analysis["shot_holes"] < analysis["expected_holes"] or analysis["unknown_outcomes"]:
            warning = card(body)
            warning.pack(fill="x",pady=(0,18))
            label(warning,f"PARTIAL COVERAGE · {analysis['shot_holes']} of {analysis['expected_holes']} holes have shot data; {analysis['unknown_outcomes']} approach outcome(s) are unknown. Missing shots are never counted as successes or failures.",10,color=AMBER,wraplength=1080,justify="left").pack(anchor="w",padx=16,pady=14)
        frame = self.section(body,"Approach outcomes by club","Sorted by recorded off-green finishes, not by a claim that every miss was a mistake. Small samples and shot difficulty matter.")
        tree = self.tree(frame,[("club","Club",200),("attempts","Approaches",90),("green","On green",85),("miss","Off green",85),("unknown","Unknown",85),("rate","Green hit",90),("sample","Sample",95)],height=min(10,max(3,len(analysis["clubs"]))))
        for i,row in enumerate(analysis["clubs"]):
            tree.insert("","end",iid=row["id"],values=(row["label"],row["approaches"],row["green"],row["miss"],row["unknown"],fmt(row["green_percent"],suffix="%"),"Small (<10)" if row["approaches"]<10 else "Recorded"),tags=("muted" if row["unassigned"] else "highlight" if i==0 else "",))
        actions = tk.Frame(frame,bg=WHITE)
        actions.pack(fill="x",padx=18,pady=(0,16))
        button(actions,"Edit club display name",lambda: self.rename_club(tree)).pack(side="left")
        button(actions,"Plan selected club’s approach",lambda:self.go_strategy("approach",tree.selection()[0] if tree.selection() else None)).pack(side="left",padx=10)
        button(actions,"Export this comparison",lambda: self.export_table(tree,"approach-clubs.csv")).pack(side="right")
        label(frame,"Standard club names are filled in automatically. Your Garmin custom names are preserved; optional display-name edits stay local and do not change your Garmin account.",9,color=MUTED,wraplength=1080,justify="left").pack(anchor="w",padx=18,pady=(0,16))
        shots_frame = self.section(body,"Approach shot log","On-green finish is not the same as GIR. Distances below are recorded shot lengths, not carry or original target distance.")
        shot_tree = self.tree(shots_frame,[("date","Date",105),("hole","Hole",55),("club","Club",180),("start","From",100),("end","Finished",100),("outcome","Outcome",105),("distance","Length (yd)",95)],height=7)
        for i,row in enumerate(analysis["shots"]):
            shot_tree.insert("","end",iid=str(i),values=(row["date"],row["hole"],row["club"],row["start_lie"],row["end_lie"],{"green":"On green","miss":"Off green","unknown":"Unknown"}[row["outcome"]],fmt(row["meters"]/0.9144 if row["meters"] is not None else None,0)),tags=("highlight" if row["outcome"]=="green" else "caution" if row["outcome"]=="unknown" else "",))
        if not analysis["shots"]:
            label(shots_frame,"No detailed approaches for this selection yet. Use ‘Update detailed shots’ to choose an import window; locations remain optional until you confirm the import.",10,color=MUTED,wraplength=1080).pack(anchor="w",padx=18,pady=(0,18))

    def select_approach_round(self, rid):
        self.approach_round = rid
        self.show_page("clubs")

    def render_aggregate_clubs(self, body):
        frame = self.section(body,"Garmin’s aggregate club summary","These percentages are not restricted to your selected games. Total tracked shots are NOT the number of approach attempts.")
        tree = self.tree(frame,[("club","Club",200),("hit","Green hit",85),("short","Short",80),("long","Long",80),("left","Left",80),("right","Right",80),("all","All tracked shots",125)],height=12)
        for row in self.model.aggregate_clubs():
            tree.insert("","end",iid=row["id"],values=(row["label"],fmt(row["green_percent"],suffix="%"),fmt(row["short"],suffix="%"),fmt(row["long"],suffix="%"),fmt(row["left"],suffix="%"),fmt(row["right"],suffix="%"),fmt(row["all_shots"],0)))
        actions = tk.Frame(frame,bg=WHITE)
        actions.pack(fill="x",padx=18,pady=(0,16))
        button(actions,"Edit club display name",lambda: self.rename_club(tree)).pack(side="left")
        button(actions,"Export comparison",lambda: self.export_table(tree,"aggregate-club-stats.csv")).pack(side="right")
        label(frame,"Retired clubs are hidden here, but still appear in recent-shot analysis if used during those rounds. A long-club green miss is not automatically a worse shot than a wedge miss.",9,color=MUTED,wraplength=1080,justify="left").pack(anchor="w",padx=18,pady=(0,18))

    def render_privacy(self, body):
        frame = self.section(body,"Remembered sign-in","Session tokens are protected by Windows DPAPI for your Windows user. Your Garmin password is never saved.")
        label(frame,"Remembered on this PC" if self.store.exists else "No remembered sign-in yet",16,True,color=GREEN if self.store.exists else INK).pack(anchor="w",padx=18)
        label(frame,"Sign in once using ‘Update from Garmin’ and leave ‘Remember this PC’ checked. The app can refresh a valid saved session on later updates. Garmin can expire or revoke access, so six months without another prompt cannot be guaranteed.",10,color=MUTED,wraplength=1070,justify="left").pack(anchor="w",padx=18,pady=(10,16))
        row = tk.Frame(frame,bg=WHITE)
        row.pack(fill="x",padx=18,pady=(0,18))
        button(row,"Forget sign-in on this PC",self.forget_account).pack(side="left")
        button(row,"Open Garmin Connect",lambda: webbrowser.open("https://connect.garmin.com/app/golf-stats")).pack(side="left",padx=10)
        privacy = self.section(body,"What stays where")
        for title,text in (("No Garmin edits","The app reads golf data. It does not upload workouts, change scorecards, or delete Garmin records."),
                           ("Windows-protected session","The encrypted session file is outside exports, under Local AppData / GolfDesk. Other processes running as your Windows user may still access user-protected data."),
                           ("Private golf exports","JSON exports contain course names, dates, and possibly shot locations. The exports themselves are not encrypted; protect them like other personal files."),
                           ("One account at a time","Exports are combined only when their player profile IDs match. Unidentified or other-account exports are not silently mixed."),
                           ("Unofficial API limits","Garmin may change or block this integration. Authentication grants broader account access than this app uses; trust in the library is still required.")):
            label(privacy,title,10,True).pack(anchor="w",padx=18,pady=(8,3))
            label(privacy,text,10,color=MUTED,wraplength=1070,justify="left").pack(anchor="w",padx=18,pady=(0,10))
        history = self.section(body,"Local export history",f"{len(self.model.sources)} compatible source files · {self.model.skipped_files} other or unreadable file(s) excluded")
        tree = self.tree(history,[("file","File",500),("rounds","Requested rounds",130),("shots","Detailed shots",130),("status","Result",120)],height=min(6,max(2,len(self.model.sources))))
        for i,path in enumerate(self.model.sources):
            try:
                data = read_export(path)
                tree.insert("","end",iid=str(i),values=(path.name,data.get("scope",{}).get("round_limit","—"),"Included" if data.get("scope",{}).get("include_shots") else "Not included",data.get("status","Unknown")))
            except (OSError,ValueError):
                pass
        actions = tk.Frame(history,bg=WHITE)
        actions.pack(fill="x",padx=18,pady=(0,18))
        button(actions,"Open exports folder",self.open_exports_folder).pack(side="left")
        button(actions,"Reload saved data",self.reload_data).pack(side="left",padx=10)
        label(body,"This app is not made or supported by Garmin. Passwords, verification codes, and decrypted tokens must never be shared in chat.",9,color=MUTED,bg=BG,wraplength=1090,justify="left").pack(anchor="w",pady=(0,16))

    def empty(self,parent,title,text):
        frame = self.section(parent,title,text)
        button(frame,"Connect to Garmin",self.open_sync,primary=True).pack(anchor="w",padx=18,pady=(0,18))

    def rename_club(self, tree):
        chosen = tree.selection()
        if not chosen:
            messagebox.showinfo("Choose a club","Select a club row first.",parent=self.root)
            return
        key = chosen[0]
        if key == "0":
            messagebox.showinfo("Unassigned shots","These shots have no recorded club. Assign their clubs in Garmin before re-importing; a local label cannot identify them.",parent=self.root)
            return
        club = self.model.clubs.get(key,{})
        current_name = self.model.club_label(key)[0]
        name = simpledialog.askstring("Club display name",f"Club: {current_name}\n\nOptionally choose a different display name.\nThis changes Golf Desk only, not your Garmin account.\nLeave blank to restore the Garmin club name.",initialvalue=self.local_labels.get(key,club.get("name","") or current_name),parent=self.root)
        if name is None:
            return
        if name.strip():
            self.local_labels[key] = name.strip()[:60]
        else:
            self.local_labels.pop(key,None)
        try:
            self.data_dir.mkdir(parents=True,exist_ok=True)
            (self.data_dir/"club-labels.json").write_text(json.dumps({"labels":self.local_labels},indent=2),encoding="utf-8")
        except OSError:
            messagebox.showwarning("Label not saved","The local label could not be saved. Check the app’s local-data folder permissions.",parent=self.root)
        self.model.local_labels = dict(self.local_labels)
        self.show_page(self.page)

    def export_table(self, tree, filename):
        path = filedialog.asksaveasfilename(parent=self.root,title="Save comparison",initialfile=filename,defaultextension=".csv",filetypes=[("CSV spreadsheet","*.csv")])
        if not path:
            return
        try:
            with open(path,"w",encoding="utf-8-sig",newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([tree.heading(c,"text") for c in tree["columns"]])
                for iid in tree.get_children():
                    # Avoid spreadsheet-formula interpretation of user club labels.
                    values = [str(v) for v in tree.item(iid,"values")]
                    writer.writerow(["'"+v if v.startswith(("=","+","-","@")) else v for v in values])
            self.status.set("Comparison saved. It contains private golf statistics, not login tokens.")
        except OSError:
            messagebox.showerror("Could not save","Check that the selected folder is writable.",parent=self.root)

    def import_export(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self.root,title="Import a golf export",filetypes=[("Golf Desk JSON export","*.json")])
        if not path:
            return
        try:
            data = read_export(Path(path))
            saved = save_export(data,self.export_dir)
            self.reload_data(preferred=saved)
            self.show_notice("Imported your saved golf data. No sign-in or Garmin account changes were needed.")
        except (OSError,ValueError,KeyError,TypeError):
            messagebox.showerror("Unsupported export","Choose a valid Golf Desk JSON export. Nothing was sent to Garmin.",parent=self.root)

    def open_exports_folder(self):
        self.export_dir.mkdir(parents=True,exist_ok=True)
        os.startfile(self.export_dir)

    def reload_data(self, preferred=None):
        previous=self.model.account_identities
        self.model = load_snapshot(self.export_dir,self.local_labels,preferred)
        if previous!=self.model.account_identities:
            self.history=load_selection(self.data_dir/"round-selection.json",self.model.account_identities)
        self.show_page(self.page)
        self.status.set(f"Loaded {len(self.model.rounds)} scorecards from {len(self.model.sources)} compatible local export(s).")
        self.refresh_session_status()

    def forget_account(self):
        if self.busy:
            messagebox.showinfo("Update in progress","Finish or cancel the current update before forgetting its sign-in.",parent=self.root)
            return
        if not self.store.exists:
            messagebox.showinfo("Nothing saved","This app has no remembered sign-in on this PC.",parent=self.root)
            return
        if messagebox.askyesno("Forget remembered sign-in?","Remove this app’s encrypted session from this PC?\n\nYour golf exports will remain. This does not revoke an already issued token at Garmin.",parent=self.root):
            try:
                self.store.forget()
                self.refresh_session_status()
                self.show_page(self.page)
                self.show_notice("Remembered sign-in removed from this PC. Your saved golf exports were kept.")
            except SessionStoreError as exc:
                messagebox.showerror("Could not forget sign-in",str(exc),parent=self.root)

    def open_sync(self, rounds=None, shots=False, force_fresh=False, email_hint=""):
        if self.busy:
            return
        rounds=self.recommended_import_count(shots) if rounds is None else rounds
        dialog = SyncDialog(self.root,self.store.exists,rounds,shots,email_hint,force_fresh)
        self.root.wait_window(dialog)
        options = dialog.result
        dialog.result = None
        if options:
            self.start_sync(options)

    def start_sync(self, options):
        self.busy = True
        self.cancel = threading.Event()
        self.last_options = {k:v for k,v in options.items() if k != "credentials"}
        self.sync_button.configure(state="disabled")
        self.refresh_history_controls()
        self.progress_frame.pack(fill="x",before=self.scroll,pady=(0,8))
        self.progress_label.configure(text="Preparing a private golf update…")
        self.progress_bar.start(12)
        self.show_notice("")
        def mfa():
            request = {"event":threading.Event(),"code":"","cancelled":False}
            self.events.put(("mfa",request))
            while not request["event"].wait(0.1):
                if self.cancel.is_set():
                    raise SyncCancelled
            code,request["code"] = request["code"],""
            if request["cancelled"] or self.cancel.is_set():
                raise SyncCancelled
            return code
        def work():
            try:
                result = sync_golf(self.export_dir,options["rounds"],options["include_shots"],options.pop("credentials"),options["remember"],mfa,lambda text:self.events.put(("progress",text)),self.cancel,store=self.store)
                self.events.put(("done",result))
            except SignInRequired as exc:
                self.events.put(("signin",exc.email))
            except SyncCancelled:
                self.events.put(("cancelled",None))
            except SyncError as exc:
                self.events.put(("error",str(exc)))
            except Exception:
                self.events.put(("error","The update could not finish. No sensitive error details were logged."))
            finally:
                credentials = options.pop("credentials",None)
                if isinstance(credentials,dict):
                    credentials.clear()
        threading.Thread(target=work,daemon=True,name="GolfDeskSync").start()

    def finish_sync(self):
        self.busy = False
        self.progress_bar.stop()
        self.progress_frame.pack_forget()
        self.sync_button.configure(state="normal")
        self.refresh_history_controls()
        self.refresh_session_status()

    def drain_events(self):
        if self.closed:
            return
        try:
            while True:
                kind,value = self.events.get_nowait()
                if kind == "progress":
                    self.progress_label.configure(text=value)
                elif kind == "mfa":
                    self.mfa_pending = value
                    self.mfa_dialog = MfaDialog(self.root)
                    self.root.wait_window(self.mfa_dialog)
                    if self.closed:
                        return
                    value["code"] = self.mfa_dialog.result or ""
                    value["cancelled"] = self.mfa_dialog.result is None
                    self.mfa_dialog.result = None
                    value["event"].set()
                    self.mfa_dialog = self.mfa_pending = None
                elif kind == "done":
                    self.finish_sync()
                    self.reload_data(preferred=value.path)
                    count = len(value.data.get("golf",{}).get("scorecard_summaries",[]))
                    text = f"Imported {count} round(s). " + ("Sign-in remembered securely on this PC." if value.remembered else "Sign-in was not remembered.")
                    if value.data.get("errors"):
                        text += " Some sections or optional metadata were unavailable; review coverage in the app."
                    if value.warnings:
                        text += " " + " ".join(value.warnings)
                    self.show_notice(text)
                elif kind == "signin":
                    self.finish_sync()
                    self.status.set("Garmin needs a fresh sign-in. Enter it only in the app.")
                    self.open_sync(self.last_options["rounds"],self.last_options["include_shots"],True,value)
                elif kind in ("error","cancelled"):
                    self.finish_sync()
                    self.show_notice(value if kind=="error" else "Update canceled. Existing golf exports were retained.")
        except queue.Empty:
            pass
        if not self.closed:
            self.poll_id = self.root.after(100,self.drain_events)

    def cancel_sync(self):
        self.cancel.set()
        self.progress_label.configure(text="Canceling after the current request…")
        if self.mfa_pending:
            self.mfa_pending["cancelled"] = True
            self.mfa_pending["event"].set()
        if self.mfa_dialog and self.mfa_dialog.winfo_exists():
            self.mfa_dialog.cancel()

    def on_wheel(self, event):
        if isinstance(event.widget,(ttk.Treeview,ttk.Combobox,tk.Entry,ttk.Entry)):
            return
        self.scroll.canvas.yview_scroll(-int(event.delta/120),"units")

    def callback_error(self, _kind, _value, _traceback):
        # Never log arbitrary exception messages or credential-containing locals.
        self.status.set("That action could not finish. Your Garmin records were not changed.")

    def close(self):
        if self.busy and not messagebox.askyesno("Close Golf Desk?","Cancel the update and close? Saved exports and remembered sign-in settings will be kept.",parent=self.root):
            return
        self.closed = True
        self.cancel_sync()
        self.root.after_cancel(self.poll_id)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def math_floor(value, step):
    return int(value//step)*step


def main():
    mutex = None
    if os.name == "nt":
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError,OSError):
            pass
        kernel = ctypes.WinDLL("kernel32",use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p,ctypes.c_int,ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        import hashlib
        name = "Local\\GolfDesk."+hashlib.sha256(str(app_data_dir()).encode()).hexdigest()[:20]
        ctypes.set_last_error(0)
        mutex = kernel.CreateMutexW(None,False,name)
        if ctypes.get_last_error() == 183:
            user = ctypes.windll.user32
            user.FindWindowW.argtypes = [ctypes.c_wchar_p,ctypes.c_wchar_p]
            user.FindWindowW.restype = ctypes.c_void_p
            user.ShowWindow.argtypes = [ctypes.c_void_p,ctypes.c_int]
            user.SetForegroundWindow.argtypes = [ctypes.c_void_p]
            handle = user.FindWindowW(None,TITLE)
            if handle:
                user.ShowWindow(ctypes.c_void_p(handle),9)
                user.SetForegroundWindow(ctypes.c_void_p(handle))
            return
    try:
        GolfApp(initial_page="overview").run()
    finally:
        if mutex:
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(mutex)


if __name__ == "__main__":
    main()
