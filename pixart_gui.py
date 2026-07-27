#!/usr/bin/env python3
"""
pixart_gui.py — GUI 版像素密度字符画 (pixart)

功能：
  - 上传图片，自动匹配长宽比
  - 五种字符渐变集
  - 加减号调整参数
  - 实时预览
  - 复制到剪贴板
"""

import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import os
import sys

from pixart import convert_image, RAMPS

# ---- 参数定义: (名称, 最小值, 最大值, 默认值, 步长) ----
PARAMS = [
    ("宽度", 10, 300, 80, 5),
    ("高度", 0, 200, 0, 5),       # 0 = 自动
    ("对比度", 10, 300, 100, 10),  # 0.1x - 3.0x, 存储为整数
    ("亮度", -128, 128, 0, 16),
]


class PixArtGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("pixart — 像素密度字符画")
        self.root.geometry("950x720")
        self.root.minsize(800, 600)

        self.image_path = None
        self.pil_image = None
        self.thumb_tk = None

        self.params = {}
        self._build_ui()

    def _build_ui(self):
        # ========== 顶栏 ==========
        toolbar = tk.Frame(self.root)
        toolbar.pack(fill=tk.X, padx=8, pady=6)

        tk.Button(toolbar, text="📁 选择图片", command=self._pick_image,
                  padx=10).pack(side=tk.LEFT)
        self.file_label = tk.Label(toolbar, text="未选择图片", fg="gray",
                                   anchor=tk.W, width=30)
        self.file_label.pack(side=tk.LEFT, padx=10)

        tk.Frame(toolbar, width=2, bg="#ccc").pack(side=tk.LEFT, fill=tk.Y, padx=6)
        tk.Label(toolbar, text="字符集:").pack(side=tk.LEFT, padx=2)

        self.char_var = tk.StringVar(value="detailed")
        for key in RAMPS:
            names = {"detailed": "精细", "blocks": "方块",
                     "minimal": "极简", "ascii": "ASCII"}
            label = names.get(key, key)
            tk.Radiobutton(toolbar, text=label, variable=self.char_var,
                           value=key, command=self._convert,
                           indicatoron=0, width=7).pack(side=tk.LEFT, padx=2)

        # 反色 + 抖动
        self.invert_var = tk.BooleanVar(value=False)
        tk.Checkbutton(toolbar, text="反色", variable=self.invert_var,
                       command=self._convert).pack(side=tk.LEFT, padx=4)
        self.dither_var = tk.BooleanVar(value=False)
        tk.Checkbutton(toolbar, text="抖动", variable=self.dither_var,
                       command=self._convert).pack(side=tk.LEFT, padx=4)

        # ========== 中间：左右分栏 ==========
        paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashrelief=tk.RAISED,
                               sashwidth=4, bg="#ddd")
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # -- 左：图片预览 --
        left = tk.LabelFrame(paned, text="图片预览", padx=4, pady=4)
        paned.add(left, width=260, minsize=200)
        self.preview_label = tk.Label(left, bg="#f0f0f0", relief=tk.SUNKEN,
                                      anchor=tk.CENTER, text="点击上方按钮选择图片")
        self.preview_label.pack(fill=tk.BOTH, expand=True)

        # -- 右：字符画输出 --
        right = tk.LabelFrame(paned, text="字符画输出", padx=4, pady=4)
        paned.add(right, width=500, minsize=300)

        text_frame = tk.Frame(right)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.output_text = tk.Text(text_frame, wrap=tk.NONE,
                                   font=("Consolas", 9), relief=tk.SUNKEN, bd=2)
        vsb = tk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.output_text.yview)
        hsb = tk.Scrollbar(text_frame, orient=tk.HORIZONTAL, command=self.output_text.xview)
        self.output_text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ========== 底部控制区 ==========
        ctrl = tk.Frame(self.root, padx=8, pady=4)
        ctrl.pack(fill=tk.X)

        # 两行，每行两个参数
        for row_idx in range(2):
            row_frame = tk.Frame(ctrl)
            row_frame.pack(fill=tk.X, pady=4)
            for col_idx in range(2):
                param_idx = row_idx * 2 + col_idx
                if param_idx < len(PARAMS):
                    self._make_spinner(row_frame, param_idx, col_idx * 4)

        # 按钮行
        btn_frame = tk.Frame(ctrl)
        btn_frame.pack(fill=tk.X, pady=6)

        tk.Button(btn_frame, text="🔄 转换", padx=16,
                  command=self._convert).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_frame, text="📋 复制到剪贴板", padx=16,
                  command=self._copy).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_frame, text="↺ 重置", padx=16,
                  command=self._reset).pack(side=tk.LEFT, padx=4)

        # ========== 状态栏 ==========
        self.status_var = tk.StringVar(value="就绪")
        status = tk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN,
                          anchor=tk.W, padx=6)
        status.pack(fill=tk.X, side=tk.BOTTOM)

    def _make_spinner(self, parent, param_idx, col):
        """创建一组 标签 | [-] [数值] [+] 控件。"""
        name, vmin, vmax, default, step = PARAMS[param_idx]

        # 高度 0 显示"自动"
        is_height = name == "高度"

        var = tk.IntVar(value=default)
        label_name = "行数" if is_height else name

        tk.Label(parent, text=label_name, width=5, anchor=tk.E).grid(
            row=0, column=col, padx=(4, 2))

        btn_dec = tk.Button(parent, text="−", width=3,
                            command=lambda n=name, s=step: self._adjust(n, -s))
        btn_dec.grid(row=0, column=col + 1, padx=1)

        val_label = tk.Label(parent, text=str(default) if not is_height else "自动",
                             width=6, anchor=tk.CENTER,
                             font=("Consolas", 12, "bold"), relief=tk.RIDGE, bd=1)
        val_label.grid(row=0, column=col + 2, padx=2)

        btn_inc = tk.Button(parent, text="+", width=3,
                            command=lambda n=name, s=step: self._adjust(n, s))
        btn_inc.grid(row=0, column=col + 3, padx=1)

        btn_dec.bind("<Shift-Button-1>",
                     lambda e, n=name, s=step: self._adjust(n, -s * 5))
        btn_inc.bind("<Shift-Button-1>",
                     lambda e, n=name, s=step: self._adjust(n, s * 5))

        self.params[name] = {
            "var": var,
            "label": val_label,
            "min": vmin,
            "max": vmax,
            "step": step,
            "is_height": is_height,
        }

    # ── 事件处理 ──────────────────────────────────────────────

    def _adjust(self, name, delta):
        """增加/减少参数值，带边界钳制。"""
        p = self.params[name]
        current = p["var"].get()
        new_val = current + delta
        new_val = max(p["min"], min(p["max"], new_val))
        if new_val != current:
            p["var"].set(new_val)
            # 显示标签
            if p["is_height"] and new_val == 0:
                p["label"].config(text="自动")
            else:
                p["label"].config(text=str(new_val))
            if self.image_path:
                self._convert()

    def _pick_image(self):
        path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
                       ("所有文件", "*.*")],
        )
        if not path:
            return

        self.image_path = path
        self.file_label.config(text=os.path.basename(path), fg="black")

        self.pil_image = Image.open(path)
        self._show_thumbnail()
        self._auto_width()
        self._convert()

    def _show_thumbnail(self):
        if not self.pil_image:
            return
        img = self.pil_image.copy()
        img.thumbnail((240, 400), Image.Resampling.LANCZOS)
        self.thumb_tk = ImageTk.PhotoImage(img)
        self.preview_label.config(image=self.thumb_tk, text="")

    def _auto_width(self):
        """根据图片尺寸和字符密度推荐初始宽度。"""
        if not self.pil_image:
            return
        w, h = self.pil_image.size
        # 推荐宽度：让字符画在终端里舒适显示
        # 按图片长边 ≈ 120 字符
        max_side = max(w, h)
        recommended = int(120 * w / max_side)
        recommended = max(10, min(200, recommended))

        p = self.params["宽度"]
        p["var"].set(recommended)
        p["label"].config(text=str(recommended))

    def _convert(self, *_):
        if not self.image_path:
            return

        width = self.params["宽度"]["var"].get()
        height = self.params["高度"]["var"].get()
        contrast = self.params["对比度"]["var"].get() / 100.0
        brightness = self.params["亮度"]["var"].get()
        char_set = self.char_var.get()
        invert = self.invert_var.get()
        dither = self.dither_var.get()

        try:
            art, w, h = convert_image(
                self.image_path,
                width=width,
                height=height,
                char_set=char_set,
                invert=invert,
                contrast=contrast,
                brightness=brightness,
                dither=dither,
            )

            self.output_text.delete("1.0", tk.END)
            if art.strip():
                self.output_text.insert("1.0", art)
                lines = art.split("\n")
                chars = sum(len(ln) for ln in lines)
                parts = [f"尺寸: {w}×{h} 字符  总数: {chars}  字符集: {char_set}"]
                if dither:
                    parts.append("  抖动: 开")
                self.status_var.set("".join(parts))
            else:
                self.status_var.set("输出为空")
        except Exception as e:
            self.status_var.set(f"转换失败: {e}")

    def _copy(self):
        content = self.output_text.get("1.0", tk.END).strip()
        if content:
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.status_var.set("✅ 已复制到剪贴板")
        else:
            self.status_var.set("没有内容可复制")

    def _reset(self):
        for name, vmin, vmax, default, step in PARAMS:
            p = self.params[name]
            p["var"].set(default)
            if p["is_height"] and default == 0:
                p["label"].config(text="自动")
            else:
                p["label"].config(text=str(default))
        self.invert_var.set(False)
        self.dither_var.set(False)
        self.char_var.set("detailed")

        if self.image_path:
            self._convert()
        else:
            self.output_text.delete("1.0", tk.END)
            self.status_var.set("已重置")


if __name__ == "__main__":
    # Ensure UTF-8 for console
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

    root = tk.Tk()
    app = PixArtGUI(root)
    root.mainloop()
