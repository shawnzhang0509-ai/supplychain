import pandas as pd
import os
import json
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import ImageGrab

# ========== 中文字体修复 ==========
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

CONFIG_FILE = "inventory_config.json"
CONTAINER_THRESHOLD = 69.0

COL_MAP = {
    "SKU": "Sku", "Name": "Name", "ProductFamily": "ProductFamily",
    "地区": "Region", "在库库存": "在库库存", "在途库存": "在途库存",
    "总量库存": "总量库存", "8-30天": "需求_8_30天", "15天": "需求_15天", "30天": "需求_30天",
    "采用需求": "日均需求", "需求来源": "需求来源", "LT预估": "LT预估", "物流预估": "物流预估",
    "决策建议": "决策建议", "建议订货量": "建议订货量", "体积系数": "PriceRadarVolume",
    "备货体积": "备货体积", "催发货体积": "催发货体积", "详细说明": "详细说明"
}
SORT_OPTIONS = ["（无）"] + list(COL_MAP.keys())

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

UI_FONT = ("Microsoft YaHei UI", 10)
UI_FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")
UI_TITLE_FONT = ("Microsoft YaHei UI", 18, "bold")
UI_MONO_FONT = ("Consolas", 10)

class InventoryDecisionSystem:
    def __init__(self, root):
        self.root = root
        self.root.title("智能库存决策系统 V4.8")
        self.root.geometry("1620x920")
        self.root.minsize(1200, 720)
        self.root.configure(bg="#FFFFFF")

        base_dir = get_base_dir()
        self.default_data_dir = os.path.join(base_dir, "data")
        self.default_output_dir = os.path.join(base_dir, "output")
        os.makedirs(self.default_output_dir, exist_ok=True)

        self.data_dir = tk.StringVar()
        self.channel = tk.StringVar()
        self.filter_region = tk.StringVar(value="全部")
        self.filter_decision = tk.StringVar(value="全部")
        self.filter_family = tk.StringVar(value="全部")
        self.sort_primary_var = tk.StringVar(value="（无）")
        self.sort_secondary_var = tk.StringVar(value="（无）")

        self.sort_primary = None
        self.sort_secondary = None
        self.sort_primary_asc = True
        self.sort_secondary_asc = True
        self.shift_pressed = False

        self.result_data = None
        self.family_list = ["全部"]

        self.auto_scanning = False
        self.scan_job_id = None

        self.load_config()

        current_dir = self.data_dir.get()
        if current_dir and os.path.exists(current_dir):
            is_valid_data = False
            try:
                for item in os.listdir(current_dir):
                    item_path = os.path.join(current_dir, item)
                    if os.path.isdir(item_path) and os.path.exists(os.path.join(item_path, "stock.csv")):
                        is_valid_data = True
                        break
            except Exception:
                pass
            if not is_valid_data and os.path.exists(self.default_data_dir):
                self.data_dir.set(self.default_data_dir)
                self.save_config()
        else:
            if os.path.exists(self.default_data_dir):
                self.data_dir.set(self.default_data_dir)
                self.save_config()

        self.setup_styles()
        self.setup_ui()
        self._bind_shortcuts()
        if self.data_dir.get() and os.path.exists(self.data_dir.get()):
            self.refresh_channels(silent=True)

    def load_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    last_dir = config.get('last_data_dir', '')
                    if last_dir and os.path.exists(last_dir):
                        self.data_dir.set(last_dir)
                    else:
                        self.data_dir.set('')
                    self.auto_scan_interval = config.get('auto_scan_interval', 60)
            else:
                self.auto_scan_interval = 60
        except Exception:
            self.auto_scan_interval = 60

    def save_config(self):
        try:
            config = {
                'last_data_dir': self.data_dir.get(),
                'auto_scan_interval': getattr(self, 'auto_scan_interval', 60)
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Card.TLabelframe", padding=12, background="#FFFFFF", relief="flat", borderwidth=1)
        style.configure("Card.TLabelframe.Label", background="#FFFFFF", foreground="#1E3A5F", font=UI_FONT_BOLD)
        style.configure("Modern.Treeview",
                        background="#FFFFFF",
                        foreground="#1F2937",
                        fieldbackground="#FFFFFF",
                        rowheight=30,
                        borderwidth=0,
                        font=UI_FONT)
        style.configure("Modern.Treeview.Heading",
                        background="#F1F5F9",
                        foreground="#1E3A5F",
                        font=UI_FONT_BOLD,
                        relief="flat",
                        borderwidth=0)
        style.map("Modern.Treeview",
                  background=[("selected", "#DBEAFE")],
                  foreground=[("selected", "#0F172A")])
        style.map("Modern.Treeview.Heading",
                  background=[("active", "#E2E8F0")])

    def _bind_shortcuts(self):
        for key in ("<KeyPress-Shift_L>", "<KeyPress-Shift_R>"):
            self.root.bind(key, lambda e: setattr(self, "shift_pressed", True))
        for key in ("<KeyRelease-Shift_L>", "<KeyRelease-Shift_R>"):
            self.root.bind(key, lambda e: setattr(self, "shift_pressed", False))

    def _section(self, parent, title):
        outer = tk.Frame(parent, bg="#FFFFFF", highlightbackground="#E2E8F0", highlightthickness=1)
        outer.pack(fill="x", padx=16, pady=(0, 10))
        tk.Label(outer, text=title, font=UI_FONT_BOLD, bg="#FFFFFF", fg="#1E3A5F").pack(
            anchor="w", padx=12, pady=(10, 4))
        body = tk.Frame(outer, bg="#FFFFFF")
        body.pack(fill="x", padx=12, pady=(0, 12))
        return body

    def _frame(self, parent):
        frame = tk.Frame(parent, bg="#FFFFFF")
        return frame

    def _set_combo_values(self, combo, values):
        combo["values"] = values

    def _set_label(self, label, text, color="#334155"):
        label.configure(text=text, fg=color)

    def setup_ui(self):
        header = tk.Frame(self.root, bg="#FFFFFF")
        header.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(header, text="智能库存决策系统", font=UI_TITLE_FONT,
                 bg="#FFFFFF", fg="#0F172A").pack(anchor="w")
        tk.Label(header, text="库存决策分析 · 订柜体积监控 · 多维筛选与排序",
                 font=UI_FONT, bg="#FFFFFF", fg="#64748B").pack(anchor="w", pady=(2, 0))

        dir_body = self._section(self.root, "数据源配置")
        dir_row = self._frame(dir_body)
        dir_row.pack(fill="x")
        tk.Label(dir_row, text="数据根目录", font=UI_FONT, bg="#FFFFFF").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.dir_entry = ttk.Entry(dir_row, textvariable=self.data_dir, width=52)
        self.dir_entry.grid(row=0, column=1, padx=(0, 8))
        ttk.Button(dir_row, text="浏览", command=self.select_data_dir).grid(row=0, column=2, padx=(0, 16))
        tk.Label(dir_row, text="渠道", font=UI_FONT, bg="#FFFFFF").grid(row=0, column=3, sticky="w", padx=(0, 8))
        self.channel_combo = ttk.Combobox(dir_row, textvariable=self.channel, width=18, state="readonly")
        self.channel_combo.grid(row=0, column=4, padx=(0, 8))
        self.channel_combo.bind("<<ComboboxSelected>>", lambda _e: self.update_file_status())
        ttk.Button(dir_row, text="刷新渠道", command=lambda: self.refresh_channels()).grid(row=0, column=5)

        self.file_status_label = tk.Label(dir_body, text="请选择数据根目录并刷新渠道列表",
                                        font=UI_FONT, fg="#64748B", bg="#FFFFFF", anchor="w")
        self.file_status_label.pack(fill="x", pady=(8, 0))

        auto_body = self._section(self.root, "自动扫描")
        auto_row = self._frame(auto_body)
        auto_row.pack(fill="x")
        tk.Label(auto_row, text="间隔(分钟)", font=UI_FONT, bg="#FFFFFF").pack(side="left")
        self.interval_entry = ttk.Entry(auto_row, width=8)
        self.interval_entry.insert(0, str(self.auto_scan_interval))
        self.interval_entry.pack(side="left", padx=(8, 12))
        self.auto_btn = tk.Button(auto_row, text="开始自动扫描", width=12, font=UI_FONT_BOLD,
                                  bg="#16A34A", fg="white", relief="flat", command=self.toggle_auto_scan)
        self.auto_btn.pack(side="left", padx=(0, 12))
        self.auto_status = tk.Label(auto_row, text="状态：已停止", font=UI_FONT, fg="#64748B", bg="#FFFFFF")
        self.auto_status.pack(side="left")
        tk.Label(auto_body, text=f"归档目录：{self.default_output_dir}",
                font=UI_MONO_FONT, fg="#94A3B8", bg="#FFFFFF", anchor="w").pack(fill="x", pady=(8, 0))

        param_body = self._section(self.root, "时间参数（天）")
        param_row = self._frame(param_body)
        param_row.pack(fill="x")
        tk.Label(param_row, text="Lead Time", font=UI_FONT, bg="#FFFFFF").pack(side="left")
        self.lead_time = ttk.Entry(param_row, width=10)
        self.lead_time.insert(0, "90")
        self.lead_time.pack(side="left", padx=(8, 24))
        tk.Label(param_row, text="物流时间", font=UI_FONT, bg="#FFFFFF").pack(side="left")
        self.logistics_time = ttk.Entry(param_row, width=10)
        self.logistics_time.insert(0, "30")
        self.logistics_time.pack(side="left", padx=8)

        self.help_visible = tk.BooleanVar(value=False)
        help_toggle_frame = self._frame(self.root)
        help_toggle_frame.pack(fill="x", padx=16, pady=(0, 4))
        self.help_toggle_btn = tk.Button(help_toggle_frame, text="展开说明", font=UI_FONT,
                                        fg="#2563EB", bg="#FFFFFF", relief="flat",
                                        command=self.toggle_help)
        self.help_toggle_btn.pack(anchor="w")

        self.help_frame = tk.Frame(self.root, bg="#FFFFFF", highlightbackground="#E2E8F0", highlightthickness=1)
        help_text = (
            "数据源：各渠道文件夹需含 stock.csv / PO.csv / Sales 8-30.csv / Sales 15.csv / Sales 30.csv\n"
            "决策逻辑：取三档销售最大日均需求；「下单备货」计入备货体积，「催促发货」计入催发货体积（在途×体积系数）\n"
            "筛选：地区 / 决策 / Family 可组合，体积面板会随当前视图实时更新\n"
            "排序：使用下方排序栏设置主/次排序，或点击表头（Shift+点击设次排序）"
        )
        self.help_label = tk.Label(self.help_frame, text=help_text, justify="left",
                                   font=UI_FONT, fg="#475569", bg="#FFFFFF")
        self.help_label.pack(anchor="w")

        action_body = self._section(self.root, "分析与导出")
        action_row = self._frame(action_body)
        action_row.pack(fill="x")
        tk.Button(action_row, text="生成分析报告", width=14, height=1, font=UI_FONT_BOLD,
                  bg="#16A34A", fg="white", relief="flat",
                  command=self.generate_analysis).pack(side="left", padx=(0, 10))
        tk.Button(action_row, text="导出 Excel", width=12, height=1, font=UI_FONT_BOLD,
                  bg="#2563EB", fg="white", relief="flat",
                  command=self.export_excel).pack(side="left")

        filter_body = self._section(self.root, "筛选与排序")
        filter_row = self._frame(filter_body)
        filter_row.pack(fill="x", pady=(0, 8))

        tk.Label(filter_row, text="地区", font=UI_FONT, bg="#FFFFFF").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.region_combo = ttk.Combobox(filter_row, textvariable=self.filter_region, width=10,
                                         values=["全部", "北岛", "南岛"], state="readonly")
        self.region_combo.grid(row=0, column=1, padx=(0, 16))
        self.region_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_display())

        tk.Label(filter_row, text="决策", font=UI_FONT, bg="#FFFFFF").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.decision_combo = ttk.Combobox(
            filter_row, textvariable=self.filter_decision, width=12,
            values=["全部", "下单备货", "催促发货", "保持现状", "暂无销售"], state="readonly")
        self.decision_combo.grid(row=0, column=3, padx=(0, 16))
        self.decision_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_display())

        tk.Label(filter_row, text="Family（可搜索）", font=UI_FONT, bg="#FFFFFF").grid(row=0, column=4, sticky="w", padx=(0, 6))
        self.family_combo = ttk.Combobox(filter_row, textvariable=self.filter_family, width=22,
                                         values=self.family_list)
        self.family_combo.grid(row=0, column=5, padx=(0, 16))
        self.family_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_family_selected())
        self.family_combo.bind("<KeyRelease>", self.on_family_keyrelease)
        self.family_combo.bind("<Return>", lambda _e: self.refresh_display())

        tk.Button(filter_row, text="重置", width=8, font=UI_FONT, bg="#64748B", fg="white",
                  relief="flat", command=self.reset_filters).grid(row=0, column=6)

        sort_row = self._frame(filter_body)
        sort_row.pack(fill="x")
        tk.Label(sort_row, text="主排序", font=UI_FONT, bg="#FFFFFF").pack(side="left")
        self.sort_primary_combo = ttk.Combobox(sort_row, textvariable=self.sort_primary_var, width=14,
                                               values=SORT_OPTIONS, state="readonly")
        self.sort_primary_combo.pack(side="left", padx=(6, 4))
        self.sort_primary_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_sort_control_change())
        self.sort_primary_dir_btn = tk.Button(sort_row, text="升序 ↑", width=8, font=UI_FONT,
                                              relief="flat", bg="#E2E8F0",
                                              command=self.toggle_primary_sort_dir)
        self.sort_primary_dir_btn.pack(side="left", padx=(0, 16))

        tk.Label(sort_row, text="次排序", font=UI_FONT, bg="#FFFFFF").pack(side="left")
        self.sort_secondary_combo = ttk.Combobox(sort_row, textvariable=self.sort_secondary_var, width=14,
                                                 values=SORT_OPTIONS, state="readonly")
        self.sort_secondary_combo.pack(side="left", padx=(6, 4))
        self.sort_secondary_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_sort_control_change())
        self.sort_secondary_dir_btn = tk.Button(sort_row, text="升序 ↑", width=8, font=UI_FONT,
                                                relief="flat", bg="#E2E8F0",
                                                command=self.toggle_secondary_sort_dir)
        self.sort_secondary_dir_btn.pack(side="left", padx=(0, 8))
        tk.Button(sort_row, text="清除次排序", width=10, font=UI_FONT, bg="#94A3B8", fg="white",
                  relief="flat", command=self.clear_secondary_sort).pack(side="left", padx=(0, 12))

        self.sort_status_label = tk.Label(sort_row, text="排序：默认（决策优先级）", font=UI_FONT, fg="#64748B", bg="#FFFFFF")
        self.sort_status_label.pack(side="left")

        container_body = self._section(self.root, f"订柜状态监控（阈值 {CONTAINER_THRESHOLD:.0f} m³/柜）")
        self.container_status_label = tk.Label(container_body, text="等待分析...",
                                               font=("Microsoft YaHei UI", 11), fg="#64748B",
                                               justify="left", anchor="w", bg="#FFFFFF")
        self.container_status_label.pack(fill="x")
        self.volume_detail_label = tk.Label(container_body, text="", font=UI_FONT,
                                            fg="#475569", justify="left", anchor="w", bg="#FFFFFF")
        self.volume_detail_label.pack(fill="x", pady=(6, 0))

        table_section = tk.Frame(self.root, bg="#FFFFFF", highlightbackground="#E2E8F0", highlightthickness=1)
        table_section.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        tk.Label(table_section, text="分析结果（点击表头排序，Shift+点击设次排序）",
                 font=UI_FONT_BOLD, bg="#FFFFFF", fg="#1E3A5F").pack(anchor="w", padx=12, pady=(10, 6))

        table_wrap = tk.Frame(table_section, bg="#FFFFFF")
        table_wrap.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        columns = ("SKU", "Name", "ProductFamily", "地区", "在库库存", "在途库存", "总量库存",
                   "8-30天", "15天", "30天", "采用需求", "需求来源",
                   "LT预估", "物流预估", "决策建议", "建议订货量", "体积系数", "备货体积", "催发货体积", "详细说明")
        self.tree = ttk.Treeview(table_wrap, columns=columns, show="headings", height=14, style="Modern.Treeview")
        self.column_display_names = columns

        col_widths = [80, 160, 90, 55, 65, 65, 65, 60, 60, 60, 70, 80, 75, 75, 85, 75, 70, 75, 80, 160]
        for col, width in zip(columns, col_widths):
            self.tree.heading(col, text=col, command=lambda c=col: self.on_header_click(c))
            self.tree.column(col, width=width, anchor="center")

        scrollbar_y = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        scrollbar_x = ttk.Scrollbar(table_wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        scrollbar_x.grid(row=1, column=0, sticky="ew")
        table_wrap.grid_rowconfigure(0, weight=1)
        table_wrap.grid_columnconfigure(0, weight=1)

        self.tree.tag_configure("normal", background="#FFFFFF", foreground="#1F2937")
        self.tree.tag_configure("urgent", background="#FFFFFF", foreground="#B91C1C")
        self.tree.tag_configure("warning", background="#FFFFFF", foreground="#B45309")
        self.tree.tag_configure("no_sales", background="#FFFFFF", foreground="#9CA3AF")

        summary_body = self._section(self.root, "汇总统计")
        self.summary_label = tk.Label(summary_body, text="等待分析...", font=UI_MONO_FONT,
                                      justify="left", anchor="w", bg="#FFFFFF")
        self.summary_label.pack(fill="x")

    def toggle_help(self):
        if self.help_visible.get():
            self.help_frame.pack_forget()
            self.help_toggle_btn.configure(text="展开说明")
            self.help_visible.set(False)
        else:
            self.help_frame.pack(fill="x", padx=16, pady=(0, 10), after=self.help_toggle_btn.master)
            self.help_toggle_btn.configure(text="收起说明")
            self.help_visible.set(True)

    def select_data_dir(self):
        folder = filedialog.askdirectory()
        if folder:
            self.data_dir.set(folder)
            self.save_config()
            self.refresh_channels()

    def refresh_channels(self, silent=False):
        data_dir = self.data_dir.get()
        if not data_dir or not os.path.exists(data_dir):
            if not silent:
                messagebox.showerror("错误", "请先选择有效的数据根目录")
            return
        try:
            channels = [d for d in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, d))]
            channels.sort()
            self._set_combo_values(self.channel_combo, channels)
            if channels:
                self.channel_combo.set(channels[0])
                self.update_file_status()
            else:
                self._set_label(self.file_status_label, "该目录下未找到子文件夹（渠道）", "#DC2626")
        except Exception as e:
            if not silent:
                messagebox.showerror("错误", f"读取目录失败：{str(e)}")

    def update_file_status(self):
        ch = self.channel.get()
        dir_path = self.data_dir.get()
        if not ch or not dir_path:
            return False
        folder = os.path.join(dir_path, ch)
        required_files = ["stock.csv", "PO.csv", "Sales 8-30.csv", "Sales 15.csv", "Sales 30.csv"]
        status_lines = [f"当前渠道 [{ch}] 文件检查："]
        all_ready = True
        for f in required_files:
            exists = os.path.exists(os.path.join(folder, f))
            symbol = "✓" if exists else "✗"
            status_lines.append(f"{symbol} {f}")
            if not exists: all_ready = False
        self._set_label(self.file_status_label, "  |  ".join(status_lines),
                        "#16A34A" if all_ready else "#DC2626")
        return all_ready

    def on_family_selected(self, _value=None):
        self.refresh_display()

    def on_family_keyrelease(self, event):
        if event.keysym in ("Up", "Down", "Return", "Tab", "Shift_L", "Shift_R"):
            return
        typed = self.filter_family.get().strip().lower()
        if not typed:
            self._set_combo_values(self.family_combo, self.family_list)
            return
        matches = [f for f in self.family_list if typed in f.lower()]
        if not matches:
            matches = self.family_list
        self._set_combo_values(self.family_combo, matches)
        if len(matches) == 1 and matches[0] != "全部":
            self.filter_family.set(matches[0])
            self.refresh_display()

    def _display_name_for_col(self, df_col):
        for display, internal in COL_MAP.items():
            if internal == df_col:
                return display
        return df_col

    def _col_from_display(self, display_name):
        if not display_name or display_name == "（无）":
            return None
        return COL_MAP.get(display_name)

    def _sync_sort_controls(self):
        self.sort_primary_var.set(self._display_name_for_col(self.sort_primary) if self.sort_primary else "（无）")
        self.sort_secondary_var.set(self._display_name_for_col(self.sort_secondary) if self.sort_secondary else "（无）")
        self.sort_primary_dir_btn.configure(text="升序 ↑" if self.sort_primary_asc else "降序 ↓")
        self.sort_secondary_dir_btn.configure(text="升序 ↑" if self.sort_secondary_asc else "降序 ↓")

    def on_sort_control_change(self, _value=None):
        self.sort_primary = self._col_from_display(self.sort_primary_var.get())
        self.sort_secondary = self._col_from_display(self.sort_secondary_var.get())
        if self.sort_primary and self.sort_secondary and self.sort_primary == self.sort_secondary:
            self.sort_secondary = None
            self.sort_secondary_var.set("（无）")
        self.update_sort_status()
        self.refresh_display()

    def toggle_primary_sort_dir(self):
        if self.sort_primary is None:
            return
        self.sort_primary_asc = not self.sort_primary_asc
        self._sync_sort_controls()
        self.update_sort_status()
        self.refresh_display()

    def toggle_secondary_sort_dir(self):
        if self.sort_secondary is None:
            return
        self.sort_secondary_asc = not self.sort_secondary_asc
        self._sync_sort_controls()
        self.update_sort_status()
        self.refresh_display()

    def reset_filters(self):
        self.filter_region.set("全部")
        self.filter_decision.set("全部")
        self.filter_family.set("全部")
        self._set_combo_values(self.family_combo, self.family_list)
        self.sort_primary = None
        self.sort_secondary = None
        self.sort_primary_asc = True
        self.sort_secondary_asc = True
        self._sync_sort_controls()
        self.update_sort_status()
        self.refresh_display()

    def update_sort_status(self):
        self._sync_sort_controls()
        self._update_column_headers()
        if self.sort_primary is None:
            self.sort_status_label.configure(text="排序：默认（决策优先级）", fg="#64748B")
            return
        primary_text = f"{self._display_name_for_col(self.sort_primary)} {'↑' if self.sort_primary_asc else '↓'}"
        if self.sort_secondary:
            secondary_text = f"{self._display_name_for_col(self.sort_secondary)} {'↑' if self.sort_secondary_asc else '↓'}"
            self.sort_status_label.configure(text=f"排序：{primary_text} → {secondary_text}", fg="#2563EB")
        else:
            self.sort_status_label.configure(text=f"排序：{primary_text}", fg="#2563EB")

    def _update_column_headers(self):
        for col in self.column_display_names:
            suffix = ""
            df_col = COL_MAP.get(col)
            if df_col == self.sort_primary:
                suffix = " ↑" if self.sort_primary_asc else " ↓"
            elif df_col == self.sort_secondary:
                suffix = " ·" + ("↑" if self.sort_secondary_asc else "↓")
            self.tree.heading(col, text=f"{col}{suffix}")

    def on_header_click(self, col):
        df_col = COL_MAP.get(col)
        if not df_col or self.result_data is None:
            return

        if self.shift_pressed:
            if self.sort_primary == df_col:
                self.sort_primary_asc = not self.sort_primary_asc
            else:
                self.sort_secondary = df_col
                self.sort_secondary_asc = True
        elif self.sort_primary == df_col:
            self.sort_primary_asc = not self.sort_primary_asc
        else:
            if self.sort_primary is not None:
                self.sort_secondary = self.sort_primary
                self.sort_secondary_asc = self.sort_primary_asc
            self.sort_primary = df_col
            self.sort_primary_asc = True

        self.update_sort_status()
        self.refresh_display()

    def clear_secondary_sort(self):
        self.sort_secondary = None
        self.sort_secondary_asc = True
        self.update_sort_status()
        self.refresh_display()

    def _filters_active(self):
        return (self.filter_region.get() != "全部"
                or self.filter_decision.get() != "全部"
                or self.filter_family.get() != "全部")

    def get_filtered_df(self):
        if self.result_data is None:
            return None
        df = self.result_data.copy()
        if self.filter_region.get() != "全部":
            df = df[df['Region'] == self.filter_region.get()]
        if self.filter_decision.get() != "全部":
            df = df[df['决策建议'] == self.filter_decision.get()]
        family = self.filter_family.get().strip()
        if family and family != "全部":
            exact = df[df['ProductFamily'].str.lower() == family.lower()]
            if len(exact) > 0:
                df = exact
            else:
                df = df[df['ProductFamily'].str.lower().str.contains(family.lower(), na=False)]
        return df

    def update_volume_displays(self, df):
        order_df = df[df['决策建议'] == '下单备货']
        expedite_df = df[df['决策建议'] == '催促发货']

        north_order = order_df[order_df['Region'] == '北岛']['备货体积'].sum()
        south_order = order_df[order_df['Region'] == '南岛']['备货体积'].sum()
        total_order = order_df['备货体积'].sum()

        north_expedite = expedite_df[expedite_df['Region'] == '北岛']['催发货体积'].sum()
        south_expedite = expedite_df[expedite_df['Region'] == '南岛']['催发货体积'].sum()
        total_expedite = expedite_df['催发货体积'].sum()

        threshold = CONTAINER_THRESHOLD
        north_can = north_order >= threshold
        south_can = south_order >= threshold
        view_note = "（当前筛选视图）" if self._filters_active() else "（全量数据）"
        channel = self.channel.get() or "—"
        decision_filter = self.filter_decision.get()

        if decision_filter == "催促发货":
            status_text = (f"[{channel}] {view_note}  "
                           f"催发货体积：北岛 {north_expedite:.3f} m³ / 南岛 {south_expedite:.3f} m³ / 合计 {total_expedite:.3f} m³")
            status_color = "#B45309" if total_expedite > 0 else "#334155"
        elif decision_filter == "下单备货":
            msgs = []
            if north_can:
                msgs.append(f"北岛可订柜：{north_order:.2f} m³ ≥ {threshold:.0f} m³")
            else:
                msgs.append(f"北岛备货：{north_order:.2f} m³（差 {threshold - north_order:.2f} m³）")
            if south_can:
                msgs.append(f"南岛可订柜：{south_order:.2f} m³ ≥ {threshold:.0f} m³")
            else:
                msgs.append(f"南岛备货：{south_order:.2f} m³（差 {threshold - south_order:.2f} m³）")
            status_text = f"[{channel}] {view_note}  " + "  |  ".join(msgs)
            status_color = "#DC2626" if (north_can or south_can) else "#334155"
        else:
            msgs = []
            if north_can:
                msgs.append(f"北岛可订柜：{north_order:.2f} m³")
            else:
                msgs.append(f"北岛备货：{north_order:.2f} m³")
            if south_can:
                msgs.append(f"南岛可订柜：{south_order:.2f} m³")
            else:
                msgs.append(f"南岛备货：{south_order:.2f} m³")
            status_text = f"[{channel}] {view_note}  " + "  |  ".join(msgs)
            status_color = "#DC2626" if (north_can or south_can) else "#334155"

        self._set_label(self.container_status_label, status_text, status_color)

        decision_stats = []
        for decision in ["下单备货", "催促发货", "保持现状", "暂无销售"]:
            subset = df[df['决策建议'] == decision]
            if len(subset) == 0:
                continue
            if decision == "下单备货":
                vol = subset['备货体积'].sum()
                decision_stats.append(f"{decision} {len(subset)} 行 / 备货 {vol:.3f} m³")
            elif decision == "催促发货":
                vol = subset['催发货体积'].sum()
                transit = subset['在途库存'].sum()
                decision_stats.append(f"{decision} {len(subset)} 行 / 在途 {transit:.0f} 件 / 催发 {vol:.3f} m³")
            else:
                decision_stats.append(f"{decision} {len(subset)} 行")

        detail = "各决策状态：" + "  |  ".join(decision_stats)
        detail += f"  |  备货合计 {total_order:.3f} m³  |  催发合计 {total_expedite:.3f} m³"
        self._set_label(self.volume_detail_label, detail, "#475569")

    def refresh_display(self):
        if self.result_data is None:
            return
        for item in self.tree.get_children():
            self.tree.delete(item)

        df = self.get_filtered_df()
        if df is None:
            return

        sort_cols = []
        sort_asc = []
        if self.sort_primary:
            sort_cols.append(self.sort_primary)
            sort_asc.append(self.sort_primary_asc)
        if self.sort_secondary:
            sort_cols.append(self.sort_secondary)
            sort_asc.append(self.sort_secondary_asc)

        if sort_cols:
            try:
                df = df.sort_values(by=sort_cols, ascending=sort_asc)
            except Exception:
                pass

        for _, row in df.iterrows():
            values = (
                row['Sku'], row['Name'], row['ProductFamily'], row['Region'],
                f"{row['在库库存']:.0f}", f"{row['在途库存']:.0f}",
                f"{row['总量库存']:.0f}", f"{row['需求_8_30天']:.3f}", f"{row['需求_15天']:.3f}",
                f"{row['需求_30天']:.3f}", f"{row['日均需求']:.3f}", row['需求来源'],
                f"{row['LT预估']:.1f}", f"{row['物流预估']:.1f}", row['决策建议'],
                f"{row['建议订货量']:.0f}" if row['建议订货量'] > 0 else "-",
                f"{row['PriceRadarVolume']:.5f}",
                f"{row['备货体积']:.4f}" if row['备货体积'] > 0 else "-",
                f"{row['催发货体积']:.4f}" if row['催发货体积'] > 0 else "-",
                row['详细说明']
            )
            if row['决策建议'] == "下单备货":
                tags = ("urgent",)
            elif row['决策建议'] == "催促发货":
                tags = ("warning",)
            elif row['决策建议'] == "暂无销售":
                tags = ("no_sales",)
            else:
                tags = ("normal",)
            self.tree.insert("", "end", values=values, tags=tags)

        self.update_volume_displays(df)

        order_df = df[df['决策建议'] == '下单备货']
        expedite_df = df[df['决策建议'] == '催促发货']
        total_order = order_df['备货体积'].sum()
        north_order = order_df[order_df['Region'] == '北岛']['备货体积'].sum()
        south_order = order_df[order_df['Region'] == '南岛']['备货体积'].sum()
        total_expedite = expedite_df['催发货体积'].sum()
        north_expedite = expedite_df[expedite_df['Region'] == '北岛']['催发货体积'].sum()
        south_expedite = expedite_df[expedite_df['Region'] == '南岛']['催发货体积'].sum()
        filter_hint = "（筛选视图）" if self._filters_active() else ""
        self._set_label(self.summary_label,
                        (f"当前显示：{len(df)} 行{filter_hint}  |  "
                         f"需下单：{len(order_df)}  |  需催发：{len(expedite_df)}  |  "
                         f"备货体积：北岛 {north_order:.3f} / 南岛 {south_order:.3f} / 合计 {total_order:.3f} m³  |  "
                         f"催发体积：北岛 {north_expedite:.3f} / 南岛 {south_expedite:.3f} / 合计 {total_expedite:.3f} m³"))

    # ========== 自动扫描（轮询所有渠道） ==========
    def toggle_auto_scan(self):
        if self.auto_scanning:
            self.stop_auto_scan()
        else:
            try:
                interval = int(self.interval_entry.get())
                if interval < 1:
                    raise ValueError
                self.auto_scan_interval = interval
                self.save_config()
            except ValueError:
                messagebox.showerror("错误", "扫描间隔必须是正整数（分钟）")
                return
            self.start_auto_scan()

    def start_auto_scan(self):
        self.auto_scanning = True
        self.auto_btn.configure(text="停止自动扫描", bg="#DC2626")
        self._set_label(self.auto_status, f"运行中（每 {self.auto_scan_interval} 分钟扫描全部渠道）", "#16A34A")
        self.scan_all_channels()

    def stop_auto_scan(self):
        self.auto_scanning = False
        if self.scan_job_id:
            self.root.after_cancel(self.scan_job_id)
            self.scan_job_id = None
        self.auto_btn.configure(text="开始自动扫描", bg="#16A34A")
        self._set_label(self.auto_status, "状态：已停止", "#64748B")
        self._set_label(self.summary_label, "自动扫描已停止")

    def scan_all_channels(self):
        if not self.auto_scanning:
            return

        data_dir = self.data_dir.get()
        if not data_dir or not os.path.exists(data_dir):
            self._set_label(self.summary_label, "错误：数据根目录无效，扫描暂停")
            self.stop_auto_scan()
            return

        try:
            all_channels = [d for d in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, d))]
            all_channels.sort()
        except Exception as e:
            self._set_label(self.summary_label, f"读取渠道列表失败: {e}")
            self.stop_auto_scan()
            return

        if not all_channels:
            self._set_label(self.summary_label, "未找到任何渠道文件夹")
            self.stop_auto_scan()
            return

        self._scan_channel_index = 0
        self._all_channels = all_channels
        self._process_next_channel()

    def _process_next_channel(self):
        if not self.auto_scanning:
            return

        if self._scan_channel_index >= len(self._all_channels):
            self._set_label(self.summary_label,
                            f"本轮扫描完成（共 {len(self._all_channels)} 个渠道），{self.auto_scan_interval} 分钟后开始下一轮...")
            ms = self.auto_scan_interval * 60 * 1000
            self.scan_job_id = self.root.after(ms, self.scan_all_channels)
            return

        ch = self._all_channels[self._scan_channel_index]
        self.channel.set(ch)
        try:
            values = self.channel_combo.cget("values")
            if ch in values:
                self.channel_combo.set(ch)
        except Exception:
            pass

        self.update_file_status()
        self._set_label(self.summary_label,
                        f"正在扫描 [{ch}] ({self._scan_channel_index + 1}/{len(self._all_channels)})...")
        self.root.update_idletasks()

        success = self.run_analysis_core(silent=True, auto_export=True, channel_override=ch)

        self._scan_channel_index += 1
        self.root.after(500, self._process_next_channel)

    # ========== 截图功能 ==========
    def capture_screenshot(self, save_path):
        try:
            self.root.update_idletasks()
            self.root.update()
            x = self.root.winfo_rootx()
            y = self.root.winfo_rooty()
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            img.save(save_path, "PNG")
            return True
        except Exception as e:
            print(f"截图失败: {e}")
            return False

    # ========== 图表生成 ==========
    def generate_charts(self, df, output_dir, prefix):
        try:
            # 图1: 决策建议分布饼图
            fig1, ax1 = plt.subplots(figsize=(8, 6))
            decision_counts = df['决策建议'].value_counts()
            colors_map = {'下单备货': '#FF5252', '催促发货': '#FFD740', '保持现状': '#69F0AE', '暂无销售': '#E0E0E0'}
            colors = [colors_map.get(d, '#BDBDBD') for d in decision_counts.index]
            labels_en = []
            for d in decision_counts.index:
                en_map = {'下单备货': 'Place Order', '催促发货': 'Expedite', '保持现状': 'OK', '暂无销售': 'No Sales'}
                labels_en.append(f"{d}\n({en_map.get(d, d)})")

            wedges, texts, autotexts = ax1.pie(decision_counts, labels=labels_en, autopct='%1.1f%%',
                                               colors=colors, startangle=90, textprops={'fontsize': 10})
            ax1.set_title(f'Decision Distribution / 决策分布 - {prefix}', fontsize=14, fontweight='bold', pad=20)
            plt.tight_layout()
            fig1.savefig(os.path.join(output_dir, "decision_distribution.png"), dpi=150, bbox_inches='tight')
            plt.close(fig1)

            # 图2: 南北岛备货体积对比
            fig2, ax2 = plt.subplots(figsize=(8, 5))
            order_df = df[df['决策建议'] == '下单备货']
            regions = ['North Island\n北岛', 'South Island\n南岛']
            volumes = [
                order_df[order_df['Region'] == '北岛']['备货体积'].sum(),
                order_df[order_df['Region'] == '南岛']['备货体积'].sum()
            ]
            bars = ax2.bar(regions, volumes, color=['#42A5F5', '#AB47BC'], width=0.5, edgecolor='white', linewidth=1.5)
            ax2.axhline(y=CONTAINER_THRESHOLD, color='#D32F2F', linestyle='--', linewidth=2,
                        label=f'Container Threshold / 订柜阈值 {CONTAINER_THRESHOLD:.0f}m³')
            ax2.set_ylabel('Volume (m³) / 体积', fontsize=12)
            ax2.set_title(f'Region Volume & Container Threshold / 南北岛备货体积 - {prefix}', fontsize=13, fontweight='bold')
            ax2.legend()
            for bar, vol in zip(bars, volumes):
                height = bar.get_height()
                flag = 'BOOK NOW!\n可订柜!' if vol >= CONTAINER_THRESHOLD else ''
                ax2.annotate(f"{vol:.2f}m³\n{flag}", xy=(bar.get_x() + bar.get_width()/2, height),
                            xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=10)
            plt.tight_layout()
            fig2.savefig(os.path.join(output_dir, "container_volume.png"), dpi=150, bbox_inches='tight')
            plt.close(fig2)

            # 图3: 库存可支撑天数分布
            fig3, ax3 = plt.subplots(figsize=(10, 5))
            active_df = df[df['决策建议'].isin(['下单备货', '催促发货'])].copy()
            if len(active_df) > 0:
                active_df['可支撑天数'] = active_df.apply(
                    lambda r: r['总量库存']/r['日均需求'] if r['日均需求']>0 else 999, axis=1
                )
                active_df = active_df.sort_values('可支撑天数').head(30)
                colors_bar = ['#FF5252' if d == '下单备货' else '#FFD740' for d in active_df['决策建议']]
                ax3.barh(range(len(active_df)), active_df['可支撑天数'], color=colors_bar, edgecolor='white')
                ax3.set_yticks(range(len(active_df)))
                ax3.set_yticklabels([f"{r['Sku'][:15]}({r['Region']})" for _, r in active_df.iterrows()], fontsize=8)
                ax3.set_xlabel('Days of Supply / 可支撑天数', fontsize=11)
                ax3.set_title(f'TOP30 Urgent SKU Days of Supply / 最紧急库存预警 TOP30 - {prefix}', fontsize=13, fontweight='bold')
                ax3.axvline(x=int(self.logistics_time.get()), color='#FF9800', linestyle='--', alpha=0.7, label=f'Logistics({self.logistics_time.get()}d) / 物流周期')
                ax3.axvline(x=int(self.lead_time.get()), color='#D32F2F', linestyle='--', alpha=0.7, label=f'LeadTime({self.lead_time.get()}d) / 采购周期')
                ax3.legend(loc='lower right')
                plt.tight_layout()
                fig3.savefig(os.path.join(output_dir, "stock_alert.png"), dpi=150, bbox_inches='tight')
                plt.close(fig3)

            return True
        except Exception as e:
            print(f"Chart generation failed: {e}")
            return False

    # ========== 核心分析逻辑 ==========
    def run_analysis_core(self, silent=False, auto_export=False, channel_override=None):
        try:
            target_channel = channel_override or self.channel.get()
            if not self.data_dir.get() or not target_channel:
                if not silent:
                    messagebox.showerror("错误", "请先选择数据根目录和渠道")
                return False

            base_path = os.path.join(self.data_dir.get(), target_channel)
            stock_path = os.path.join(base_path, "stock.csv")
            po_path = os.path.join(base_path, "PO.csv")
            sales_8_path = os.path.join(base_path, "Sales 8-30.csv")
            sales_15_path = os.path.join(base_path, "Sales 15.csv")
            sales_30_path = os.path.join(base_path, "Sales 30.csv")

            required_files = ["stock.csv", "PO.csv", "Sales 8-30.csv", "Sales 15.csv", "Sales 30.csv"]
            missing = [f for f in required_files if not os.path.exists(os.path.join(base_path, f))]
            if missing:
                if not silent:
                    messagebox.showerror("错误", f"渠道 [{target_channel}] 缺少文件: {', '.join(missing)}")
                return False

            stock_wide = pd.read_csv(stock_path)

            # 检查新格式：包含 Name 和 ProductFamily
            has_name = 'Name' in stock_wide.columns
            has_family = 'ProductFamily' in stock_wide.columns

            if 'SouthIslandStock' in stock_wide.columns and 'NorthIslandStock' in stock_wide.columns:
                id_vars = ['Sku', 'PriceRadarVolume', 'IsDiscontinued']
                if has_name:
                    id_vars.append('Name')
                if has_family:
                    id_vars.append('ProductFamily')

                stock_df = pd.melt(stock_wide, 
                                  id_vars=id_vars, 
                                  value_vars=['SouthIslandStock', 'NorthIslandStock'],
                                  var_name='RegionRaw', value_name='在库库存')
                stock_df['Region'] = stock_df['RegionRaw'].map({
                    'SouthIslandStock': '南岛', 'NorthIslandStock': '北岛'
                })
                stock_df = stock_df.drop(columns=['RegionRaw'])
                stock_df['PriceRadarVolume'] = pd.to_numeric(stock_df['PriceRadarVolume'], errors='coerce').fillna(0)
                stock_df['IsDiscontinued'] = pd.to_numeric(stock_df['IsDiscontinued'], errors='coerce').fillna(0).astype(int)
                stock_df['在库库存'] = pd.to_numeric(stock_df['在库库存'], errors='coerce').fillna(0)

                # 如果没有 Name/ProductFamily，填充空值
                if not has_name:
                    stock_df['Name'] = ''
                if not has_family:
                    stock_df['ProductFamily'] = ''

                stock_df = stock_df.drop_duplicates(subset=['Sku', 'Region'])
            else:
                if not silent:
                    messagebox.showerror("错误", "Stock文件格式不正确：缺少SouthIslandStock/NorthIslandStock列")
                return False

            # 更新 ProductFamily 筛选列表
            families = sorted(stock_df['ProductFamily'].dropna().unique().tolist())
            families = [f for f in families if f]  # 去掉空值
            self.family_list = ["全部"] + families
            self._set_combo_values(self.family_combo, self.family_list)
            if self.filter_family.get() not in self.family_list:
                self.filter_family.set("全部")

            po_df = pd.read_csv(po_path)
            sales_8_30_df = pd.read_csv(sales_8_path)
            sales_15_df = pd.read_csv(sales_15_path)
            sales_30_df = pd.read_csv(sales_30_path)

            for df_chk, name in [(sales_8_30_df, "Sales 8-30"), (sales_15_df, "Sales 15"), (sales_30_df, "Sales 30")]:
                if 'AvgDailyDemand_3Checkins_Avg' not in df_chk.columns:
                    if not silent:
                        messagebox.showerror("错误", f"{name}.csv 缺少字段：AvgDailyDemand_3Checkins_Avg")
                    return False

            def is_in_transit(val):
                if pd.isna(val):
                    return True
                val_str = str(val).strip().lower()
                return val_str in ('', 'nan', 'nat', 'none', 'null')

            po_df['IsInTransit'] = po_df['CheckinDate'].apply(is_in_transit)
            transit_rows = po_df[po_df['IsInTransit']]

            in_transit = transit_rows.groupby(['Sku', 'Region'])['QuantityOrdered'].sum().reset_index()
            in_transit.rename(columns={'QuantityOrdered': '在途库存'}, inplace=True)

            all_skus = pd.concat([
                stock_df[['Sku', 'Region']],
                po_df[['Sku', 'Region']],
                sales_8_30_df[['Sku', 'Region']],
                sales_15_df[['Sku', 'Region']],
                sales_30_df[['Sku', 'Region']]
            ], ignore_index=True).drop_duplicates()

            # 合并时保留 Name 和 ProductFamily
            merge_cols = ['Sku', 'Region', '在库库存', 'PriceRadarVolume', 'IsDiscontinued']
            if 'Name' in stock_df.columns:
                merge_cols.append('Name')
            if 'ProductFamily' in stock_df.columns:
                merge_cols.append('ProductFamily')

            df = pd.merge(all_skus, stock_df[merge_cols], 
                          on=['Sku', 'Region'], how='left')
            df = pd.merge(df, in_transit, on=['Sku', 'Region'], how='left')

            df['在途库存'] = df['在途库存'].fillna(0)
            df['在库库存'] = df['在库库存'].fillna(0)
            df['总量库存'] = df['在库库存'] + df['在途库存']
            df['PriceRadarVolume'] = df['PriceRadarVolume'].fillna(0)
            df['IsDiscontinued'] = df['IsDiscontinued'].fillna(0).astype(int)
            if 'Name' in df.columns:
                df['Name'] = df['Name'].fillna('')
            else:
                df['Name'] = ''
            if 'ProductFamily' in df.columns:
                df['ProductFamily'] = df['ProductFamily'].fillna('')
            else:
                df['ProductFamily'] = ''

            s8 = sales_8_30_df.groupby(['Sku', 'Region'])['AvgDailyDemand_3Checkins_Avg'].mean().reset_index()
            s8.rename(columns={'AvgDailyDemand_3Checkins_Avg': '需求_8_30天'}, inplace=True)
            s15 = sales_15_df.groupby(['Sku', 'Region'])['AvgDailyDemand_3Checkins_Avg'].mean().reset_index()
            s15.rename(columns={'AvgDailyDemand_3Checkins_Avg': '需求_15天'}, inplace=True)
            s30 = sales_30_df.groupby(['Sku', 'Region'])['AvgDailyDemand_3Checkins_Avg'].mean().reset_index()
            s30.rename(columns={'AvgDailyDemand_3Checkins_Avg': '需求_30天'}, inplace=True)

            df = pd.merge(df, s8, on=['Sku', 'Region'], how='left')
            df = pd.merge(df, s15, on=['Sku', 'Region'], how='left')
            df = pd.merge(df, s30, on=['Sku', 'Region'], how='left')

            df['需求_8_30天'] = df['需求_8_30天'].fillna(0)
            df['需求_15天'] = df['需求_15天'].fillna(0)
            df['需求_30天'] = df['需求_30天'].fillna(0)
            df['日均需求'] = df[['需求_8_30天', '需求_15天', '需求_30天']].max(axis=1)

            def get_source(row):
                max_val = row['日均需求']
                if max_val == 0:
                    return "无销售数据", "no_sales"
                sources = []
                if row['需求_8_30天'] == max_val: sources.append("8-30天")
                if row['需求_15天'] == max_val: sources.append("15天")
                if row['需求_30天'] == max_val: sources.append("30天")
                source_str = "/".join(sources)
                if "15天" in sources: return source_str, "use_15"
                elif "8-30天" in sources: return source_str, "use_8_30"
                else: return source_str, "use_30"

            source_info = df.apply(get_source, axis=1)
            df['需求来源'] = [s[0] for s in source_info]
            df['来源标签'] = [s[1] for s in source_info]

            df_before = len(df)
            df = df[df['IsDiscontinued'] != 1].copy()

            lt_days = int(self.lead_time.get())
            log_days = int(self.logistics_time.get())
            df['LT预估'] = df['日均需求'] * lt_days
            df['物流预估'] = df['日均需求'] * log_days

            def decide(row):
                total = row['总量库存']
                in_stock = row['在库库存']
                transit = row['在途库存']
                daily = row['日均需求']
                lt_need = row['LT预估']
                log_need = row['物流预估']
                source = row['需求来源']
                price_vol = row['PriceRadarVolume']

                if daily == 0:
                    return "暂无销售", 0, 0, f"无销售记录，当前库存: 现货{in_stock:.0f}+在途{transit:.0f}"
                if total <= lt_need:
                    order_qty = max(0, lt_need - total)
                    order_vol = order_qty * price_vol
                    return ("下单备货", order_qty, order_vol,
                           f"总库存{total:.0f}≤{lt_days}天需求({lt_need:.1f})，缺口{order_qty:.0f}，体积{order_vol:.4f}m³，基于{source}")
                elif in_stock <= log_need:
                    days = in_stock / daily
                    expedite_vol = transit * price_vol
                    return ("催促发货", 0, 0,
                           f"现货{in_stock:.0f}≤{log_days}天需求({log_need:.1f})，仅够{days:.0f}天，"
                           f"需催{transit:.0f}件到港，催发货体积{expedite_vol:.4f}m³")
                else:
                    days = total / daily
                    return ("保持现状", 0, 0,
                           f"库存充足(现货{in_stock:.0f}+在途{transit:.0f})，基于{source}可撑{days:.0f}天")

            decisions = df.apply(decide, axis=1)
            df['决策建议'] = [d[0] for d in decisions]
            df['建议订货量'] = [d[1] for d in decisions]
            df['备货体积'] = [d[2] for d in decisions]
            df['详细说明'] = [d[3] for d in decisions]
            df['催发货体积'] = 0.0
            expedite_mask = df['决策建议'] == '催促发货'
            df.loc[expedite_mask, '催发货体积'] = (
                df.loc[expedite_mask, '在途库存'] * df.loc[expedite_mask, 'PriceRadarVolume']
            )

            priority = {"下单备货": 0, "催促发货": 1, "保持现状": 2, "暂无销售": 3}
            df['优先级'] = df['决策建议'].map(priority)
            df = df.sort_values(['优先级', 'Sku'])

            self.result_data = df
            self.sort_primary = None
            self.sort_secondary = None
            self.sort_primary_asc = True
            self.sort_secondary_asc = True
            self.update_sort_status()
            self.refresh_display()

            order_df = df[df['决策建议'] == '下单备货']
            north_volume = order_df[order_df['Region'] == '北岛']['备货体积'].sum()
            south_volume = order_df[order_df['Region'] == '南岛']['备货体积'].sum()
            total_volume = order_df['备货体积'].sum()
            north_can = north_volume >= CONTAINER_THRESHOLD
            south_can = south_volume >= CONTAINER_THRESHOLD

            timestamp = datetime.now().strftime('%Y%m%d_%H%M')

            # ========== 归档输出 ==========
            if auto_export:
                archive_dir = os.path.join(self.default_output_dir, target_channel, timestamp)
                os.makedirs(archive_dir, exist_ok=True)

                excel_path = os.path.join(archive_dir, "inventory_analysis.xlsx")
                self.export_to_path(excel_path, df)

                self.generate_charts(df, archive_dir, f"{target_channel}_{timestamp}")

                ss_path = os.path.join(archive_dir, "screenshot.png")
                self.capture_screenshot(ss_path)

                channel_folder = os.path.join(self.data_dir.get(), target_channel)
                channel_ss_name = f"screenshot_{timestamp}.png"
                channel_ss_path = os.path.join(channel_folder, channel_ss_name)
                self.capture_screenshot(channel_ss_path)

                log_dir = os.path.join(self.default_output_dir, target_channel)
                os.makedirs(log_dir, exist_ok=True)
                log_path = os.path.join(log_dir, "scan_log.txt")
                with open(log_path, 'a', encoding='utf-8') as lf:
                    lf.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                            f"SKU:{len(df)} Orders:{len(order_df)} "
                            f"North:{north_volume:.2f}m³ South:{south_volume:.2f}m³ "
                            f"Archive:{timestamp}/\n")

                self._set_label(self.summary_label,
                                f"[{target_channel}] 完成 | 归档: output/{target_channel}/{timestamp}/ | 截图+Excel+Charts")

            if not silent:
                archive_dir = os.path.join(self.default_output_dir, target_channel, timestamp)
                os.makedirs(archive_dir, exist_ok=True)

                excel_path = os.path.join(archive_dir, "inventory_analysis.xlsx")
                self.export_to_path(excel_path, df)
                self.generate_charts(df, archive_dir, f"{target_channel}_{timestamp}")

                ss_path = os.path.join(archive_dir, "screenshot.png")
                self.capture_screenshot(ss_path)

                channel_folder = os.path.join(self.data_dir.get(), target_channel)
                channel_ss_name = f"screenshot_{timestamp}.png"
                channel_ss_path = os.path.join(channel_folder, channel_ss_name)
                success = self.capture_screenshot(channel_ss_path)

                alert = ""
                if north_can or south_can:
                    a = []
                    if north_can: a.append("🚢 北岛")
                    if south_can: a.append("🚢 南岛")
                    alert = f"\n\n{' | '.join(a)} 已达到订柜标准！"

                ss_msg = f"\n\n📸 截图已保存：\n  归档: output/{target_channel}/{timestamp}/screenshot.png\n  渠道: {channel_ss_name}" if success else ""

                stats = f"""分析完成！

📦 决策：下单{(df['决策建议']=='下单备货').sum()} | 催促{(df['决策建议']=='催促发货').sum()} | 保持{(df['决策建议']=='保持现状').sum()} | 无销售{(df['决策建议']=='暂无销售').sum()}
📊 订货：总量{order_df['建议订货量'].sum():.0f}件 | 总体积{total_volume:.3f}m³
📍 北岛{north_volume:.2f}m³{'【可订柜】' if north_can else ''} | 南岛{south_volume:.2f}m³{'【可订柜】' if south_can else ''}{alert}{ss_msg}
📁 归档路径：output/{target_channel}/{timestamp}/
🚫 已过滤：{df_before - len(df)} 个 Discontinue SKU"""
                messagebox.showinfo("分析完成", stats)

            return True

        except Exception as e:
            error_msg = f"处理数据时出错：\n{str(e)}"
            if not silent:
                messagebox.showerror("分析错误", error_msg)
            import traceback
            traceback.print_exc()
            return False

    def generate_analysis(self):
        self.run_analysis_core(silent=False, auto_export=True)

    def export_to_path(self, filename, df=None):
        data = df if df is not None else self.result_data
        if data is None:
            return False
        cols = ['Sku', 'Name', 'ProductFamily', 'Region', '在库库存', '在途库存', '总量库存', 
               '需求_8_30天', '需求_15天', '需求_30天', '日均需求', '需求来源',
               'LT预估', '物流预估', '决策建议', '建议订货量', 'PriceRadarVolume', '备货体积', '催发货体积', '详细说明']

        export_df = data[cols].copy()
        export_df.columns = ['SKU', 'Name', 'ProductFamily', '地区', '在库库存', '在途库存', '总量库存',
                           '8-30天日均', '15天日均', '30天日均', '采用日均需求', '需求来源',
                           'LeadTime周期需求', '物流周期需求', '决策建议', '建议订货量', '体积系数',
                           '备货体积(m³)', '催发货体积(m³)', '详细说明']

        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            export_df.to_excel(writer, index=False, sheet_name='库存决策分析')
            ws = writer.sheets['库存决策分析']

            order_df = data[data['决策建议'] == '下单备货']
            expedite_df = data[data['决策建议'] == '催促发货']
            n_vol = order_df[order_df['Region'] == '北岛']['备货体积'].sum()
            s_vol = order_df[order_df['Region'] == '南岛']['备货体积'].sum()
            n_exp = expedite_df[expedite_df['Region'] == '北岛']['催发货体积'].sum()
            s_exp = expedite_df[expedite_df['Region'] == '南岛']['催发货体积'].sum()

            r = len(export_df) + 2
            ws.cell(row=r, column=1, value="=== 汇总统计 ===")
            ws.cell(row=r+1, column=1, value="总备货体积(m³):")
            ws.cell(row=r+1, column=2, value=order_df['备货体积'].sum())
            ws.cell(row=r+2, column=1, value="北岛备货体积(m³):")
            ws.cell(row=r+2, column=2, value=n_vol)
            ws.cell(row=r+3, column=1, value="南岛备货体积(m³):")
            ws.cell(row=r+3, column=2, value=s_vol)
            ws.cell(row=r+4, column=1, value="总催发货体积(m³):")
            ws.cell(row=r+4, column=2, value=expedite_df['催发货体积'].sum())
            ws.cell(row=r+5, column=1, value="北岛催发货体积(m³):")
            ws.cell(row=r+5, column=2, value=n_exp)
            ws.cell(row=r+6, column=1, value="南岛催发货体积(m³):")
            ws.cell(row=r+6, column=2, value=s_exp)
            ws.cell(row=r+7, column=1, value="订柜状态:")
            ws.cell(row=r+7, column=2, value=f"北岛:{'可订柜' if n_vol>=CONTAINER_THRESHOLD else '未满柜'}, 南岛:{'可订柜' if s_vol>=CONTAINER_THRESHOLD else '未满柜'}")
        return True

    def export_excel(self):
        if self.result_data is None:
            messagebox.showwarning("提示", "请先生成分析报告")
            return
        try:
            default_name = f"inventory_analysis_{self.channel.get()}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
            filename = filedialog.asksaveasfilename(
                defaultextension=".xlsx",
                filetypes=[("Excel files", "*.xlsx")],
                initialfile=default_name,
                initialdir=self.default_output_dir
            )
            if filename:
                self.export_to_path(filename)
                messagebox.showinfo("导出成功", f"报告已保存至：\n{filename}")
        except Exception as e:
            messagebox.showerror("导出错误", f"导出失败：{str(e)}")

def main():
    try:
        root = tk.Tk()
        root.configure(bg="#FFFFFF")
        app = InventoryDecisionSystem(root)
        root.mainloop()
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            messagebox.showerror("启动失败", f"程序无法启动：\n{e}")
        except Exception:
            print(f"程序无法启动：{e}")
            input("按回车键退出...")


if __name__ == "__main__":
    main()
