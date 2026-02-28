"""
视频生成模块
生成带有背景、字幕、配音的新闻视频
"""

import os
import subprocess
import json
import asyncio
import re
from pathlib import Path
import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple, Any, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VideoGenerator:
    """新闻视频生成器"""
    
    def __init__(self, output_dir: str = 'output', assets_dir: str = 'assets'):
        self.output_dir = output_dir
        self.assets_dir = assets_dir
        self.temp_dir = os.path.join(output_dir, 'temp')
        
        # 创建目录
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # 视频配置
        self.width = 1920
        self.height = 1080
        self.fps = 30
        self.video_codec = 'libx264'
        self.audio_codec = 'aac'
        
        # 字体配置
        self.font_paths = self._find_fonts()
        
        # TTS配置
        self.tts_voice = os.getenv('TTS_VOICE', 'zh-CN-XiaoxiaoNeural')
        self.tts_rate = "+0%"
        self.tts_volume = "+0%"

        # 断句模型配置（OpenAI兼容接口）
        self.x666_base_url = os.getenv('X666_BASE_URL', 'https://x666.me/v1').rstrip('/')
        self.x666_api_key = os.getenv('X666_API_KEY') or os.getenv('OPENAI_API_KEY', '')
        self.x666_model = os.getenv('X666_MODEL', 'gemini-2.5-flash')
        self.enable_ai_subtitle_split = os.getenv('ENABLE_AI_SUBTITLE_SPLIT', 'false').lower() == 'true'
        self.subtitle_split_cache: Dict[str, List[str]] = {}

        # 预渲染科技背景模板，减少每帧绘制开销
        self.base_background = self._create_tech_background()
        self.logo_image = self._load_logo_image()

    def _beijing_now(self) -> datetime:
        """北京时间"""
        return datetime.now(timezone(timedelta(hours=8)))
    
    def _find_fonts(self) -> Dict[str, str]:
        """查找系统中可用的中文字体"""
        font_paths = {
            'title': None,
            'subtitle': None,
            'body': None
        }
        
        # 常见中文字体路径
        possible_fonts = [
            '/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc',
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
            '/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc',
            '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
            '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            '/System/Library/Fonts/PingFang.ttc',
            '/System/Library/Fonts/STHeiti Light.ttc',
            'C:/Windows/Fonts/simhei.ttf',
            'C:/Windows/Fonts/simsun.ttc',
            'C:/Windows/Fonts/msyh.ttc',
        ]
        
        for font_path in possible_fonts:
            if os.path.exists(font_path):
                font_paths['title'] = font_path
                font_paths['subtitle'] = font_path
                font_paths['body'] = font_path
                logger.info(f"Found font: {font_path}")
                break
        
        # 如果没有找到，使用默认字体
        if not font_paths['title']:
            logger.warning("No Chinese font found, using default")
            font_paths['title'] = None
            font_paths['subtitle'] = None
            font_paths['body'] = None
        
        return font_paths
    
    def _get_font(self, font_type: str, size: int) -> ImageFont.FreeTypeFont:
        """获取指定类型和大小的字体"""
        font_path = self.font_paths.get(font_type)
        try:
            if font_path:
                return ImageFont.truetype(font_path, size)
        except Exception as e:
            logger.warning(f"Failed to load font {font_path}: {e}")
        
        return ImageFont.load_default()

    def _normalize_news_item(self, news_item: Any) -> Dict[str, str]:
        """兼容字典和对象两种新闻结构，统一成字典"""
        if isinstance(news_item, dict):
            title = news_item.get('title', '')
            summary = news_item.get('summary') or news_item.get('content') or ''
            source = news_item.get('source', '')
        else:
            title = getattr(news_item, 'title', '')
            summary = getattr(news_item, 'summary', '') or getattr(news_item, 'content', '')
            source = getattr(news_item, 'source', '')

        return {
            'title': title.strip() if title else '',
            'summary': summary.strip() if summary else '',
            'source': source.strip() if source else ''
        }

    def _load_logo_image(self) -> Optional[Image.Image]:
        """加载左上角logo"""
        logo_candidates = [
            Path(self.assets_dir) / 'logo.png',
            Path('logo.png'),
            Path(__file__).resolve().parent.parent / 'logo.png',
        ]

        for logo_path in logo_candidates:
            if not logo_path.exists():
                continue
            try:
                logo = Image.open(logo_path).convert('RGBA')
                resample = Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS
                return logo.resize((156, 156), resample)
            except Exception as e:
                logger.warning(f"Failed to load logo {logo_path}: {e}")

        logger.warning("logo.png not found, fallback to text badge")
        return None

    def _split_short_subtitles_local(self, text: str, max_chars: int) -> List[str]:
        """本地规则断句兜底"""
        parts = re.split(r'([。！？；：，、,.!?;:])', text)
        sentences = []
        for i in range(0, len(parts), 2):
            sentence = parts[i]
            punct = parts[i + 1] if i + 1 < len(parts) else ''
            combined = f"{sentence}{punct}".strip()
            if combined:
                sentences.append(combined)

        chunks = []
        for sentence in sentences:
            rest = sentence
            while len(rest) > max_chars:
                chunks.append(rest[:max_chars])
                rest = rest[max_chars:]
            if rest:
                chunks.append(rest)

        return chunks or [text[:max_chars]]

    def _split_short_subtitles_by_llm(self, text: str, max_chars: int) -> List[str]:
        """使用x666/gemini进行断句"""
        if not self.x666_api_key:
            return []

        try:
            url = f"{self.x666_base_url}/chat/completions"
            payload = {
                "model": self.x666_model,
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是中文新闻字幕断句助手。"
                            "请严格保留原文信息，不改写、不扩写、不删除。"
                            "把文本拆成适合字幕的短句。"
                            "只输出JSON数组，例如：[\"句子1\",\"句子2\"]。"
                        )
                    },
                    {
                        "role": "user",
                        "content": (
                            f"请对这段文本断句，每句不超过{max_chars}个汉字，"
                            f"尽量在自然停顿处分句，保留必要标点：\n{text}"
                        )
                    }
                ]
            }
            headers = {
                "Authorization": f"Bearer {self.x666_api_key}",
                "Content-Type": "application/json",
            }
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            content = (
                data.get('choices', [{}])[0]
                .get('message', {})
                .get('content', '')
                .strip()
            )
            if not content:
                return []

            # 兼容 ```json ... ``` 输出
            fence_match = re.search(r'```(?:json)?\s*(.*?)\s*```', content, re.S)
            if fence_match:
                content = fence_match.group(1).strip()

            parsed = json.loads(content)
            if not isinstance(parsed, list):
                return []

            chunks: List[str] = []
            for item in parsed:
                line = str(item).strip()
                if not line:
                    continue
                if len(line) <= max_chars:
                    chunks.append(line)
                else:
                    chunks.extend(self._split_short_subtitles_local(line, max_chars))
            return chunks
        except Exception as e:
            logger.warning(f"Subtitle split via x666 failed, fallback to local: {e}")
            return []

    def _split_short_subtitles(self, text: str, max_chars: int = 14) -> List[str]:
        """将文案拆分为短字幕片段，优先使用模型断句"""
        if not text:
            return []

        cleaned = re.sub(r'\s+', '', text).strip()
        if not cleaned:
            return []

        cache_key = f"{max_chars}:{cleaned}"
        if cache_key in self.subtitle_split_cache:
            return list(self.subtitle_split_cache[cache_key])

        if self.enable_ai_subtitle_split:
            chunks = self._split_short_subtitles_by_llm(cleaned, max_chars)
            if not chunks:
                chunks = self._split_short_subtitles_local(cleaned, max_chars)
        else:
            chunks = self._split_short_subtitles_local(cleaned, max_chars)

        self.subtitle_split_cache[cache_key] = list(chunks)
        return chunks

    def _wrap_text_lines(self, draw: ImageDraw.Draw, text: str, font: ImageFont.FreeTypeFont,
                         max_width: int, max_lines: int) -> List[str]:
        """按像素宽度换行，限制最大行数"""
        lines = []
        current = ""
        for char in text:
            test = current + char
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] > max_width and current:
                lines.append(current)
                current = char
                if len(lines) >= max_lines:
                    break
            else:
                current = test

        if len(lines) < max_lines and current:
            lines.append(current)

        if len(lines) == max_lines and ''.join(lines) != text:
            last = lines[-1]
            lines[-1] = (last[:-1] + '…') if len(last) > 1 else last

        return lines

    def _create_tech_background(self) -> np.ndarray:
        """创建蓝色科技风背景模板（一次生成，多帧复用）"""
        img = Image.new('RGBA', (self.width, self.height), (5, 22, 110, 255))
        draw = ImageDraw.Draw(img)

        # 蓝色渐变
        top = np.array([3, 20, 105], dtype=float)
        mid = np.array([8, 52, 170], dtype=float)
        bottom = np.array([9, 78, 190], dtype=float)
        for y in range(self.height):
            t = y / max(self.height - 1, 1)
            if t < 0.55:
                k = t / 0.55
                color = top * (1 - k) + mid * k
            else:
                k = (t - 0.55) / 0.45
                color = mid * (1 - k) + bottom * k
            draw.line([(0, y), (self.width, y)], fill=tuple(int(v) for v in color))

        overlay = Image.new('RGBA', (self.width, self.height), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)

        # 左侧镜头光
        flare_center = (-120, int(self.height * 0.70))
        for r in range(420, 40, -32):
            alpha = int(140 * (r / 420) ** 2)
            od.ellipse(
                [flare_center[0] - r, flare_center[1] - r, flare_center[0] + r, flare_center[1] + r],
                fill=(80, 200, 255, alpha)
            )

        # 科技网格节点
        rng = np.random.default_rng(20260227)
        nodes = []
        for _ in range(72):
            nodes.append((
                int(rng.uniform(110, self.width - 110)),
                int(rng.uniform(70, self.height - 70))
            ))

        max_dist2 = 280 * 280
        for i in range(len(nodes)):
            x1, y1 = nodes[i]
            for j in range(i + 1, len(nodes)):
                x2, y2 = nodes[j]
                dx = x2 - x1
                dy = y2 - y1
                d2 = dx * dx + dy * dy
                if d2 <= max_dist2:
                    alpha = int(120 * (1 - d2 / max_dist2))
                    od.line([(x1, y1), (x2, y2)], fill=(140, 205, 255, alpha), width=2)

        for x, y in nodes:
            od.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(230, 245, 255, 220))
            od.ellipse([x - 10, y - 10, x + 10, y + 10], outline=(150, 210, 255, 90), width=1)

        # 中央波形网格
        cx = int(self.width * 0.44)
        for i in range(-18, 19):
            x0 = cx + i * 18
            pts = []
            for y in range(-30, self.height + 30, 18):
                offset = int(34 * np.sin((y / 130.0) + i * 0.32))
                pts.append((x0 + offset, y))
            od.line(pts, fill=(185, 225, 255, 70), width=2)

        for j in range(8, 46):
            y0 = j * 22
            pts = []
            for x in range(180, self.width - 120, 22):
                offset = int(22 * np.sin((x / 140.0) + j * 0.18))
                pts.append((x, y0 + offset))
            od.line(pts, fill=(180, 220, 255, 42), width=1)

        img = Image.alpha_composite(img, overlay)
        return np.array(img.convert('RGB'))

    def _draw_brand_badge(self, img: Image.Image, draw: ImageDraw.Draw):
        """左上角品牌角标"""
        left, top, right, bottom = 36, 24, 194, 210
        draw.rounded_rectangle(
            [left, top, right, bottom],
            radius=18,
            fill=(8, 30, 105),
            outline=(180, 220, 255),
            width=2
        )
        if self.logo_image is not None:
            # `paste` with alpha mask works for both RGB and RGBA base images.
            img.paste(self.logo_image, (left + 1, top + 1), self.logo_image)
        else:
            title_font = self._get_font('title', 68)
            draw.text(
                (left + 18, top + 16),
                "听闻",
                font=title_font,
                fill=(240, 246, 255),
                stroke_width=3,
                stroke_fill=(10, 45, 145)
            )
            draw.text(
                (left + 18, top + 86),
                "天下",
                font=title_font,
                fill=(248, 208, 130),
                stroke_width=3,
                stroke_fill=(65, 20, 10)
            )

    def _draw_main_title_block(self, draw: ImageDraw.Draw, date_str: str, weekday_str: str):
        """开场主标题 + 日期块"""
        title = "听闻天下"
        title_font = self._get_font('title', 188)
        bbox = draw.textbbox((0, 0), title, font=title_font)
        title_w = bbox[2] - bbox[0]
        tx = (self.width - title_w) // 2
        ty = 125

        # 立体蓝色阴影
        for depth in range(12, 0, -2):
            draw.text(
                (tx + depth, ty + depth),
                title,
                font=title_font,
                fill=(32, 120, 215),
                stroke_width=2,
                stroke_fill=(20, 70, 160)
            )

        draw.text(
            (tx, ty),
            title,
            font=title_font,
            fill=(248, 252, 255),
            stroke_width=4,
            stroke_fill=(35, 130, 225)
        )

        # 红色日期（白描边）
        date_font = self._get_font('title', 150)
        week_font = self._get_font('title', 148)
        date_bbox = draw.textbbox((0, 0), date_str, font=date_font)
        week_bbox = draw.textbbox((0, 0), weekday_str, font=week_font)
        dx = (self.width - (date_bbox[2] - date_bbox[0])) // 2
        wx = (self.width - (week_bbox[2] - week_bbox[0])) // 2

        draw.text(
            (dx, 410),
            date_str,
            font=date_font,
            fill=(244, 28, 28),
            stroke_width=12,
            stroke_fill=(248, 248, 255)
        )
        draw.text(
            (wx, 560),
            weekday_str,
            font=week_font,
            fill=(244, 28, 28),
            stroke_width=12,
            stroke_fill=(248, 248, 255)
        )

    def _draw_subtitle(self, draw: ImageDraw.Draw, subtitle: str):
        """绘制底部短字幕"""
        if not subtitle:
            return

        subtitle_font = self._get_font('title', 92)
        text = subtitle.strip()
        max_text_width = self.width - 150
        lines = self._wrap_text_lines(draw, text, subtitle_font, max_text_width, max_lines=2)
        if not lines:
            return

        line_height = 108
        start_y = self.height - 220 - (len(lines) - 1) * line_height
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=subtitle_font)
            line_width = bbox[2] - bbox[0]
            x = (self.width - line_width) // 2
            y = start_y + i * line_height
            draw.text(
                (x + 4, y + 5),
                line,
                font=subtitle_font,
                fill=(60, 0, 0),
                stroke_width=12,
                stroke_fill=(40, 0, 0)
            )
            draw.text(
                (x, y),
                line,
                font=subtitle_font,
                fill=(255, 224, 60),
                stroke_width=10,
                stroke_fill=(175, 8, 8)
            )
    
    def create_background_frame(self, date_str: str, weekday_str: str,
                                progress: float = 0, is_intro: bool = True,
                                subtitle: Optional[str] = None) -> np.ndarray:
        """创建背景帧"""
        img = Image.fromarray(self.base_background.copy())
        draw = ImageDraw.Draw(img)

        self._draw_brand_badge(img, draw)
        self._draw_main_title_block(draw, date_str, weekday_str)

        self._draw_subtitle(draw, subtitle or "")
        
        return np.array(img)
    
    def _add_light_rays(self, draw: ImageDraw.Draw, progress: float):
        """添加光线效果"""
        center_x = self.width // 2
        center_y = self.height // 3
        
        # 绘制从中心发散的光线
        for angle in range(0, 360, 15):
            rad = np.radians(angle + progress * 10)
            x1 = center_x + np.cos(rad) * 50
            y1 = center_y + np.sin(rad) * 50
            x2 = center_x + np.cos(rad) * 800
            y2 = center_y + np.sin(rad) * 800
            
            # 光线颜色（半透明白色）
            alpha = int(30 + np.sin(progress * 2 * np.pi + rad) * 20)
            color = (255, 255, 255, alpha)
            
            draw.line([(x1, y1), (x2, y2)], fill=color[:3], width=2)
    
    def _add_dot_pattern(self, img: Image.Image):
        """添加网点纹理"""
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        # 绘制随机分布的网点
        np.random.seed(42)
        for _ in range(500):
            x = np.random.randint(0, self.width)
            y = np.random.randint(0, self.height)
            size = np.random.randint(1, 4)
            alpha = np.random.randint(10, 40)
            draw.ellipse([x, y, x+size, y+size], fill=(255, 255, 255, alpha))
        
        # 混合图层
        img_rgba = img.convert('RGBA')
        img_rgba = Image.alpha_composite(img_rgba, overlay)
        img.paste(img_rgba.convert('RGB'))
    
    def _draw_title(self, draw: ImageDraw.Draw, date_str: str, weekday_str: str):
        """绘制标题和日期"""
        # 主标题 "听闻天下" - 3D立体效果
        title = "听闻天下"
        title_font = self._get_font('title', 120)
        
        # 获取文字尺寸
        bbox = draw.textbbox((0, 0), title, font=title_font)
        title_width = bbox[2] - bbox[0]
        title_x = (self.width - title_width) // 2
        title_y = 150
        
        # 绘制3D阴影效果
        shadow_offset = 4
        for i in range(shadow_offset, 0, -1):
            alpha = int(100 - i * 15)
            shadow_color = (0, 0, int(100 - i * 20))
            draw.text((title_x + i, title_y + i), title, 
                     font=title_font, fill=shadow_color)
        
        # 绘制主文字（白色）
        draw.text((title_x, title_y), title, font=title_font, fill='white')
        
        # 添加发光效果
        glow_layer = Image.new('RGBA', (self.width, self.height), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_layer)
        glow_draw.text((title_x, title_y), title, font=title_font, 
                      fill=(255, 255, 255, 100))
        
        # 日期 - 红色粗体
        date_text = f"{date_str} {weekday_str}"
        date_font = self._get_font('subtitle', 60)
        
        bbox = draw.textbbox((0, 0), date_text, font=date_font)
        date_width = bbox[2] - bbox[0]
        date_x = (self.width - date_width) // 2
        date_y = title_y + 160
        
        # 绘制日期阴影
        draw.text((date_x + 2, date_y + 2), date_text, 
                 font=date_font, fill=(150, 0, 0))
        # 绘制日期（红色）
        draw.text((date_x, date_y), date_text, 
                 font=date_font, fill='#ff3333')
        
        # 副标题/口号 - 金色立体艺术字
        slogan = "每日 5 分钟  听闻天下事"
        slogan_font = self._get_font('subtitle', 50)
        
        bbox = draw.textbbox((0, 0), slogan, font=slogan_font)
        slogan_width = bbox[2] - bbox[0]
        slogan_x = (self.width - slogan_width) // 2
        slogan_y = self.height - 200
        
        # 绘制金色立体效果
        self._draw_golden_text(draw, slogan, slogan_x, slogan_y, slogan_font)
    
    def _draw_golden_text(self, draw: ImageDraw.Draw, text: str, x: int, y: int, 
                          font: ImageFont.FreeTypeFont):
        """绘制金色立体文字"""
        # 阴影层
        for i in range(3, 0, -1):
            shadow_color = (139, 119, 50)  # 深金色
            draw.text((x + i, y + i), text, font=font, fill=shadow_color)
        
        # 主金色渐变效果
        gold_colors = [
            (255, 215, 0),    # 亮金
            (255, 223, 80),   # 浅金
            (218, 165, 32),   # 中金
            (184, 134, 11),   # 深金
        ]
        
        # 绘制主文字
        draw.text((x, y), text, font=font, fill=gold_colors[0])
        
        # 添加高光效果
        highlight_offset = -1
        draw.text((x + highlight_offset, y + highlight_offset), 
                 text, font=font, fill=(255, 240, 150))
    
    def create_news_frame(self, news_item: Dict, index: int,
                          total: int, progress: float,
                          subtitle: Optional[str] = None,
                          display_date: Optional[str] = None,
                          display_weekday: Optional[str] = None) -> np.ndarray:
        """创建新闻内容帧（仅保留主视觉与字幕）"""
        img = Image.fromarray(self.base_background.copy())
        draw = ImageDraw.Draw(img)

        self._draw_brand_badge(img, draw)
        date_str = display_date or self._beijing_now().strftime("%m月%d日")
        weekday_str = display_weekday or self._beijing_now().strftime("星期%w").replace("0", "日").replace("1", "一").replace("2", "二").replace("3", "三").replace("4", "四").replace("5", "五").replace("6", "六")
        self._draw_main_title_block(draw, date_str, weekday_str)
        self._draw_subtitle(draw, subtitle or "")
        
        return np.array(img)
    
    def create_ending_frame(self, progress: float,
                            subtitle: Optional[str] = None,
                            display_date: Optional[str] = None,
                            display_weekday: Optional[str] = None) -> np.ndarray:
        """创建结束帧（保持中间日期主视觉）"""
        img = Image.fromarray(self.base_background.copy())
        draw = ImageDraw.Draw(img)

        self._draw_brand_badge(img, draw)
        date_str = display_date or self._beijing_now().strftime("%m月%d日")
        weekday_str = display_weekday or self._beijing_now().strftime("星期%w").replace("0", "日").replace("1", "一").replace("2", "二").replace("3", "三").replace("4", "四").replace("5", "五").replace("6", "六")
        self._draw_main_title_block(draw, date_str, weekday_str)

        # 底部短字幕
        self._draw_subtitle(draw, subtitle or "")
        
        return np.array(img)
    
    def _get_audio_duration(self, audio_path: str) -> float:
        """获取音频时长（秒）"""
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
            capture_output=True, text=True
        )
        if probe.returncode != 0 or not probe.stdout.strip():
            raise RuntimeError(f"Failed to probe duration for {audio_path}: {probe.stderr}")
        return float(probe.stdout.strip())

    def _generate_silent_audio(self, output_path: str, duration: float) -> float:
        """生成静音音频作为最终兜底，避免流程中断"""
        safe_duration = max(0.6, min(duration, 3.0))
        cmd = [
            'ffmpeg', '-y',
            '-f', 'lavfi',
            '-i', 'anullsrc=r=24000:cl=mono',
            '-t', f'{safe_duration:.2f}',
            '-q:a', '9',
            '-acodec', 'libmp3lame',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to generate silent audio: {result.stderr}")
        return self._get_audio_duration(output_path)

    async def generate_audio(self, text: str, output_path: str) -> float:
        """使用edge-tts生成音频"""
        cleaned_text = re.sub(r'\s+', ' ', text or '').strip()
        if not cleaned_text:
            return self._generate_silent_audio(output_path, 0.8)

        voices = []
        for voice in [self.tts_voice, 'zh-CN-XiaoxiaoNeural', 'zh-CN-YunxiNeural']:
            if voice and voice not in voices:
                voices.append(voice)

        last_error = None
        for voice in voices:
            for attempt in range(3):
                try:
                    communicate = edge_tts.Communicate(
                        text=cleaned_text,
                        voice=voice,
                        rate=self.tts_rate,
                        volume=self.tts_volume
                    )
                    await communicate.save(output_path)
                    duration = self._get_audio_duration(output_path)
                    logger.info(
                        f"Generated audio: {output_path}, duration: {duration:.2f}s, voice: {voice}"
                    )
                    return duration
                except Exception as e:
                    last_error = e
                    wait_seconds = 1.0 + attempt * 1.5
                    logger.warning(
                        f"TTS failed for voice={voice}, attempt={attempt + 1}/3, error={e}"
                    )
                    await asyncio.sleep(wait_seconds)

        logger.error(f"Error generating audio after retries: {last_error}")
        # 兜底静音，避免整个工作流失败
        fallback_duration = max(0.8, min(len(cleaned_text) * 0.18, 3.0))
        return self._generate_silent_audio(output_path, fallback_duration)

    def concat_audio_segments(self, audio_paths: List[str], output_path: str):
        """合并音频片段"""
        list_path = os.path.abspath(os.path.join(self.temp_dir, 'audio_segments.txt'))
        with open(list_path, 'w', encoding='utf-8') as f:
            for path in audio_paths:
                absolute_path = os.path.abspath(path)
                escaped = absolute_path.replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', list_path,
            '-c:a', 'libmp3lame',
            '-b:a', '192k',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if os.path.exists(list_path):
            os.remove(list_path)

        if result.returncode != 0:
            logger.error(f"Audio concat error: {result.stderr}")
            raise RuntimeError(f"Failed to concat audio: {result.stderr}")
    
    def frames_to_video(self, frames: List[np.ndarray], output_path: str, 
                        duration: float, audio_path: str = None):
        """将帧序列转换为视频"""
        import tempfile
        import shutil
        
        # 保存帧为临时图片
        frame_dir = tempfile.mkdtemp()
        try:
            for i, frame in enumerate(frames):
                frame_path = os.path.join(frame_dir, f"frame_{i:06d}.png")
                Image.fromarray(frame).save(frame_path)
            
            self._encode_frame_dir_to_video(
                frame_dir=frame_dir,
                total_frames=len(frames),
                output_path=output_path,
                duration=duration,
                audio_path=audio_path
            )
        finally:
            shutil.rmtree(frame_dir, ignore_errors=True)

    def _encode_frame_dir_to_video(self, frame_dir: str, total_frames: int,
                                   output_path: str, duration: float,
                                   audio_path: Optional[str] = None):
        """将指定目录中的帧序列编码为视频"""
        if total_frames <= 0:
            raise RuntimeError("No frames to encode")
        
        # 计算帧率
        fps = total_frames / duration if duration > 0 else self.fps
        
        # 构建ffmpeg命令
        if audio_path and os.path.exists(audio_path):
            cmd = [
                'ffmpeg', '-y',
                '-framerate', str(fps),
                '-i', os.path.join(frame_dir, 'frame_%06d.png'),
                '-i', audio_path,
                '-c:v', self.video_codec,
                '-pix_fmt', 'yuv420p',
                '-c:a', self.audio_codec,
                '-b:a', '192k',
                '-shortest',
                '-movflags', '+faststart',
                output_path
            ]
        else:
            cmd = [
                'ffmpeg', '-y',
                '-framerate', str(fps),
                '-i', os.path.join(frame_dir, 'frame_%06d.png'),
                '-c:v', self.video_codec,
                '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart',
                output_path
            ]
        
        # 执行ffmpeg
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            raise RuntimeError(f"FFmpeg failed: {result.stderr}")
        
        logger.info(f"Generated video: {output_path}")
    
    async def generate_video(self, script: Dict, news_items: List) -> str:
        """生成完整的新闻视频"""
        date_str = script.get('date', self._beijing_now().strftime("%m月%d日"))
        weekday_str = script.get('weekday', '')
        normalized_news = [self._normalize_news_item(item) for item in news_items]
        news_count = len(normalized_news)

        # 构建“段落语音 + 短字幕切片”
        blocks = []

        opening_text = script.get('opening', '欢迎收听听闻天下。')
        opening_subtitles = self._split_short_subtitles(opening_text, max_chars=14)
        blocks.append({
            'scene': 'intro',
            'tts_text': opening_text,
            'subtitles': opening_subtitles or [opening_text]
        })

        domestic_script = script.get('domestic_news', [])
        international_script = script.get('international_news', [])
        script_news = script.get('news', [])

        # 兼容旧脚本结构：从 `news` 字段推断分组
        if not domestic_script and not international_script and isinstance(script_news, list):
            for item in script_news:
                if not isinstance(item, dict):
                    continue
                section = str(item.get('section', 'domestic')).strip().lower()
                if section == 'international':
                    international_script.append(item)
                else:
                    domestic_script.append(item)

        # 若脚本中无AI产出的结构，兜底使用原始新闻
        if not domestic_script and not international_script and normalized_news:
            for news in normalized_news:
                title = (news['title'] or '今日要闻').strip()[:28]
                summary = (news['summary'] or '').strip()[:36]
                domestic_script.append({
                    'title': title,
                    'content': f"{title}。{summary}。",
                    'subtitle': f"{title}。{summary}。",
                    'section': 'domestic'
                })

        total_script_news = len(domestic_script) + len(international_script)
        if total_script_news == 0:
            logger.warning("No news blocks provided, generating intro/outro only video")
        else:
            if domestic_script:
                section_text = "先看国内新闻。"
                blocks.append({
                    'scene': 'news',
                    'tts_text': section_text,
                    'subtitles': self._split_short_subtitles(section_text, max_chars=14) or [section_text],
                    'news': {},
                    'index': 1,
                    'total': max(total_script_news, 1)
                })

                for idx, item in enumerate(domestic_script, 1):
                    content = str(item.get('content', '')).strip()
                    subtitle_text = content
                    if not content:
                        continue
                    blocks.append({
                        'scene': 'news',
                        'tts_text': content,
                        'subtitles': self._split_short_subtitles(subtitle_text, max_chars=14) or [subtitle_text],
                        'news': {},
                        'index': idx,
                        'total': max(total_script_news, 1)
                    })

            if international_script:
                section_text = "再看国际新闻。"
                blocks.append({
                    'scene': 'news',
                    'tts_text': section_text,
                    'subtitles': self._split_short_subtitles(section_text, max_chars=14) or [section_text],
                    'news': {},
                    'index': max(len(domestic_script), 1),
                    'total': max(total_script_news, 1)
                })

                for idx, item in enumerate(international_script, len(domestic_script) + 1):
                    content = str(item.get('content', '')).strip()
                    subtitle_text = content
                    if not content:
                        continue
                    blocks.append({
                        'scene': 'news',
                        'tts_text': content,
                        'subtitles': self._split_short_subtitles(subtitle_text, max_chars=14) or [subtitle_text],
                        'news': {},
                        'index': idx,
                        'total': max(total_script_news, 1)
                    })

        closing_text = script.get('closing', '以上就是今天的新闻播报，感谢收听，我们明天再见。')
        closing_subtitles = self._split_short_subtitles(closing_text, max_chars=14)
        blocks.append({
            'scene': 'outro',
            'tts_text': closing_text,
            'subtitles': closing_subtitles or [closing_text]
        })

        if not blocks:
            raise RuntimeError("No blocks generated for audio/video rendering")

        # 按段落生成音频（调用次数少，稳定性更高）
        block_audio_paths = []
        for i, block in enumerate(blocks):
            block_audio_path = os.path.join(self.temp_dir, f'block_{i:03d}.mp3')
            block_duration = await self.generate_audio(block['tts_text'], block_audio_path)
            block['duration'] = max(block_duration, 0.6)
            block_audio_paths.append(block_audio_path)

        # 合并音频片段
        audio_path = os.path.join(self.temp_dir, 'full_audio.mp3')
        self.concat_audio_segments(block_audio_paths, audio_path)
        audio_duration = self._get_audio_duration(audio_path)
        logger.info(f"Total audio duration: {audio_duration:.2f}s")

        # 根据每段音频时长和字幕切片渲染画面（逐帧落盘，避免内存暴涨）
        import tempfile
        import shutil

        frame_dir = tempfile.mkdtemp()
        total_frames = 0
        try:
            for block in blocks:
                subtitles = block['subtitles'] or ['']
                total_block_frames = max(1, int(block['duration'] * self.fps))
                weights = [max(len(s), 1) for s in subtitles]
                total_weight = sum(weights)

                subtitle_frame_counts = [
                    max(1, int(total_block_frames * (weight / total_weight)))
                    for weight in weights
                ]
                diff = total_block_frames - sum(subtitle_frame_counts)
                if diff > 0:
                    subtitle_frame_counts[-1] += diff
                elif diff < 0:
                    for idx in sorted(
                        range(len(subtitle_frame_counts)),
                        key=lambda i: subtitle_frame_counts[i],
                        reverse=True
                    ):
                        if diff == 0:
                            break
                        reducible = subtitle_frame_counts[idx] - 1
                        if reducible <= 0:
                            continue
                        step = min(reducible, -diff)
                        subtitle_frame_counts[idx] -= step
                        diff += step

                for subtitle, subtitle_frames in zip(subtitles, subtitle_frame_counts):
                    for i in range(subtitle_frames):
                        progress = i / subtitle_frames
                        if block['scene'] == 'intro':
                            frame = self.create_background_frame(
                                date_str,
                                weekday_str,
                                progress,
                                True,
                                subtitle=subtitle
                            )
                        elif block['scene'] == 'news':
                            frame = self.create_news_frame(
                                block['news'],
                                block['index'],
                                block['total'],
                                progress,
                                subtitle=subtitle,
                                display_date=date_str,
                                display_weekday=weekday_str
                            )
                        else:
                            frame = self.create_ending_frame(
                                progress,
                                subtitle=subtitle,
                                display_date=date_str,
                                display_weekday=weekday_str
                            )

                        frame_path = os.path.join(frame_dir, f"frame_{total_frames:06d}.png")
                        Image.fromarray(frame).save(frame_path)
                        total_frames += 1

            # 生成视频
            timestamp = self._beijing_now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(self.output_dir, f'daily_news_{timestamp}.mp4')
            self._encode_frame_dir_to_video(
                frame_dir=frame_dir,
                total_frames=total_frames,
                output_path=output_path,
                duration=audio_duration,
                audio_path=audio_path
            )
        finally:
            shutil.rmtree(frame_dir, ignore_errors=True)

        # 清理临时文件
        for block_audio_path in block_audio_paths:
            if os.path.exists(block_audio_path):
                os.remove(block_audio_path)
        if os.path.exists(audio_path):
            os.remove(audio_path)

        logger.info(f"Video generation complete: {output_path}")
        return output_path


if __name__ == '__main__':
    # 测试
    generator = VideoGenerator()
    
    test_script = {
        'date': '02月25日',
        'weekday': '星期二',
        'full_script': '欢迎收听听闻天下。第一条新闻：测试新闻标题。这是测试新闻内容。感谢收听听闻天下，我们明天再见。'
    }
    
    test_news = [
        {'title': '测试新闻标题', 'content': '这是测试新闻内容的详细描述。'}
    ]
    
    asyncio.run(generator.generate_video(test_script, test_news))
