# 把 Arena 放到网上(网页 App)

部署好以后，你会得到一个网址，比如 `https://arena-xxxx.onrender.com`：

- **开局**：打开网址 → 输入 app 口令 → 选人类人数、Claude AI 人数、规则机器人人数 → 「开始新一局」→ 把「玩家 1 / 玩家 2」的链接分别发给大家。
- **玩**：每人打开自己的链接就能玩。AI 座位由服务器自动玩，不用再找 Claude 推进。
- **装成 App**：手机上用 Safari 点「分享 → 添加到主屏幕」，安卓 Chrome 点「安装应用」，电脑 Chrome/Edge 点地址栏右侧的安装图标。之后从桌面图标打开，就是全屏的 Arena App。

## 方式一：Render（免费，点几下就好）

1. 登录 [render.com](https://render.com)（用 GitHub 账号登录最方便）。
2. **New + → Blueprint**，选这个仓库和分支，Render 会读取仓库里的 `render.yaml`。
3. 它会让你填 `ANTHROPIC_API_KEY`：
   - 想要 Claude AI 座位就填你的 key（在 [console.anthropic.com](https://console.anthropic.com) 创建）。
   - 不填也能玩，只是 AI 座位只能选规则机器人。
4. 部署完成后，在服务的 **Environment** 页面能看到自动生成的 `ARENA_PASSWORD`，这就是 app 口令。也可以改成你自己好记的。

注意：Render 免费版闲置 15 分钟会休眠，下次打开要等半分钟左右才能唤醒；重启后正在进行的对局会丢失。想一直在线可以换付费版，或者用下面的方式。

## 方式二：任何能跑 Docker 的地方（Fly.io、Railway、自己的服务器）

```bash
docker build -t arena .
docker run -p 8000:8000 -e ARENA_PASSWORD=你的口令 -e ANTHROPIC_API_KEY=sk-ant-... arena
```

## 方式三：在自己电脑上开，局域网里的人一起玩

```bash
pip install -r requirements.txt
ARENA_HOST=0.0.0.0 ARENA_PASSWORD=你的口令 ANTHROPIC_API_KEY=sk-ant-... python3 app/server.py
```

同一个 Wi-Fi 下的其他设备打开 `http://你电脑的局域网IP:8000` 就行。

## 设置项（环境变量）

| 变量 | 作用 |
|---|---|
| `ARENA_PASSWORD` | app 口令：从别的电脑开新局、查看人类座位链接都要输入它。不设置的话，只有运行服务器的那台电脑能开局。 |
| `ANTHROPIC_API_KEY` | Claude AI 座位要用。不设置就只能用规则机器人。 |
| `ARENA_MODEL` | Claude AI 用的模型，默认 `claude-opus-5-5`。想省钱可以换成 `claude-sonnet-5-5`。 |
| `ARENA_EFFORT` | Claude 思考的深度：`low` / `medium` / `high`，默认 `low`（快而且省钱）。 |
| `ARENA_HOST` / `PORT` | 监听地址和端口。Docker 镜像里已经设成 `0.0.0.0:8000`。 |

## 花费

每个 Claude AI 座位每做一次决定，就要调用一次 API，读一份几千字的提示。7 人局如果 5 个 AI 全用 Claude，一整局大约要做一百多次决定：

- 用默认的 `claude-opus-5-5`（low），一局大约 3–6 美元；
- 换成 `claude-sonnet-5-5`，大约便宜一半。

规则机器人完全免费，可以混着用，比如 2 个 Claude 加 3 个机器人。

## 现在的限制

- 一台服务器同一时间只跑一局。开新局时，旧局会自动存档。
- 全知视角的观战页（地图、所有人的身份和手牌）只有在运行服务器的电脑上能看，或者等对局结束后才能看，这样远程玩家不会被剧透。
- Claude 调用失败（网络、额度用完等）时，这一步由规则机器人代打，开局页会显示错误原因，对局不会卡住。
