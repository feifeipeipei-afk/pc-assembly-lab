# -*- coding: utf-8 -*-
"""
战斗角色切图骨骼 · 资产评估与图集构建
================================================================

用途
----
把 `static/battle/{hero,boss,dummy}.png` 这三张**单姿势整图**，
切成可用于骨骼动画的**分层部件**，打包成一张图集 + 一份元数据 JSON。

为什么需要"分层"
----------------
旧实现里角色是一张静态 PNG，攻击只是整张图 `translateX(±44px)` ——
没有挥砍、没有抬臂、没有压扁拉伸。要做真正的骨骼动画，必须先把角色
拆成「头 / 躯干 / 手臂 / 武器 / 腿」这些可独立旋转的部件。

为什么不手标矩形框
------------------
三张图里角色都是斜向持械（勇者的剑横伸向左侧、魔王的火焰剑斜向右下），
用矩形框切必然把剑和躯干混在一起。这里改用**测地 Voronoi 分水岭**：

  1. 每张图取 alpha>alphaSeed 的最大连通域 = 角色实体（hard 掩膜）；
  2. 以 hard 为种子、alpha>alphaFloor 做洪泛，把角色的柔边与光晕一起纳入。
     >> 关键：这三张图带一层铺满整张画布的柔光（alpha 16~64 之间有 3 万像素），
        若直接按阈值切分，每个部件都会分到一大片雾状晕影。实测背景晕影与
        角色**不连通**，所以洪泛能干净地把晕影丢掉、把角色柔边留下。
  3. 每个部件给定一个「种子点」，在掩膜内部做**测地距离**（沿角色轮廓走，
     不是直线距离）多源扩散，像素归属于测地距离最近的种子点。
     >> 用测地而非欧氏：勇者的持剑手到躯干中心的直线距离很近，但沿轮廓
        要走完整条手臂，因此手会被正确判给手臂而非躯干。
  4. 每个部件掩膜向外**膨胀 bleed 像素**（侵入邻域），减少关节转动时的缝隙；
     每部件是独立的 RGBA 图，互相重叠无害。
  5. 逐部件裁紧（四周再加 PAD 透明边距）→ 铺进图集。

另外为每个角色额外出一个 `__base` 部件（整只角色的完整贴图，z 最低）。
它的作用：任何部件转动后让开的像素位置，都还能看到 base 的同色像素，
**把关节缝隙视觉上填掉**。代价是每个角色多一张整图，可以接受。

运行
----
    py tools/build_battle_assets.py

依赖 Pillow（已在 requirements.txt 声明）。部件定义见 tools/battle_rig/*.rig.json。

产物
----
    static/battle/atlas/battle_atlas.png      图集
    static/battle/atlas/battle_atlas.json     元数据（部件矩形 / 关节 pivot / 层级）
    static/battle/atlas/preview_<unit>.png    校验图：色块分区 + 逐部件隔离 + 关节标记
"""

import json
import os
import sys
import heapq
from collections import deque
from datetime import datetime

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as _err:
    sys.stderr.write('缺少 Pillow（%s）。请先安装：py -m pip install pillow\n' % _err)
    raise SystemExit(1)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG_DIR = os.path.join(ROOT, 'tools', 'battle_rig')
OUT_DIR = os.path.join(ROOT, 'static', 'battle', 'atlas')

# 图集内每个部件四周留出的透明边距：
# mipmap 降采样与线性过滤时不会把邻居区域的像素吸进来形成亮边。
PAD = 4

# 图集目标宽度（最终宽高会向上取整到 2 的幂）
ATLAS_MAX_W = 1024

# 预览图中各部件分区的配色
PREVIEW_HUES = [
    (232, 84, 84), (232, 150, 60), (222, 206, 60), (110, 200, 84),
    (72, 190, 190), (86, 140, 230), (170, 106, 220), (226, 100, 176),
]

NB8 = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
       (1, 1, 1.41421356), (1, -1, 1.41421356), (-1, 1, 1.41421356), (-1, -1, 1.41421356))
NB4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


# ============================================================
# 一、掩膜：剔除背景晕影，只留角色
# ============================================================

def build_keep_mask(alpha, seed_thr, floor_thr):
    """
    返回 (keep, box)
      keep : bytearray，1 表示该像素属于角色（含柔边）
      box  : keep 的紧密包围盒 (x0, y0, x1, y1)，后两值为开区间
    """
    w, h = alpha.size
    px = alpha.load()

    # ---- 1. 取 alpha>seed_thr 的最大连通域 ----
    seen = bytearray(w * h)
    best = None
    for sy in range(h):
        for sx in range(w):
            if seen[sy * w + sx] or px[sx, sy] <= seed_thr:
                continue
            q = deque([(sx, sy)])
            seen[sy * w + sx] = 1
            cells = []
            while q:
                x, y = q.popleft()
                cells.append((x, y))
                for dx, dy in NB4:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx] \
                            and px[nx, ny] > seed_thr:
                        seen[ny * w + nx] = 1
                        q.append((nx, ny))
            if best is None or len(cells) > len(best):
                best = cells

    if not best:
        raise RuntimeError('未找到任何 alpha>%d 的连通域，源图可能全透明' % seed_thr)

    # ---- 2. 从实体向柔边洪泛（4 邻域，alpha>floor_thr） ----
    keep = bytearray(w * h)
    q = deque()
    for x, y in best:
        keep[y * w + x] = 1
        q.append((x, y))
    while q:
        x, y = q.popleft()
        for dx, dy in NB4:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not keep[ny * w + nx] \
                    and px[nx, ny] > floor_thr:
                keep[ny * w + nx] = 1
                q.append((nx, ny))

    return keep, bbox_of(keep, w, h)


def bbox_of(mask, w, h):
    """掩膜的紧密包围盒 (x0,y0,x1,y1)"""
    xs = []
    ys = []
    for i, v in enumerate(mask):
        if v:
            xs.append(i % w)
            ys.append(i // w)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


# ============================================================
# 二、测地 Voronoi 分水岭
# ============================================================

def geodetic_partition(keep, w, h, parts):
    """
    在 keep 掩膜内做多源测地 Dijkstra，每个像素判给测地最近的种子点。
    parts 中每项需有 name / seed / 可选 bias（正数=该部件退让）。

    返回 {name: bytearray}
    """
    INF = float('inf')
    dist = [INF] * (w * h)
    owner = [-1] * (w * h)
    heap = []

    def snap(sx, sy, max_r=48):
        """种子点可能落在透明处，向外找最近的 keep 像素"""
        if 0 <= sx < w and 0 <= sy < h and keep[sy * w + sx]:
            return sx, sy
        for r in range(1, max_r):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) != r:
                        continue
                    nx, ny = sx + dx, sy + dy
                    if 0 <= nx < w and 0 <= ny < h and keep[ny * w + nx]:
                        return nx, ny
        return None

    for idx, p in enumerate(parts):
        snapped = snap(int(p['seed'][0]), int(p['seed'][1]))
        if snapped is None:
            raise RuntimeError('部件 %s 的种子点 %s 附近没有角色像素'
                               % (p['name'], p['seed']))
        nx, ny = snapped
        k = ny * w + nx
        bias = float(p.get('bias', 0.0))
        if bias < dist[k]:
            dist[k] = bias
            owner[k] = idx
            heapq.heappush(heap, (bias, k))

    while heap:
        d, k = heapq.heappop(heap)
        if d > dist[k]:
            continue
        x, y = k % w, k // w
        own = owner[k]
        for dx, dy, cost in NB8:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            nk = ny * w + nx
            if not keep[nk]:
                continue
            nd = d + cost
            if nd < dist[nk] - 1e-9:
                dist[nk] = nd
                owner[nk] = own
                heapq.heappush(heap, (nd, nk))

    names = [p['name'] for p in parts]
    out = {n: bytearray(w * h) for n in names}
    for k in range(w * h):
        if keep[k] and owner[k] >= 0:
            out[names[owner[k]]][k] = 1
    return out


def dilate_within(mask, keep, w, h, r):
    """掩膜向外膨胀 r 像素（4 邻域 BFS），限制在 keep 内。让关节处轻微侵入邻域。"""
    if r <= 0:
        return mask
    cur = bytearray(mask)
    frontier = [i for i, v in enumerate(cur) if v]
    for _ in range(r):
        nxt = []
        for k in frontier:
            x, y = k % w, k // w
            for dx, dy in NB4:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    nk = ny * w + nx
                    if keep[nk] and not cur[nk]:
                        cur[nk] = 1
                        nxt.append(nk)
        frontier = nxt
        if not frontier:
            break
    return cur


# ============================================================
# 三、图集打包（shelf / 高度递减）
# ============================================================

def pow2(v):
    p = 1
    while p < v:
        p *= 2
    return p


def pack_regions(items):
    """
    items : [(key, w, h)]，顺序无关。
    返回 {key: (x, y, w, h)}, atlas_w, atlas_h
    """
    order = sorted(items, key=lambda it: (-it[2], -it[1]))
    placed = {}
    x = y = shelf_h = 0
    for key, w, h in order:
        if x + w > ATLAS_MAX_W and x > 0:
            y += shelf_h
            x = 0
            shelf_h = 0
        placed[key] = (x, y, w, h)
        x += w
        shelf_h = max(shelf_h, h)
    used_w = max((v[0] + v[2] for v in placed.values()), default=1)
    return placed, used_w, y + shelf_h


# ============================================================
# 四、校验预览图
# ============================================================

def checkerboard(w, h, size=8):
    img = Image.new('RGBA', (w, h), (58, 58, 62, 255))
    d = ImageDraw.Draw(img)
    for yy in range(0, h, size):
        for xx in range(0, w, size):
            if ((xx // size) + (yy // size)) % 2 == 0:
                d.rectangle([xx, yy, xx + size - 1, yy + size - 1], fill=(84, 84, 90, 255))
    return img


def make_preview(meta, part_full, masks, keep, src_size, out_path, scale=1.5):
    """
    校验图：第 1 格「色块分区」（SEG），其余格逐一隔离展示每个部件，
    标出种子点（黄圈）与关节 pivot（青十字）。肉眼即可判断切分与关节对不对。

    part_full : {name: 与源图同尺寸的 RGBA 画布}，部件已贴回其在源图中的位置
    masks     : {name: bytearray}，源图坐标系下的部件掩膜
    """
    tx0, ty0, tx1, ty1 = meta['trim']
    cw, ch = tx1 - tx0, ty1 - ty0
    sw, sh = int(cw * scale), int(ch * scale)
    m, cap = 10, 18

    parts = [p for p in meta['parts']]        # 含 __base
    cells = 1 + len(parts)
    cols = min(4, cells)
    rows = (cells + cols - 1) // cols
    cell_w, cell_h = sw + m * 2, sh + m * 2 + cap

    canvas = Image.new('RGBA', (cell_w * cols, cell_h * rows), (24, 26, 30, 255))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.load_default(size=13)
    except TypeError:                                  # 老 Pillow 无 size 参数
        font = ImageFont.load_default()

    def put(idx, tile_img, caption, marks):
        cx, cy = (idx % cols) * cell_w, (idx // cols) * cell_h
        draw.rectangle([cx, cy, cx + cell_w - 1, cy + cell_h - 1],
                       outline=(140, 142, 152, 255), width=1)
        canvas.paste(tile_img, (cx + m, cy + m), tile_img)
        for kind, mx, my in marks:
            px_, py_ = cx + m + (mx - tx0) * scale, cy + m + (my - ty0) * scale
            if kind == 'seed':
                draw.ellipse([px_ - 4, py_ - 4, px_ + 4, py_ + 4],
                             outline=(255, 216, 60, 255), width=2)
            else:
                draw.line([px_ - 7, py_, px_ + 7, py_], fill=(56, 236, 255, 255), width=2)
                draw.line([px_, py_ - 7, px_, py_ + 7], fill=(56, 236, 255, 255), width=2)
        draw.text((cx + m, cy + cell_h - 15), caption, fill=(226, 230, 238, 255), font=font)

    # ---- 格 0：色块分区 ----
    seg = checkerboard(sw, sh, int(8 * scale))
    sp = seg.load()
    for i, p in enumerate([q for q in parts if not q.get('isBase')]):
        mk = masks.get(p['name'])
        if mk is None:
            continue
        col = PREVIEW_HUES[i % len(PREVIEW_HUES)]
        # 直接按缩放后的格子扫描，保证与贴图逐像素对齐
        for py in range(sh):
            sy = ty0 + int(py / scale)
            for px in range(sw):
                sx = tx0 + int(px / scale)
                if 0 <= sy < src_size[1] and 0 <= sx < src_size[0] \
                        and mk[sy * src_size[0] + sx]:
                    r, g, b, a = sp[px, py]
                    sp[px, py] = ((r + col[0] * 3) // 4, (g + col[1] * 3) // 4,
                                  (b + col[2] * 3) // 4, 255)
    # 角色轮廓描一层白，便于看边界
    for py in range(sh):
        sy = ty0 + int(py / scale)
        for px in range(sw):
            sx = tx0 + int(px / scale)
            if 0 <= sy < src_size[1] and 0 <= sx < src_size[0] \
                    and keep[sy * src_size[0] + sx]:
                r, g, b, a = sp[px, py]
                sp[px, py] = (min(255, r + 34), min(255, g + 34), min(255, b + 34), 255)
    put(0, seg, '0 SEG 色块分区',
        [('seed', p['seed'][0], p['seed'][1]) for p in parts if p.get('seed')]
        + [('pivot', p['pivot'][0], p['pivot'][1]) for p in parts if not p.get('isBase')])

    # ---- 其余格：逐部件隔离 ----
    for i, p in enumerate(parts):
        full = part_full[p['name']]
        tile = checkerboard(sw, sh, int(8 * scale))
        piece = full.crop(meta['trim']).resize((sw, sh), Image.LANCZOS)
        tile.paste(piece, (0, 0), piece)
        name = p['name']
        cap = ('%d %s  z=%d pivot=(%d,%d)' % (i + 1, name, p['z'],
                                              p['pivot'][0], p['pivot'][1]))
        marks = [] if p.get('isBase') else [('pivot', p['pivot'][0], p['pivot'][1])]
        put(i + 1, tile, cap, marks)

    canvas.save(out_path)
    return out_path


# ============================================================
# 五、单个角色的切分
# ============================================================

def build_unit(rig):
    """返回 (meta, part_full, masks, keep, img)"""
    src_path = os.path.join(ROOT, rig['source'].replace('/', os.sep))
    img = Image.open(src_path).convert('RGBA')
    w, h = img.size
    alpha = img.getchannel('A')

    keep, trim_box = build_keep_mask(alpha, rig['alphaSeed'], rig['alphaFloor'])
    parts = rig['parts']
    raw = geodetic_partition(keep, w, h, parts)

    bleed = int(rig.get('bleed', 3))
    masks = {}
    for p in parts:
        masks[p['name']] = dilate_within(raw[p['name']], keep, w, h, bleed)

    src_px = img.load()
    part_full = {}
    entries = []

    def make_part(name, mask, z, parent, pivot, extra=None):
        bb = bbox_of(mask, w, h)
        if bb is None:
            raise RuntimeError('部件 %s 切出来是空的，请检查种子点' % name)
        rx0, ry0, rx1, ry1 = bb
        px0, py0, px1, py1 = rx0 - PAD, ry0 - PAD, rx1 + PAD, ry1 + PAD
        out = Image.new('RGBA', (px1 - px0, py1 - py0), (0, 0, 0, 0))
        op = out.load()
        full = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        fp = full.load()
        for yy in range(ry0, ry1):
            for xx in range(rx0, rx1):
                if mask[yy * w + xx]:
                    c = src_px[xx, yy]
                    op[xx - px0, yy - py0] = c
                    fp[xx, yy] = c
        part_full[name] = full
        e = {
            'name': name,
            'parent': parent,
            'pivot': [int(pivot[0]), int(pivot[1])],
            'rect': [px0, py0, px1 - px0, py1 - py0],
            'z': int(z),
        }
        if extra:
            e.update(extra)
        entries.append(e)

    # base 兜底层：整只角色的完整贴图，z 最低
    if rig.get('useBase', True):
        make_part('__base', keep, -1, None, [0, 0], extra={'isBase': True})

    for p in parts:
        make_part(p['name'], masks[p['name']], p['z'], p.get('parent'), p['pivot'],
                  extra={'seed': [int(p['seed'][0]), int(p['seed'][1])]})

    # 锚点：x 取源图水平中心（与旧 CSS object-position:center bottom 一致），
    #       y 取脚底，使角色正好站在世界地面线 y=0 上。
    anchor = rig.get('anchor') or [w / 2.0, trim_box[3]]

    meta = {
        'label': rig.get('label', rig['unit']),
        'source': rig['source'],
        'sourceSize': [w, h],
        'anchor': [float(anchor[0]), float(anchor[1])],
        'trim': list(trim_box),
        'bleed': bleed,
        'pad': PAD,
        # 以下三项供运行时摆姿势用：哪只手握武器、角色朝向、以及摆姿时
        # 躯干/持械臂应当往哪边转（两张源图朝向不同，符号无法统一推出）。
        'weaponArm': rig.get('weaponArm'),
        'facing': int(rig.get('facing', 1)),
        'leanSign': int(rig.get('leanSign', 1)),
        'armSign': int(rig.get('armSign', 1)),
        'parts': entries,
    }
    return meta, part_full, masks, keep, img


# ============================================================
# 六、主流程
# ============================================================

def main():
    rig_files = sorted(f for f in os.listdir(RIG_DIR) if f.endswith('.rig.json'))
    if not rig_files:
        sys.stderr.write('tools/battle_rig/ 下没有找到 *.rig.json\n')
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)

    prepared = []
    for rf in rig_files:
        with open(os.path.join(RIG_DIR, rf), 'r', encoding='utf-8') as fh:
            rig = json.load(fh)
        meta, part_full, masks, keep, img = build_unit(rig)
        prepared.append(dict(rig=rig, meta=meta, part_full=part_full,
                             masks=masks, keep=keep, img=img))

    # ---- 统一打包成一张图集 ----
    items = []
    for it in prepared:
        unit = it['rig']['unit']
        for e in it['meta']['parts']:
            items.append(('%s/%s' % (unit, e['name']), e['rect'][2], e['rect'][3]))

    placed, used_w, used_h = pack_regions(items)
    atlas_w, atlas_h = pow2(used_w), pow2(used_h)
    atlas = Image.new('RGBA', (atlas_w, atlas_h), (0, 0, 0, 0))

    for it in prepared:
        unit = it['rig']['unit']
        for e in it['meta']['parts']:
            ax, ay, pw, ph = placed['%s/%s' % (unit, e['name'])]
            atlas.paste(it['part_full'][e['name']].crop(
                (e['rect'][0], e['rect'][1],
                 e['rect'][0] + e['rect'][2], e['rect'][1] + e['rect'][3])), (ax, ay))
            e['region'] = [ax, ay, pw, ph]

    atlas_png = os.path.join(OUT_DIR, 'battle_atlas.png')
    atlas.save(atlas_png)

    # ---- 元数据 ----
    units = {it['rig']['unit']: it['meta'] for it in prepared}
    doc = {
        'version': 1,
        'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'generator': 'tools/build_battle_assets.py',
        'atlas': {
            'image': 'static/battle/atlas/battle_atlas.png',
            'url': '/static/battle/atlas/battle_atlas.png',
            'width': atlas_w,
            'height': atlas_h,
        },
        # 旧 CSS `.bt-sprite` 是 200x200 的框 + object-fit:contain，
        # 源图 372x372 因此等比缩放 —— 世界单位/源像素 = 200/372。
        'unitBox': 200,
        'units': units,
    }
    json_path = os.path.join(OUT_DIR, 'battle_atlas.json')
    with open(json_path, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)

    # ---- 校验预览图 ----
    previews = []
    for it in prepared:
        pv = os.path.join(OUT_DIR, 'preview_%s.png' % it['rig']['unit'])
        make_preview(it['meta'], it['part_full'], it['masks'], it['keep'],
                     tuple(it['meta']['sourceSize']), pv)
        previews.append(pv)

    # ---- 报告 ----
    print('=' * 74)
    print('图集 %s  %dx%d  (%.0f KB, 填充率 %.0f%%)' % (
        os.path.relpath(atlas_png, ROOT).replace('\\', '/'), atlas_w, atlas_h,
        os.path.getsize(atlas_png) / 1024,
        100.0 * used_w * used_h / (atlas_w * atlas_h)))
    print('元数据 %s' % os.path.relpath(json_path, ROOT).replace('\\', '/'))
    for it in prepared:
        meta = it['meta']
        print('-' * 74)
        print('%-6s %-6s 源=%s 裁剪盒=%s 锚点=(%.0f,%.0f)'
              % (it['rig']['unit'], meta['label'], meta['sourceSize'],
                 meta['trim'], meta['anchor'][0], meta['anchor'][1]))
        for p in meta['parts']:
            print('  z=%-2d %-8s parent=%-6s pivot=%-12s rect=%-20s region=%s%s' % (
                p['z'], p['name'], p['parent'] or '-', p['pivot'], p['rect'],
                p.get('region'), '  [base]' if p.get('isBase') else ''))
    print('-' * 74)
    for pv in previews:
        print('预览 %s' % os.path.relpath(pv, ROOT).replace('\\', '/'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
