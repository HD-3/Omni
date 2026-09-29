"""URDF 解析与 TF 树构建(移植自现有 PyQt 可视化器,纯 numpy/xml,无 GUI 依赖)。"""

import math
import xml.etree.ElementTree as ET

import numpy as np


def create_transform_matrix(translation, rpy):
    """Create a 4x4 transformation matrix from translation and RPY rotation"""
    x, y, z = translation
    roll, pitch, yaw = rpy

    # Rotation matrix from RPY
    cos_r, sin_r = math.cos(roll), math.sin(roll)
    cos_p, sin_p = math.cos(pitch), math.sin(pitch)
    cos_y, sin_y = math.cos(yaw), math.sin(yaw)

    # Combined rotation matrix (ZYX Euler angles)
    R = np.array([
        [cos_y*cos_p, cos_y*sin_p*sin_r - sin_y*cos_r, cos_y*sin_p*cos_r + sin_y*sin_r],
        [sin_y*cos_p, sin_y*sin_p*sin_r + cos_y*cos_r, sin_y*sin_p*cos_r - cos_y*sin_r],
        [-sin_p, cos_p*sin_r, cos_p*cos_r]
    ])

    # 4x4 transformation matrix
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = [x, y, z]

    return T


def create_rotation_transform(angle, axis):
    """Create a rotation transform around a specific axis by angle (in radians)"""
    T = np.eye(4)

    # Normalize the axis
    axis = np.array(axis)
    axis = axis / np.linalg.norm(axis)

    # Use axis-angle formula
    x, y, z = axis
    c = math.cos(angle)
    s = math.sin(angle)
    t = 1 - c

    # Rotation matrix
    R = np.array([
        [t*x*x + c,   t*x*y - z*s, t*x*z + y*s],
        [t*x*y + z*s, t*y*y + c,   t*y*z - x*s],
        [t*x*z - y*s, t*y*z + x*s, t*z*z + c  ]
    ])

    T[:3, :3] = R
    return T


class TFNode:
    """A node in the TF tree"""
    def __init__(self, name, parent=None):
        self.name = name
        self.parent = parent
        self.children = []
        self.transform = np.eye(4)  # Transform from parent to this node (static)
        self.joint_transform = np.eye(4)  # Additional transform due to joint movement
        self.absolute_transform = np.eye(4)  # Transform from world to this node
        self.joint_type = "fixed"  # Type of joint connecting to parent
        self.joint_axis = [0, 0, 1]  # Joint axis (for revolute joints)
        self.current_angle = 0.0  # Current joint angle (for revolute joints)


class URDFParser:
    def __init__(self):
        self.links = {}
        self.joints = {}
        self.materials = {}
        self.tf_nodes = {}
        self.root_link = None
        self.joint_limits = {}

    def parse_urdf(self, urdf_file):
        """Parse URDF file and build TF tree structure"""
        tree = ET.parse(urdf_file)
        root = tree.getroot()

        # Parse materials
        for material_elem in root.findall('material'):
            name = material_elem.get('name')
            color_elem = material_elem.find('color')
            if color_elem is not None:
                rgba = [float(x) for x in color_elem.get('rgba').split()]
            else:
                rgba = [0.5, 0.5, 0.5, 1.0]
            self.materials[name] = rgba

        # Parse links
        for link_elem in root.findall('link'):
            link_name = link_elem.get('name')
            link_data = {'visual': [], 'collision': []}

            # Parse visual elements
            for visual_elem in link_elem.findall('visual'):
                visual_data = self._parse_visual_element(visual_elem)
                link_data['visual'].append(visual_data)

            # Parse collision elements (for碰撞检测)
            for collision_elem in link_elem.findall('collision'):
                collision_data = self._parse_visual_element(collision_elem)
                link_data['collision'].append(collision_data)

            self.links[link_name] = link_data

        # Parse joints
        for joint_elem in root.findall('joint'):
            joint_name = joint_elem.get('name')
            joint_type = joint_elem.get('type')

            parent_elem = joint_elem.find('parent')
            child_elem = joint_elem.find('child')

            parent_link = parent_elem.get('link') if parent_elem is not None else ''
            child_link = child_elem.get('link') if child_elem is not None else ''

            origin_elem = joint_elem.find('origin')
            if origin_elem is not None:
                xyz_str = origin_elem.get('xyz', '0 0 0')
                rpy_str = origin_elem.get('rpy', '0 0 0')
                xyz = [float(x) for x in xyz_str.split()]
                rpy = [float(x) for x in rpy_str.split()]
            else:
                xyz = [0, 0, 0]
                rpy = [0, 0, 0]

            # Parse axis for revolute joints
            axis = [0, 0, 1]  # Default Z-axis
            if joint_elem.find('axis') is not None:
                axis_str = joint_elem.find('axis').get('xyz', '0 0 1')
                axis = [float(x) for x in axis_str.split()]

            # Parse limits
            lower = -math.pi  # Default limits
            upper = math.pi
            if joint_elem.find('limit') is not None:
                limit_elem = joint_elem.find('limit')
                lower = float(limit_elem.get('lower', str(-math.pi)))
                upper = float(limit_elem.get('upper', str(math.pi)))

            self.joints[joint_name] = {
                'type': joint_type,
                'parent': parent_link,
                'child': child_link,
                'origin_xyz': xyz,
                'origin_rpy': rpy,
                'axis': axis,
                'limits': {'lower': lower, 'upper': upper}
            }

        # Build TF tree
        self._build_tf_tree()

    def _parse_visual_element(self, visual_elem):
        """Parse a visual/collision element from URDF"""
        origin_elem = visual_elem.find('origin')
        if origin_elem is not None:
            xyz_str = origin_elem.get('xyz', '0 0 0')
            rpy_str = origin_elem.get('rpy', '0 0 0')
            xyz = [float(x) for x in xyz_str.split()]
            rpy = [float(x) for x in rpy_str.split()]
        else:
            xyz = [0, 0, 0]
            rpy = [0, 0, 0]

        geometry_elem = visual_elem.find('geometry')
        geometry_type = None
        geometry_data = {}

        # Check for different geometry types
        box_elem = geometry_elem.find('box')
        if box_elem is not None:
            geometry_type = 'box'
            size_str = box_elem.get('size', '1 1 1')
            size = [float(x) for x in size_str.split()]
            geometry_data = {'size': size}

        cylinder_elem = geometry_elem.find('cylinder')
        if cylinder_elem is not None:
            geometry_type = 'cylinder'
            radius = float(cylinder_elem.get('radius', '1'))
            length = float(cylinder_elem.get('length', '1'))
            geometry_data = {'radius': radius, 'length': length}

        sphere_elem = geometry_elem.find('sphere')
        if sphere_elem is not None:
            geometry_type = 'sphere'
            radius = float(sphere_elem.get('radius', '1'))
            geometry_data = {'radius': radius}

        mesh_elem = geometry_elem.find('mesh')
        if mesh_elem is not None:
            geometry_type = 'mesh'
            filename = mesh_elem.get('filename')
            scale_str = mesh_elem.get('scale', '1 1 1')
            scale = [float(x) for x in scale_str.split()]
            geometry_data = {'filename': filename, 'scale': scale}

        # Get material
        material_elem = visual_elem.find('material')
        if material_elem is not None:
            material_name = material_elem.get('name')
            if material_name and material_name in self.materials:
                color = self.materials[material_name]
            else:
                color_elem = material_elem.find('color')
                if color_elem is not None:
                    color = [float(x) for x in color_elem.get('rgba').split()]
                else:
                    color = [0.5, 0.5, 0.5, 1.0]
        else:
            color = [0.5, 0.5, 0.5, 1.0]

        return {
            'origin_xyz': xyz,
            'origin_rpy': rpy,
            'geometry_type': geometry_type,
            'geometry_data': geometry_data,
            'color': color
        }

    def _build_tf_tree(self):
        """Build the TF tree structure"""
        # Find all children for each parent
        children_map = {}
        for joint_name, joint_data in self.joints.items():
            parent = joint_data['parent']
            child = joint_data['child']

            if parent not in children_map:
                children_map[parent] = []
            children_map[parent].append((child, joint_data))

        # Find root link (has no parent)
        all_child_links = {joint['child'] for joint in self.joints.values()}

        # Special handling for dummy joint
        for joint_name, joint_data in self.joints.items():
            if joint_data['parent'] == 'dummy':
                self.root_link = joint_data['child']
                break
        else:
            # Regular method
            for link_name in self.links.keys():
                if link_name not in all_child_links:
                    self.root_link = link_name
                    break

        if self.root_link is None and self.links:
            self.root_link = next(iter(self.links.keys()))

        print(f"Root link: {self.root_link}")

        # Create TF nodes
        self.tf_nodes = {}
        for link_name in self.links.keys():
            self.tf_nodes[link_name] = TFNode(link_name)

        # Build tree structure and set transforms
        for joint_name, joint_data in self.joints.items():
            parent_node = self.tf_nodes.get(joint_data['parent'])
            child_node = self.tf_nodes.get(joint_data['child'])

            if parent_node and child_node:
                # Set the static transform from parent to child
                child_node.transform = create_transform_matrix(
                    joint_data['origin_xyz'],
                    joint_data['origin_rpy']
                )

                # Store joint information
                child_node.joint_type = joint_data['type']
                child_node.joint_axis = joint_data['axis']

                # Initialize with 0 angle
                child_node.current_angle = 0.0

                # Add to joint limits for control panel
                if joint_data['type'] in ['revolute', 'continuous']:
                    self.joint_limits[joint_name] = {
                        'lower': joint_data['limits']['lower'],
                        'upper': joint_data['limits']['upper'],
                        'position': 0.0,  # Start at 0
                        'type': joint_data['type']
                    }

                # Add child to parent's children list
                parent_node.children.append(child_node)
                child_node.parent = parent_node

        # Compute absolute transforms
        self._compute_absolute_transforms()

    def _compute_absolute_transforms(self):
        """Compute absolute transforms for all nodes"""
        def compute_recursive(node, parent_transform):
            # For revolute joints, add the rotation
            if node.joint_type in ['revolute', 'continuous']:
                joint_rotation = create_rotation_transform(node.current_angle, node.joint_axis)
                current_transform = node.transform @ joint_rotation
            else:
                current_transform = node.transform

            # Absolute transform is parent_transform * current_transform
            node.absolute_transform = parent_transform @ current_transform

            # Recursively compute for children
            for child in node.children:
                compute_recursive(child, node.absolute_transform)

        # Root node's absolute transform is just its own transform
        root_node = self.tf_nodes[self.root_link]
        root_node.absolute_transform = np.eye(4)  # Root is at world origin

        # Compute for all children
        for child in root_node.children:
            compute_recursive(child, root_node.absolute_transform)

    def update_joint_angle(self, joint_name, angle):
        """Update the angle of a specific joint (弧度)"""
        for joint_jn, joint_data in self.joints.items():
            if joint_jn == joint_name:
                child_node = self.tf_nodes[joint_data['child']]
                child_node.current_angle = angle
                break

        # Recompute all transforms since this affects all children
        self._compute_absolute_transforms()
