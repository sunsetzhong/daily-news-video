# 听闻天下 - 每日新闻视频生成器

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python 3.11+">
  <img src="https://github.com/yourusername/daily-news-video/actions/workflows/daily-news.yml/badge.svg" alt="Build Status">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License: MIT">
</p>

<p align="center">
  <strong>每日自动获取新闻，生成专业新闻播报视频</strong>
</p>

---

## 项目简介

"听闻天下"是一个基于 GitHub Actions 的自动化新闻视频生成工具。每天定时获取热点新闻，通过 AI 语音合成和视觉特效，生成专业的新闻播报视频。

### 视频效果

- **开场画面**: 深邃蓝色渐变背景，3D立体标题"听闻天下"，红色日期显示，金色口号
- **新闻播报**: 精美的新闻卡片展示，包含标题和内容
- **配音**: 使用 Edge TTS 生成清晰自然的中文语音
- **结束画面**: 优雅的结束语展示

## 功能特性

- 每日自动运行（北京时间 00:00）
- 支持手动触发工作流
- 多源新闻获取（知乎热榜、微博热搜、百度热搜、NewsAPI）
- AI 语音合成（Edge TTS）
- 专业视觉效果（渐变背景、光线特效、网点纹理）
- 自动打包为视频文件
- 视频产物自动上传到 GitHub Artifacts

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/yourusername/daily-news-video.git
cd daily-news-video
```

### 2. 配置 Secrets

在 GitHub 仓库的 Settings -> Secrets and variables -> Actions 中添加以下 secrets：

| Secret | 说明 | 必需 |
|--------|------|------|
| `NEWS_API_KEY` | NewsAPI 的 API Key | 可选 |
| `TTS_VOICE` | Edge TTS 语音选择，默认 `zh-CN-XiaoxiaoNeural` | 可选 |

### 3. 手动触发

进入 Actions 页面，选择 "Daily News Video Generator"，点击 "Run workflow" 手动触发。

## 本地开发

### 环境要求

- Python 3.11+
- FFmpeg
- 中文字体（Noto Sans CJK 或文泉驿）

### 安装依赖

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install ffmpeg fonts-noto-cjk

# macOS
brew install ffmpeg font-noto-sans-cjk

# Windows
# 下载 FFmpeg 并添加到 PATH
```

### Python 依赖

```bash
pip install -r requirements.txt
```

### 运行

```bash
# 使用模拟数据测试
export USE_MOCK_NEWS=true
python src/main.py

# 使用真实新闻数据
export NEWS_API_KEY=your_api_key
python src/main.py
```

## 项目结构

```
daily-news-video/
├── .github/
│   └── workflows/
│       └── daily-news.yml    # GitHub Actions 工作流配置
├── src/
│   ├── main.py               # 主程序入口
│   ├── news_fetcher.py       # 新闻获取模块
│   └── video_generator.py    # 视频生成模块
├── assets/                   # 静态资源
├── output/                   # 输出目录（视频文件）
├── logs/                     # 日志目录
├── requirements.txt          # Python 依赖
└── README.md                 # 项目说明
```

## 配置说明

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NEWS_API_KEY` | - | NewsAPI 密钥 |
| `TTS_VOICE` | `zh-CN-XiaoxiaoNeural` | TTS 语音 |
| `USE_MOCK_NEWS` | `false` | 使用模拟数据 |

### 支持的 TTS 语音

- `zh-CN-XiaoxiaoNeural` - 晓晓（女声，默认）
- `zh-CN-YunxiNeural` - 云希（男声）
- `zh-CN-YunjianNeural` - 云健（男声）
- `zh-CN-XiaoyiNeural` - 晓伊（女声）
- `zh-CN-YunxiaNeural` - 云夏（男声）

## 自定义配置

### 修改新闻数量

编辑 `src/news_fetcher.py` 中的 `filter_and_rank_news` 方法：

```python
def filter_and_rank_news(self, news_items: List[NewsItem], max_items: int = 8) -> List[NewsItem]:
    # 修改 max_items 参数
```

### 修改视频样式

编辑 `src/video_generator.py` 中的相关方法：

- `create_background_frame()` - 开场背景
- `create_news_frame()` - 新闻卡片样式
- `create_ending_frame()` - 结束画面

## 工作流程

1. **定时触发**: 每天 UTC 16:00（北京时间 00:00）自动运行
2. **手动触发**: 通过 GitHub Actions 页面手动执行
3. **新闻获取**: 从多个源获取热点新闻
4. **脚本生成**: 生成新闻播报脚本
5. **音频生成**: 使用 Edge TTS 生成配音
6. **视频合成**: 使用 FFmpeg 合成最终视频
7. **产物上传**: 视频文件上传到 GitHub Artifacts

## 产物下载

工作流运行完成后，可以在 Actions 页面的产物区域下载：

- `daily-news-video-{run_id}` - 包含生成的视频文件
- `logs-{run_id}` - 包含运行日志

## 技术栈

- **Python 3.11+** - 核心编程语言
- **Edge TTS** - 微软 Edge 语音合成
- **Pillow** - 图像处理
- **FFmpeg** - 视频编码
- **GitHub Actions** - 自动化工作流

## 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 贡献

欢迎提交 Issue 和 Pull Request！

## 致谢

- [Edge TTS](https://github.com/rany2/edge-tts) - 语音合成
- [NewsAPI](https://newsapi.org/) - 新闻数据
- [FFmpeg](https://ffmpeg.org/) - 视频处理

---

<p align="center">
  <sub>Made with ❤️ by 听闻天下团队</sub>
</p>
