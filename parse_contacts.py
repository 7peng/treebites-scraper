#!/usr/bin/env python3
import argparse
import csv
import sys
from html.parser import HTMLParser
from typing import List, Optional, Tuple


class ContactNameExtractor(HTMLParser):
	"""
	Parse HTML and extract anchor text inside any <p> that contains the literal text 'Contact:'.
	We consider the remainder of that <p> as a contact section and collect text content of all <a> tags within it.
	"""

	def __init__(self) -> None:
		super().__init__(convert_charrefs=True)
		self.in_p: bool = False
		self.in_contact_p: bool = False
		self.in_anchor: bool = False
		self.current_anchor_text_parts: List[str] = []
		self.names_with_clubs: List[Tuple[str, str]] = []
		self.group_label_stack: List[Optional[str]] = []
		self.current_club: str = ""

	def handle_starttag(self, tag: str, attrs):
		if tag.lower() == "div":
			role = None
			aria_label = None
			for k, v in attrs:
				kl = k.lower()
				if kl == "role":
					role = (v or "").lower()
				elif kl == "aria-label":
					aria_label = v or ""
			if role == "group":
				self.group_label_stack.append(aria_label)
				self._update_current_club()
			else:
				self.group_label_stack.append(None)
		if tag.lower() == "p":
			self.in_p = True
		elif tag.lower() == "a" and self.in_contact_p:
			self.in_anchor = True
			self.current_anchor_text_parts = []

	def handle_endtag(self, tag: str):
		if tag.lower() == "a" and self.in_anchor:
			text = "".join(self.current_anchor_text_parts).strip()
			if text:
				self.names_with_clubs.append((text, self.current_club))
			self.in_anchor = False
			self.current_anchor_text_parts = []
		elif tag.lower() == "p" and self.in_p:
			self.in_p = False
			self.in_contact_p = False
		elif tag.lower() == "div":
			if self.group_label_stack:
				self.group_label_stack.pop()
				self._update_current_club()

	def handle_data(self, data: str):
		if self.in_p and not self.in_contact_p:
			# Detect the "Contact:" label inside the current <p>
			if "contact:" in data.lower():
				self.in_contact_p = True
		if self.in_anchor:
			self.current_anchor_text_parts.append(data)

	def _update_current_club(self) -> None:
		# Use the nearest ancestor div[role="group"]'s aria-label as the club name
		for label in reversed(self.group_label_stack):
			if label:
				self.current_club = label.strip()
				return
		self.current_club = ""

def extract_contact_names_with_clubs(html_content: str) -> List[Tuple[str, str]]:
	parser = ContactNameExtractor()
	parser.feed(html_content)
	return parser.names_with_clubs


def main(argv: List[str]) -> int:
	parser = argparse.ArgumentParser(description="Extract plain-text contact names with club from ListOfGroups HTML and output CSV.")
	parser.add_argument(
		"--input",
		"-i",
		default="/home/william/Projects/treebites-scraper/ListOfGroups.html",
		help="Path to the input HTML file (default: %(default)s)",
	)
	parser.add_argument(
		"--output",
		"-o",
		default="/home/william/Projects/treebites-scraper/contacts.csv",
		help="Path to the output CSV file (default: %(default)s)",
	)
	args = parser.parse_args(argv)

	try:
		with open(args.input, "r", encoding="utf-8", errors="ignore") as f:
			html_content = f.read()
	except OSError as e:
		print(f"Failed to read input HTML: {e}", file=sys.stderr)
		return 1

	names_with_clubs = extract_contact_names_with_clubs(html_content)

	try:
		with open(args.output, "w", encoding="utf-8", newline="") as f:
			writer = csv.writer(f)
			writer.writerow(["name", "club"])
			for name, club in names_with_clubs:
				writer.writerow([name, club])
	except OSError as e:
		print(f"Failed to write CSV: {e}", file=sys.stderr)
		return 1

	print(f"Wrote {len(names_with_clubs)} contacts to {args.output}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main(sys.argv[1:]))


