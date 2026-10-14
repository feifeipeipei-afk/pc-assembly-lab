# -*- coding: utf-8 -*-
"""把生成的像素角色 JPG 抠成透明背景 PNG 并调整朝向。"""
from PIL import Image, ImageOps
import os

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'battle')


def white_to_alpha(img):
    """根据与纯白的接近程度生成 alpha，保留纯色像素与抗锯齿边缘。"""
    img = img.convert('RGBA')
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            mn = min(r, g, b)
            if mn >= 230:
                # 230..255 -> alpha 255..0 线性过渡，纯白全透明
                alpha = int((255 - mn) / (255 - 230) * 255)
            else:
                alpha = a
            px[x, y] = (r, g, b, alpha)
    return img


def trim(img):
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else img


def process(src, dst, flip=False, target_h=360):
    img = Image.open(src)
    img = white_to_alpha(img)
    if flip:
        img = ImageOps.mirror(img)
    # 缩到目标高度，像素风直接平滑缩放即可
    w, h = img.size
    ratio = target_h / h
    img = img.resize((max(1, round(w * ratio)), target_h), Image.Resampling.LANCZOS)
    img = trim(img)
    img = ImageOps.expand(img, border=6, fill=(0, 0, 0, 0))
    img.save(dst, 'PNG')
    print('OK', os.path.basename(dst), img.size)


process(os.path.join(BASE, 'hero.jpg'), os.path.join(BASE, 'hero.png'), flip=True)   # 站右侧，朝左
process(os.path.join(BASE, 'boss.jpg'), os.path.join(BASE, 'boss.png'), flip=True)    # 站左侧，朝右
process(os.path.join(BASE, 'dummy.jpg'), os.path.join(BASE, 'dummy.png'), flip=False) # 假人朝右