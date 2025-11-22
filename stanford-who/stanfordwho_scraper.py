#!/usr/bin/env python3
import argparse
import csv
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager


START_URL = "https://stanfordwho.stanford.edu/ords/r/regapps/swho/public-home"
OUTPUT_CSV = "/home/william/Projects/treebites-scraper/stanford-who/results.csv"
DEFAULT_WAIT_SECONDS = 20
PAGE_PAUSE_SECONDS = 1.0
ALLOW_PROFILE_NAV = False


@dataclass
class PersonRow:
	name: str
	email: str
	affiliation: str
	department: str


def launch_browser() -> webdriver.Chrome:
	options = webdriver.ChromeOptions()
	# Headed (visible) so you can log in and set filters
	options.add_argument("--start-maximized")
	driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
	return driver


def wait_for_any_selector(driver: webdriver.Chrome, selectors: List[str], timeout: int = DEFAULT_WAIT_SECONDS) -> None:
	wait = WebDriverWait(driver, timeout)
	for selector in selectors:
		try:
			wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
			return
		except TimeoutException:
			continue
	raise TimeoutException(f"No results found by any selector in: {selectors}")


def find_cards(driver: webdriver.Chrome) -> List[webdriver.Chrome]:
	# Try multiple likely result-card containers/selectors (APEX cards)
	candidates = [
		".t-Card",  # Oracle APEX card
		".t-ContentCard",
		".t-ContentRow",  # Oracle APEX list view row
		".t-ContentRow-wrap",
		".t-ContentRow-content",
		".t-SearchResults-item",
		".t-Region .t-Card",
		"li.a-IRR-tableRow",  # Interactive report rows as fallback
	]
	
	# Instead of returning the first match, we want to find the selector that yields the MOST items
	# or just aggregate them if they are non-overlapping?
	# Typically one selector type dominates the page structure.
	best_els = []
	for sel in candidates:
		els = driver.find_elements(By.CSS_SELECTOR, sel)
		if len(els) > len(best_els):
			best_els = els
			
	return best_els


def extract_email_from_text(text: str) -> Optional[str]:
	for token in text.split():
		if "@stanford.edu" in token:
			# Strip trailing punctuation
			return token.strip().strip(",;()[]")
	return None


def safe_text(el) -> str:
	try:
		return el.text or ""
	except Exception:
		return ""


def get_email_from_profile(driver: webdriver.Chrome, detail_href: str) -> Optional[str]:
	original_window = driver.current_window_handle
	driver.execute_script("window.open(arguments[0], '_blank');", detail_href)
	driver.switch_to.window(driver.window_handles[-1])
	try:
		# Wait a bit for content to load
		wait_for_any_selector(driver, [
			"a[href^='mailto:']",
			".t-Region, body"
		], timeout=DEFAULT_WAIT_SECONDS)
		# Try mailto links first
		mailtos = driver.find_elements(By.CSS_SELECTOR, "a[href^='mailto:']")
		for a in mailtos:
			href = a.get_attribute("href") or ""
			if "mailto:" in href:
				email = href.split("mailto:", 1)[-1].strip()
				if email:
					return email
		# Fallback: parse the page text for @stanford.edu
		page_text = safe_text(driver.find_element(By.TAG_NAME, "body"))
		return extract_email_from_text(page_text)
	finally:
		driver.close()
		driver.switch_to.window(original_window)


def parse_card(driver: webdriver.Chrome, card) -> Optional[PersonRow]:
	# Prefer to scope to the wrapper that contains both content and misc (email) sections
	scope_el = card
	for sel in [".t-ContentRow-wrap", ".t-Card-body", ".t-Card"]:
		try:
			# Check if this sub-element exists; if so, use it as the scope
			# ensuring we don't drill down into just 'content' and miss 'misc'
			candidate = card.find_element(By.CSS_SELECTOR, sel)
			scope_el = candidate
			break
		except Exception:
			continue

	text_lines = [ln.strip() for ln in (safe_text(scope_el).splitlines()) if ln.strip()]
	if not text_lines:
		# print(f"DEBUG: Empty text lines for card. Scope text was: {safe_text(scope_el)}")
		return None

	# Name: prefer a prominent title/link if present; else first line
	name_el = None
	for sel in [
		"a.t-Card-title",
		".t-Card-title a",
		".t-ContentCard-title a",
		".t-ContentRow-content h3 a",
		".t-ContentRow-content h3",
		"h3 a",
		"h3",
		"a",
	]:
		try:
			name_el = scope_el.find_element(By.CSS_SELECTOR, sel)
			break
		except Exception:
			continue
	name = (name_el.text.strip() if name_el and name_el.text else text_lines[0])

	# Department and affiliation heuristic: scan lines after the name
	rest = [ln for ln in text_lines if ln != name]
	department = ""
	affiliation = ""
	# Try more targeted APEX selectors for the two lines beneath the name
	try:
		desc_el = scope_el.find_element(By.CSS_SELECTOR, ".t-ContentRow-body .t-ContentRow-desc")
		desc_lines = [ln.strip() for ln in safe_text(desc_el).splitlines() if ln.strip()]
		if desc_lines:
			department = desc_lines[0]
		if len(desc_lines) > 1:
			affiliation = desc_lines[1]
	except Exception:
		if rest:
			department = rest[0]
		if len(rest) > 1:
			affiliation = rest[1]
	# Refine affiliation: pick the first line containing hyphen-separated role or containing 'Student'/'Faculty'
	for ln in rest[1:3]:
		if (" - " in ln) or ("Student" in ln) or ("Faculty" in ln) or ("Staff" in ln):
			affiliation = ln
			break

	# Email: prefer mailto link, else any text token with @stanford.edu, else go to profile
	email = None
	try:
		mail_links = scope_el.find_elements(By.CSS_SELECTOR, "a[href^='mailto:']")
		for a in mail_links:
			href = a.get_attribute("href") or ""
			if "mailto:" in href:
				email = href.split("mailto:", 1)[-1].strip()
				if email:
					break
	except Exception:
		pass
	if not email:
		# Fallback: scan visible text lines for @stanford.edu
		email = extract_email_from_text("\n".join(text_lines))

	# DEBUG: if still no email, print what lines we saw so we can debug selector issues
	if not email:
		# print(f"DEBUG: No email found for {name}. Text lines seen: {text_lines}")
		pass

	if ALLOW_PROFILE_NAV and (not email) and name_el:
		# Try to fetch from detail page
		href = name_el.get_attribute("href")
		if href:
			try:
				email = get_email_from_profile(driver, href)
			except Exception:
				email = None

	return PersonRow(
		name=name,
		email=email or "",
		affiliation=affiliation,
		department=department,
	)


def click_next_if_available(driver: webdriver.Chrome) -> bool:
	# Numeric pagination logic: find active page, click active+1
	try:
		# Find current active page number
		# APEX often uses <b> or <span> with specific classes for the current page
		candidates_active = [
			"strong[aria-current='page']",  # High specificity ARIA
			".t-Report-paginationText strong", # Common APEX pattern
			".t-Report-paginationLink.is-active",
			".t-Pagination-item.is-active",
			".t-Report-pagination b",
			".t-Report-pagination span.current",
			"table.a-IRR-pagination td span"
		]
		active_page_els = []
		for sel in candidates_active:
			found = driver.find_elements(By.CSS_SELECTOR, sel)
			if found:
				active_page_els = found
				print(f"DEBUG: Found active page element using '{sel}': {[e.text for e in found]}")
				break
		
		if not active_page_els:
			# Fallback: try standard Next button if no numeric pagination found
			print("DEBUG: No numeric active page indicator found.")
			pass
		else:
			current_page_text = active_page_els[0].text.strip()
			if current_page_text.isdigit():
				next_page_num = int(current_page_text) + 1
				print(f"DEBUG: Current page is {current_page_text}, looking for link to {next_page_num}")
				# Look for link with exact text of next page number
				# Using XPath for exact text match
				next_link_xpath = f"//a[contains(@class, 't-Report-paginationLink') and normalize-space(text())='{next_page_num}']"
				# Also try generic link inside pagination container
				generic_xpath = f"//*[contains(@class, 't-Report-pagination')]//a[normalize-space(text())='{next_page_num}']"
				
				for xp in [next_link_xpath, generic_xpath]:
					next_links = driver.find_elements(By.XPATH, xp)
					if next_links:
						print(f"Clicking numeric pagination link for page {next_page_num}")
						next_links[0].click()
						time.sleep(PAGE_PAUSE_SECONDS)
						return True
				print(f"DEBUG: Could not find link for page {next_page_num}")
	except Exception as e:
		print(f"Numeric pagination check failed: {e}")

	# Fallback to Next buttons (checking for > or Next text)
	candidates = [
		"a[aria-label='Next']",
		".t-Report-paginationLink--next",
		"a[title='Next']"
	]
	for sel in candidates:
		btns = driver.find_elements(By.CSS_SELECTOR, sel)
		if not btns:
			continue
		for btn in btns:
			try:
				if not btn.is_displayed() or not btn.is_enabled():
					continue
				print(f"Clicking fallback Next button: {sel}")
				btn.click()
				time.sleep(PAGE_PAUSE_SECONDS)
				return True
			except Exception:
				continue
	
	print("No active Next button or next page number found.")
	return False


def scrape_results(driver: webdriver.Chrome, csv_path: str) -> None:
	with open(csv_path, "w", encoding="utf-8", newline="") as f:
		writer = csv.writer(f)
		writer.writerow(["name", "email", "affiliation", "department"])

		page_index = 1
		while True:
			# Retry logic: wait for cards to appear (handling potential slow loads)
			cards = []
			start_time = time.time()
			while time.time() - start_time < DEFAULT_WAIT_SECONDS:
				try:
					cards = find_cards(driver)
					if cards:
						# Ensure elements are not stale by checking one property
						_ = cards[0].tag_name
						break
				except Exception:
					# Stale element or other error, retry
					cards = []
				time.sleep(1)
			
			if not cards:
				print(f"Warning: No cards found on page {page_index} after waiting {DEFAULT_WAIT_SECONDS}s.")
			
			print(f"Found {len(cards)} card elements on page {page_index}")
			for card in cards:
				row = parse_card(driver, card)
				if row:
					writer.writerow([row.name, row.email, row.affiliation, row.department])
				else:
					print("Skipped a card (parsed as None)")
			# Flush per page to avoid data loss
			f.flush()

			if not click_next_if_available(driver):
				break
			
			# Wait for the new page content to stabilize
			print("Waiting for page load...")
			time.sleep(1)  # increased from PAGE_PAUSE_SECONDS implicit wait
			
			page_index += 1


def main() -> int:
	global DEFAULT_WAIT_SECONDS
	parser = argparse.ArgumentParser(description="Scrape Stanford Who directory results into CSV.")
	parser.add_argument("--url", "-u", default=START_URL, help="Start URL (use file:///path/to/sample.html for local test)")
	parser.add_argument("--output", "-o", default=OUTPUT_CSV, help="Output CSV path")
	parser.add_argument("--headless", action="store_true", help="Run Chrome headlessly")
	parser.add_argument("--no-login-wait", action="store_true", help="Do not wait for manual login; start scraping immediately")
	parser.add_argument("--wait", type=int, default=DEFAULT_WAIT_SECONDS, help="Default explicit wait seconds")
	parser.add_argument("--follow-profile", action="store_true", help="Follow profile links to fetch missing emails (disabled by default)")
	args = parser.parse_args()

	DEFAULT_WAIT_SECONDS = args.wait
	global ALLOW_PROFILE_NAV
	ALLOW_PROFILE_NAV = args.follow_profile

	driver = launch_browser()
	if args.headless:
		print("Headless mode is not currently supported for manual login; ignoring --headless.")
	driver.get(args.url)
	print("A Chrome window has opened.")
	if not args.no_login_wait and args.url.startswith("http"):
		print("- Sign in manually.")
		print("- Apply any filters or search you want.")
		print("- Navigate to the results list view.")
		input("When results are visible, press Enter here to begin scraping...")
	else:
		print("Skipping login wait due to --no-login-wait or non-http URL.")
	try:
		scrape_results(driver, args.output)
		print(f"Saved results to: {args.output}")
	finally:
		# Keep browser open to review if needed; comment next line to persist
		driver.quit()
	return 0


if __name__ == "__main__":
	raise SystemExit(main())


