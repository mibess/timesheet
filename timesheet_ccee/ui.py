from __future__ import annotations

import logging
import platform
import queue
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable

from .config import (
    APP_NAME,
    APP_VERSION,
    AppSettings,
    configure_logging,
    default_workbook_path,
    load_settings,
)
from .database import DatabaseError, TimesheetDatabase
from .models import TimeEntry, WorkbookMetadata
from .sync import SyncOutcome, TimesheetSync
from .system import open_in_default_app, reveal_in_file_manager
from .time_utils import (
    format_br_date,
    format_duration,
    mask_duration_input,
    parse_br_date,
    parse_duration,
)
from .updater import (
    UpdateClient,
    UpdateError,
    UpdateInfo,
    consume_update_status,
    start_update_installer,
)
from .workbook import TimesheetError, TimesheetWorkbook


COLORS = {
    "navy": "#0B1F3A",
    "navy_light": "#17365D",
    "background": "#F3F6FA",
    "card": "#FFFFFF",
    "border": "#DDE5EF",
    "text": "#132238",
    "muted": "#64748B",
    "accent": "#2563EB",
    "accent_dark": "#1D4ED8",
    "accent_soft": "#E8F0FF",
    "green": "#14804A",
    "green_soft": "#E7F6EE",
    "amber": "#B45309",
    "amber_soft": "#FFF5DF",
    "red": "#C2414B",
    "red_soft": "#FDECEE",
    "row_alt": "#F8FAFD",
}

APP_ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "timesheet-ccee-icon.png"


class TimesheetApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.settings: AppSettings = load_settings()
        self.log_path = configure_logging()
        self.database = TimesheetDatabase()
        self.synchronizer = TimesheetSync(self.database)
        self.update_client = UpdateClient(APP_VERSION)
        self.workbook_path = default_workbook_path()
        self.metadata = WorkbookMetadata()
        self._active_workbook_path: str | None = None
        self.dirty = False
        self._cell_editor: tk.Widget | None = None
        self._operation_active = False
        self._operation_results: queue.Queue[tuple[bool, object]] = queue.Queue()
        self._operation_success: Callable[[Any], None] | None = None
        self._operation_error: Callable[[Exception], None] | None = None
        self._busy_widgets: list[ttk.Widget] = []
        self._busy_button: ttk.Widget | None = None
        self._busy_button_text = ""
        self._button_feedback: dict[
            str, tuple[ttk.Button, str, str, str]
        ] = {}
        self._undo_state: tuple[list[TimeEntry], bool, str] | None = None
        self._last_backup_path: Path | None = None
        self._stored_day_has_entries = False

        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1280x820")
        self.minsize(1080, 700)
        self.configure(background=COLORS["background"])
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._configure_icon()
        self._configure_styles()
        self._create_variables()
        self._build_ui()
        self._bind_shortcuts()
        self.after(150, self._startup)

    @property
    def font_family(self) -> str:
        if platform.system() == "Darwin":
            return "SF Pro Text"
        if platform.system() == "Windows":
            return "Segoe UI"
        return "DejaVu Sans"

    def _configure_icon(self) -> None:
        if APP_ICON_PATH.is_file():
            icon = tk.PhotoImage(file=APP_ICON_PATH)
            self.iconphoto(True, icon)
            self._icon = icon
            return

        icon = tk.PhotoImage(width=32, height=32)
        icon.put(COLORS["navy"], to=(0, 0, 32, 32))
        icon.put(COLORS["accent"], to=(5, 5, 27, 27))
        icon.put("#FFFFFF", to=(9, 9, 23, 13))
        icon.put("#FFFFFF", to=(9, 16, 19, 20))
        icon.put("#FFFFFF", to=(9, 23, 15, 26))
        self.iconphoto(True, icon)
        self._icon = icon

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            ".",
            font=(self.font_family, 10),
            foreground=COLORS["text"],
        )
        style.configure(
            "TEntry",
            padding=(10, 8),
            fieldbackground="#FFFFFF",
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
        )
        style.configure(
            "TCombobox",
            padding=(8, 7),
            fieldbackground="#FFFFFF",
            background="#FFFFFF",
            bordercolor=COLORS["border"],
            arrowcolor=COLORS["muted"],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#FFFFFF")],
            selectbackground=[("readonly", "#FFFFFF")],
            selectforeground=[("readonly", COLORS["text"])],
        )
        style.configure(
            "Primary.TButton",
            background=COLORS["accent"],
            foreground="#FFFFFF",
            padding=(18, 10),
            borderwidth=0,
            font=(self.font_family, 10, "bold"),
        )
        style.map(
            "Primary.TButton",
            background=[("active", COLORS["accent_dark"]), ("disabled", "#9CB5E8")],
        )
        style.configure(
            "Success.TButton",
            background=COLORS["green"],
            foreground="#FFFFFF",
            padding=(18, 10),
            borderwidth=0,
            font=(self.font_family, 10, "bold"),
        )
        style.map(
            "Success.TButton",
            background=[("active", COLORS["green"]), ("disabled", "#8AC2A6")],
        )
        for style_name, padding, font in (
            ("SuccessSecondary.TButton", (14, 9), (self.font_family, 10)),
            ("SuccessGhost.TButton", (10, 7), (self.font_family, 9, "bold")),
            ("SuccessDanger.TButton", (12, 8), (self.font_family, 10)),
            ("SuccessFooter.TButton", (8, 4), (self.font_family, 8, "bold")),
        ):
            style.configure(
                style_name,
                background=COLORS["green"],
                foreground="#FFFFFF",
                padding=padding,
                borderwidth=0,
                font=font,
            )
            style.map(
                style_name,
                background=[
                    ("active", COLORS["green"]),
                    ("disabled", "#8AC2A6"),
                ],
            )
        style.configure(
            "Secondary.TButton",
            background="#FFFFFF",
            foreground=COLORS["text"],
            padding=(14, 9),
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
        )
        style.map("Secondary.TButton", background=[("active", "#F1F5F9")])
        style.configure(
            "Ghost.TButton",
            background=COLORS["background"],
            foreground=COLORS["accent_dark"],
            padding=(10, 7),
            borderwidth=0,
            font=(self.font_family, 9, "bold"),
        )
        style.map("Ghost.TButton", background=[("active", COLORS["accent_soft"])])
        style.configure(
            "Danger.TButton",
            background="#FFFFFF",
            foreground=COLORS["red"],
            padding=(12, 8),
            bordercolor="#F3C7CC",
            lightcolor="#F3C7CC",
            darkcolor="#F3C7CC",
        )
        style.map("Danger.TButton", background=[("active", COLORS["red_soft"])])
        style.configure(
            "Treeview",
            background="#FFFFFF",
            fieldbackground="#FFFFFF",
            foreground=COLORS["text"],
            rowheight=36,
            borderwidth=0,
            font=(self.font_family, 10),
        )
        style.configure(
            "Treeview.Heading",
            background="#EDF2F8",
            foreground=COLORS["navy"],
            relief="flat",
            padding=(8, 10),
            font=(self.font_family, 9, "bold"),
        )
        style.map(
            "Treeview",
            background=[("selected", "#DCE8FF")],
            foreground=[("selected", COLORS["navy"])],
        )
        style.map("Treeview.Heading", background=[("active", "#E5ECF5")])
        style.configure(
            "Total.Horizontal.TProgressbar",
            troughcolor="#E2E8F0",
            background=COLORS["accent"],
            borderwidth=0,
            thickness=8,
        )
        style.configure(
            "Busy.Horizontal.TProgressbar",
            troughcolor=COLORS["accent_soft"],
            background=COLORS["accent"],
            borderwidth=0,
            thickness=5,
        )
        style.configure(
            "Footer.TButton",
            background="#E9EEF5",
            foreground=COLORS["accent_dark"],
            padding=(8, 4),
            borderwidth=0,
            font=(self.font_family, 8, "bold"),
        )
        style.map("Footer.TButton", background=[("active", COLORS["accent_soft"])])
        style.configure(
            "Header.TMenubutton",
            background=COLORS["navy_light"],
            foreground="#FFFFFF",
            padding=(12, 8),
            borderwidth=0,
            font=(self.font_family, 9, "bold"),
            arrowcolor="#D8E5F3",
        )
        style.map(
            "Header.TMenubutton",
            background=[("active", COLORS["accent"]), ("disabled", COLORS["navy_light"])],
            foreground=[("disabled", "#8296AE")],
        )

    def _create_variables(self) -> None:
        self.date_var = tk.StringVar(value=format_br_date(date.today()))
        self.hours_var = tk.StringVar(value="07:30")
        self.activity_var = tk.StringVar(value=self.settings.default_activity_type)
        self.ticket_var = tk.StringVar(value=self.settings.default_ticket)
        self.number_var = tk.StringVar()
        self.observation_var = tk.StringVar(value=self.settings.default_observation)
        self.phase_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Pronto para começar")
        self.total_var = tk.StringVar(value="00:00")
        self.summary_var = tk.StringVar(value="0 atividades")
        self.progress_hint_var = tk.StringVar(value="Meta diária: 08:00")

    def _build_ui(self) -> None:
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build_header()

        content = tk.Frame(self, background=COLORS["background"])
        content.grid(row=1, column=0, sticky="nsew", padx=24, pady=(18, 12))
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(2, weight=1)

        self._build_workbook_card(content)
        self._build_entry_card(content)
        self._build_table_card(content)
        self._build_summary_bar(content)
        self._build_status_bar()
        self._update_action_states()
        self._update_table_feedback()

    def _build_header(self) -> None:
        header = tk.Frame(self, background=COLORS["navy"], height=92)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(1, weight=1)

        mark = tk.Frame(header, background=COLORS["accent"], width=50, height=50)
        mark.grid(row=0, column=0, rowspan=2, padx=(25, 16), pady=21)
        mark.grid_propagate(False)
        tk.Label(
            mark,
            text="CC",
            background=COLORS["accent"],
            foreground="#FFFFFF",
            font=(self.font_family, 15, "bold"),
        ).place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(
            header,
            text="Timesheet CCEE",
            background=COLORS["navy"],
            foreground="#FFFFFF",
            font=(self.font_family, 20, "bold"),
        ).grid(row=0, column=1, sticky="sw", pady=(20, 0))
        tk.Label(
            header,
            text="Apontamentos claros, rápidos e sempre protegidos por backup.",
            background=COLORS["navy"],
            foreground="#AFC2DA",
            font=(self.font_family, 10),
        ).grid(row=1, column=1, sticky="nw", pady=(2, 20))

        self.actions_menu_button = ttk.Menubutton(
            header,
            text="Opções",
            style="Header.TMenubutton",
        )
        actions_menu = tk.Menu(self.actions_menu_button, tearoff=False)
        actions_menu.add_command(
            label="Calcular horas",
            command=self._calculate_hours,
        )
        actions_menu.add_separator()
        actions_menu.add_command(
            label="Buscar Atualizações",
            command=self._check_for_updates,
        )
        self.actions_menu_button.configure(menu=actions_menu)
        self.actions_menu_button.grid(row=0, column=2, rowspan=2, padx=(8, 0))
        self._actions_menu = actions_menu

        version = tk.Label(
            header,
            text=f"VERSÃO {APP_VERSION}",
            background=COLORS["navy_light"],
            foreground="#D8E5F3",
            font=(self.font_family, 8, "bold"),
            padx=12,
            pady=6,
        )
        version.grid(row=0, column=3, rowspan=2, padx=25)

    def _card(self, parent: tk.Widget) -> tk.Frame:
        return tk.Frame(
            parent,
            background=COLORS["card"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )

    def _section_label(self, parent: tk.Widget, text: str) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            background=COLORS["card"],
            foreground=COLORS["navy"],
            font=(self.font_family, 11, "bold"),
        )

    def _field_label(self, parent: tk.Widget, text: str) -> tk.Label:
        return tk.Label(
            parent,
            text=text.upper(),
            background=COLORS["card"],
            foreground=COLORS["muted"],
            font=(self.font_family, 8, "bold"),
        )

    def _build_workbook_card(self, parent: tk.Widget) -> None:
        card = self._card(parent)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        card.grid_columnconfigure(0, weight=1)

        date_block = tk.Frame(card, background=COLORS["card"])
        date_block.grid(row=0, column=0, sticky="w", padx=18, pady=14)
        self._field_label(date_block, "Data do apontamento").grid(
            row=0, column=0, columnspan=5, sticky="w", pady=(0, 5)
        )
        self.previous_day_button = ttk.Button(
            date_block,
            text="‹",
            style="Secondary.TButton",
            width=2,
            command=lambda: self._navigate_date(-1),
        )
        self.previous_day_button.grid(row=1, column=0)
        self.date_entry = ttk.Entry(
            date_block, textvariable=self.date_var, width=13, justify="center"
        )
        self.date_entry.grid(row=1, column=1, padx=6)
        self.next_day_button = ttk.Button(
            date_block,
            text="›",
            style="Secondary.TButton",
            width=2,
            command=lambda: self._navigate_date(1),
        )
        self.next_day_button.grid(row=1, column=2)
        self.today_button = ttk.Button(
            date_block,
            text="Hoje",
            style="Ghost.TButton",
            command=self._go_to_today,
        )
        self.today_button.grid(row=1, column=3, padx=(4, 0))
        self.load_button = ttk.Button(
            date_block,
            text="Carregar dia",
            style="Primary.TButton",
            command=self._load_selected_day,
        )
        self.load_button.grid(row=1, column=4, padx=(4, 0))

        actions_block = tk.Frame(card, background=COLORS["card"])
        actions_block.grid(row=0, column=1, sticky="e", padx=18, pady=14)
        self._field_label(actions_block, "Arquivo do timesheet").grid(
            row=0, column=0, columnspan=2, sticky="e", pady=(0, 5)
        )
        self.open_button = ttk.Button(
            actions_block,
            text="Abrir arquivo",
            style="Ghost.TButton",
            command=self._open_workbook,
        )
        self.open_button.grid(row=1, column=0)
        self.sync_button = ttk.Button(
            actions_block,
            text="Sincronizar",
            style="Secondary.TButton",
            command=self._synchronize,
        )
        self.sync_button.grid(row=1, column=1, padx=(4, 0))

    def _build_entry_card(self, parent: tk.Widget) -> None:
        card = self._card(parent)
        card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        for column, weight in enumerate((0, 2, 2, 1, 4, 2, 0)):
            card.grid_columnconfigure(column, weight=weight)

        self._section_label(card, "Nova atividade").grid(
            row=0, column=0, columnspan=4, sticky="w", padx=18, pady=(14, 2)
        )
        tk.Label(
            card,
            text="Preencha os dados ou use um dos atalhos.",
            background=COLORS["card"],
            foreground=COLORS["muted"],
            font=(self.font_family, 9),
        ).grid(row=0, column=4, columnspan=3, sticky="e", padx=18, pady=(14, 2))

        fields = (
            ("Horas · HH:MM", self.hours_var),
            ("Tipo de atividade", self.activity_var),
            ("Ticket", self.ticket_var),
            ("Número", self.number_var),
            ("Observação", self.observation_var),
            ("Fase", self.phase_var),
        )
        for column, (label, _) in enumerate(fields):
            self._field_label(card, label).grid(
                row=1,
                column=column,
                sticky="w",
                padx=(18 if column == 0 else 6, 6),
                pady=(10, 4),
            )

        self.hours_entry = ttk.Entry(card, textvariable=self.hours_var, width=9)
        self.hours_entry.grid(row=2, column=0, sticky="ew", padx=(18, 6))
        self.activity_combo = ttk.Combobox(card, textvariable=self.activity_var)
        self.activity_combo.grid(row=2, column=1, sticky="ew", padx=6)
        self.ticket_combo = ttk.Combobox(card, textvariable=self.ticket_var)
        self.ticket_combo.grid(row=2, column=2, sticky="ew", padx=6)
        self.number_combo = ttk.Combobox(card, textvariable=self.number_var)
        self.number_combo.grid(row=2, column=3, sticky="ew", padx=6)
        self.observation_entry = ttk.Entry(card, textvariable=self.observation_var)
        self.observation_entry.grid(
            row=2, column=4, sticky="ew", padx=6
        )
        self.phase_combo = ttk.Combobox(card, textvariable=self.phase_var)
        self.phase_combo.grid(row=2, column=5, sticky="ew", padx=6)
        self.add_button = ttk.Button(
            card,
            text="+ Adicionar",
            style="Primary.TButton",
            command=self._add_form_entry,
        )
        self.add_button.grid(row=2, column=6, padx=(6, 18))

        shortcuts = tk.Frame(card, background=COLORS["card"])
        shortcuts.grid(
            row=3, column=0, columnspan=7, sticky="ew", padx=18, pady=(12, 14)
        )
        tk.Label(
            shortcuts,
            text="ATALHOS",
            background=COLORS["card"],
            foreground=COLORS["muted"],
            font=(self.font_family, 8, "bold"),
        ).pack(side="left", padx=(0, 8))
        for preset in self.settings.presets:
            preset_button = ttk.Button(
                shortcuts,
                text=f"{preset.name}  ·  {preset.hours}",
                style="Ghost.TButton",
            )
            preset_button.configure(
                command=lambda item=preset, button=preset_button: self._add_preset(
                    item.name, item.hours, button
                )
            )
            preset_button.pack(side="left", padx=2)
        self.import_previous_day_button = ttk.Button(
            shortcuts,
            text="Importar dia Anterior",
            style="Ghost.TButton",
            command=self._import_previous_day,
        )

    def _build_table_card(self, parent: tk.Widget) -> None:
        card = self._card(parent)
        card.grid(row=2, column=0, sticky="nsew", pady=(0, 12))
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)

        heading = tk.Frame(card, background=COLORS["card"])
        heading.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 8))
        heading.grid_columnconfigure(1, weight=1)
        self._section_label(heading, "Atividades do dia").grid(row=0, column=0)
        tk.Label(
            heading,
            textvariable=self.summary_var,
            background=COLORS["accent_soft"],
            foreground=COLORS["accent_dark"],
            font=(self.font_family, 8, "bold"),
            padx=10,
            pady=5,
        ).grid(row=0, column=1, sticky="w", padx=10)
        self.duplicate_button = ttk.Button(
            heading,
            text="Duplicar",
            style="Secondary.TButton",
            command=self._duplicate_selected,
        )
        self.duplicate_button.grid(row=0, column=2, padx=4)
        self.remove_button = ttk.Button(
            heading,
            text="Remover",
            style="Danger.TButton",
            command=self._remove_selected,
        )
        self.remove_button.grid(row=0, column=3, padx=(4, 0))

        table_frame = tk.Frame(card, background=COLORS["card"])
        table_frame.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 14))
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        columns = ("hours", "activity", "ticket", "number", "observation", "phase")
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
        )
        definitions = (
            ("hours", "HORAS", 78, False, "center"),
            ("activity", "TIPO DE ATIVIDADE", 160, True, "w"),
            ("ticket", "TICKET", 120, True, "w"),
            ("number", "NÚMERO", 110, False, "w"),
            ("observation", "OBSERVAÇÃO", 360, True, "w"),
            ("phase", "FASE", 180, True, "w"),
        )
        for name, title, width, stretch, anchor in definitions:
            self.tree.heading(name, text=title)
            self.tree.column(
                name, width=width, minwidth=65, stretch=stretch, anchor=anchor
            )
        self.tree.tag_configure("even", background="#FFFFFF")
        self.tree.tag_configure("odd", background=COLORS["row_alt"])
        self.tree.tag_configure(
            "invalid_hours",
            background=COLORS["red_soft"],
            foreground=COLORS["red"],
        )
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            table_frame, orient="vertical", command=self.tree.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<Double-1>", self._begin_cell_edit)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_action_states())

        self.table_feedback = tk.Frame(
            table_frame,
            background="#FFFFFF",
            highlightbackground=COLORS["border"],
            highlightthickness=1,
            padx=34,
            pady=20,
        )
        self.table_feedback_label = tk.Label(
            self.table_feedback,
            background="#FFFFFF",
            foreground=COLORS["navy"],
            font=(self.font_family, 11, "bold"),
        )
        self.table_feedback_label.pack()
        self.table_feedback_hint = tk.Label(
            self.table_feedback,
            background="#FFFFFF",
            foreground=COLORS["muted"],
            font=(self.font_family, 9),
        )
        self.table_feedback_hint.pack(pady=(4, 0))
        self.table_loader = ttk.Progressbar(
            self.table_feedback,
            style="Busy.Horizontal.TProgressbar",
            mode="indeterminate",
            length=180,
        )

    def _build_summary_bar(self, parent: tk.Widget) -> None:
        bar = self._card(parent)
        bar.grid(row=3, column=0, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)

        total_block = tk.Frame(bar, background=COLORS["card"])
        total_block.grid(row=0, column=0, padx=18, pady=13, sticky="w")
        self._field_label(total_block, "Total do dia").grid(row=0, column=0, sticky="w")
        self.total_label = tk.Label(
            total_block,
            textvariable=self.total_var,
            background=COLORS["card"],
            foreground=COLORS["accent"],
            font=(self.font_family, 19, "bold"),
        )
        self.total_label.grid(row=1, column=0, sticky="w")

        progress_block = tk.Frame(bar, background=COLORS["card"])
        progress_block.grid(row=0, column=1, sticky="ew", padx=24, pady=13)
        progress_block.grid_columnconfigure(0, weight=1)
        tk.Label(
            progress_block,
            textvariable=self.progress_hint_var,
            background=COLORS["card"],
            foreground=COLORS["muted"],
            font=(self.font_family, 9),
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.progress = ttk.Progressbar(
            progress_block,
            style="Total.Horizontal.TProgressbar",
            mode="determinate",
        )
        self.progress.grid(row=1, column=0, sticky="ew")

        self.clear_button = ttk.Button(
            bar,
            text="Limpar",
            style="Danger.TButton",
            command=self._clear_entries,
        )
        self.clear_button.grid(row=0, column=2, padx=(8, 4), pady=18)
        self.save_button = ttk.Button(
            bar,
            text="Salvar no banco",
            style="Primary.TButton",
            command=self._save_day,
        )
        self.save_button.grid(row=0, column=3, padx=(4, 18), pady=18)

    def _build_status_bar(self) -> None:
        footer = tk.Frame(self, background="#E9EEF5", height=34)
        footer.grid(row=2, column=0, sticky="ew")
        footer.grid_propagate(False)
        self.status_dot = tk.Label(
            footer,
            text="●",
            background="#E9EEF5",
            foreground=COLORS["green"],
            font=(self.font_family, 8),
        )
        self.status_dot.pack(side="left", padx=(25, 7))
        self.status_label = tk.Label(
            footer,
            textvariable=self.status_var,
            background="#E9EEF5",
            foreground=COLORS["muted"],
            font=(self.font_family, 9),
        )
        self.status_label.pack(side="left")
        self.footer_loader = ttk.Progressbar(
            footer,
            style="Busy.Horizontal.TProgressbar",
            mode="indeterminate",
            length=68,
        )
        self.footer_hint = tk.Label(
            footer,
            text="Ctrl/⌘+S salva  ·  Ctrl/⌘+Shift+S sincroniza",
            background="#E9EEF5",
            foreground="#8898AA",
            font=(self.font_family, 8),
        )
        self.footer_hint.pack(side="right", padx=25)
        self.backup_button = ttk.Button(
            footer,
            text="Ver backup",
            style="Footer.TButton",
            command=self._reveal_last_backup,
        )
        self.undo_button = ttk.Button(
            footer,
            text="Desfazer",
            style="Footer.TButton",
            command=self._undo_last_action,
        )

    def _bind_shortcuts(self) -> None:
        self.bind_all("<Control-s>", lambda _event: self._save_day())
        self.bind_all("<Command-s>", lambda _event: self._save_day())
        self.bind_all("<Control-Shift-S>", lambda _event: self._synchronize())
        self.bind_all("<Command-Shift-S>", lambda _event: self._synchronize())
        self.bind_all("<Control-Return>", lambda _event: self._add_form_entry())
        self.bind_all("<Command-Return>", lambda _event: self._add_form_entry())
        self.bind_all("<F5>", lambda _event: self._load_selected_day())
        self.tree.bind("<Delete>", lambda _event: self._remove_selected())
        self.tree.bind("<BackSpace>", lambda _event: self._remove_selected())
        self.date_entry.bind("<Return>", lambda _event: self._load_selected_day())

        self.hours_entry.bind("<KeyRelease>", self._mask_time_entry)
        self.hours_entry.bind(
            "<<Paste>>",
            lambda _event: self.after_idle(
                self._mask_time_entry_widget, self.hours_entry
            ),
        )
        self.hours_entry.bind("<FocusOut>", self._normalize_form_hours)

    def _run_async(
        self,
        *,
        message: str,
        button: ttk.Widget,
        button_text: str,
        task: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        if self._operation_active:
            return

        self._reset_button_feedback(button)
        self._operation_active = True
        self._operation_success = on_success
        self._operation_error = on_error
        self._set_busy(True, message, button, button_text)

        def worker() -> None:
            try:
                self._operation_results.put((True, task()))
            except Exception as exc:
                self._operation_results.put((False, exc))

        threading.Thread(target=worker, daemon=True, name="timesheet-operation").start()
        self.after(50, self._poll_async_result)

    def _poll_async_result(self) -> None:
        try:
            succeeded, payload = self._operation_results.get_nowait()
        except queue.Empty:
            if self._operation_active:
                self.after(50, self._poll_async_result)
            return

        success_callback = self._operation_success
        error_callback = self._operation_error
        self._operation_success = None
        self._operation_error = None
        self._set_busy(False)
        try:
            if succeeded and success_callback is not None:
                success_callback(payload)
            elif not succeeded and error_callback is not None:
                error_callback(payload)  # type: ignore[arg-type]
        except Exception as exc:
            logging.error(
                "Falha ao concluir operação na interface",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            self._show_unexpected_error(exc)

    def _interactive_widgets(self) -> list[ttk.Widget]:
        result: list[ttk.Widget] = []

        def visit(parent: tk.Misc) -> None:
            for child in parent.winfo_children():
                if isinstance(
                    child,
                    (
                        ttk.Button,
                        ttk.Entry,
                        ttk.Combobox,
                        ttk.Treeview,
                        ttk.Menubutton,
                    ),
                ):
                    result.append(child)
                visit(child)

        visit(self)
        return result

    def _set_busy(
        self,
        active: bool,
        message: str = "",
        button: ttk.Widget | None = None,
        button_text: str = "",
    ) -> None:
        if active:
            self._set_status(message, "busy")
            self._busy_widgets = []
            for widget in self._interactive_widgets():
                if not widget.instate(["disabled"]):
                    widget.state(["disabled"])
                    self._busy_widgets.append(widget)
            self._busy_button = button
            if button is not None:
                self._busy_button_text = str(button.cget("text"))
                button.configure(text=button_text)
            self.footer_loader.pack(side="left", padx=(10, 0))
            self.footer_loader.start(12)
            self._update_table_feedback(message)
            try:
                self.configure(cursor="watch")
            except tk.TclError:
                pass
            return

        self._operation_active = False
        for widget in self._busy_widgets:
            if widget.winfo_exists():
                widget.state(["!disabled"])
        self._busy_widgets = []
        if self._busy_button is not None and self._busy_button.winfo_exists():
            self._busy_button.configure(text=self._busy_button_text)
        self._busy_button = None
        self.footer_loader.stop()
        self.footer_loader.pack_forget()
        self.table_loader.stop()
        self.configure(cursor="")
        self._update_action_states()
        self._update_table_feedback()

    def _set_status(self, message: str, kind: str = "success") -> None:
        colors = {
            "success": COLORS["green"],
            "busy": COLORS["accent"],
            "warning": COLORS["amber"],
            "error": COLORS["red"],
        }
        self.status_var.set(message)
        self.status_dot.configure(foreground=colors.get(kind, COLORS["green"]))

    def _set_dirty(self, dirty: bool = True) -> None:
        self.dirty = dirty
        suffix = " • alterações não salvas" if dirty else ""
        self.title(f"{APP_NAME} {APP_VERSION}{suffix}")

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        return messagebox.askyesno(
            "Alterações não salvas",
            "Há alterações ainda não salvas. Deseja descartá-las?",
            parent=self,
        )

    def _selected_date(self) -> date:
        return parse_br_date(self.date_var.get())

    def _startup(self) -> None:
        if self.workbook_path.is_file():
            self._activate_selected_workbook()
        else:
            self._set_status("O arquivo do Timesheet CCEE não foi encontrado.", "warning")
        self.hours_entry.focus_set()
        self.hours_entry.selection_range(0, tk.END)
        self.after(400, self._show_update_result)

    def _show_update_result(self) -> None:
        result = consume_update_status()
        if result is None:
            return
        message = str(result.get("message", "")).strip()
        if result.get("success"):
            self._set_status(message or "Aplicativo atualizado com sucesso.")
            messagebox.showinfo(
                "Atualização concluída",
                message or "A atualização foi instalada com sucesso.",
                parent=self,
            )
            return
        self._set_status("Não foi possível instalar a atualização.", "error")
        messagebox.showerror(
            "Atualização não concluída",
            f"{message or 'Não foi possível instalar a atualização.'}\n\n"
            f"Consulte os detalhes em:\n"
            f"{self.log_path.parent / 'update-installer.log'}",
            parent=self,
        )

    def _check_for_updates(self) -> None:
        if self._operation_active:
            return

        def checked(update: UpdateInfo | None) -> None:
            if update is None:
                self._set_status(
                    f"Você já está usando a versão mais recente ({APP_VERSION})."
                )
                messagebox.showinfo(
                    "Nenhuma atualização disponível",
                    f"O {APP_NAME} {APP_VERSION} já é a versão mais recente.",
                    parent=self,
                )
                return
            notes = update.notes[:900]
            details = f"\n\nNovidades:\n{notes}" if notes else ""
            self._set_status(
                f"Versão {update.version} disponível para download.", "busy"
            )
            if messagebox.askyesno(
                "Atualização disponível",
                f"A versão {update.version} está disponível.\n"
                f"Versão instalada: {APP_VERSION}.{details}\n\n"
                "Deseja baixar a atualização agora?",
                parent=self,
            ):
                self._download_update(update)

        self._run_async(
            message="Buscando atualizações…",
            button=self.actions_menu_button,
            button_text="Buscando…",
            task=self.update_client.check,
            on_success=checked,
            on_error=self._handle_update_error,
        )

    def _download_update(self, update: UpdateInfo) -> None:
        def downloaded(archive_path: Path) -> None:
            self._set_status(
                f"Atualização {update.version} baixada com a integridade verificada."
            )
            if messagebox.askyesno(
                "Instalar atualização",
                f"A versão {update.version} foi baixada e validada.\n\n"
                "O aplicativo salvará e sincronizará os dados pendentes, "
                "fechará e abrirá novamente. Deseja instalar agora?",
                parent=self,
            ):
                self._prepare_update_install(archive_path, update)

        self._run_async(
            message=f"Baixando a versão {update.version}…",
            button=self.actions_menu_button,
            button_text="Baixando…",
            task=lambda: self.update_client.download(update),
            on_success=downloaded,
            on_error=self._handle_update_error,
        )

    def _prepare_update_install(self, archive_path: Path, update: UpdateInfo) -> None:
        pending: tuple[date, list[TimeEntry], int] | None = None
        workbook: TimesheetWorkbook | None = None
        try:
            if self._active_workbook_path is not None:
                workbook = self._active_workbook()
                if self.dirty:
                    pending = self._prepared_day_entries()
        except (ValueError, TimesheetError, DatabaseError) as exc:
            if str(exc) != "Salvamento cancelado.":
                self._handle_save_error(exc)
            return

        def prepare() -> None:
            if workbook is None:
                return
            if pending is not None:
                selected_date, entries, _removed_count = pending
                self.database.save_day(workbook.path, selected_date, entries)
            if workbook.path.is_file():
                self.synchronizer.synchronize(workbook)

        def prepared(_result: None) -> None:
            try:
                start_update_installer(archive_path, version=update.version)
            except (OSError, UpdateError) as exc:
                self._handle_update_error(exc)
                return
            self.destroy()

        self._run_async(
            message="Preparando a instalação e protegendo seus dados…",
            button=self.actions_menu_button,
            button_text="Preparando…",
            task=prepare,
            on_success=prepared,
            on_error=self._handle_update_error,
        )

    def _handle_update_error(self, exc: Exception) -> None:
        logging.error(
            "Falha na atualização do aplicativo",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        self._set_status("Não foi possível concluir a atualização.", "error")
        message = (
            str(exc)
            if isinstance(exc, (UpdateError, TimesheetError, DatabaseError))
            else f"Ocorreu um erro inesperado. Consulte o log em:\n{self.log_path}"
        )
        messagebox.showerror(
            "Não foi possível atualizar",
            message,
            parent=self,
        )

    def _open_workbook(self) -> None:
        path = self.workbook_path
        if not path.is_file():
            messagebox.showwarning(
                "Planilha não encontrada",
                "O arquivo fixo do Timesheet CCEE não foi encontrado.",
                parent=self,
            )
            return
        try:
            open_in_default_app(path)
            self._show_action_confirmation(self.open_button, "✓ Aberto")
            self._set_status("Planilha aberta no aplicativo padrão.")
        except Exception as exc:
            logging.exception("Falha ao abrir a planilha")
            messagebox.showerror("Não foi possível abrir", str(exc), parent=self)

    def _navigate_date(self, days: int) -> None:
        if not self._confirm_discard():
            return
        try:
            selected = self._selected_date() + timedelta(days=days)
        except ValueError as exc:
            messagebox.showwarning("Data inválida", str(exc), parent=self)
            return
        self.date_var.set(format_br_date(selected))
        self._load_selected_day(skip_confirm=True)

    def _go_to_today(self) -> None:
        if not self._confirm_discard():
            return
        self.date_var.set(format_br_date(date.today()))
        self._load_selected_day(skip_confirm=True)

    def _load_selected_day(self, *, skip_confirm: bool = False) -> None:
        if self._operation_active:
            return
        if not skip_confirm and not self._confirm_discard():
            return
        try:
            selected_date = self._selected_date()
            workbook = TimesheetWorkbook(self.workbook_path)
        except (ValueError, TimesheetError) as exc:
            self._handle_load_error(exc)
            return

        if (
            self._active_workbook_path != str(workbook.path)
            or not self.database.contains(workbook.path)
        ):
            self._activate_selected_workbook()
            return

        try:
            metadata = self.database.load_metadata(workbook.path)
            entries = self.database.load_day(workbook.path, selected_date)
        except DatabaseError as exc:
            self._handle_load_error(exc)
            return
        self._show_loaded_day(workbook, selected_date, metadata, entries)

    def _activate_selected_workbook(self) -> None:
        if self._operation_active:
            return
        try:
            selected_date = self._selected_date()
            workbook = TimesheetWorkbook(self.workbook_path)
        except (ValueError, TimesheetError) as exc:
            self._handle_load_error(exc)
            return

        def activate() -> tuple[
            SyncOutcome, WorkbookMetadata, list[TimeEntry], Exception | None
        ]:
            sync_error: Exception | None = None
            try:
                outcome = self.synchronizer.activate(workbook)
            except Exception as exc:
                if not self.database.contains(workbook.path):
                    raise
                sync_error = exc
                outcome = SyncOutcome(
                    imported=False,
                    synchronized=False,
                    record_count=0,
                )
            metadata = self.database.load_metadata(workbook.path)
            entries = self.database.load_day(workbook.path, selected_date)
            return outcome, metadata, entries, sync_error

        def activated(
            payload: tuple[
                SyncOutcome, WorkbookMetadata, list[TimeEntry], Exception | None
            ]
        ) -> None:
            outcome, metadata, entries, sync_error = payload
            self._active_workbook_path = str(workbook.path)
            self._show_loaded_day(workbook, selected_date, metadata, entries)
            self._remember_sync_backup(outcome)
            if sync_error is not None:
                logging.error(
                    "Falha ao sincronizar na abertura",
                    exc_info=(
                        type(sync_error),
                        sync_error,
                        sync_error.__traceback__,
                    ),
                )
                self._set_status(
                    "Dados locais carregados; a planilha não pôde ser sincronizada.",
                    "warning",
                )
                messagebox.showwarning(
                    "Sincronização pendente",
                    f"Os dados locais estão disponíveis, mas a planilha não pôde ser "
                    f"atualizada agora.\n\n{sync_error}",
                    parent=self,
                )
            elif outcome.imported:
                self._set_status(
                    f"Planilha importada para o banco local · "
                    f"{outcome.record_count} registro(s)."
                )
            elif outcome.synchronized:
                self._set_status(
                    f"Banco local e planilha sincronizados · "
                    f"{outcome.record_count} registro(s)."
                )

        self._run_async(
            message="Preparando banco local e sincronizando…",
            button=self.load_button,
            button_text="Carregando…",
            task=activate,
            on_success=activated,
            on_error=self._handle_load_error,
        )

    def _show_loaded_day(
        self,
        workbook: TimesheetWorkbook,
        selected_date: date,
        metadata: WorkbookMetadata,
        entries: list[TimeEntry],
    ) -> None:
        self.metadata = metadata
        self._populate_combos()
        self._stored_day_has_entries = bool(entries)
        self._replace_entries(entries)
        self._set_dirty(False)
        self._clear_undo()
        self._show_action_confirmation(self.load_button, "✓ Carregado")
        zero_count = sum(
            1
            for entry in entries
            if parse_duration(entry.hours, allow_zero=True) == 0
        )
        if zero_count:
            self._set_status(
                f"{len(entries)} atividade(s) carregada(s); {zero_count} com 00:00. "
                "Edite as horas antes de salvar.",
                "warning",
            )
        elif entries:
            self._set_status(
                f"{len(entries)} atividade(s) carregada(s) do banco local para "
                f"{format_br_date(selected_date)}."
            )
        else:
            self._set_status(
                f"Nenhuma atividade registrada em {format_br_date(selected_date)}.",
                "warning",
            )

    def _handle_load_error(self, exc: Exception) -> None:
        logging.error(
            "Falha ao carregar o dia",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        if isinstance(exc, (ValueError, TimesheetError, DatabaseError)):
            self._set_status("Não foi possível carregar os dados.", "error")
            messagebox.showerror("Não foi possível carregar", str(exc), parent=self)
        else:
            self._show_unexpected_error(exc)

    def _populate_combos(self) -> None:
        self.activity_combo.configure(values=self.metadata.activity_types)
        self.ticket_combo.configure(values=self.metadata.ticket_types)
        self.number_combo.configure(values=self.metadata.recent_numbers)
        self.phase_combo.configure(values=("", *self.metadata.phases))

    def _replace_entries(self, entries: list[TimeEntry]) -> None:
        self.tree.delete(*self.tree.get_children())
        for entry in entries:
            self.tree.insert("", "end", values=entry.as_row())
        self._refresh_rows()

    def _add_form_entry(self) -> None:
        if self._operation_active:
            return
        try:
            minutes = parse_duration(self.hours_var.get())
        except ValueError as exc:
            messagebox.showwarning("Horas inválidas", str(exc), parent=self)
            self.hours_entry.focus_set()
            self.hours_entry.selection_range(0, tk.END)
            return
        if not self.activity_var.get().strip():
            messagebox.showwarning(
                "Campo obrigatório", "Informe o Tipo de Atividade.", parent=self
            )
            self.activity_combo.focus_set()
            return
        if not self.ticket_var.get().strip():
            messagebox.showwarning(
                "Campo obrigatório", "Informe o Ticket.", parent=self
            )
            self.ticket_combo.focus_set()
            return

        entry = TimeEntry(
            hours=format_duration(minutes),
            activity_type=self.activity_var.get().strip(),
            ticket=self.ticket_var.get().strip(),
            number=self.number_var.get().strip(),
            observation=self.observation_var.get().strip(),
            phase=self.phase_var.get().strip(),
        )
        item = self.tree.insert("", "end", values=entry.as_row())
        self.tree.selection_set(item)
        self.tree.see(item)
        self.number_var.set("")
        self._clear_undo()
        self._set_dirty()
        self._refresh_rows()
        self.hours_entry.focus_set()
        self.hours_entry.selection_range(0, tk.END)
        self._show_action_confirmation(self.add_button, "✓ Adicionado")
        self._set_status("Atividade adicionada. Salve para confirmar no banco.", "busy")

    def _mask_time_entry(self, event: tk.Event) -> None:
        self._mask_time_entry_widget(event.widget)

    @staticmethod
    def _mask_time_entry_widget(entry: ttk.Entry) -> None:
        current = entry.get()
        masked = mask_duration_input(current)
        if current == masked:
            return
        entry.delete(0, tk.END)
        entry.insert(0, masked)
        entry.icursor(tk.END)

    def _normalize_form_hours(self, _event: tk.Event | None = None) -> None:
        text = self.hours_var.get().strip()
        if not text:
            return
        try:
            self.hours_var.set(
                format_duration(parse_duration(text, allow_zero=True))
            )
        except ValueError:
            # A mensagem completa será mostrada ao tentar adicionar a atividade.
            pass

    def _add_preset(
        self, name: str, hours: str, button: ttk.Button | None = None
    ) -> None:
        entry = TimeEntry(hours, "ADM", "Reuniões", "", name, "")
        item = self.tree.insert("", "end", values=entry.as_row())
        self.tree.selection_set(item)
        self.tree.see(item)
        self._clear_undo()
        self._set_dirty()
        self._refresh_rows()
        if button is not None:
            self._show_action_confirmation(button, "✓ Adicionado")
        self._set_status(f"Atalho “{name}” adicionado.", "busy")

    def _import_previous_day(self) -> None:
        if self._operation_active:
            return
        if self.tree.get_children() or self._stored_day_has_entries:
            self._update_import_previous_day_visibility()
            return
        try:
            workbook = self._active_workbook()
            selected_date = self._selected_date()
            if self.database.load_day(workbook.path, selected_date):
                self._stored_day_has_entries = True
                self._update_import_previous_day_visibility()
                return
            previous_day = self.database.load_latest_day_before(
                workbook.path, selected_date
            )
        except (ValueError, TimesheetError, DatabaseError) as exc:
            self._handle_load_error(exc)
            return

        if previous_day is None:
            self._set_status(
                "Não há um dia anterior com atividades para importar.", "warning"
            )
            return

        source_date, entries = previous_day
        self._remember_undo("importação do dia anterior")
        self._replace_entries(entries)
        self._set_dirty()
        self._set_status(
            f"{len(entries)} atividade(s) importada(s) de "
            f"{format_br_date(source_date)}. Revise e salve para confirmar.",
            "busy",
        )

    def _remove_selected(self) -> None:
        if self._operation_active:
            return
        selected = self.tree.selection()
        if not selected:
            self._set_status("Selecione uma ou mais atividades para remover.", "warning")
            return
        self._remember_undo("remoção")
        for item in selected:
            self.tree.delete(item)
        self._set_dirty()
        self._refresh_rows()
        self._show_action_confirmation(self.remove_button, "✓ Removido")
        self._set_status(f"{len(selected)} atividade(s) removida(s).", "busy")

    def _duplicate_selected(self) -> None:
        if self._operation_active:
            return
        selected = self.tree.selection()
        if not selected:
            self._set_status("Selecione uma atividade para duplicar.", "warning")
            return
        self._clear_undo()
        new_items = []
        for item in selected:
            new_items.append(self.tree.insert("", "end", values=self.tree.item(item, "values")))
        self.tree.selection_set(new_items)
        self.tree.see(new_items[-1])
        self._set_dirty()
        self._refresh_rows()
        self._show_action_confirmation(self.duplicate_button, "✓ Duplicado")
        self._set_status(f"{len(new_items)} atividade(s) duplicada(s).", "busy")

    def _clear_entries(self) -> None:
        if self._operation_active:
            return
        children = self.tree.get_children()
        if not children:
            return
        if messagebox.askyesno(
            "Limpar atividades",
            "Remover todas as atividades exibidas?",
            parent=self,
        ):
            self._remember_undo("limpeza")
            self.tree.delete(*children)
            self._set_dirty()
            self._refresh_rows()
            self._show_action_confirmation(self.clear_button, "✓ Limpo")
            self._set_status("Todas as atividades foram removidas.", "warning")

    def _begin_cell_edit(self, event: tk.Event) -> None:
        if self._operation_active:
            return
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        item = self.tree.identify_row(event.y)
        column_id = self.tree.identify_column(event.x)
        if not item or not column_id:
            return
        column_index = int(column_id[1:]) - 1
        columns = self.tree.cget("columns")
        column_name = columns[column_index]
        bbox = self.tree.bbox(item, column_id)
        if not bbox:
            return
        x, y, width, height = bbox
        value = self.tree.set(item, column_name)

        if self._cell_editor is not None:
            self._cell_editor.destroy()
        editor = ttk.Entry(self.tree)
        editor.insert(0, value)
        editor.select_range(0, tk.END)
        editor.place(x=x, y=y, width=width, height=height)
        editor.focus_set()
        if column_name == "hours":
            editor.bind("<KeyRelease>", self._mask_time_entry)
            editor.bind(
                "<<Paste>>",
                lambda _event: self.after_idle(self._mask_time_entry_widget, editor),
            )
        self._cell_editor = editor
        finished = False

        def close(*, save: bool) -> None:
            nonlocal finished
            if finished:
                return
            finished = True
            new_value = editor.get().strip()
            if save and column_name == "hours":
                try:
                    new_value = format_duration(parse_duration(new_value, allow_zero=True))
                except ValueError as exc:
                    messagebox.showwarning("Horas inválidas", str(exc), parent=self)
                    save = False
            if save and new_value != value:
                self.tree.set(item, column_name, new_value)
                self._clear_undo()
                self._set_dirty()
                self._refresh_rows()
                self._set_status("Atividade editada. Salve para confirmar.", "busy")
            editor.destroy()
            self._cell_editor = None

        editor.bind("<Return>", lambda _event: close(save=True))
        editor.bind("<Escape>", lambda _event: close(save=False))
        editor.bind("<FocusOut>", lambda _event: close(save=True))

    def _collect_entries(self) -> list[TimeEntry]:
        entries: list[TimeEntry] = []
        for item in self.tree.get_children():
            values = list(self.tree.item(item, "values"))
            values.extend([""] * (6 - len(values)))
            entries.append(TimeEntry(*[str(value) for value in values[:6]]))
        return entries

    def _calculate_hours(self) -> None:
        if self._operation_active:
            return
        try:
            workbook = self._active_workbook()
            total_minutes, activity_count = self.database.calculate_worked_hours(
                workbook.path
            )
            includes_unsaved_changes = False
            if self.dirty:
                selected_date = self._selected_date()
                stored_entries = self.database.load_day(workbook.path, selected_date)
                current_entries = self._collect_entries()
                stored_minutes = sum(
                    parse_duration(entry.hours, allow_zero=True)
                    for entry in stored_entries
                )
                current_minutes = sum(
                    parse_duration(entry.hours, allow_zero=True)
                    for entry in current_entries
                )
                total_minutes += current_minutes - stored_minutes
                activity_count += len(current_entries) - len(stored_entries)
                includes_unsaved_changes = True
        except (ValueError, TimesheetError, DatabaseError) as exc:
            self._set_status("Não foi possível calcular as horas.", "error")
            messagebox.showerror(
                "Não foi possível calcular as horas",
                str(exc),
                parent=self,
            )
            return

        activity_text = (
            "1 atividade" if activity_count == 1 else f"{activity_count} atividades"
        )
        unsaved_note = (
            "\n\nAs alterações ainda não salvas do dia aberto foram incluídas."
            if includes_unsaved_changes
            else ""
        )
        messagebox.showinfo(
            "Total de horas trabalhadas",
            f"Total: {format_duration(total_minutes)}\n"
            f"Apontamentos considerados: {activity_text}{unsaved_note}",
            parent=self,
        )
        self._set_status(
            f"Total calculado: {format_duration(total_minutes)} em {activity_text}."
        )

    def _prepared_day_entries(self) -> tuple[date, list[TimeEntry], int]:
        selected_date = self._selected_date()
        entries = self._collect_entries()
        zero_indexes: list[int] = []
        for index, entry in enumerate(entries, start=1):
            try:
                minutes = parse_duration(entry.hours, allow_zero=True)
            except ValueError as exc:
                raise TimesheetError(f"Linha {index}: {exc}") from exc
            if minutes == 0:
                zero_indexes.append(index - 1)
            if not entry.activity_type.strip():
                raise TimesheetError(
                    f"Informe o Tipo de Atividade na linha {index}."
                )
            if not entry.ticket.strip():
                raise TimesheetError(f"Informe o Ticket na linha {index}.")

        removed_zero_count = len(zero_indexes)
        if removed_zero_count:
            children = self.tree.get_children()
            invalid_items = [children[index] for index in zero_indexes]
            self.tree.selection_set(invalid_items)
            self.tree.see(invalid_items[0])
            if not messagebox.askyesno(
                "Atividades com 00:00",
                f"{removed_zero_count} atividade(s) estão com 00:00 e não podem "
                "ser apontadas.\n\nDeseja removê-las e salvar o restante do dia?",
                parent=self,
            ):
                self._set_status(
                    "Edite ou remova as atividades destacadas em vermelho.",
                    "warning",
                )
                raise TimesheetError("Salvamento cancelado.")
            zero_index_set = set(zero_indexes)
            entries = [
                entry
                for index, entry in enumerate(entries)
                if index not in zero_index_set
            ]
        return selected_date, entries, removed_zero_count

    def _active_workbook(self) -> TimesheetWorkbook:
        workbook = TimesheetWorkbook(self.workbook_path)
        if (
            self._active_workbook_path != str(workbook.path)
            or not self.database.contains(workbook.path)
        ):
            raise TimesheetError(
                "Carregue a planilha antes de salvar ou sincronizar os dados."
            )
        return workbook

    def _save_day(self) -> None:
        if self._operation_active:
            return
        try:
            workbook = self._active_workbook()
            selected_date, entries, removed_zero_count = self._prepared_day_entries()
            self.database.save_day(workbook.path, selected_date, entries)
        except (ValueError, TimesheetError, DatabaseError) as exc:
            if str(exc) == "Salvamento cancelado.":
                return
            self._handle_save_error(exc)
            return

        if removed_zero_count:
            self._replace_entries(entries)
        self.metadata = self.database.load_metadata(workbook.path)
        self._populate_combos()
        self._stored_day_has_entries = bool(entries)
        self._update_import_previous_day_visibility()
        self._set_dirty(False)
        self._clear_undo()
        self._show_action_confirmation(self.save_button, "✓ Salvo")
        self._set_status(
            f"Salvo no banco local às {datetime.now().strftime('%H:%M:%S')} · "
            f"dia {format_br_date(selected_date)} · sincronização pendente."
        )

    def _reset_button_feedback(self, button: ttk.Button) -> None:
        state = self._button_feedback.pop(str(button), None)
        if state is None:
            return
        target, after_id, original_text, original_style = state
        try:
            self.after_cancel(after_id)
        except tk.TclError:
            pass
        if target.winfo_exists():
            target.configure(text=original_text, style=original_style)

    def _show_action_confirmation(
        self, button: ttk.Button, confirmation_text: str
    ) -> None:
        self._reset_button_feedback(button)
        original_text = str(button.cget("text"))
        original_style = str(button.cget("style"))
        success_style = {
            "Secondary.TButton": "SuccessSecondary.TButton",
            "Ghost.TButton": "SuccessGhost.TButton",
            "Danger.TButton": "SuccessDanger.TButton",
            "Footer.TButton": "SuccessFooter.TButton",
        }.get(original_style, "Success.TButton")
        button.configure(text=confirmation_text, style=success_style)
        key = str(button)

        def restore() -> None:
            state = self._button_feedback.pop(key, None)
            if state is None:
                return
            target, _after_id, text, style = state
            if target.winfo_exists():
                target.configure(text=text, style=style)

        after_id = self.after(2200, restore)
        self._button_feedback[key] = (
            button,
            after_id,
            original_text,
            original_style,
        )

    def _synchronize(self) -> None:
        self._synchronize_workbook(close_after=False, save_pending=True)

    def _synchronize_workbook(
        self, *, close_after: bool, save_pending: bool
    ) -> None:
        if self._operation_active:
            return
        try:
            workbook = self._active_workbook()
            pending: tuple[date, list[TimeEntry], int] | None = None
            if self.dirty and save_pending:
                pending = self._prepared_day_entries()
        except (ValueError, TimesheetError, DatabaseError) as exc:
            if str(exc) == "Salvamento cancelado.":
                return
            self._handle_save_error(exc)
            return

        pending_saved = False

        def synchronize() -> tuple[SyncOutcome, bool]:
            nonlocal pending_saved
            saved_pending = pending is not None
            if pending is not None:
                selected_date, entries, _removed_count = pending
                self.database.save_day(workbook.path, selected_date, entries)
                pending_saved = True
            return self.synchronizer.synchronize(workbook), saved_pending

        def synchronized(payload: tuple[SyncOutcome, bool]) -> None:
            outcome, saved_pending = payload
            if pending is not None and saved_pending:
                _selected_date, entries, removed_count = pending
                if removed_count:
                    self._replace_entries(entries)
                self._stored_day_has_entries = bool(entries)
                self._update_import_previous_day_visibility()
                self._set_dirty(False)
                self._clear_undo()
            self._remember_sync_backup(outcome)
            if close_after:
                self.destroy()
                return
            if outcome.synchronized:
                self._show_action_confirmation(
                    self.sync_button, "✓ Sincronizado"
                )
                self._set_status(
                    f"Planilha sincronizada com o banco local · "
                    f"{outcome.record_count} registro(s)."
                )
            else:
                self._show_action_confirmation(self.sync_button, "✓ Em dia")
                self._set_status("Banco local e planilha já estavam sincronizados.")

        def synchronization_failed(exc: Exception) -> None:
            if close_after and (pending is None or pending_saved):
                logging.error(
                    "Falha ao sincronizar antes de fechar",
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
                self._set_status(
                    "Dados protegidos no banco; sincronização pendente.", "warning"
                )
                if messagebox.askyesno(
                    "Sincronização pendente",
                    f"Os dados estão protegidos no banco local, mas a planilha não "
                    f"pôde ser atualizada.\n\n{exc}\n\nDeseja fechar mesmo assim?",
                    parent=self,
                ):
                    self.destroy()
                return
            self._handle_sync_error(exc)

        self._run_async(
            message=(
                "Salvando e sincronizando antes de fechar…"
                if close_after and pending is not None
                else "Sincronizando banco local e planilha…"
            ),
            button=self.sync_button,
            button_text="Sincronizando…",
            task=synchronize,
            on_success=synchronized,
            on_error=synchronization_failed,
        )

    def _remember_sync_backup(self, outcome: SyncOutcome) -> None:
        if not outcome.backup_path:
            return
        self._last_backup_path = Path(outcome.backup_path)
        if not self.backup_button.winfo_manager():
            self.backup_button.pack(side="right", padx=(4, 0))

    def _handle_sync_error(self, exc: Exception) -> None:
        logging.error(
            "Falha ao sincronizar a planilha",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        if isinstance(exc, (ValueError, TimesheetError, DatabaseError)):
            self._set_status("Não foi possível sincronizar a planilha.", "error")
            messagebox.showerror(
                "Não foi possível sincronizar", str(exc), parent=self
            )
        else:
            self._show_unexpected_error(exc)

    def _handle_save_error(self, exc: Exception) -> None:
        logging.error(
            "Falha ao salvar o dia",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        if isinstance(exc, (ValueError, TimesheetError, DatabaseError)):
            self._set_status("Não foi possível salvar no banco local.", "error")
            messagebox.showerror("Não foi possível salvar", str(exc), parent=self)
        else:
            self._show_unexpected_error(exc)

    def _remember_undo(self, action: str) -> None:
        self._undo_state = (self._collect_entries(), self.dirty, action)
        if not self.undo_button.winfo_manager():
            self.undo_button.pack(side="right", padx=(4, 0))

    def _clear_undo(self) -> None:
        self._undo_state = None
        self.undo_button.pack_forget()

    def _undo_last_action(self) -> None:
        if self._operation_active or self._undo_state is None:
            return
        entries, was_dirty, action = self._undo_state
        self._replace_entries(entries)
        self._set_dirty(was_dirty)
        self._undo_state = None
        self._show_action_confirmation(self.undo_button, "✓ Desfeito")

        def hide_completed_undo() -> None:
            if self._undo_state is None and self.undo_button.winfo_exists():
                self.undo_button.pack_forget()

        self.after(2250, hide_completed_undo)
        self._set_status(f"{action.capitalize()} desfeita.")

    def _reveal_last_backup(self) -> None:
        if self._last_backup_path is None:
            return
        try:
            reveal_in_file_manager(self._last_backup_path)
            self._show_action_confirmation(self.backup_button, "✓ Exibido")
            self._set_status("Backup exibido no gerenciador de arquivos.")
        except Exception as exc:
            logging.error(
                "Falha ao mostrar o backup",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            messagebox.showerror("Não foi possível mostrar o backup", str(exc), parent=self)

    def _refresh_rows(self) -> None:
        total_minutes = 0
        zero_count = 0
        children = self.tree.get_children()
        for index, item in enumerate(children):
            try:
                minutes = parse_duration(
                    self.tree.set(item, "hours"), allow_zero=True
                )
                total_minutes += minutes
                if minutes == 0:
                    zero_count += 1
                    self.tree.item(item, tags=("invalid_hours",))
                else:
                    self.tree.item(
                        item, tags=(("even" if index % 2 == 0 else "odd"),)
                    )
            except ValueError:
                zero_count += 1
                self.tree.item(item, tags=("invalid_hours",))

        count = len(children)
        self.total_var.set(format_duration(total_minutes))
        count_text = f"{count} atividade" if count == 1 else f"{count} atividades"
        if zero_count:
            count_text += f" · {zero_count} com 00:00"
        self.summary_var.set(count_text)
        try:
            expected = parse_duration(
                self.settings.expected_daily_hours, allow_zero=True
            )
        except ValueError:
            expected = 480

        self.progress.configure(maximum=max(expected, 1), value=min(total_minutes, expected))
        style = ttk.Style(self)
        if total_minutes == expected:
            color = COLORS["green"]
            hint = f"Meta diária atingida: {format_duration(expected)}"
        elif total_minutes > expected:
            color = COLORS["amber"]
            hint = (
                f"{format_duration(total_minutes - expected)} acima da meta de "
                f"{format_duration(expected)}"
            )
        else:
            color = COLORS["accent"]
            hint = (
                f"Faltam {format_duration(expected - total_minutes)} para a meta de "
                f"{format_duration(expected)}"
            )
        self.total_label.configure(foreground=color)
        style.configure("Total.Horizontal.TProgressbar", background=color)
        self.progress_hint_var.set(hint)
        self._update_action_states()
        self._update_table_feedback()

    def _update_action_states(self) -> None:
        if not hasattr(self, "tree") or self._operation_active:
            return
        has_selection = bool(self.tree.selection())
        has_entries = bool(self.tree.get_children())
        for button in (self.duplicate_button, self.remove_button):
            button.state(["!disabled"] if has_selection else ["disabled"])
        self.clear_button.state(["!disabled"] if has_entries else ["disabled"])
        self._update_import_previous_day_visibility()

    def _update_import_previous_day_visibility(self) -> None:
        if not hasattr(self, "import_previous_day_button"):
            return
        should_show = (
            self._active_workbook_path is not None
            and not self._stored_day_has_entries
            and not self.tree.get_children()
        )
        is_visible = bool(self.import_previous_day_button.winfo_manager())
        if should_show and not is_visible:
            self.import_previous_day_button.pack(side="left", padx=(10, 2))
        elif not should_show and is_visible:
            self.import_previous_day_button.pack_forget()

    def _update_table_feedback(self, busy_message: str = "") -> None:
        if not hasattr(self, "table_feedback"):
            return
        if self._operation_active:
            self.table_feedback_label.configure(text=busy_message)
            self.table_feedback_hint.configure(
                text="Você pode continuar assim que a operação terminar."
            )
            if not self.table_loader.winfo_manager():
                self.table_loader.pack(pady=(12, 0), fill="x")
            self.table_loader.start(12)
            self.table_feedback.place(relx=0.5, rely=0.5, anchor="center")
            self.table_feedback.lift()
        elif not self.tree.get_children():
            self.table_loader.stop()
            self.table_loader.pack_forget()
            self.table_feedback_label.configure(text="Nenhuma atividade neste dia")
            self.table_feedback_hint.configure(
                text="Use o formulário ou um dos atalhos acima para começar."
            )
            self.table_feedback.place(relx=0.5, rely=0.5, anchor="center")
            self.table_feedback.lift()
        else:
            self.table_loader.stop()
            self.table_loader.pack_forget()
            self.table_feedback.place_forget()

    def _show_unexpected_error(self, exc: Exception) -> None:
        self._set_status("Ocorreu um erro inesperado.", "error")
        messagebox.showerror(
            "Erro inesperado",
            f"{exc}\n\nOs detalhes foram gravados em:\n{self.log_path}",
            parent=self,
        )

    def _on_close(self) -> None:
        if self._operation_active:
            messagebox.showinfo(
                "Operação em andamento",
                "Aguarde o carregamento ou salvamento terminar antes de fechar.",
                parent=self,
            )
            return
        if self._active_workbook_path is None:
            if self._confirm_discard():
                self.destroy()
            return

        save_pending = True
        if self.dirty:
            choice = messagebox.askyesnocancel(
                "Salvar antes de fechar",
                "Há alterações ainda não salvas. Deseja salvá-las no banco local "
                "antes de sincronizar e fechar?",
                parent=self,
            )
            if choice is None:
                return
            save_pending = choice

        if not Path(self._active_workbook_path).is_file():
            if messagebox.askyesno(
                "Planilha não encontrada",
                "A planilha não foi encontrada e não pode ser sincronizada. "
                "Deseja fechar mesmo assim? Os dados continuam protegidos no banco local.",
                parent=self,
            ):
                self.destroy()
            return

        self._synchronize_workbook(
            close_after=True,
            save_pending=save_pending,
        )


def main() -> None:
    if platform.system() == "Windows":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    app = TimesheetApp()
    app.mainloop()
