"""
新闻获取模块
支持多个新闻源获取每日热点新闻
"""

import requests
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import List, Dict, Optional
from dataclasses import dataclass
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    """新闻条目数据结构"""
    title: str
    summary: str
    source: str
    url: str
    publish_time: str
    category: str = "general"


class NewsFetcher:
    """新闻获取器"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
        })
        self.news_api_key = os.getenv('NEWS_API_KEY', '')
        self.allow_mock_fallback = os.getenv('ALLOW_MOCK_NEWS_FALLBACK', 'false').lower() == 'true'

    def _strip_html(self, text: str) -> str:
        """移除HTML标签"""
        if not text:
            return ''
        cleaned = unescape(re.sub(r'<[^>]+>', '', text))
        return re.sub(r'\s+', ' ', cleaned).strip()

    def _beijing_now(self) -> datetime:
        """北京时间"""
        return datetime.now(timezone(timedelta(hours=8)))

    def _parse_publish_time(self, raw: str) -> Optional[datetime]:
        """解析发布时间并统一为带时区的UTC时间"""
        if not raw:
            return None

        value = raw.strip()
        if not value:
            return None

        # 兼容RSS/HTTP日期
        try:
            dt = parsedate_to_datetime(value)
            if dt:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
        except Exception:
            pass

        # 兼容ISO时间
        try:
            iso_value = value.replace('Z', '+00:00')
            dt = datetime.fromisoformat(iso_value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

    def _get_item_text(self, parent: ET.Element, tag_names: List[str]) -> str:
        """从XML节点中提取文本"""
        for tag in tag_names:
            node = parent.find(tag)
            if node is not None and node.text:
                return node.text.strip()
        return ''

    def fetch_from_rss(self, url: str, source: str, category: str = 'general',
                       limit: int = 15, recency_hours: int = 36) -> List[NewsItem]:
        """通用RSS新闻抓取"""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            root = ET.fromstring(response.content)

            now_utc = datetime.now(timezone.utc)
            news_items = []

            # RSS item
            for item in root.findall('.//item'):
                title = self._get_item_text(item, ['title'])
                if not title:
                    continue

                summary = self._get_item_text(
                    item,
                    ['description', '{http://purl.org/rss/1.0/modules/content/}encoded']
                )
                link = self._get_item_text(item, ['link'])
                raw_pub = self._get_item_text(item, ['pubDate', 'published', 'updated'])
                publish_dt = self._parse_publish_time(raw_pub) or now_utc

                if (now_utc - publish_dt) > timedelta(hours=recency_hours):
                    continue

                news_items.append(NewsItem(
                    title=self._strip_html(title)[:120],
                    summary=self._strip_html(summary)[:220],
                    source=source,
                    url=link,
                    publish_time=publish_dt.isoformat(),
                    category=category
                ))

                if len(news_items) >= limit:
                    break

            # Atom entry（部分站点）
            if not news_items:
                atom_ns = {'atom': 'http://www.w3.org/2005/Atom'}
                entries = root.findall('.//atom:entry', atom_ns) or root.findall('.//entry')
                for entry in entries:
                    title = self._get_item_text(entry, ['{http://www.w3.org/2005/Atom}title', 'title'])
                    if not title:
                        continue

                    summary = self._get_item_text(
                        entry,
                        ['{http://www.w3.org/2005/Atom}summary',
                         '{http://www.w3.org/2005/Atom}content',
                         'summary', 'content']
                    )

                    link = ''
                    link_node = entry.find('{http://www.w3.org/2005/Atom}link') or entry.find('link')
                    if link_node is not None:
                        link = (link_node.attrib.get('href') or link_node.text or '').strip()

                    raw_pub = self._get_item_text(
                        entry,
                        ['{http://www.w3.org/2005/Atom}published',
                         '{http://www.w3.org/2005/Atom}updated',
                         'published', 'updated']
                    )
                    publish_dt = self._parse_publish_time(raw_pub) or now_utc

                    if (now_utc - publish_dt) > timedelta(hours=recency_hours):
                        continue

                    news_items.append(NewsItem(
                        title=self._strip_html(title)[:120],
                        summary=self._strip_html(summary)[:220],
                        source=source,
                        url=link,
                        publish_time=publish_dt.isoformat(),
                        category=category
                    ))

                    if len(news_items) >= limit:
                        break

            logger.info(f"Fetched {len(news_items)} items from RSS ({source})")
            return news_items
        except Exception as e:
            logger.error(f"Error fetching RSS from {source}: {e}")
            return []

    def fetch_from_google_news_rss(self) -> List[NewsItem]:
        """Google News 中文RSS"""
        url = 'https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans'
        return self.fetch_from_rss(url, source='Google新闻', category='hot', limit=20, recency_hours=36)

    def fetch_from_bing_news_rss(self, query: str) -> List[NewsItem]:
        """Bing News RSS"""
        url = 'https://www.bing.com/news/search'
        params = {'q': query, 'format': 'rss'}
        try:
            query_url = requests.Request('GET', url, params=params).prepare().url
            return self.fetch_from_rss(query_url, source='Bing新闻', category='hot', limit=15, recency_hours=36)
        except Exception as e:
            logger.error(f"Error preparing Bing RSS URL: {e}")
            return []
    
    def fetch_from_newsapi(self, category: str = 'general', page_size: int = 10) -> List[NewsItem]:
        """从 NewsAPI 获取新闻"""
        if not self.news_api_key:
            logger.warning("NewsAPI key not configured, skipping")
            return []
        
        url = 'https://newsapi.org/v2/top-headlines'
        params = {
            'country': 'cn',
            'category': category,
            'pageSize': page_size,
            'apiKey': self.news_api_key
        }
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            news_items = []
            for article in data.get('articles', []):
                news = NewsItem(
                    title=article.get('title', ''),
                    summary=article.get('description', '') or article.get('content', '')[:200],
                    source=article.get('source', {}).get('name', 'Unknown'),
                    url=article.get('url', ''),
                    publish_time=article.get('publishedAt', ''),
                    category=category
                )
                news_items.append(news)
            
            logger.info(f"Fetched {len(news_items)} news from NewsAPI ({category})")
            return news_items
            
        except Exception as e:
            logger.error(f"Error fetching from NewsAPI: {e}")
            return []
    
    def fetch_from_zhihu_hot(self) -> List[NewsItem]:
        """从知乎热榜获取热门话题"""
        url = 'https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total'
        
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            news_items = []
            for item in data.get('data', [])[:15]:
                target = item.get('target', {})
                news = NewsItem(
                    title=target.get('title', ''),
                    summary=target.get('excerpt', '')[:200],
                    source='知乎热榜',
                    url=target.get('link', {}).get('url', ''),
                    publish_time=self._beijing_now().isoformat(),
                    category='hot'
                )
                news_items.append(news)
            
            logger.info(f"Fetched {len(news_items)} hot topics from Zhihu")
            return news_items
            
        except Exception as e:
            logger.error(f"Error fetching from Zhihu: {e}")
            return []
    
    def fetch_from_weibo_hot(self) -> List[NewsItem]:
        """从微博热搜获取热门话题"""
        url = 'https://weibo.com/ajax/side/hotSearch'
        
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            news_items = []
            for item in data.get('data', {}).get('realtime', [])[:15]:
                news = NewsItem(
                    title=item.get('note', ''),
                    summary=item.get('word', ''),
                    source='微博热搜',
                    url=f"https://s.weibo.com/weibo?q={item.get('word', '')}",
                    publish_time=self._beijing_now().isoformat(),
                    category='hot'
                )
                news_items.append(news)
            
            logger.info(f"Fetched {len(news_items)} hot topics from Weibo")
            return news_items
            
        except Exception as e:
            logger.error(f"Error fetching from Weibo: {e}")
            return []
    
    def fetch_from_baidu_hot(self) -> List[NewsItem]:
        """从百度热搜获取热门话题"""
        url = 'https://top.baidu.com/api/board'
        params = {
            'platform': 'wise',
            'tab': 'realtime'
        }
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            news_items = []
            cards = data.get('data', {}).get('cards', [])
            contents = []

            for card in cards:
                if not isinstance(card, dict):
                    continue
                for key in ['content', 'list', 'data']:
                    value = card.get(key)
                    if isinstance(value, list):
                        contents.extend(value)

            for item in contents[:30]:
                if not isinstance(item, dict):
                    continue

                title = (item.get('word') or item.get('title') or item.get('query') or '').strip()
                if not title:
                    continue

                summary = item.get('desc') or item.get('hotScore') or item.get('hotDesc') or ''
                summary = str(summary).strip()[:220]
                publish_time = self._beijing_now().isoformat()

                news = NewsItem(
                    title=title,
                    summary=summary,
                    source='百度热搜',
                    url=item.get('url', '') or item.get('link', ''),
                    publish_time=publish_time,
                    category='hot'
                )
                news_items.append(news)
            
            logger.info(f"Fetched {len(news_items)} hot topics from Baidu")
            return news_items
            
        except Exception as e:
            logger.error(f"Error fetching from Baidu: {e}")
            return []
    
    def fetch_mock_news(self) -> List[NewsItem]:
        """获取模拟新闻（用于测试）"""
        mock_news = [
            NewsItem(
                title="人工智能技术在医疗领域取得重大突破",
                summary="最新研究表明，AI辅助诊断系统在早期癌症检测方面准确率提升至95%以上，为医疗行业带来革命性变化。",
                source="科技日报",
                url="https://example.com/news/1",
                publish_time=self._beijing_now().isoformat(),
                category="tech"
            ),
            NewsItem(
                title="全球气候变化会议达成新共识",
                summary="各国代表在气候峰会上承诺加大减排力度，目标在2030年前将碳排放量减少40%。",
                source="国际新闻",
                url="https://example.com/news/2",
                publish_time=self._beijing_now().isoformat(),
                category="environment"
            ),
            NewsItem(
                title="新能源汽车销量创历史新高",
                summary="今年前三季度，新能源汽车销量同比增长超过60%，市场渗透率突破30%大关。",
                source="财经网",
                url="https://example.com/news/3",
                publish_time=self._beijing_now().isoformat(),
                category="business"
            ),
            NewsItem(
                title="空间站建设取得重要进展",
                summary="我国空间站完成最新一次对接任务，为后续科学实验奠定坚实基础。",
                source="航天报",
                url="https://example.com/news/4",
                publish_time=self._beijing_now().isoformat(),
                category="science"
            ),
            NewsItem(
                title="教育改革新政发布",
                summary="教育部发布最新政策，强调素质教育与创新能力培养，减轻学生课业负担。",
                source="教育周刊",
                url="https://example.com/news/5",
                publish_time=self._beijing_now().isoformat(),
                category="education"
            ),
        ]
        logger.info(f"Using {len(mock_news)} mock news items")
        return mock_news
    
    def filter_and_rank_news(self, news_items: List[NewsItem], max_items: int = 8) -> List[NewsItem]:
        """过滤和排序新闻，选择最重要的内容"""
        # 去重：基于标题相似度
        unique_news = []
        seen_titles = set()
        
        for news in news_items:
            # 清理标题用于比较
            base_text = (news.title or news.summary or '').lower()
            clean_title = re.sub(r'[^\w\u4e00-\u9fff]', '', base_text)
            if not clean_title:
                continue
            if clean_title not in seen_titles:
                seen_titles.add(clean_title)
                unique_news.append(news)
        
        # 按来源优先级排序（可以根据需要调整）
        source_priority = {
            '知乎热榜': 1,
            '微博热搜': 1,
            '百度热搜': 1,
            'Google新闻': 2,
            'Bing新闻': 2,
            '科技日报': 2,
            '财经网': 2,
            '国际新闻': 2,
        }

        def sort_key(news: NewsItem):
            publish_dt = self._parse_publish_time(news.publish_time)
            timestamp = publish_dt.timestamp() if publish_dt else 0
            return (source_priority.get(news.source, 4), -timestamp)

        unique_news.sort(key=sort_key)
        
        return unique_news[:max_items]
    
    def generate_news_script(self, news_items: List[NewsItem]) -> Dict:
        """生成新闻播报脚本"""
        today = self._beijing_now()
        date_str = today.strftime("%m月%d日")
        weekday_str = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][today.weekday()]
        
        # 开场白
        opening = f"欢迎收听听闻天下，今天是{date_str}，{weekday_str}。每日五分钟，听闻天下事。"
        
        # 新闻内容
        news_content = []
        for i, news in enumerate(news_items, 1):
            news_text = f"第{i}条新闻：{news.title}。{news.summary}"
            news_content.append({
                'index': i,
                'title': news.title,
                'content': news_text,
                'source': news.source
            })
        
        # 结束语
        closing = "以上就是今天的新闻播报，感谢收听听闻天下，我们明天再见。"
        
        return {
            'date': date_str,
            'weekday': weekday_str,
            'opening': opening,
            'news': news_content,
            'closing': closing,
            'full_script': opening + " " + " ".join([n['content'] for n in news_content]) + " " + closing
        }
    
    def fetch_all_news(self, use_mock: bool = False) -> Dict:
        """获取所有新闻并生成脚本"""
        if use_mock:
            all_news = self.fetch_mock_news()
        else:
            all_news = []
            
            # 尝试从各个源获取新闻
            all_news.extend(self.fetch_from_zhihu_hot())
            all_news.extend(self.fetch_from_weibo_hot())
            all_news.extend(self.fetch_from_baidu_hot())
            all_news.extend(self.fetch_from_google_news_rss())
            all_news.extend(self.fetch_from_bing_news_rss('中国 热点'))
            all_news.extend(self.fetch_from_bing_news_rss('国际 科技'))
            
            # 如果有NewsAPI key，也尝试获取
            if self.news_api_key:
                all_news.extend(self.fetch_from_newsapi('general'))
                all_news.extend(self.fetch_from_newsapi('technology'))
                all_news.extend(self.fetch_from_newsapi('business'))
            
            # 没有真实新闻时，默认不再静默回退mock，除非显式开启
            if not all_news:
                if self.allow_mock_fallback:
                    logger.warning("No real-time news fetched, fallback to mock data")
                    all_news = self.fetch_mock_news()
                else:
                    raise RuntimeError(
                        "No real-time news fetched from available sources. "
                        "Set ALLOW_MOCK_NEWS_FALLBACK=true if you want mock fallback."
                    )
        
        # 过滤和排序
        selected_news = self.filter_and_rank_news(all_news)

        # 筛选后为空时同样遵循fallback策略
        if not selected_news:
            if self.allow_mock_fallback:
                logger.warning("No valid real-time news selected, fallback to mock data")
                selected_news = self.fetch_mock_news()
            else:
                raise RuntimeError(
                    "No valid real-time news selected after filtering. "
                    "Set ALLOW_MOCK_NEWS_FALLBACK=true if you want mock fallback."
                )
        
        # 生成脚本
        script = self.generate_news_script(selected_news)
        
        return {
            'script': script,
            'news_items': selected_news,
            'total_fetched': len(all_news),
            'total_selected': len(selected_news)
        }


if __name__ == '__main__':
    fetcher = NewsFetcher()
    result = fetcher.fetch_all_news(use_mock=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
