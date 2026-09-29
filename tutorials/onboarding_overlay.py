"""新手引导浮层:半透明遮罩 + 目标控件高亮 + 步骤说明卡片。

参考 ReachControl 的 onboarding overlay:首启动全屏引导,
完成或跳过后写 config 不再自动弹出。
"""

import json
import os

from kivy.core.window import Window
from kivy.graphics import Color, Line, Rectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.widget import Widget

import theme

STEPS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'steps.json')


def load_steps(path=STEPS_PATH):
    with open(path, encoding='utf-8') as f:
        return json.load(f)['steps']


class OnboardingOverlay(Widget):
    """全屏引导浮层;target_getter(id) 返回目标 widget 或 None。"""

    def __init__(self, steps, target_getter, on_finish, on_step=None, **kwargs):
        super().__init__(**kwargs)
        self.steps = steps
        self.target_getter = target_getter
        self.on_finish = on_finish
        self.on_step = on_step
        self.index = 0

        self.size = Window.size
        Window.bind(size=self._on_win_size)

        # 遮罩 + 高亮框
        with self.canvas:
            Color(0, 0, 0, 0.55)
            self._mask = Rectangle(pos=self.pos, size=self.size)
            Color(*theme.COLOR_ACCENT, a=0.9)
            self._hl_lines = [
                Line(width=2), Line(width=2), Line(width=2), Line(width=2)]
        self.bind(pos=self._upd_mask, size=self._upd_mask)

        # 底部说明卡片
        self._card = BoxLayout(
            orientation='vertical', size_hint=(None, None),
            width=min(560, Window.width - 40), height=190,
            padding=16, spacing=8)
        self._card.bind(
            pos=lambda *_: self._upd_mask(),
            size=lambda *_: self._upd_mask())
        with self._card.canvas.before:
            Color(*theme.COLOR_PANEL)
            self._card_bg = Rectangle(pos=self._card.pos, size=self._card.size)
        self._title = Label(text='', bold=True,
                            font_size=theme.FONT_SIZE_H2,
                            color=theme.COLOR_ACCENT, size_hint_y=0.3)
        self._text = Label(text='', font_size=theme.FONT_SIZE_P,
                           color=theme.COLOR_TEXT, size_hint_y=0.7,
                           halign='left', valign='top')
        self._card.add_widget(self._title)
        self._card.add_widget(self._text)
        self.add_widget(self._card)

        self._btn_next = Button(text='下一步', size_hint=(None, None),
                                size=(140, 44))
        self._btn_next.bind(on_release=self._on_next)
        self._btn_skip = Button(text='跳过教程', size_hint=(None, None),
                                size=(140, 44))
        self._btn_skip.bind(on_release=self._on_skip)
        self.add_widget(self._btn_next)
        self.add_widget(self._btn_skip)

        self._layout()
        self._update_step()

    # ---- 布局 ----

    def _on_win_size(self, _, size):
        self.size = size
        self._layout()

    def _layout(self):
        w, h = self.size
        self._card.pos = (w / 2 - self._card.width / 2, 24)
        self._btn_skip.pos = (w - 160, 24 + self._card.height - 56)
        self._btn_next.pos = (w - 320, 24 + self._card.height - 56)

    def _upd_mask(self, *_):
        self._mask.pos = self.pos
        self._mask.size = self.size
        self._card_bg.pos = self._card.pos
        self._card_bg.size = self._card.size

    # ---- 步骤 ----

    def _update_step(self):
        step = self.steps[self.index]
        self._title.text = f'{self.index + 1}/{len(self.steps)}  {step["title"]}'
        self._text.text = step['text']
        self._btn_next.text = ('完成' if self.index == len(self.steps) - 1
                               else '下一步')
        if self.on_step:
            self.on_step(step.get('target'))
        self._draw_highlight(step.get('target'))

    def _draw_highlight(self, target_id):
        """在目标控件周围画高亮框;找不到目标时隐藏。"""
        target = self.target_getter(target_id) if target_id else None
        for line in self._hl_lines:
            line.points = []
        if target is None:
            return
        x, y = target.to_window(0, 0)
        w, h = target.size
        pad = 4
        x, y = x - pad, y - pad
        w, h = w + pad * 2, h + pad * 2
        self._hl_lines[0].points = [x, y, x + w, y]
        self._hl_lines[1].points = [x + w, y, x + w, y + h]
        self._hl_lines[2].points = [x + w, y + h, x, y + h]
        self._hl_lines[3].points = [x, y + h, x, y]

    def _on_next(self, *_):
        if self.index >= len(self.steps) - 1:
            self._finish()
        else:
            self.index += 1
            self._update_step()

    def _on_skip(self, *_):
        self._finish()

    def _finish(self):
        Window.unbind(size=self._on_win_size)
        parent = self.parent
        if parent is not None:
            parent.remove_widget(self)
        if self.on_finish:
            self.on_finish()
