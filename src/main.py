"""
听闻天下 - 每日新闻视频生成器主程序
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from news_fetcher import NewsFetcher
from video_generator import VideoGenerator

BEIJING_TZ = timezone(timedelta(hours=8))


def bj_now() -> datetime:
    """北京时间当前时间"""
    return datetime.now(BEIJING_TZ)


# 确保日志目录在日志处理器初始化前存在
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / 'logs'
LOGS_DIR.mkdir(parents=True, exist_ok=True)
# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            LOGS_DIR / f'news_generator_{bj_now().strftime("%Y%m%d")}.log',
            encoding='utf-8'
        )
    ]
)
logger = logging.getLogger(__name__)


def setup_directories(output_dir: str):
    """创建必要的目录"""
    dirs = [output_dir, 'logs', 'assets', os.path.join(output_dir, 'temp')]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)
        logger.info(f"Directory ensured: {d}")


def save_script(script: dict, output_dir: str = 'output'):
    """保存脚本到JSON文件"""
    script_path = os.path.join(output_dir, f'script_{bj_now().strftime("%Y%m%d")}.json')
    with open(script_path, 'w', encoding='utf-8') as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    logger.info(f"Script saved to: {script_path}")
    return script_path


def generate_metadata(video_path: str, script: dict, news_count: int) -> dict:
    """生成视频元数据"""
    metadata = {
        'title': f'听闻天下 - {script["date"]} {script["weekday"]}',
        'description': f'每日5分钟，听闻天下事。本期包含{news_count}条精选新闻。',
        'date': script['date'],
        'weekday': script['weekday'],
        'video_file': os.path.basename(video_path),
        'generated_at': bj_now().isoformat(),
        'news_count': news_count,
        'opening': script['opening'],
        'closing': script['closing'],
        'news_titles': [n['title'] for n in script['news']]
    }
    return metadata


async def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("听闻天下 - 每日新闻视频生成器启动")
    logger.info("=" * 60)
    
    output_dir = os.getenv('OUTPUT_DIR', 'output')

    # 设置目录
    setup_directories(output_dir=output_dir)
    
    # 检查环境
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Working directory: {os.getcwd()}")
    
    # 初始化组件
    news_fetcher = NewsFetcher()
    video_generator = VideoGenerator(output_dir=output_dir)
    
    try:
        # 1. 获取新闻
        logger.info("开始获取新闻...")
        use_mock = os.getenv('USE_MOCK_NEWS', 'false').lower() == 'true'
        news_result = news_fetcher.fetch_all_news(use_mock=use_mock)
        
        logger.info(f"获取到 {news_result['total_fetched']} 条新闻，"
                   f"精选 {news_result['total_selected']} 条")
        
        script = news_result['script']
        news_items = news_result['news_items']
        
        # 保存脚本
        save_script(script, output_dir=output_dir)
        
        # 2. 生成视频
        logger.info("开始生成视频...")
        video_path = await video_generator.generate_video(script, news_items)
        
        # 3. 生成元数据
        metadata = generate_metadata(video_path, script, len(news_items))
        metadata_path = os.path.join(output_dir,
            f'metadata_{bj_now().strftime("%Y%m%d")}.json')
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        logger.info("=" * 60)
        logger.info("视频生成完成！")
        logger.info(f"视频文件: {video_path}")
        logger.info(f"元数据文件: {metadata_path}")
        logger.info("=" * 60)
        
        # 输出GitHub Actions需要的格式
        if os.getenv('GITHUB_ACTIONS') == 'true':
            print(f"::set-output name=video_path::{video_path}")
            print(f"::set-output name=metadata_path::{metadata_path}")
        
        return 0
        
    except Exception as e:
        logger.exception("生成过程中发生错误")
        return 1


if __name__ == '__main__':
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
