"""网格生成:STL 加载(numpy-stl,带缓存)与盒/圆柱/球基本体。

所有网格统一为 flat shading 格式:每个三角面 3 个独立顶点,
返回 (vertices Nx3, normals Nx3, colors Nx4, indices Mx1=arange)。
"""

import hashlib
import math
import os

import numpy as np

# 文件名 → (vertices, normals, indices) 缓存,避免同一 STL 反复读盘
_mesh_cache = {}

# 平滑法线的磁盘缓存目录(与 config.py 的 ~/.omni 保持一致)
_SMOOTH_CACHE_DIR = os.path.join(os.path.expanduser('~'), '.omni', 'mesh_cache')

# STL 中点细分次数:6 边圆柱 → 24 边(每代 ×4 面)。低边数圆柱的
# 轮廓多边形无法靠法线平滑修复,细分让轮廓与光影都接近圆;
# 中点细分不改变折线角度,90° 硬边天然保持锐利。
SUBDIV_ITERS = 2


def smooth_normals(verts, norms, angle_deg=40.0, eps=1e-6):
    """按角度阈值平滑面法线,算法对齐 ReachControl 的
    stlloader.generate_normals(threshold_angle=20):

    - STL 面法线字段不是单位向量(长度=2×三角形面积),方向才是
      有效信息,角度判定前先单位化
    - 夹角取锐角(>90° 折叠到补角,同 RC 的 π-angle)
    - 位置相同(1e-6 精度内)的顶点归为一组,组内贪心聚类:
      法线夹角 ≤ angle_deg 的面取平均(曲面平滑圆润);
      夹角大(硬边/直角)的面各自保持面法线,棱角锐利
    - 子组平均用原始法线求和再单位化(面积加权,大面权重大,
      同 RC 的 normalize_v4)

    阈值取 40°(RC 为 20°):s7 等模型的圆柱只有 12 边,相邻侧面
    夹角 30° > 20° 不被平滑,圆截面显示成棱柱;40° 能平滑这类
    低边数圆柱,而 90° 的硬边(直角、端盖交界)仍保持锐利。
    """
    cos_thr = math.cos(math.radians(angle_deg))

    # 单位化面法线(仅用于角度判定;加权平均仍用原始法线)
    fn = norms.astype(np.float64)
    fn_lens = np.linalg.norm(fn, axis=1)
    fn = np.divide(fn, fn_lens[:, None], out=np.zeros_like(fn),
                   where=fn_lens[:, None] > 1e-12)
    raw = norms.astype(np.float64)

    key = np.round(verts / eps).astype(np.int64)
    _, idx, inv = np.unique(key, axis=0,
                            return_index=True, return_inverse=True)
    n_groups = len(idx)

    # 组平均法线(面积加权),用于区分纯平滑组与混合组
    acc = np.zeros((n_groups, 3), dtype=np.float64)
    np.add.at(acc, inv, raw)
    lens = np.linalg.norm(acc, axis=1)
    avg = np.zeros_like(acc)
    ok = lens > 1e-12
    avg[ok] = acc[ok] / lens[ok, None]
    avg[~ok] = fn[idx[~ok]]

    # 顶点按组排序,同组连续;starts 为各组起始偏移(reduceat 用),
    # starts_full 多一个尾部终点(切片用)
    order = np.argsort(inv, kind='stable')
    inv_sorted = inv[order]
    starts = np.r_[0, np.searchsorted(inv_sorted,
                                      np.arange(1, n_groups), 'left')]
    starts_full = np.r_[starts, len(inv)]

    # 夹角取锐角(折叠 >90°),同 RC 的 vector_angle
    cos_v = np.abs((fn * avg[inv]).sum(axis=1))
    min_cos = np.minimum.reduceat(cos_v[order], starts)
    smooth_group = min_cos >= cos_thr

    out = np.empty_like(norms, dtype=np.float64)
    out[:] = avg[inv]                       # 默认:组平均(纯平滑组)

    # 混合组(含硬边):组内按面法线贪心聚类,子组分别平均
    for gi in np.where(~smooth_group)[0]:
        lo, hi = starts_full[gi], starts_full[gi + 1]
        members = order[lo:hi]
        n = hi - lo
        labels = np.full(n, -1)
        nlab = 0
        for i in range(n):
            if labels[i] >= 0:
                continue
            labels[i] = nlab
            nlab += 1
            for j in range(i + 1, n):
                if labels[j] < 0 and abs(np.dot(fn[members[i]], fn[members[j]])) >= cos_thr:
                    labels[j] = labels[i]
        for lab in range(nlab):
            m = labels == lab
            if m.sum() == 1:
                out[members[m]] = fn[members[m]]
            else:
                a = raw[members[m]].sum(axis=0)   # 面积加权(同 RC)
                la = np.linalg.norm(a)
                out[members[m]] = (a / la) if la > 1e-12 else fn[members[m]]
    return out.astype(np.float32)


def _weld_verts(verts, indices, eps=1e-6):
    """焊接重复顶点(STL 每面独立存 3 顶点),返回唯一顶点与索引。

    位置相同(eps 内)的顶点合并,取首见位置;三角形索引重映射。
    """
    key = np.round(verts / eps).astype(np.int64)
    _, idx, inv = np.unique(key, axis=0,
                            return_index=True, return_inverse=True)
    uniq_verts = verts[idx]
    uniq_tris = inv[np.asarray(indices, dtype=np.int64)].reshape(-1, 3)
    return uniq_verts, uniq_tris


def _face_normals_from_tris(verts, tris):
    """按三角形绕序叉积算面法线(长度=2×面积,同 numpy-stl)。"""
    a = verts[tris[:, 0]]
    b = verts[tris[:, 1]]
    c = verts[tris[:, 2]]
    return np.cross(b - a, c - a).astype(np.float32)


def _subdivide_once(verts, tris):
    """中点细分一代:每个三角形拆成 4 个,新顶点为边中点(全 numpy)。"""
    v_count = len(verts)
    # 所有有向边 (i,j),(j,k),(k,i) 归一化为 (min,max) 后去重
    edges = np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    uniq_edges, edge_inv = np.unique(
        np.column_stack([edges.min(axis=1), edges.max(axis=1)]),
        axis=0, return_inverse=True)
    mid = (verts[uniq_edges[:, 0]] + verts[uniq_edges[:, 1]]) * 0.5
    verts = np.vstack([verts, mid])
    m = edge_inv.reshape(3, -1).T + v_count    # M×3:每条三角的边中点索引
    m0, m1, m2 = m[:, 0], m[:, 1], m[:, 2]
    i, j, k = tris[:, 0], tris[:, 1], tris[:, 2]
    tris = np.vstack([
        np.column_stack([i, m0, m2]),
        np.column_stack([m0, j, m1]),
        np.column_stack([m2, m1, k]),
        np.column_stack([m0, m1, m2]),
    ]).astype(np.uint32)
    return verts, tris


def subdivide_midpoint(verts, indices, iters=1, max_edge=None):
    """中点细分:每个三角形拆成 4 个,新顶点为边中点。

    新顶点落在原折线上,折线角度不变 —— 低边数圆柱轮廓变密
    (6 边→12 边→24 边),而 90° 硬边角度原样保持。全 numpy 批量。

    max_edge 给定时,最长边超过该值的面再多细分一代:大直径圆柱
    (同边数下屏幕偏差最大、棱角最显眼)加密到边数 ×8,小面不再
    加密,控制总面数。
    """
    verts = np.asarray(verts, dtype=np.float32)
    tris = np.asarray(indices, dtype=np.int64)
    for _ in range(iters):
        verts, tris = _subdivide_once(verts, tris)
    if max_edge is not None:
        while True:
            longest = np.max(np.linalg.norm(
                verts[tris[:, [1, 2, 0]]] - verts[tris[:, [0, 1, 2]]],
                axis=2), axis=1)
            big = longest > max_edge
            if not big.any():
                break
            verts, sub = _subdivide_once(verts, tris[big])
            tris = np.vstack([tris[~big], sub]).astype(np.uint32)
            # 中点细分每代边长减半,必然有限次终止
    return verts, tris


def _subdiv_cached(path, verts, indices, iters=SUBDIV_ITERS, max_edge=None):
    """带磁盘缓存的焊接+细分:首次计算后存 ~/.omni/mesh_cache/。

    细分只与 STL 几何有关,按文件 mtime/大小/顶点数与迭代次数
    命名,文件变化后自动失效。
    """
    st = os.stat(path)
    key = hashlib.md5(
        f'{path}|{st.st_mtime:.3f}|{st.st_size}|{len(verts)}|{iters}'
        f'|{max_edge}|v2'.encode()).hexdigest()[:16]
    cache_path = os.path.join(_SMOOTH_CACHE_DIR, key + '_subdiv.npz')
    try:
        cached = np.load(cache_path)
        return cached['verts'], cached['tris']
    except (OSError, ValueError, KeyError):
        pass
    uniq_verts, uniq_tris = _weld_verts(verts, indices)
    sub_verts, sub_tris = subdivide_midpoint(uniq_verts, uniq_tris, iters,
                                             max_edge=max_edge)
    try:
        os.makedirs(_SMOOTH_CACHE_DIR, exist_ok=True)
        np.savez(cache_path, verts=sub_verts, tris=sub_tris)
    except OSError:
        pass  # 目录不可写(如打包后只读环境)时仅跳过缓存
    return sub_verts, sub_tris


def _smooth_cached(path, verts, norms, angle_deg=40.0, eps=1e-6):
    """带磁盘缓存的法线平滑:首次计算后存 ~/.omni/mesh_cache/。

    平滑只与 STL 原始顶点有关(法线是形状属性,均匀缩放不改变
    方向),因此用未缩放顶点计算;缓存按文件 mtime/大小/顶点数
    命名,文件变化后自动失效。启动从 ~8s 降到 ~3s。
    """
    st = os.stat(path)
    key = hashlib.md5(
        f'{path}|{st.st_mtime:.3f}|{st.st_size}|{len(verts)}|{angle_deg}'
        .encode()).hexdigest()[:16]
    cache_path = os.path.join(_SMOOTH_CACHE_DIR, key + '.npy')
    try:
        cached = np.load(cache_path)
        if len(cached) == len(verts):
            return cached.astype(np.float32)
    except (OSError, ValueError):
        pass
    out = smooth_normals(verts, norms, angle_deg=angle_deg, eps=eps)
    try:
        os.makedirs(_SMOOTH_CACHE_DIR, exist_ok=True)
        np.save(cache_path, out)
    except OSError:
        pass  # 目录不可写(如打包后只读环境)时仅跳过缓存
    return out


def load_stl(path, scale=(1, 1, 1), color=(0.5, 0.5, 0.5, 1.0), smooth=True):
    """加载 STL:焊接 → 中点细分(SUBDIV_ITERS 代)→ 法线平滑,
    返回 flat-shading 格式数组(每面 3 个独立顶点)。

    细分把低边数圆柱(6~12 边)加密到 24~48 边,轮廓与光影圆润;
    smooth=True 时法线平滑(默认)。
    """
    path = os.path.abspath(path)
    if path in _mesh_cache:
        verts, indices = _mesh_cache[path]
    else:
        import stl
        m = stl.mesh.Mesh.from_file(path)
        verts = m.vectors.reshape(-1, 3).astype(np.float32)
        indices = np.arange(len(verts), dtype=np.uint32)
        _mesh_cache[path] = (verts, indices)

    # 焊接 + 细分(带磁盘缓存),细分后用三角形叉积重算面法线;
    # 大面阈值取包围盒对角线 4%:大直径圆柱多细分一代(棱角在
    # 屏幕上最显眼),小面不加密,总面数只增加约 5%
    diag = float(np.linalg.norm(verts.max(axis=0) - verts.min(axis=0)))
    sub_verts, sub_tris = _subdiv_cached(path, verts, indices,
                                         max_edge=diag * 0.04)
    flat = sub_verts[sub_tris.ravel()]
    face_norms = np.repeat(_face_normals_from_tris(sub_verts, sub_tris), 3,
                           axis=0)
    indices = np.arange(len(flat), dtype=np.uint32)

    scaled = flat * np.asarray(scale, dtype=np.float32)
    if smooth:
        face_norms = _smooth_cached(path, flat, face_norms)
    colors = np.tile(np.asarray(color, dtype=np.float32), (len(indices), 1))
    return scaled, face_norms, colors, indices


def make_box(size, color=(0.5, 0.5, 0.5, 1.0)):
    """盒体(每个面两个三角形,面法线朝外)。"""
    w, h, d = size
    corners = np.array([
        [-w/2, -h/2, -d/2], [w/2, -h/2, -d/2], [w/2, h/2, -d/2], [-w/2, h/2, -d/2],
        [-w/2, -h/2, d/2], [w/2, -h/2, d/2], [w/2, h/2, d/2], [-w/2, h/2, d/2],
    ], dtype=np.float32)
    # 12 个三角形,每个面法线固定
    faces = [
        (0, 1, 2, [0, 0, -1]), (0, 2, 3, [0, 0, -1]),   # 底面
        (4, 7, 6, [0, 0, 1]), (4, 6, 5, [0, 0, 1]),     # 顶面
        (0, 4, 5, [0, -1, 0]), (0, 5, 1, [0, -1, 0]),   # 前
        (2, 6, 7, [0, 1, 0]), (2, 7, 3, [0, 1, 0]),     # 后
        (0, 3, 7, [-1, 0, 0]), (0, 7, 4, [-1, 0, 0]),   # 左
        (1, 5, 6, [1, 0, 0]), (1, 6, 2, [1, 0, 0]),     # 右
    ]
    return _from_faces(corners, faces, color)


def make_cylinder(radius, length, color=(0.5, 0.5, 0.5, 1.0), segments=32):
    """圆柱体(侧面 + 上下盖),平滑着色:侧面顶点法线取径向,
    上下盖取 ±Z —— 圆周光影连续,不再显示成棱柱。"""
    verts, norms, indices = [], [], []

    # 侧面:每段两个三角形,顶点法线径向(相邻面共享顶点法线)
    for i in range(segments):
        a0 = 2 * math.pi * i / segments
        a1 = 2 * math.pi * (i + 1) / segments
        n0 = [math.cos(a0), math.sin(a0), 0.0]
        n1 = [math.cos(a1), math.sin(a1), 0.0]
        b = len(verts)
        verts += [[radius * math.cos(a0), radius * math.sin(a0), -length / 2],
                  [radius * math.cos(a1), radius * math.sin(a1), -length / 2],
                  [radius * math.cos(a0), radius * math.sin(a0), length / 2],
                  [radius * math.cos(a1), radius * math.sin(a1), length / 2]]
        norms += [n0, n1, n0, n1]
        indices += [b, b + 1, b + 3, b + 3, b + 2, b]

    # 上下盖:环顶点与中心点法线 ±Z(独立于侧面顶点,交界保持清晰)
    for zsign in (-1.0, 1.0):
        center = len(verts)
        verts.append([0.0, 0.0, zsign * length / 2])
        norms.append([0.0, 0.0, zsign])
        ring = len(verts)
        for i in range(segments):
            a = 2 * math.pi * i / segments
            verts.append([radius * math.cos(a), radius * math.sin(a),
                          zsign * length / 2])
            norms.append([0.0, 0.0, zsign])
        for i in range(segments):
            j = (i + 1) % segments
            if zsign < 0:
                indices += [center, ring + i, ring + j]   # 底盖朝下
            else:
                indices += [center, ring + j, ring + i]   # 顶盖朝上

    verts = np.array(verts, dtype=np.float32)
    norms = np.array(norms, dtype=np.float32)
    indices = np.array(indices, dtype=np.uint32)
    colors = np.tile(np.asarray(color, dtype=np.float32), (len(indices), 1))
    return verts, norms, colors, indices


def make_sphere(radius, color=(0.5, 0.5, 0.5, 1.0), rows=20, cols=20):
    """经纬球,平滑着色:顶点法线 = 归一化顶点位置(球面连续光影)。"""
    verts, norms = [], []
    for r in range(rows + 1):
        phi = math.pi * r / rows
        for c in range(cols):
            theta = 2 * math.pi * c / cols
            pos = [radius * math.sin(phi) * math.cos(theta),
                   radius * math.sin(phi) * math.sin(theta),
                   radius * math.cos(phi)]
            verts.append(pos)
            norms.append(_normalize(pos))

    def idx(r, c):
        return r * cols + (c % cols)

    indices = []
    for r in range(rows):
        for c in range(cols):
            a, b = idx(r, c), idx(r, c + 1)
            c1, c2 = idx(r + 1, c), idx(r + 1, c + 1)
            indices += [a, c1, b, b, c1, c2]   # 绕序同旧版 _from_faces

    verts = np.array(verts, dtype=np.float32)
    norms = np.array(norms, dtype=np.float32)
    indices = np.array(indices, dtype=np.uint32)
    colors = np.tile(np.asarray(color, dtype=np.float32), (len(indices), 1))
    return verts, norms, colors, indices


def _normalize(v):
    v = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(v)
    return (v / n if n > 1e-9 else np.array([0, 0, 1], dtype=np.float32)).tolist()


def _from_faces(corner_verts, faces, color):
    """由 (顶点索引 a,b,c, 面法线) 列表生成 flat-shading 数组。"""
    verts, norms = [], []
    for (a, b, c, n) in faces:
        for k in (a, b, c):
            verts.append(corner_verts[k])
            norms.append(n)
    verts = np.array(verts, dtype=np.float32)
    norms = np.array(norms, dtype=np.float32)
    indices = np.arange(len(verts), dtype=np.uint32)
    colors = np.tile(np.asarray(color, dtype=np.float32), (len(indices), 1))
    return verts, norms, colors, indices


def make_kivy_mesh(verts, norms, colors, indices):
    """把 numpy 数组组装成 Kivy Mesh 指令列表。

    Kivy Mesh 索引仅支持 unsigned short(≤65535),大网格自动分块,
    每块独立重映射索引。
    """
    from kivy.graphics import Mesh

    MAX_VERTICES = 65535
    meshes = []
    indices = np.asarray(indices)
    total = len(indices)
    for start in range(0, total, MAX_VERTICES):
        chunk = indices[start:start + MAX_VERTICES]
        used, inverse = np.unique(chunk, return_inverse=True)
        vertex_data = np.hstack([verts[used], norms[used], colors[used]]).astype(np.float32)
        meshes.append(Mesh(
            vertices=vertex_data.flatten().tolist(),
            indices=inverse.astype(np.uint16).tolist(),
            fmt=[(b'v_pos', 3, 'float'), (b'v_normal', 3, 'float'), (b'v_color', 4, 'float')],
            mode='triangles',
        ))
    return meshes
