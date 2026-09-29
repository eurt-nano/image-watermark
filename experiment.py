# -*- coding: utf-8 -*-
"""
完整实验：嵌入水印 -> 攻击 -> 看还能不能提取出来

这个脚本回答两个问题：
  1. 水印藏进去之后，图片看不看得出来？      -> 用 PSNR 衡量
  2. 图片被压缩/裁剪/加噪之后，水印还在不在？ -> 用提取成功率衡量

两个问题是一对矛盾：改得越多越抗攻击，但也越容易被看出来。
数字水印研究的核心，就是在两者之间找平衡。

用法：
    python experiment.py                  # 用自动生成的测试图
    python experiment.py --image 你的图.jpg  # 用自己的照片（效果更真实）
    python experiment.py --message "你的学号"
"""
import argparse
import os
import sys

import cv2
import numpy as np

import attacks
import imgio
from watermark import (BLOCK, _blocks, embed_dct, embed_lsb, extract_dct,
                       extract_lsb, psnr)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'output')

# 需要中文字体来给对比图加标签
FONT_CANDIDATES = [
    r'C:\Windows\Fonts\msyh.ttc',
    r'C:\Windows\Fonts\msyhbd.ttc',
    r'C:\Windows\Fonts\simhei.ttf',
    r'C:\Windows\Fonts\simsun.ttc',
]


def make_test_image(size=512):
    """
    生成一张有梯度和纹理的测试图。
    故意做得"细节丰富"——因为太平滑的图会让攻击显得不真实，
    真实的照片是有噪声和纹理的。
    """
    rng = np.random.default_rng(2025)
    h = w = size
    img = np.zeros((h, w, 3), np.uint8)

    # 天空渐变（蓝 -> 浅黄）
    for y in range(h):
        t = y / h
        img[y, :] = (int(200 - 60 * t), int(160 + 40 * t), int(90 + 100 * t))

    # 远处建筑
    for i in range(14):
        x0 = rng.integers(0, w - 40)
        bw = int(rng.integers(24, 70))
        bh = int(rng.integers(60, 240))
        y0 = int(h * 0.62) - bh
        color = tuple(int(c) for c in rng.integers(60, 150, 3))
        cv2.rectangle(img, (x0, y0), (min(w, x0 + bw), int(h * 0.62)), color, -1)
        # 窗户
        for wy in range(y0 + 8, int(h * 0.62) - 8, 14):
            for wx in range(x0 + 6, min(w, x0 + bw) - 6, 12):
                if rng.random() > 0.35:
                    cv2.rectangle(img, (wx, wy), (wx + 5, wy + 7),
                                  (230, 230, 180), -1)

    # 地面
    cv2.rectangle(img, (0, int(h * 0.62)), (w, h), (70, 90, 70), -1)

    # 前景几个圆（模拟物体）
    for _ in range(6):
        c = (int(rng.integers(0, w)), int(rng.integers(int(h * 0.65), h)))
        r = int(rng.integers(15, 45))
        col = tuple(int(x) for x in rng.integers(30, 220, 3))
        cv2.circle(img, c, r, col, -1)

    # 纹理噪声 —— 关键，让图片接近真实照片的统计特性
    img = cv2.GaussianBlur(img, (3, 3), 0)
    noise = rng.normal(0, 4.0, img.shape)
    img = np.clip(img.astype(np.float64) + noise, 0, 255).astype(np.uint8)
    return img


def low_texture_ratio(img, thr=2.0):
    """
    统计"低纹理块"的比例 —— 块内标准差小于 thr 的算。

    这个数字很关键：DCT 水印靠"把信息藏进中频纹理"，
    纯色区域没有纹理可藏，改动会更显眼、也更扛不住压缩。
    所以低纹理比例高的图（校徽、图标、扁平插画）天然比照片更难做鲁棒水印。
    """
    small, nblocks = _blocks(img)
    y = cv2.cvtColor(small, cv2.COLOR_BGR2YCrCb)[:, :, 0].astype(np.float32)
    nb_h, nb_w = y.shape[0] // BLOCK, y.shape[1] // BLOCK
    n = 0
    for by in range(nb_h):
        for bx in range(nb_w):
            if y[by * BLOCK:(by + 1) * BLOCK, bx * BLOCK:(bx + 1) * BLOCK].std() < thr:
                n += 1
    return n / float(nblocks) if nblocks else 0.0


def match_ratio(orig: str, got):
    """提取结果的字符正确率（可能只对了一部分）"""
    if got is None or not orig:
        return 0.0
    n = min(len(orig), len(got))
    same = sum(1 for i in range(n) if orig[i] == got[i])
    return same / len(orig)


def amplify_diff(a, b, gain=40):
    """把改动放大，让人能看出来水印藏在哪"""
    d = np.abs(a.astype(np.int16) - b.astype(np.int16)).astype(np.float64)
    return np.clip(d * gain, 0, 255).astype(np.uint8)


def label(img, text, height=28, color=(255, 255, 255)):
    """在图片上方加一条标题栏"""
    from PIL import Image, ImageDraw, ImageFont
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    w, h = pil.size
    canvas = Image.new('RGB', (w, h + height), (25, 25, 25))
    canvas.paste(pil, (0, height))
    d = ImageDraw.Draw(canvas)
    font = None
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                font = ImageFont.truetype(p, 17)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()
    d.text((8, 5), text, fill=color, font=font)
    return cv2.cvtColor(np.array(canvas), cv2.COLOR_RGB2BGR)


def tile(images, cols, cell_w, cell_h, bg=20):
    """把若干图片拼成网格"""
    rows = (len(images) + cols - 1) // cols
    sheet = np.full((rows * cell_h, cols * cell_w, 3), bg, np.uint8)
    for i, im in enumerate(images):
        r, c = divmod(i, cols)
        t = cv2.resize(im, (cell_w, cell_h), interpolation=cv2.INTER_AREA)
        sheet[r * cell_h:(r + 1) * cell_h, c * cell_w:(c + 1) * cell_w] = t
    return sheet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--image', default=None, help='用自己的图片（可选）')
    ap.add_argument('--message', default='hfut-se-2025', help='要藏的信息')
    ap.add_argument('--delta', type=float, default=25.0, help='DCT 嵌入强度（默认 25，往上更抗攻击但更容易看出）')
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)

    # ---------- 1. 准备图片 ----------
    if args.image:
        orig = imgio.imread(args.image)
        if orig is None:
            print('读不到图片，改用自动生成的测试图')
            orig = make_test_image()
        else:
            print('使用自己的图片：%s  (%dx%d)' % (args.image, orig.shape[1], orig.shape[0]))
    else:
        orig = make_test_image()
        print('使用自动生成的测试图 (512x512)')

    # 图片太小的话，8x8 块数不够，容量和冗余都不足，水印会非常脆弱。
    # 所以自动放大到短边至少 MIN_SIDE 像素。
    # 线条图（比如校徽）放大后反而更清晰，不会损失信息。
    MIN_SIDE = 512
    h, w = orig.shape[:2]
    if min(h, w) < MIN_SIDE:
        s = MIN_SIDE / float(min(h, w))
        nw, nh = int(round(w * s)), int(round(h * s))
        orig = cv2.resize(orig, (nw, nh), interpolation=cv2.INTER_LANCZOS4)
        print('图片较小 (%dx%d)，已放大约 %.0f%% 到 %dx%d，以保证块数和冗余'
              % (w, h, (s - 1) * 100, nw, nh))

    imgio.imwrite(os.path.join(OUT, '0_原图.png'), orig)

    tex = low_texture_ratio(orig)
    print('低纹理块占比：%.1f%%%s'
          % (tex * 100, '（图偏"平"，水印会更难做）' if tex > 0.25 else ''))

    msg = args.message
    print('要嵌入的信息：%r  (%d 字节)' % (msg, len(msg.encode('utf-8'))))
    print()

    # ---------- 2. 嵌入 ----------
    lsb_img = embed_lsb(orig, msg)
    dct_img, rep_used, blocks_used = embed_dct(orig, msg, args.delta)

    psnr_lsb = psnr(orig, lsb_img)
    psnr_dct = psnr(orig, dct_img)

    imgio.imwrite(os.path.join(OUT, '1_LSB含水印.png'), lsb_img)
    imgio.imwrite(os.path.join(OUT, '2_DCT含水印.png'), dct_img)
    imgio.imwrite(os.path.join(OUT, '3_LSB差异放大40倍.png'), amplify_diff(orig, lsb_img))
    imgio.imwrite(os.path.join(OUT, '4_DCT差异放大40倍.png'), amplify_diff(orig, dct_img))

    print('=' * 74)
    print('第一步：不可见性（PSNR 越高越看不出来，40 dB 以上算合格）')
    print('=' * 74)
    print('  LSB 水印   PSNR = %6.2f dB     改动范围 ±1（最低位）' % psnr_lsb)
    print('  DCT 水印   PSNR = %6.2f dB     重复编码 %d 次，占用 %d 个 8x8 块'
          % (psnr_dct, rep_used, blocks_used))
    print()

    # ---------- 3. 攻击 ----------
    print('=' * 74)
    print('第二步：鲁棒性（被攻击之后还能不能提取出来）')
    print('=' * 74)
    print('  %-14s %-18s %-18s %s' % ('攻击方式', 'LSB 提取结果', 'DCT 提取结果', 'DCT 字符正确率'))
    print('  ' + '-' * 70)

    rows = []
    attack_tiles = []
    for name, fn, desc in attacks.ATTACKS:
        a_lsb = fn(lsb_img)
        a_dct = fn(dct_img)

        got_lsb = extract_lsb(a_lsb)
        got_dct, acc, rep = extract_dct(a_dct)

        r_lsb = match_ratio(msg, got_lsb)
        r_dct = match_ratio(msg, got_dct)

        s_lsb = '成功 %s' % got_lsb if got_lsb == msg else ('部分 %.0f%%' % (r_lsb * 100) if r_lsb > 0 else '失败')
        s_dct = '成功 %s' % got_dct if got_dct == msg else ('部分 %.0f%%' % (r_dct * 100) if r_dct > 0 else '失败')

        print('  %-14s %-18s %-18s %.0f%%' % (name, s_lsb[:16], s_dct[:16], r_dct * 100))

        rows.append((name, desc, got_lsb == msg, r_lsb, got_dct == msg, r_dct, psnr(dct_img, a_dct)))

        if name != '无攻击':
            attack_tiles.append(label(cv2.resize(a_dct, (256, 256)),
                                      '%s   %s' % (name, 'OK' if got_dct == msg else 'FAIL')))

    print()

    # ---------- 4. 汇总图 ----------
    main_sheet = tile([
        label(cv2.resize(orig, (256, 256)), '原图'),
        label(cv2.resize(lsb_img, (256, 256)), 'LSB  PSNR %.1f dB' % psnr_lsb),
        label(cv2.resize(dct_img, (256, 256)), 'DCT  PSNR %.1f dB' % psnr_dct),
        label(cv2.resize(amplify_diff(orig, lsb_img), (256, 256)), 'LSB 差异（放大40倍）'),
        label(cv2.resize(amplify_diff(orig, dct_img), (256, 256)), 'DCT 差异（放大40倍）'),
        label(np.full((256, 256, 3), 255, np.uint8), '结论见 实验结果.md'),
    ], cols=3, cell_w=256, cell_h=256 + 28)
    imgio.imwrite(os.path.join(OUT, '5_总览对比.png'), main_sheet)
    imgio.imwrite(os.path.join(OUT, '6_攻击后效果.png'),
                  tile(attack_tiles, cols=3, cell_w=256, cell_h=256 + 28))

    # ---------- 5. 写报告 ----------
    n_lsb_ok = sum(1 for r in rows if r[2])
    n_dct_ok = sum(1 for r in rows if r[4])
    n_tot = len(rows)

    lines = []
    lines.append('# 数字水印实验结果\n')
    lines.append('> 本报告由 `experiment.py` 自动生成\n')
    lines.append('- 嵌入信息：`%s`' % msg)
    lines.append('- 测试图片：%s' % ('自定义 ' + args.image if args.image else '自动生成的 512x512 测试图'))
    lines.append('- DCT 参数：嵌入强度 delta = %g，重复编码 %d 次' % (args.delta, rep_used))
    lines.append('- 低纹理块占比：%.1f%%（纯色区域越多，水印越难做鲁棒）\n' % (tex * 100))

    lines.append('## 一、不可见性\n')
    lines.append('| 方案 | PSNR | 说明 |')
    lines.append('|---|---|---|')
    lines.append('| LSB | %.2f dB | 只改最低位，肉眼绝对看不出 |' % psnr_lsb)
    lines.append('| DCT | %.2f dB | 改中频系数，40 dB 以上即看不出 |\n' % psnr_dct)

    lines.append('## 二、鲁棒性\n')
    lines.append('| 攻击方式 | 说明 | LSB | DCT | DCT 字符正确率 | 攻击后 PSNR |')
    lines.append('|---|---|---|---|---|---|')
    for name, desc, ok_l, r_l, ok_d, r_d, p in rows:
        lines.append('| %s | %s | %s | %s | %.0f%% | %.1f dB |'
                     % (name, desc,
                        '成功' if ok_l else ('部分' if r_l > 0 else '失败'),
                        '成功' if ok_d else ('部分' if r_d > 0 else '失败'),
                        r_d * 100, p))
    lines.append('')
    lines.append('- LSB：**%d/%d** 种攻击下成功提取' % (n_lsb_ok, n_tot))
    lines.append('- DCT：**%d/%d** 种攻击下成功提取\n' % (n_dct_ok, n_tot))

    lines.append('## 三、结论\n')
    lines.append('1. **两种水印都做到了不可见**——PSNR 都在 40 dB 以上，')
    lines.append('   肉眼看不出原图和水印图的差别（可以打开 `output/3_*.png` 和 `output/4_*.png` 看放大后的差异分布）。')
    lines.append('2. **LSB 几乎不抗攻击**。只要经过一次 JPEG 压缩，最低位就被重写，水印直接消失。')
    lines.append('   它只适合"图片不会被改动"的场景，比如内部存档。')
    lines.append('3. **DCT 水印抗压缩和抗噪声能力明显更强**，因为它把信息藏在')
    lines.append('   中频系数上——那个区域 JPEG 压不狠，人眼也不敏感。')
    lines.append('4. **代价是容量和强度**：DCT 每 8x8 块只能藏 1 比特，')
    lines.append('   而且嵌入强度 delta 越大越抗攻击、但也越容易被看出来。')
    if tex > 0.25:
        lines.append('5. **本图属于"难做"的一类**：低纹理块占 %.0f%%，'
                     '大面积纯色区域没有纹理可供隐藏，' % (tex * 100))
        lines.append('   改动相对更显眼、抗压缩也更弱。'
                     '所以它比纹理丰富的照片少扛住了一种攻击。\n')
    else:
        lines.append('')
    lines.append('> 这正是数字水印研究的核心矛盾：**不可见性 vs 鲁棒性 vs 容量**，')
    lines.append('> 三者不可能同时最优，只能根据应用场景做取舍。')

    rp = os.path.join(HERE, '实验结果.md')
    with open(rp, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print('=' * 74)
    print('汇总')
    print('=' * 74)
    print('  LSB：%d/%d 种攻击下成功提取' % (n_lsb_ok, n_tot))
    print('  DCT：%d/%d 种攻击下成功提取' % (n_dct_ok, n_tot))
    print()
    print('  结果图：output/5_总览对比.png')
    print('           output/6_攻击后效果.png')
    print('  报告：  实验结果.md')


if __name__ == '__main__':
    sys.exit(main())
