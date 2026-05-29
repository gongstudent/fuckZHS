"""
自动答题脚本：注入 cookies，打开作业页面，抓取答案，自动点击选项。
用法: python capture_exam.py <作业URL>
"""
import asyncio
import json
import sys
import os
from playwright.async_api import async_playwright

def load_cookies():
    cookies_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.json")
    if not os.path.exists(cookies_path):
        print("未找到 cookies.json，请先登录")
        return []
    with open(cookies_path, "r", encoding="utf-8") as f:
        cookies = json.load(f)
    pw_cookies = []
    for c in cookies:
        domain = c.get("domain", "")
        if not domain:
            continue
        pw_cookies.append({
            "name": c["name"],
            "value": c["value"],
            "domain": domain,
            "path": c.get("path", "/"),
            "secure": c.get("secure", False),
            "httpOnly": False,
        })
    return pw_cookies

captured = []
question_data = []  # 存储每道题的题目和选项

async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else input("请输入作业URL: ")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()

        # 注入 cookies
        cookies = load_cookies()
        if cookies:
            await context.add_cookies(cookies)
            print(f"已注入 {len(cookies)} 个 cookies")

        page = await context.new_page()

        # 拦截 API 响应
        async def handle_response(response):
            req_url = response.url
            if "zhihuishu.com" not in req_url:
                return
            try:
                body = await response.text()
            except Exception:
                return
            # 记录所有可能的 API 请求
            if any(k in req_url for k in ["/gateway/", "/api/", "/exam/", "/answer/", "/question/", "/homework/", "/stuExam/"]):
                entry = {
                    "method": response.request.method,
                    "url": req_url,
                    "status": response.status,
                    "request_post_data": response.request.post_data,
                    "response_body": body[:10000],
                }
                captured.append(entry)
                print(f"\n[API] {entry['method']} {req_url} -> {response.status}")

                # 尝试解析题目数据
                try:
                    data = json.loads(body)
                    if isinstance(data, dict):
                        # 查找题目相关数据
                        for key in ["data", "result", "body"]:
                            if key in data and isinstance(data[key], (dict, list)):
                                inner = data[key]
                                if isinstance(inner, dict):
                                    for qk in ["questions", "questionList", "examQuestions", "questionVos"]:
                                        if qk in inner:
                                            print(f"  >>> 发现题目数据: {qk}")
                                elif isinstance(inner, list) and len(inner) > 0:
                                    first = inner[0]
                                    if isinstance(first, dict) and ("content" in first or "questionContent" in first):
                                        print(f"  >>> 发现题目列表")
                except json.JSONDecodeError:
                    pass

        page.on("response", handle_response)

        print(f"正在打开: {url}")
        await page.goto(url, wait_until="networkidle", timeout=60000)
        print("页面加载完成，等待 5 秒收集请求...")
        await asyncio.sleep(5)

        # 尝试自动点击"开始答题"按钮
        try:
            btn = page.locator("text=开始答题").first
            if await btn.is_visible(timeout=3000):
                print("点击: 开始答题")
                await btn.click()
                await page.wait_for_load_state("networkidle", timeout=15000)
                await asyncio.sleep(3)
        except Exception:
            pass

        print(f"\n已捕获 {len(captured)} 条 API 请求。")
        print("请在浏览器中手动操作（如果需要），然后按 Enter 保存结果。")
        await asyncio.get_event_loop().run_in_executor(None, input)

        # 保存结果
        output_file = "exam_api_capture.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(captured, f, ensure_ascii=False, indent=2)

        print(f"\n已保存 {len(captured)} 条请求到 {output_file}")
        await browser.close()

asyncio.run(main())
