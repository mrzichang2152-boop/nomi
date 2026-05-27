from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")
        pages = [page for context in browser.contexts for page in context.pages]
        print("pages:")
        for page in pages:
            print(f"- {page.title()} :: {page.url[:100]}")

        whatsapp_pages = [page for page in pages if "web.whatsapp.com" in page.url]
        if not whatsapp_pages:
            raise SystemExit("WhatsApp page not found")

        checks = ["WhatsApp", "搜索或开始新聊天", "陈子扬", "测试", "端到端加密"]
        for index, whatsapp in enumerate(whatsapp_pages):
            whatsapp.bring_to_front()
            whatsapp.wait_for_timeout(1500)
            body_text = whatsapp.locator("body").inner_text(timeout=8000)
            print(f"whatsapp_page[{index}] title={whatsapp.title()} url={whatsapp.url}")
            print(f"body_len={len(body_text)}")
            for text in checks:
                print(f"contains[{text}]={text in body_text}")

            preview = body_text[:800].replace("\n", " | ")
            print(f"preview={preview}")

            if "陈子扬" in body_text:
                whatsapp.get_by_text("陈子扬", exact=True).first.click(timeout=5000)
                whatsapp.wait_for_timeout(2000)
                chat_text = whatsapp.locator("body").inner_text(timeout=8000)
                print(f"opened_chat_body_len={len(chat_text)}")
                print(f"opened_chat_contains[陈子扬]={'陈子扬' in chat_text}")
                print(f"opened_chat_contains[测试]={'测试' in chat_text}")
                print(f"opened_chat_contains[输入消息]={'输入消息' in chat_text}")
                chat_preview = chat_text[:1200].replace("\n", " | ")
                print(f"opened_chat_preview={chat_preview}")


if __name__ == "__main__":
    main()
