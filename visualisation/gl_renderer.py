"""裸 OpenGL 渲染层 —— 参考 ReachControl(kivy3)的做法。

背景:本机环境下 Kivy Canvas 的自定义 RenderContext 着色器静默失效
(conda-forge 2.3.1 / pip wheel 2.3.1 / 2.1.0 及官方 3Drendering 示例
均不渲染),因此 3D 渲染完全绕开 Kivy 着色器管线,用
kivy.graphics.opengl 直接调用 GL:

- 着色器自行编译(错误信息直接打印,不再静默失败)
- 每个网格一个 VBO(位置+法线+颜色 interleaved)+ IBO(uint32 索引,
  不受 Kivy Mesh 的 65535 顶点上限约束)
- 每帧由 Viewport3D 的定时器在 FBO 内调用 draw(),矩阵用 numpy
  计算后经 glUniformMatrix4fv 直接上传

接口:
    renderer = GLRenderer()
    mesh = renderer.upload_mesh(verts, norms, colors, indices)
    lines = renderer.upload_lines(points, colors)
    renderer.begin_frame(x, y, w, h)
    renderer.set_camera(view, proj, light_pos)
    renderer.draw_mesh(mesh, modelview)
    renderer.draw_lines(lines, modelview)
    renderer.end_frame()
"""

import os

import numpy as np

import kivy.graphics.opengl as gl

SHADER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'shaders', 'blinnphong_gl120.glsl')
LINE_SHADER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'shaders', 'line_gl120.glsl')


def _mat_bytes(m):
    """4x4 numpy → 列主序 bytes(glUniformMatrix4fv 用)。"""
    return np.ascontiguousarray(m, dtype=np.float32).T.tobytes()


def _mat3_bytes(m):
    """3x3 numpy → 列主序 bytes(glUniformMatrix3fv 用)。"""
    return np.ascontiguousarray(m, dtype=np.float32).T.tobytes()


def _compile(src, stype, tag):
    s = gl.glCreateShader(stype)
    gl.glShaderSource(s, src)
    gl.glCompileShader(s)
    if not gl.glGetShaderiv(s, gl.GL_COMPILE_STATUS):
        print(f'[gl_renderer] {tag} compile error:\n'
              + gl.glGetShaderInfoLog(s, 8192))
    return s


def _load_pair(path):
    """读取着色器文件,按 ---VERTEX---/---FRAGMENT--- 拆成两段。"""
    text = open(path, encoding='utf-8').read()
    vs = text.split('---VERTEX---')[1].split('---FRAGMENT---')[0]
    fs = text.split('---FRAGMENT---')[1]
    return vs.encode(), fs.encode()


def _link_program(vs, fs, attribs, tag):
    """编译并链接程序;attribs: {location: b'name'}。"""
    prog = gl.glCreateProgram()
    gl.glAttachShader(prog, _compile(vs, gl.GL_VERTEX_SHADER, tag))
    gl.glAttachShader(prog, _compile(fs, gl.GL_FRAGMENT_SHADER, tag))
    for loc, name in attribs.items():
        gl.glBindAttribLocation(prog, loc, name)
    gl.glLinkProgram(prog)
    if not gl.glGetProgramiv(prog, gl.GL_LINK_STATUS):
        print(f'[gl_renderer] {tag} link error:\n'
              + gl.glGetProgramInfoLog(prog, 8192))
    return prog


class MeshBuffer:
    """单个网格的 GPU 缓冲(interleaved: pos 3f + normal 3f + color 4f)。"""

    STRIDE = 40  # 10 floats * 4 bytes

    def __init__(self, verts, norms, colors, indices):
        data = np.hstack([verts, norms, colors]).astype(np.float32)
        self.count = len(indices)
        self.vbo = gl.glGenBuffers(1)[0]
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, data.nbytes, data.tobytes(),
                        gl.GL_STATIC_DRAW)
        self.ibo = gl.glGenBuffers(1)[0]
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, self.ibo)
        ibo_data = np.asarray(indices, dtype=np.uint32)
        gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, ibo_data.nbytes,
                        ibo_data.tobytes(), gl.GL_STATIC_DRAW)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, 0)

    def draw(self):
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, self.ibo)
        # 属性位置用 3/4/5,避开 Kivy 文字/矩形绘制用的 0/1 ——
        # 本机构建 Kivy 绘制前不复位 attrib 指针,3D 若动 0/1,
        # HUD 文字纹理的 UV 会采样错乱,文字渲染成实心白块。
        gl.glVertexAttribPointer(3, 3, gl.GL_FLOAT, gl.GL_FALSE, self.STRIDE, 0)
        gl.glVertexAttribPointer(4, 3, gl.GL_FLOAT, gl.GL_FALSE, self.STRIDE, 12)
        gl.glVertexAttribPointer(5, 4, gl.GL_FLOAT, gl.GL_FALSE, self.STRIDE, 24)
        gl.glEnableVertexAttribArray(3)
        gl.glEnableVertexAttribArray(4)
        gl.glEnableVertexAttribArray(5)
        gl.glDrawElements(gl.GL_TRIANGLES, self.count, gl.GL_UNSIGNED_INT, 0)
        # 注意:不要在这里 disable 顶点属性数组 —— 保持 3/4/5 启用,
        # 避免每帧重复启停(3/4/5 不影响 Kivy 的 0/1)。


class LineBuffer:
    """线段集合(unlit):points Nx3 + colors Nx4,GL_LINES 绘制。"""

    STRIDE = 28  # 7 floats * 4 bytes

    def __init__(self, points, colors):
        data = np.hstack([points, colors]).astype(np.float32)
        self.count = len(points)
        self.vbo = gl.glGenBuffers(1)[0]
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, data.nbytes, data.tobytes(),
                        gl.GL_STATIC_DRAW)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)

    def draw(self):
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
        gl.glVertexAttribPointer(3, 3, gl.GL_FLOAT, gl.GL_FALSE, self.STRIDE, 0)
        gl.glVertexAttribPointer(4, 4, gl.GL_FLOAT, gl.GL_FALSE, self.STRIDE, 12)
        gl.glEnableVertexAttribArray(3)
        gl.glEnableVertexAttribArray(4)
        gl.glDrawArrays(gl.GL_LINES, 0, self.count)
        # 同上:不 disable 顶点属性数组(3/4 不影响 Kivy 的 0/1)。


class GLRenderer:
    """裸 GL 渲染器:着色器编译、uniform 管理、每帧绘制。"""

    def __init__(self):
        lit_vs, lit_fs = _load_pair(SHADER_PATH)
        line_vs, line_fs = _load_pair(LINE_SHADER_PATH)
        # 属性位置避开 0/1(Kivy 文字/矩形绘制用),见 MeshBuffer.draw 注释
        self.lit_prog = _link_program(
            lit_vs, lit_fs, {3: b'pos', 4: b'normal', 5: b'color'}, 'lit')
        self.line_prog = _link_program(
            line_vs, line_fs, {3: b'pos', 4: b'color'}, 'line')

        p = self.lit_prog
        self.u_mv = gl.glGetUniformLocation(p, b'modelview_mat')
        self.u_proj = gl.glGetUniformLocation(p, b'projection_mat')
        self.u_nmat = gl.glGetUniformLocation(p, b'normal_mat')
        self.u_light = gl.glGetUniformLocation(p, b'light_pos')
        self.u_light2 = gl.glGetUniformLocation(p, b'light_pos2')
        self.u_camera = gl.glGetUniformLocation(p, b'camera_pos')
        self.u_ka = gl.glGetUniformLocation(p, b'Ka')
        self.u_intensity = gl.glGetUniformLocation(p, b'light_intensity')
        self.u_spec = gl.glGetUniformLocation(p, b'specular_power')

        lp = self.line_prog
        self.lu_mv = gl.glGetUniformLocation(lp, b'modelview_mat')
        self.lu_proj = gl.glGetUniformLocation(lp, b'projection_mat')

        self._view = np.eye(4, dtype=np.float32)

    # ---- 缓冲上传 ----

    def upload_mesh(self, verts, norms, colors, indices):
        return MeshBuffer(verts, norms, colors, indices)

    def upload_lines(self, points, colors):
        return LineBuffer(points, colors)

    # ---- 每帧绘制 ----

    def begin_frame(self, x, y, w, h, clear_color=(0.16, 0.16, 0.16, 1.0)):
        """设置视口、清屏(颜色+深度)、开启深度测试。

        视口区域的清屏完全由裸 GL 负责,不依赖 Kivy 管线。
        先保存 Kivy 当前的 program:end_frame 恢复它,否则 Kivy 的
        shader 缓存(_current_program)会与实际 GL program 不一致,
        导致 Kivy 跳过 glUseProgram,HUD 文字用错程序渲染成实心块。
        """
        self._saved_program = gl.glGetIntegerv(gl.GL_CURRENT_PROGRAM)[0]
        gl.glViewport(x, y, w, h)
        gl.glClearColor(*clear_color)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LEQUAL)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)

    def set_camera(self, view, proj, light_pos, light_pos2, ka=0.45,
                   intensity=1.0, specular_power=48.0):
        """设置每帧相机与光照;light_pos/light_pos2 为世界系,转视图空间后上传。"""
        self._view = np.asarray(view, dtype=np.float32)
        light_view = self._view @ np.append(np.asarray(light_pos, dtype=np.float32), 1.0)
        light2_view = self._view @ np.append(np.asarray(light_pos2, dtype=np.float32), 1.0)

        gl.glUseProgram(self.lit_prog)
        gl.glUniformMatrix4fv(self.u_proj, 1, gl.GL_FALSE, _mat_bytes(proj))
        gl.glUniform3f(self.u_light, *(light_view[:3]))
        gl.glUniform3f(self.u_light2, *(light2_view[:3]))
        gl.glUniform3f(self.u_camera, 0.0, 0.0, 0.0)  # 视图空间相机在原点
        gl.glUniform1f(self.u_ka, ka)
        gl.glUniform1f(self.u_intensity, intensity)
        gl.glUniform1f(self.u_spec, specular_power)

        gl.glUseProgram(self.line_prog)
        gl.glUniformMatrix4fv(self.lu_proj, 1, gl.GL_FALSE, _mat_bytes(proj))

    def draw_mesh(self, mesh, modelview, blend=False):
        """画一个网格;modelview 为世界系模型矩阵(视图矩阵在 set_camera 里)。

        blend=True 时开混合、关深度写入(半透明障碍物用)。
        """
        mv = self._view @ np.asarray(modelview, dtype=np.float32)
        if blend:
            gl.glEnable(gl.GL_BLEND)
            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
            gl.glDepthMask(False)
        gl.glUseProgram(self.lit_prog)
        gl.glUniformMatrix4fv(self.u_mv, 1, gl.GL_FALSE, _mat_bytes(mv))
        # 法线矩阵(3x3 嵌入 4x4,glUniformMatrix3fv 绑定残缺)
        nmat = np.linalg.inv(mv[:3, :3]).T.astype(np.float32)
        nmat4 = np.eye(4, dtype=np.float32)
        nmat4[:3, :3] = nmat
        gl.glUniformMatrix4fv(self.u_nmat, 1, gl.GL_FALSE, _mat_bytes(nmat4))
        mesh.draw()
        if blend:
            gl.glDepthMask(True)
            # 恢复 Kivy 的默认混合(straight alpha,见 kivy instructions.pyx
            # 初始化):设成预乘(ONE, ...)会导致文字纹理透明区被白色
            # 叠加,整个文字 quad 变实心白块。
            gl.glBlendFuncSeparate(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA,
                                   gl.GL_ONE, gl.GL_ONE)

    def draw_lines(self, lines, modelview=np.eye(4)):
        """画线段集合(unlit)。"""
        mv = self._view @ np.asarray(modelview, dtype=np.float32)
        gl.glUseProgram(self.line_prog)
        gl.glUniformMatrix4fv(self.lu_mv, 1, gl.GL_FALSE, _mat_bytes(mv))
        lines.draw()

    def end_frame(self):
        """恢复 GL 状态,避免污染 Kivy 默认管线。"""
        gl.glDisable(gl.GL_DEPTH_TEST)
        # 恢复 Kivy 的 program(而非 0):Kivy 的 Shader.use 有
        # _current_program 缓存,若实际 program 被我们改掉而缓存未
        # 更新,Kivy 会跳过 glUseProgram,后续 HUD 绘制全部用错程序。
        gl.glUseProgram(getattr(self, '_saved_program', 0))
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, 0)
        # 恢复全窗口视口:Kivy 只在窗口 resize 时重设 glViewport,若留着
        # 视口局部区域,下一帧 Kivy 的清屏和 HUD 绘制会被裁剪/错位。
        from kivy.core.window import Window
        density = getattr(Window, '_density', 1.0)
        gl.glViewport(0, 0, int(Window.width * density),
                      int(Window.height * density))
        # 恢复 Kivy 的清屏色:否则下一帧 Kivy 清屏会用我们留下的
        # 视口背景色刷满整个窗口,把 HUD 底下/周围全染成灰。
        gl.glClearColor(*Window.clearcolor)
        # 恢复 Kivy 的混合状态(straight alpha):与 Kivy 初始化一致
        # (instructions.pyx: SRC_ALPHA/ONE_MINUS_SRC_ALPHA, ONE/ONE)。
        # 错误的 blend 函数会让文字纹理的透明区域被白色叠加成实心块。
        gl.glBlendFuncSeparate(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA,
                               gl.GL_ONE, gl.GL_ONE)
        gl.glEnable(gl.GL_BLEND)
