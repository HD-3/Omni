#!/usr/bin/env python3
"""板侧桥节点:Omni(PC)与板侧 ROS2/硬件之间的翻译官 + 守门员。

职责:
1. TCP 服务器(默认 8765):收 PC 的 JSON 命令,回发实际关节状态
2. ROS2 节点:发布 /omni/joint_state;订阅 /omni/joint_command
   (板侧控制程序——如 MoveIt——的命令入口)
3. 控制权仲裁:mode=pc 只执行 PC 命令;mode=board 只执行板侧命令
4. 驱动硬件:apply_positions/read_positions 两个钩子,接厂商 SDK

协议(与 Omni 的 robot_link.py 一致,UTF-8 一行一条):
    PC → 板:{"cmd": "joints", "positions": {"Joint1": 0.5, ...}}  弧度
    PC → 板:{"cmd": "mode", "value": "pc"|"board"}
    板 → PC:{"state": {"Joint1": 0.52, ...}}

用法:
    python3 bridge_node.py [--port 8765] [--rate 20]
"""

import argparse
import json
import socket
import threading

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState


# ============================================================
# 硬件驱动钩子:拿到厂商 SDK 后在这里填空
# ============================================================

def apply_positions(positions):
    """把关节角(弧度)下发到真实机械臂。

    positions: {关节名: 弧度}。按你的硬件接口实现,例如:
    - 串口总线舵机:把每个关节角换算成舵机脉宽/角度,按协议帧发串口
    - 厂商 SDK:调对应的 set_joint_angle / servo_write 接口
    """
    raise NotImplementedError('接入厂商驱动后实现:向硬件下发 ' + str(positions))


def read_positions():
    """读取机械臂当前实际关节角,返回 {关节名: 弧度}。

    按硬件接口实现,例如读舵机编码器/厂商 SDK 的 get_joint_angle。
    """
    raise NotImplementedError('接入厂商驱动后实现:从硬件读取实际关节角')


# 可控关节名:改成与 Omni URDF 一致(JointState 的 name 字段用它过滤)
JOINT_NAMES = ['Joint1', 'Joint2', 'Joint3', 'Joint4', 'Joint5', 'Joint6',
               'JointGL', 'JointGR']


# ============================================================
# 桥本体
# ============================================================

class Bridge:
    """TCP 服务 + 命令仲裁 + 状态回发。"""

    def __init__(self, node, port, rate):
        self.node = node
        self.mode = 'pc'            # 默认 PC 控制;PC 发 mode 消息切换
        self.pc_positions = None    # 最近一条 PC 命令 {名: 弧度}
        self.ros_positions = None   # 最近一条板侧 ROS2 命令
        self._lock = threading.Lock()
        self._conns = set()         # 已连接的 PC 连接(回发 state 用)

        # ROS2:发布实际状态,订阅板侧控制命令
        self.pub = node.create_publisher(JointState, '/omni/joint_state', 10)
        node.create_subscription(JointState, '/omni/joint_command',
                                 self._on_ros_command, 10)
        # 控制循环(rate Hz,ROS2 定时器回调)+ TCP 服务器线程
        node.create_timer(1.0 / rate, self._tick)
        threading.Thread(target=self._serve, args=(port,), daemon=True).start()

    # ---- TCP:PC 侧 ----

    def _serve(self, port):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('0.0.0.0', port))
        srv.listen(1)
        self.node.get_logger().info(f'bridge listening on :{port}')
        while rclpy.ok():
            conn, addr = srv.accept()
            self._conns.add(conn)
            threading.Thread(target=self._recv_loop, args=(conn,),
                             daemon=True).start()

    def _recv_loop(self, conn):
        buf = b''
        while rclpy.ok():
            try:
                data = conn.recv(4096)
            except OSError:
                break
            if not data:
                break
            buf += data
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                self._handle_line(line)
        self._conns.discard(conn)
        try:
            conn.close()
        except OSError:
            pass

    def _handle_line(self, line):
        line = line.strip()
        if not line:
            return
        try:
            msg = json.loads(line)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        with self._lock:
            if msg.get('cmd') == 'joints' and isinstance(msg.get('positions'),
                                                         dict):
                self.pc_positions = msg['positions']
            elif msg.get('cmd') == 'mode' and msg.get('value') in ('pc', 'board'):
                self.mode = msg['value']
                self.node.get_logger().info(f'control mode -> {self.mode}')

    # ---- ROS2:板侧命令入口 ----

    def _on_ros_command(self, msg):
        with self._lock:
            self.ros_positions = dict(zip(msg.name, msg.position))

    # ---- 控制循环:仲裁 → 执行 → 回读 → 发布 ----

    def _tick(self):
        with self._lock:
            cmd = self.pc_positions if self.mode == 'pc' else self.ros_positions
        if cmd:
            try:
                apply_positions(cmd)
            except NotImplementedError:
                pass    # 钩子未接时静默;接入后正常执行
        try:
            states = read_positions()
        except NotImplementedError:
            states = cmd or {}    # 钩子未接时把命令当状态,便于联调
        if not states:
            return
        # 发布 ROS2 状态
        names = [n for n in JOINT_NAMES if n in states]
        jmsg = JointState()
        jmsg.header.stamp = self.node.get_clock().now().to_msg()
        jmsg.name = names
        jmsg.position = [float(states[n]) for n in names]
        self.pub.publish(jmsg)
        # 回发 PC
        line = json.dumps({'state': states}) + '\n'
        for conn in list(self._conns):
            try:
                conn.sendall(line.encode('utf-8'))
            except OSError:
                self._conns.discard(conn)


def main():
    parser = argparse.ArgumentParser(description='Omni 板侧桥节点')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--rate', type=float, default=20.0)
    args = parser.parse_args()

    rclpy.init()
    node = Node('omni_board_bridge')
    Bridge(node, args.port, args.rate)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
