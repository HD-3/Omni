"""集中式设计体系:字号分级、间距、配色常量。

模仿 ReachControl 的做法(bpstyle_viewer.kv 中集中定义 FONT_SIZE_* / PANEL_*),
所有 kv 文件与代码统一从这里取常量,改主题只需改这一个文件。
"""

# ---- 字号分级 ----
# 中文笔画密度高,同字号下比英文(如 ReachControl 的 Roboto)显糊;
# 小字号在 CFF 字体(思源黑体)下细节丢失,整体上调一档
FONT_SIZE_H1 = 28
FONT_SIZE_H2 = 22
FONT_SIZE_P = 18
FONT_SIZE_SUB = 16
FONT_SIZE_HELP = 14

# ---- 间距/尺寸 ----
PANEL_BORDER = 12
PANEL_SEPARATOR = 8
HUD_LEFT_WIDTH = 280
HUD_TOP_HEIGHT = 56
HUD_TOP_OFFSET = 5    # 顶栏距窗口顶部的留白

# ---- 配色(HUD 深海军蓝系,同 ReachControl 的 bpstyle.kv)----
COLOR_BG = (0.10, 0.11, 0.13, 1)            # 主背景
COLOR_VIEWPORT_BG = (0.0706, 0.2235, 0.3765, 1)  # 3D 视口背景(同 ReachControl 的 BACKGROUND_COLOUR,RGB 18,57,96)
COLOR_PANEL = (9/255, 31/255, 57/255, 0.92) # 面板底(同 RC RR_NAVY_90 深海军蓝)
COLOR_PANEL_BORDER = (143/255, 153/255, 165/255, 1)  # 边框(同 RC LIGHT_BLUE_GRAY)
COLOR_BUTTON = (9/255, 31/255, 57/255, 1)   # 按钮实色(同 RC RR_NAVY_OPAQUE)
COLOR_TOPBAR_BTN = (5/255, 18/255, 34/255, 1)  # 顶栏按钮:比面板底更深一档的实色
COLOR_INPUT_BG = (0.14, 0.19, 0.29, 1)      # 输入框底色(比面板底稍亮,内凹感)
COLOR_TEXT = (0.76, 0.77, 0.78, 1)          # 正文(同 RC TEXT_GRAY)
COLOR_TEXT_DIM = (143/255, 153/255, 165/255, 1)  # 次级文字(同 RC LIGHT_BLUE_GRAY)
COLOR_ACCENT = (0.20, 0.55, 0.95, 1)        # 主色(蓝)
COLOR_ACCENT_DARK = (0.13, 0.40, 0.75, 1)
COLOR_WARN = (0.95, 0.55, 0.20, 1)
COLOR_DANGER = (0.90, 0.25, 0.25, 1)
COLOR_OK = (0.30, 0.75, 0.40, 1)

# ---- 步进按钮(+/- 号,天蓝圆角框)----
COLOR_SKY = (135/255, 206/255, 235/255, 1)          # 天蓝填充(RGB 135,206,235)
COLOR_SKY_PRESSED = (100/255, 180/255, 215/255, 1)  # 按下加深
COLOR_SKY_BORDER = (75/255, 150/255, 190/255, 1)    # 描边(比填充深一档)
COLOR_SKY_DISABLED = (0.33, 0.38, 0.45, 1)          # 禁用灰蓝(比面板底亮,按钮轮廓仍可辨)

# ---- 3D 场景 ----
GRID_COLOR = (0.19, 0.31, 0.45, 1)   # 淡网格(同 ReachControl 截图取色,几乎融入背景)
GRID_SPACING = 0.1        # 米
GRID_SIZE = 3.0           # 半边长(米)
AXIS_LENGTH = 0.25        # 坐标轴长度(米)
LIGHT_POS = (5.0, 5.0, 10.0)     # 世界系主光位置(同 ReachControl 高位光)
LIGHT_POS2 = (-5.0, -5.0, 10.0)  # 世界系补光位置(与主光对称,照亮背光面)
LIGHT_INTENSITY = 1.0    # 主光强度
SPECULAR_POWER = 10.0    # 镜面高光锐度(同 ReachControl 的 shininess 默认值)
KA = 0.30                # 环境光系数(同 ReachControl 的 0.3)
