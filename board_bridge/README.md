# 板侧桥节点(board_bridge)

跑在开发板(树莓派/Jetson)上的小软件:Omni(PC)与板侧 ROS2/硬件之间的翻译官 + 守门员。PC 侧 Omni 不装任何 ROS2,只讲 JSON over TCP。

## 职责

- TCP 服务器(默认 8765):收 PC 的 JSON 命令,回发实际关节状态
- ROS2 节点:发布 `/omni/joint_state`(实际状态,20Hz);订阅 `/omni/joint_command`(板侧 MoveIt 等控制程序的命令入口)
- 控制权仲裁:mode=pc 只执行 PC 命令、丢弃板侧 ROS2 命令;mode=board 反之(Omni 面板此时只读纯显示)
- 驱动硬件:`apply_positions`/`read_positions` 两个钩子,拿到厂商 SDK 后填空

## 部署(板上)

1. 按板子系统装 ROS2:
   - Ubuntu 22.04 + Humble:`sudo apt install ros-humble-ros-base`
   - Ubuntu 24.04 + Jazzy:`sudo apt install ros-jazzy-ros-base`
2. 把 `board_bridge/` 拷到板上,运行:

```bash
source /opt/ros/<distro>/setup.bash
python3 bridge_node.py
```

3. PC 与板同一局域网;两端 `ROS_DOMAIN_ID` 一致(默认 0 即可);板防火墙放行 8765:

```bash
sudo ufw allow 8765
```

## 自测(不接 Omni)

板 1 号终端跑桥,2 号终端看状态话题:

```bash
ros2 topic echo /omni/joint_state
```

PC(或板上)用 nc 模拟 Omni 发命令:

```bash
printf '{"cmd":"joints","positions":{"Joint1":0.5}}\n' | nc <板IP> 8765
printf '{"cmd":"mode","value":"board"}\n' | nc <板IP> 8765   # 切到板控制权
```

钩子未接时,桥把「命令」原样当「状态」回显,话题/回读能先跑通;接完硬件后删掉回退逻辑(见 bridge_node.py 的 `_tick` 注释)。

协议完整规范见 `docs/protocol.md`(字段、单位、仲裁、重连、回声抑制)。

## 接入厂商驱动

编辑 `bridge_node.py` 顶部两个钩子:

- `apply_positions(positions)`:把 `{关节名: 弧度}` 下发硬件(串口舵机帧 / 厂商 SDK 接口)
- `read_positions()`:读回实际角度,返回 `{关节名: 弧度}`
- `JOINT_NAMES`:改成与 Omni URDF 一致的可控关节名列表(必须逐字一致,否则对不上)

## 板侧控制(板模式)

板侧程序(如 MoveIt)把关节命令发到 `/omni/joint_command`(sensor_msgs/JointState,弧度)。桥在 mode=board 时执行它,PC 的 Omni 只显示回读。Omni 面板顶部「控制权」按钮切换,桥侧实时收到 mode 消息;断线重连后桥自动补发当前模式,两端始终对齐。
