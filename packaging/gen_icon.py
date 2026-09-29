#!/usr/bin/env python3
"""生成 Omni 应用图标(占位版):深海军蓝圆角底 + 机器人头像,配色取 theme.py。

用法(conda 环境 omni,项目根目录):
    python packaging/gen_icon.py

以后有正式 logo 时直接替换 packaging/debian/usr/share/icons/.../omni.png 即可,
本脚本不用再跑。
"""

from PIL import Image, ImageDraw

S = 256
NAVY = (9, 31, 57, 255)            # theme.COLOR_BUTTON
STEEL = (200, 208, 216, 255)       # 浅钢灰(头像本体)
ACCENT = (51, 140, 242, 255)       # theme.COLOR_ACCENT

img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 圆角方块底(应用主题深海军蓝)
d.rounded_rectangle((4, 4, S - 4, S - 4), radius=52, fill=NAVY)

# 天线
d.line((128, 74, 128, 34), fill=STEEL, width=8)
d.ellipse((114, 18, 142, 46), fill=ACCENT)

# 头
d.rounded_rectangle((70, 62, 186, 168), radius=26, fill=STEEL)

# 眼睛(主色蓝)
d.ellipse((100, 98, 128, 126), fill=ACCENT)
d.ellipse((140, 98, 168, 126), fill=ACCENT)

# 嘴
d.rounded_rectangle((104, 136, 152, 144), radius=4, fill=NAVY)

# 身子(底座) + 呼吸灯
d.rounded_rectangle((96, 172, 160, 216), radius=14, fill=STEEL)
d.ellipse((116, 184, 140, 208), fill=ACCENT)

out = 'packaging/debian/usr/share/icons/hicolor/256x256/apps/omni.png'
import os
os.makedirs(os.path.dirname(out), exist_ok=True)
img.save(out)
print(f'icon saved: {out}')
