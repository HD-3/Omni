# Omni —— Kivy 机器人可视化软件

模仿商业软件 ReachControl 的架构:Kivy HUD + 自研 3D 渲染层 + 模块化功能包。

## 功能(v1 全量)

- **3D 查看 + 关节控制**:URDF 机器人 Blinn-Phong 光照渲染;轨道相机(左键旋转/右键平移/滚轮缩放);21 关节滑块实时驱动
- **板连接**:顶栏「连接设置」面板手动输入 IP/端口连接实物开发板(JSON over TCP),顶栏显示连接状态与机器人名;接口协议见 `docs/protocol.md`,板侧 ROS2 桥见 `board_bridge/`
- **顶栏自动隐藏**:顶栏默认隐藏,鼠标移到窗口顶部时滑出,移开后收回;侧边栏展开期间顶栏保持显示;点击 3D 画面折叠侧边栏回到全屏
- **新手引导**:首启动 2 步图文教程,完成后不再显示
- **文件对话框 + 打包**:HUD「打开 URDF」按钮;PyInstaller onedir 双击运行

## 运行

```bash
conda run -n omni python main.py [urdf路径] [--screenshot out.png]
```

无参数时打开上次的 URDF(默认内置 `s5v2-urdf.urdf`)。

## 打包(Linux)

```bash
./packaging/build_linux.sh     # 产出 dist/Omni/Omni(onedir,双击运行)
./packaging/build_deb.sh       # 产出 dist/omni_1.0.0_amd64.deb(安装到 /opt/omni,
                               # 带桌面启动项与 /usr/bin/omni 命令;VERSION= 可覆盖版本号)
```

deb 安装:`sudo dpkg -i dist/omni_1.0.0_amd64.deb`,之后应用菜单出现「Omni」,终端可 `omni [urdf路径]`。

## 目录结构

```
main.py                 # 入口 OmniApp;CLI;URDF 加载;板连接;教程触发
omni.kv                 # HUD 根布局:状态栏 + 左栏(关节面板/连接面板)+ 3D 视口
theme.py                # 设计常量(字号/间距/配色)
config.py               # ~/.omni/config.json(tutorial_completed/last_urdf/link_host/link_port)
visualisation/          # 3D 层:viewport3d / camera / gl_renderer(裸 GL)
                        # urdf_parser / robot_builder / mesh_factory / shaders / assets
ui/                     # joint_panel(关节控制)/ connect_panel(板连接设置)
tutorials/              # onboarding_overlay + steps.json
filedialog/             # URDFPicker(FileChooser)
docs/                   # 板通信接口协议(protocol.md)
board_bridge/           # 板侧桥:bridge_node.py(真机)/ demo_bridge.py(零硬件
                        # ROS2 演示)/ test_comm.py(通讯测试)
packaging/              # omni.spec + build_linux.sh + build_deb.sh
```

## 技术要点

- 3D 渲染绕过 Kivy Canvas 着色器管线(本机 RenderContext 失效),经
  `kivy.graphics.opengl` 直接调用 OpenGL(`Callback` 指令 + 自编译 GLSL 120
  着色器 + VBO/IBO + Blinn-Phong 光照)
- 深度缓冲:启动前 `Config.set('graphics', 'depthbuffer', 1)`
- 打包 spec 直接调用 Kivy 官方 `pyinstaller_hooks` 模块(PyInstaller 6 不加载
  第三方 hooks 目录);SDL2 动态库从 conda 环境手动收集
- kv 加载:重写 `App.load_kv`,统一由 `build()` 按 PROJECT_ROOT 显式加载
  (冻结打包下 `sys._MEIPASS`),避免规则应用两次导致部件树重复
