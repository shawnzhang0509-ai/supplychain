import pandas as pd
import os
import json
import sys
import io
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image, ImageGrab, ImageTk

# ========== 中文字体修复 ==========
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

CONFIG_FILE = "inventory_config.json"
CHANNELS_SETTINGS_FILE = "channels_settings.json"
CHANNELS_SETTINGS_TEMPLATE = "channels_settings.template.json"
LEGACY_CHANNELS_SETTINGS_FILES = (
    "channel_settings.template.json",
    CHANNELS_SETTINGS_TEMPLATE,
)
DEFAULT_LEAD_TIME = 90
DEFAULT_LOGISTICS_TIME = 30
CONTAINER_THRESHOLD = 69.0
ERP_IMAGE_BASE = "https://ierpapi.ifurniture.co.nz/"
IMAGE_THUMB_SIZE = (60, 60)
TREE_ROW_HEIGHT = 68
ERP_ROW_EVEN = "#FFFFFF"
ERP_ROW_ODD = "#F0F4F8"

COL_MAP = {
    "SKU": "Sku", "Name": "Name", "ProductFamily": "ProductFamily",
    "地区": "Region", "在库库存": "在库库存", "在途库存": "在途库存", "在产库存": "在产库存",
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

UI_FONT = ("Microsoft YaHei UI", 9)
UI_FONT_BOLD = ("Microsoft YaHei UI", 9, "bold")
UI_TITLE_FONT = ("Microsoft YaHei UI", 14, "bold")
UI_MONO_FONT = ("Consolas", 9)

ERP_PAGE_BG = "#F0F4F8"
ERP_HEADER_BG = "#3B7DD8"
ERP_PANEL_BG = "#FFFFFF"
ERP_BORDER = "#C8D4E3"
ERP_BTN_BLUE = "#337AB7"
ERP_BTN_GREEN = "#5CB85C"
ERP_BTN_GREY = "#6C757D"
ERP_TEXT = "#2C3E50"
ERP_MUTED = "#6C757D"
ERP_TABLE_HEAD = "#E8EEF5"
ERP_STATUS_BG = "#FFF8E6"

DECISION_STYLES = {
    "下单备货": {
        "badge_bg": "#E53935", "badge_fg": "white",
        "row_bg": "#FFCDD2", "row_bg_alt": "#FFEBEE", "row_fg": "#B71C1C",
    },
    "催促发货": {
        "badge_bg": "#FB8C00", "badge_fg": "white",
        "row_bg": "#FFE0B2", "row_bg_alt": "#FFF8E1", "row_fg": "#E65100",
    },
    "保持现状": {
        "badge_bg": "#43A047", "badge_fg": "white",
        "row_bg": "#C8E6C9", "row_bg_alt": "#E8F5E9", "row_fg": "#2E7D32",
    },
    "暂无销售": {
        "badge_bg": "#78909C", "badge_fg": "white",
        "row_bg": "#CFD8DC", "row_bg_alt": "#ECEFF1", "row_fg": "#546E7A",
    },
}
DECISION_ORDER = ["下单备货", "催促发货", "保持现状", "暂无销售"]

class InventoryDecisionSystem:
    def __init__(self, root):
        self.root = root
        self.root.title("智能库存决策系统 V4.8")
        self.root.geometry("1620x920")
        self.root.minsize(1200, 720)
        self.root.configure(bg=ERP_PAGE_BG)

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
        self._family_popup_visible = False
        self._image_by_sku = {}
        self._image_cache = {}
        self._row_photos = []
        self._placeholder_photo = None
        self._preload_status = ""

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
        style.configure("ERP.TLabelframe", padding=6, background=ERP_PANEL_BG, relief="flat", borderwidth=1)
        style.configure("ERP.TLabelframe.Label", background=ERP_PANEL_BG, foreground=ERP_TEXT, font=UI_FONT_BOLD)
        style.configure("ERP.Treeview",
                        background=ERP_ROW_EVEN,
                        foreground=ERP_TEXT,
                        fieldbackground=ERP_ROW_EVEN,
                        rowheight=TREE_ROW_HEIGHT,
                        borderwidth=0,
                        font=UI_FONT)
        style.configure("ERP.Treeview.Heading",
                        background=ERP_TABLE_HEAD,
                        foreground=ERP_TEXT,
                        font=UI_FONT_BOLD,
                        relief="flat",
                        borderwidth=1)
        style.map("ERP.Treeview",
                  background=[("selected", "#D6E9FF")],
                  foreground=[("selected", ERP_TEXT)])
        style.map("ERP.Treeview.Heading",
                  background=[("active", "#D6E9FF")])
        style.configure("ERP.TCombobox", padding=2)
        style.configure("ERP.TEntry", padding=2)

    def _bind_shortcuts(self):
        for key in ("<KeyPress-Shift_L>", "<KeyPress-Shift_R>"):
            self.root.bind(key, lambda e: setattr(self, "shift_pressed", True))
        for key in ("<KeyRelease-Shift_L>", "<KeyRelease-Shift_R>"):
            self.root.bind(key, lambda e: setattr(self, "shift_pressed", False))

    def _section(self, parent, title):
        outer = tk.Frame(parent, bg=ERP_PANEL_BG, highlightbackground=ERP_BORDER, highlightthickness=1)
        outer.pack(fill="x", padx=8, pady=(0, 6))
        tk.Label(outer, text=title, font=UI_FONT_BOLD, bg=ERP_PANEL_BG, fg=ERP_TEXT).pack(
            anchor="w", padx=8, pady=(6, 2))
        body = tk.Frame(outer, bg=ERP_PANEL_BG)
        body.pack(fill="x", padx=8, pady=(0, 6))
        return body

    def _frame(self, parent, bg=None):
        return tk.Frame(parent, bg=bg or ERP_PANEL_BG)

    def _lbl(self, parent, text, bold=False, fg=None):
        return tk.Label(parent, text=text, font=UI_FONT_BOLD if bold else UI_FONT,
                        bg=parent.cget("bg"), fg=fg or ERP_TEXT)

    def _erp_button(self, parent, text, command, color=ERP_BTN_BLUE, width=None):
        kw = dict(text=text, command=command, font=UI_FONT, bg=color, fg="white",
                  relief="flat", padx=10, pady=3, cursor="hand2")
        if width:
            kw["width"] = width
        return tk.Button(parent, **kw)

    def _set_combo_values(self, combo, values):
        combo["values"] = values

    def _set_label(self, label, text, color=ERP_TEXT):
        label.configure(text=text, fg=color)

    def _decision_tag(self, decision, stripe=0):
        if decision in DECISION_STYLES:
            return f"dec_{decision}_{stripe % 2}"
        return "even" if stripe % 2 == 0 else "odd"

    def _list_channel_folders(self, data_dir=None):
        data_dir = data_dir or self.data_dir.get()
        if not data_dir or not os.path.exists(data_dir):
            return []
        return sorted(
            d for d in os.listdir(data_dir)
            if os.path.isdir(os.path.join(data_dir, d)) and not d.startswith((".", "_"))
        )

    def _channels_settings_path(self, data_dir=None):
        data_dir = data_dir or self.data_dir.get()
        return os.path.join(data_dir, CHANNELS_SETTINGS_FILE)

    def _legacy_settings_paths(self, data_dir=None):
        data_dir = data_dir or self.data_dir.get()
        return [
            os.path.join(data_dir, name)
            for name in LEGACY_CHANNELS_SETTINGS_FILES
        ]

    def _parse_channels_settings_payload(self, loaded, document=None):
        document = document or {
            "_说明": "",
            "default": self._default_channel_settings(),
            "channels": {},
        }
        if not isinstance(loaded, dict):
            return document
        if isinstance(loaded.get("default"), dict):
            document["default"] = self._normalize_channel_entry(
                loaded["default"], self._default_channel_settings()
            )
        if isinstance(loaded.get("channels"), dict):
            document["channels"] = {
                str(name): self._normalize_channel_entry(entry, document["default"])
                for name, entry in loaded["channels"].items()
                if not str(name).startswith("_")
            }
        elif "LeadTime" in loaded or "LogisticsTime" in loaded:
            document["default"] = self._normalize_channel_entry(loaded, document["default"])
        if loaded.get("_说明"):
            document["_说明"] = str(loaded["_说明"])
        return document

    def _read_channels_settings_file(self, path):
        with open(path, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        return self._parse_channels_settings_payload(loaded)

    def migrate_channels_settings(self, data_dir=None):
        data_dir = data_dir or self.data_dir.get()
        if not data_dir or not os.path.exists(data_dir):
            return None, None
        primary = self._channels_settings_path(data_dir)
        candidates = []
        if os.path.exists(primary):
            candidates.append((primary, os.path.getmtime(primary)))
        for path in self._legacy_settings_paths(data_dir):
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict) and isinstance(loaded.get("channels"), dict):
                    candidates.append((path, os.path.getmtime(path)))
            except Exception:
                continue
        if not candidates:
            return None, None
        newest_path, _ = max(candidates, key=lambda item: item[1])
        try:
            document = self._read_channels_settings_file(newest_path)
        except Exception:
            return None, None
        channels = self._list_channel_folders(data_dir)
        default = document["default"]
        document["channels"] = {
            channel: self._normalize_channel_entry(document["channels"].get(channel), default)
            for channel in channels
        }
        self._save_channels_settings_document(document, data_dir)
        source_name = os.path.basename(newest_path)
        if newest_path != primary:
            return primary, source_name
        return primary, CHANNELS_SETTINGS_FILE

    def _default_channel_settings(self):
        return {
            "LeadTime": DEFAULT_LEAD_TIME,
            "LogisticsTime": DEFAULT_LOGISTICS_TIME,
            "备注": "",
        }

    def _normalize_channel_entry(self, entry, fallback=None):
        fallback = fallback or self._default_channel_settings()
        if not isinstance(entry, dict):
            entry = {}
        lead = entry.get("LeadTime", fallback["LeadTime"])
        logistics = entry.get("LogisticsTime", fallback["LogisticsTime"])
        try:
            lead = int(lead)
        except (TypeError, ValueError):
            lead = fallback["LeadTime"]
        try:
            logistics = int(logistics)
        except (TypeError, ValueError):
            logistics = fallback["LogisticsTime"]
        return {
            "LeadTime": lead,
            "LogisticsTime": logistics,
            "备注": str(entry.get("备注", fallback.get("备注", ""))),
        }

    def _load_channels_settings_document(self, data_dir=None):
        data_dir = data_dir or self.data_dir.get()
        document = {
            "_说明": (
                "放在数据根目录（例如 output 文件夹）。channels 下每个键名=SKU渠道文件夹名，"
                "可单独设置 LeadTime(采购交期天数) 和 LogisticsTime(物流周期天数)。"
            ),
            "default": self._default_channel_settings(),
            "channels": {},
        }
        if not data_dir:
            return document
        self.migrate_channels_settings(data_dir)
        path = self._channels_settings_path(data_dir)
        if not os.path.exists(path):
            return document
        try:
            return self._read_channels_settings_file(path)
        except Exception:
            return document

    def _save_channels_settings_document(self, document, data_dir=None):
        data_dir = data_dir or self.data_dir.get()
        if not data_dir:
            return False
        os.makedirs(data_dir, exist_ok=True)
        with open(self._channels_settings_path(data_dir), "w", encoding="utf-8") as f:
            json.dump(document, f, ensure_ascii=False, indent=2)
        return True

    def sync_channels_settings(self, data_dir=None):
        data_dir = data_dir or self.data_dir.get()
        if not data_dir or not os.path.exists(data_dir):
            return None
        document = self._load_channels_settings_document(data_dir)
        default = document["default"]
        channels = self._list_channel_folders(data_dir)
        merged = {}
        for channel in channels:
            if channel in document["channels"]:
                merged[channel] = self._normalize_channel_entry(document["channels"][channel], default)
            else:
                merged[channel] = self._normalize_channel_entry({}, default)
        document["channels"] = merged
        document["_说明"] = (
            "放在数据根目录(output)。channels 键名=SKU渠道子文件夹名(如918、996)。"
            "LeadTime=LT预估天数，LogisticsTime=物流预估天数。修改后切换渠道或点刷新生效。"
        )
        self._save_channels_settings_document(document, data_dir)
        return document

    def generate_channels_settings(self):
        data_dir = self.data_dir.get()
        if not data_dir or not os.path.exists(data_dir):
            messagebox.showerror("错误", "请先选择有效的数据根目录（output 文件夹）")
            return
        channels = self._list_channel_folders(data_dir)
        if not channels:
            messagebox.showerror("错误", "该目录下未找到任何 SKU 渠道子文件夹")
            return
        self.ensure_channels_settings_template(data_dir)
        document = self.sync_channels_settings(data_dir)
        settings_path = self._channels_settings_path(data_dir)
        channel = self.channel.get()
        if channel:
            self.apply_channel_settings(channel)
        self.update_file_status()
        preview = "\n".join(
            f"  · {name}: LT {document['channels'][name]['LeadTime']} / 物流 {document['channels'][name]['LogisticsTime']}"
            for name in channels[:12]
        )
        if len(channels) > 12:
            preview += f"\n  · ... 共 {len(channels)} 个渠道"
        messagebox.showinfo(
            "渠道配置已生成",
            f"已写入：\n{settings_path}\n\n"
            f"共扫描 {len(channels)} 个 SKU 渠道文件夹。\n"
            f"请用记事本打开上述文件，按需修改各渠道的 LeadTime / LogisticsTime。\n\n"
            f"预览：\n{preview}",
        )
        try:
            if sys.platform.startswith("win"):
                os.startfile(settings_path)  # noqa: S606
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", settings_path])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", settings_path])
        except Exception:
            pass

    def load_channel_settings(self, channel):
        if not channel:
            return self._default_channel_settings()
        document = self._load_channels_settings_document()
        default = document["default"]
        entry = document["channels"].get(channel)
        if entry is None:
            return self._normalize_channel_entry({}, default)
        return self._normalize_channel_entry(entry, default)

    def get_channel_settings_source(self, channel):
        document = self._load_channels_settings_document()
        if channel in document["channels"]:
            return CHANNELS_SETTINGS_FILE
        return "default"

    def apply_channel_settings(self, channel):
        settings = self.load_channel_settings(channel)
        self.lead_time.delete(0, tk.END)
        self.lead_time.insert(0, str(settings["LeadTime"]))
        self.logistics_time.delete(0, tk.END)
        self.logistics_time.insert(0, str(settings["LogisticsTime"]))
        return settings

    def save_channel_settings(self, channel, lead_time=None, logistics_time=None, note=None):
        if not channel:
            return False
        document = self.sync_channels_settings()
        if document is None:
            return False
        current = document["channels"].get(channel, document["default"])
        document["channels"][channel] = {
            "LeadTime": int(lead_time if lead_time is not None else self.lead_time.get()),
            "LogisticsTime": int(logistics_time if logistics_time is not None else self.logistics_time.get()),
            "备注": note if note is not None else current.get("备注", ""),
        }
        return self._save_channels_settings_document(document)

    def get_channel_timing(self, channel, use_ui=False):
        settings = self.load_channel_settings(channel)
        if use_ui:
            try:
                settings["LeadTime"] = int(self.lead_time.get())
                settings["LogisticsTime"] = int(self.logistics_time.get())
            except ValueError:
                pass
        return int(settings["LeadTime"]), int(settings["LogisticsTime"])

    def on_channel_changed(self):
        channel = self.channel.get()
        if channel:
            self.migrate_channels_settings()
            self.apply_channel_settings(channel)
        self.update_file_status()

    def ensure_channels_settings_template(self, data_dir=None):
        data_dir = data_dir or self.data_dir.get()
        if not data_dir or not os.path.exists(data_dir):
            return
        template_path = os.path.join(data_dir, CHANNELS_SETTINGS_TEMPLATE)
        if os.path.exists(template_path):
            return
        payload = {
            "_说明": (
                "复制为 channels_settings.json 放在数据根目录（output 文件夹）。"
                "channels 的键名必须与 SKU 渠道子文件夹名称一致，例如 918、996。"
            ),
            "default": {
                "LeadTime": DEFAULT_LEAD_TIME,
                "LogisticsTime": DEFAULT_LOGISTICS_TIME,
                "备注": "未单独配置的渠道使用 default",
            },
            "channels": {
                "918": {"LeadTime": 90, "LogisticsTime": 30, "备注": "示例：918 渠道"},
                "996": {"LeadTime": 120, "LogisticsTime": 45, "备注": "示例：996 渠道"},
            },
        }
        with open(template_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _decision_badge_text(self, decision, subset):
        if decision == "下单备货":
            vol = subset["备货体积"].sum()
            return f" {decision}  {len(subset)}行 · 备货 {vol:.3f} m³ "
        if decision == "催促发货":
            vol = subset["催发货体积"].sum()
            production = subset["在产库存"].sum()
            return f" {decision}  {len(subset)}行 · 在产 {production:.0f}件 · 催发 {vol:.3f} m³ "
        return f" {decision}  {len(subset)}行 "

    def _update_decision_badges(self, df):
        for widget in self.decision_badge_frame.winfo_children():
            widget.destroy()
        if self.result_data is None:
            return
        active = self.filter_decision.get()
        for decision in DECISION_ORDER:
            subset = self.result_data[self.result_data["决策建议"] == decision]
            if len(subset) == 0:
                continue
            style = DECISION_STYLES[decision]
            is_active = active == decision
            badge = tk.Label(
                self.decision_badge_frame,
                text=self._decision_badge_text(decision, subset),
                font=UI_FONT_BOLD,
                bg=style["badge_bg"],
                fg=style["badge_fg"],
                padx=2,
                pady=3,
                cursor="hand2",
                relief="solid",
                borderwidth=2 if is_active else 0,
                highlightbackground="#2C3E50" if is_active else style["badge_bg"],
                highlightthickness=2 if is_active else 0,
            )
            badge.pack(side="left", padx=(0, 8), pady=2)
            badge.bind("<Button-1>", lambda _e, d=decision: self._on_decision_badge_click(d))

    def _on_decision_badge_click(self, decision):
        if self.filter_decision.get() == decision:
            self.filter_decision.set("全部")
        else:
            self.filter_decision.set(decision)
        self.decision_combo.set(self.filter_decision.get())
        self.refresh_display()

    def _family_matches(self, query):
        query = (query or "").strip()
        if not query or query == "全部":
            return list(self.family_list)
        q = query.lower()
        starts = [f for f in self.family_list if f != "全部" and f.lower().startswith(q)]
        contains = [f for f in self.family_list if f != "全部" and q in f.lower() and f not in starts]
        all_match = ["全部"] if q in "全部" or "全部".startswith(q) else []
        return all_match + starts + contains if (all_match or starts or contains) else list(self.family_list)

    def _best_family_match(self, typed, matches):
        typed_l = typed.strip().lower()
        if not typed_l:
            return None
        for item in matches:
            if item.lower().startswith(typed_l):
                return item
        return matches[0] if matches else None

    def _show_family_popup(self, matches):
        if not matches:
            self._hide_family_popup()
            return
        self.family_popup.delete(0, tk.END)
        for item in matches[:12]:
            self.family_popup.insert(tk.END, item)
        self.family_combo.update_idletasks()
        x = self.family_combo.winfo_rootx() - self.root.winfo_rootx()
        y = self.family_combo.winfo_rooty() - self.root.winfo_rooty() + self.family_combo.winfo_height()
        w = max(self.family_combo.winfo_width(), 180)
        rows = min(len(matches), 8)
        self.family_popup.place(x=x, y=y, width=w, height=rows * 22 + 4)
        self._family_popup_visible = True

    def _hide_family_popup(self):
        if hasattr(self, "family_popup"):
            self.family_popup.place_forget()
        self._family_popup_visible = False

    def _apply_family_value(self, value):
        self.filter_family.set(value)
        self._hide_family_popup()
        self.refresh_display()

    def _on_family_popup_select(self, _event=None):
        sel = self.family_popup.curselection()
        if sel:
            self._apply_family_value(self.family_popup.get(sel[0]))
        self.family_combo.focus_set()

    def setup_ui(self):
        header = tk.Frame(self.root, bg=ERP_HEADER_BG)
        header.pack(fill="x")
        header_inner = self._frame(header, ERP_HEADER_BG)
        header_inner.pack(fill="x", padx=10, pady=8)
        tk.Label(header_inner, text="智能库存决策系统 V4.8", font=UI_TITLE_FONT,
                 bg=ERP_HEADER_BG, fg="white").pack(side="left")
        tk.Label(header_inner, text="库存决策 · 订柜监控", font=UI_FONT,
                 bg=ERP_HEADER_BG, fg="#DCEBFF").pack(side="left", padx=(12, 0))
        btn_box = self._frame(header_inner, ERP_HEADER_BG)
        btn_box.pack(side="right")
        self._erp_button(btn_box, "生成分析报告", self.generate_analysis, ERP_BTN_GREEN, 12).pack(side="left", padx=(0, 6))
        self._erp_button(btn_box, "导出 Excel", self.export_excel, ERP_BTN_BLUE, 10).pack(side="left")

        toolbar = tk.Frame(self.root, bg=ERP_PANEL_BG, highlightbackground=ERP_BORDER, highlightthickness=1)
        toolbar.pack(fill="x", padx=8, pady=(6, 4))

        row1 = self._frame(toolbar)
        row1.pack(fill="x", padx=8, pady=(6, 4))
        self._lbl(row1, "数据目录").pack(side="left")
        self.dir_entry = ttk.Entry(row1, textvariable=self.data_dir, width=42, style="ERP.TEntry")
        self.dir_entry.pack(side="left", padx=(4, 4))
        self._erp_button(row1, "浏览", self.select_data_dir, ERP_BTN_GREY, 6).pack(side="left", padx=(0, 10))
        self._lbl(row1, "渠道").pack(side="left")
        self.channel_combo = ttk.Combobox(row1, textvariable=self.channel, width=10, state="readonly", style="ERP.TCombobox")
        self.channel_combo.pack(side="left", padx=(4, 4))
        self.channel_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_channel_changed())
        self._erp_button(row1, "刷新", lambda: self.refresh_channels(), ERP_BTN_GREY, 5).pack(side="left", padx=(0, 6))
        self._erp_button(row1, "更新渠道配置", self.generate_channels_settings, ERP_BTN_BLUE, 10).pack(side="left", padx=(0, 14))
        self._lbl(row1, "Lead Time").pack(side="left")
        self.lead_time = ttk.Entry(row1, width=5, style="ERP.TEntry")
        self.lead_time.insert(0, "90")
        self.lead_time.pack(side="left", padx=(4, 10))
        self._lbl(row1, "物流").pack(side="left")
        self.logistics_time = ttk.Entry(row1, width=5, style="ERP.TEntry")
        self.logistics_time.insert(0, "30")
        self.logistics_time.pack(side="left", padx=(4, 14))
        self._lbl(row1, "扫描(分)").pack(side="left")
        self.interval_entry = ttk.Entry(row1, width=5, style="ERP.TEntry")
        self.interval_entry.insert(0, str(self.auto_scan_interval))
        self.interval_entry.pack(side="left", padx=(4, 6))
        self.auto_btn = self._erp_button(row1, "自动扫描", self.toggle_auto_scan, ERP_BTN_GREEN, 8)
        self.auto_btn.pack(side="left", padx=(0, 8))
        self.auto_status = self._lbl(row1, "已停止", fg=ERP_MUTED)
        self.auto_status.pack(side="left")

        self.file_status_label = self._lbl(toolbar, "请选择数据根目录", fg=ERP_MUTED)
        self.file_status_label.pack(anchor="w", padx=8, pady=(0, 4))

        row2 = self._frame(toolbar)
        row2.pack(fill="x", padx=8, pady=(0, 6))
        self._lbl(row2, "地区").pack(side="left")
        self.region_combo = ttk.Combobox(row2, textvariable=self.filter_region, width=8,
                                         values=["全部", "北岛", "南岛"], state="readonly", style="ERP.TCombobox")
        self.region_combo.pack(side="left", padx=(4, 10))
        self.region_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_display())
        self._lbl(row2, "决策").pack(side="left")
        self.decision_combo = ttk.Combobox(row2, textvariable=self.filter_decision, width=10,
            values=["全部", "下单备货", "催促发货", "保持现状", "暂无销售"], state="readonly", style="ERP.TCombobox")
        self.decision_combo.pack(side="left", padx=(4, 10))
        self.decision_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_display())
        self._lbl(row2, "Family").pack(side="left")
        self.family_combo = ttk.Combobox(row2, textvariable=self.filter_family, width=18,
                                         values=self.family_list, style="ERP.TCombobox")
        self.family_combo.pack(side="left", padx=(4, 6))
        self.family_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_family_selected())
        self.family_combo.bind("<KeyRelease>", self.on_family_keyrelease)
        self.family_combo.bind("<Return>", self.on_family_return)
        self.family_combo.bind("<Escape>", lambda _e: self._hide_family_popup())
        self.family_combo.bind("<FocusOut>", lambda _e: self.root.after(150, self._hide_family_popup))
        self.family_popup = tk.Listbox(self.root, height=8, font=UI_FONT, bg="white", fg=ERP_TEXT,
                                       selectbackground=ERP_BTN_BLUE, selectforeground="white",
                                       relief="solid", borderwidth=1, highlightthickness=0)
        self.family_popup.bind("<ButtonRelease-1>", self._on_family_popup_select)
        self.family_popup.bind("<Return>", self._on_family_popup_select)
        self._erp_button(row2, "重置", self.reset_filters, ERP_BTN_GREY, 5).pack(side="left", padx=(4, 14))
        self._lbl(row2, "主排序").pack(side="left")
        self.sort_primary_combo = ttk.Combobox(row2, textvariable=self.sort_primary_var, width=11,
                                               values=SORT_OPTIONS, state="readonly", style="ERP.TCombobox")
        self.sort_primary_combo.pack(side="left", padx=(4, 2))
        self.sort_primary_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_sort_control_change())
        self.sort_primary_dir_btn = tk.Button(row2, text="↑", width=2, font=UI_FONT, relief="flat",
                                              bg=ERP_TABLE_HEAD, command=self.toggle_primary_sort_dir)
        self.sort_primary_dir_btn.pack(side="left", padx=(0, 8))
        self._lbl(row2, "次排序").pack(side="left")
        self.sort_secondary_combo = ttk.Combobox(row2, textvariable=self.sort_secondary_var, width=11,
                                                 values=SORT_OPTIONS, state="readonly", style="ERP.TCombobox")
        self.sort_secondary_combo.pack(side="left", padx=(4, 2))
        self.sort_secondary_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_sort_control_change())
        self.sort_secondary_dir_btn = tk.Button(row2, text="↑", width=2, font=UI_FONT, relief="flat",
                                                bg=ERP_TABLE_HEAD, command=self.toggle_secondary_sort_dir)
        self.sort_secondary_dir_btn.pack(side="left", padx=(0, 6))
        self._erp_button(row2, "清除次排", self.clear_secondary_sort, ERP_BTN_GREY, 7).pack(side="left", padx=(0, 8))
        self.sort_status_label = self._lbl(row2, "排序：默认", fg=ERP_MUTED)
        self.sort_status_label.pack(side="left")

        status_bar = tk.Frame(self.root, bg=ERP_STATUS_BG, highlightbackground="#F0D78C", highlightthickness=1)
        status_bar.pack(fill="x", padx=8, pady=(0, 4))
        self.container_status_label = tk.Label(status_bar, text="等待分析...", font=UI_FONT_BOLD,
                                               bg=ERP_STATUS_BG, fg=ERP_TEXT, justify="left", anchor="w")
        self.container_status_label.pack(fill="x", padx=8, pady=(4, 2))
        self.decision_badge_frame = tk.Frame(status_bar, bg=ERP_STATUS_BG)
        self.decision_badge_frame.pack(fill="x", padx=8, pady=(0, 2))
        self.volume_detail_label = tk.Label(status_bar, text="", font=UI_FONT,
                                            bg=ERP_STATUS_BG, fg=ERP_MUTED, justify="left", anchor="w")
        self.volume_detail_label.pack(fill="x", padx=8, pady=(0, 4))

        table_section = tk.Frame(self.root, bg=ERP_PANEL_BG, highlightbackground=ERP_BORDER, highlightthickness=1)
        table_section.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        head = self._frame(table_section)
        head.pack(fill="x", padx=8, pady=(6, 4))
        self._lbl(head, "分析结果", bold=True).pack(side="left")
        self._lbl(head, "（点击表头排序，Shift+点击设次排序）", fg=ERP_MUTED).pack(side="left", padx=(8, 12))
        self.decision_legend_frame = tk.Frame(head, bg=ERP_PANEL_BG)
        self.decision_legend_frame.pack(side="left")
        for decision in DECISION_ORDER:
            style = DECISION_STYLES[decision]
            tk.Label(self.decision_legend_frame, text=f" {decision} ", font=UI_FONT,
                     bg=style["badge_bg"], fg=style["badge_fg"], padx=4, pady=1).pack(side="left", padx=(0, 4))

        table_wrap = self._frame(table_section)
        table_wrap.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        table_wrap.grid_columnconfigure(0, weight=1)
        table_wrap.grid_rowconfigure(0, weight=1)

        columns = ("SKU", "Name", "ProductFamily", "地区", "在库库存", "在途库存", "在产库存", "总量库存",
                   "8-30天", "15天", "30天", "采用需求", "需求来源",
                   "LT预估", "物流预估", "决策建议", "建议订货量", "体积系数", "备货体积", "催发货体积", "详细说明")
        self.tree = ttk.Treeview(table_wrap, columns=columns, show="tree headings",
                                 height=12, style="ERP.Treeview")
        self.column_display_names = columns
        self.tree.heading("#0", text="产品图")
        self.tree.column("#0", width=72, stretch=False, anchor="center")

        col_widths = [78, 150, 88, 50, 62, 62, 62, 62, 58, 58, 58, 68, 76, 72, 72, 82, 72, 68, 72, 76, 150]
        for col, width in zip(columns, col_widths):
            self.tree.heading(col, text=col, command=lambda c=col: self.on_header_click(c))
            anchor = "w" if col in ("Name", "详细说明", "ProductFamily") else "center"
            self.tree.column(col, width=width, anchor=anchor, stretch=False)

        scrollbar_y = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        scrollbar_x = ttk.Scrollbar(table_wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        scrollbar_x.grid(row=1, column=0, sticky="ew")

        self.tree.tag_configure("even", background=ERP_ROW_EVEN, foreground=ERP_TEXT)
        self.tree.tag_configure("odd", background=ERP_ROW_ODD, foreground=ERP_TEXT)
        for decision, style in DECISION_STYLES.items():
            for stripe, bg_key in enumerate(("row_bg", "row_bg_alt")):
                self.tree.tag_configure(
                    self._decision_tag(decision, stripe),
                    background=style[bg_key],
                    foreground=style["row_fg"],
                )

        footer = tk.Frame(self.root, bg=ERP_PANEL_BG, highlightbackground=ERP_BORDER, highlightthickness=1)
        footer.pack(fill="x", padx=8, pady=(0, 8))
        self.summary_label = tk.Label(footer, text="等待分析...", font=UI_MONO_FONT,
                                      justify="left", anchor="w", bg=ERP_PANEL_BG, fg=ERP_TEXT)
        self.summary_label.pack(fill="x", padx=8, pady=6)

        self.help_visible = tk.BooleanVar(value=False)
        self.help_frame = tk.Frame(self.root, bg=ERP_PANEL_BG, highlightbackground=ERP_BORDER, highlightthickness=1)
        help_text = (
            "数据：stock.csv 需含 ImageUrl  |  在数据根目录(output)放 channels_settings.json 配置各 SKU 的 LT/物流天数  |  "
            "PO：无 ContainerNumber=在产，有=在途"
        )
        self.help_label = tk.Label(self.help_frame, text=help_text, justify="left",
                                   font=UI_FONT, fg=ERP_MUTED, bg=ERP_PANEL_BG)
        self.help_label.pack(anchor="w", padx=8, pady=6)

    def toggle_help(self):
        if self.help_visible.get():
            self.help_frame.pack_forget()
            self.help_visible.set(False)
        else:
            self.help_frame.pack(fill="x", padx=8, pady=(0, 4), before=self.summary_label.master)
            self.help_visible.set(True)

    def _normalize_image_url(self, url):
        if url is None or (isinstance(url, float) and pd.isna(url)):
            return ""
        url = str(url).strip()
        if not url:
            return ""
        if not url.lower().startswith("http"):
            url = ERP_IMAGE_BASE + url.replace("\\", "/").lstrip("/")
        parts = urlsplit(url)
        path = quote(parts.path, safe="/:%")
        return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))

    def _build_image_url_column(self, stock_wide):
        if 'ImageUrl' in stock_wide.columns:
            return stock_wide['ImageUrl'].fillna('').astype(str).str.strip()
        if 'ImagePath' in stock_wide.columns:
            return stock_wide['ImagePath'].apply(
                lambda p: self._normalize_image_url(p) if pd.notna(p) and str(p).strip() else ""
            )
        return pd.Series([''] * len(stock_wide), index=stock_wide.index)

    def _update_image_lookup(self, df):
        self._image_by_sku = {}
        if df is None or 'ImageUrl' not in df.columns:
            return
        for _, row in df.drop_duplicates(subset=['Sku']).iterrows():
            url = self._normalize_image_url(row.get('ImageUrl', ''))
            if url:
                self._image_by_sku[str(row['Sku'])] = url

    def _get_placeholder_photo(self):
        if self._placeholder_photo is None:
            img = Image.new("RGB", IMAGE_THUMB_SIZE, "#E2E8F0")
            self._placeholder_photo = ImageTk.PhotoImage(img)
        return self._placeholder_photo

    def _photo_for_sku(self, sku):
        url = self._image_by_sku.get(str(sku), "")
        if url and url in self._image_cache:
            return self._image_cache[url]
        return self._get_placeholder_photo()

    def _download_image_photo(self, url):
        if url in self._image_cache:
            return self._image_cache[url]
        try:
            req = Request(url, headers={"User-Agent": "InventoryDecisionSystem/4.8"})
            with urlopen(req, timeout=12) as resp:
                data = resp.read()
            img = Image.open(io.BytesIO(data))
            img.thumbnail(IMAGE_THUMB_SIZE, getattr(Image, "Resampling", Image).LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._image_cache[url] = photo
            return photo
        except Exception:
            return None

    def _preload_images_async(self):
        urls = list({u for u in self._image_by_sku.values() if u})
        if not urls:
            return

        total = len(urls)
        self._preload_status = f"正在预加载产品图 0/{total}..."

        def worker():
            loaded = 0
            for url in urls:
                if url not in self._image_cache:
                    self._download_image_photo(url)
                loaded += 1
                if loaded % 5 == 0 or loaded == total:
                    n = loaded
                    self._preload_status = f"正在预加载产品图 {n}/{total}..."

            def done():
                self._preload_status = ""
                self.refresh_display()

            self.root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

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
            channels = self._list_channel_folders(data_dir)
            self._set_combo_values(self.channel_combo, channels)
            if channels:
                self.ensure_channels_settings_template(data_dir)
                self.sync_channels_settings(data_dir)
                self.channel_combo.set(channels[0])
                self.apply_channel_settings(channels[0])
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
        settings = self.load_channel_settings(ch)
        settings_path = self._channels_settings_path(dir_path)
        migrated_path, migrated_from = self.migrate_channels_settings(dir_path)
        if migrated_path and os.path.exists(migrated_path):
            settings = self.load_channel_settings(ch)
            if migrated_from and migrated_from != CHANNELS_SETTINGS_FILE:
                status_lines.append(
                    f"✓ 已从 {migrated_from} 生成 {CHANNELS_SETTINGS_FILE} · "
                    f"[{ch}] LT {settings['LeadTime']} / 物流 {settings['LogisticsTime']}"
                )
            elif ch in self._load_channels_settings_document(dir_path).get("channels", {}):
                status_lines.append(
                    f"✓ {CHANNELS_SETTINGS_FILE} · [{ch}] LT {settings['LeadTime']} / 物流 {settings['LogisticsTime']}"
                )
            else:
                status_lines.append(
                    f"○ {CHANNELS_SETTINGS_FILE} 已存在，但 [{ch}] 未单独配置 · "
                    f"使用 default LT {settings['LeadTime']} / 物流 {settings['LogisticsTime']}"
                )
        else:
            status_lines.append(
                f"○ 未找到 {CHANNELS_SETTINGS_FILE}（请点「更新渠道配置」生成；不要只改 template 文件）· "
                f"[{ch}] 默认 LT {settings['LeadTime']} / 物流 {settings['LogisticsTime']}"
            )
        self._set_label(self.file_status_label, "  |  ".join(status_lines),
                        "#16A34A" if all_ready else "#DC2626")
        return all_ready

    def on_family_selected(self, _value=None):
        self._hide_family_popup()
        self.refresh_display()

    def on_family_return(self, _event=None):
        typed = self.filter_family.get().strip()
        matches = self._family_matches(typed)
        best = self._best_family_match(typed, matches)
        if best:
            self.filter_family.set(best)
        self._hide_family_popup()
        self.refresh_display()
        return "break"

    def on_family_keyrelease(self, event):
        if event.keysym in ("Up", "Down", "Shift_L", "Shift_R", "Control_L", "Control_R"):
            if event.keysym == "Down" and self._family_popup_visible:
                self.family_popup.focus_set()
            return
        if event.keysym == "Escape":
            self._hide_family_popup()
            return
        if event.keysym == "Return":
            return

        typed = self.filter_family.get()
        matches = self._family_matches(typed)
        self._set_combo_values(self.family_combo, matches)

        if typed.strip():
            best = self._best_family_match(typed, matches)
            if best and best.lower().startswith(typed.strip().lower()) and len(best) > len(typed.strip()):
                pos = len(typed.strip())
                self.filter_family.set(best)
                self.family_combo.icursor(pos)
                self.family_combo.selection_range(pos, tk.END)
            if len(matches) > 1 or (len(matches) == 1 and matches[0].lower() != typed.strip().lower()):
                self._show_family_popup(matches)
            else:
                self._hide_family_popup()
        else:
            self._hide_family_popup()

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
        self._hide_family_popup()
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
            if len(df) == 0 and self.result_data is not None:
                fuzzy = self.result_data[
                    self.result_data['ProductFamily'].str.lower().str.contains(family.lower(), na=False)
                    | self.result_data['Name'].str.lower().str.contains(family.lower(), na=False)
                ]
                if len(fuzzy) > 0:
                    df = fuzzy
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
        self._update_decision_badges(df)

        detail = f"备货合计 {total_order:.3f} m³  |  催发合计 {total_expedite:.3f} m³"
        if self._filters_active():
            detail += f"  |  当前筛选显示 {len(df)} 行"
        self._set_label(self.volume_detail_label, detail, "#475569")

    def refresh_display(self):
        if self.result_data is None:
            return
        self._row_photos = []
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

        for idx, (_, row) in enumerate(df.iterrows()):
            values = (
                row['Sku'], row['Name'], row['ProductFamily'], row['Region'],
                f"{row['在库库存']:.0f}", f"{row['在途库存']:.0f}", f"{row['在产库存']:.0f}",
                f"{row['总量库存']:.0f}", f"{row['需求_8_30天']:.3f}", f"{row['需求_15天']:.3f}",
                f"{row['需求_30天']:.3f}", f"{row['日均需求']:.3f}", row['需求来源'],
                f"{row['LT预估']:.1f}", f"{row['物流预估']:.1f}", row['决策建议'],
                f"{row['建议订货量']:.0f}" if row['建议订货量'] > 0 else "-",
                f"{row['PriceRadarVolume']:.5f}",
                f"{row['备货体积']:.4f}" if row['备货体积'] > 0 else "-",
                f"{row['催发货体积']:.4f}" if row['催发货体积'] > 0 else "-",
                row['详细说明']
            )
            photo = self._photo_for_sku(row['Sku'])
            self._row_photos.append(photo)
            decision = row['决策建议']
            row_tag = self._decision_tag(decision, idx)
            self.tree.insert("", "end", text="", image=photo, values=values, tags=(row_tag,))

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
        preload_hint = getattr(self, "_preload_status", "")
        summary = (f"当前显示：{len(df)} 行{filter_hint}  |  "
                   f"需下单：{len(order_df)}  |  需催发：{len(expedite_df)}  |  "
                   f"备货体积：北岛 {north_order:.3f} / 南岛 {south_order:.3f} / 合计 {total_order:.3f} m³  |  "
                   f"催发体积：北岛 {north_expedite:.3f} / 南岛 {south_expedite:.3f} / 合计 {total_expedite:.3f} m³")
        if preload_hint:
            summary += f"  |  {preload_hint}"
        self._set_label(self.summary_label, summary)

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
        self.auto_btn.configure(text="停止扫描", bg="#D9534F")
        self._set_label(self.auto_status, f"运行中 / {self.auto_scan_interval}分钟", "#449D44")
        self.scan_all_channels()

    def stop_auto_scan(self):
        self.auto_scanning = False
        if self.scan_job_id:
            self.root.after_cancel(self.scan_job_id)
            self.scan_job_id = None
        self.auto_btn.configure(text="自动扫描", bg=ERP_BTN_GREEN)
        self._set_label(self.auto_status, "已停止", ERP_MUTED)
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
            all_channels = self._list_channel_folders(data_dir)
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

        self.apply_channel_settings(ch)
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
            stock_wide['ImageUrl'] = self._build_image_url_column(stock_wide)

            # 检查新格式：包含 Name 和 ProductFamily
            has_name = 'Name' in stock_wide.columns
            has_family = 'ProductFamily' in stock_wide.columns

            if 'SouthIslandStock' in stock_wide.columns and 'NorthIslandStock' in stock_wide.columns:
                id_vars = ['Sku', 'PriceRadarVolume', 'IsDiscontinued', 'ImageUrl']
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

            def _is_empty_value(val):
                if pd.isna(val):
                    return True
                val_str = str(val).strip().lower()
                return val_str in ('', 'nan', 'nat', 'none', 'null')

            po_df['NotCheckedIn'] = po_df['CheckinDate'].apply(_is_empty_value)
            if 'ContainerNumber' in po_df.columns:
                po_df['HasContainer'] = po_df['ContainerNumber'].apply(lambda v: not _is_empty_value(v))
                transit_rows = po_df[po_df['NotCheckedIn'] & po_df['HasContainer']]
                production_rows = po_df[po_df['NotCheckedIn'] & ~po_df['HasContainer']]
            else:
                transit_rows = po_df[po_df['NotCheckedIn']]
                production_rows = po_df.iloc[0:0]

            in_transit = transit_rows.groupby(['Sku', 'Region'])['QuantityOrdered'].sum().reset_index()
            in_transit.rename(columns={'QuantityOrdered': '在途库存'}, inplace=True)
            in_production = production_rows.groupby(['Sku', 'Region'])['QuantityOrdered'].sum().reset_index()
            in_production.rename(columns={'QuantityOrdered': '在产库存'}, inplace=True)

            all_skus = pd.concat([
                stock_df[['Sku', 'Region']],
                po_df[['Sku', 'Region']],
                sales_8_30_df[['Sku', 'Region']],
                sales_15_df[['Sku', 'Region']],
                sales_30_df[['Sku', 'Region']]
            ], ignore_index=True).drop_duplicates()

            # 合并时保留 Name 和 ProductFamily
            merge_cols = ['Sku', 'Region', '在库库存', 'PriceRadarVolume', 'IsDiscontinued', 'ImageUrl']
            if 'Name' in stock_df.columns:
                merge_cols.append('Name')
            if 'ProductFamily' in stock_df.columns:
                merge_cols.append('ProductFamily')

            df = pd.merge(all_skus, stock_df[merge_cols], 
                          on=['Sku', 'Region'], how='left')
            df = pd.merge(df, in_transit, on=['Sku', 'Region'], how='left')
            df = pd.merge(df, in_production, on=['Sku', 'Region'], how='left')

            df['在途库存'] = df['在途库存'].fillna(0)
            df['在产库存'] = df['在产库存'].fillna(0)
            df['在库库存'] = df['在库库存'].fillna(0)
            df['总量库存'] = df['在库库存'] + df['在途库存'] + df['在产库存']
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
            if 'ImageUrl' in df.columns:
                df['ImageUrl'] = df['ImageUrl'].fillna('').astype(str).str.strip()
            else:
                df['ImageUrl'] = ''

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

            lt_days, log_days = self.get_channel_timing(
                target_channel,
                use_ui=(channel_override is None),
            )
            try:
                self.save_channel_settings(target_channel, lead_time=lt_days, logistics_time=log_days)
            except (ValueError, OSError):
                pass
            df['LT预估'] = df['日均需求'] * lt_days
            df['物流预估'] = df['日均需求'] * log_days

            def decide(row):
                total = row['总量库存']
                in_stock = row['在库库存']
                transit = row['在途库存']
                production = row['在产库存']
                daily = row['日均需求']
                lt_need = row['LT预估']
                log_need = row['物流预估']
                source = row['需求来源']
                price_vol = row['PriceRadarVolume']

                if daily == 0:
                    return ("暂无销售", 0, 0,
                            f"无销售记录，当前库存: 现货{in_stock:.0f}+在途{transit:.0f}+在产{production:.0f}")
                if total <= lt_need:
                    order_qty = max(0, lt_need - total)
                    order_vol = order_qty * price_vol
                    return ("下单备货", order_qty, order_vol,
                           f"总库存{total:.0f}≤{lt_days}天需求({lt_need:.1f})，缺口{order_qty:.0f}，体积{order_vol:.4f}m³，基于{source}")
                elif (in_stock + transit) <= log_need and production > 0:
                    expedite_vol = production * price_vol
                    return ("催促发货", 0, 0,
                           f"现货+在途{in_stock + transit:.0f}≤{log_days}天物流需求({log_need:.1f})，"
                           f"需催在产{production:.0f}件尽快发货，催发货体积{expedite_vol:.4f}m³")
                else:
                    days = total / daily if daily > 0 else 0
                    if (in_stock + transit) <= log_need and production == 0:
                        return ("保持现状", 0, 0,
                               f"现货+在途{in_stock + transit:.0f}≤{log_days}天物流需求({log_need:.1f})，"
                               f"无在产可催，总库存可撑{days:.0f}天")
                    return ("保持现状", 0, 0,
                           f"库存充足(现货{in_stock:.0f}+在途{transit:.0f}+在产{production:.0f})，基于{source}可撑{days:.0f}天")

            decisions = df.apply(decide, axis=1)
            df['决策建议'] = [d[0] for d in decisions]
            df['建议订货量'] = [d[1] for d in decisions]
            df['备货体积'] = [d[2] for d in decisions]
            df['详细说明'] = [d[3] for d in decisions]
            df['催发货体积'] = 0.0
            expedite_mask = df['决策建议'] == '催促发货'
            df.loc[expedite_mask, '催发货体积'] = (
                df.loc[expedite_mask, '在产库存'] * df.loc[expedite_mask, 'PriceRadarVolume']
            )

            priority = {"下单备货": 0, "催促发货": 1, "保持现状": 2, "暂无销售": 3}
            df['优先级'] = df['决策建议'].map(priority)
            df = df.sort_values(['优先级', 'Sku'])

            self.result_data = df
            self._image_cache = {}
            self._update_image_lookup(df)
            self.sort_primary = None
            self.sort_secondary = None
            self.sort_primary_asc = True
            self.sort_secondary_asc = True
            self.update_sort_status()
            self.refresh_display()
            self._preload_images_async()

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
        if 'ImageUrl' not in data.columns:
            data = data.copy()
            data['ImageUrl'] = ''
        cols = ['Sku', 'Name', 'ProductFamily', 'Region', '在库库存', '在途库存', '在产库存', '总量库存',
               '需求_8_30天', '需求_15天', '需求_30天', '日均需求', '需求来源',
               'LT预估', '物流预估', '决策建议', '建议订货量', 'PriceRadarVolume', '备货体积', '催发货体积', 'ImageUrl', '详细说明']

        export_df = data[cols].copy()
        export_df.columns = ['SKU', 'Name', 'ProductFamily', '地区', '在库库存', '在途库存', '在产库存', '总量库存',
                           '8-30天日均', '15天日均', '30天日均', '采用日均需求', '需求来源',
                           'LeadTime周期需求', '物流周期需求', '决策建议', '建议订货量', '体积系数',
                           '备货体积(m³)', '催发货体积(m³)', 'ImageUrl', '详细说明']

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
        root.configure(bg=ERP_PAGE_BG)
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
