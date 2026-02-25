"""
视频生成模块
生成带有背景、字幕、配音的新闻视频
"""

import os
import subprocess
import json
import asyncio
import edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import numpy as np
from datetime import datetime
from typing import List, Dict, Tuple
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
    
    def create_background_frame(self, date_str: str, weekday_str: str, 
                                progress: float = 0, is_intro: bool = True) -> np.ndarray:
        """创建背景帧"""
        # 创建深蓝色渐变背景
        img = Image.new('RGB', (self.width, self.height), color='#0a1628')
        draw = ImageDraw.Draw(img)
        
        # 绘制渐变效果
        for y in range(self.height):
            # 从顶部深蓝到底部稍浅的蓝色
            r = int(10 + (y / self.height) * 15)
            g = int(22 + (y / self.height) * 20)
            b = int(40 + (y / self.height) * 30)
            draw.line([(0, y), (self.width, y)], fill=(r, g, b))
        
        # 添加光线效果
        self._add_light_rays(draw, progress)
        
        # 添加网点纹理
        self._add_dot_pattern(img)
        
        # 如果是开场画面，添加标题和日期
        if is_intro:
            self._draw_title(draw, date_str, weekday_str)
        
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
                          total: int, progress: float) -> np.ndarray:
        """创建新闻内容帧"""
        # 创建背景
        img = Image.new('RGB', (self.width, self.height), color='#0a1628')
        draw = ImageDraw.Draw(img)
        
        # 绘制渐变背景
        for y in range(self.height):
            r = int(10 + (y / self.height) * 15)
            g = int(22 + (y / self.height) * 20)
            b = int(40 + (y / self.height) * 30)
            draw.line([(0, y), (self.width, y)], fill=(r, g, b))
        
        # 添加光线和纹理
        self._add_light_rays(draw, progress)
        self._add_dot_pattern(img)
        
        # 绘制顶部标题栏
        header_height = 120
        draw.rectangle([0, 0, self.width, header_height], 
                      fill=(0, 0, 0, 100))
        
        # 节目名称
        program_font = self._get_font('title', 50)
        draw.text((50, 30), "听闻天下", font=program_font, fill='white')
        
        # 日期
        date_str = datetime.now().strftime("%m月%d日")
        date_font = self._get_font('body', 30)
        draw.text((self.width - 200, 45), date_str, font=date_font, fill='#ff3333')
        
        # 新闻序号指示器
        indicator_text = f"{index} / {total}"
        indicator_font = self._get_font('body', 25)
        bbox = draw.textbbox((0, 0), indicator_text, font=indicator_font)
        indicator_width = bbox[2] - bbox[0]
        draw.text((self.width - 150 - indicator_width, 85), 
                 indicator_text, font=indicator_font, fill='#aaaaaa')
        
        # 绘制新闻标题
        title = news_item['title']
        title_font = self._get_font('title', 55)
        
        # 自动换行处理标题
        max_title_width = self.width - 200
        words = []
        current_line = ""
        for char in title:
            test_line = current_line + char
            bbox = draw.textbbox((0, 0), test_line, font=title_font)
            if bbox[2] - bbox[0] > max_title_width and current_line:
                words.append(current_line)
                current_line = char
            else:
                current_line = test_line
        if current_line:
            words.append(current_line)
        
        title_y = 200
        for i, line in enumerate(words[:2]):  # 最多两行
            # 金色标题效果
            self._draw_golden_text(draw, line, 100, title_y + i * 70, title_font)
        
        # 绘制新闻内容
        content = news_item['content']
        content_font = self._get_font('body', 35)
        
        # 自动换行处理内容
        max_content_width = self.width - 200
        content_lines = []
        current_line = ""
        for char in content:
            test_line = current_line + char
            bbox = draw.textbbox((0, 0), test_line, font=content_font)
            if bbox[2] - bbox[0] > max_content_width and current_line:
                content_lines.append(current_line)
                current_line = char
            else:
                current_line = test_line
        if current_line:
            content_lines.append(current_line)
        
        content_y = 400
        for i, line in enumerate(content_lines[:6]):  # 最多6行
            draw.text((100, content_y + i * 50), line, 
                     font=content_font, fill='#e0e0e0')
        
        # 绘制进度条
        bar_y = self.height - 80
        bar_width = self.width - 200
        bar_height = 8
        
        # 背景条
        draw.rectangle([100, bar_y, 100 + bar_width, bar_y + bar_height],
                      fill='#333333', outline=None)
        
        # 进度条
        progress_width = int(bar_width * (index / total))
        draw.rectangle([100, bar_y, 100 + progress_width, bar_y + bar_height],
                      fill='#ff3333', outline=None)
        
        return np.array(img)
    
    def create_ending_frame(self, progress: float) -> np.ndarray:
        """创建结束帧"""
        img = Image.new('RGB', (self.width, self.height), color='#0a1628')
        draw = ImageDraw.Draw(img)
        
        # 绘制渐变背景
        for y in range(self.height):
            r = int(10 + (y / self.height) * 15)
            g = int(22 + (y / self.height) * 20)
            b = int(40 + (y / self.height) * 30)
            draw.line([(0, y), (self.width, y)], fill=(r, g, b))
        
        self._add_light_rays(draw, progress)
        self._add_dot_pattern(img)
        
        # 结束语
        ending = "感谢收听听闻天下"
        ending_font = self._get_font('title', 80)
        
        bbox = draw.textbbox((0, 0), ending, font=ending_font)
        text_width = bbox[2] - bbox[0]
        text_x = (self.width - text_width) // 2
        text_y = self.height // 2 - 100
        
        self._draw_golden_text(draw, ending, text_x, text_y, ending_font)
        
        # 副标题
        sub = "我们明天再见"
        sub_font = self._get_font('subtitle', 50)
        
        bbox = draw.textbbox((0, 0), sub, font=sub_font)
        sub_width = bbox[2] - bbox[0]
        sub_x = (self.width - sub_width) // 2
        sub_y = text_y + 150
        
        draw.text((sub_x, sub_y), sub, font=sub_font, fill='#cccccc')
        
        return np.array(img)
    
    async def generate_audio(self, text: str, output_path: str) -> float:
        """使用edge-tts生成音频"""
        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=self.tts_voice,
                rate=self.tts_rate,
                volume=self.tts_volume
            )
            await communicate.save(output_path)
            
            # 获取音频时长
            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', output_path],
                capture_output=True, text=True
            )
            duration = float(probe.stdout.strip())
            
            logger.info(f"Generated audio: {output_path}, duration: {duration:.2f}s")
            return duration
            
        except Exception as e:
            logger.error(f"Error generating audio: {e}")
            raise
    
    def frames_to_video(self, frames: List[np.ndarray], output_path: str, 
                        duration: float, audio_path: str = None):
        """将帧序列转换为视频"""
        import tempfile
        
        # 保存帧为临时图片
        frame_dir = tempfile.mkdtemp()
        frame_files = []
        
        for i, frame in enumerate(frames):
            frame_path = os.path.join(frame_dir, f"frame_{i:06d}.png")
            Image.fromarray(frame).save(frame_path)
            frame_files.append(frame_path)
        
        # 计算帧率
        total_frames = len(frames)
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
        
        # 清理临时文件
        for f in frame_files:
            os.remove(f)
        os.rmdir(frame_dir)
        
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            raise RuntimeError(f"FFmpeg failed: {result.stderr}")
        
        logger.info(f"Generated video: {output_path}")
    
    async def generate_video(self, script: Dict, news_items: List) -> str:
        """生成完整的新闻视频"""
        date_str = script['date']
        weekday_str = script['weekday']
        
        # 生成完整音频
        audio_path = os.path.join(self.temp_dir, 'full_audio.mp3')
        full_script = script['full_script']
        audio_duration = await self.generate_audio(full_script, audio_path)
        
        logger.info(f"Total audio duration: {audio_duration:.2f}s")
        
        # 计算各部分时长分配
        opening_duration = 5  # 开场5秒
        closing_duration = 5  # 结束5秒
        news_duration = (audio_duration - opening_duration - closing_duration) / len(news_items)
        news_duration = max(news_duration, 10)  # 每条新闻至少10秒
        
        all_frames = []
        
        # 生成开场帧
        intro_frames_count = int(opening_duration * self.fps)
        for i in range(intro_frames_count):
            progress = i / intro_frames_count
            frame = self.create_background_frame(date_str, weekday_str, progress, True)
            all_frames.append(frame)
        
        # 生成新闻帧
        for idx, news in enumerate(news_items, 1):
            news_frames_count = int(news_duration * self.fps)
            for i in range(news_frames_count):
                progress = i / news_frames_count
                frame = self.create_news_frame(news, idx, len(news_items), progress)
                all_frames.append(frame)
        
        # 生成结束帧
        ending_frames_count = int(closing_duration * self.fps)
        for i in range(ending_frames_count):
            progress = i / ending_frames_count
            frame = self.create_ending_frame(progress)
            all_frames.append(frame)
        
        # 生成视频
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(self.output_dir, f'daily_news_{timestamp}.mp4')
        
        self.frames_to_video(all_frames, output_path, audio_duration, audio_path)
        
        # 清理临时文件
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
