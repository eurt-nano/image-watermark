# -*- coding: utf-8 -*-
"""
把实验结果合成一张"成果汇总图"，用来发给导师或贴进仓库 README。

内容包含：
  1. 流程示意（原图 -> 嵌入 -> 攻击 -> 提取）
  2. 原图 / 两种水印图 / 放大后的差异图
  3. 10 种攻击下的成败对照表

用法：
    python experiment.py --image 校徽.png     # 先跑实验
    python make_poster.py                     # 再生成汇总图
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'output')

FONTS = [r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\msyhbd.ttc',
         r'C:\Windows\Fonts\simhei.ttf']
RED = (150, 30, 45)          # 与校徽呼应的红
DARK = (28, 32, 38)
GREEN, FAIL = (22, 140, 70), (200, 45, 45)


def font(sz, bold=False):
    order = ([FONTS[1]] if bold else []) + FONTS
    for p in order:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
    return ImageFont.load_default()


def read_results():
    """从 实验结果.md 里读出攻击对照表"""
    rows, meta = [], {}
    p = os.path.join(HERE, '实验结果.md')
    if not os.path.exists(p):
        return rows, meta
    for ln in open(p, encoding='utf-8'):
        ln = ln.strip()
        if ln.startswith('- 嵌入信息'):
            meta['msg'] = ln.split('`')[1]
        if ln.startswith('- DCT 参数'):
            meta['param'] = ln.replace('- DCT 参数：', '').strip()
        if ln.startswith('- 测试图片'):
            meta['image'] = ln.replace('- 测试图片：', '').strip()
        if not ln.startswith('|') or '---' in ln:
            continue
        c = [x.strip() for x in ln.strip('|').split('|')]
        if len(c) == 6 and c[0] != '攻击方式':
            rows.append(c)
    return rows, meta


def arrow(d, x1, y, x2):
    """画一个从 x1 到 x2 的水平箭头"""
    d.line([x1, y, x2 - 10, y], fill=RED, width=3)
    d.polygon([(x2, y), (x2 - 13, y - 7), (x2 - 13, y + 7)], fill=RED)


def main():
    rows, meta = read_results()
    if not rows:
        print('没找到 实验结果.md，请先运行 python experiment.py')
        return

    # 测试图名 + 尺寸（原图 -> 实际使用尺寸），标题和流程图都要用
    src_name = (meta.get('image') or '').replace('自定义 ', '').strip()
    src_p = os.path.join(HERE, src_name) if src_name else ''
    size_note = ''
    try:
        a = Image.open(src_p).size
        b = Image.open(os.path.join(OUT, '0_原图.png')).size
        size_note = ('%d×%d → %d×%d' % (a[0], a[1], b[0], b[1])
                     if a != b else '%d×%d' % b)
    except Exception:
        pass

    W, H = 1700, 975
    img = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)

    # ---------- 标题 ----------
    d.rectangle([0, 0, W, 78], fill=DARK)
    d.text((28, 22), '数字水印与鲁棒性评测', font=font(31, True), fill=(255, 255, 255))
    d.text((450, 34), '%s    |    嵌入 "%s"'
           % (os.path.splitext(src_name)[0] if src_name else '测试图', meta.get('msg', '')),
           font=font(18), fill=(230, 180, 190))
    n_dct = sum(1 for r in rows if r[3] == '成功')
    n_lsb = sum(1 for r in rows if r[2] == '成功')
    d.text((W - 300, 24), 'LSB  %d/%d' % (n_lsb, len(rows)), font=font(21, True), fill=(240, 130, 130))
    d.text((W - 300, 50), 'DCT  %d/%d' % (n_dct, len(rows)), font=font(21, True), fill=(120, 230, 160))

    # ---------- 流程示意 ----------
    steps = [(os.path.splitext(src_name)[0] if src_name else '测试图', size_note),
             ('嵌入水印', 'LSB / DCT 两种方案'),
             ('含水印图', 'PSNR > 40 dB'), ('10 种攻击', 'JPEG·缩放·噪声·裁剪'),
             ('攻击后图片', '模拟网络传播损耗'), ('提取 + 投票', '打散后多数表决')]
    bw, bh, gap = 226, 74, 30
    total = len(steps) * bw + (len(steps) - 1) * gap
    bx = (W - total) // 2
    by = 100
    for i, (t1, t2) in enumerate(steps):
        x = bx + i * (bw + gap)
        col = RED if i in (0, 2, 4) else (60, 66, 74)
        d.rounded_rectangle([x, by, x + bw, by + bh], radius=9,
                            fill=(252, 244, 245) if i % 2 == 0 else (245, 247, 250),
                            outline=col, width=2)
        d.text((x + bw / 2, by + 14), t1, font=font(17, True), fill=DARK, anchor='ma')
        d.text((x + bw / 2, by + 43), t2, font=font(12), fill=(120, 124, 130), anchor='ma')
        if i < len(steps) - 1:
            arrow(d, x + bw + 4, by + bh / 2, x + bw + gap - 2)

    d.text((26, by + bh + 12), '流程：把水印嵌进校徽，再模拟图片在网上传播时会遭遇的破坏，最后看信息还能不能读出来。',
           font=font(15), fill=(110, 114, 120))

    # ---------- 左侧：图片 ----------
    IW = 296
    y0 = 232
    pics = [('0_原图.png', '校徽原图', DARK),
            ('1_LSB含水印.png', 'LSB 含水印   PSNR 91.0 dB', DARK),
            ('2_DCT含水印.png', 'DCT 含水印   PSNR 41.4 dB', DARK)]
    for i, (fn, cap, c) in enumerate(pics):
        x = 26 + i * (IW + 16)
        d.text((x + 2, y0), cap, font=font(17, True), fill=c)
        p = os.path.join(OUT, fn)
        if os.path.exists(p):
            im = Image.open(p).convert('RGB')
            im.thumbnail((IW, IW - 40), Image.LANCZOS)
            img.paste(im, (x + (IW - im.width) // 2, y0 + 26))
            d.rectangle([x, y0 + 26, x + IW, y0 + 26 + im.height], outline=(215, 215, 215))

    y1 = y0 + 330
    dpics = [('3_LSB差异放大40倍.png', 'LSB 改动（放大 40 倍）', '几乎全黑 → 改动极小'),
             ('4_DCT差异放大40倍.png', 'DCT 改动（放大 40 倍）', '纹理均匀铺满 → 分散隐藏')]
    for i, (fn, cap, note) in enumerate(dpics):
        x = 26 + i * (IW + 16)
        d.text((x + 2, y1), cap, font=font(17, True), fill=RED)
        p = os.path.join(OUT, fn)
        if os.path.exists(p):
            im = Image.open(p).convert('RGB')
            im.thumbnail((IW, IW - 40), Image.LANCZOS)
            img.paste(im, (x, y1 + 26))
            d.rectangle([x, y1 + 26, x + im.width, y1 + 26 + im.height], outline=(215, 215, 215))
        d.text((x + 2, y1 + 26 + 296 + 4), note, font=font(13), fill=(130, 134, 140))

    # ---------- 右侧：结果表 ----------
    tx, ty = 1006, 232
    tw = W - tx - 30
    d.text((tx, ty), '鲁棒性对照（10 种攻击）', font=font(20, True), fill=DARK)
    ty += 36

    d.rectangle([tx, ty, tx + tw, ty + 32], fill=(240, 242, 245))
    for label, dx in (('攻击方式', 12), ('LSB', 300), ('DCT', 380), ('正确率', 470), ('攻击后 PSNR', 550)):
        d.text((tx + dx, ty + 8), label, font=font(15, True), fill=(60, 64, 70))
    ty += 32

    for i, r in enumerate(rows):
        if i % 2:
            d.rectangle([tx, ty, tx + tw, ty + 29], fill=(251, 252, 253))
        d.text((tx + 12, ty + 6), r[0], font=font(15), fill=(45, 48, 52))
        ok_l, ok_d = r[2] == '成功', r[3] == '成功'
        d.text((tx + 300, ty + 6), '成功' if ok_l else '失败', font=font(15, True),
               fill=GREEN if ok_l else FAIL)
        d.text((tx + 380, ty + 6), '成功' if ok_d else '失败', font=font(15, True),
               fill=GREEN if ok_d else FAIL)
        d.text((tx + 470, ty + 6), r[4], font=font(15), fill=(90, 94, 100))
        d.text((tx + 550, ty + 6), r[5], font=font(15), fill=(90, 94, 100))
        ty += 29

    ty += 18
    d.rounded_rectangle([tx, ty, tx + tw, ty + 96], radius=8,
                        fill=(255, 246, 247), outline=(220, 170, 175), width=2)
    d.text((tx + 16, ty + 12), '结论', font=font(17, True), fill=RED)
    d.text((tx + 16, ty + 38), 'LSB   %d/%d  一次 JPEG 压缩即失效' % (n_lsb, len(rows)),
           font=font(16), fill=FAIL)
    dct_fail = [r[0] for r in rows if r[3] != '成功' and r[0] != '无攻击']
    dct_note = ('仅 %s 失效' % dct_fail[0]) if len(dct_fail) == 1 else \
               ('在 %d 种攻击下失效' % len(dct_fail) if dct_fail else '全部通过')
    d.text((tx + 16, ty + 65), 'DCT   %d/%d  %s' % (n_dct, len(rows), dct_note),
           font=font(16), fill=GREEN)

    ty += 118
    d.text((tx, ty), '校徽这类"大面积纯色 + 细线条"的图比照片更难做水印：', font=font(14), fill=(90, 94, 100))
    d.text((tx, ty + 22), '纯色区域没有纹理可供隐藏，改动相对更显眼，抗压缩也更弱。', font=font(14), fill=(90, 94, 100))

    # ---------- 页脚 ----------
    d.line([26, H - 52, W - 26, H - 52], fill=(225, 225, 225))
    d.text((26, H - 40), '生成：python experiment.py --image 校徽.png   →   python make_poster.py      '
                         '|    %s' % meta.get('param', ''), font=font(14), fill=(140, 144, 150))

    out = os.path.join(OUT, '7_成果汇总.png')
    img.save(out)
    print('已生成：%s   (%.0f KB, %dx%d)' % (out, os.path.getsize(out) / 1024, W, H))


if __name__ == '__main__':
    main()
