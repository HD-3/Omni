"""全局配置读写(~/.omni/config.json)。

参考 ReachControl 用 jsonpickle 持久化配置的做法,我们用标准 json,
保持零额外依赖。
"""

import json
import os

CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.omni')
CONFIG_PATH = os.path.join(CONFIG_DIR, 'config.json')

_DEFAULTS = {
    'tutorial_completed': False,
    'last_urdf': None,
    # 实物开发板(可选):配了 link_host 才启用板连接
    # 注意:运行时配置在 ~/.omni/config.json,这里只是默认值,别改这里
    'link_host': None,
    'link_port': 8765,
}


def load_config():
    """读取配置,不存在或损坏时返回默认值。"""
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return dict(_DEFAULTS)
    cfg = dict(_DEFAULTS)
    cfg.update(data)
    return cfg


def save_config(cfg):
    """写回配置,自动创建目录。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
