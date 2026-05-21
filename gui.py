"""
arXiv Paper Analyzer GUI — 现代桌面工作台
CustomTkinter 实现，扁平设计，支持明暗主题。
使用方法: python gui.py
"""

from __future__ import annotations

import csv
import queue
import re
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import customtkinter as ctk

# ── 路径 ──────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from src.searcher import build_query, search_arxiv
from src.downloader import download_pdf
from src.parser import parse_paper
from src.extractor import _build_client, extract_from_paper, _fallback_row
from src.csv_writer import init_csv, append_row, read_all_rows, read_existing_ids
from src.stats import compute_frequency, cluster_tags
from src.models import CSV_COLUMNS, FILL_NONE, PaperMeta
from src.config import (PDF_DIR, CSV_PATH, IDEA_FREQ_PATH, IDEA_CLUSTER_PATH,
                        TRANSLATE_API_KEY, TRANSLATE_BASE_URL, TRANSLATE_MODEL,
                        TRANSLATE_BACKEND, BING_API_KEY, BING_REGION, DEEPL_API_KEY,
                        BAIDU_APPID, BAIDU_SECRET_KEY,
                        TENCENT_SECRET_ID, TENCENT_SECRET_KEY, TENCENT_REGION,
                        CUSTOM_TRANSLATE_URL, CUSTOM_TRANSLATE_API_KEY)
from src.translator import TranslateConfig, translate_text


# ═══════════════════════════════════════════════════════════════
# 主题配置
# ═══════════════════════════════════════════════════════════════
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

ACCENT = "#2563EB"
ACCENT_HOVER = "#1D4ED8"
BG_CARD = "#F8FAFC"
BG_SIDEBAR = "#F1F5F9"
TEXT_PRIMARY = "#1E293B"
TEXT_SECONDARY = "#64748B"
BORDER = "#E2E8F0"
SUCCESS = "#16A34A"
WARNING = "#CA8A04"
DANGER = "#DC2626"


# ═══════════════════════════════════════════════════════════════
# 主窗口
# ═══════════════════════════════════════════════════════════════
class ArxivAnalyzerGUI:
    def __init__(self) -> None:
        self.root = ctk.CTk()
        self.root.title("arXiv Paper Analyzer")
        self.root.geometry("1340x840")
        self.root.minsize(1100, 700)

        # 窗口居中
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 1340) // 2
        y = (sh - 840) // 2
        self.root.geometry(f"1340x840+{x}+{y}")

        # 后台通信
        self._task_queue: queue.Queue = queue.Queue()
        self._cancel_flag = threading.Event()

        # 数据
        self.papers: list[PaperMeta] = []
        self.analysis_rows: list[dict] = []
        self.selected_paper_indices: set[int] = set()
        self._analyzing: bool = False
        self._pending_run: bool = False

        self._build_ui()
        self._auto_load_history()
        self._poll_queue()

    # ── 整体布局 ─────────────────────────────────────────────
    def _build_ui(self) -> None:
        # 顶部导航栏
        self._build_topbar()

        # 主内容区
        main = ctk.CTkFrame(self.root, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=20, pady=(12, 16))

        # 左侧面板 (固定宽度 340)
        self._build_sidebar(main)

        # 右侧内容 (自适应)
        self._build_content(main)

    # ═══════════════════════════════════════════════════════════
    # 顶部导航栏
    # ═══════════════════════════════════════════════════════════
    def _build_topbar(self) -> None:
        bar = ctk.CTkFrame(self.root, height=56, fg_color=BG_SIDEBAR,
                           corner_radius=0)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20)

        ctk.CTkLabel(inner, text="arXiv Paper Analyzer",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(side="left", pady=10)

        ctk.CTkLabel(inner, text="论文检索 · AI 分析 · 高频 Idea 挖掘",
                     font=ctk.CTkFont(size=12),
                     text_color=TEXT_SECONDARY).pack(side="left", padx=(12, 0), pady=12)

        ctk.CTkButton(inner, text="📂 已下载 PDF", width=110, height=32,
                      fg_color="transparent", hover_color="#E2E8F0",
                      text_color=TEXT_PRIMARY, border_color=BORDER,
                      border_width=1, font=ctk.CTkFont(size=11),
                      corner_radius=6, command=self._open_pdf_dir).pack(side="right", pady=10)


    # ═══════════════════════════════════════════════════════════
    # 左侧控制面板
    # ═══════════════════════════════════════════════════════════
    def _build_sidebar(self, parent: ctk.CTkFrame) -> None:
        sidebar = ctk.CTkFrame(parent, width=340, fg_color=BG_SIDEBAR,
                               corner_radius=16)
        sidebar.pack(side="left", fill="y", padx=(0, 16))
        sidebar.pack_propagate(False)

        # 可滚动
        scroll = ctk.CTkScrollableFrame(sidebar, fg_color="transparent",
                                        scrollbar_button_color=BORDER,
                                        scrollbar_button_hover_color=ACCENT)
        scroll.pack(fill="both", expand=True, padx=8, pady=8)

        c = scroll  # 快捷别名
        pad = {"padx": 4, "fill": "x"}

        # ── 检索参数 ──
        ctk.CTkLabel(c, text="检索参数",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", **pad)

        ctk.CTkLabel(c, text="关键词（空格分隔）",
                     font=ctk.CTkFont(size=11),
                     text_color=TEXT_SECONDARY).pack(anchor="w", **pad)
        self.kw_var = ctk.StringVar(value="large language model")
        ctk.CTkEntry(c, textvariable=self.kw_var, height=36,
                     border_color=BORDER, fg_color="white").pack(pady=(0, 10), **pad)

        ctk.CTkLabel(c, text="检索字段",
                     font=ctk.CTkFont(size=11),
                     text_color=TEXT_SECONDARY).pack(anchor="w", **pad)
        fields_frame = ctk.CTkFrame(c, fg_color="transparent")
        fields_frame.pack(pady=(0, 10), **pad)
        self.f_ti = ctk.BooleanVar(value=True)
        self.f_abs = ctk.BooleanVar(value=True)
        self.f_au = ctk.BooleanVar(value=False)
        self.f_cat = ctk.BooleanVar(value=False)
        for text, var in [("标题", self.f_ti), ("摘要", self.f_abs),
                          ("作者", self.f_au), ("分类", self.f_cat)]:
            ctk.CTkCheckBox(fields_frame, text=text, variable=var,
                            checkbox_width=18, checkbox_height=18,
                            border_color=BORDER,
                            font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 10))

        ctk.CTkLabel(c, text="arXiv 分类筛选（逗号分隔，留空=全部）",
                     font=ctk.CTkFont(size=11),
                     text_color=TEXT_SECONDARY).pack(anchor="w", **pad)
        self.cat_var = ctk.StringVar(value="cs.CL, cs.AI, cs.LG")
        ctk.CTkEntry(c, textvariable=self.cat_var, height=36,
                     border_color=BORDER, fg_color="white").pack(pady=(0, 10), **pad)

        ctk.CTkLabel(c, text="日期范围（YYYY-MM-DD，留空=不限）",
                     font=ctk.CTkFont(size=11),
                     text_color=TEXT_SECONDARY).pack(anchor="w", **pad)
        date_frame = ctk.CTkFrame(c, fg_color="transparent")
        date_frame.pack(pady=(0, 10), **pad)
        self.date_from = ctk.StringVar(value="2024-01-01")
        self.date_to = ctk.StringVar(value="2026-05-20")
        ctk.CTkEntry(date_frame, textvariable=self.date_from,
                     width=130, height=36,
                     border_color=BORDER, fg_color="white").pack(side="left")
        ctk.CTkLabel(date_frame, text="  —  ",
                     font=ctk.CTkFont(size=11),
                     text_color=TEXT_SECONDARY).pack(side="left")
        ctk.CTkEntry(date_frame, textvariable=self.date_to,
                     width=130, height=36,
                     border_color=BORDER, fg_color="white").pack(side="left")

        ctk.CTkLabel(c, text="最大论文数",
                     font=ctk.CTkFont(size=11),
                     text_color=TEXT_SECONDARY).pack(anchor="w", **pad)
        num_frame = ctk.CTkFrame(c, fg_color="transparent")
        num_frame.pack(pady=(0, 10), **pad)
        self.max_var = ctk.IntVar(value=10)
        for v in (10, 30, 50, 100, 200):
            ctk.CTkRadioButton(num_frame, text=str(v), variable=self.max_var,
                               value=v, radiobutton_width=16,
                               radiobutton_height=16,
                               border_color=BORDER,
                               font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 10))

        ctk.CTkLabel(c, text="排序方式",
                     font=ctk.CTkFont(size=11),
                     text_color=TEXT_SECONDARY).pack(anchor="w", **pad)
        sort_frame = ctk.CTkFrame(c, fg_color="transparent")
        sort_frame.pack(pady=(0, 14), **pad)
        self.sort_var = ctk.StringVar(value="relevance")
        ctk.CTkRadioButton(sort_frame, text="相关度", variable=self.sort_var,
                           value="relevance", radiobutton_width=16,
                           radiobutton_height=16, border_color=BORDER,
                           font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 10))
        ctk.CTkRadioButton(sort_frame, text="最近更新", variable=self.sort_var,
                           value="lastUpdatedDate", radiobutton_width=16,
                           radiobutton_height=16, border_color=BORDER,
                           font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 10))
        ctk.CTkRadioButton(sort_frame, text="提交日期", variable=self.sort_var,
                           value="submittedDate", radiobutton_width=16,
                           radiobutton_height=16, border_color=BORDER,
                           font=ctk.CTkFont(size=12)).pack(side="left")

        # 分隔
        ctk.CTkFrame(c, height=1, fg_color=BORDER).pack(fill="x", pady=14, padx=4)

        # ── 分析选项 ──
        ctk.CTkLabel(c, text="分析选项",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", **pad)

        self.analysis_mode = ctk.StringVar(value="ai_abstract")
        for text, val in [
            ("跳过 PDF 下载（仅使用摘要分析）", "ai_abstract"),
            ("下载 PDF 全文分析", "ai_fulltext"),
            ("不使用 AI 分析（仅提取基础信息）", "no_ai"),
            ("仅下载 PDF（不分析，不写入 CSV）", "pdf_only"),
        ]:
            ctk.CTkRadioButton(c, text=text, variable=self.analysis_mode,
                               value=val, radiobutton_width=18,
                               radiobutton_height=18, border_color=BORDER,
                               font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(0, 6), **pad)

        # 分隔
        ctk.CTkFrame(c, height=1, fg_color=BORDER).pack(fill="x", pady=14, padx=4)

        # ── 查询预览 ──
        ctk.CTkLabel(c, text="查询预览",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", **pad)
        self.query_preview = ctk.CTkTextbox(c, height=60,
                                            fg_color="white",
                                            border_color=BORDER,
                                            border_width=1,
                                            font=ctk.CTkFont(size=10, family="Consolas"),
                                            wrap="word")
        self.query_preview.pack(pady=(0, 14), **pad)

        # ── 按钮 ──
        self.search_btn = ctk.CTkButton(
            c, text="🔍  搜索预览", height=42,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            corner_radius=8, command=self._on_search)
        self.search_btn.pack(pady=(0, 8), **pad)

        self.run_btn = ctk.CTkButton(
            c, text="▶  完整分析", height=42,
            fg_color=TEXT_PRIMARY, hover_color="#334155",
            font=ctk.CTkFont(size=13, weight="bold"),
            corner_radius=8, command=self._on_run)
        self.run_btn.pack(pady=(0, 8), **pad)

        self.cancel_btn = ctk.CTkButton(
            c, text="⏹  取消操作", height=42,
            fg_color=DANGER, hover_color="#B91C1C",
            font=ctk.CTkFont(size=13, weight="bold"),
            corner_radius=8, command=self._on_cancel_op)
        self.cancel_btn.pack(pady=(0, 8), **pad)
        self.cancel_btn.configure(state="disabled", fg_color="transparent",
                                  text_color=TEXT_SECONDARY,
                                  border_color=BORDER, border_width=1,
                                  hover=False)

        self.stats_btn = ctk.CTkButton(
            c, text="📊  加载统计数据", height=36,
            fg_color="transparent", hover_color="#E2E8F0",
            text_color=TEXT_PRIMARY,
            border_color=BORDER, border_width=1,
            font=ctk.CTkFont(size=12),
            corner_radius=8, command=self._on_load_stats)
        self.stats_btn.pack(pady=(0, 8), **pad)

        self.export_btn = ctk.CTkButton(
            c, text="📥  导出 CSV", height=36,
            fg_color="transparent", hover_color="#E2E8F0",
            text_color=TEXT_PRIMARY,
            border_color=BORDER, border_width=1,
            font=ctk.CTkFont(size=12),
            corner_radius=8, command=self._on_export)
        self.export_btn.pack(**pad)

        # 实时刷新查询预览
        self._update_query_preview()
        for var in (self.kw_var, self.f_ti, self.f_abs, self.f_au, self.f_cat,
                     self.cat_var, self.date_from, self.date_to, self.sort_var):
            var.trace_add("write", lambda *_: self._update_query_preview())

    # ═══════════════════════════════════════════════════════════
    # 右侧内容区 — TabView
    # ═══════════════════════════════════════════════════════════
    def _build_content(self, parent: ctk.CTkFrame) -> None:
        right = ctk.CTkFrame(parent, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)

        self.tabview = ctk.CTkTabview(right, fg_color="transparent",
                                      segmented_button_fg_color=BG_SIDEBAR,
                                      segmented_button_selected_color="#93C5FD",
                                      segmented_button_unselected_color=BG_SIDEBAR,
                                      segmented_button_selected_hover_color="#BFDBFE",
                                      text_color=("#334155", "#CBD5E1"),
                                      corner_radius=12)
        self.tabview.pack(fill="both", expand=True)

        self.tabview.add("📄 论文列表")
        self.tabview.add("⏳ 分析进度")
        self.tabview.add("📋 分析结果")
        self.tabview.add("💡 Idea 统计")
        self.tabview.add("📝 日志")
        self.tabview.add("⚙️ 设置")

        self._build_papers_tab()
        self._build_progress_tab()
        self._build_results_tab()
        self._build_ideas_tab()
        self._build_log_tab()
        self._build_settings_tab()

        # 状态栏
        status = ctk.CTkFrame(right, height=32, fg_color="transparent")
        status.pack(fill="x", pady=(8, 0))
        self.status_var = ctk.StringVar(value="就绪")
        ctk.CTkLabel(status, textvariable=self.status_var,
                     font=ctk.CTkFont(size=11),
                     text_color=TEXT_SECONDARY).pack(side="left")
        self.progress_bar = ctk.CTkProgressBar(status, width=200, height=8,
                                               fg_color=BG_SIDEBAR,
                                               progress_color=ACCENT)
        self.progress_bar.pack(side="right")
        self.progress_bar.set(0)

    # ── Tab: 论文列表 ─────────────────────────────────────────
    def _build_papers_tab(self) -> None:
        tab = self.tabview.tab("📄 论文列表")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(tab, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self._paper_count_sv = ctk.StringVar(value="论文: 0 篇")
        ctk.CTkLabel(toolbar, textvariable=self._paper_count_sv,
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(side="left")

        for text, cmd in [("全选", lambda: self._select_all_papers(True)),
                          ("取消全选", lambda: self._select_all_papers(False)),
                          ("排除未选", self._exclude_unselected)]:
            ctk.CTkButton(toolbar, text=text, width=70, height=28,
                          fg_color="transparent", hover_color="#E2E8F0",
                          text_color=TEXT_PRIMARY, border_color=BORDER,
                          border_width=1, font=ctk.CTkFont(size=11),
                          corner_radius=6, command=cmd).pack(side="right", padx=3)

        # Treeview (保留 ttk 因为 CTk 无表格)
        cols = ("sel", "title", "authors", "published", "categories")
        tree_frame = ctk.CTkFrame(tab, fg_color="white", border_color=BORDER,
                                  border_width=1, corner_radius=8)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)

        self.papers_tree = ttk.Treeview(tree_frame, columns=cols,
                                        show="headings", selectmode="extended")
        self.papers_tree.heading("sel", text="✓")
        self.papers_tree.heading("title", text="标题")
        self.papers_tree.heading("authors", text="作者")
        self.papers_tree.heading("published", text="日期")
        self.papers_tree.heading("categories", text="分类")
        self.papers_tree.column("sel", width=30, anchor="center")
        self.papers_tree.column("title", width=420)
        self.papers_tree.column("authors", width=160)
        self.papers_tree.column("published", width=90)
        self.papers_tree.column("categories", width=110)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.papers_tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.papers_tree.xview)
        self.papers_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.papers_tree.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        style = ttk.Style()
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

        self.papers_tree.bind("<Double-1>", self._toggle_paper_selection)

        # 提示
        self._paper_hint = ctk.CTkLabel(tab, text="双击行选中/取消选中该论文",
                                         font=ctk.CTkFont(size=11),
                                         text_color=TEXT_SECONDARY)
        self._paper_hint.grid(row=2, column=0, sticky="w", pady=(4, 0))

    # ── Tab: 分析进度 ─────────────────────────────────────────
    def _build_progress_tab(self) -> None:
        tab = self.tabview.tab("⏳ 分析进度")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        info = ctk.CTkFrame(tab, fg_color="white", border_color=BORDER,
                            border_width=1, corner_radius=12)
        info.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        info.grid_columnconfigure(0, weight=1)

        inner = ctk.CTkFrame(info, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=16)

        self.task_progress_var = ctk.StringVar(value="等待开始…")
        ctk.CTkLabel(inner, textvariable=self.task_progress_var,
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w")

        self.current_paper_var = ctk.StringVar(value="")
        ctk.CTkLabel(inner, textvariable=self.current_paper_var,
                     font=ctk.CTkFont(size=12),
                     text_color=TEXT_SECONDARY).pack(anchor="w", pady=(4, 8))

        self.paper_progress = ctk.CTkProgressBar(inner, height=10,
                                                 fg_color=BG_SIDEBAR,
                                                 progress_color=ACCENT)
        self.paper_progress.pack(fill="x")

        self.progress_cancel_btn = ctk.CTkButton(
            inner, text="⏹  取消", width=100, height=32,
            fg_color=DANGER, hover_color="#B91C1C",
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=6, command=self._on_cancel_op)
        self.progress_cancel_btn.pack(anchor="e", pady=(8, 0))
        self.progress_cancel_btn.configure(state="disabled", fg_color="transparent",
                                           text_color=TEXT_SECONDARY,
                                           border_color=BORDER, border_width=1,
                                           hover=False)
        self.paper_progress.set(0)

        # 日志面板
        log_frame = ctk.CTkFrame(tab, fg_color="white", border_color=BORDER,
                                 border_width=1, corner_radius=12)
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(log_frame, text="实时日志",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).grid(row=0, column=0, sticky="w",
                                                   padx=16, pady=(12, 4))

        self.progress_log = ctk.CTkTextbox(log_frame,
                                           fg_color="#1E293B",
                                           text_color="#E2E8F0",
                                           border_width=0,
                                           font=ctk.CTkFont(size=10, family="Consolas"),
                                           wrap="word")
        self.progress_log.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

    # ── Tab: 分析结果 ─────────────────────────────────────────
    def _build_results_tab(self) -> None:
        tab = self.tabview.tab("📋 分析结果")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=0)
        tab.grid_rowconfigure(1, weight=0)
        tab.grid_rowconfigure(2, weight=1)

        # 筛选栏
        filter_bar = ctk.CTkFrame(tab, fg_color="white", border_color=BORDER,
                                  border_width=1, corner_radius=10)
        filter_bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        filter_bar.grid_columnconfigure(5, weight=1)

        ctk.CTkLabel(filter_bar, text="筛选",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).grid(row=0, column=0, padx=(16, 8), pady=10)

        self.filter_var = ctk.StringVar()
        ctk.CTkEntry(filter_bar, textvariable=self.filter_var,
                     placeholder_text="输入关键词过滤…", width=200, height=32,
                     border_color=BORDER, fg_color="white").grid(row=0, column=1, padx=4, pady=10)
        self.filter_var.trace_add("write", lambda *_: self._refresh_results_table())

        ctk.CTkLabel(filter_bar, text="置信度",
                     font=ctk.CTkFont(size=12),
                     text_color=TEXT_SECONDARY).grid(row=0, column=2, padx=(12, 4), pady=10)
        self.conf_filter_var = ctk.StringVar(value="全部")
        conf_cb = ctk.CTkOptionMenu(filter_bar, variable=self.conf_filter_var,
                                    values=["全部", "high", "medium", "low"],
                                    width=100, height=32, fg_color="white",
                                    text_color=TEXT_PRIMARY,
                                    button_color=ACCENT,
                                    dropdown_fg_color="white",
                                    dropdown_text_color=TEXT_PRIMARY)
        conf_cb.grid(row=0, column=3, padx=4, pady=10)
        conf_cb.configure(command=lambda v: self._refresh_results_table())

        # 当前选中行
        self._selected_result_idx: int | None = None

        # 操作按钮 — 右侧
        btn_frame = ctk.CTkFrame(filter_bar, fg_color="transparent")
        btn_frame.grid(row=0, column=5, sticky="e", padx=(0, 8), pady=10)

        btn_cfg = {"width": 70, "height": 28, "fg_color": "transparent",
                    "hover_color": "#E2E8F0", "text_color": TEXT_PRIMARY,
                    "border_color": BORDER, "border_width": 1,
                    "font": ctk.CTkFont(size=11), "corner_radius": 6}

        self.result_detail_btn = ctk.CTkButton(btn_frame, text="详情", command=self._on_result_detail_btn, **btn_cfg)
        self.result_edit_btn = ctk.CTkButton(btn_frame, text="编辑", command=self._on_result_edit_btn, **btn_cfg)
        self.result_reanalyze_btn = ctk.CTkButton(btn_frame, text="重分析", command=self._on_result_reanalyze_btn, **btn_cfg)
        self.result_delete_btn = ctk.CTkButton(btn_frame, text="删除", command=self._on_result_delete_btn,
                                               fg_color=DANGER, hover_color="#B91C1C",
                                               text_color="white", border_width=0,
                                               width=70, height=28,
                                               font=ctk.CTkFont(size=11), corner_radius=6)
        self.result_reanalyze_all_btn = ctk.CTkButton(btn_frame, text="全部重分析", command=self._on_reanalyze_all,
                                                       **btn_cfg)
        self.result_reanalyze_all_btn.pack(side="right", padx=2)
        self.result_save_btn = ctk.CTkButton(btn_frame, text="✏️ 保存修改", command=self._save_edits, **btn_cfg)
        self.result_save_btn.pack(side="right", padx=2)
        self.result_export_btn2 = ctk.CTkButton(btn_frame, text="📥 导出", command=self._on_export, **btn_cfg)
        self.result_export_btn2.pack(side="right", padx=2)

        self._set_result_action_buttons_visible(False)

        # 提示
        self._result_hint = ctk.CTkLabel(tab, text="点击行查看操作按钮 | 双击行查看详情 | Ctrl+点击多选行可批量删除/重分析",
                                         font=ctk.CTkFont(size=11),
                                         text_color=TEXT_SECONDARY)
        self._result_hint.grid(row=1, column=0, sticky="w", pady=(0, 4))

        # 结果表格
        rcols = ("arxiv_id", "title", "innovation", "method", "idea_tags", "confidence")
        tree_frame = ctk.CTkFrame(tab, fg_color="white", border_color=BORDER,
                                  border_width=1, corner_radius=8)
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)

        self.results_tree = ttk.Treeview(tree_frame, columns=rcols,
                                         show="headings", selectmode="extended")
        self.results_tree.heading("arxiv_id", text="arXiv ID")
        self.results_tree.heading("title", text="标题")
        self.results_tree.heading("innovation", text="创新点")
        self.results_tree.heading("method", text="方法")
        self.results_tree.heading("idea_tags", text="Idea Tags")
        self.results_tree.heading("confidence", text="置信度")
        self.results_tree.column("arxiv_id", width=100)
        self.results_tree.column("title", width=320)
        self.results_tree.column("innovation", width=260)
        self.results_tree.column("method", width=200)
        self.results_tree.column("idea_tags", width=200)
        self.results_tree.column("confidence", width=60, anchor="center")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.results_tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.results_tree.xview)
        self.results_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.results_tree.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self.results_tree.bind("<Double-1>", self._on_result_detail)
        self.results_tree.bind("<<TreeviewSelect>>", self._on_result_select)

    # ── Tab: Idea 统计 ────────────────────────────────────────
    def _build_ideas_tab(self) -> None:
        tab = self.tabview.tab("💡 Idea 统计")
        tab.grid_columnconfigure(0, weight=3)
        tab.grid_columnconfigure(1, weight=2)
        tab.grid_rowconfigure(0, weight=1)

        # 左：频率表
        left_card = ctk.CTkFrame(tab, fg_color="white", border_color=BORDER,
                                 border_width=1, corner_radius=12)
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left_card.grid_columnconfigure(0, weight=1)
        left_card.grid_rowconfigure(0, weight=0)
        left_card.grid_rowconfigure(1, weight=1)

        header_l = ctk.CTkFrame(left_card, fg_color="transparent")
        header_l.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
        ctk.CTkLabel(header_l, text="高频 Idea 标签",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(side="left")
        ctk.CTkButton(header_l, text="合并选中", width=80, height=28,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      font=ctk.CTkFont(size=11), corner_radius=6,
                      command=self._merge_idea_tags).pack(side="right", padx=2)
        ctk.CTkButton(header_l, text="清空全部", width=70, height=28,
                      fg_color=DANGER, hover_color="#B91C1C",
                      text_color="white", border_width=0,
                      font=ctk.CTkFont(size=11), corner_radius=6,
                      command=self._clear_all_idea_tags).pack(side="right", padx=2)
        ctk.CTkButton(header_l, text="删除", width=60, height=28,
                      fg_color=DANGER, hover_color="#B91C1C",
                      text_color="white", border_width=0,
                      font=ctk.CTkFont(size=11), corner_radius=6,
                      command=self._delete_idea_tags).pack(side="right", padx=4)
        ctk.CTkButton(header_l, text="导出", width=60, height=28,
                      fg_color="transparent", hover_color="#E2E8F0",
                      text_color=TEXT_PRIMARY, border_color=BORDER,
                      border_width=1, font=ctk.CTkFont(size=11),
                      corner_radius=6, command=self._export_idea_csv).pack(side="right", padx=2)

        icols = ("idea", "count", "paper_ids")
        idea_frame = ctk.CTkFrame(left_card, fg_color="transparent")
        idea_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        idea_frame.grid_columnconfigure(0, weight=1)
        idea_frame.grid_rowconfigure(0, weight=1)

        self.idea_tree = ttk.Treeview(idea_frame, columns=icols,
                                      show="headings", selectmode="extended")
        self.idea_tree.heading("idea", text="Idea Tag")
        self.idea_tree.heading("count", text="频次")
        self.idea_tree.heading("paper_ids", text="相关论文")
        self.idea_tree.column("idea", width=280)
        self.idea_tree.column("count", width=50, anchor="center")
        self.idea_tree.column("paper_ids", width=200)

        vsb_i = ttk.Scrollbar(idea_frame, orient="vertical", command=self.idea_tree.yview)
        self.idea_tree.configure(yscrollcommand=vsb_i.set)
        self.idea_tree.grid(row=0, column=0, sticky="nsew")
        vsb_i.grid(row=0, column=1, sticky="ns")

        self.idea_tree.bind("<<TreeviewSelect>>", self._on_idea_select)

        # 右：详情 + 聚类
        right_card = ctk.CTkFrame(tab, fg_color="white", border_color=BORDER,
                                  border_width=1, corner_radius=12)
        right_card.grid(row=0, column=1, sticky="nsew")
        right_card.grid_columnconfigure(0, weight=1)
        right_card.grid_rowconfigure(0, weight=3)
        right_card.grid_rowconfigure(1, weight=2)

        # 详情
        detail_frame = ctk.CTkFrame(right_card, fg_color="transparent")
        detail_frame.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 4))
        detail_frame.grid_columnconfigure(0, weight=1)
        detail_frame.grid_rowconfigure(0, weight=0)
        detail_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(detail_frame, text="选中 Idea 详情",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).grid(row=0, column=0, sticky="w")
        self.idea_detail_text = ctk.CTkTextbox(detail_frame,
                                               fg_color="#F8FAFC",
                                               text_color=TEXT_PRIMARY,
                                               border_width=0,
                                               font=ctk.CTkFont(size=11),
                                               wrap="word")
        self.idea_detail_text.grid(row=1, column=0, sticky="nsew", pady=(4, 0))

        # 聚类
        cluster_frame = ctk.CTkFrame(right_card, fg_color="transparent")
        cluster_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 12))
        cluster_frame.grid_columnconfigure(0, weight=1)
        cluster_frame.grid_rowconfigure(0, weight=0)
        cluster_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(cluster_frame, text="相似标签聚类",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).grid(row=0, column=0, sticky="w", pady=(0, 4))

        ccols = ("cluster", "members", "total")
        clust_tree_frame = ctk.CTkFrame(cluster_frame, fg_color="transparent")
        clust_tree_frame.grid(row=1, column=0, sticky="nsew")
        clust_tree_frame.grid_columnconfigure(0, weight=1)
        clust_tree_frame.grid_rowconfigure(0, weight=1)

        self.cluster_tree = ttk.Treeview(clust_tree_frame, columns=ccols,
                                         show="headings", height=6)
        self.cluster_tree.heading("cluster", text="规范标签")
        self.cluster_tree.heading("members", text="成员")
        self.cluster_tree.heading("total", text="合计")
        self.cluster_tree.column("cluster", width=200)
        self.cluster_tree.column("members", width=280)
        self.cluster_tree.column("total", width=50, anchor="center")

        vsb_c = ttk.Scrollbar(clust_tree_frame, orient="vertical",
                              command=self.cluster_tree.yview)
        self.cluster_tree.configure(yscrollcommand=vsb_c.set)
        self.cluster_tree.grid(row=0, column=0, sticky="nsew")
        vsb_c.grid(row=0, column=1, sticky="ns")

    # ── Tab: 日志 ─────────────────────────────────────────────
    def _build_log_tab(self) -> None:
        tab = self.tabview.tab("📝 日志")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=0)
        tab.grid_rowconfigure(1, weight=1)

        ctk.CTkButton(tab, text="清空日志", width=80, height=28,
                      fg_color="transparent", hover_color="#E2E8F0",
                      text_color=TEXT_PRIMARY, border_color=BORDER,
                      border_width=1, font=ctk.CTkFont(size=11),
                      corner_radius=6, command=self._clear_log).grid(
            row=0, column=0, sticky="w", pady=(0, 8))

        self.log_text = ctk.CTkTextbox(tab,
                                       fg_color="#1E293B",
                                       text_color="#E2E8F0",
                                       border_width=0,
                                       font=ctk.CTkFont(size=10, family="Consolas"),
                                       wrap="word")
        self.log_text.grid(row=1, column=0, sticky="nsew")

    def _open_pdf_dir(self) -> None:
        """打开 PDF 下载目录"""
        import os
        PDF_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(PDF_DIR))

    # ═══════════════════════════════════════════════════════════
    # 查询预览
    # ═══════════════════════════════════════════════════════════
    def _get_selected_fields(self) -> list[str]:
        fields = []
        if self.f_ti.get(): fields.append("ti")
        if self.f_abs.get(): fields.append("abs")
        if self.f_au.get(): fields.append("au")
        if self.f_cat.get(): fields.append("cat")
        return fields or ["ti", "abs"]

    def _get_date_range(self) -> tuple[str, str] | None:
        dfrom = self.date_from.get().strip()
        dto = self.date_to.get().strip()
        if not dfrom and not dto:
            return None
        df = dfrom.replace("-", "") + "0000" if dfrom else "190001010000"
        dt = dto.replace("-", "") + "2359" if dto else "209912312359"
        return df, dt

    def _update_query_preview(self) -> None:
        try:
            keywords = [k.strip() for k in self.kw_var.get().split() if k.strip()]
            if not keywords:
                self.query_preview.delete("0.0", "end")
                self.query_preview.insert("0.0", "（请输入关键词）")
                return
            q = build_query(keywords=keywords, fields=self._get_selected_fields(),
                            date_range=self._get_date_range(), operator="AND")
            self.query_preview.delete("0.0", "end")
            self.query_preview.insert("0.0", q)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    # 日志
    # ═══════════════════════════════════════════════════════════
    def _log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._task_queue.put(("log", f"[{ts}] {msg}\n"))

    def _flush_log(self, line: str) -> None:
        self.log_text.insert("end", line)
        self.log_text.see("end")
        if hasattr(self, 'progress_log'):
            self.progress_log.insert("end", line)
            self.progress_log.see("end")

    def _clear_log(self) -> None:
        self.log_text.delete("0.0", "end")
        if hasattr(self, 'progress_log'):
            self.progress_log.delete("0.0", "end")

    # ═══════════════════════════════════════════════════════════
    # 搜索
    # ═══════════════════════════════════════════════════════════
    def _on_search(self) -> None:
        self._cancel_flag.clear()
        self.search_btn.configure(state="disabled", text="⏳ 搜索中…")
        self.run_btn.configure(state="disabled")
        self._set_cancel_buttons_active(True)
        self.status_var.set("正在检索 arXiv…")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        self.tabview.set("⏳ 分析进度")
        self._clear_log()
        self._log("开始检索 arXiv…")
        threading.Thread(target=self._do_search, daemon=True).start()

    def _do_search(self) -> None:
        try:
            keywords = [k.strip() for k in self.kw_var.get().split() if k.strip()]
            if not keywords:
                self._task_queue.put(("error", "请输入至少一个关键词"))
                return

            if self._cancel_flag.is_set():
                self._task_queue.put(("cancelled", "搜索已取消"))
                return

            query = build_query(keywords=keywords, fields=self._get_selected_fields(),
                                date_range=self._get_date_range(), operator="AND")
            self._log(f"查询: {query}")

            cat_filter = [c.strip() for c in self.cat_var.get().split(",") if c.strip()]

            papers = search_arxiv(query=query, max_results=self.max_var.get(),
                                  start=0, sort_by=self.sort_var.get())

            if self._cancel_flag.is_set():
                self._task_queue.put(("cancelled", "搜索已取消（检索完成但丢弃结果）"))
                return

            if cat_filter:
                papers = [p for p in papers
                          if any(c.startswith(cf) for c in p.categories for cf in cat_filter)]

            self.papers = papers
            self.selected_paper_indices = set(range(len(papers)))
            self._log(f"找到 {len(papers)} 篇论文")
            self._task_queue.put(("papers_loaded", papers))
            self._task_queue.put(("search_done", f"搜索完成，共 {len(papers)} 篇"))
        except Exception as e:
            self._log(f"搜索失败: {e}")
            self._task_queue.put(("error", str(e)))

    # ═══════════════════════════════════════════════════════════
    # 完整分析
    # ═══════════════════════════════════════════════════════════
    def _on_run(self) -> None:
        if not self.papers:
            self._on_search()
            self._pending_run = True
            return
        self._start_analysis()

    def _start_analysis(self) -> None:
        if not self.papers:
            messagebox.showinfo("提示", "请先搜索论文")
            return

        n = len([i for i in self.selected_paper_indices if i < len(self.papers)])
        if n == 0:
            messagebox.showinfo("提示", "没有选中任何论文")
            return
        mode = self.analysis_mode.get()
        if mode == "pdf_only":
            msg = f"将下载 {n} 篇论文的 PDF\n（不分析，不写入 CSV，不消耗 token）\n\n确认继续？"
        elif mode == "no_ai":
            msg = f"将提取 {n} 篇论文基础信息\n（不下载 PDF，不消耗 token）\n\n确认继续？"
        elif mode == "ai_fulltext":
            msg = (f"将分析 {n} 篇论文（PDF 全文）\n"
                   f"预估 token: ~{n * 5000}\n"
                   f"预估耗时: ~{n * 8} 秒\n\n确认继续？")
        else:  # ai_abstract
            msg = (f"将分析 {n} 篇论文（仅摘要）\n"
                   f"预估 token: ~{n * 1500}\n"
                   f"预估耗时: ~{n * 4} 秒\n\n确认继续？")
        if not messagebox.askokcancel("确认分析", msg):
            return

        self._analyzing = True
        self.search_btn.configure(state="disabled")
        self.run_btn.configure(state="disabled", text="⏳ 分析中…")
        self.stats_btn.configure(state="disabled")
        self._set_cancel_buttons_active(True)
        self.status_var.set(f"正在分析 0/{n}…")
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(0)
        self.tabview.set("⏳ 分析进度")
        self._cancel_flag.clear()

        if mode != "pdf_only":
            init_csv(CSV_PATH)
        threading.Thread(target=self._do_analysis, daemon=True).start()

    def _do_analysis(self) -> None:
        try:
            indices = sorted([i for i in self.selected_paper_indices if i < len(self.papers)])
            total = len(indices)
            existing_ids = read_existing_ids(CSV_PATH)
            client = None
            total_tokens = 0
            paper_count = 0

            for step, idx in enumerate(indices):
                if self._cancel_flag.is_set():
                    self._log("用户取消分析")
                    break

                meta = self.papers[idx]
                if meta.arxiv_id in existing_ids:
                    self._log(f"跳过 {meta.arxiv_id}（已分析）")
                    continue

                self._task_queue.put(("progress", (step + 1, total,
                                                    f"正在处理 {meta.arxiv_id}…")))
                self._log(f"处理 [{step+1}/{total}] {meta.arxiv_id}: {meta.title[:80]}")

                mode = self.analysis_mode.get()
                do_download = (mode == "ai_fulltext" or mode == "pdf_only")

                if mode == "pdf_only":
                    if do_download and not self._cancel_flag.is_set():
                        self._log(f"  下载 PDF…")
                        download_pdf(meta.arxiv_id, meta.pdf_url, PDF_DIR)
                    if self._cancel_flag.is_set():
                        self._log("用户取消分析")
                        break
                    self._log(f"  ✓ 仅下载 PDF，跳过分析")
                    continue

                if mode == "no_ai":
                    row = _fallback_row(meta)
                    append_row(CSV_PATH, row)
                    existing_ids.add(meta.arxiv_id)
                    self._log(f"  ✓ 已保存基础信息（未下载 PDF，未使用 AI）")
                    continue

                # AI 分析模式 (ai_abstract 或 ai_fulltext)
                if do_download:
                    self._log(f"  下载 PDF…")
                    download_pdf(meta.arxiv_id, meta.pdf_url, PDF_DIR)

                _full_text, source_text = parse_paper(meta, PDF_DIR)
                self._log(f"  DeepSeek 分析中…")

                if client is None:
                    try:
                        client = _build_client()
                    except Exception as e:
                        self._log(f"  API 客户端创建失败: {e}")
                        self._task_queue.put(("error", f"API 客户端创建失败: {e}"))
                        return

                row, usage = extract_from_paper(meta, source_text, client=client)
                append_row(CSV_PATH, row)
                existing_ids.add(meta.arxiv_id)
                paper_count += 1
                total_tokens += usage.get("total_tokens", 0)

                conf = row.get("confidence", "none")
                tags = row.get("idea_tags", "none")
                self._log(f"  ✓ 完成 | 置信度={conf} | tags={tags[:60]}")
                time.sleep(1.5)

            self._task_queue.put(("done", f"分析完成，共处理 {paper_count} 篇，实际消耗 {total_tokens} tokens"))
        except Exception as e:
            self._log(f"分析失败: {traceback.format_exc()}")
            self._task_queue.put(("error", str(e)))

    # ═══════════════════════════════════════════════════════════
    # 取消操作
    # ═══════════════════════════════════════════════════════════
    def _on_cancel_op(self) -> None:
        self._cancel_flag.set()
        self._log("⚠ 用户取消操作")
        self.status_var.set("已取消")
        self._set_cancel_buttons_active(False)

    def _set_cancel_buttons_active(self, active: bool) -> None:
        """启用或禁用取消按钮"""
        for btn in (self.cancel_btn, self.progress_cancel_btn):
            if active:
                btn.configure(state="normal", fg_color=DANGER,
                              hover_color="#B91C1C", text_color="white",
                              border_width=0, hover=True)
            else:
                btn.configure(state="disabled", fg_color="transparent",
                              text_color=TEXT_SECONDARY,
                              border_color=BORDER, border_width=1,
                              hover=False)

    # ═══════════════════════════════════════════════════════════
    # 消息轮询（主线程）
    # ═══════════════════════════════════════════════════════════
    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self._task_queue.get_nowait()
                self._handle_message(msg)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._poll_queue)

    def _handle_message(self, msg: tuple) -> None:
        kind = msg[0]
        if kind == "log":
            self._flush_log(msg[1])
        elif kind == "error":
            messagebox.showerror("错误", msg[1])
            self._analyzing = False
            self._reset_buttons()
            self._set_cancel_buttons_active(False)
            self.status_var.set("出错")
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate")
            self.progress_bar.set(0)
        elif kind == "cancelled":
            self._flush_log(f"[INFO] {msg[1]}\n")
            self._analyzing = False
            self._reset_buttons()
            self._set_cancel_buttons_active(False)
            self.status_var.set(msg[1])
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate")
            self.progress_bar.set(0)
        elif kind == "search_done":
            self._flush_log(f"[INFO] {msg[1]}\n")
            self._analyzing = False
            self._reset_buttons()
            self._set_cancel_buttons_active(False)
            self.status_var.set(msg[1])
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate")
        elif kind == "done":
            self._flush_log(f"[INFO] {msg[1]}\n")
            self._analyzing = False
            self._reset_buttons()
            self._set_cancel_buttons_active(False)
            self.status_var.set(msg[1])
            self.progress_bar.stop()
            self.progress_bar.set(1)
            self._load_stats()
            self._load_results()
            self.tabview.set("📋 分析结果")
            messagebox.showinfo("分析完成", msg[1])
        elif kind == "papers_loaded":
            self._populate_papers_table(msg[1])
            self._reset_buttons()
            self.status_var.set(f"检索完成，共 {len(msg[1])} 篇")
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate")
            self.tabview.set("📄 论文列表")
            if getattr(self, "_pending_run", False):
                self._pending_run = False
                self._start_analysis()
        elif kind == "reanalyze_done":
            self._flush_log(f"[INFO] {msg[1]}\n")
            self._analyzing = False
            self._reset_buttons()
            self._set_cancel_buttons_active(False)
            self.status_var.set(msg[1])
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate")
            self.progress_bar.set(1)
            messagebox.showinfo("重分析完成", msg[1])
        elif kind == "progress":
            current, total, text = msg[1]
            self.task_progress_var.set(f"{current} / {total} 篇")
            self.current_paper_var.set(text)
            self.paper_progress.set(current / total if total else 0)

    def _reset_buttons(self) -> None:
        if not self._analyzing:
            self.search_btn.configure(state="normal", text="🔍  搜索预览")
            self.run_btn.configure(state="normal", text="▶  完整分析")
            self.stats_btn.configure(state="normal")

    # ═══════════════════════════════════════════════════════════
    # 论文列表
    # ═══════════════════════════════════════════════════════════
    def _populate_papers_table(self, papers: list[PaperMeta]) -> None:
        tree = self.papers_tree
        tree.delete(*tree.get_children())
        for i, p in enumerate(papers):
            tree.insert("", "end", iid=str(i), values=(
                "✓" if i in self.selected_paper_indices else "",
                p.title[:120],
                "; ".join(p.authors[:2]),
                p.published[:10],
                "; ".join(p.categories[:3]),
            ))
        self._paper_count_sv.set(f"论文: {len(papers)} 篇")

    def _toggle_paper_selection(self, event) -> None:
        sel = self.papers_tree.selection()
        if not sel: return
        idx = int(sel[0])
        if idx in self.selected_paper_indices:
            self.selected_paper_indices.remove(idx)
            self.papers_tree.set(sel[0], "sel", "")
        else:
            self.selected_paper_indices.add(idx)
            self.papers_tree.set(sel[0], "sel", "✓")

    def _select_all_papers(self, select: bool) -> None:
        if select:
            self.selected_paper_indices = set(range(len(self.papers)))
        else:
            self.selected_paper_indices.clear()
        self._populate_papers_table(self.papers)

    def _exclude_unselected(self) -> None:
        indices = sorted(self.selected_paper_indices)
        self.papers = [self.papers[i] for i in indices]
        self.selected_paper_indices = set(range(len(self.papers)))
        self._populate_papers_table(self.papers)
        self._log(f"已排除未选论文，剩余 {len(self.papers)} 篇")

    # ═══════════════════════════════════════════════════════════
    # 分析结果
    # ═══════════════════════════════════════════════════════════
    def _load_results(self) -> None:
        try:
            rows = read_all_rows(CSV_PATH)
        except Exception:
            return
        self.analysis_rows = rows
        self._refresh_results_table()

    def _refresh_results_table(self) -> None:
        tree = self.results_tree
        tree.delete(*tree.get_children())
        ft = self.filter_var.get().lower()
        cf = self.conf_filter_var.get()

        for i, row in enumerate(self.analysis_rows):
            if cf != "全部" and row.get("confidence", "") != cf:
                continue
            if ft:
                combined = " ".join(str(v) for v in row.values()).lower()
                if ft not in combined:
                    continue

            tree.insert("", "end", iid=str(i), values=(
                row.get("arxiv_id", ""),
                row.get("title", "")[:100],
                row.get("innovation", "")[:80],
                row.get("method", "")[:80],
                row.get("idea_tags", "")[:80],
                row.get("confidence", ""),
            ))

    def _on_result_detail(self, event) -> None:
        sel = self.results_tree.selection()
        if not sel: return
        idx = int(sel[0])
        if idx >= len(self.analysis_rows): return
        self._open_detail_dialog(self.analysis_rows[idx])

    def _open_detail_dialog(self, row: dict) -> None:
        dlg = ctk.CTkToplevel(self.root)
        dlg.title(f"详情: {row.get('title', '')[:50]}")
        dlg.geometry("720x640")
        dlg.grab_set()

        text = ctk.CTkTextbox(dlg, wrap="word", font=ctk.CTkFont(size=11),
                              fg_color="#F8FAFC", text_color=TEXT_PRIMARY)
        text.pack(fill="both", expand=True, padx=12, pady=(12, 0))

        fields = [
            ("标题", "title"), ("arXiv ID", "arxiv_id"), ("作者", "authors"),
            ("发表时间", "published"), ("分类", "categories"),
            ("摘要", "abstract"), ("创新点", "innovation"), ("方法", "method"),
            ("实验", "experiments"), ("数据集", "datasets"), ("指标", "metrics"),
            ("结果", "results"), ("局限性", "limitations"),
            ("Idea Tags", "idea_tags"), ("证据", "evidence"),
            ("置信度", "confidence"),
        ]

        # 翻译状态挂载到 dialog
        dlg._detail_fields = fields
        dlg._detail_row = row
        dlg._translated = False
        dlg._translations: dict[str, str] = {}
        dlg._translating = False

        def _render(show_translation: bool) -> None:
            text.configure(state="normal")
            text.delete("0.0", "end")
            for label, key in fields:
                val = row.get(key, "")
                if val and val != FILL_NONE:
                    text.insert("end", f"▌{label}\n")
                    text.insert("end", f"{val}\n")
                    if show_translation and key in dlg._translations:
                        text.insert("end", f"\n{dlg._translations[key]}\n")
                    text.insert("end", "\n")
            text.configure(state="disabled")

        # 底部按钮栏
        btn_bar = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_bar.pack(fill="x", padx=12, pady=12)

        translate_btn = ctk.CTkButton(
            btn_bar, text="🌐 翻译为中文", width=130, height=32,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=6)
        translate_btn.pack(side="right")

        def _download_pdf() -> None:
            arxiv_id = row.get("arxiv_id", "")
            pdf_url = row.get("pdf_url", "")
            if not pdf_url:
                messagebox.showwarning("提示", "该论文无 PDF 链接", parent=dlg)
                return
            dest = PDF_DIR / f"{arxiv_id}.pdf"
            if dest.exists():
                messagebox.showinfo("已存在", f"PDF 已下载过:\n{dest}", parent=dlg)
            else:
                try:
                    download_pdf(arxiv_id, pdf_url, PDF_DIR)
                    messagebox.showinfo("下载完成", f"PDF 已保存到:\n{dest}", parent=dlg)
                except Exception as e:
                    messagebox.showerror("下载失败", str(e), parent=dlg)

        download_btn = ctk.CTkButton(
            btn_bar, text="📥 下载 PDF", width=110, height=32,
            fg_color="transparent", hover_color="#E2E8F0",
            text_color=TEXT_PRIMARY, border_color=BORDER,
            border_width=1, font=ctk.CTkFont(size=12),
            corner_radius=6, command=_download_pdf)
        download_btn.pack(side="right", padx=(0, 8))

        def _on_translate_done(translations: dict[str, str]) -> None:
            dlg._translating = False
            dlg._translations = translations
            dlg._translated = True
            translate_btn.configure(text="📄 显示原文", state="normal")
            _render(True)

        def _on_translate_error(err: str) -> None:
            dlg._translating = False
            translate_btn.configure(text="🌐 翻译为中文", state="normal")
            messagebox.showerror("翻译失败", err, parent=dlg)

        def _toggle_translate() -> None:
            if dlg._translating:
                return
            if dlg._translated:
                dlg._translated = False
                translate_btn.configure(text="🌐 翻译为中文")
                _render(False)
            elif dlg._translations:
                dlg._translated = True
                translate_btn.configure(text="📄 显示原文")
                _render(True)
            else:
                dlg._translating = True
                translate_btn.configure(text="⏳ 翻译中…", state="disabled")

                def _thread() -> None:
                    try:
                        translations = self._translate_fields(row, fields)
                        dlg.after(0, lambda: _on_translate_done(translations))
                    except Exception as e:
                        dlg.after(0, lambda: _on_translate_error(str(e)))

                threading.Thread(target=_thread, daemon=True).start()

        translate_btn.configure(command=_toggle_translate)

        _render(False)

    def _on_result_select(self, event) -> None:
        sel = self.results_tree.selection()
        if not sel:
            self._selected_result_idx = None
            self._set_result_action_buttons_visible(False)
            return
        idx = int(sel[0])
        if idx >= len(self.analysis_rows):
            self._selected_result_idx = None
            self._set_result_action_buttons_visible(False)
            return
        self._selected_result_idx = idx
        self._set_result_action_buttons_visible(True)

    def _set_result_action_buttons_visible(self, visible: bool) -> None:
        buttons = [self.result_detail_btn, self.result_edit_btn,
                    self.result_reanalyze_btn, self.result_delete_btn]
        for btn in buttons:
            if visible:
                btn.pack(side="left", padx=2, before=self.result_save_btn)
            else:
                btn.pack_forget()

    def _on_result_detail_btn(self) -> None:
        if self._selected_result_idx is not None:
            self._open_detail_dialog(self.analysis_rows[self._selected_result_idx])

    def _on_result_edit_btn(self) -> None:
        if self._selected_result_idx is not None:
            self._open_edit_dialog(self.analysis_rows[self._selected_result_idx])

    # ── 翻译 ──────────────────────────────────────────────────
    def _get_translate_config(self) -> TranslateConfig:
        backend = self.setting_trans_backend.get().strip() if hasattr(self, 'setting_trans_backend') else "google"
        return TranslateConfig(
            backend=backend,
            llm_api_key=TRANSLATE_API_KEY,
            llm_base_url=TRANSLATE_BASE_URL,
            llm_model=TRANSLATE_MODEL,
            bing_api_key=BING_API_KEY,
            bing_region=BING_REGION or "global",
            deepl_api_key=DEEPL_API_KEY,
            baidu_appid=BAIDU_APPID,
            baidu_secret_key=BAIDU_SECRET_KEY,
            tencent_secret_id=TENCENT_SECRET_ID,
            tencent_secret_key=TENCENT_SECRET_KEY,
            tencent_region=TENCENT_REGION or "ap-guangzhou",
            custom_url=CUSTOM_TRANSLATE_URL,
            custom_api_key=CUSTOM_TRANSLATE_API_KEY,
        )

    def _translate_fields(self, row: dict, fields: list[tuple[str, str]]) -> dict[str, str]:
        """将所有非空字段翻译为中文，返回 {key: 中文翻译}"""
        texts: list[tuple[str, str]] = []
        for _label, key in fields:
            val = row.get(key, "")
            if val and val != FILL_NONE:
                texts.append((key, val))
        if not texts:
            return {}

        config = self._get_translate_config()
        result: dict[str, str] = {}
        for key, text_val in texts:
            try:
                result[key] = translate_text(text_val, config)
            except Exception as e:
                result[key] = f"[翻译失败] {e}"
        return result

    def _get_selected_arxiv_ids(self) -> list[str]:
        """获取当前结果表中所有选中行的 arxiv_id"""
        ids: list[str] = []
        for sel in self.results_tree.selection():
            idx = int(sel)
            if idx < len(self.analysis_rows):
                aid = self.analysis_rows[idx].get("arxiv_id", "")
                if aid:
                    ids.append(aid)
        return ids

    def _reanalyze_confirm_dialog(self, title: str, n: int, preview: str) -> str | None:
        """弹出重分析确认弹窗，返回 "ai_abstract" 或 "ai_fulltext"，None 表示取消"""
        dlg = ctk.CTkToplevel(self.root)
        dlg.title(title)
        dlg.geometry("440x320")
        dlg.grab_set()
        dlg.resizable(False, False)

        result: list[str | None] = [None]

        ctk.CTkLabel(dlg, text=f"将重新分析 {n} 篇论文",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(pady=(20, 4))
        ctk.CTkLabel(dlg, text=f"预估 token: ~{n * 5000}  预估耗时: ~{n * 5} 秒",
                     font=ctk.CTkFont(size=11),
                     text_color=TEXT_SECONDARY).pack(pady=(0, 12))

        # PDF 下载选项（单选，初始值跟侧边栏同步，仅 AI 模式有效）
        init_mode = self.analysis_mode.get()
        if init_mode not in ("ai_abstract", "ai_fulltext"):
            init_mode = "ai_abstract"
        dl_mode = ctk.StringVar(value=init_mode)
        ctk.CTkRadioButton(dlg, text="跳过 PDF 下载（仅使用摘要分析）",
                           variable=dl_mode, value="ai_abstract",
                           radiobutton_width=18, radiobutton_height=18,
                           border_color=BORDER,
                           font=ctk.CTkFont(size=12)).pack(anchor="w", padx=40, pady=(4, 6))
        ctk.CTkRadioButton(dlg, text="下载 PDF 全文分析",
                           variable=dl_mode, value="ai_fulltext",
                           radiobutton_width=18, radiobutton_height=18,
                           border_color=BORDER,
                           font=ctk.CTkFont(size=12)).pack(anchor="w", padx=40, pady=(0, 12))

        ctk.CTkLabel(dlg, text=preview,
                     font=ctk.CTkFont(size=10), text_color=TEXT_SECONDARY,
                     wraplength=380).pack(padx=30, pady=(0, 16))

        btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_frame.pack(pady=(0, 16))

        def _confirm() -> None:
            result[0] = dl_mode.get()
            dlg.destroy()

        ctk.CTkButton(btn_frame, text="确认重分析", width=120, height=36,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      corner_radius=8, command=_confirm).pack(side="left", padx=6)
        ctk.CTkButton(btn_frame, text="取消", width=100, height=36,
                      fg_color="transparent", hover_color="#E2E8F0",
                      text_color=TEXT_PRIMARY, border_color=BORDER,
                      border_width=1, font=ctk.CTkFont(size=13),
                      corner_radius=8, command=dlg.destroy).pack(side="left", padx=6)

        dlg.wait_window()
        return result[0]

    def _on_result_reanalyze_btn(self) -> None:
        ids = self._get_selected_arxiv_ids()
        if not ids:
            return
        n = len(ids)
        preview = ", ".join(ids[:5])
        if n > 5:
            preview += f" …等 {n} 篇"
        dl_mode = self._reanalyze_confirm_dialog("确认重分析", n, preview)
        if dl_mode is None:
            return
        threading.Thread(target=self._do_reanalyze_batch, args=(ids, dl_mode), daemon=True).start()

    def _on_reanalyze_all(self) -> None:
        ids = [r.get("arxiv_id", "") for r in self.analysis_rows if r.get("arxiv_id")]
        if not ids:
            messagebox.showinfo("提示", "没有可重分析的条目")
            return
        total = len(ids)
        preview = f"涵盖 {total} 篇论文的全部分析结果"
        dl_mode = self._reanalyze_confirm_dialog("确认全部重分析", total, preview)
        if dl_mode is None:
            return
        threading.Thread(target=self._do_reanalyze_batch, args=(ids, dl_mode), daemon=True).start()

    def _do_reanalyze_batch(self, arxiv_ids: list[str], dl_mode: str = "ai_abstract") -> None:
        self._analyzing = True
        self._cancel_flag.clear()
        self._set_cancel_buttons_active(True)
        total = len(arxiv_ids)
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(0)
        self._log(f"开始批量重分析 {total} 篇…")
        client = None
        completed = 0
        total_tokens = 0
        for aid in arxiv_ids:
            if self._cancel_flag.is_set():
                self._log("用户取消重分析")
                break
            self.status_var.set(f"重分析 {completed+1}/{total}: {aid}…")
            self._log(f"重分析 [{completed+1}/{total}] {aid} …")
            try:
                if client is None:
                    client = _build_client()
                for i, row in enumerate(self.analysis_rows):
                    if row.get("arxiv_id") == aid:
                        meta = PaperMeta(
                            arxiv_id=row.get("arxiv_id", ""),
                            title=row.get("title", ""),
                            authors=(row.get("authors", "")).split("; "),
                            published=row.get("published", ""),
                            updated=row.get("updated", ""),
                            categories=(row.get("categories", "")).split("; "),
                            abstract=row.get("abstract", ""),
                            pdf_url=row.get("pdf_url", ""),
                        )
                        if dl_mode == "ai_fulltext":
                            download_pdf(meta.arxiv_id, meta.pdf_url, PDF_DIR)
                        _full_text, source_text = parse_paper(meta, PDF_DIR)
                        new_row, usage = extract_from_paper(meta, source_text, client=client)
                        self.analysis_rows[i] = new_row
                        self._rewrite_csv()
                        total_tokens += usage.get("total_tokens", 0)
                        self._log(f"  ✓ {aid} 重分析完成")
                        break
                completed += 1
                self.progress_bar.set(completed / total)
                time.sleep(1.5)
            except Exception as e:
                self._log(f"  ✗ {aid} 重分析失败: {e}")
                completed += 1
                self.progress_bar.set(completed / total)
        self._refresh_results_table()
        self._load_stats()
        self._task_queue.put(("reanalyze_done", f"批量重分析完成: {completed}/{total}，实际消耗 {total_tokens} tokens"))

    def _on_result_delete_btn(self) -> None:
        indices = sorted([int(s) for s in self.results_tree.selection()
                          if int(s) < len(self.analysis_rows)], reverse=True)
        if not indices:
            return
        n = len(indices)
        preview = ", ".join(self.analysis_rows[i].get("arxiv_id", "") for i in indices[:5])
        if n > 5:
            preview += f" …等 {n} 篇"
        if not messagebox.askyesno("确认删除", f"将删除 {n} 个条目:\n\n{preview}\n\n此操作不可撤销！"):
            return
        for i in indices:
            aid = self.analysis_rows[i].get("arxiv_id", "")
            del self.analysis_rows[i]
            self._log(f"已删除: {aid}")
        self._selected_result_idx = None
        self._set_result_action_buttons_visible(False)
        self._rewrite_csv()
        self._refresh_results_table()
        self._load_stats()

    def _open_edit_dialog(self, row: dict) -> None:
        dlg = ctk.CTkToplevel(self.root)
        dlg.title(f"编辑: {row.get('title', '')[:50]}")
        dlg.geometry("600x680")
        dlg.grab_set()

        scroll = ctk.CTkScrollableFrame(dlg, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=12, pady=12)

        vars_dict: dict[str, ctk.StringVar] = {}
        edit_fields = [
            ("innovation", "创新点"), ("method", "方法"), ("experiments", "实验"),
            ("datasets", "数据集"), ("metrics", "指标"), ("results", "结果"),
            ("limitations", "局限性"), ("idea_tags", "Idea标签"), ("confidence", "置信度"),
        ]
        for key, zh_label in edit_fields:
            ctk.CTkLabel(scroll, text=zh_label, font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=TEXT_PRIMARY).pack(anchor="w", pady=(8, 2))
            var = ctk.StringVar(value=row.get(key, ""))
            vars_dict[key] = var
            ctk.CTkEntry(scroll, textvariable=var, height=34,
                         border_color=BORDER, fg_color="white").pack(fill="x")

        def _save() -> None:
            for f, var in vars_dict.items():
                row[f] = var.get()
            self._rewrite_csv()
            self._refresh_results_table()
            dlg.destroy()

        ctk.CTkButton(scroll, text="保存修改", height=38,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      corner_radius=8, command=_save).pack(pady=(16, 4))
        ctk.CTkLabel(scroll, text="保存后自动更新 CSV 文件",
                     font=ctk.CTkFont(size=11),
                     text_color=TEXT_SECONDARY).pack()

    def _rewrite_csv(self) -> None:
        import csv as csv_mod
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            w = csv_mod.DictWriter(f, fieldnames=CSV_COLUMNS, quoting=csv_mod.QUOTE_ALL)
            w.writeheader()
            for row in self.analysis_rows:
                sanitised = {}
                for col in CSV_COLUMNS:
                    v = row.get(col, FILL_NONE)
                    if v is None or (isinstance(v, str) and v.strip() == ""):
                        v = FILL_NONE
                    sanitised[col] = str(v)
                w.writerow(sanitised)

    def _save_edits(self) -> None:
        self._rewrite_csv()
        self._log("修改已保存到 CSV")
        messagebox.showinfo("保存", "修改已保存到 CSV 文件")

    # ═══════════════════════════════════════════════════════════
    # Idea 统计
    # ═══════════════════════════════════════════════════════════
    def _on_load_history(self) -> None:
        """一键加载历史分析结果（结果 + 统计）"""
        self._load_results()
        self._load_stats()
        count = len(self.analysis_rows)
        self._log(f"已加载历史分析结果: {count} 篇论文")
        self.status_var.set(f"已加载 {count} 篇历史分析结果")
        self.tabview.set("📋 分析结果")

    def _auto_load_history(self) -> None:
        """启动时自动加载已有 CSV 数据"""
        if not CSV_PATH.exists():
            return
        try:
            rows = read_all_rows(CSV_PATH)
            if not rows:
                return
            self.analysis_rows = rows
            self._refresh_results_table()
            self._populate_idea_stats(rows)
            self._log(f"自动加载历史结果: {len(rows)} 篇论文")
        except Exception:
            pass  # 静默失败，不影响启动

    def _on_load_stats(self) -> None:
        self._load_stats()
        self.tabview.set("💡 Idea 统计")

    def _load_stats(self) -> None:
        try:
            rows = read_all_rows(CSV_PATH)
        except Exception:
            return
        if not rows: return
        self.analysis_rows = rows
        self._populate_idea_stats(rows)
        self._log(f"统计完成: {len(set(
            t.strip().lower() for r in rows
            for t in re.split(r'\s*;\s*', r.get('idea_tags', ''))
            if t.strip() and t.strip() != FILL_NONE
        ))} 个唯一标签")

    def _populate_idea_stats(self, rows: list[dict]) -> None:
        """仅填充 idea 统计树（不读 CSV，由调用方传入 rows）"""
        self.idea_tree.delete(*self.idea_tree.get_children())
        tag_papers: dict[str, list[str]] = {}
        for r in rows:
            tags_raw = r.get("idea_tags", "")
            if not tags_raw or tags_raw == FILL_NONE: continue
            for tag in re.split(r"\s*;\s*", tags_raw):
                tag = tag.strip().lower()
                if tag and tag != FILL_NONE:
                    tag_papers.setdefault(tag, []).append(r.get("arxiv_id", ""))
        for tag, ids in sorted(tag_papers.items(), key=lambda x: len(x[1]), reverse=True):
            self.idea_tree.insert("", "end", values=(tag, len(ids), "; ".join(ids[:5])))
        self._load_clusters(rows)

    def _load_clusters(self, rows: list[dict]) -> None:
        try:
            cluster_df = cluster_tags(rows)
        except Exception:
            return
        self.cluster_tree.delete(*self.cluster_tree.get_children())
        for _, crow in cluster_df.iterrows():
            self.cluster_tree.insert("", "end", values=(
                crow.get("canonical_tag", ""),
                crow.get("member_tags", ""),
                crow.get("total_count", ""),
            ))

    def _on_idea_select(self, event) -> None:
        sel = self.idea_tree.selection()
        if not sel: return
        values = self.idea_tree.item(sel[0], "values")
        tag, count, papers = values[0], values[1], (values[2] or "")[:200]

        self.idea_detail_text.delete("0.0", "end")
        self.idea_detail_text.insert("end", f"标签: {tag}\n频次: {count}\n\n")
        self.idea_detail_text.insert("end", f"相关论文 (前5篇):\n{papers}\n\n")

        methods: list[str] = []
        for r in self.analysis_rows:
            if tag in r.get("idea_tags", "").lower():
                m = r.get("method", "")
                if m and m != FILL_NONE:
                    methods.append(m[:80])
        if methods:
            self.idea_detail_text.insert("end", "常用方法:\n")
            for m in methods[:5]:
                self.idea_detail_text.insert("end", f"  • {m}\n")

    def _delete_idea_tags(self) -> None:
        sel = self.idea_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择要删除的标签（Ctrl+点击多选）")
            return
        tags = [self.idea_tree.item(s, "values")[0] for s in sel]
        preview = ", ".join(tags[:8])
        if len(tags) > 8:
            preview += f" …等 {len(tags)} 个"
        if not messagebox.askyesno("确认删除", f"将从所有论文中删除以下标签:\n\n{preview}\n\n此操作不可撤销！"):
            return
        for tag in tags:
            for r in self.analysis_rows:
                cur = r.get("idea_tags", "")
                if not cur or cur == FILL_NONE:
                    continue
                parts = [p.strip() for p in cur.split(";")]
                parts = [p for p in parts if p.lower() != tag.lower()]
                r["idea_tags"] = "; ".join(parts) if parts else FILL_NONE
        self._rewrite_csv()
        self._load_stats()
        self._log(f"已删除标签: {', '.join(tags)}")

    def _clear_all_idea_tags(self) -> None:
        """清空所有论文的 idea_tags 字段"""
        if not self.analysis_rows:
            messagebox.showinfo("提示", "没有可清空的条目")
            return
        if not messagebox.askyesno("确认清空", f"将清空全部 {len(self.analysis_rows)} 篇论文的 Idea 标签\n\n此操作不可撤销！"):
            return
        for r in self.analysis_rows:
            r["idea_tags"] = FILL_NONE
        self._rewrite_csv()
        self._load_stats()
        self._log("已清空全部 Idea 标签")

    def _merge_idea_tags(self) -> None:
        sel = self.idea_tree.selection()
        if len(sel) < 2:
            messagebox.showinfo("提示", "请至少选择 2 个标签（Ctrl+点击多选）")
            return

        tags = [self.idea_tree.item(s, "values")[0] for s in sel]
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("合并 Idea 标签")
        dlg.geometry("420x240")
        dlg.grab_set()

        ctk.CTkLabel(dlg, text="将以下标签合并为:",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(pady=(16, 4))
        ctk.CTkLabel(dlg, text="\n".join(tags),
                     font=ctk.CTkFont(size=11),
                     text_color=TEXT_SECONDARY).pack()

        target_var = ctk.StringVar(value=tags[0])
        ctk.CTkEntry(dlg, textvariable=target_var, height=36,
                     border_color=BORDER, fg_color="white").pack(padx=20, pady=12, fill="x")

        def _merge() -> None:
            target = target_var.get().strip().lower()
            for r in self.analysis_rows:
                cur = r.get("idea_tags", "")
                for old in tags:
                    cur = re.sub(rf"\b{re.escape(old)}\b", target, cur, flags=re.IGNORECASE)
                parts = list(dict.fromkeys(p.strip() for p in cur.split(";") if p.strip()))
                r["idea_tags"] = "; ".join(parts)
            self._rewrite_csv()
            self._load_stats()
            dlg.destroy()
            self._log(f"合并完成: {' + '.join(tags)} → {target}")

        ctk.CTkButton(dlg, text="确认合并", height=38,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      corner_radius=8, command=_merge).pack()

    # ═══════════════════════════════════════════════════════════
    # 导出
    # ═══════════════════════════════════════════════════════════
    def _on_export(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile="arxiv_analysis.csv")
        if not path: return
        try:
            import shutil
            if CSV_PATH.exists():
                shutil.copy(CSV_PATH, path)
                self._log(f"导出 CSV → {path}")
                messagebox.showinfo("导出成功", f"已保存到:\n{path}")
            else:
                messagebox.showinfo("提示", "暂无分析结果，请先运行分析")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))

    def _export_idea_csv(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile="idea_frequency.csv")
        if not path: return
        try:
            import shutil
            if IDEA_FREQ_PATH.exists():
                shutil.copy(IDEA_FREQ_PATH, path)
                shutil.copy(IDEA_CLUSTER_PATH,
                            str(Path(path).parent / "idea_clusters.csv"))
                self._log(f"导出统计 → {path}")
                messagebox.showinfo("导出成功", f"已保存到:\n{path}\nidea_clusters.csv")
            else:
                self._load_stats()
        except Exception as e:
            messagebox.showerror("导出失败", str(e))

    # ═══════════════════════════════════════════════════════════
    # 设置 — 切换模型 / 修改 .env
    # ═══════════════════════════════════════════════════════════
    def _build_settings_tab(self) -> None:
        tab = self.tabview.tab("⚙️ 设置")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=0)
        tab.grid_rowconfigure(1, weight=1)

        # 预设切换栏
        preset_bar = ctk.CTkFrame(tab, fg_color="white", border_color=BORDER,
                                  border_width=1, corner_radius=10)
        preset_bar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        preset_bar.grid_columnconfigure(4, weight=1)

        ctk.CTkLabel(preset_bar, text="快速切换",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).grid(row=0, column=0, padx=(16, 8), pady=12)

        # 预设列表
        PRESETS = {
            "DeepSeek V4 Pro": {
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-v4-pro",
            },
            "DeepSeek Chat": {
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
            },
            "OpenAI GPT-4o": {
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o",
            },
            "OpenAI GPT-4.1": {
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4.1",
            },
            "Anthropic Claude (兼容)": {
                "base_url": "https://api.deepseek.com/anthropic",
                "model": "deepseek-v4-pro",
            },
        }

        self.preset_var = ctk.StringVar(value="选择预设…")
        preset_cb = ctk.CTkOptionMenu(
            preset_bar, variable=self.preset_var,
            values=["选择预设…"] + list(PRESETS.keys()),
            width=180, height=32, fg_color="white",
            text_color=TEXT_PRIMARY, button_color=ACCENT,
            dropdown_fg_color="white", dropdown_text_color=TEXT_PRIMARY,
            command=lambda v: self._apply_preset(v, PRESETS))
        preset_cb.grid(row=0, column=1, padx=4, pady=12)

        # 当前状态标签
        self.preset_status = ctk.CTkLabel(
            preset_bar, text="",
            font=ctk.CTkFont(size=11), text_color=SUCCESS)
        self.preset_status.grid(row=0, column=2, padx=(12, 0), pady=12)

        # 主设置区域
        settings_card = ctk.CTkFrame(tab, fg_color="white", border_color=BORDER,
                                     border_width=1, corner_radius=12)
        settings_card.grid(row=1, column=0, sticky="nsew")
        settings_card.grid_columnconfigure(0, weight=1)
        settings_card.grid_rowconfigure(0, weight=0)
        settings_card.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(settings_card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 8))
        ctk.CTkLabel(header, text="API 配置",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(side="left")
        ctk.CTkButton(header, text="重新加载并重启", width=110, height=28,
                      fg_color="transparent", hover_color="#E2E8F0",
                      text_color=TEXT_PRIMARY, border_color=BORDER,
                      border_width=1, font=ctk.CTkFont(size=11),
                      corner_radius=6, command=self._reload_and_restart).pack(side="right", padx=2)
        ctk.CTkButton(header, text="💾 保存", width=80, height=28,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      font=ctk.CTkFont(size=11, weight="bold"),
                      corner_radius=6, command=self._save_env_from_form).pack(side="right", padx=4)

        # 表单区
        form = ctk.CTkScrollableFrame(settings_card, fg_color="transparent",
                                      scrollbar_button_color=BORDER,
                                      scrollbar_button_hover_color=ACCENT)
        form.grid(row=1, column=0, sticky="nsew", padx=20, pady=(4, 16))

        # API Key
        ctk.CTkLabel(form, text="API Key",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", pady=(12, 2))
        self.setting_key = ctk.CTkEntry(form, height=36, border_color=BORDER,
                                        fg_color="white", show="•")
        self.setting_key.pack(fill="x")

        ctk.CTkLabel(form, text="Base URL",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", pady=(12, 2))
        self.setting_url = ctk.CTkEntry(form, height=36, border_color=BORDER,
                                        fg_color="white")
        self.setting_url.pack(fill="x")
        ctk.CTkLabel(form, text="OpenAI 兼容端点通常以 /v1 结尾，Anthropic 端点通常以 /anthropic 结尾",
                     font=ctk.CTkFont(size=10), text_color=TEXT_SECONDARY).pack(anchor="w", pady=(2, 0))

        ctk.CTkLabel(form, text="Model",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", pady=(12, 2))
        self.setting_model = ctk.CTkEntry(form, height=36, border_color=BORDER,
                                          fg_color="white")
        self.setting_model.pack(fill="x")
        ctk.CTkLabel(form, text="例如: gpt-4o / deepseek-chat / deepseek-v4-pro / claude-opus-4-7",
                     font=ctk.CTkFont(size=10), text_color=TEXT_SECONDARY).pack(anchor="w", pady=(2, 0))

        # ── 翻译 API 配置 ──
        ctk.CTkFrame(form, height=1, fg_color=BORDER).pack(fill="x", pady=16)
        ctk.CTkLabel(form, text="翻译 API 配置（独立于分析 API）",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", pady=(0, 8))

        # 翻译后端选择
        ctk.CTkLabel(form, text="翻译后端",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", pady=(4, 2))
        self.setting_trans_backend = ctk.StringVar(value="google")
        trans_backend_cb = ctk.CTkOptionMenu(
            form, variable=self.setting_trans_backend,
            values=["google", "baidu", "tencent", "llm", "bing", "deepl", "custom"],
            width=200, height=32, fg_color="white",
            text_color=TEXT_PRIMARY, button_color=ACCENT,
            dropdown_fg_color="white", dropdown_text_color=TEXT_PRIMARY,
            command=self._on_trans_backend_changed)
        trans_backend_cb.pack(anchor="w")

        # Google (免费免配置)
        self._trans_google_frame = ctk.CTkFrame(form, fg_color="transparent")
        ctk.CTkLabel(self._trans_google_frame, text="✓ Google 翻译免费无需 API Key，直接使用",
                     font=ctk.CTkFont(size=11), text_color=SUCCESS).pack(anchor="w", pady=(12, 0))
        ctk.CTkLabel(self._trans_google_frame, text="注意：国内网络可能需要代理才能访问",
                     font=ctk.CTkFont(size=10), text_color=WARNING).pack(anchor="w", pady=(4, 0))

        # 百度
        self._trans_baidu_frame = ctk.CTkFrame(form, fg_color="transparent")
        ctk.CTkLabel(self._trans_baidu_frame, text="百度翻译 APPID",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", pady=(12, 2))
        self.setting_baidu_appid = ctk.CTkEntry(self._trans_baidu_frame, height=36, border_color=BORDER,
                                                  fg_color="white", placeholder_text="百度翻译开放平台获取")
        self.setting_baidu_appid.pack(fill="x")
        ctk.CTkLabel(self._trans_baidu_frame, text="百度翻译 Secret Key",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", pady=(12, 2))
        self.setting_baidu_secret = ctk.CTkEntry(self._trans_baidu_frame, height=36, border_color=BORDER,
                                                   fg_color="white", show="•")
        self.setting_baidu_secret.pack(fill="x")
        ctk.CTkLabel(self._trans_baidu_frame, text="免费版每月 200 万字符，申请: fanyi-api.baidu.com",
                     font=ctk.CTkFont(size=10), text_color=TEXT_SECONDARY).pack(anchor="w", pady=(4, 0))

        # 腾讯
        self._trans_tencent_frame = ctk.CTkFrame(form, fg_color="transparent")
        ctk.CTkLabel(self._trans_tencent_frame, text="腾讯云 SecretId",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", pady=(12, 2))
        self.setting_tencent_id = ctk.CTkEntry(self._trans_tencent_frame, height=36, border_color=BORDER,
                                                 fg_color="white", placeholder_text="腾讯云 API 密钥管理获取")
        self.setting_tencent_id.pack(fill="x")
        ctk.CTkLabel(self._trans_tencent_frame, text="腾讯云 SecretKey",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", pady=(12, 2))
        self.setting_tencent_key = ctk.CTkEntry(self._trans_tencent_frame, height=36, border_color=BORDER,
                                                  fg_color="white", show="•")
        self.setting_tencent_key.pack(fill="x")
        ctk.CTkLabel(self._trans_tencent_frame, text="地域",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", pady=(12, 2))
        self.setting_tencent_region = ctk.CTkEntry(self._trans_tencent_frame, height=36, border_color=BORDER,
                                                     fg_color="white", placeholder_text="默认 ap-guangzhou")
        self.setting_tencent_region.pack(fill="x")
        ctk.CTkLabel(self._trans_tencent_frame, text="每月免费 500 万字符，申请: cloud.tencent.com/product/tmt",
                     font=ctk.CTkFont(size=10), text_color=TEXT_SECONDARY).pack(anchor="w", pady=(4, 0))

        # LLM
        self._trans_llm_frame = ctk.CTkFrame(form, fg_color="transparent")
        ctk.CTkLabel(self._trans_llm_frame, text="翻译 API Key（可选，留空=复用分析 Key）",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", pady=(12, 2))
        self.setting_trans_key = ctk.CTkEntry(self._trans_llm_frame, height=36, border_color=BORDER,
                                               fg_color="white", show="•",
                                               placeholder_text="留空则使用上方 API Key")
        self.setting_trans_key.pack(fill="x")
        ctk.CTkLabel(self._trans_llm_frame, text="翻译 Base URL（可选，留空=复用分析 URL）",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", pady=(12, 2))
        self.setting_trans_url = ctk.CTkEntry(self._trans_llm_frame, height=36, border_color=BORDER,
                                               fg_color="white",
                                               placeholder_text="留空则使用上方 Base URL")
        self.setting_trans_url.pack(fill="x")
        ctk.CTkLabel(self._trans_llm_frame, text="翻译 Model（可选，留空=使用 deepseek-chat）",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", pady=(12, 2))
        self.setting_trans_model = ctk.CTkEntry(self._trans_llm_frame, height=36, border_color=BORDER,
                                                 fg_color="white",
                                                 placeholder_text="建议用便宜的模型")
        self.setting_trans_model.pack(fill="x")

        # Bing
        self._trans_bing_frame = ctk.CTkFrame(form, fg_color="transparent")
        ctk.CTkLabel(self._trans_bing_frame, text="Bing API Key（Azure Translator）",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", pady=(12, 2))
        self.setting_bing_key = ctk.CTkEntry(self._trans_bing_frame, height=36, border_color=BORDER,
                                              fg_color="white", show="•",
                                              placeholder_text="Azure 门户获取")
        self.setting_bing_key.pack(fill="x")
        ctk.CTkLabel(self._trans_bing_frame, text="Azure 区域",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", pady=(12, 2))
        self.setting_bing_region = ctk.CTkEntry(self._trans_bing_frame, height=36, border_color=BORDER,
                                                 fg_color="white", placeholder_text="默认 global")
        self.setting_bing_region.pack(fill="x")

        # DeepL
        self._trans_deepl_frame = ctk.CTkFrame(form, fg_color="transparent")
        ctk.CTkLabel(self._trans_deepl_frame, text="DeepL API Key",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", pady=(12, 2))
        self.setting_deepl_key = ctk.CTkEntry(self._trans_deepl_frame, height=36, border_color=BORDER,
                                               fg_color="white", show="•",
                                               placeholder_text="免费版以 :fx 结尾")
        self.setting_deepl_key.pack(fill="x")
        ctk.CTkLabel(self._trans_deepl_frame, text="免费版每月 50 万字符，申请: deepl.com/pro-api",
                     font=ctk.CTkFont(size=10), text_color=TEXT_SECONDARY).pack(anchor="w", pady=(4, 0))

        # Custom
        self._trans_custom_frame = ctk.CTkFrame(form, fg_color="transparent")
        ctk.CTkLabel(self._trans_custom_frame, text="自定义 API URL",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", pady=(12, 2))
        self.setting_custom_url = ctk.CTkEntry(self._trans_custom_frame, height=36, border_color=BORDER,
                                                fg_color="white",
                                                placeholder_text="http://xxx/translate?apiKey=xxx")
        self.setting_custom_url.pack(fill="x")
        ctk.CTkLabel(self._trans_custom_frame, text="POST JSON: {\"text\":\"...\",\"sourceLang\":\"en\",\"targetLang\":\"zh-CN\"}",
                     font=ctk.CTkFont(size=10), text_color=TEXT_SECONDARY).pack(anchor="w", pady=(4, 0))
        ctk.CTkLabel(self._trans_custom_frame, text="额外 API Key（可选，URL 中已含则留空）",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_PRIMARY).pack(anchor="w", pady=(12, 2))
        self.setting_custom_api_key = ctk.CTkEntry(self._trans_custom_frame, height=36, border_color=BORDER,
                                                     fg_color="white", show="•",
                                                     placeholder_text="留空则使用 URL 中的 apiKey")
        self.setting_custom_api_key.pack(fill="x")

        # 初始显示 Google（默认后端，免费免配置）
        for frm in (self._trans_baidu_frame, self._trans_tencent_frame,
                    self._trans_llm_frame, self._trans_bing_frame,
                    self._trans_deepl_frame, self._trans_custom_frame):
            frm.pack_forget()

        # 原提示
        ctk.CTkFrame(form, height=1, fg_color=BORDER).pack(fill="x", pady=16)
        ctk.CTkLabel(form, text="💡 提示：修改后点「保存」，后续分析将使用新配置。\n"
                     "      保存不会自动重载已加载的 API 客户端，建议重启 GUI。",
                     font=ctk.CTkFont(size=10), text_color=TEXT_SECONDARY,
                     justify="left").pack(anchor="w")

        # 加载当前配置
        self._load_env_to_form()

    def _reload_and_restart(self) -> None:
        """重新加载 .env 配置并重启 GUI"""
        import os
        if messagebox.askyesno("重启确认", "将保存当前配置、重新加载 .env 并重启 GUI。\n\n确认重启？"):
            self._save_env_from_form()
            self._log("重启 GUI…")
            python = sys.executable
            os.execl(python, python, *sys.argv)

    def _load_env_to_form(self) -> None:
        """从 .env 文件读取当前配置并填入表单"""
        env_path = BASE_DIR / ".env"
        config = {
            "DEEPSEEK_API_KEY": "", "DEEPSEEK_BASE_URL": "", "DEEPSEEK_MODEL": "",
            "TRANSLATE_BACKEND": "google",
            "TRANSLATE_API_KEY": "", "TRANSLATE_BASE_URL": "", "TRANSLATE_MODEL": "",
            "BING_API_KEY": "", "BING_REGION": "global",
            "DEEPL_API_KEY": "",
            "BAIDU_APPID": "", "BAIDU_SECRET_KEY": "",
            "TENCENT_SECRET_ID": "", "TENCENT_SECRET_KEY": "", "TENCENT_REGION": "ap-guangzhou",
            "CUSTOM_TRANSLATE_URL": "", "CUSTOM_TRANSLATE_API_KEY": "",
        }
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.split("#")[0].strip()
                    if key in config:
                        config[key] = val

        # 分析 API
        self.setting_key.delete(0, "end")
        self.setting_key.insert(0, config["DEEPSEEK_API_KEY"])
        self.setting_url.delete(0, "end")
        self.setting_url.insert(0, config["DEEPSEEK_BASE_URL"])
        self.setting_model.delete(0, "end")
        self.setting_model.insert(0, config["DEEPSEEK_MODEL"])

        # 翻译 API
        self.setting_trans_backend.set(config.get("TRANSLATE_BACKEND", "google"))
        self.setting_trans_key.delete(0, "end")
        self.setting_trans_key.insert(0, config.get("TRANSLATE_API_KEY", ""))
        self.setting_trans_url.delete(0, "end")
        self.setting_trans_url.insert(0, config.get("TRANSLATE_BASE_URL", ""))
        self.setting_trans_model.delete(0, "end")
        self.setting_trans_model.insert(0, config.get("TRANSLATE_MODEL", ""))
        self.setting_bing_key.delete(0, "end")
        self.setting_bing_key.insert(0, config.get("BING_API_KEY", ""))
        self.setting_bing_region.delete(0, "end")
        self.setting_bing_region.insert(0, config.get("BING_REGION", "global"))
        self.setting_deepl_key.delete(0, "end")
        self.setting_deepl_key.insert(0, config.get("DEEPL_API_KEY", ""))
        self.setting_baidu_appid.delete(0, "end")
        self.setting_baidu_appid.insert(0, config.get("BAIDU_APPID", ""))
        self.setting_baidu_secret.delete(0, "end")
        self.setting_baidu_secret.insert(0, config.get("BAIDU_SECRET_KEY", ""))
        self.setting_tencent_id.delete(0, "end")
        self.setting_tencent_id.insert(0, config.get("TENCENT_SECRET_ID", ""))
        self.setting_tencent_key.delete(0, "end")
        self.setting_tencent_key.insert(0, config.get("TENCENT_SECRET_KEY", ""))
        self.setting_tencent_region.delete(0, "end")
        self.setting_tencent_region.insert(0, config.get("TENCENT_REGION", "ap-guangzhou"))
        self.setting_custom_url.delete(0, "end")
        self.setting_custom_url.insert(0, config.get("CUSTOM_TRANSLATE_URL", ""))
        self.setting_custom_api_key.delete(0, "end")
        self.setting_custom_api_key.insert(0, config.get("CUSTOM_TRANSLATE_API_KEY", ""))

        self._on_trans_backend_changed(config.get("TRANSLATE_BACKEND", "google"))
        self._log("已从 .env 加载配置")

    def _save_env_from_form(self) -> None:
        """将表单内容写回 .env 文件"""
        env_path = BASE_DIR / ".env"
        key = self.setting_key.get().strip()
        url = self.setting_url.get().strip()
        model = self.setting_model.get().strip()

        if not key:
            messagebox.showwarning("提示", "API Key 不能为空")
            return

        lines = [
            "# deepseek API配置",
            f"DEEPSEEK_API_KEY={key}",
            f"DEEPSEEK_BASE_URL={url}",
            f"DEEPSEEK_MODEL={model}",
            f"TRANSLATE_BACKEND={self.setting_trans_backend.get().strip()}",
        ]

        def _add_if(prompt: str, val: str) -> None:
            if val.strip():
                lines.append(f"{prompt}={val.strip()}")

        _add_if("TRANSLATE_API_KEY", self.setting_trans_key.get())
        _add_if("TRANSLATE_BASE_URL", self.setting_trans_url.get())
        _add_if("TRANSLATE_MODEL", self.setting_trans_model.get())
        _add_if("BING_API_KEY", self.setting_bing_key.get())
        if self.setting_bing_region.get().strip():
            lines.append(f"BING_REGION={self.setting_bing_region.get().strip()}")
        _add_if("DEEPL_API_KEY", self.setting_deepl_key.get())
        _add_if("BAIDU_APPID", self.setting_baidu_appid.get())
        _add_if("BAIDU_SECRET_KEY", self.setting_baidu_secret.get())
        _add_if("TENCENT_SECRET_ID", self.setting_tencent_id.get())
        _add_if("TENCENT_SECRET_KEY", self.setting_tencent_key.get())
        if self.setting_tencent_region.get().strip() not in ("", "ap-guangzhou"):
            lines.append(f"TENCENT_REGION={self.setting_tencent_region.get().strip()}")
        _add_if("CUSTOM_TRANSLATE_URL", self.setting_custom_url.get())
        _add_if("CUSTOM_TRANSLATE_API_KEY", self.setting_custom_api_key.get())

        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._log(f"配置已保存 → {env_path}")
        self.preset_status.configure(text="✓ 已保存")
        messagebox.showinfo("保存成功", f"配置已写入 .env\nModel: {model}")

    def _on_trans_backend_changed(self, choice: str) -> None:
        """切换翻译后端时显示/隐藏对应配置字段"""
        all_frames = (
            self._trans_google_frame, self._trans_baidu_frame,
            self._trans_tencent_frame, self._trans_llm_frame,
            self._trans_bing_frame, self._trans_deepl_frame,
            self._trans_custom_frame,
        )
        frame_map = {
            "google": self._trans_google_frame,
            "baidu": self._trans_baidu_frame,
            "tencent": self._trans_tencent_frame,
            "llm": self._trans_llm_frame,
            "bing": self._trans_bing_frame,
            "deepl": self._trans_deepl_frame,
            "custom": self._trans_custom_frame,
        }
        for frm in all_frames:
            frm.pack_forget()
        target = frame_map.get(choice, self._trans_google_frame)
        target.pack(fill="x")

    def _apply_preset(self, choice: str, presets: dict) -> None:
        """应用预设配置"""
        if choice == "选择预设…":
            return
        p = presets.get(choice)
        if not p:
            return
        self.setting_url.delete(0, "end")
        self.setting_url.insert(0, p["base_url"])
        self.setting_model.delete(0, "end")
        self.setting_model.insert(0, p["model"])
        self.preset_status.configure(text=f"✓ 已填入 {choice}，请点保存")
        self._log(f"应用预设: {choice}")

    # ═══════════════════════════════════════════════════════════
    # 启动
    # ═══════════════════════════════════════════════════════════
    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    if sys.platform == "win32":
        import codecs
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")

    gui = ArxivAnalyzerGUI()
    gui.run()


if __name__ == "__main__":
    main()
