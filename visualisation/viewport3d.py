"""3D 视口组件:地面网格 + RGB 坐标轴 + 机器人网格 + 轨道相机交互。

渲染走裸 OpenGL(gl_renderer),每帧画进离屏 FBO,再用普通纹理矩形
显示 —— 不用 Kivy 的自定义 RenderContext(本机环境不可用),也不用
canvas Callback 指令(本机构建在 Callback 后不复位顶点属性状态,
会破坏 HUD 文字纹理的 UV 采样)。网格/坐标轴与机器人网格统一走
GL 着色器,带深度测试。
"""

import ctypes
import ctypes.util
import math
import sys

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Fbo, Rectangle
from kivy.graphics import opengl as gl
from kivy.uix.widget import Widget

import numpy as np

import theme
from .camera import OrbitCamera, perspective
from .gl_renderer import GLRenderer
from .robot_builder import RobotScene

# Kivy 的 gl 包装缺 MSAA 相关的函数与常量,用 ctypes/常量补齐
GL_RGBA8 = 0x8058
GL_DEPTH_COMPONENT24 = 0x81A6
GL_READ_FRAMEBUFFER = 0x8CA8

if sys.platform == 'win32':
    # Windows 没有 libGL:MSAA 函数是 GL 扩展函数,opengl32.dll 不导出,
    # 只能 wglGetProcAddress 现取,且必须等 GL 上下文建立之后调用才
    # 返回有效指针 —— 延迟到 _ensure_msaa_gl(),首次调用发生在
    # _alloc_msaa 时(此时 Kivy 窗口已建、GL 上下文已当前)。
    _libgl = ctypes.WinDLL('opengl32')
    _wgl_get_proc = _libgl.wglGetProcAddress
    _wgl_get_proc.restype = ctypes.c_void_p
    _wgl_get_proc.argtypes = [ctypes.c_char_p]
    _glRenderbufferStorageMultisample = None
    _glBlitFramebuffer = None
else:
    _libgl = ctypes.CDLL(ctypes.util.find_library('GL'))
    _glRenderbufferStorageMultisample = _libgl.glRenderbufferStorageMultisample
    _glRenderbufferStorageMultisample.restype = None
    _glRenderbufferStorageMultisample.argtypes = [
        ctypes.c_uint, ctypes.c_int, ctypes.c_uint, ctypes.c_int, ctypes.c_int]
    _glBlitFramebuffer = _libgl.glBlitFramebuffer
    _glBlitFramebuffer.restype = None
    _glBlitFramebuffer.argtypes = [ctypes.c_int] * 10


def _ensure_msaa_gl():
    """Windows 上延迟取 MSAA 函数指针;Linux 上 import 时已绑定,直接返回。"""
    global _glRenderbufferStorageMultisample, _glBlitFramebuffer
    if sys.platform != 'win32' or _glRenderbufferStorageMultisample is not None:
        return
    addr = _wgl_get_proc(b'glRenderbufferStorageMultisample')
    if addr:
        _glRenderbufferStorageMultisample = ctypes.WINFUNCTYPE(
            None, ctypes.c_uint, ctypes.c_int, ctypes.c_uint,
            ctypes.c_int, ctypes.c_int)(addr)
    addr = _wgl_get_proc(b'glBlitFramebuffer')
    if addr:
        _glBlitFramebuffer = ctypes.WINFUNCTYPE(
            None, *([ctypes.c_int] * 10))(addr)
    if _glRenderbufferStorageMultisample is None or _glBlitFramebuffer is None:
        raise RuntimeError(
            '[viewport3d] wglGetProcAddress 取不到 MSAA 函数,'
            '显卡驱动可能不支持 OpenGL')


def _build_grid_points(spacing=theme.GRID_SPACING):
    """地面网格线段(xy 平面)。"""
    n = int(theme.GRID_SIZE / spacing)
    half = theme.GRID_SIZE
    pts = []
    for i in range(-n, n + 1):
        x = i * spacing
        pts += [[x, -half, 0], [x, half, 0]]
        pts += [[-half, x, 0], [half, x, 0]]
    return np.array(pts, dtype=np.float32)


def _build_axis_points():
    """RGB 三色坐标轴线段。"""
    a = theme.AXIS_LENGTH
    return np.array([[0, 0, 0], [a, 0, 0],
                     [0, 0, 0], [0, a, 0],
                     [0, 0, 0], [0, 0, a]], dtype=np.float32), \
        np.array([[0.9, 0.3, 0.3, 1], [0.9, 0.3, 0.3, 1],
                  [0.3, 0.9, 0.3, 1], [0.3, 0.9, 0.3, 1],
                  [0.3, 0.5, 0.95, 1], [0.3, 0.5, 0.95, 1]], dtype=np.float32)


class Viewport3D(Widget):
    """机器人 3D 视口;scene 由 load_robot() 填充。"""

    ROTATE_SPEED = 0.35   # 度/像素
    ZOOM_STEP = 1.1
    SSAA = 2              # 超采样:FBO 以窗口 2 倍分辨率渲染,再缩小显示
    MSAA = 8              # 多重采样抗锯齿:边缘 8x 采样(每屏像素 16 样本)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.camera = OrbitCamera()
        self.scene = None
        self.renderer = GLRenderer()
        self._touch_rot = None
        self._touch_pan = None
        self._rebuild_ev = None
        self.on_viewport_click = None   # 鼠标按下视口回调(主程序用它折叠侧边栏)

        # 背景装饰(一次上传,每帧绘制)
        grid_pts = _build_grid_points()
        grid_cols = np.tile(np.array(theme.GRID_COLOR, dtype=np.float32),
                            (len(grid_pts), 1))
        self.grid_lines = self.renderer.upload_lines(grid_pts, grid_cols)
        axis_pts, axis_cols = _build_axis_points()
        self.axes_lines = self.renderer.upload_lines(axis_pts, axis_cols)

        # MSAA 多重采样渲染目标(裸 GL renderbuffer),resolve 进普通 FBO
        self._msaa_fbo = gl.glGenFramebuffers(1)[0]
        self._msaa_color = gl.glGenRenderbuffers(1)[0]
        self._msaa_depth = gl.glGenRenderbuffers(1)[0]
        self._msaa_size = None

        with self.canvas:
            Color(1, 1, 1, 1)
            # 3D 画进离屏 FBO,再由普通纹理矩形显示 —— 不用 Callback
            # 指令:本机构建的 Kivy 在 Callback 执行后不复位顶点属性
            # 状态,HUD 文字纹理的 UV 会采样错乱(文字变实心白块)。
            self._fbo = Fbo(size=self._fbo_size())
            self._rect = Rectangle(texture=self._fbo.texture,
                                   pos=self.pos, size=self.size)
        self.bind(pos=self._sync_rect, size=self._sync_rect)
        # 窗口尺寸变化 → 防抖重建 FBO:纹理始终与窗口 1:1,不拉伸失真
        self.bind(size=self._schedule_fbo_rebuild)
        self._alloc_msaa()

        # 连续重绘:每帧把 3D 画进 FBO,再重画显示矩形
        Clock.schedule_interval(self._render, 1 / 60.0)

    def _fbo_size(self):
        """FBO 像素尺寸 = 窗口 × SSAA(初始化时窗口尚未布局,用 Window)。"""
        w = max(int(Window.width), 1) * self.SSAA
        h = max(int(Window.height), 1) * self.SSAA
        return (w, h)

    def _alloc_msaa(self):
        """分配 MSAA renderbuffer 并挂到裸 GL framebuffer 上。"""
        _ensure_msaa_gl()
        w, h = self._fbo_size()
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, self._msaa_color)
        _glRenderbufferStorageMultisample(
            gl.GL_RENDERBUFFER, self.MSAA, GL_RGBA8, w, h)
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, self._msaa_depth)
        _glRenderbufferStorageMultisample(
            gl.GL_RENDERBUFFER, self.MSAA, GL_DEPTH_COMPONENT24, w, h)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._msaa_fbo)
        gl.glFramebufferRenderbuffer(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
                                     gl.GL_RENDERBUFFER, self._msaa_color)
        gl.glFramebufferRenderbuffer(gl.GL_FRAMEBUFFER, gl.GL_DEPTH_ATTACHMENT,
                                     gl.GL_RENDERBUFFER, self._msaa_depth)
        if gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) != gl.GL_FRAMEBUFFER_COMPLETE:
            print('[viewport3d] MSAA framebuffer incomplete!')
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        self._msaa_size = (w, h)

    def _schedule_fbo_rebuild(self, *_):
        """窗口缩放结束后重建 FBO(拖拽 resize 连续触发,防抖)。"""
        if self._rebuild_ev is not None:
            self._rebuild_ev.cancel()
        self._rebuild_ev = Clock.schedule_once(self._rebuild_fbo, 0.15)

    def _rebuild_fbo(self, *_):
        size = self._fbo_size()
        if tuple(self._fbo.size) == size and self._msaa_size == size:
            return
        self._fbo = Fbo(size=size)
        self._rect.texture = self._fbo.texture
        self._alloc_msaa()
        # 旧 FBO 解除引用,GPU 资源由 GC 回收

    def _sync_rect(self, *_):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def _request_redraw(self, *_):
        self.canvas.ask_update()

    # ---- 场景 ----

    def load_robot(self, parser, urdf_dir):
        """构建机器人场景(重复调用会清掉旧的)。"""
        self.scene = RobotScene(parser, urdf_dir, self.renderer)
        self._request_redraw()

    # ---- 每帧绘制 ----

    def _render(self, *_):
        """把 3D 画进 MSAA 目标,resolve 到普通 FBO 纹理显示。"""
        _ensure_msaa_gl()
        w, h = self._msaa_size
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._msaa_fbo)
        try:
            self._draw_3d(w, h)
        finally:
            # resolve:多重采样缓冲 → 普通纹理(先绑 Kivy Fbo 为 DRAW,
            # 再把 READ 指回 MSAA 缓冲,避免 Kivy Fbo.bind 覆盖 READ)
            self._fbo.bind()
            gl.glBindFramebuffer(GL_READ_FRAMEBUFFER, self._msaa_fbo)
            _glBlitFramebuffer(0, 0, w, h, 0, 0, w, h,
                               gl.GL_COLOR_BUFFER_BIT, gl.GL_NEAREST)
            self._fbo.release()
            # Kivy Fbo 的全局栈首次 bind 记录的是此刻的绑定(MSAA fbo,
            # 不是默认 0),release 会停在 MSAA 上;显式回默认帧缓冲,
            # 否则 Kivy 的 HUD/显示矩形全画进 MSAA 缓冲,画面黑屏。
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        self.canvas.ask_update()

    def _draw_3d(self, w, h):
        """在已绑定的 FBO 里画一帧 3D(裸 GL,w/h 为 FBO 像素尺寸)。"""
        aspect = w / h
        view = self.camera.view_matrix
        proj = perspective(45.0, aspect, 0.05, 250.0)

        self.renderer.begin_frame(0, 0, w, h,
                                  clear_color=theme.COLOR_VIEWPORT_BG)
        self.renderer.set_camera(
            view, proj, theme.LIGHT_POS, theme.LIGHT_POS2,
            ka=theme.KA, intensity=theme.LIGHT_INTENSITY,
            specular_power=theme.SPECULAR_POWER)
        self.renderer.draw_lines(self.grid_lines)
        self.renderer.draw_lines(self.axes_lines)
        if self.scene is not None:
            self.scene.draw()
        self.renderer.end_frame()

    # ---- 交互 ----

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        # 本机 Kivy 构建把滚轮作为 scrolldown/scrollup 触摸派发,
        # 不触发 Window.on_mouse_scroll,缩放在这里处理。
        if touch.button == 'scrollup':
            self.camera.zoom(1.0 / self.ZOOM_STEP)    # 滚轮向上:放大(拉近)
            self._request_redraw()
            return True
        if touch.button == 'scrolldown':
            self.camera.zoom(self.ZOOM_STEP)          # 滚轮向下:缩小(拉远)
            self._request_redraw()
            return True
        if touch.button == 'right':
            self._touch_pan = touch
        elif touch.button == 'left':
            self._touch_rot = touch
        # 点击 3D 画面(非滚轮)通知主程序:折叠展开的侧边栏
        if self.on_viewport_click:
            self.on_viewport_click()
        return True

    def on_touch_move(self, touch):
        if touch is self._touch_rot:
            dx, dy = touch.pos[0] - touch.ppos[0], touch.pos[1] - touch.ppos[1]
            # dy 取负:向上拖拽时相机下降(抓取手感),与常规方向一致
            self.camera.rotate(-dx * self.ROTATE_SPEED, -dy * self.ROTATE_SPEED)
            self._request_redraw()
            return True
        if touch is self._touch_pan:
            dx, dy = touch.pos[0] - touch.ppos[0], touch.pos[1] - touch.ppos[1]
            self.camera.pan(dx, dy)
            self._request_redraw()
            return True
        return False

    def on_touch_up(self, touch):
        if touch is self._touch_rot:
            self._touch_rot = None
            return True
        if touch is self._touch_pan:
            self._touch_pan = None
            return True
        return False
