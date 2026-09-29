# -*- coding: utf-8 -*-
"""
对含水印图片的各种"攻击"

为什么要攻击自己的水印？
    水印的价值不在于"能藏进去"——那太容易了。
    真正的问题是：图片在网上传一圈，会被压缩、裁剪、转发、二次编辑，
    水印还在不在？

    所以做数字水印必须回答一个问题：**被攻击之后还能不能提取出来。**
    这叫"鲁棒性评估"，是水印研究里最核心的一环。

本模块实现 5 种常见攻击：
    jpeg      —— 最现实的一种（微信、微博、论坛都会压缩图片）
    resize    —— 缩放（先缩小再放大）
    noise     —— 加高斯噪声
    crop      —— 裁剪掉边缘
    brighten  —— 调整亮度
"""
import cv2
import numpy as np


def attack_jpeg(img, quality=70):
    """JPEG 有损压缩。quality 越低压得越狠，水印越容易丢"""
    ok, buf = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        return img.copy()
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def attack_resize(img, scale=0.5):
    """缩小再放大回原尺寸。像素被重采样，细微改动会被抹平"""
    h, w = img.shape[:2]
    small = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))),
                       interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def attack_noise(img, sigma=3.0, seed=0):
    """加高斯噪声，模拟拍照/传输过程中的干扰"""
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, sigma, img.shape)
    return np.clip(img.astype(np.float64) + noise, 0, 255).astype(np.uint8)


def attack_crop(img, border=64, fill=128):
    """
    裁剪掉四周 border 像素。

    注意实现方式：裁掉之后，把剩下的内容**贴回原来位置**，
    空出来的边填灰。这样做的原因是——
    DCT 水印是 8x8 分块嵌入的，如果把图片直接裁小，
    所有块都会错位，提取必然失败，测不出真实鲁棒性。

    贴回原位 + 补灰，模拟的是"图片边缘被裁掉了"，
    这样内部那些块仍然对齐、仍然能提取，
    才能真正看出"裁剪之后还剩多少水印信息"。
    """
    h, w = img.shape[:2]
    border = max(0, min(border, min(h, w) // 2 - 1))
    out = np.full_like(img, fill)
    if border > 0:
        inner = img[border:h - border, border:w - border]
        out[border:h - border, border:w - border] = inner
    return out


def attack_brighten(img, delta=15):
    """整体调亮/调暗，模拟二次编辑"""
    return np.clip(img.astype(np.int16) + delta, 0, 255).astype(np.uint8)


# 攻击清单：(名字, 函数, 说明)
ATTACKS = [
    ('无攻击',        lambda im: im.copy(),                  '原图，作为对照'),
    ('JPEG q=90',     lambda im: attack_jpeg(im, 90),        '轻微压缩'),
    ('JPEG q=70',     lambda im: attack_jpeg(im, 70),        '常见压缩强度'),
    ('JPEG q=50',     lambda im: attack_jpeg(im, 50),        '较狠的压缩'),
    ('JPEG q=30',     lambda im: attack_jpeg(im, 30),        '很狠的压缩'),
    ('缩放 50%',      lambda im: attack_resize(im, 0.5),     '缩小一半再放大'),
    ('高斯噪声 s=3',  lambda im: attack_noise(im, 3.0),      '轻微噪声'),
    ('高斯噪声 s=8',  lambda im: attack_noise(im, 8.0),      '较强噪声'),
    ('裁剪 64px',     lambda im: attack_crop(im, 64),        '裁掉四周 64 像素'),
    ('亮度 +15',      lambda im: attack_brighten(im, 15),    '整体调亮'),
]
