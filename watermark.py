# -*- coding: utf-8 -*-
"""
数字水印核心模块

实现了两种水印，用来对比"简单方案"和"鲁棒方案"的差别：

  1. LSB（最低有效位）
     把信息藏进每个像素值的最低位。改动只有 ±1，人眼完全看不出来，
     但 JPEG 压缩、加噪等操作会直接把它抹掉。

  2. DCT（离散余弦变换）
     把图像切成 8x8 小块，转到频率域，在中频系数上做手脚。
     配合"重复编码 + 打散 + 多数表决"，抗攻击能力大幅提升。
     这是工业界数字水印的常用思路。

术语：
  delta      -- 嵌入强度。改得越多越抗攻击，但越容易被看出来，要权衡。
  重复编码   -- 每个比特藏多份，提取时投票。用冗余换鲁棒性。
  打散       -- 把同一比特的多份副本散布到整张图，避免"一裁全没"。
  容量       -- 能藏多少信息，受图片大小限制。

用法见 README.md
"""
import struct

import cv2
import numpy as np

BLOCK = 8                 # DCT 分块大小（和 JPEG 一致）
P1, P2 = (3, 2), (2, 3)   # 用来做"配对比较"的两个中频系数位置
SEED = 20250928           # 打散用的固定随机种子（两端必须一致）
MIN_REPEAT = 20           # 每个比特至少重复这么多份，投票才有足够冗余
FLAT_STD = 0.5            # 块内标准差低于此值 = 死块（被裁剪填充等破坏），不参与投票
                          # 阈值不能太高：纯色区域（如校徽的白底）嵌入水印后
                          # 块内标准差只有 1.2 左右，阈值定 1.0 会在压缩后误杀它们。
                          # 而被灰色填充的真死块标准差精确为 0，用 0.5 足够区分。


# ============================================================
#  通用工具：文本 <-> 比特流
# ============================================================

def bytes_to_bits(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def bits_to_bytes(bits) -> bytes:
    return np.packbits(np.asarray(bits, dtype=np.uint8)).tobytes()


def make_payload(message: str) -> np.ndarray:
    """
    消息 -> 比特流。
    开头 32 位是"消息有多少字节"，这样提取时才知道要读多少。
    """
    data = message.encode('utf-8')
    return bytes_to_bits(struct.pack('>I', len(data)) + data)


def read_payload(bits) -> str:
    """比特流 -> 消息。读不出来（被破坏）返回 None"""
    bits = np.asarray(bits, dtype=np.uint8)
    if bits.size < 32:
        return None
    n = struct.unpack('>I', bits_to_bytes(bits[:32]))[0]
    if n <= 0 or 32 + n * 8 > bits.size:
        return None
    try:
        return bits_to_bytes(bits[32:32 + n * 8]).decode('utf-8')
    except UnicodeDecodeError:
        return None


def psnr(a, b) -> float:
    """
    峰值信噪比（dB），衡量"改图改了多少"。
    越高说明改动越不可见：
      > 45 dB  完全看不出
      40-45    几乎看不出（水印的常见目标）
      35-40    仔细看可能察觉
      < 35     开始能看出瑕疵
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    mse = np.mean((a - b) ** 2)
    return float('inf') if mse == 0 else 10.0 * np.log10(255.0 ** 2 / mse)


# ============================================================
#  方案一：LSB（最低有效位）
# ============================================================

def lsb_capacity(img) -> int:
    """能藏多少比特：每个通道 1 位"""
    return img.size


def embed_lsb(img, message: str):
    bits = make_payload(message)
    flat = img.reshape(-1).astype(np.uint8).copy()
    if bits.size > flat.size:
        raise ValueError('图片太小：需要 %d 位，只有 %d 位' % (bits.size, flat.size))
    # 把最低位清零，再写入我们的比特
    flat[:bits.size] = (flat[:bits.size] & 0xFE) | bits.astype(np.uint8)
    return flat.reshape(img.shape)


def extract_lsb(img):
    flat = img.reshape(-1)
    if flat.size < 32:
        return None
    length = struct.unpack('>I', bits_to_bytes(flat[:32] & 1))[0]
    total = 32 + length * 8
    if length <= 0 or total > flat.size:
        return None
    return read_payload(flat[:total] & 1)


# ============================================================
#  方案二：DCT（离散余弦变换）
# ============================================================

def _blocks(img):
    """裁成 8 的整数倍，返回 (裁剪后图像, 块数)"""
    h, w = img.shape[:2]
    small = img[:h - h % BLOCK, :w - w % BLOCK]
    nb_h, nb_w = small.shape[0] // BLOCK, small.shape[1] // BLOCK
    return small, nb_h * nb_w


def _layout(nblocks):
    """
    算出这一段"载荷"有多长、重复多少遍。

    为什么要固定载荷长度？
      载荷长度 L = 32(长度头) + 消息字节数*8。
      如果把消息直接拼上去，L 会随消息长短变化，
      提取端在还不知道消息多长的情况下就没法确定 L —— 鸡生蛋问题。
      所以约定：按图片容量取一个固定的最大长度，短消息用 0 补齐。
      这样两端算出的 L 一定一致。

    为什么至少要重复若干遍？
      只有一份副本的话，投不了票，一处损坏就全错。
      但图片很小时不能死守高重复次数，否则容量会小到没法用，
      所以让重复次数随图片大小自适应（下限 6 遍）。
    """
    min_rep = max(6, min(MIN_REPEAT, nblocks // 200))
    nmax = max(2, (nblocks // min_rep - 32) // 8)      # 最多能放多少字节
    L = 32 + nmax * 8                                  # 载荷总比特数
    repeat = nblocks // L                              # 能重复多少遍
    return nmax, L, repeat


def _scatter(nblocks, count):
    """
    打散：决定"第 k 个待嵌入的比特，放到第几个块里"。

    这一步至关重要。如果按顺序平铺（seq[k] 放进第 k 块），
    那么承载同一个比特的块满足 块序号 ≡ 比特序号 (mod L)，
    由于 L 是 64 的倍数，这些块会全部落在**同一列**上。
    结果就是：裁剪掉左边几列，就有若干比特的所有副本同时被毁，投票也救不回来。

    用固定种子的随机置换把它们打散到整张图，损坏就会被摊薄到所有比特上。
    嵌入端和提取端用同一个种子，所以能算出一模一样的顺序。
    """
    rng = np.random.default_rng(SEED)
    return rng.permutation(nblocks)[:count]


def dct_capacity(img):
    """返回 (最大消息字节数, 总共能用多少块)"""
    _, nblocks = _blocks(img)
    nmax, L, repeat = _layout(nblocks)
    return nmax, nblocks


def embed_dct(img, message: str, delta: float = 25.0):
    """
    在 Y（亮度）通道的 8x8 块里嵌入水印。

    每一块做一次"配对比较"：
      要藏 1 -> 让 P1 处的系数比 P2 大 delta
      要藏 0 -> 让 P2 处的系数比 P1 大 delta
    提取时只要比较这两个系数谁大谁小即可。

    选 Y 通道，是因为 JPEG 对色度的压缩比亮度狠得多。
    选 P1/P2 这样偏中频的位置，是因为低频改动容易被看出来，
    高频又容易被 JPEG 直接量化掉。
    """
    small, nblocks = _blocks(img)
    nmax, L, repeat = _layout(nblocks)

    data = message.encode('utf-8')
    if len(data) > nmax:
        raise ValueError('消息太长：最多 %d 字节，当前 %d 字节' % (nmax, len(data)))
    if repeat < 1:
        raise ValueError('图片太小，装不下')

    # 载荷 = 长度头(4字节) + 消息 + 补零到 nmax 字节
    padded = struct.pack('>I', len(data)) + data + b'\x00' * (nmax - len(data))
    payload = bytes_to_bits(padded)
    assert payload.size == L

    seq = np.tile(payload, repeat)              # 重复 repeat 遍
    order = _scatter(nblocks, seq.size)         # 打散：第 k 个比特 -> 第 order[k] 块

    ycc = cv2.cvtColor(small, cv2.COLOR_BGR2YCrCb)
    Y = ycc[:, :, 0].astype(np.float32)

    for k, blk_idx in enumerate(order):
        by, bx = divmod(int(blk_idx), small.shape[1] // BLOCK)
        y0, x0 = by * BLOCK, bx * BLOCK
        d = cv2.dct(Y[y0:y0 + BLOCK, x0:x0 + BLOCK])

        avg = (d[P1] + d[P2]) / 2.0
        if seq[k] == 1:
            d[P1], d[P2] = avg + delta / 2.0, avg - delta / 2.0
        else:
            d[P1], d[P2] = avg - delta / 2.0, avg + delta / 2.0

        Y[y0:y0 + BLOCK, x0:x0 + BLOCK] = cv2.idct(d)

    ycc[:, :, 0] = np.clip(Y, 0, 255)
    out = img.copy()
    out[:small.shape[0], :small.shape[1]] = cv2.cvtColor(ycc, cv2.COLOR_YCrCb2BGR)
    return out, repeat, seq.size


def extract_dct(img):
    """
    提取水印。流程：
      1. 每个块读出 1 比特（比较 P1、P2 谁大）
      2. 按打散顺序还原比特序列
      3. 按重复次数分组投票
      4. 从开头 32 位解出消息长度，取出消息
    """
    small, nblocks = _blocks(img)
    nmax, L, repeat = _layout(nblocks)
    if repeat < 1:
        return None, 0.0, 0

    ycc = cv2.cvtColor(small, cv2.COLOR_BGR2YCrCb)
    Y = ycc[:, :, 0].astype(np.float32)
    nb_w = small.shape[1] // BLOCK

    raw = np.zeros(nblocks, dtype=np.uint8)       # 每个块读出的原始比特
    valid = np.zeros(nblocks, dtype=bool)         # 该块是否可用

    for i in range(nblocks):
        by, bx = divmod(i, nb_w)
        y0, x0 = by * BLOCK, bx * BLOCK
        blk = Y[y0:y0 + BLOCK, x0:x0 + BLOCK]

        # 死块检测：被灰色填充（裁剪攻击留下）的块是平坦的，DCT 系数全为 0，
        # 于是 d[P1] > d[P2] 恒为假，它会**永远投 0 票**。
        # 这不是随机噪声而是系统性偏差 —— 重复多少次都压不住。
        # 所以直接把这类块标记为无效，不让它参与投票。
        if float(blk.std()) < FLAT_STD:
            continue

        d = cv2.dct(blk)
        raw[i] = 1 if d[P1] > d[P2] else 0
        valid[i] = True

    order = _scatter(nblocks, L * repeat)
    votes = raw[order].reshape(repeat, L)         # 每个比特的各份副本
    vmask = valid[order].reshape(repeat, L)       # 对应副本是否有效

    n_valid = vmask.sum(axis=0)                   # 每个比特有多少有效票
    ones = (votes & vmask).sum(axis=0)
    bits = np.where(n_valid > 0, ones * 2 > n_valid, False).astype(np.uint8)

    total_valid = int(n_valid.sum())
    acc = float(((votes == bits[None, :]) & vmask).sum() / total_valid) if total_valid else 0.0

    return read_payload(bits), acc, repeat


# ============================================================
#  命令行入口
# ============================================================

def _main():
    import argparse

    import imgio

    ap = argparse.ArgumentParser(description='数字水印：嵌入 / 提取')
    ap.add_argument('action', choices=['embed', 'extract'])
    ap.add_argument('--method', choices=['lsb', 'dct'], required=True)
    ap.add_argument('--image', required=True)
    ap.add_argument('--out', default=None, help='embed 时的输出路径')
    ap.add_argument('--message', default='hfut-se-2025')
    ap.add_argument('--delta', type=float, default=25.0)
    args = ap.parse_args()

    img = imgio.imread(args.image)
    if img is None:
        print('读不到图片：%s' % args.image)
        return

    if args.action == 'embed':
        if args.method == 'lsb':
            out = embed_lsb(img, args.message)
            print('LSB 嵌入完成  PSNR = %.2f dB' % psnr(img, out))
        else:
            out, rep, used = embed_dct(img, args.message, args.delta)
            print('DCT 嵌入完成  重复=%d  用了 %d 块  PSNR = %.2f dB'
                  % (rep, used, psnr(img, out)))
        path = args.out or ('output/%s_%s' % (args.method, 'wm.png'))
        imgio.imwrite(path, out)
        print('已保存：%s' % path)
    else:
        if args.method == 'lsb':
            msg = extract_lsb(img)
            print('LSB 提取结果：%s' % (msg if msg is not None else '【提取失败】'))
        else:
            msg, acc, rep = extract_dct(img)
            print('DCT 提取结果：%s   (投票一致率 %.1f%%)'
                  % (msg if msg is not None else '【提取失败】', acc * 100))


if __name__ == '__main__':
    _main()
