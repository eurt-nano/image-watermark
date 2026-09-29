# -*- coding: utf-8 -*-
"""
中文路径安全的图片读写

坑：OpenCV 的 cv2.imread / cv2.imwrite 在 Windows 上遇到
非 ASCII 路径（比如本项目的 "数字水印" 目录）会**静默失败**——
不报错，但读进来是 None、写出去没文件。

绕法：先用 numpy 把文件读成字节，再交给 cv2.imdecode；
写的时候先 cv2.imencode 成内存缓冲，再用 tofile 落盘。
"""
import os

import cv2
import numpy as np


def imread(path, flags=cv2.IMREAD_COLOR):
    if not os.path.exists(path):
        return None
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def imwrite(path, img) -> bool:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    ext = os.path.splitext(path)[1] or '.png'
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    buf.tofile(path)
    return True
