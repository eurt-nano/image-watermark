# -*- coding: utf-8 -*-
"""
对比"不同图片类型"对水印难度的影响。

报告里有一条结论：纹理丰富的照片比大面积纯色的图标更容易做鲁棒水印。
这个脚本把这条结论的证据补齐 —— 用同一套代码分别跑合成风景图和实际测试图，
把两边原图、差异图和成绩都产出来，供报告引用。

产物：
    output/对比_风景图.png / 对比_风景图_差异.png
    output/对比_测试图.png / 对比_测试图_差异.png
    output/图片类型对比.json      （供 make_report.py 读取）

用法：
    python compare_types.py
"""
import json
import os

import cv2
import numpy as np

import attacks
import imgio
from experiment import amplify_diff, low_texture_ratio, make_test_image
from watermark import embed_dct, extract_dct, psnr

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'output')
MSG = 'hfut-se-2025'


def run(img, tag, msg=MSG):
    """对一张图跑完整流程，产出原图/差异图，并返回成绩"""
    wm, rep, used = embed_dct(img, msg)
    imgio.imwrite(os.path.join(OUT, '对比_%s.png' % tag), img)
    imgio.imwrite(os.path.join(OUT, '对比_%s_差异.png' % tag), amplify_diff(img, wm))

    ok, fails = 0, []
    for name, fn, _ in attacks.ATTACKS:
        got, acc, _ = extract_dct(fn(wm))
        if got == msg:
            ok += 1
        elif name != '无攻击':
            fails.append(name)

    return {
        'tag': tag,
        'size': '%d×%d' % (img.shape[1], img.shape[0]),
        'tex': round(low_texture_ratio(img) * 100, 1),
        'psnr': round(psnr(img, wm), 2),
        'dct_ok': ok,
        'total': len(attacks.ATTACKS),
        'fails': fails,
    }


def main():
    os.makedirs(OUT, exist_ok=True)

    print('跑「合成风景图」（纹理丰富）...')
    a = run(make_test_image(), '风景图')

    print('跑「%s」（大面积纯色）...' % '实际测试图')
    src = imgio.imread(os.path.join(OUT, '0_原图.png'))
    if src is None:
        print('没找到 output/0_原图.png，请先运行 python experiment.py')
        return
    b = run(src, '测试图')

    data = {'a': a, 'b': b}
    with open(os.path.join(OUT, '图片类型对比.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print()
    print('%-14s %-10s %-12s %-9s %s' % ('图片', '尺寸', '低纹理块占比', 'PSNR', 'DCT 抗住攻击'))
    print('-' * 68)
    for r in (a, b):
        print('%-14s %-10s %-12s %-9s %d/%d%s'
              % (r['tag'], r['size'], '%.1f%%' % r['tex'], '%.2f dB' % r['psnr'],
                 r['dct_ok'], r['total'],
                 ('   失败: ' + '、'.join(r['fails'])) if r['fails'] else ''))
    print()
    print('已产出 output/对比_*.png 与 output/图片类型对比.json')


if __name__ == '__main__':
    main()
