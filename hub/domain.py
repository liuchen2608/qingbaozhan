import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

CATEGORIES = ['大模型技术', 'AI Agent', 'AI Native 产品', 'AIGC 图像生成', 'AIGC 视频生成', 'AI 音频生成', 'AI 产品发布', 'AI 商业化', 'AI 行业融资与市场趋势']
WEIGHTS = {'技术创新价值': 25, '产品应用价值': 25, '商业化潜力': 25, '行业影响力': 15, '个人目标关联': 10}
ANALYSIS_FIELDS = ['summary', 'change', 'problem', 'scenarios', 'user_value', 'business_value', 'pm_insight', 'evidence', 'uncertainties']
PM_QUESTIONS = ['它是什么', '解决什么问题', '目标用户', '核心能力', '相比传统软件的优势', 'AI Native 特征', '商业模式', '如果由我设计会怎么做']

def now():
    return datetime.now(timezone.utc).isoformat()

def timestamp(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            raise ValueError('发布时间必须带时区，例如 +08:00')
        return dt.astimezone(timezone.utc).isoformat()
    except (ValueError, AttributeError) as exc:
        raise ValueError('发布时间必须是带时区的 ISO 日期时间') from exc

def link(value):
    parts = urlsplit(value.strip())
    if parts.scheme not in ('https', 'http') or not parts.hostname or parts.username or parts.password:
        raise ValueError('请提供有效的 http/https 原文链接，不要包含凭证')
    return value.strip()

def identity(url, content):
    parts = urlsplit(url)
    match = re.search(r'/[^/]+/status/(\d+)(?:/|$)', parts.path)
    if parts.hostname in ('x.com', 'www.x.com', 'twitter.com', 'www.twitter.com', 'mobile.twitter.com') and match:
        canonical = 'https://x.com/i/status/' + match.group(1)
    else:
        canonical = url.split('#')[0].rstrip('/')
    normalized = re.sub(r'\s+', '', content).casefold()
    fingerprint = hashlib.sha256(normalized.encode()).hexdigest() if len(normalized) >= 80 else None
    return canonical, fingerprint

def validate_analysis(value):
    if not isinstance(value, dict):
        raise ValueError('模型分析必须是 JSON 对象')
    if value.get('category') not in CATEGORIES:
        raise ValueError('主要分类无效')
    for key in ANALYSIS_FIELDS:
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError('缺少分析字段：' + key)
    if not isinstance(value.get('tags'), list) or len(value['tags']) > 20 or any(not isinstance(t, str) for t in value['tags']):
        raise ValueError('标签必须是最多20项的字符串列表')
    questions = value.get('pm_questions', {})
    for q in PM_QUESTIONS:
        if not isinstance(questions.get(q), str) or not questions[q].strip():
            raise ValueError('缺少产品经理八问：' + q)
    scores = value.get('scores', {})
    total = 0
    for key, maximum in WEIGHTS.items():
        score = scores.get(key, {})
        number = score.get('score')
        if type(number) is not int or not 0 <= number <= maximum or not isinstance(score.get('reason'), str) or not score['reason'].strip():
            raise ValueError('评分或理由无效：' + key)
        total += number
    value['total_score'] = total
    value['priority'] = '重点研究' if total >= 80 else '值得关注' if total >= 60 else '普通信息' if total >= 40 else '低优先级'
    return value
