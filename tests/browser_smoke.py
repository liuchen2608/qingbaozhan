"""Optional real Chromium smoke test. Requires playwright and a disposable running server.

HUB_SMOKE_URL=http://127.0.0.1:8765 python tests/browser_smoke.py
Creates and deletes its own records; never run against an unknown database.
"""
import os
import uuid
from playwright.sync_api import sync_playwright, expect

token = uuid.uuid4().hex[:8]
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'), headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1280, 'height': 900})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(os.getenv('HUB_SMOKE_URL', 'http://127.0.0.1:8765'))
    expect(page.locator('#status')).to_contain_text('模型未配置')
    page.get_by_role('button', name='信息源', exact=True).click()
    page.locator('#add-source').click()
    page.locator('#source-form [name=name]').fill('浏览器来源' + token)
    page.locator('#source-form [name=url]').fill('https://example.com/source/' + token)
    page.locator('#source-form button[type=submit], #source-form button:not([type])').click()
    expect(page.locator('#source-list')).to_contain_text('浏览器来源' + token)
    page.locator('#source-list article').filter(has_text=token).get_by_role('button', name='停用', exact=True).click()
    expect(page.locator('#source-list article').filter(has_text=token).get_by_role('button', name='启用', exact=True)).to_be_visible()
    page.get_by_role('button', name='情报知识库', exact=True).click()
    page.locator('#add-item').click()
    page.locator('#item-form [name=title]').fill('浏览器测试' + token)
    page.locator('#item-form [name=url]').fill('https://example.com/news/' + token)
    page.locator('#item-form [name=content]').fill('这是浏览器验收记录，不是真实行业新闻。')
    page.locator('#item-form [name=published_at]').fill('2026-11-14T12:00')
    page.locator('#item-form [name=source_id]').select_option(label='浏览器来源' + token)
    page.locator('#item-form').get_by_role('button', name='保存', exact=True).click()
    card = page.locator('#items article').filter(has_text=token)
    expect(card).to_be_visible()
    card.get_by_role('button', name='AI 分析', exact=True).click()
    expect(page.locator('#message')).to_contain_text('尚未配置模型')
    card.get_by_role('button', name='查看分析', exact=True).click()
    page.get_by_text('人工分析／修订（结构化表单）', exact=True).click()
    form = page.locator('#detail-content form')
    for area in form.locator('textarea').all():
        area.fill('测试分析，实际效果未知，需核查原文。')
    for n in form.locator('input[type=number]').all():
        n.fill(n.get_attribute('max'))
    form.get_by_role('button', name='保存人工分析', exact=True).click()
    expect(page.locator('#message')).to_contain_text('人工分析已保存')
    expect(page.locator('#detail-content')).to_contain_text('100分')
    page.locator('#detail [data-close]').click()
    card.get_by_role('button', name='收藏', exact=True).click()
    expect(card).to_contain_text('★')
    page.locator('#filters [name=q]').fill(token)
    page.locator('#filters').get_by_role('button', name='筛选', exact=True).click()
    expect(page.locator('#items article')).to_have_count(1)
    page.get_by_role('button', name='日报与周报', exact=True).click()
    page.locator('#report-day').fill('2026-11-14')
    page.get_by_role('button', name='生成报告', exact=True).click()
    expect(page.locator('#report-output')).to_contain_text('浏览器测试' + token)
    with page.expect_download() as download:
        page.get_by_role('button', name='下载 Markdown', exact=True).click()
    assert download.value.suggested_filename.endswith('.md')
    with page.expect_download() as download:
        page.get_by_role('link', name='导出 Excel', exact=True).click()
    assert download.value.suggested_filename.endswith('.xlsx')
    page.set_viewport_size({'width': 390, 'height': 844})
    page.get_by_role('button', name='情报知识库', exact=True).click()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.on('dialog', lambda d: d.accept())
    card.get_by_role('button', name='删除', exact=True).click()
    expect(page.locator('#items article').filter(has_text=token)).to_have_count(0)
    page.get_by_role('button', name='信息源', exact=True).click()
    page.locator('#source-list article').filter(has_text=token).get_by_role('button', name='移除', exact=True).click()
    expect(page.locator('#source-list article').filter(has_text=token)).to_have_count(0)
    assert not errors, errors
    browser.close()
    print('PASS: Chromium source/item CRUD, no-key error, manual analysis, favorite, search, report, downloads, mobile width; no page errors')
