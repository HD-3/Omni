#!/usr/bin/env python3
"""Omni —— Kivy 机器人可视化软件(架构模仿 ReachControl)。

用法:
    python main.py [urdf路径] [--screenshot out.png]
无参数时打开内置机器人模型;--screenshot 用于自动截图后退出(验证用)。
"""

import os
import sys

os.environ.setdefault('KIVY_NO_ARGS', '1')  # 禁用 Kivy 参数解析,用我们自己的 CLI

# 3D 渲染需要深度缓冲(Kivy 默认关闭),必须在 Window 创建前设置
from kivy.config import Config
Config.set('graphics', 'depthbuffer', 1)
# 窗口级 MSAA 提到驱动上限 4x:顶栏圆角框、文字等 2D UI 边缘整体更平滑
Config.set('graphics', 'multisamples', 4)
# 禁用右键的多点触控模拟:否则右键按下/松开会画一个红色触点圆点,
# 且右键触点不随松开结束,红点会一直留在窗口里。
Config.set('input', 'mouse', 'mouse,disable_multitouch')

# PyInstaller 冻结打包时资源在 sys._MEIPASS(onedir 的 _internal 目录)
PROJECT_ROOT = (getattr(sys, '_MEIPASS')
                if getattr(sys, 'frozen', False)
                else os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 自带剪贴板工具:系统未装 xclip/xsel 时,Kivy 的剪贴板探测会打
# CRITICAL + FileNotFoundError 回溯且输入框复制/粘贴失效。把项目
# tools/ 里的二进制加入 PATH(源码运行与打包版 _internal 都随
# PROJECT_ROOT 走),Kivy 的 subprocess 探测即可找到;datas 拷贝
# 可能丢失执行位,每次启动补一次 chmod。
_TOOLS_DIR = os.path.join(PROJECT_ROOT, 'tools')
if os.path.isdir(_TOOLS_DIR):
    for _tool in ('xclip', 'xsel'):
        _tool_path = os.path.join(_TOOLS_DIR, _tool)
        if os.path.exists(_tool_path):
            try:
                os.chmod(_tool_path, 0o755)
            except OSError:
                pass
    os.environ['PATH'] = _TOOLS_DIR + os.pathsep + os.environ.get('PATH', '')

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import BooleanProperty
from kivy.uix.floatlayout import FloatLayout

# Kivy 默认字体 Roboto 不含中文字形,中文全部渲染成实心块(tofu);
# 用项目内置的 Noto Sans CJK SC 覆盖 Roboto 注册,中英文统一渲染
LabelBase.register(
    name='Roboto',
    fn_regular=os.path.join(PROJECT_ROOT, 'visualisation', 'assets', 'fonts',
                            'NotoSansCJKsc-Regular.otf'),
    fn_bold=os.path.join(PROJECT_ROOT, 'visualisation', 'assets', 'fonts',
                        'NotoSansCJKsc-Bold.otf'),
)

import config
import robot_link
import theme
from filedialog.urdf_picker import URDFPicker
from tutorials.onboarding_overlay import OnboardingOverlay, load_steps
from ui.connect_panel import ConnectPanel  # noqa: F401 (kv 注册)
from ui.joint_panel import JointPanel
from visualisation.urdf_parser import URDFParser
from visualisation.viewport3d import Viewport3D

DEFAULT_URDF = os.path.join(PROJECT_ROOT, 'visualisation', 'assets',
                            'urdfs', 's5', 's5v2-urdf.urdf')


class OmniRoot(FloatLayout):
    """根布局:3D 视口占满窗口;HUD 浮在 3D 之上,左栏默认折叠。"""

    panel_open = BooleanProperty(False)

    def __init__(self, urdf_file, **kwargs):
        super().__init__(**kwargs)
        self.urdf_file = urdf_file
        self.link = None   # 实物开发板链路;未配置时保持本地模式
        self.control_mode = 'pc'   # 控制权:pc 听 PC / board 听板侧(PC 只显示)
        self._send_pending = False   # 发送合并:一帧内多次关节变化只发一条全量
        self._topbar_visible = False   # 顶栏默认隐藏,鼠标移到窗口顶部条带才滑出

        self.parser = URDFParser()
        self.parser.parse_urdf(urdf_file)
        urdf_dir = os.path.dirname(urdf_file)

        viewport = self.ids.viewport
        viewport.load_robot(self.parser, urdf_dir)
        # 点击 3D 视口(非滚轮)折叠展开的侧边栏,回到全屏
        viewport.on_viewport_click = self._close_panel
        self.ids.joint_panel.setup(self.parser.joint_limits, self._on_joint_changed)
        self.ids.joint_panel.on_mode_toggle = self._toggle_control_mode

        # 板连接面板:手动输入 IP/端口,预填上次成功连接的地址,不自动连接
        cfg = config.load_config()
        panel = self.ids.connect_panel
        panel.on_connect = self._connect_from_panel
        panel.on_disconnect = self._disconnect_board
        panel.set_prefill(cfg.get('link_host'), cfg.get('link_port') or 8765)

        self._update_status()
        # 侧边栏切换:顶栏按钮选择显示关节控制或障碍物控制
        self._active_panel = 'joints'
        self._update_panel_buttons()
        # 侧边栏默认折叠、顶栏默认隐藏(都移到窗口外);布局完成后设置初始位置
        Clock.schedule_once(self._init_panel_pos, 0)
        # 顶栏自动隐藏:鼠标进入窗口顶部条带滑出,离开后收回
        Window.bind(mouse_pos=self._on_topbar_mouse)
        # 顶栏位置用高度绑定同步(不用 kv pos 规则):窗口挂载时 root
        # 高度 100→800 变化,kv 绑定会重新触发把初始隐藏位覆盖成显示位;
        # 高度绑定按 _topbar_visible 状态重算,初始必然是隐藏位
        self.bind(height=self._sync_topbar_pos)
        self._sync_topbar_pos()
        # 新手引导:首启动显示,完成后写 config
        if not cfg.get('tutorial_completed'):
            Clock.schedule_once(self._show_tutorial, 0.8)

    def _init_panel_pos(self, *_):
        """初始:两个侧边栏都在窗口外(顶栏隐藏位见 _sync_topbar_pos)。

        注意要多退 10px:只退 bar.width 时侧边栏右边缘正好压在
        窗口左缘 x=0,边框线的抗锯齿半像素会漏进窗口,在窗口
        左边形成一条 1px 竖线。顶栏同理,底部边缘不能压在
        窗口上缘。
        """
        for bar in (self.ids.joint_sidebar, self.ids.connect_sidebar):
            bar.x = -bar.width - 10

    def _open_panel(self, name):
        """打开指定侧边栏,顶栏按钮高亮同步。"""
        self._active_panel = name
        self.panel_open = True
        self._update_panel_buttons()
        self._sync_sidebars()
        # 侧边栏展开期间顶栏恒显示(不随鼠标隐藏)
        self._set_topbar_visible(True)

    def _show_panel(self, name):
        """顶栏按钮:再点当前面板按钮折叠,否则打开对应侧边栏。"""
        if self._active_panel == name and self.panel_open:
            self._close_panel()
        else:
            self._open_panel(name)

    def _close_panel(self):
        """折叠当前侧边栏(顶栏按钮再点 / 点击 3D 视口都会走到这)。

        面板折叠后顶栏显隐回到鼠标规则,按当前鼠标位置重新判定:
        点击视口时鼠标必然在视口内(顶部条带外),顶栏随即收回,全屏。
        """
        if not self.panel_open:
            return
        self.panel_open = False
        self._update_panel_buttons()
        self._sync_sidebars()
        self._set_topbar_visible(self._topbar_keep(Window.mouse_pos))

    def _sync_sidebars(self):
        """两个侧边栏就位:选中的滑入(留左边距),另一个滑到窗口外。"""
        for name, bar in (('joints', self.ids.joint_sidebar),
                          ('connect', self.ids.connect_sidebar)):
            visible = self.panel_open and self._active_panel == name
            # 隐藏位同样多退 10px,见 _init_panel_pos 的说明
            Animation(x=theme.HUD_TOP_OFFSET if visible else -bar.width - 10,
                      duration=0.25, t='out_quad').start(bar)

    # ---- 顶栏自动隐藏 ----

    def _sync_topbar_pos(self, *_):
        """按当前状态同步顶栏位置(绑定 root.height,窗口挂载时触发)。

        初始在 __init__ 末尾调用一次兜底;挂载后高度 100→800 变化
        再触发,把隐藏位按最终窗口高度重算,保证启动即隐藏。
        """
        bar = self.ids.top_bar
        bar.x = theme.HUD_TOP_OFFSET
        bar.y = (self.height - bar.height - theme.HUD_TOP_OFFSET
                 if self._topbar_visible else self.height + 10)

    def _on_topbar_mouse(self, *args):
        """顶栏显隐联动(Window.bind(mouse_pos=...) 回调传入 (window, pos))。"""
        self._set_topbar_visible(self._topbar_keep(args[1]))

    def _topbar_keep(self, pos):
        """顶栏保持显示的条件:任一侧边栏展开恒真;都折叠时仅鼠标在顶部条带。"""
        if self.panel_open:
            return True
        strip_h = theme.HUD_TOP_HEIGHT + theme.HUD_TOP_OFFSET * 2
        return pos[1] >= self.height - strip_h

    def _set_topbar_visible(self, visible):
        """顶栏滑出/收回;隐藏位多退 10px,防边框抗锯齿漏进窗口。"""
        if visible == self._topbar_visible:
            return
        self._topbar_visible = visible
        bar = self.ids.top_bar
        Animation.stop_all(bar, 'y')
        y = (self.height - bar.height - theme.HUD_TOP_OFFSET
             if visible else self.height + 10)
        Animation(y=y, duration=0.2, t='out_quad').start(bar)

    def _update_panel_buttons(self):
        """顶栏按钮高亮当前选中的面板;折叠时不亮。"""
        for name, btn in (('joints', self.ids.joints_btn),
                          ('connect', self.ids.connect_btn)):
            active = self.panel_open and self._active_panel == name
            btn.background_color = (theme.COLOR_ACCENT_DARK if active
                                    else theme.COLOR_TOPBAR_BTN)

    def _show_tutorial(self, *_):
        # 引导步骤指向左栏面板,先把面板展开(并切到第一步的面板)
        self._open_panel('joints')
        steps = load_steps()
        overlay = OnboardingOverlay(
            steps=steps,
            target_getter=lambda tid: self.ids.get(tid),
            on_finish=self._tutorial_done,
            on_step=self._tutorial_step,
        )
        Window.add_widget(overlay)

    def _tutorial_step(self, target_id):
        # 引导指向的面板先切出来,否则高亮框落在隐藏面板上
        if target_id == 'joint_panel':
            self._open_panel('joints')

    def _tutorial_done(self):
        cfg = config.load_config()
        cfg['tutorial_completed'] = True
        config.save_config(cfg)

    # ---- URDF 加载 ----

    def _pick_urdf(self):
        URDFPicker(on_select=self._load_urdf).open()

    def _load_urdf(self, path):
        """加载新 URDF:重解析 + 重建场景 + 重填关节面板。"""
        try:
            parser = URDFParser()
            parser.parse_urdf(path)
        except Exception as e:
            print(f'Error: failed to parse URDF: {e}')
            return

        self.parser = parser
        self.urdf_file = path   # 顶栏板状态要显示当前机器人名称
        urdf_dir = os.path.dirname(path)
        self.ids.viewport.load_robot(parser, urdf_dir)
        self.ids.joint_panel.setup(parser.joint_limits, self._on_joint_changed)

        cfg = config.load_config()
        cfg['last_urdf'] = path
        config.save_config(cfg)
        self._update_status()

    def _on_joint_changed(self, joint_name, angle):
        scene = self.ids.viewport.scene
        if scene is not None:
            scene.set_joint_angle(joint_name, angle)
        self.ids.joint_panel.update_label(joint_name, angle)
        # 合并行(夹爪)一次拖动会连续回调两个关节,逐条发会先发出
        # "GL 已更新、GR 还是旧值"的中间态;按帧合并,只发最终全量
        if not self._send_pending:
            self._send_pending = True
            Clock.schedule_once(self._flush_send, 0)
        self._update_status()

    def _flush_send(self, *_):
        """把本帧内所有关节变化合并成一条全量命令。"""
        self._send_pending = False
        if self.link is not None and self.control_mode == 'pc':
            self.link.send_all(self._current_angles())

    # ---- 实物开发板链路 ----

    def connect_board(self, host, port=8765):
        """连接实物开发板(JSON over TCP),断线自动重连。"""
        self.link = robot_link.RobotLink(
            host, port,
            on_state=self._on_board_state,
            on_status=self._on_link_status)
        self.link.send_mode(self.control_mode)  # 未连上时由链路连接后补发
        self._update_status()
        # 兜底:后台线程的连接回调排 Clock 事件在启动阶段可能被拖慢,
        # 2s 后主线程再刷一次,保证顶栏状态与面板提示最终正确
        link = self.link
        Clock.schedule_once(lambda dt: self._sync_link_ui(link.connected), 2.0)

    def _toggle_control_mode(self):
        """控制权切换:PC ↔ 板。board 模式下面板只读,纯显示板回读。

        真正的仲裁在板桥:它按 mode 只放行一个命令来源;PC 侧
        这里只做本地锁(不发命令)并通知板。
        """
        self.control_mode = 'board' if self.control_mode == 'pc' else 'pc'
        self.ids.joint_panel.set_control_mode(self.control_mode)
        if self.link is not None:
            self.link.send_mode(self.control_mode)

    def _on_link_status(self, connected):
        # 链路后台线程回调 → 转 Kivy 主线程刷新顶栏状态与面板提示
        Clock.schedule_once(lambda dt: self._sync_link_ui(connected))

    def _sync_link_ui(self, connected):
        self._update_status()
        self.ids.connect_panel.set_status(connected)

    def _connect_from_panel(self, host, port):
        """连接面板回调:建立链路并记住本次地址(下次启动预填)。"""
        if self.link is not None:
            return
        self.connect_board(host, port)
        self.ids.connect_panel.set_state(True)
        cfg = config.load_config()
        cfg['link_host'] = host
        cfg['link_port'] = port
        config.save_config(cfg)

    def _disconnect_board(self):
        """断开当前链路;RobotLink.close 是一次性的,下次连接须新建。"""
        if self.link is None:
            return
        self.link.close()
        self.link = None
        self.ids.connect_panel.set_state(False)
        self._update_status()

    def _on_board_state(self, states):
        # 链路后台线程回调 → 转 Kivy 主线程应用回读
        Clock.schedule_once(lambda dt: self._apply_board_state(states))

    def _apply_board_state(self, states):
        """板回读(弧度)同步场景与滑块;正被拖动的关节跳过。"""
        scene = self.ids.viewport.scene
        panel = self.ids.joint_panel
        for jn, rad in states.items():
            if jn not in self.parser.joint_limits:
                continue
            if not isinstance(rad, (int, float)):
                continue
            if panel.is_dragging(jn):
                continue
            # 钳位到限位内:真硬件过冲/异常回读不能污染场景和回传命令
            limits = self.parser.joint_limits[jn]
            rad = min(max(rad, limits['lower']), limits['upper'])
            if scene is not None:
                scene.set_joint_angle(jn, rad)
            panel.set_slider_feedback(jn, rad)

    def _current_angles(self):
        """全部可控关节当前角(弧度),发全量让板侧无状态应用。"""
        return {jn: self.parser.tf_nodes[self.parser.joints[jn]['child']].current_angle
                for jn in self.parser.joint_limits}

    def _robot_name(self):
        """当前机器人的短名称:内置模型取资产目录名(s7/s5)。"""
        path = getattr(self, 'urdf_file', None) or ''
        return os.path.basename(os.path.dirname(path)) or 'robot'

    def _update_status(self):
        # 顶栏显示板连接状态:未连接 / 机器人名 · IP
        if self.link is not None and self.link.connected:
            self.ids.status.text = f'{self._robot_name()} · {self.link.host}'
        else:
            self.ids.status.text = '未连接'


class OmniApp(App):
    title = 'Omni'

    def __init__(self, urdf_file=None, screenshot_path=None, **kwargs):
        super().__init__(**kwargs)
        self.urdf_file = urdf_file or DEFAULT_URDF
        self.screenshot_path = screenshot_path

    def on_stop(self):
        # 退出时关掉板链路(后台线程随进程退出,这里保证干净关闭)
        root = self.root
        if isinstance(root, OmniRoot) and root.link is not None:
            root.link.close()

    def load_kv(self, filename=None):
        # 不用 App 自动查找 kv(打包后会找到 _MEIPASS 里的副本,与
        # build() 的显式加载重复 → 规则应用两次 → 部件树重复);
        # kv 统一由 build() 按 PROJECT_ROOT 显式加载。
        pass

    def build(self):
        Builder.load_file(os.path.join(PROJECT_ROOT, 'omni.kv'))
        Window.clearcolor = theme.COLOR_BG
        # 窗口 1280x800;3D 以 2x 超采样渲染(见 viewport3d.SSAA),
        # 像素量不随窗口缩小而降低
        Window.size = (1280, 800)
        root = OmniRoot(self.urdf_file)
        if self.screenshot_path:
            Clock.schedule_once(self._take_screenshot, 6.0)
        return root

    def _take_screenshot(self, *_):
        """自写截图:glReadPixels + PIL 保存。

        不用 Window.screenshot:Kivy 2.3 的截图函数有行对齐 bug
        (GL_RGB 每行字节数不是 4 的倍数时,GL 补的 padding 会让颜色
        通道逐行错位),且它总是把文件名改写成 base{:04d}.png,
        传入的精确文件名从不使用。
        """
        try:
            from PIL import Image
            from kivy.graphics import opengl as gl
            w, h = Window.size
            gl.glPixelStorei(gl.GL_PACK_ALIGNMENT, 1)
            data = gl.glReadPixels(0, 0, w, h, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
            # 本环境 glReadPixels 第 0 行即窗口底部(实测:不翻转时
            # 顶栏出现在截图底部),PIL 数值验证按 img_y = win_y 换算
            img = Image.frombytes('RGB', (w, h), data)
            img.save(self.screenshot_path)
            print(f"screenshot saved: {self.screenshot_path}")
        except Exception as e:
            print(f"screenshot failed: {e}")
        self.stop()


def main():
    args = [a for a in sys.argv[1:]]
    screenshot_path = None
    if '--screenshot' in args:
        i = args.index('--screenshot')
        screenshot_path = args[i + 1] if i + 1 < len(args) else 'omni.png'
        del args[i:i + 2]
    urdf_file = args[0] if args else None
    if urdf_file is None:
        # 无命令行参数:优先上次打开的文件
        urdf_file = config.load_config().get('last_urdf')
    if urdf_file and not os.path.exists(urdf_file):
        print(f"Warning: URDF file does not exist: {urdf_file}, using default")
        urdf_file = None

    OmniApp(urdf_file=urdf_file, screenshot_path=screenshot_path).run()


if __name__ == '__main__':
    main()
