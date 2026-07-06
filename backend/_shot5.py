import asyncio
from playwright.async_api import async_playwright
from app.core.auth import create_access_token

USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


async def main():
    token = create_access_token(data={"sub": USER_ID})
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        await context.add_cookies([{
            "name": "access_token", "value": token,
            "domain": "10.185.1.180", "path": "/",
            "httpOnly": True, "sameSite": "Lax",
        }])
        page = await context.new_page()

        console_msgs = []
        page.on("console", lambda msg: console_msgs.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda exc: console_msgs.append(f"[pageerror] {exc}"))

        failed_requests = []
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url} -> {req.failure}"))

        responses = []
        def on_response(resp):
            if "/chat/stream" in resp.url or "/chat" in resp.url:
                responses.append(f"{resp.status} {resp.url}")
        page.on("response", on_response)

        await page.goto("http://10.185.1.180:3000/", wait_until="load")
        await page.wait_for_timeout(3000)

        # Find the chat input and send a message
        input_box = page.locator("textarea, input[type='text']").first
        await input_box.click()
        await input_box.fill("say the word hello and nothing else")
        await input_box.press("Enter")

        await page.wait_for_timeout(8000)
        await page.screenshot(path="/app/_shot_chat_attempt.png")

        print("=== CONSOLE ===")
        for m in console_msgs[-40:]:
            print(m)
        print("=== FAILED REQUESTS ===")
        for f in failed_requests:
            print(f)
        print("=== CHAT RESPONSES ===")
        for r in responses:
            print(r)

        await browser.close()

asyncio.run(main())
print("done")
