# 鲸鱼娘 QQ 机器人（本地版）

QQ 消息 → DeepSeek → 用鲸鱼娘的口吻回复。跑在你自己电脑上，不花钱租服务器。

```
QQ 客户端 → NapCat（协议端）→ NoneBot2（本项目）→ DeepSeek API
```

## 已经搭好的部分

| 文件 | 作用 |
|---|---|
| `bot.py` | 入口，注册 OneBot V11 适配器 |
| `plugins/whale_chat/__init__.py` | 收发消息、上下文记忆、调用 DeepSeek |
| `plugins/whale_chat/persona.py` | **鲸鱼娘人设，想改性格就改这里** |
| `.env` | 配置：API Key、触发词、历史轮数 |
| `test_deepseek.py` | 不接 QQ 也能测人设效果 |
| `start.bat` | 双击启动 |

已装好：NoneBot2 2.5.0 + OneBot V11 适配器 + FastAPI 驱动（在 `.venv` 里）。

## 你要做的三件事

### 1. 填 DeepSeek API Key

去 https://platform.deepseek.com 创建 Key，打开 `.env` 填进去：

```
DEEPSEEK_API_KEY=sk-你的key
```

然后先跑一次测试，确认人设和接口都正常：

```bash
.venv\Scripts\python.exe test_deepseek.py      # 单次
.venv\Scripts\python.exe test_deepseek.py -i   # 交互对话，调人设用这个
```

看到鲸鱼娘回话就说明这条路通了，剩下的只是接 QQ。

### 2. 装 QQ + NapCat

> ⚠️ **用小号。** NapCat 是非官方协议端，违反 QQ 用户协议，有封号风险，别拿主号试。
>
> ⚠️ **运行 NapCat 前，先完全退出 QQ**（任务管理器里确认没有 QQ.exe 残留）。

1. **QQ**：本机已装 NT 版 9.9.19（`D:\Program Files (x86)\Tencent\QQNT`），这步跳过。
   换机器的话去 https://im.qq.com 下新版 NTQQ —— 必须是 NT 版，旧版 9.7 那种不行
2. **NapCat**：https://github.com/NapNeko/NapCatQQ/releases
   Windows 选 `NapCat.Framework` 一键安装版，它会自动找到你装的 QQ
3. 启动后浏览器会打开 WebUI（形如 `http://127.0.0.1:6099/webui?token=xxxx`），
   token 也在启动窗口的日志里
4. 扫码登录你的**小号**

### 3. 把 NapCat 接到本项目

本项目在 `127.0.0.1:8080` 监听，等待 NapCat 主动连过来（反向 WS）。

在 NapCat WebUI 里：

1. 进「网络配置」→ 新建 → 选 **WebSocket 客户端**（有的版本叫「反向 WebSocket」）
2. URL 填：`ws://127.0.0.1:8080/onebot/v11/ws`
3. Token 留空（要和 `.env` 里的 `ONEBOT_ACCESS_TOKEN` 保持一致，现在都是空）
4. 保存并启用

然后双击 `start.bat` 启动本项目。连接成功时日志会出现类似：

```
[INFO] nonebot | OneBot V11 | Bot 123456789 connected
```

### 4. 试一下

- **私聊**：直接发消息，什么都回
- **群聊**：`@机器人 你好` 或者以 `鲸鱼` 开头（`鲸鱼 今天吃什么`）
- 想清空上下文：发 `重置` 或 `/reset`

## 记忆系统

她有长期记忆了。数据存在 `data/whale.db`（SQLite），重启不失忆。

**结构**：人设（固定）→ 已知事实（每天最多变一次）→ 相关往事（向量召回）→ 最近对话

前两段稳定，能命中 DeepSeek 的上下文缓存，实际花钱的只有最后一段。

### 指令

| 指令 | 作用 | 权限 |
|---|---|---|
| `/记忆` | 看她记住了什么 | 私聊所有人 / 群里仅 `WHALE_ADMIN_QQ` |
| `/忘掉 香菜` | 删掉相关记忆 | 同上 |
| `/记忆清空` | 清空当前会话记忆 | 同上 |
| `重置` | 清空事实（旧行为保留） | 所有人 |

### 提炼事实

画像不是自动出现的，要跑提炼脚本：

```bash
.venv\Scripts\python.exe distill.py            # 有新料才提炼（≥30 条新对话）
.venv\Scripts\python.exe distill.py --force    # 强制提炼
.venv\Scripts\python.exe distill.py --list     # 看各会话待提炼数量
```

建议加个 Windows 任务计划每天跑一次，脚本自己判断要不要真干活。

### 相关文件

| 文件 | 作用 |
|---|---|
| `plugins/whale_chat/storage.py` | SQLite 读写 |
| `plugins/whale_chat/embedding.py` | 本地向量化（bge-small-zh，离线跑，不花 token） |
| `plugins/whale_chat/memory.py` | 组装上下文、向量召回 |
| `distill.py` | 离线提炼事实 |
| `models/hf/` | 向量模型缓存（91MB） |

关掉记忆：`.env` 里 `WHALE_MEMORY_ENABLED=false`，退回内存模式。

## 调人设

改 `plugins/whale_chat/persona.py` 里的 `SYSTEM_PROMPT`，改完重启生效。
建议先用 `test_deepseek.py -i` 反复试，满意了再去 QQ 里用。

## 常见问题

**启动报端口被占用**
改 `.env` 里的 `PORT`，同时把 NapCat 里的 WS 地址跟着改。

**NapCat 报 `Unexpected server response: 404`**
缺 WebSocket 库。装 uvicorn 时如果没带 `[standard]` 就会缺：
```bash
.venv\Scripts\pip install websockets
```
日志里会同时出现 `No supported WebSocket library detected`，看到这句就是这个问题。

**NapCat 显示已连接，但机器人不回话**
- 群聊必须 @ 机器人或以触发词开头，普通闲聊不会回（防止刷屏和烧 token）
- 看本项目日志有没有报错

**回复 `出问题了：DeepSeek 返回 401`**
Key 错了或失效了。

**回复 `余额不足`**
DeepSeek 账户没钱了，去平台充值。

**重启后上下文没了**
历史存在内存里，重启即清空。本地测试阶段够用。

## 后续想 24 小时在线

现在这套依赖电脑开着。想 7×24 跑，把这整个目录搬到云服务器上：

- 国内轻量 2核2G 起步（NapCat 吃内存，别买 1核1G）
- 用 `systemd` 或 Docker 守护两个进程：NapCat 和 `bot.py`
- 服务器不需要域名、不需要备案（只主动外连，不对外提供服务）
- 把 `.env` 里的 `ONEBOT_ACCESS_TOKEN` 改成强随机串，`HOST` 保持 `127.0.0.1`

## 注意

- `.env` 里有你的 API Key，别提交到 git（`.gitignore` 已排除）
- 鲸鱼娘形象版权归原作者，本项目仅作个人使用
