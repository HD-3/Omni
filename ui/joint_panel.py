"""关节控制面板(左栏 HUD):每个关节一行 名称 + 滑块 + 数值。

镜像关节对(如夹爪 JointGL/JointGR)合并成单行,一个滑块同步驱动。
"""

import math
from io import BytesIO

from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, Rectangle
from kivy.properties import (BooleanProperty, ListProperty, NumericProperty,
                             StringProperty)
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

import theme


# 框内内容的纵向对齐基准(NotoSansCJK SC 14px,窗口坐标实测):
# 数字字形占 638-647 行 → 视觉中心距框底 9.5px;
# 「度」字形在 21 行高纹理中占 2-15 行 → 中心 8.5px
# (FBO 读回实测,勿用行高一半 10.5 猜——CoreLabel 有内边距,
# 字形在纹理里偏上,拿 10.5 算会让度字比目标低 2px)
_DIGIT_CENTER = 9.5
_DEG_CENTER_IN_TEX = 8.5


def _build_box_texture(size, radius, bg_rgba, border_rgba, scale=4):
    """离屏超采样渲染输入框外观(圆角深底 + 1px 圆角环)成纹理。

    GL 直接画 1px Line 圆弧:三角带在半径 4 的小尺度下栅格化成
    2px 宽的阶梯(角落像素 89/89、72/76 参差,肉眼就是锯齿)。
    改为 PIL 4× 超采样画圆角环 + 双线性缩回,抗锯齿离线一次做好,
    贴回后圆角是平滑渐变,与 GL 光栅化无关。
    """
    from PIL import Image, ImageDraw
    w, h = size
    W, H = w * scale, h * scale
    lw = scale          # 1px 线宽(超采样坐标系)
    r = radius * scale

    # Kivy 主题色是 0-1 浮点,PIL 要 0-255 整数
    bg8 = tuple(round(c * 255) for c in bg_rgba[:3]) + (255,)
    ring8 = tuple(round(c * 255) for c in border_rgba[:3]) + (0,)

    bg_mask = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(bg_mask)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=r, fill=255)
    bg = Image.new('RGBA', (W, H), bg8)
    bg.putalpha(bg_mask)

    ring_mask = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(ring_mask)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=r,
                        fill=round(border_rgba[3] * 255))
    d.rounded_rectangle([lw, lw, W - 1 - lw, H - 1 - lw],
                        radius=r - lw, fill=0)
    ring = Image.new('RGBA', (W, H), ring8)
    ring.putalpha(ring_mask)

    # BOX 滤波:整数倍缩小时恰好逐块平均——直边像素精确 1px、
    # 无相邻灰晕,圆角处保留 16 级平滑渐变
    img = Image.alpha_composite(bg, ring).resize((w, h), Image.BOX)
    buf = BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)
    return CoreImage(buf, ext='png').texture


class StepInput(TextInput):
    """步长输入框:圆角深底 + 细描边,聚焦时描边高亮为主题蓝。

    TextInput 默认 kv 样式自带背景块与光标,都画在 canvas.before,
    会被本控件后插入的圆角底盖住(白底露角 + 光标不可见)。因此:
    背景色置透明,光标改在 canvas.after 自绘。
    """

    _tex_cache = {}   # (size, radius, border_rgba) → Texture
    _deg_tex = None   # 单位汉字「度」的字形纹理(类级缓存)

    @classmethod
    def _get_deg_texture(cls):
        """单位汉字「度」的字形纹理;字体与输入框一致(Roboto=NotoSansCJK)。"""
        if cls._deg_tex is None:
            from kivy.core.text import Label as CoreLabel
            cl = CoreLabel(text='度', font_size=theme.FONT_SIZE_HELP,
                           color=theme.COLOR_TEXT_DIM)
            cl.refresh()
            cls._deg_tex = cl.texture
        return cls._deg_tex

    def __init__(self, **kw):
        super().__init__(**kw)
        # 外观整体是一张贴图(圆角底 + 边框环),失焦/聚焦各一张
        self._tex_dim = self._get_box_texture(
            tuple(self.size), (*theme.COLOR_TEXT_DIM[:3], 0.6))
        self._tex_focused = self._get_box_texture(
            tuple(self.size), theme.COLOR_ACCENT)
        with self.canvas.before:
            Color(1, 1, 1, 1)   # 纹理自带 RGBA,用白色乘色保留原色
            self._gfx_box = Rectangle(
                texture=self._tex_dim, pos=self.pos, size=self.size)
            # style.kv 在 canvas.before 末尾用 foreground_color 给文字纹理
            # 着色;上面的自绘指令把它改掉了,必须重新设回,
            # 否则文字被染成别的颜色(与描边同色,几乎看不清)
            Color(*self.foreground_color)
        with self.canvas.after:
            self._gfx_cursor = Color(0, 0, 0, 0)
            self._gfx_cursor_rect = Rectangle(pos=(0, 0), size=(0, 0))
            # 单位汉字「度」画在框内右侧(纯装饰,不参与编辑/解析)
            Color(1, 1, 1, 1)
            self._gfx_deg = Rectangle(texture=self._get_deg_texture())
            # 「度」左侧的数值分隔竖线(1px,高度 14 垂直居中)
            self._gfx_sep = Color(*theme.COLOR_TEXT_DIM[:3], 0.5)
            self._gfx_sep_rect = Rectangle(pos=(0, 0), size=(1, 14))
        # 注意:回调名不能叫 _on_focus——FocusBehavior.__init__ 会
        # fbind('focus', self._on_focus) 绑定自己的键盘注册逻辑,
        # 子类同名方法会把它盖掉,导致聚焦后拿不到键盘、无法输入
        self.bind(pos=self._on_geom, size=self._on_geom,
                  focus=self._on_focus_visual)
        self.bind(_cursor_visual_pos=self._sync_cursor,
                  _cursor_visual_height=self._sync_cursor,
                  cursor_width=self._sync_cursor,
                  focus=self._sync_cursor,
                  _cursor_blink=self._sync_cursor)

    @classmethod
    def _get_box_texture(cls, size, border_rgba):
        key = (tuple(size), 4, tuple(border_rgba))
        tex = cls._tex_cache.get(key)
        if tex is None:
            tex = _build_box_texture(size, 4, theme.COLOR_INPUT_BG,
                                     border_rgba)
            cls._tex_cache[key] = tex
        return tex

    def _on_geom(self, *args):
        """跟随布局移动/缩放,防止画布图形与控件脱位。"""
        self._gfx_box.pos = self.pos
        self._gfx_box.size = self.size
        tex = self._get_deg_texture()
        self._gfx_deg.size = tex.size
        # 「度」的视觉中心对齐「步长」标签字形中心(643.5,实测两者
        # 字形同为 637-650 行);y 必须取整,半像素位置会让 GPU 双线性
        # 采样把字形和透明纹素插值,符号被糊暗
        self._gfx_deg.pos = (self.right - 8 - tex.width,
                             int(self.y + self.height / 2
                                 - _DEG_CENTER_IN_TEX))
        # 分隔线 14 高,中心同样对齐数字中心
        self._gfx_sep_rect.pos = (self._gfx_deg.pos[0] - 7,
                                  int(self.y + _DIGIT_CENTER - 7 + 0.5))

    def _on_focus_visual(self, w, focused):
        """聚焦:描边变主题蓝;失焦恢复次级灰。只换贴图,几何不变。"""
        self._gfx_box.texture = (self._tex_focused if focused
                                 else self._tex_dim)

    def _sync_cursor(self, *args):
        """在圆角底之上重画光标(_cursor_visual_pos 是窗口坐标)。"""
        if self.focus and not self._cursor_blink:
            x, y = self._cursor_visual_pos
            h = self._cursor_visual_height
            self._gfx_cursor.rgba = self.cursor_color
            self._gfx_cursor_rect.pos = (x, y - h)
            self._gfx_cursor_rect.size = (self.cursor_width, h)
        else:
            self._gfx_cursor.rgba = (0, 0, 0, 0)


class JointRow(BoxLayout):
    """单个关节的滑块行。"""

    joint_name = StringProperty('')
    joint_names = ListProperty([])   # 该滑块驱动的全部关节(合并对含两个)
    # 面板上 minv/maxv/value/default 的单位都是度(显示);回调时转弧度
    minv = NumericProperty(-180.0)
    maxv = NumericProperty(180.0)
    value = NumericProperty(0.0)
    default = NumericProperty(0.0)   # 复位目标:URDF 加载时的默认位
    dragging = BooleanProperty(False)  # 正在拖滑块时,板回读不覆盖该行

    # 本机 Kivy 构建不会把 kv 里 id: xxx 自动赋给同名属性
    # (实测 ObjectProperty 恒为 None),控件统一经 self.ids 取
    def _find_panel(self):
        """沿父链找 JointPanel。

        行挂在 ScrollView 的 GridLayout 里,on_joint_value 定义在
        JointPanel 上(直接看 self.parent 拿到的是 GridLayout,
        回调会静默丢失)。
        """
        node = self.parent
        while node and not getattr(node, 'on_joint_value', None):
            node = node.parent
        return node

    def on_value_slider(self, slider, val):
        """滑块拖动 → 回调主程序。"""
        node = self._find_panel()
        if node:
            # 合并行(如夹爪)一次拖动同步驱动两个关节;
            # 滑块值单位是度,场景/回调用弧度
            for jn in self.joint_names or [self.joint_name]:
                node.on_joint_value(jn, math.radians(val))
        label = self.ids.get('value_label')
        if label:
            label.text = f"{val:.1f}°"

    def on_step_button(self, direction):
        """+/- 按钮:按面板顶部输入的统一步长(度)增减,夹在限位内。"""
        node = self._find_panel()
        slider = self.ids.get('slider')
        if node is None or slider is None:
            return
        val = slider.value + direction * node.step
        slider.value = max(self.minv, min(self.maxv, val))

    def _on_slider_touch(self, slider, touch):
        self.dragging = True

    def _on_slider_release(self, slider, touch):
        self.dragging = False


class JointPanel(BoxLayout):
    """左栏关节控制面板。"""

    step = NumericProperty(5.0)   # +/- 按钮的统一步长(度)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.callback = None
        self.rows = {}       # 显示名 → 行(复位遍历)
        self._row_of = {}    # 原始关节名 → 行(update_label 反查合并行)
        self._suppress = False  # 板回读写滑块期间抑制回调(避免回声循环)
        self.on_mode_toggle = None  # 控制权按钮回调(由主程序注入)

        # 顶部:控制权切换(PC 可操作 / 板只读显示板回读)
        self.mode_btn = Button(text='控制权: PC', size_hint=(1, None), height=40)
        self.mode_btn.bind(on_release=lambda b: self.on_mode_toggle
                           and self.on_mode_toggle())
        self.add_widget(self.mode_btn)

        # 顶部:步长输入(所有关节的 +/- 共用,单位度),整行水平居中
        step_anchor = AnchorLayout(anchor_x='center',
                                   size_hint=(1, None), height=40)
        self.step_row = BoxLayout(orientation='horizontal',
                                  size_hint=(None, None), width=124,
                                  height=40, spacing=6)
        self.step_row.add_widget(Label(
            text='步长', size_hint_x=None, width=44,
            font_size=theme.FONT_SIZE_HELP, color=theme.COLOR_TEXT_DIM))
        self.step_input = StepInput(
            text='5', size_hint_x=None, width=74,   # 加宽容纳汉字「度」
            size_hint_y=None, height=22,   # 行高 40,输入框收窄后 22(25 再减 10%)
            # BoxLayout 横排不自带交叉轴居中,手动居中;但「步长」两个字的
            # 字形中心(643.5)比行中心(646)低 2.5px,框下移 2px 与之对齐。
            # 注意:pos_hint center_y 按父行全高计算(center = parent.y +
            # center_y × parent.height),不是按剩余空间!目标框中心 644:
            # center_y = (644 - 626) / 40 = 0.45
            pos_hint={'center_y': 0.45},
            multiline=False,
            input_filter='float', font_size=theme.FONT_SIZE_HELP,
            # 行高 21≤22,聚焦不触发竖向滚动(否则文字点击时上下跳);
            # 右侧 padding 留出「分隔线 | + 度」的位置;数字右对齐
            # 贴着分隔线,不同长度数字的右缘对齐,不会与「度」重叠
            halign='right', padding=(4, 0, 36, 0),
            background_normal='', background_active='',
            background_color=(0, 0, 0, 0),  # 关掉默认样式底块,背景由 StepInput 自绘
            foreground_color=theme.COLOR_TEXT, cursor_color=theme.COLOR_ACCENT)
        self.step_input.bind(text=self._on_step_text)
        self.step_row.add_widget(self.step_input)
        step_anchor.add_widget(self.step_row)
        self.add_widget(step_anchor)

        # 关节行高度随内容自适应,超过上限滚动(侧边栏整体按内容收缩)
        self.scroll = ScrollView(size_hint=(1, None), height=120)
        self.grid = GridLayout(cols=1, size_hint_y=None, spacing=4,
                               padding=(0, 4, 4, 0))
        self.grid.bind(minimum_height=self.grid.setter('height'))
        self.grid.bind(minimum_height=self._cap_scroll_height)
        self.scroll.add_widget(self.grid)
        self.add_widget(self.scroll)

        self.reset_btn = Button(text='复位关节', size_hint=(1, None), height=48)
        self.reset_btn.bind(on_release=self._on_reset)
        self.add_widget(self.reset_btn)

    def _cap_scroll_height(self, grid, h):
        """关节行少时滚动区按内容高度收缩,行多时封顶滚动。"""
        self.scroll.height = min(h, 520)

    def _on_step_text(self, inp, text):
        """步长输入变化:解析为度;非法/非正值忽略,保持旧步长。"""
        try:
            val = float(text)
        except ValueError:
            return
        if val > 0:
            self.step = val

    # ---- 数据绑定 ----

    def setup(self, joint_limits, callback):
        """填充关节行;joint_limits: {name: {lower, upper, position}}"""
        self.callback = callback
        self.grid.clear_widgets()
        self.rows = {}
        self._row_of = {}
        for display, jnames in self._group_joints(joint_limits):
            limits = joint_limits[jnames[0]]
            row = JointRow(
                joint_name=display,
                joint_names=jnames,
                # URDF 限位是弧度,面板显示用度
                minv=math.degrees(limits['lower']),
                maxv=math.degrees(limits['upper']),
                value=math.degrees(limits.get('position', 0.0)),
                default=math.degrees(limits.get('position', 0.0)),
            )
            self.rows[display] = row
            for jn in jnames:
                self._row_of[jn] = row
            # 拖动标记:板回读同步时跳过正被拖的滑块
            slider = row.ids['slider']
            slider.bind(on_touch_down=row._on_slider_touch,
                        on_touch_up=row._on_slider_release)
            self.grid.add_widget(row)

    @staticmethod
    def _group_joints(joint_limits):
        """把镜像关节对(如 JointGL/JointGR)合并成一个控制信号。

        夹爪左右指本来就同步开合,各给一个滑块既啰嗦,还可能把
        两根指头拖成不同开度。合并规则:名字只差末尾 L/R、限位
        相同的两个关节,归并到以公共前缀命名的单行(如 JointG)。
        """
        grouped = []   # [(显示名, [关节名...])]
        used = set()
        for n in sorted(joint_limits.keys()):
            if n in used:
                continue
            partner = None
            for sfx, other in (('L', 'R'), ('R', 'L')):
                if n.endswith(sfx):
                    p = n[:-1] + other
                    if p in joint_limits:
                        partner = p
            limits = joint_limits[n]
            if (partner is not None and partner not in used
                    and joint_limits[partner]['lower'] == limits['lower']
                    and joint_limits[partner]['upper'] == limits['upper']):
                grouped.append((n[:-1], [n, partner]))
                used.update((n, partner))
            else:
                grouped.append((n, [n]))
                used.add(n)
        return grouped

    def on_joint_value(self, joint_name, angle):
        if not self._suppress and self.callback:
            self.callback(joint_name, angle)

    def update_label(self, joint_name, angle):
        """angle 是弧度,显示转度。"""
        row = self._row_of.get(joint_name)
        if row:
            label = row.ids.get('value_label')
            if label:
                label.text = f"{math.degrees(angle):.1f}°"

    def is_dragging(self, joint_name):
        """该关节的滑块是否正被拖动(板回读同步时跳过)。"""
        row = self._row_of.get(joint_name)
        return bool(row and row.dragging)

    def set_control_mode(self, mode):
        """控制权:'pc' 可操作;'board' 只读,仅显示板回读。"""
        self.mode_btn.text = f"控制权: {'PC' if mode == 'pc' else '板'}"
        self.set_readonly(mode == 'board')

    def set_readonly(self, readonly):
        """禁用命令输入(滑块/步进/复位);板回读照常显示。"""
        self.step_input.disabled = readonly
        self.reset_btn.disabled = readonly
        for row in self.rows.values():
            row.ids['slider'].disabled = readonly
            row.ids['btn_minus'].disabled = readonly
            row.ids['btn_plus'].disabled = readonly

    def set_slider_feedback(self, joint_name, angle_rad):
        """板回读同步滑块位置(度)。

        置位 _suppress 抑制回调:改了值但不把命令发回板,
        避免 PC↔板 回声循环。
        """
        row = self._row_of.get(joint_name)
        if row is None:
            return
        self._suppress = True
        try:
            row.ids['slider'].value = math.degrees(angle_rad)
        finally:
            self._suppress = False

    def _on_reset(self, *_):
        """复位到 URDF 加载时的默认位。

        不用限位中点:夹爪等关节限位不对称(如 s7 夹爪 [0, 0.5983]),
        中点 0.3 会把闭合的夹爪拉到半开;默认位才是「复位」语义。
        """
        for jn, row in self.rows.items():
            row.ids['slider'].value = row.default
