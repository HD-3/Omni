"""实物开发板链路:Omni 与板之间的轻量通信,不依赖 ROS。

PC 侧只讲简单协议(JSON over TCP,每行一条消息),ROS 2 留在板侧:
板上的桥节点负责把消息转成 ROS 2 topic。链路跑在后台线程,断线
自动重连;未配置时不创建,UI 照常本地运行。
"""

import json
import socket
import threading
import time


class RobotLink:
    """JSON over TCP 链路(标准库实现,零依赖,便于打包)。

    协议(UTF-8,一行一个 JSON 对象):
        PC → 板:{"cmd": "joints", "positions": {"Joint1": 0.5, ...}}(弧度)
        PC → 板:{"cmd": "mode", "value": "pc"|"board"}   控制权切换
        板 → PC:{"state": {"Joint1": 0.52, ...}}
    """

    def __init__(self, host, port=8765, on_state=None, on_status=None):
        self.host = host
        self.port = port
        self._on_state = on_state    # 板回读 {name: rad};后台线程调用
        self._on_status = on_status  # 连接状态变化(bool);后台线程调用
        self._sock = None
        self._closed = False
        self.connected = False
        self._mode = None            # 最近一次控制权,连接/重连后自动补发
        self._send_lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    def send_all(self, positions):
        """positions: {关节名: 弧度},一次发全量(板侧无状态应用)。"""
        self._send({'cmd': 'joints', 'positions': positions})

    def send_mode(self, value):
        """控制权:'pc' 板只听 PC;'board' 板只听板侧 ROS2(PC 只显示)。"""
        self._mode = value
        self._send({'cmd': 'mode', 'value': value})

    def _send(self, msg):
        sock = self._sock
        if sock is None:
            return
        line = json.dumps(msg) + '\n'
        try:
            with self._send_lock:
                sock.sendall(line.encode('utf-8'))
        except OSError:
            self._close_sock()

    def close(self):
        self._closed = True
        self._on_status = None
        self._close_sock()

    def _close_sock(self):
        sock, self._sock = self._sock, None
        self._set_connected(False)
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _set_connected(self, val):
        if val != self.connected:
            self.connected = val
            if self._on_status:
                self._on_status(val)

    def _run(self):
        buf = b''
        while not self._closed:
            if self._sock is None:
                # 重连:板没开机/网络抖动时静默退避
                try:
                    sock = socket.create_connection((self.host, self.port),
                                                    timeout=3)
                    sock.settimeout(1.0)
                    self._sock = sock
                    self._set_connected(True)
                    # 补发控制权:建连前 send_mode 时 socket 还不存在,
                    # 断线重连后板侧也需要重新对齐模式
                    if self._mode is not None:
                        self._send({'cmd': 'mode', 'value': self._mode})
                except OSError:
                    time.sleep(2)
                    continue
            try:
                data = self._sock.recv(4096)
            except socket.timeout:
                continue          # 空闲超时,连接健康,继续等
            except OSError:
                data = None
            if not data:          # b'' = 对端断开;None = 出错
                self._close_sock()
                continue
            buf += data
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                self._handle_line(line)

    def _handle_line(self, line):
        line = line.strip()
        if not line:
            return
        try:
            msg = json.loads(line)
        except ValueError:
            return
        states = msg.get('state') if isinstance(msg, dict) else None
        if isinstance(states, dict) and self._on_state:
            self._on_state(states)
