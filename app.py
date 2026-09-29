# -*- coding: utf-8 -*-
"""
数字水印工作台 · 交互版

把"嵌入 → 攻击 → 检测"整条链路做成可手动操作的界面：

    ① 载入图片，输入要藏的信息，选方法（LSB / DCT），点「嵌入水印」
    ② 拖动攻击滑块（JPEG 压缩 / 裁剪 / 噪声 / 缩放 / 亮度）
    ③ 实时看检测结果 —— 水印在哪一档攻击下失效，一目了然

界面用 Tkinter（Python 自带，无需安装）。

用法：
    python app.py
"""
import os
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

import attacks
import imgio
from watermark import (embed_dct, embed_lsb, extract_dct, extract_lsb, psnr)

HERE = os.path.dirname(os.path.abspath(__file__))
UI = ('Microsoft YaHei', 9)
UI_B = ('Microsoft YaHei', 9, 'bold')
MONO = ('Consolas', 9)

MAX_SIDE = 800          # 工作分辨率上限（超出则等比缩小，保证交互流畅）
MIN_SIDE = 512          # 工作分辨率下限（不足则放大，保证分块数与冗余）
CANVAS_W, CANVAS_H = 630, 400

FONTS = [r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\msyhbd.ttc',
         r'C:\Windows\Fonts\simhei.ttf']


def font(sz, bold=False):
    order = ([FONTS[1]] if bold else []) + FONTS
    for p in order:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
    return ImageFont.load_default()


def label_bar(img, text, h=26):
    """给图片顶部加一条标题栏"""
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    w = pil.width
    canvas = Image.new('RGB', (w, pil.height + h), (28, 32, 38))
    canvas.paste(pil, (0, h))
    ImageDraw.Draw(canvas).text((8, 4), text, font=font(15, True),
                                fill=(235, 235, 235))
    return canvas


def default_image():
    """默认用目录里的校徽；没有就生成一张测试图"""
    p = os.path.join(HERE, '校徽.png')
    if os.path.exists(p):
        im = imgio.imread(p)
        if im is not None:
            return im
    rng = np.random.default_rng(7)
    img = np.zeros((512, 512, 3), np.uint8)
    for y in range(512):
        img[y, :] = (int(200 - 60 * y / 512), int(160 + 40 * y / 512),
                     int(90 + 100 * y / 512))
    for _ in range(40):
        c = tuple(int(v) for v in rng.integers(0, 512, 2))
        r = int(rng.integers(20, 80))
        col = tuple(int(v) for v in rng.integers(40, 230, 3))
        cv2.circle(img, tuple(int(x) for x in c), r, col, -1)
    img = cv2.GaussianBlur(img, (3, 3), 0)
    return np.clip(img.astype(np.float64) + rng.normal(0, 4, img.shape),
                   0, 255).astype(np.uint8)


class App:
    def __init__(self, root):
        self.root = root
        root.title('数字水印工作台 · 交互版')
        root.configure(bg='#f2f3f5')

        self.orig = None          # 原图
        self.wm = None            # 含水印图
        self.attacked = None      # 攻击后
        self.photo = None
        self.pending = None
        self.embedded_msg = None
        self.embed_info = ''

        self.msg = tk.StringVar(value='hfut-se-2025')
        self.method = tk.StringVar(value='dct')
        self.v_jpeg = tk.IntVar(value=100)
        self.v_crop = tk.IntVar(value=0)
        self.v_noise = tk.IntVar(value=0)
        self.v_scale = tk.IntVar(value=100)
        self.v_bright = tk.IntVar(value=0)

        self._build_ui()
        self.load(default_image(), '校徽.png（内置）')

    # ------------------------------------------------------------ 界面

    def _build_ui(self):
        # 右侧面板先 pack —— 否则左侧 expand=True 会把它挤出窗口
        right = tk.Frame(self.root, bg='white', width=330)
        right.pack(side='right', fill='y', padx=(0, 10), pady=10)
        right.pack_propagate(False)

        left = tk.Frame(self.root, bg='#f2f3f5')
        left.pack(side='left', fill='both', expand=True, padx=(10, 6), pady=10)

        self.canvas = tk.Canvas(left, width=CANVAS_W, height=CANVAS_H, bg='white',
                                highlightthickness=1, highlightbackground='#d0d3d8')
        self.canvas.pack()

        self.status = tk.Label(left, text='', font=UI, bg='#f2f3f5', fg='#444',
                               anchor='w', justify='left')
        self.status.pack(fill='x', pady=(6, 0))

        # ---------- ① 水印设置 ----------
        self._sec(right, '① 水印设置')
        row = tk.Frame(right, bg='white')
        row.pack(fill='x', padx=14)
        tk.Label(row, text='信息', font=UI, bg='white').pack(side='left')
        tk.Entry(row, textvariable=self.msg, font=MONO).pack(
            side='left', fill='x', expand=True, padx=(6, 0))

        f = tk.Frame(right, bg='white')
        f.pack(fill='x', padx=14, pady=(6, 0))
        tk.Label(f, text='方法', font=UI, bg='white').pack(side='left')
        tk.Radiobutton(f, text='DCT（抗攻击）', variable=self.method, value='dct',
                       font=UI, bg='white', activebackground='white').pack(side='left',
                                                                          padx=(6, 0))
        tk.Radiobutton(f, text='LSB（脆弱）', variable=self.method, value='lsb',
                       font=UI, bg='white', activebackground='white').pack(side='left')

        bf = tk.Frame(right, bg='white')
        bf.pack(fill='x', padx=14, pady=(8, 0))
        tk.Button(bf, text='选择图片', font=UI, command=self.pick,
                  width=9).pack(side='left')
        tk.Button(bf, text='嵌入水印', font=UI_B, command=self.embed,
                  width=10).pack(side='right')

        self.lbl_embed = tk.Label(right, text='尚未嵌入水印', font=MONO, bg='white',
                                  fg='#8a8e95', anchor='w', justify='left')
        self.lbl_embed.pack(fill='x', padx=14, pady=(6, 0))

        # ---------- ② 攻击 ----------
        self._sec(right, '② 施加攻击（拖动滑块）')
        tk.Label(right, text='拖动可实时看到水印在哪种攻击下失效',
                 font=('Microsoft YaHei', 8), bg='white', fg='#8a8e95',
                 anchor='w').pack(fill='x', padx=14)

        self.sliders = {}
        for key, var, lo, hi, lab, fmt in (
                ('jpeg', self.v_jpeg, 10, 100, 'JPEG 质量', '%d'),
                ('crop', self.v_crop, 0, 200, '裁剪像素', '%d'),
                ('noise', self.v_noise, 0, 100, '高斯噪声', '%d'),
                ('scale', self.v_scale, 20, 100, '缩放 %', '%d'),
                ('bright', self.v_bright, -40, 40, '亮度', '%+d')):
            r = tk.Frame(right, bg='white')
            r.pack(fill='x', padx=14, pady=1)
            tk.Label(r, text=lab, font=UI, bg='white', width=8,
                     anchor='w').pack(side='left')
            s = tk.Scale(r, from_=lo, to=hi, orient='horizontal', variable=var,
                         showvalue=0, length=150, bg='white', highlightthickness=0,
                         sliderlength=14, command=lambda v: self.on_attack())
            s.pack(side='left', padx=(2, 6))
            lv = tk.Label(r, text=fmt % var.get(), font=MONO, bg='white',
                          width=5, anchor='e')
            lv.pack(side='right')
            self.sliders[key] = (s, lv, fmt)

        tk.Button(right, text='重置攻击', font=UI, command=self.reset_attacks,
                  width=10).pack(anchor='w', padx=14, pady=(8, 0))

        # ---------- ③ 检测 ----------
        self._sec(right, '③ 检测结果')
        self.result = tk.Label(right, text='请先嵌入水印', font=('Microsoft YaHei', 10),
                               bg='#f7f8fa', fg='#24282e', justify='left',
                               anchor='nw', relief='solid', bd=1, padx=10, pady=8,
                               wraplength=290, height=6)
        self.result.pack(fill='x', padx=14)
        tk.Button(right, text='重新检测', font=UI, command=self.detect,
                  width=10).pack(anchor='w', padx=14, pady=(8, 14))

    def _sec(self, parent, text):
        tk.Label(parent, text=text, font=UI_B, bg='white', anchor='w').pack(
            fill='x', padx=14, pady=(14, 4))

    # ------------------------------------------------------------ 数据流

    def load(self, img, name=''):
        h, w = img.shape[:2]
        note = ''
        # 太大：压到工作分辨率，保证交互流畅
        if max(h, w) > MAX_SIDE:
            s = MAX_SIDE / float(max(h, w))
            img = cv2.resize(img, (int(round(w * s)), int(h * s)),
                             interpolation=cv2.INTER_AREA)
            note = '（已缩至 %d×%d）' % (img.shape[1], img.shape[0])
        # 太小：放大到短边至少 MIN_SIDE
        # 8x8 分块数不够时，重复编码次数太少、水印会非常脆弱；
        # 这里和命令行实验用同一套规则，保证两边结果可比。
        elif min(h, w) < MIN_SIDE:
            s = MIN_SIDE / float(min(h, w))
            img = cv2.resize(img, (int(round(w * s)), int(round(h * s))),
                             interpolation=cv2.INTER_LANCZOS4)
            note = '（原图偏小，已放大至 %d×%d）' % (img.shape[1], img.shape[0])
        self.orig = img
        self.src_name = (name or '') + note
        self.wm = self.attacked = None
        self.embedded_msg = None
        self.reset_attacks(silent=True)
        self.lbl_embed.config(text='尚未嵌入水印')
        self.result.config(text='请先嵌入水印', fg='#24282e')
        self.show()
        self.set_status()

    def pick(self):
        p = filedialog.askopenfilename(
            filetypes=[('图片', '*.png *.jpg *.jpeg *.bmp *.webp'), ('所有文件', '*.*')])
        if not p:
            return
        im = imgio.imread(p)
        if im is None:
            messagebox.showerror('读图失败', '无法读取：\n%s' % p)
            return
        self.load(im, os.path.basename(p))

    def embed(self):
        if self.orig is None:
            return
        msg = self.msg.get().strip()
        if not msg:
            messagebox.showwarning('提示', '请输入要嵌入的信息')
            return
        try:
            t0 = time.time()
            if self.method.get() == 'dct':
                wm, rep, used = embed_dct(self.orig, msg)
                note = '重复编码 %d 次，占用 %d 个 8x8 块' % (rep, used)
            else:
                wm = embed_lsb(self.orig, msg)
                note = '改写像素最低位'
            dt = time.time() - t0
        except ValueError as e:
            messagebox.showerror('嵌入失败', str(e))
            return
        self.wm = wm
        self.embedded_msg = msg
        self.attacked = None
        self.embed_info = note
        self.lbl_embed.config(
            text='已嵌入「%s」\nPSNR %.2f dB（越高越看不出）\n%s\n耗时 %.3f 秒'
                 % (msg, psnr(self.orig, wm), note, dt), fg='#24282e')
        self.reset_attacks(silent=True)
        self.show()
        self.detect()

    def on_attack(self):
        for k, (_, lv, fmt) in self.sliders.items():
            lv.config(text=fmt % getattr(self, 'v_' + k).get())
        self.apply_attacks()
        self.show()
        self.set_status()
        # 检测稍慢（约 0.2 秒），加防抖，拖动时不至于卡顿
        if self.pending:
            self.root.after_cancel(self.pending)
        self.pending = self.root.after(180, self.detect)

    def apply_attacks(self):
        """按当前滑块参数依次施加攻击；参数为默认值时跳过该步"""
        if self.wm is None:
            return
        out = self.wm
        try:
            if self.v_jpeg.get() < 100:
                out = attacks.attack_jpeg(out, self.v_jpeg.get())
            if self.v_crop.get() > 0:
                out = attacks.attack_crop(out, self.v_crop.get())
            if self.v_noise.get() > 0:
                out = attacks.attack_noise(out, self.v_noise.get() / 10.0)
            if self.v_scale.get() < 100:
                out = attacks.attack_resize(out, self.v_scale.get() / 100.0)
            if self.v_bright.get() != 0:
                out = attacks.attack_brighten(out, self.v_bright.get())
        except Exception:
            out = self.wm
        self.attacked = out if out is not self.wm else None

    def reset_attacks(self, silent=False):
        self.v_jpeg.set(100)
        self.v_crop.set(0)
        self.v_noise.set(0)
        self.v_scale.set(100)
        self.v_bright.set(0)
        for k, (s, lv, fmt) in self.sliders.items():
            s.set(getattr(self, 'v_' + k).get())
            lv.config(text=fmt % getattr(self, 'v_' + k).get())
        self.attacked = None
        if not silent:
            self.show()
            self.set_status()
            self.detect()

    def detect(self):
        self.pending = None
        if self.wm is None or self.embedded_msg is None:
            self.result.config(text='请先嵌入水印', fg='#24282e')
            return
        src = self.attacked if self.attacked is not None else self.wm
        t0 = time.time()
        if self.method.get() == 'dct':
            got, acc, rep = extract_dct(src)
            extra = '投票一致率 %.1f%%　重复 %d 次' % (acc * 100, rep)
        else:
            got = extract_lsb(src)
            extra = '直接读取最低位，无冗余'
        dt = time.time() - t0

        ok = (got == self.embedded_msg)
        attack_on = self.attacked is not None
        if ok:
            state = '⚠ 未受攻击' if not attack_on else '✅ 抵御成功'
            col = '#1a7f42' if attack_on else '#8a6d1a'
            body = '提取到：%s' % got
        elif got is None:
            state, col, body = '❌ 水印已被破坏', '#c0392b', '提取失败（无法还原）'
        else:
            state, col, body = '❌ 水印已被破坏', '#c0392b', '提取到乱码：%s' % got[:24]

        self.result.config(
            text='%s\n%s\n%s\n攻击后 PSNR %.1f dB\n检测耗时 %.3f 秒'
                 % (state, body, extra,
                    psnr(self.wm, src) if attack_on else float('inf'), dt), fg=col)

    # ------------------------------------------------------------ 显示

    def show(self):
        if self.orig is None:
            return
        cur = self.attacked if self.attacked is not None else (
            self.wm if self.wm is not None else self.orig)
        if self.attacked is not None:
            cap = '当前 · 攻击后'
        elif self.wm is not None:
            cap = '当前 · 含水印'
        else:
            cap = '当前 · 原图'
        a = label_bar(self.orig, '原图')
        b = label_bar(cur, cap)
        gap = 12
        sheet = Image.new('RGB', (a.width + b.width + gap, max(a.height, b.height)),
                          (255, 255, 255))
        sheet.paste(a, (0, 0))
        sheet.paste(b, (a.width + gap, 0))
        s = min(CANVAS_W / sheet.width, CANVAS_H / sheet.height, 1.0)
        if s < 1.0:
            sheet = sheet.resize((int(sheet.width * s), int(sheet.height * s)),
                                 Image.LANCZOS)
        self.photo = ImageTk.PhotoImage(sheet)
        self.canvas.delete('all')
        self.canvas.create_image(CANVAS_W // 2, CANVAS_H // 2, image=self.photo,
                                 anchor='center')

    def set_status(self):
        if self.orig is None:
            return
        h, w = self.orig.shape[:2]
        s = '图片：%s　%d×%d' % (self.src_name or '—', w, h)
        if self.attacked is not None:
            on = [k for k in ('jpeg', 'crop', 'noise', 'scale', 'bright')
                  if (getattr(self, 'v_' + k).get() not in (100, 0))]
            s += '　|　已施加攻击：%s' % ('、'.join(on) if on else '无')
        self.status.config(text=s)


def main():
    root = tk.Tk()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w = min(1320, max(1040, int(sw * 0.88)))
    h = min(780, max(640, int(sh * 0.88)))
    root.geometry('%dx%d+%d+%d' % (w, h, (sw - w) // 2, max(0, (sh - h) // 2 - 20)))
    root.minsize(1040, 640)
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
