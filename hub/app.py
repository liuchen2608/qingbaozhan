import csv
import io
import json
import logging
import sqlite3
import zipfile
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from openpyxl import Workbook, load_workbook
from pydantic import BaseModel, Field

from . import model, store
from .domain import CATEGORIES, identity, link, now, timestamp, validate_analysis

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
logger = logging.getLogger('hub')

@asynccontextmanager
async def lifespan(app):
    store.init()
    yield

app = FastAPI(title='情报站', lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

@app.middleware('http')
async def local_origin(request: Request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if origin and origin not in ('http://127.0.0.1:8765', 'http://localhost:8765'):
            return JSONResponse({'detail': '拒绝跨站写入请求'}, status_code=403)
    return await call_next(request)

@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=422)

@app.exception_handler(sqlite3.IntegrityError)
async def integrity(request, exc):
    return JSONResponse({'detail': '重复记录，或关联的信息源不存在'}, status_code=409)

class SourceInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(max_length=2000)
    category: str = Field(default='', max_length=100)
    enabled: bool = True

class ItemInput(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    url: str = Field(max_length=2000)
    content: str = Field(default='', max_length=60000)
    author: str = Field(default='', max_length=200)
    published_at: str
    source_id: int | None = None
    notes: str = Field(default='', max_length=20000)
    favorite: bool = False

def get_item(con, item_id):
    row = con.execute('SELECT * FROM items WHERE id=?', (item_id,)).fetchone()
    if row is None:
        raise HTTPException(404, '情报不存在')
    return store.item(row)

def insert_item(con, value):
    url = link(value.url)
    canonical, fingerprint = identity(url, value.content)
    return con.execute('INSERT INTO items(title,url,canonical,content,author,published_at,source_id,notes,favorite,fingerprint,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
        (value.title, url, canonical, value.content, value.author, timestamp(value.published_at), value.source_id, value.notes, value.favorite, fingerprint, now())).lastrowid

@app.get('/api/status')
def status():
    try:
        provider, base, key, name = model.configuration()
        configured = True
    except model.ModelError:
        configured = False
    return {'model_configured': configured, 'categories': CATEGORIES, 'automatic_collection': False}

@app.get('/api/sources')
def sources():
    with store.db() as con:
        return [dict(r) for r in con.execute('SELECT * FROM sources ORDER BY id')]

@app.post('/api/sources', status_code=201)
def create_source(value: SourceInput):
    with store.db() as con:
        sid = con.execute('INSERT INTO sources(name,url,category,enabled) VALUES(?,?,?,?)', (value.name, link(value.url), value.category, value.enabled)).lastrowid
        return {'id': sid}

@app.put('/api/sources/{sid}')
def edit_source(sid: int, value: SourceInput):
    with store.db() as con:
        cur = con.execute('UPDATE sources SET name=?,url=?,category=?,enabled=? WHERE id=?', (value.name, link(value.url), value.category, value.enabled, sid))
        if not cur.rowcount:
            raise HTTPException(404, '信息源不存在')
    return {'ok': True}

@app.delete('/api/sources/{sid}')
def delete_source(sid: int):
    with store.db() as con:
        con.execute('DELETE FROM sources WHERE id=?', (sid,))
    return {'ok': True}

@app.post('/api/items', status_code=201)
def create_item(value: ItemInput):
    with store.db() as con:
        iid = insert_item(con, value)
        return get_item(con, iid)

@app.get('/api/items')
def items(q: str = '', category: str = '', start: date | None = None, end: date | None = None,
          min_score: int = Query(0, ge=0, le=100), favorite: bool = False, sort: str = 'date'):
    if start and end and start > end:
        raise HTTPException(422, '开始日期不能晚于结束日期')
    clauses, args = [], []
    if q:
        clauses.append('(instr(lower(title),lower(?))>0 OR instr(lower(content),lower(?))>0 OR instr(lower(notes),lower(?))>0 OR instr(lower(coalesce(analysis,\'\')),lower(?))>0)')
        args.extend([q] * 4)
    if category:
        clauses.append('category=?'); args.append(category)
    if start:
        clauses.append('published_at>=?'); args.append(datetime.combine(start, time.min, ZoneInfo('Asia/Shanghai')).astimezone(ZoneInfo('UTC')).isoformat())
    if end:
        clauses.append('published_at<?'); args.append(datetime.combine(end + timedelta(days=1), time.min, ZoneInfo('Asia/Shanghai')).astimezone(ZoneInfo('UTC')).isoformat())
    if min_score:
        clauses.append('score>=?'); args.append(min_score)
    if favorite:
        clauses.append('favorite=1')
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    order = 'score DESC, published_at DESC' if sort == 'score' else 'published_at DESC'
    with store.db() as con:
        return [store.item(r) for r in con.execute('SELECT * FROM items' + where + ' ORDER BY ' + order, args)]

@app.get('/api/items/{iid}')
def item_detail(iid: int):
    with store.db() as con:
        return get_item(con, iid)

@app.put('/api/items/{iid}')
def edit_item(iid: int, value: ItemInput):
    with store.db() as con:
        old = get_item(con, iid)
        url, published = link(value.url), timestamp(value.published_at)
        canonical, fingerprint = identity(url, value.content)
        changed = any(old[k] != v for k, v in {'title': value.title, 'url': url, 'content': value.content, 'author': value.author, 'published_at': published, 'source_id': value.source_id}.items())
        con.execute('UPDATE items SET title=?,url=?,canonical=?,content=?,author=?,published_at=?,source_id=?,notes=?,favorite=?,fingerprint=?,revision=? WHERE id=?',
            (value.title, url, canonical, value.content, value.author, published, value.source_id, value.notes, value.favorite, fingerprint, old['revision'] + int(changed), iid))
        if changed:
            con.execute('UPDATE items SET analysis=NULL,category=NULL,score=NULL WHERE id=?', (iid,))
        return get_item(con, iid)

@app.delete('/api/items/{iid}')
def delete_item(iid: int):
    with store.db() as con:
        con.execute('DELETE FROM items WHERE id=?', (iid,))
    return {'ok': True}

def save_analysis(iid, revision, value, kind, model_name=None):
    encoded = json.dumps(validate_analysis(value), ensure_ascii=False)
    with store.db() as con:
        cur = con.execute('UPDATE items SET analysis=?,category=?,score=? WHERE id=? AND revision=?', (encoded, value['category'], value['total_score'], iid, revision))
        if not cur.rowcount:
            raise HTTPException(409, '原文已改变或被删除，请重新分析')
        con.execute('INSERT INTO versions(item_id,revision,analysis,kind,model,created_at) VALUES(?,?,?,?,?,?)', (iid, revision, encoded, kind, model_name, now()))
        return get_item(con, iid)

@app.post('/api/items/{iid}/analyze')
async def analyze_item(iid: int):
    with store.db() as con:
        record = get_item(con, iid)
    try:
        result, model_name = await model.analyze(record)
    except model.ModelError as exc:
        logger.warning('analysis_failed item_id=%s', iid)
        raise HTTPException(502, str(exc)) from None
    logger.info('analysis_complete item_id=%s', iid)
    return save_analysis(iid, record['revision'], result, 'ai', model_name)

class ManualAnalysis(BaseModel):
    revision: int
    analysis: dict

@app.put('/api/items/{iid}/analysis')
def revise_analysis(iid: int, value: ManualAnalysis):
    return save_analysis(iid, value.revision, value.analysis, 'manual')

@app.get('/api/items/{iid}/versions')
def versions(iid: int):
    with store.db() as con:
        get_item(con, iid)
        result = [dict(r) for r in con.execute('SELECT * FROM versions WHERE item_id=? ORDER BY id DESC', (iid,))]
        for row in result:
            row['analysis'] = json.loads(row['analysis'])
        return result

@app.post('/api/import/{target}')
async def import_file(target: str, file: UploadFile):
    if target not in ('sources', 'items'):
        raise HTTPException(404, '导入目标不存在')
    data = await file.read(2_000_001)
    if len(data) > 2_000_000:
        raise HTTPException(413, '导入文件不得超过2MB')
    suffix = Path(file.filename or '').suffix.lower()
    try:
        if suffix == '.json':
            rows = json.loads(data)
            if not isinstance(rows, list):
                raise ValueError('JSON 必须是对象数组')
        elif suffix == '.csv':
            rows = list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
        elif suffix == '.xlsx':
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if sum(i.file_size for i in archive.infolist()) > 20_000_000:
                    raise ValueError('Excel 解压后过大')
            book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            sheet = book.active
            iterator = sheet.iter_rows(values_only=True)
            headers = next(iterator)
            rows = []
            for row in iterator:
                if len(rows) >= 1000:
                    raise ValueError('单次最多导入1000条')
                if any(v is not None for v in row):
                    rows.append(dict(zip(headers, row)))
            book.close()
        else:
            raise ValueError('支持 CSV、JSON、.xlsx 文件')
        if len(rows) > 1000:
            raise ValueError('单次最多导入1000条')
    except Exception as exc:
        raise HTTPException(422, '无法读取导入文件；请检查格式、编码、文件大小和列名') from None
    result = {'imported': 0, 'duplicates': 0, 'errors': []}
    with store.db() as con:
        for index, row in enumerate(rows, 2):
            con.execute('SAVEPOINT import_row')
            try:
                if target == 'sources':
                    value = SourceInput(**row)
                    con.execute('INSERT INTO sources(name,url,category,enabled) VALUES(?,?,?,?)', (value.name, link(value.url), value.category, value.enabled))
                else:
                    insert_item(con, ItemInput(**row))
                result['imported'] += 1
            except sqlite3.IntegrityError as exc:
                con.execute('ROLLBACK TO import_row')
                if 'UNIQUE constraint' in str(exc):
                    result['duplicates'] += 1
                else:
                    result['errors'].append({'row': index, 'error': '关联信息源不存在'})
            except (ValueError, TypeError):
                con.execute('ROLLBACK TO import_row')
                result['errors'].append({'row': index, 'error': '字段缺失或无效，请检查列名、链接和带时区的发布时间'})
            finally:
                con.execute('RELEASE import_row')
    return result

@app.get('/api/report')
def report(day: date, period: str = 'daily'):
    if period not in ('daily', 'weekly'):
        raise HTTPException(422, 'period 为 daily 或 weekly')
    days = 1 if period == 'daily' else 7
    start = day if days == 1 else day - timedelta(days=6)
    records = [r for r in items(start=start, end=day, min_score=60, favorite=False, sort='score') if r['analysis']][:10]
    groups = ['今日 AI 重要动态', '新模型和新产品发布', 'Agent 与 AI Native 进展', 'AIGC 视频与图像进展', '值得进一步研究的信息'] if days == 1 else ['本周 AI 行业重要变化', '技术发展趋势', 'AI 产品创新案例', '值得关注的商业机会', '对 AIGC 产品经理的启发', '下周值得跟踪的方向']
    lines = [f'# 情报站{"日报" if days == 1 else "周报"}：{start} — {day}', '', '时间范围按北京时间及原文发布时间；仅纳入当前分析有效、评分≥60的记录，最多10条，不足5条不补齐。', '本报告整理已保存分析，未进行额外联网核实；商业机会与跟踪方向为推断或建议。', '']
    if not records:
        lines.append('此时间范围暂无符合条件的情报。')
    used = set()
    for section in groups:
        lines.extend(['## ' + section, ''])
        section_count = 0
        for r in records:
            a = r['analysis']; cat = r['category']
            if days == 1:
                bucket = '新模型和新产品发布' if cat in ('大模型技术', 'AI 产品发布') else 'Agent 与 AI Native 进展' if cat in ('AI Agent', 'AI Native 产品') else 'AIGC 视频与图像进展' if cat in ('AIGC 视频生成', 'AIGC 图像生成') else '今日 AI 重要动态'
                if section == '值得进一步研究的信息':
                    if r['score'] >= 80:
                        lines.extend([f'- {r["title"]}：待验证方向：{a["uncertainties"]}；原文：<{r["url"]}>', ''])
                        section_count += 1
                    continue
                if section != bucket:
                    continue
            field = {'技术发展趋势': 'change', 'AI 产品创新案例': 'user_value', '值得关注的商业机会': 'business_value', '对 AIGC 产品经理的启发': 'pm_insight', '下周值得跟踪的方向': 'uncertainties'}.get(section, 'summary')
            # Weekly angles use distinct saved findings, capped at three per angle.
            if days == 7 and field != 'summary':
                finding = a[field].strip()
                if finding in used or section_count >= 3:
                    continue
                used.add(finding)
                lines.extend([f'- {finding}（来源：{r["title"]}，<{r["url"]}>）', ''])
            else:
                lines.extend([f'### {r["title"]}（{r["score"]}分）', a[field], f'原文：<{r["url"]}>', f'证据状态：{a["evidence"]}', ''])
            section_count += 1
        if not section_count:
            lines.extend(['暂无符合条件的独立条目，不补齐。', ''])
    return {'markdown': '\n'.join(lines), 'count': len(records), 'start': str(start), 'end': str(day)}

@app.get('/api/export')
def export(format: str = 'markdown'):
    records = items(q='', category='', start=None, end=None, min_score=0, favorite=False, sort='score')
    if format == 'xlsx':
        book = Workbook(); sheet = book.active; sheet.title = '情报知识库'
        sheet.append(['标题', '原文链接', '作者', '发布时间UTC', '主要分类', '总分', '收藏', '正文', '笔记', '分析JSON'])
        for r in records:
            values = [r['title'], r['url'], r['author'], r['published_at'], r['category'], r['score'], r['favorite'], r['content'], r['notes'], json.dumps(r['analysis'], ensure_ascii=False)]
            sheet.append(values)
            for cell in sheet[sheet.max_row]:
                if isinstance(cell.value, str): cell.data_type = 's'
        output = io.BytesIO(); book.save(output)
        return Response(output.getvalue(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': 'attachment; filename="intelligence.xlsx"'})
    if format != 'markdown':
        raise HTTPException(422, 'format 为 markdown 或 xlsx')
    lines = ['# 情报站知识库', '']
    for r in records:
        lines.extend(['## ' + r['title'], '原文：<' + r['url'] + '>', '发布时间：' + r['published_at'], '', r['content'], '', '个人笔记：' + r['notes'], '', '```json', json.dumps(r['analysis'], ensure_ascii=False, indent=2), '```', ''])
    return Response('\n'.join(lines), media_type='text/markdown', headers={'Content-Disposition': 'attachment; filename="intelligence.md"'})

app.mount('/', StaticFiles(directory=ROOT / 'static', html=True), name='static')
