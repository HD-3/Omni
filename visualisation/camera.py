"""轨道相机:球坐标旋转、滚轮缩放、平移。输出视图/投影矩阵(numpy 实现)。"""

import math

import numpy as np


def perspective(fovy_deg, aspect, near, far):
    """透视投影矩阵(与 gluPerspective 一致)。"""
    f = 1.0 / math.tan(math.radians(fovy_deg) / 2.0)
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2.0 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


def look_at(eye, center, up=(0, 0, 1)):
    """视图矩阵:相机位于 eye,看向 center。"""
    eye = np.asarray(eye, dtype=np.float32)
    center = np.asarray(center, dtype=np.float32)
    up = np.asarray(up, dtype=np.float32)

    f = center - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)

    m = np.eye(4, dtype=np.float32)
    m[0, :3] = s
    m[1, :3] = u
    m[2, :3] = -f
    m[0, 3] = -np.dot(s, eye)
    m[1, 3] = -np.dot(u, eye)
    m[2, 3] = np.dot(f, eye)
    return m


def mat_to_gl(mat):
    """numpy 4x4(行主序)→ OpenGL 列主序 16 元 list。"""
    return np.asarray(mat, dtype=np.float32).T.flatten().tolist()


class OrbitCamera:
    """球坐标轨道相机。

    eye = target + distance * [cos(el)cos(az), cos(el)sin(az), sin(el)]
    """

    MIN_DISTANCE = 0.2
    MAX_DISTANCE = 60.0   # 滚轮缩小范围上限(配合 far=250,可缩到全局视野)
    MAX_ELEVATION = 89.0

    def __init__(self, distance=3.0, azimuth=45.0, elevation=15.0, target=(0, 0, 0.15)):
        self.distance = distance
        self.azimuth = azimuth
        self.elevation = elevation
        self.target = np.array(target, dtype=np.float32)

    # ---- 变换 ----

    def rotate(self, d_azimuth, d_elevation):
        """拖拽旋转(角度增量)。"""
        self.azimuth = (self.azimuth + d_azimuth) % 360.0
        self.elevation = max(-self.MAX_ELEVATION,
                             min(self.MAX_ELEVATION, self.elevation + d_elevation))

    def zoom(self, factor):
        """滚轮缩放,factor < 1 拉近。"""
        self.distance = max(self.MIN_DISTANCE,
                            min(self.MAX_DISTANCE, self.distance * factor))

    def pan(self, dx, dy):
        """平移目标点(屏幕像素增量换算为世界位移)。

        场景跟随鼠标:目标点沿相机右/上方向的反向移动,画面才随
        拖拽同向走(拖上 → 场景上移 → 目标点向下)。
        """
        _, s, u = self._basis()
        k = self.distance * 0.0015  # 像素 → 世界比例
        self.target = self.target + s * (-dx * k) + u * (-dy * k)

    # ---- 矩阵 ----

    @property
    def eye(self):
        el = math.radians(self.elevation)
        az = math.radians(self.azimuth)
        d = self.distance
        return (self.target[0] + d * math.cos(el) * math.cos(az),
                self.target[1] + d * math.cos(el) * math.sin(az),
                self.target[2] + d * math.sin(el))

    def _basis(self):
        """返回 (前向, 右向, 上向) 单位向量。"""
        eye = np.asarray(self.eye, dtype=np.float32)
        f = self.target - eye
        f /= np.linalg.norm(f)
        s = np.cross(f, (0, 0, 1))
        n = np.linalg.norm(s)
        if n < 1e-9:
            s = np.array([1.0, 0.0, 0.0], dtype=np.float32)  # 俯视退化时
        else:
            s /= n
        u = np.cross(s, f)
        return f, s, u

    @property
    def view_matrix(self):
        return look_at(self.eye, self.target)

    def pv_matrix(self, aspect):
        """投影 × 视图矩阵(直接作为 projection_mat 传给着色器)。"""
        p = perspective(45.0, aspect, 0.05, 50.0)
        return p @ self.view_matrix

    def gl_projection(self, aspect):
        return mat_to_gl(self.pv_matrix(aspect))
