"""
ai_agent.py
------------

Safe agentic AI prototype (OpenAI + Selenium) for Windows/macOS/Linux.

HOW IT WORKS (summary):
- Opens a browser with Selenium.
- Loads a page you navigate to or a page specified in code.
- Sends the page text/HTML + a user task to OpenAI asking for a structured action plan (JSON).
- Displays the plan to you and asks for explicit approval.
- If you approve, executes the actions (click, fill, submit, navigate, wait) using Selenium.

SAFETY & USAGE:
- Must set OPENAI_API_KEY in a .env file (see README).
- Add sites/domains to ALLOWED_DOMAINS below before enabling execution.
- Always review the plan before approving. This script will not run actions without your approval.
- Do not use on banking/real-money/personal-sensitive sites until you've fully tested and understand risks.
"""

import os
import json
import time
import validators
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import openai

# -------------------------
# Configuration (edit me)
# -------------------------
# Whitelist domains where the agent is allowed to execute actions.
# Example: ["example.com", "localhost", "my.school.edu"]
ALLOWED_DOMAINS = ["example.com", "localhost"]

# Model to use. Use a capable model you have access to.
OPENAI_MODEL = "gpt-4"  # change if needed

# Timeout for page loads / waits
DEFAULT_WAIT = 2.0

# -------------------------
# Load API key from .env
# -------------------------
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    raise RuntimeError("OPENAI_API_KEY not found. Put it in a .env file in the same folder.")

# -------------------------
# Helpers
# -------------------------
def get_domain_from_url(url: str):
    try:
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        return parsed.netloc.replace("www.", "")
    except Exception:
        return ""

def ask_openai_for_plan(page_text: str, page_url: str, user_task: str) -> list:
    """
    Ask OpenAI to produce a JSON action plan.
    The plan should be a JSON array of actions, each:
      { "action": "click"|"fill"|"submit"|"navigate"|"wait",
        "by": "css"|"xpath"|"id"|"name"|"link_text",
        "selector": "<selector string>",
        "value": "<text to type (for fill) or url (for navigate)>"
      }
    The assistant should respond with JSON only.
    """
    system = (
        "You are a web automation planner. Given page text/HTML and a user task, "
        "produce a JSON array (and ONLY JSON) of the minimal steps needed to accomplish the task. "
        "Each step must be one of: click, fill, submit, navigate, wait. "
        "For click/fill/submit include a selector and selector type (css/xpath/id/name/link_text). "
        "For 'fill' include 'value'. For 'wait' include 'value' seconds. For 'navigate' include 'value' which is the URL."
        "Keep steps robust and minimal. Do not invent credentials or sensitive content."
    )

    user_prompt = (
        f"Page URL: {page_url}\n\n"
        f"Page text/HTML snippet (shortened):\n{page_text[:3000]}\n\n"
        f"User task: {user_task}\n\n"
        "Return only JSON. Example output:\n"
        '[\n  {\"action\":\"click\",\"by\":\"css\",\"selector\":\"#btn-continue\"},\n  {\"action\":\"fill\",\"by\":\"name\",\"selector\":\"email\",\"value\":\"example@example.com\"},\n  {\"action\":\"click\",\"by\":\"css\",\"selector\":\"button.submit\"}\n]\n'
    )

    resp = openai.ChatCompletion.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0
    )

    text = resp["choices"][0]["message"]["content"].strip()
    # Try to find JSON inside text and parse
    try:
        # Allow the model to include backticks or code fences; strip them
        if text.startswith("```"):
            # remove code fence
            text = "\n".join(text.splitlines()[1:-1])
        return json.loads(text)
    except Exception as e:
        raise RuntimeError(f"Failed to parse JSON from model response. Raw response:\n{text}\n\nError: {e}")

def find_element(driver, by, selector):
    by_map = {
        "css": By.CSS_SELECTOR,
        "xpath": By.XPATH,
        "id": By.ID,
        "name": By.NAME,
        "link_text": By.LINK_TEXT
    }
    if by not in by_map:
        raise ValueError(f"Unsupported selector type: {by}")
    return driver.find_element(by_map[by], selector)

def execute_plan(driver, plan):
    for i, step in enumerate(plan, start=1):
        action = step.get("action")
        by = step.get("by")
        selector = step.get("selector")
        value = step.get("value", "")
        print(f"[{i}/{len(plan)}] Action: {action}, by: {by}, selector: {selector}, value: {value}")

        try:
            if action == "wait":
                secs = float(value) if value else DEFAULT_WAIT
                time.sleep(secs)
            elif action == "navigate":
                if not validators.url(value):
                    raise ValueError("Invalid URL in navigate action.")
                driver.get(value)
                time.sleep(DEFAULT_WAIT)
            elif action in ("click", "fill", "submit"):
                elem = find_element(driver, by, selector)
                if action == "click":
                    elem.click()
                elif action == "fill":
                    elem.clear()
                    elem.send_keys(value)
                elif action == "submit":
                    try:
                        elem.submit()
                    except Exception:
                        # fallback: click
                        elem.click()
                time.sleep(0.5)
            else:
                print("Unknown action:", action)
        except Exception as e:
            print(f"Error executing step {i}: {e}")
            # stop on failure to avoid unsafe cascading actions
            return False
    return True

# -------------------------
# Main interactive routine
# -------------------------
def main():
    print("=== AI Agent (OpenAI + Selenium) ===")
    print("IMPORTANT: Add the domain to ALLOWED_DOMAINS before approving actions.")
    start_url = input("Enter the URL you want to open (or press Enter to open https://example.com): ").strip()
    if not start_url:
        start_url = "https://example.com"

    # Basic validation
    if not validators.url(start_url):
        print("Invalid URL. Exiting.")
        return

    domain = get_domain_from_url(start_url)
    print("Target domain:", domain)
    if domain not in ALLOWED_DOMAINS:
        print(f"WARNING: {domain} is not in ALLOWED_DOMAINS.")
        allow = input("Do you want to add it temporarily for this session? (type 'yes' to continue): ").strip().lower()
        if allow != "yes":
            print("Add the domain to ALLOWED_DOMAINS in the script to enable execution. Exiting.")
            return
        else:
            ALLOWED_DOMAINS.append(domain)
            print("Domain temporarily added for this session.")

    # Start browser
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
    driver.maximize_window()
    driver.get(start_url)
    time.sleep(DEFAULT_WAIT)

    print("Page loaded. Fetching page text for planning...")
    try:
        page_text = driver.find_element(By.TAG_NAME, "body").get_attribute("innerText")
    except Exception:
        page_text = driver.page_source[:5000]

    task = input("Describe the task you want the AI to perform on this page (be precise):\n> ").strip()
    if not task:
        print("No task provided. Exiting.")
        driver.quit()
        return

    print("Requesting plan from OpenAI...")
    try:
        plan = ask_openai_for_plan(page_text, start_url, task)
    except Exception as e:
        print("Failed to get plan:", e)
        driver.quit()
        return

    print("\n--- PLAN (from OpenAI) ---")
    print(json.dumps(plan, indent=2))
    print("--- END PLAN ---\n")

    # Safety checks on plan: ensure no navigation to outside domains unless explicitly allowed
    for step in plan:
        if step.get("action") == "navigate":
            nav_url = step.get("value", "")
            if nav_url:
                nav_domain = get_domain_from_url(nav_url)
                if nav_domain not in ALLOWED_DOMAINS:
                    print(f"Plan wants to navigate to disallowed domain: {nav_domain}")
                    print("Refusing to execute plan. Edit ALLOWED_DOMAINS if you trust this domain.")
                    driver.quit()
                    return

    approve = input("Approve execution of the above plan? Type 'yes' to execute: ").strip().lower()
    if approve != "yes":
        print("Plan not approved. Exiting without making changes.")
        driver.quit()
        return

    print("Executing plan...")
    success = execute_plan(driver, plan)
    if success:
        print("Plan executed successfully.")
    else:
        print("Plan execution failed or was stopped. Check logs above.")

    # Keep browser open briefly for inspection
    time.sleep(5)
    driver.quit()
    print("Browser closed. Done.")

if __name__ == "__main__":
    main()
