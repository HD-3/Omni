"""板连接面板(左栏 HUD):手动输入 IP/端口连接实物开发板。

连接/断开状态由主程序注入(set_state);启动时只预填上次成功
连接的地址(set_prefill),不自动连接。
"""

from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput

import theme


class ConnectInput(TextInput):
    """连接面板输入框:圆角深底 + 细描边,聚焦时描边高亮为主题蓝。

    TextInput 默认 kv 样式自带背景块与光标,都画在 canvas.before,
    会被本控件后插入的圆角底盖住(白底露角 + 光标不可见)。因此:
    背景色置透明,背景与光标改在 canvas.before/after 自绘。
    描边用双圆角矩形叠加(同 kv 里 +/- 步进按钮的做法),避开
    1px Line 圆弧的阶梯锯齿。
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            self._gfx_border = Color(*theme.COLOR_TEXT_DIM[:3], 0.6)
            self._gfx_border_rect = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[6])
            Color(*theme.COLOR_INPUT_BG)
            self._gfx_bg = RoundedRectangle(
                pos=(self.x + 1, self.y + 1),
                size=(self.width - 2, self.height - 2), radius=[5])
            # style.kv 在 canvas.before 末尾用 foreground_color 给文字纹理
            # 着色;上面的自绘指令把它改掉了,必须重新设回,
            # 否则文字被染成别的颜色(见 joint_panel.StepInput 同款注释)
            Color(*self.foreground_color)
        with self.canvas.after:
            self._gfx_cursor = Color(0, 0, 0, 0)
            self._gfx_cursor_rect = Rectangle(pos=(0, 0), size=(0, 0))
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

    def _on_geom(self, *args):
        """跟随布局移动/缩放,防止画布图形与控件脱位。"""
        self._gfx_border_rect.pos = self.pos
        self._gfx_border_rect.size = self.size
        self._gfx_bg.pos = (self.x + 1, self.y + 1)
        self._gfx_bg.size = (self.width - 2, self.height - 2)

    def _on_focus_visual(self, w, focused):
        """聚焦:描边变主题蓝;失焦恢复次级灰。"""
        self._gfx_border.rgba = (theme.COLOR_ACCENT if focused
                                 else (*theme.COLOR_TEXT_DIM[:3], 0.6))

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


class ConnectPanel(BoxLayout):
    """板连接面板:IP/端口输入 + 连接/断开按钮,连接后输入只读。"""

    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', spacing=6, **kwargs)
        self.on_connect = None     # (host, port) -> None,由主程序注入
        self.on_disconnect = None  # () -> None,由主程序注入
        self.linked = False        # 是否已有链路(含连接中/断线重试)

        self.add_widget(Label(
            text='设备连接设置', size_hint=(1, None), height=28,
            font_size=theme.FONT_SIZE_HELP, color=theme.COLOR_TEXT_DIM))

        self.ip_row = BoxLayout(orientation='horizontal',
                                size_hint=(1, None), height=40, spacing=6)
        self.ip_row.add_widget(Label(
            text='IP', size_hint_x=None, width=44,
            font_size=theme.FONT_SIZE_HELP, color=theme.COLOR_TEXT_DIM))
        self.ip_input = ConnectInput(
            text='', size_hint=(1, None), height=28,
            pos_hint={'center_y': 0.5},
            multiline=False, font_size=theme.FONT_SIZE_HELP,
            # TextInput 无 valign,靠 padding_y 把文字挤到框的垂直中心
            # (28 高 - 14px 中文字形行高约 21) / 2 ≈ 4
            halign='left', padding=(6, 4),
            background_normal='', background_active='',
            background_color=(0, 0, 0, 0),  # 关掉默认样式底块,背景自绘
            foreground_color=theme.COLOR_TEXT, cursor_color=theme.COLOR_ACCENT)
        self.ip_row.add_widget(self.ip_input)
        self.add_widget(self.ip_row)

        self.port_row = BoxLayout(orientation='horizontal',
                                  size_hint=(1, None), height=40, spacing=6)
        self.port_row.add_widget(Label(
            text='端口', size_hint_x=None, width=44,
            font_size=theme.FONT_SIZE_HELP, color=theme.COLOR_TEXT_DIM))
        self.port_input = ConnectInput(
            text='8765', size_hint=(1, None), height=28,
            pos_hint={'center_y': 0.5},
            multiline=False, input_filter='int',
            font_size=theme.FONT_SIZE_HELP,
            halign='left', padding=(6, 4),
            background_normal='', background_active='',
            background_color=(0, 0, 0, 0),
            foreground_color=theme.COLOR_TEXT, cursor_color=theme.COLOR_ACCENT)
        self.port_row.add_widget(self.port_input)
        self.add_widget(self.port_row)

        self.tip = Label(
            text='', size_hint=(1, None), height=24,
            font_size=theme.FONT_SIZE_HELP, color=theme.COLOR_TEXT_DIM)
        self.add_widget(self.tip)

        self.btn = Button(text='连接', size_hint=(1, None), height=48)
        self.btn.bind(on_release=self._on_btn)
        self.add_widget(self.btn)

    # ---- 主程序注入的接口 ----

    def set_prefill(self, host, port):
        """启动时预填上次成功连接的地址;host 为空则留空。"""
        self.ip_input.text = host or ''
        self.port_input.text = str(port or 8765)

    def set_state(self, linked):
        """连接后按钮变「断开」、输入只读;断开后恢复可编辑。"""
        self.linked = linked
        self.btn.text = '断开' if linked else '连接'
        self.ip_input.disabled = linked
        self.port_input.disabled = linked
        if not linked:
            self._tip('', warn=False)

    def set_status(self, connected):
        """链路状态提示(仅已建立链路时显示)。"""
        if not self.linked:
            return
        self._tip('已连接' if connected else '未连接,自动重试中…',
                  warn=False)

    # ---- 内部 ----

    def _on_btn(self, *_):
        if self.linked:
            if self.on_disconnect:
                self.on_disconnect()
            return
        host = self.ip_input.text.strip()
        port_text = self.port_input.text.strip()
        if not host:
            self._tip('请输入板 IP', warn=True)
            return
        try:
            port = int(port_text)
        except ValueError:
            self._tip('端口必须是数字', warn=True)
            return
        if not 1 <= port <= 65535:
            self._tip('端口范围 1-65535', warn=True)
            return
        self._tip('连接中…', warn=False)
        if self.on_connect:
            self.on_connect(host, port)

    def _tip(self, text, warn=False):
        self.tip.text = text
        self.tip.color = theme.COLOR_WARN if warn else theme.COLOR_TEXT_DIM
