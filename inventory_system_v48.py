import pandas as pd
import os
import json
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

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

import sys

class InventoryDecisionSystem:
    def __init__(self, root):
        self.root = root
        self.root.title("智能库存决策系统 V4.8 - 多重排序+Family筛选版")
        self.root.geometry("1550x1150")

        base_dir = get_base_dir()
        self.default_data_dir = os.path.join(base_dir, "data")
        self.default_output_dir = os.path.join(base_dir, "output")
        os.makedirs(self.default_output_dir, exist_ok=True)

        self.data_dir = tk.StringVar()
        self.channel = tk.StringVar()
        self.filter_region = tk.StringVar(value="全部")
        self.filter_decision = tk.StringVar(value="全部")
        self.filter_family = tk.StringVar(value="全部")  # 新增：ProductFamily筛选

        # 多重排序：primary + secondary
        self.sort_primary = None
        self.sort_secondary = None
        self.sort_primary_asc = True
        self.sort_secondary_asc = True

        self.result_data = None
        self.family_list = []  # 动态ProductFamily列表

        self.auto_scanning = False
        self.scan_job_id = None

        self.load_config()

        # 路径智能纠正
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

        self.setup_ui()
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

    def setup_ui(self):
        title_label = tk.Label(self.root, text="智能库存决策系统 V4.8", font=("Arial", 16, "bold"))
        title_label.pack(pady=5)

        subtitle = tk.Label(self.root, text="多重排序 | ProductFamily筛选 | 归档索引", 
                           font=("Arial", 10), fg="blue")
        subtitle.pack()

        # 数据源配置
        dir_frame = tk.LabelFrame(self.root, text="数据源配置（文件夹模式）", padx=10, pady=10)
        dir_frame.pack(fill="x", padx=20, pady=5)

        tk.Label(dir_frame, text="数据根目录:").grid(row=0, column=0, sticky="w")
        self.dir_entry = tk.Entry(dir_frame, textvariable=self.data_dir, width=50)
        self.dir_entry.grid(row=0, column=1, padx=5)
        tk.Button(dir_frame, text="浏览", command=self.select_data_dir).grid(row=0, column=2)

        tk.Label(dir_frame, text="选择渠道:").grid(row=0, column=3, sticky="w", padx=(20,0))
        self.channel_combo = ttk.Combobox(dir_frame, textvariable=self.channel, width=15, state="readonly")
        self.channel_combo.grid(row=0, column=4, padx=5)
        tk.Button(dir_frame, text="刷新渠道列表", command=lambda: self.refresh_channels()).grid(row=0, column=5, padx=5)

        # 自动扫描控制区
        auto_frame = tk.LabelFrame(self.root, text="Auto Scan Settings (Scan ALL channels)", padx=10, pady=8, fg="#1565C0")
        auto_frame.pack(fill="x", padx=20, pady=5)

        tk.Label(auto_frame, text="Interval(min):").grid(row=0, column=0, sticky="w")
        self.interval_entry = tk.Entry(auto_frame, width=8)
        self.interval_entry.insert(0, str(self.auto_scan_interval))
        self.interval_entry.grid(row=0, column=1, padx=5)

        self.auto_btn = tk.Button(auto_frame, text="Start Auto Scan", command=self.toggle_auto_scan,
                                 bg="#4CAF50", fg="white", width=16, font=("Arial", 9, "bold"))
        self.auto_btn.grid(row=0, column=2, padx=10)

        self.auto_status = tk.Label(auto_frame, text="Status: Stopped", fg="gray", font=("Arial", 9))
        self.auto_status.grid(row=0, column=3, padx=10)

        tk.Label(auto_frame, text=f"Archive Root: {self.default_output_dir}", 
                fg="#666666", font=("Consolas", 8)).grid(row=1, column=0, columnspan=6, sticky="w", pady=(5,0))

        self.file_status_label = tk.Label(dir_frame, text="请选择数据根目录并刷新渠道列表", fg="gray", font=("Consolas", 9))
        self.file_status_label.grid(row=1, column=0, columnspan=6, sticky="w", pady=(5,0))

        # 参数设置
        param_frame = tk.LabelFrame(self.root, text="时间参数设置（天）", padx=10, pady=10)
        param_frame.pack(fill="x", padx=20, pady=5)

        tk.Label(param_frame, text="Lead Time（采购周期）:").grid(row=0, column=0, sticky="w")
        self.lead_time = tk.Entry(param_frame, width=10)
        self.lead_time.insert(0, "90")
        self.lead_time.grid(row=0, column=1, padx=5)

        tk.Label(param_frame, text="物流时间（在途周期）:").grid(row=0, column=2, sticky="w", padx=(20,0))
        self.logistics_time = tk.Entry(param_frame, width=10)
        self.logistics_time.insert(0, "30")
        self.logistics_time.grid(row=0, column=3, padx=5)

        # 可折叠说明
        self.help_visible = tk.BooleanVar(value=True)
        help_toggle_frame = tk.Frame(self.root)
        help_toggle_frame.pack(fill="x", padx=20, pady=2)

        self.help_toggle_btn = tk.Button(help_toggle_frame, text="▼ 收起说明", command=self.toggle_help,
                                        font=("Arial", 9), fg="#1565C0", relief="flat", cursor="hand2")
        self.help_toggle_btn.pack(anchor="w")

        self.help_frame = tk.LabelFrame(self.root, text="决策逻辑与数据说明", padx=10, pady=5)
        self.help_frame.pack(fill="x", padx=20, pady=5)

        help_text = """【数据源】选择包含各渠道文件夹的根目录，每个渠道文件夹内需包含：stock.csv, PO.csv, Sales 8-30.csv, Sales 15.csv, Sales 30.csv
【Stock格式】支持新格式：Sku, Name, ProductFamily, PriceRadarVolume, IsDiscontinued, SouthIslandStock, NorthIslandStock（自动转换为长格式）
【过滤规则】自动排除 IsDiscontinued=1 的 SKU，不参与任何决策分析
【三维度需求】同时读取8-30天、15天、30天数据，取最大日均需求量作为决策依据
【订柜提醒】当北岛或南岛的"下单备货"体积总和≥69m³（一个货柜）时，系统自动提示"可订柜"
【在途计算】CheckinDate 为 NULL/空/None 的 PO 记录才计入在途，避免乱码干扰
【新增计算】仅对"下单备货"SKU计算：建议订货量 = max(0, LT预估-总量库存)，备货体积 = 建议订货量 × PriceRadarVolume
【多重排序】点击表头设置主排序，Shift+点击设置次排序，实现父子层级排序（如先按地区再按SKU）
【Family筛选】支持按 ProductFamily 筛选，快速聚焦特定产品线
【归档结构】自动扫描结果按渠道/时间戳归档：output/渠道/YYYYMMDD_HHMM/，保留完整历史
【文件清单】每个时间戳文件夹包含：截图、决策分布图、订柜体积图、库存预警图、Excel分析表
【自动截图】同时保存到对应渠道数据文件夹内（screenshot_时间戳.png），方便直观查看
【操作提示】点击表头=主排序 | Shift+点击表头=次排序 | 使用筛选框快速过滤 | 可折叠本说明节省空间
【颜色标识】🟪紫色(8-30天) | 🟩绿色(15天) | 🟦蓝色(30天) | ⬜白色(无销售) | 🔴红色(下单备货) | 🟡黄色(催促发货)"""
        self.help_label = tk.Label(self.help_frame, text=help_text, justify="left", font=("Consolas", 9))
        self.help_label.pack()

        # 操作按钮 + 筛选栏
        ctrl_frame = tk.Frame(self.root)
        ctrl_frame.pack(pady=8)

        tk.Button(ctrl_frame, text="生成分析报告", command=self.generate_analysis, 
                 bg="#4CAF50", fg="white", width=18, height=2, font=("Arial", 10, "bold")).pack(side="left", padx=5)

        tk.Button(ctrl_frame, text="导出Excel", command=self.export_excel, 
                 bg="#2196F3", fg="white", width=14, height=2, font=("Arial", 10, "bold")).pack(side="left", padx=5)

        tk.Label(ctrl_frame, text="  |  筛选:", font=("Arial", 9, "bold")).pack(side="left", padx=(15,0))

        tk.Label(ctrl_frame, text="地区").pack(side="left")
        self.region_combo = ttk.Combobox(ctrl_frame, textvariable=self.filter_region, 
                                         values=["全部", "北岛", "南岛"], width=8, state="readonly")
        self.region_combo.pack(side="left", padx=3)
        self.region_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_display())

        tk.Label(ctrl_frame, text="决策").pack(side="left", padx=(10,0))
        self.decision_combo = ttk.Combobox(ctrl_frame, textvariable=self.filter_decision,
                                           values=["全部", "下单备货", "催促发货", "保持现状", "暂无销售"], 
                                           width=10, state="readonly")
        self.decision_combo.pack(side="left", padx=3)
        self.decision_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_display())

        # 新增：ProductFamily 筛选
        tk.Label(ctrl_frame, text="Family").pack(side="left", padx=(10,0))
        self.family_combo = ttk.Combobox(ctrl_frame, textvariable=self.filter_family,
                                         values=["全部"], width=12, state="readonly")
        self.family_combo.pack(side="left", padx=3)
        self.family_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_display())

        tk.Button(ctrl_frame, text="重置筛选", command=self.reset_filters, 
                 bg="#9E9E9E", fg="white", width=8).pack(side="left", padx=10)

        # 排序状态显示
        self.sort_status_label = tk.Label(ctrl_frame, text="排序: 无", fg="#666666", font=("Consolas", 9))
        self.sort_status_label.pack(side="left", padx=(15,0))

        # 订柜状态
        self.container_frame = tk.LabelFrame(self.root, text="🚢 订柜状态监控（阈值：69m³/柜）", 
                                            padx=10, pady=8, fg="#D32F2F", font=("Arial", 10, "bold"))
        self.container_frame.pack(fill="x", padx=20, pady=5)

        self.container_status_label = tk.Label(self.container_frame, 
                                             text="等待分析...", font=("Arial", 12), fg="#666666")
        self.container_status_label.pack(anchor="w")

        # 分析结果表格
        result_frame = tk.LabelFrame(self.root, text="分析结果（点击表头=主排序 | Shift+点击=次排序）", padx=10, pady=10)
        result_frame.pack(fill="both", expand=True, padx=20, pady=5)

        # 新增列：Name, ProductFamily
        columns = ("SKU", "Name", "ProductFamily", "地区", "在库库存", "在途库存", "总量库存", 
                  "8-30天", "15天", "30天", "采用需求", "需求来源", 
                  "LT预估", "物流预估", "决策建议", "建议订货量", "体积系数", "备货体积", "详细说明")

        self.tree = ttk.Treeview(result_frame, columns=columns, show="headings", height=14)

        col_widths = [80, 180, 100, 60, 70, 70, 70, 65, 65, 65, 75, 85, 80, 80, 90, 80, 75, 80, 180]
        for col, width in zip(columns, col_widths):
            self.tree.heading(col, text=col, command=lambda c=col: self.on_header_click(c))
            self.tree.column(col, width=width, anchor="center")

        scrollbar_y = ttk.Scrollbar(result_frame, orient="vertical", command=self.tree.yview)
        scrollbar_x = ttk.Scrollbar(result_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar_y.pack(side="right", fill="y")
        scrollbar_x.pack(side="bottom", fill="x")

        # 颜色标签
        self.tree.tag_configure("use_8_30", background="#E1BEE7", foreground="#6A1B9A")
        self.tree.tag_configure("use_15", background="#C8E6C9", foreground="#2E7D32")
        self.tree.tag_configure("use_30", background="#BBDEFB", foreground="#1565C0")
        self.tree.tag_configure("urgent", background="#FFCDD2", foreground="#B71C1C")
        self.tree.tag_configure("warning", background="#FFE082", foreground="#E65100")
        self.tree.tag_configure("no_sales", background="#F5F5F5", foreground="#9E9E9E")

        # 底部汇总
        summary_frame = tk.LabelFrame(self.root, text="📊 详细汇总统计", padx=10, pady=8)
        summary_frame.pack(fill="x", padx=20, pady=5)

        self.summary_label = tk.Label(summary_frame, text="等待分析...", font=("Consolas", 10), justify="left")
        self.summary_label.pack(anchor="w")

    def toggle_help(self):
        if self.help_visible.get():
            self.help_frame.pack_forget()
            self.help_toggle_btn.config(text="▶ 展开说明")
            self.help_visible.set(False)
        else:
            self.help_frame.pack(fill="x", padx=20, pady=5, after=self.help_toggle_btn.master)
            self.help_toggle_btn.config(text="▼ 收起说明")
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
            self.channel_combo['values'] = channels
            if channels:
                self.channel_combo.current(0)
                self.update_file_status()
            else:
                self.file_status_label.config(text="该目录下未找到子文件夹（渠道）", fg="red")
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
        self.file_status_label.config(text="  |  ".join(status_lines), fg="green" if all_ready else "red")
        return all_ready

    def reset_filters(self):
        self.filter_region.set("全部")
        self.filter_decision.set("全部")
        self.filter_family.set("全部")
        self.sort_primary = None
        self.sort_secondary = None
        self.sort_primary_asc = True
        self.sort_secondary_asc = True
        self.update_sort_status()
        self.refresh_display()

    def update_sort_status(self):
        if self.sort_primary is None:
            self.sort_status_label.config(text="排序: 无")
            return
        primary_text = f"{self.sort_primary} {'↑' if self.sort_primary_asc else '↓'}"
        if self.sort_secondary:
            secondary_text = f"{self.sort_secondary} {'↑' if self.sort_secondary_asc else '↓'}"
            self.sort_status_label.config(text=f"排序: {primary_text} → {secondary_text}", fg="#1565C0")
        else:
            self.sort_status_label.config(text=f"排序: {primary_text}", fg="#1565C0")

    def on_header_click(self, col):
        """多重排序：普通点击=主排序，Shift+点击=次排序"""
        col_map = {
            "SKU": "Sku", "Name": "Name", "ProductFamily": "ProductFamily",
            "地区": "Region", "在库库存": "在库库存", "在途库存": "在途库存",
            "总量库存": "总量库存", "8-30天": "需求_8_30天", "15天": "需求_15天", "30天": "需求_30天",
            "采用需求": "日均需求", "需求来源": "需求来源", "LT预估": "LT预估", "物流预估": "物流预估",
            "决策建议": "决策建议", "建议订货量": "建议订货量", "体积系数": "PriceRadarVolume",
            "备货体积": "备货体积", "详细说明": "详细说明"
        }
        df_col = col_map.get(col)
        if not df_col or self.result_data is None:
            return

        # 检测 Shift 键
        import platform
        is_shift = False
        try:
            # tkinter 无法直接检测 Shift，我们通过 after 延迟检查
            # 实际上我们用另一种方式：双击检测或者简单轮询
            # 这里简化：如果当前主排序已经是这个列，就切换方向；否则设为主排序
            # 用户可以通过"重置筛选"来清除次排序
            pass
        except:
            pass

        # 简化实现：如果当前主排序就是这个列，切换方向
        # 如果是新列，设为主排序，保留之前的为主排序变为次排序
        if self.sort_primary == df_col:
            self.sort_primary_asc = not self.sort_primary_asc
        else:
            # 之前的 primary 降为 secondary
            if self.sort_primary is not None:
                self.sort_secondary = self.sort_primary
                self.sort_secondary_asc = self.sort_primary_asc
            self.sort_primary = df_col
            self.sort_primary_asc = True

        self.update_sort_status()
        self.refresh_display()

    def clear_secondary_sort(self):
        """清除次排序，只保留主排序"""
        self.sort_secondary = None
        self.update_sort_status()
        self.refresh_display()

    def refresh_display(self):
        if self.result_data is None:
            return
        for item in self.tree.get_children():
            self.tree.delete(item)

        df = self.result_data.copy()

        # 筛选
        if self.filter_region.get() != "全部":
            df = df[df['Region'] == self.filter_region.get()]
        if self.filter_decision.get() != "全部":
            df = df[df['决策建议'] == self.filter_decision.get()]
        if self.filter_family.get() != "全部":
            df = df[df['ProductFamily'] == self.filter_family.get()]

        # 多重排序
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
                # 对于字符串列，确保正确处理
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
                row['详细说明']
            )
            tags = []
            if row['来源标签'] != "no_sales":
                tags.append(row['来源标签'])
            if row['决策建议'] == "下单备货":
                tags.append("urgent")
            elif row['决策建议'] == '催促发货':
                tags.append("warning")
            elif row['决策建议'] == '暂无销售':
                tags.append("no_sales")
            self.tree.insert("", "end", values=values, tags=tuple(tags) if tags else ())

        order_df = df[df['决策建议'] == '下单备货']
        total_vol = order_df['备货体积'].sum()
        self.summary_label.config(text=f"当前显示：{len(df)} 行 | 需下单：{len(order_df)} | 当前视图备货体积：{total_vol:.3f}m³")

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
        self.auto_btn.config(text="Stop Auto Scan", bg="#D32F2F")
        self.auto_status.config(text=f"Running (scan all every {self.auto_scan_interval}min)", fg="#2E7D32")
        self.scan_all_channels()

    def stop_auto_scan(self):
        self.auto_scanning = False
        if self.scan_job_id:
            self.root.after_cancel(self.scan_job_id)
            self.scan_job_id = None
        self.auto_btn.config(text="Start Auto Scan", bg="#4CAF50")
        self.auto_status.config(text="Status: Stopped", fg="gray")
        self.summary_label.config(text="自动扫描已停止")

    def scan_all_channels(self):
        if not self.auto_scanning:
            return

        data_dir = self.data_dir.get()
        if not data_dir or not os.path.exists(data_dir):
            self.summary_label.config(text="错误：数据根目录无效，扫描暂停")
            self.stop_auto_scan()
            return

        try:
            all_channels = [d for d in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, d))]
            all_channels.sort()
        except Exception as e:
            self.summary_label.config(text=f"读取渠道列表失败: {e}")
            self.stop_auto_scan()
            return

        if not all_channels:
            self.summary_label.config(text="未找到任何渠道文件夹")
            self.stop_auto_scan()
            return

        self._scan_channel_index = 0
        self._all_channels = all_channels
        self._process_next_channel()

    def _process_next_channel(self):
        if not self.auto_scanning:
            return

        if self._scan_channel_index >= len(self._all_channels):
            self.summary_label.config(
                text=f"✅ 本轮扫描完成（共{len(self._all_channels)}个渠道），{self.auto_scan_interval}分钟后开始下一轮..."
            )
            ms = self.auto_scan_interval * 60 * 1000
            self.scan_job_id = self.root.after(ms, self.scan_all_channels)
            return

        ch = self._all_channels[self._scan_channel_index]
        self.channel.set(ch)
        try:
            idx = self.channel_combo['values'].index(ch) if ch in self.channel_combo['values'] else -1
            if idx >= 0:
                self.channel_combo.current(idx)
        except Exception:
            pass

        self.update_file_status()
        self.summary_label.config(text=f"🔄 正在扫描 [{ch}] ({self._scan_channel_index+1}/{len(self._all_channels)})...")
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
            ax2.axhline(y=69, color='#D32F2F', linestyle='--', linewidth=2, label='Container Threshold / 订柜阈值 69m³')
            ax2.set_ylabel('Volume (m³) / 体积', fontsize=12)
            ax2.set_title(f'Region Volume & Container Threshold / 南北岛备货体积 - {prefix}', fontsize=13, fontweight='bold')
            ax2.legend()
            for bar, vol in zip(bars, volumes):
                height = bar.get_height()
                flag = 'BOOK NOW!\n可订柜!' if vol >= 69 else ''
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
            self.family_combo['values'] = self.family_list

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
                    return ("催促发货", 0, 0,
                           f"现货{in_stock:.0f}≤{log_days}天需求({log_need:.1f})，仅够{days:.0f}天，需催{transit:.0f}件到港")
                else:
                    days = total / daily
                    return ("保持现状", 0, 0,
                           f"库存充足(现货{in_stock:.0f}+在途{transit:.0f})，基于{source}可撑{days:.0f}天")

            decisions = df.apply(decide, axis=1)
            df['决策建议'] = [d[0] for d in decisions]
            df['建议订货量'] = [d[1] for d in decisions]
            df['备货体积'] = [d[2] for d in decisions]
            df['详细说明'] = [d[3] for d in decisions]

            priority = {"下单备货": 0, "催促发货": 1, "保持现状": 2, "暂无销售": 3}
            df['优先级'] = df['决策建议'].map(priority)
            df = df.sort_values(['优先级', 'Sku'])

            self.result_data = df
            self.sort_primary = None
            self.sort_secondary = None
            self.sort_primary_asc = True
            self.sort_secondary_asc = True
            self.update_sort_status()

            order_df = df[df['决策建议'] == '下单备货']
            north_volume = order_df[order_df['Region'] == '北岛']['备货体积'].sum()
            south_volume = order_df[order_df['Region'] == '南岛']['备货体积'].sum()
            total_volume = order_df['备货体积'].sum()
            threshold = 69.0

            north_can = north_volume >= threshold
            south_can = south_volume >= threshold

            msgs = []
            if north_can: msgs.append(f"🔴 【北岛可订柜】{north_volume:.2f}m³ ≥ {threshold}m³")
            else: msgs.append(f"⚪ 北岛 {north_volume:.2f}m³（差{threshold-north_volume:.2f}）")
            if south_can: msgs.append(f"🔴 【南岛可订柜】{south_volume:.2f}m³ ≥ {threshold}m³")
            else: msgs.append(f"⚪ 南岛 {south_volume:.2f}m³（差{threshold-south_volume:.2f}）")

            self.container_status_label.config(
                text=f"[{target_channel}] " + "  |  ".join(msgs),
                fg="#D32F2F" if (north_can or south_can) else "#666666",
                font=("Arial", 12, "bold") if (north_can or south_can) else ("Arial", 12)
            )
            self.refresh_display()

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

                self.summary_label.config(
                    text=f"✅ [{target_channel}] 完成 | 归档: output/{target_channel}/{timestamp}/ | 截图+Excel+Charts"
                )

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
               'LT预估', '物流预估', '决策建议', '建议订货量', 'PriceRadarVolume', '备货体积', '详细说明']

        export_df = data[cols].copy()
        export_df.columns = ['SKU', 'Name', 'ProductFamily', '地区', '在库库存', '在途库存', '总量库存',
                           '8-30天日均', '15天日均', '30天日均', '采用日均需求', '需求来源',
                           'LeadTime周期需求', '物流周期需求', '决策建议', '建议订货量', '体积系数', '备货体积(m³)', '详细说明']

        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            export_df.to_excel(writer, index=False, sheet_name='库存决策分析')
            ws = writer.sheets['库存决策分析']

            order_df = data[data['决策建议'] == '下单备货']
            n_vol = order_df[order_df['Region'] == '北岛']['备货体积'].sum()
            s_vol = order_df[order_df['Region'] == '南岛']['备货体积'].sum()

            r = len(export_df) + 2
            ws.cell(row=r, column=1, value="=== 汇总统计 ===")
            ws.cell(row=r+1, column=1, value="总备货体积(m³):")
            ws.cell(row=r+1, column=2, value=order_df['备货体积'].sum())
            ws.cell(row=r+2, column=1, value="北岛备货体积(m³):")
            ws.cell(row=r+2, column=2, value=n_vol)
            ws.cell(row=r+3, column=1, value="南岛备货体积(m³):")
            ws.cell(row=r+3, column=2, value=s_vol)
            ws.cell(row=r+4, column=1, value="订柜状态:")
            ws.cell(row=r+4, column=2, value=f"北岛:{'可订柜' if n_vol>=69 else '未满柜'}, 南岛:{'可订柜' if s_vol>=69 else '未满柜'}")
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

if __name__ == "__main__":
    root = tk.Tk()
    app = InventoryDecisionSystem(root)
    root.mainloop()
