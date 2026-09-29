"""URDF 选择对话框:列出 assets/urdfs 下的机器人文件夹供选择。

不索引整个设备——只扫描 urdfs 目录,每个子文件夹一项(取其中
第一个 .urdf 文件),显示文件夹名。确定后回调 on_select(urdf 路径)。
"""

import os
import sys

from kivy.graphics import Color, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView

import theme

# 与 main.py 的 PROJECT_ROOT 同一套逻辑(PyInstaller 打包后资源在 _MEIPASS)
_PROJECT_ROOT = (getattr(sys, '_MEIPASS')
                 if getattr(sys, 'frozen', False)
                 else os.path.dirname(os.path.dirname(
                     os.path.abspath(__file__))))
URDFS_ROOT = os.path.join(_PROJECT_ROOT, 'visualisation', 'assets', 'urdfs')


def _scan():
    """[(文件夹名, 文件夹内第一个 .urdf 路径)],按名字排序。"""
    entries = []
    try:
        names = sorted(os.listdir(URDFS_ROOT))
    except OSError:
        return entries
    for name in names:
        folder = os.path.join(URDFS_ROOT, name)
        if not os.path.isdir(folder):
            continue
        try:
            files = sorted(os.listdir(folder))
        except OSError:
            continue
        for fn in files:
            if fn.lower().endswith('.urdf'):
                entries.append((name, os.path.join(folder, fn)))
                break
    return entries


class URDFPicker(Popup):
    """选择机器人文件夹;确定后回调 on_select(.urdf 路径)。"""

    def __init__(self, on_select, **kwargs):
        self.on_select = on_select
        self._selected = None
        self._buttons = []

        content = BoxLayout(orientation='vertical',
                            padding=theme.PANEL_BORDER,
                            spacing=theme.PANEL_SEPARATOR)

        list_box = BoxLayout(orientation='vertical',
                             size_hint_y=None, spacing=4)
        list_box.bind(minimum_height=list_box.setter('height'))
        for name, urdf_path in _scan():
            # 行按钮用比面板底稍亮的输入底色,否则扁平 COLORT_BUTTON
            # 和面板同色看不见
            btn = Button(text=name, size_hint_y=None, height=44,
                         font_size=theme.FONT_SIZE_P,
                         halign='left', padding=(16, 0),
                         background_color=theme.COLOR_INPUT_BG)
            btn.urdf_path = urdf_path
            btn.bind(on_release=self._on_pick)
            list_box.add_widget(btn)
            self._buttons.append(btn)
        scroll = ScrollView()
        scroll.add_widget(list_box)
        content.add_widget(scroll)

        row = BoxLayout(size_hint_y=None, height=48,
                        spacing=theme.PANEL_SEPARATOR)
        cancel = Button(text='取消', font_size=theme.FONT_SIZE_P)
        cancel.bind(on_release=self.dismiss)
        open_btn = Button(text='打开', font_size=theme.FONT_SIZE_P)
        open_btn.bind(on_release=self._on_open)
        row.add_widget(cancel)
        row.add_widget(open_btn)
        content.add_widget(row)

        # 本机默认主题的 Popup 背景纹理不渲染(与默认 Slider 轨道同类),
        # 关掉后自绘:深海军蓝圆角底 + 1px 边框,与面板观感一致。
        # 注意 background='' 只清纹理,默认样式的 Color(background_color)
        # 仍会把无纹理的 BorderImage 画成白色实心块,必须连色一起置透明
        # 标题默认深色字,在深蓝底上看不见 → 改正文浅灰
        super().__init__(title='选择机器人文件夹', content=content,
                         size_hint=(0.55, 0.65), background='',
                         background_color=(0, 0, 0, 0),
                         title_color=theme.COLOR_TEXT,
                         # 默认样式在标题下画 1dp 分隔线,默认色是 Kivy
                         # 天蓝(47,167,212),在深蓝底上很扎眼 → 改边框灰
                         separator_color=theme.COLOR_PANEL_BORDER, **kwargs)
        # 自绘背景画在内层 GridLayout(样式规则里包住标题+内容的
        # 容器,即 _container.parent)的 canvas.before:画在 ModalView
        # 全窗遮罩之后、标题和内容之前。
        # 两个不能走的路:① 弹窗自己的 canvas.before——style.kv 的
        # <ModalView> 规则在 canvas 主组画了覆盖全窗口的暗色遮罩,
        # before 组会被它乘暗(实测底色只剩 ~30% 强度);② 追加到弹窗
        # 自己的 canvas 主组——实测会导致所有子控件不渲染(标题/行
        # 按钮全部消失,疑似本机构建的渲染序问题)。
        inner = self._container.parent
        with inner.canvas.before:
            # 描边环留 2px:RoundedRectangle 的抗锯齿羽毛会向形状外
            # 渗出 ~1px,内缩 1px 的环会被羽毛盖掉大半
            Color(*theme.COLOR_PANEL_BORDER)
            self._bg_out = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[10])
            Color(*theme.COLOR_PANEL)
            self._bg_in = RoundedRectangle(
                pos=(self.x + 2, self.y + 2),
                size=(self.width - 4, self.height - 4), radius=[8])
        self.bind(pos=self._sync_bg, size=self._sync_bg)

    def _sync_bg(self, *_):
        self._bg_out.pos = self.pos
        self._bg_out.size = self.size
        self._bg_in.pos = (self.x + 2, self.y + 2)
        self._bg_in.size = (self.width - 4, self.height - 4)

    def _on_pick(self, btn):
        """选中一行:主题蓝高亮,其余还原输入底色。"""
        for b in self._buttons:
            b.background_color = theme.COLOR_INPUT_BG
        btn.background_color = theme.COLOR_ACCENT
        self._selected = btn

    def _on_open(self, *_):
        if self._selected is not None:
            path = self._selected.urdf_path
            self.dismiss()
            self.on_select(path)
