# -*- coding: utf-8 -*-
"""
把实验结果整理成一份精简的 Word 实验报告（.docx）。

以表格、配图和必要注释为主体，不做大段文字陈述。

用法：
    python experiment.py --image 校徽.png     # 先跑实验
    python compare_types.py                   # 生成图片类型对比材料（可选）
    python make_report.py                     # 生成 成果汇总.docx

依赖：python-docx   （pip install python-docx）
"""
import json
import os

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'output')
DST = os.path.join(HERE, '成果汇总.docx')

GREEN = RGBColor(0x1A, 0x7F, 0x42)
RED = RGBColor(0xC0, 0x39, 0x2B)
GRAY = RGBColor(0x77, 0x77, 0x77)


# ---------------------------------------------------------------- 排版工具

def set_font(run, ascii_font='Times New Roman', cn_font='宋体', size=None,
             bold=None, color=None):
    run.font.name = ascii_font
    run._element.rPr.rFonts.set(qn('w:eastAsia'), cn_font)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color


def para(doc, text='', size=10.5, bold=False, cn='宋体', align=None,
         color=None, space_after=4, space_before=0):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.line_spacing = 1.3
    if text:
        r = p.add_run(text)
        set_font(r, 'Times New Roman', cn, size, bold, color)
    return p


def heading(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(text)
    set_font(r, 'Times New Roman', '黑体', 12.5, True)
    return p


def caption(doc, text):
    """图注：居中、小一号、黑色 —— 与正文保持同一墨色，不用灰字"""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(10)
    r = p.add_run(text)
    set_font(r, 'Times New Roman', '宋体', 9.5, False)
    return p


def note(doc, text):
    """说明段落，按正文处理（原先用小号灰字，与正文割裂）"""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.35
    p.paragraph_format.first_line_indent = Pt(21)
    r = p.add_run(text)
    set_font(r, 'Times New Roman', '宋体', 10.5, False)
    return p


def image_row(doc, items, total_width=6.25, cap=None):
    items = [(f, c) for f, c in items if os.path.exists(os.path.join(OUT, f))]
    if not items:
        return
    t = doc.add_table(rows=1, cols=len(items))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    w = total_width / len(items) - 0.06
    for cell, (fn, c) in zip(t.rows[0].cells, items):
        cp = cell.paragraphs[0]
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cp.paragraph_format.space_after = Pt(1)
        cp.add_run().add_picture(os.path.join(OUT, fn), width=Inches(w))
    if cap:
        caption(doc, cap)


def no_split(table):
    """禁止表格行跨页断开，避免一行被切成两半"""
    for row in table.rows:
        trPr = row._tr.get_or_add_trPr()
        el = OxmlElement('w:cantSplit')
        trPr.append(el)


def make_table(doc, headers, rows, widths=None, color_cols=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = 'Table Grid'
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = ''
        c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        c.paragraphs[0].paragraph_format.space_after = Pt(1)
        set_font(c.paragraphs[0].add_run(h), 'Times New Roman', '黑体', 9, True)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ''
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(1)
            p.paragraph_format.line_spacing = 1.15
            col = (GREEN if v == '成功' else RED) if (color_cols and i in color_cols) else None
            set_font(p.add_run(str(v)), 'Times New Roman', '宋体', 9, bool(col), col)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Inches(w)
    no_split(t)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return t


# ---------------------------------------------------------------- 读数据

def read_results():
    meta, invis, rows = {}, [], []
    p = os.path.join(HERE, '实验结果.md')
    if not os.path.exists(p):
        return meta, invis, rows
    for ln in open(p, encoding='utf-8'):
        ln = ln.strip()
        for key, tag in (('msg', '- 嵌入信息'), ('image', '- 测试图片'),
                         ('param', '- DCT 参数'), ('tex', '- 低纹理块占比')):
            if ln.startswith(tag):
                meta[key] = ln.replace(tag + '：', '').strip().strip('`')
        if not ln.startswith('|') or '---' in ln:
            continue
        c = [x.strip() for x in ln.strip('|').split('|')]
        if len(c) == 3 and c[0] != '方案':
            invis.append(c)
        elif len(c) == 6 and c[0] != '攻击方式':
            rows.append(c)
    return meta, invis, rows


# ---------------------------------------------------------------- 主流程

def main():
    meta, invis, rows = read_results()
    if not rows:
        print('没找到 实验结果.md，请先运行 python experiment.py')
        return

    n_tot = len(rows)
    n_lsb = sum(1 for r in rows if r[2] == '成功')
    n_dct = sum(1 for r in rows if r[3] == '成功')
    dct_fail = [r[0] for r in rows if r[3] != '成功' and r[0] != '无攻击']
    image = meta.get('image', '').replace('自定义 ', '').strip()
    src = os.path.splitext(image)[0] or '测试图'
    tex = meta.get('tex', '—')

    cmpf = os.path.join(OUT, '图片类型对比.json')
    comp = None
    if os.path.exists(cmpf):
        try:
            comp = json.load(open(cmpf, encoding='utf-8'))
        except Exception:
            comp = None

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.27), Inches(11.69)
    sec.left_margin = sec.right_margin = Inches(1.0)
    sec.top_margin = sec.bottom_margin = Inches(0.8)
    base = doc.styles['Normal']
    base.font.name = 'Times New Roman'
    base.font.size = Pt(10.5)
    base.element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    try:
        tg = doc.styles['Table Grid']
        tg.font.name = 'Times New Roman'
        tg.font.size = Pt(9)
        tg.element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), '宋体')
    except Exception:
        pass

    # ---- 标题与元信息 ----
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(2)
    set_font(p.add_run('数字水印与鲁棒性评测'), 'Times New Roman', '黑体', 17, True)

    para(doc, '测试图片：%s　　嵌入信息：%s' % (image, meta.get('msg', '')),
         size=10, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=1)
    para(doc, '%s　　低纹理块占比：%s' % (meta.get('param', ''), tex),
         size=10, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=8)

    # ---- 一、方法 ----
    heading(doc, '一、方法')
    make_table(doc, ['环节', '内容'],
               [['流程', '原图 → 嵌入水印 → 施加攻击（10 种）→ 提取信息'],
                ['攻击', 'JPEG 压缩 q=90/70/50/30、缩放 50%、高斯噪声 σ=3/8、'
                         '裁剪边缘 64 px、亮度 +15'],
                ['LSB', '修改像素最低位。改动仅 ±1，不可见，但不具备抗重编码能力'],
                ['DCT', '8×8 分块变换至频率域，在中频系数上配对比较编码；'
                        '亮度通道承载（JPEG 对色度压缩更激进）；'
                        '配合重复编码、随机打散与多数投票']],
               widths=[0.75, 5.45])

    # ---- 二、嵌入效果 ----
    heading(doc, '二、嵌入效果')
    image_row(doc, [('0_原图.png', ''), ('1_LSB含水印.png', ''), ('2_DCT含水印.png', '')],
              cap='（a）原图　（b）LSB 含水印　（c）DCT 含水印')
    image_row(doc, [('3_LSB差异放大40倍.png', ''), ('4_DCT差异放大40倍.png', '')],
              cap='（d）LSB 改动　（e）DCT 改动　（二者均放大 40 倍）')
    note(doc, '三张图在视觉上没有差别。LSB 的改动极小，放大 40 倍后仍接近全黑；'
              'DCT 的改动则均匀铺满全图，说明信息已被分散到大量分块之中。')

    # ---- 三、不可见性 ----
    heading(doc, '三、不可见性')
    make_table(doc, ['方案', 'PSNR', '说明'], invis, widths=[0.9, 1.1, 4.25])
    note(doc, '一般认为 PSNR 达到 40 dB 以上时，人眼难以察觉图像被修改的痕迹。')

    # ---- 四、鲁棒性 ----
    heading(doc, '四、鲁棒性')
    make_table(doc, ['攻击方式', '说明', 'LSB', 'DCT', 'DCT 正确率', '攻击后 PSNR'],
               rows, widths=[1.0, 1.45, 0.7, 0.7, 1.0, 1.15],
               color_cols={2: 1, 3: 1})
    para(doc, '合计：LSB %d/%d，DCT %d/%d（DCT 失效：%s）'
         % (n_lsb, n_tot, n_dct, n_tot, '、'.join(dct_fail) if dct_fail else '无'),
         size=10, bold=True, space_after=8)
    image_row(doc, [('6_攻击后效果.png', '')], total_width=4.9,
              cap='（f）各攻击方式处理后的图片及提取结果（OK / FAIL）')

    # ---- 五、图片类型对比 ----
    heading(doc, '五、图片类型对比')
    if comp:
        a, b = comp['a'], comp['b']
        image_row(doc, [('对比_风景图.png', ''), ('对比_风景图_差异.png', ''),
                        ('对比_测试图.png', ''), ('对比_测试图_差异.png', '')],
                  cap='（g）合成风景图　（h）其 DCT 改动　|　'
                      '（i）%s　（j）其 DCT 改动' % src)
        make_table(doc, ['测试图片', '尺寸', '低纹理块占比', 'PSNR', 'DCT 通过', '失效的攻击'],
                   [['合成风景图（纹理丰富）', a['size'], '%.1f%%' % a['tex'],
                     '%.2f dB' % a['psnr'], '%d/%d' % (a['dct_ok'], a['total']),
                     '、'.join(a['fails']) or '—'],
                    ['%s（大面积纯色 + 细线条）' % src, b['size'], '%.1f%%' % b['tex'],
                     '%.2f dB' % b['psnr'], '%d/%d' % (b['dct_ok'], b['total']),
                     '、'.join(b['fails']) or '—']],
                   widths=[1.55, 0.65, 0.95, 0.8, 0.85, 1.4])
        note(doc, '两张图的 PSNR 接近，说明改动幅度相当；但低纹理块占比相差悬殊'
                  '（%.1f%% 对 %.1f%%），最终成绩相差一种攻击。'
                  '对照图（h）与（j）可以看到：风景图的改动细密均匀，'
                  '%s 的改动则在纯色区域成片集中。' % (a['tex'], b['tex'], src))
    else:
        note(doc, '本次仅测试 %s。运行 compare_types.py 可生成与其他图片类型的对照。'
             % src)

    # ---- 六、问题记录 ----
    heading(doc, '六、问题记录')
    make_table(doc, ['#', '现象', '原因', '修法'],
               [['1', '未受攻击即提取失败',
                 '嵌入用 9 次重复，提取按满块推算为 32 次，'
                 '未修改块参与投票并覆盖真实结果',
                 '两端改由图像尺寸自动推算重复次数'],
                ['2', '裁剪后完全无法提取',
                 '顺序平铺使同一比特的副本全部落在同一列'
                 '（载荷长度为 64 的倍数）',
                 '用固定种子随机置换打散至全图'],
                ['3', '打散后仍有误码',
                 '灰色填充块 DCT 系数全为 0，配对比较恒判为 0，系统性投 0 票',
                 '检测平坦块并排除其投票'],
                ['4', '更换图片后成绩下降',
                 '纯色块嵌入后方差约 1.16，原阈值 1.0 余量不足，'
                 '压缩后误判为死块',
                 '阈值下调至 0.5']],
               widths=[0.3, 1.25, 2.6, 2.05])
    note(doc, '其中问题 3 属于系统性偏差而非随机误差：冗余编码可以对抗随机误差，'
              '但无法对抗系统性偏差。')

    doc.save(DST)
    print('已生成：%s   (%.0f KB)' % (DST, os.path.getsize(DST) / 1024))


if __name__ == '__main__':
    main()
