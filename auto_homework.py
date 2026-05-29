"""
智慧树普通课程作业自动答题脚本。
通过 Playwright 点击选项 + 拦截保存请求。
用法: python auto_homework.py <作业URL>
"""
import asyncio
import json
import sys
import os
import re
from playwright.async_api import async_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fucker import Openai

def parse_homework_url(url):
    m = re.search(r'dohomework/([^/]+)/([^/]+)/([^/]+)/([^/]+)/(\d+)', url)
    if m:
        return {"recruitId": m.group(1), "stuExamId": m.group(2), "examId": m.group(3), "schoolId": m.group(4)}
    return None

def load_cookies_raw():
    cookies_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.json")
    if not os.path.exists(cookies_path):
        print("未找到 cookies.json，请先登录")
        return []
    with open(cookies_path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_cookies_pw(cookies):
    pw_cookies = []
    for c in cookies:
        domain = c.get("domain", "")
        if not domain:
            continue
        pw_cookies.append({"name": c["name"], "value": c["value"], "domain": domain, "path": c.get("path", "/"), "secure": c.get("secure", False), "httpOnly": False})
    return pw_cookies

def load_ai_config():
    from utils import getConfigPath
    config_path = getConfigPath()
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f).get("ai", {})
    return {}

def init_ai(ai_config, cookies_list):
    import requests as req
    session = req.Session()
    for c in cookies_list:
        session.cookies.set(c["name"], c["value"], domain=c.get("domain", ".zhihuishu.com"), path=c.get("path", "/"))
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Origin": "https://onlineexamh5new.zhihuishu.com", "Referer": "https://onlineexamh5new.zhihuishu.com/"})
    op_conf = ai_config.get("openai", {})
    if op_conf.get("api_key") and op_conf.get("api_key") != "sk-":
        print(f"使用外部 AI: {op_conf.get('model_name', 'unknown')}")
        return Openai(baseUrl=op_conf.get("api_base", "https://api.openai.com/v1"), apiKey=op_conf.get("api_key", ""), modelName=op_conf.get("model_name", "davinci"), stream=False)
    if ai_config.get("enabled", False) and ai_config.get("use_zhidao_ai", False):
        print("使用智慧树内置 AI")
        return Openai(useZhidao=True, zhiDaosession=session, stream=False)
    print("未配置 AI，将随机作答")
    return None

def load_cached_homework():
    capture_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exam_api_capture.json")
    if not os.path.exists(capture_path):
        return None
    with open(capture_path, "r", encoding="utf-8") as f:
        captured = json.load(f)
    for entry in captured:
        if "doHomework" in entry.get("url", ""):
            try:
                body = json.loads(entry["response_body"])
                if body.get("rt"):
                    return body["rt"]
            except Exception:
                pass
    return None

def get_ai_answer(op, question_name, question_type, options):
    if op is None:
        import random
        return [random.choice(options)["id"]] if question_type in (1, 14) else [s["id"] for s in random.sample(options, random.randint(2, len(options)))]
    choices = [{"id": o["id"], "content": o["content"]} for o in options]
    if question_type == 1: prompt = op.singleChoiceTemplate(question_name, choices)
    elif question_type == 2: prompt = op.multipleChoiceTemplate(question_name, choices)
    elif question_type == 14: prompt = op.judgementTemplate(question_name, choices)
    else: prompt = op.singleChoiceTemplate(question_name, choices)
    try:
        return op.generateAnswer(prompt)
    except Exception as e:
        print(f"  AI 答题失败: {e}")
        import random
        return [random.choice(options)["id"]] if question_type in (1, 14) else [s["id"] for s in random.sample(options, random.randint(2, len(options)))]

async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else input("请输入作业URL: ")
    url_params = parse_homework_url(url)
    if not url_params:
        print("无法解析 URL 参数")
        return
    print(f"URL 参数: {url_params}")

    cookies_raw = load_cookies_raw()
    ai_config = load_ai_config()
    op = init_ai(ai_config, cookies_raw)
    homework_data = load_cached_homework()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        cookies_pw = load_cookies_pw(cookies_raw)
        if cookies_pw:
            await context.add_cookies(cookies_pw)
            print(f"已注入 {len(cookies_pw)} 个 cookies")

        page = await context.new_page()

        async def handle_response(response):
            nonlocal homework_data
            req_url = response.url
            if "doHomework" in req_url:
                try:
                    body = await response.text()
                    data = json.loads(body)
                    if data.get("rt"):
                        homework_data = data["rt"]
                        print("\n[抓取] 获取到作业题目数据")
                except Exception:
                    pass

        page.on("response", handle_response)
        print(f"正在打开: {url}")
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(3)

        try:
            btn = page.locator("text=开始答题").first
            if await btn.is_visible(timeout=3000):
                print("点击: 开始答题")
                await btn.click()
                await page.wait_for_load_state("networkidle", timeout=15000)
                await asyncio.sleep(3)
        except Exception:
            pass

        if homework_data is None:
            await asyncio.sleep(5)
        if homework_data is None:
            print("未获取到作业数据")
            await asyncio.get_event_loop().run_in_executor(None, input)
            await browser.close()
            return

        questions = []
        for part in homework_data.get("examBase", {}).get("workExamParts", []):
            for q in part.get("questionDtos", []):
                questions.append(q)

        print(f"\n共 {len(questions)} 道题\n")

        # 先截图看页面结构
        await page.screenshot(path="D:/fuckZHS/page_structure.png")
        print("已截图: page_structure.png")
        print("请查看截图确认页面结构，然后按 Enter 开始答题...")
        await asyncio.get_event_loop().run_in_executor(None, input)

        for i, q in enumerate(questions):
            q_name = q.get("name", "")
            q_type = q.get("questionType", {}).get("id", 1)
            q_type_name = q.get("questionType", {}).get("name", "未知")
            options = q.get("questionOptions", [])

            print(f"\n第 {i+1} 题 [{q_type_name}]: {q_name[:60]}...")

            answer_ids = get_ai_answer(op, q_name, q_type, options)
            answer_contents = []
            for opt in options:
                if opt["id"] in answer_ids:
                    answer_contents.append(opt["content"])
            print(f"  AI 答案: {answer_contents}")

            # 用 JS 在页面上查找并点击选项
            for content in answer_contents:
                clean = re.sub(r'<[^>]+>', '', content).strip()
                clicked = await page.evaluate(f"""
                    () => {{
                        // 查找所有可能包含选项文本的元素
                        const allElements = document.querySelectorAll('label, .option, [class*="option"], [class*="Option"], [class*="item"], [class*="Item"], [class*="choose"], [class*="radio"], [class*="check"]');
                        for (const el of allElements) {{
                            if (el.textContent.includes('{clean}')) {{
                                el.click();
                                return true;
                            }}
                        }}
                        // 备选：查找所有包含文本的可点击元素
                        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                        while (walker.nextNode()) {{
                            if (walker.currentNode.textContent.includes('{clean}')) {{
                                let parent = walker.currentNode.parentElement;
                                while (parent && parent !== document.body) {{
                                    if (parent.tagName === 'LABEL' || parent.tagName === 'INPUT' || parent.onclick || parent.style.cursor === 'pointer' || parent.classList.length > 0) {{
                                        parent.click();
                                        return true;
                                    }}
                                    parent = parent.parentElement;
                                }}
                                // 最后尝试直接点击文本所在元素
                                walker.currentNode.parentElement.click();
                                return true;
                            }}
                        }}
                        return false;
                    }}
                """)
                if clicked:
                    print(f"  点击: {clean[:40]}")
                else:
                    print(f"  未找到: {clean[:40]}")
                await asyncio.sleep(0.5)

            await asyncio.sleep(1)

            # 截图确认选择状态
            await page.screenshot(path=f"D:/fuckZHS/q{i+1}_answered.png")

            # 点击下一题或提交
            if i < len(questions) - 1:
                try:
                    next_btn = page.locator("text=下一题").first
                    await next_btn.click()
                    print(f"  点击: 下一题")
                    await page.wait_for_load_state("networkidle", timeout=10000)
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"  下一题失败: {e}")
            else:
                try:
                    submit_btn = page.locator("text=提交作业").first
                    print(f"\n点击: 提交作业")
                    await submit_btn.click()
                    await asyncio.sleep(3)
                    try:
                        confirm = page.locator("text=确定, text=确认").first
                        if await confirm.is_visible(timeout=3000):
                            await confirm.click()
                            print("确认提交")
                    except Exception:
                        pass
                except Exception as e:
                    print(f"  提交失败: {e}")

        print("\n答题完成！截图已保存到 q*_answered.png")
        print("按 Enter 退出。")
        await asyncio.get_event_loop().run_in_executor(None, input)
        await browser.close()

asyncio.run(main())
