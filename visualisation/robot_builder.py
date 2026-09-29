"""URDF → GPU 网格列表(数据驱动,不使用 Kivy 指令图)。

每个 link 的每个 visual 生成一个 MeshBuffer + 其 link 系变换矩阵;
每帧按 parser 的 absolute_transform(随关节状态重算)绘制。
"""

import os

from . import mesh_factory
from .urdf_parser import create_transform_matrix


def resolve_mesh_path(urdf_dir, filename):
    """把 URDF 里的网格路径解析成真实文件路径。

    支持 './meshes/x.stl'、绝对路径、'package://pkg/models/x.stl'
    (参照 ReachControl 用 catkin_pkg 解析 package:// 的思路,
    这里做简化版:去掉包名前缀,在 urdf_dir 下找)。
    """
    f = filename
    if f.startswith('package://'):
        parts = f[len('package://'):].split('/')
        f = '/'.join(parts[1:]) if len(parts) > 1 else f
    if os.path.isabs(f):
        return f
    return os.path.normpath(os.path.join(urdf_dir, f))


class RobotScene:
    """管理机器人 GPU 网格与运行时关节状态。"""

    def __init__(self, parser, urdf_dir, renderer):
        self.parser = parser
        self.urdf_dir = urdf_dir
        self.renderer = renderer
        self._visual_meshes = []   # [(link_name, MeshBuffer, local 4x4)]
        self._build()

    # ---- 场景构建 ----

    def _build(self):
        for link_name, link_data in self.parser.links.items():
            for visual in link_data['visual']:
                verts, norms, colors, indices = self._load_geometry(visual)
                if verts is None:
                    continue
                buf = self.renderer.upload_mesh(verts, norms, colors, indices)
                local = create_transform_matrix(visual['origin_xyz'],
                                                visual['origin_rpy'])
                self._visual_meshes.append((link_name, buf, local))

    def _load_geometry(self, elem):
        """按几何类型生成网格数组;失败返回 (None,)*4(跳过)。"""
        geo = elem.get('geometry_type')
        data = elem.get('geometry_data', {})
        color = elem.get('color', (0.5, 0.5, 0.5, 1.0))
        try:
            if geo == 'mesh':
                path = resolve_mesh_path(self.urdf_dir, data['filename'])
                if not os.path.exists(path):
                    print(f"Warning: mesh not found: {data['filename']}")
                    return None, None, None, None
                return mesh_factory.load_stl(path, scale=data.get('scale', (1, 1, 1)), color=color)
            elif geo == 'box':
                return mesh_factory.make_box(data['size'], color)
            elif geo == 'cylinder':
                return mesh_factory.make_cylinder(data['radius'], data['length'], color)
            elif geo == 'sphere':
                return mesh_factory.make_sphere(data['radius'], color)
        except Exception as e:
            print(f"Warning: failed to load {geo}: {e}")
        return None, None, None, None

    # ---- 每帧绘制 ----

    def draw(self):
        """按当前关节状态绘制所有网格。"""
        for link_name, buf, local in self._visual_meshes:
            world = self.parser.tf_nodes[link_name].absolute_transform
            self.renderer.draw_mesh(buf, world @ local)

    # ---- 关节更新 ----

    def set_joint_angle(self, joint_name, angle_rad):
        """更新关节角并重算全树世界矩阵。"""
        self.parser.update_joint_angle(joint_name, angle_rad)

    def reset_joints(self):
        # 复位到 URDF 加载时的默认位;不用限位中点(夹爪限位不对称,
        # 中点会把闭合的夹爪拉到半开,见 ui/joint_panel.py _on_reset)
        for jn, limits in self.parser.joint_limits.items():
            self.set_joint_angle(jn, limits.get('position', 0.0))
