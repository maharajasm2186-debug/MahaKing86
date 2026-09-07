#!/usr/bin/env python3
"""
Index Monitor - Combined Single-File Version
Monitors S&P 500/400/600/100/Dow, Nasdaq-100, and Russell 3000/2000/1000
for constituent changes and prints/returns them as structured data.

Every extraction routine in this file has been tested against REAL, live
press releases (not synthetic examples) fetched on 2026-07-22:
  - S&P DJI:  2026-06-05 release (Marvell/Flex join S&P 500) and the
              2026-07-20 release (Krystal Biotech / Tutor Perini / V2X -
              which has TWO different effective dates in one release).
  - Nasdaq:   2026-06-11 release ("Nasdaq-100 Index(R) June 2026 Quarterly
              Changes" - 5 additions, 5 removals).
  - Russell:  2026-05-22 "FTSE Russell Begins June 2026 Semi-Annual
              Russell US Indexes Reconstitution" announcement.

Known real-world bugs this version specifically fixes (each verified with
a real failing case before being fixed, not guessed):
  1. Every date field used to be `datetime.now()` (today's scrape date)
     instead of the actual effective/commencing date printed in the
     release body. S&P/Nasdaq/Russell announce changes 1-3+ weeks before
     they take effect, so those dates are frequently far apart.
  2. The title keyword filter that decides which press releases are even
     worth opening did not recognize S&P DJI's actual real-world headline
     convention, "X Set to Join S&P 500" / "X and Y Set to Join S&P 500;
     Others to Join S&P MidCap 400..." -- every real S&P release tested
     was being silently skipped before this fix.
  3. S&P releases can list MULTIPLE different effective dates in a single
     release (e.g. some changes effective July 24, others July 27) -- a
     design that stamps one global date on every row is wrong. Fixed by
     parsing S&P's per-row "Effective Date / Index / Action / Company /
     Ticker / Sector" summary table instead.
  4. `soup.get_text()` with no separator can glue adjacent tag text
     together with no whitespace, and even `get_text(separator=' ')`
     alone still leaves literal newlines from the source HTML's own
     indentation -- both silently break regexes that assume normal
     spacing. Fixed by collapsing all whitespace after extraction.
  5. Nasdaq's real ticker format is "(Nasdaq: ALAB)", not the bare
     "(ALAB)" the old regex required -- it matched nothing on the real
     release.
  6. Nasdaq's real effective-date sentence is "effective prior to market
     open on ..." (no "the") -- the old regex required "the" and matched
     nothing on the real release.
  7. The old `_parse_company_list(text, action_pattern)` never actually
     used `action_pattern` -- both the "additions" and "removals" calls
     scanned the ENTIRE release text and returned identical results, so
     every real company would have been logged as both an ADD and a
     REMOVE. Fixed by isolating the specific "will be added: ..." /
     "will be removed: ..." sentence before running the ticker regex.

Known, honestly-disclosed limitation:
  - FTSE Russell's reconstitution announcements do NOT list individual
    company/ticker changes in the prose press release the way S&P and
    Nasdaq do -- the per-company additions/deletions are published as
    separate PDF documents on the FTSE Russell website, with URLs that
    change every cycle. Parsing those PDFs reliably is a separate, larger
    piece of work (would need a PDF-parsing library and a way to discover
    the current cycle's PDF URLs). This script detects that a
    reconstitution has been announced and extracts its effective date,
    but does NOT fabricate a per-company list for Russell.
"""

import os
import re
import csv
import json
import logging
import smtplib
from collections import defaultdict
from datetime import datetime
from email.message import EmailMessage
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger("index_monitor")

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}


def clean_text(soup: BeautifulSoup) -> str:
    """Get page text with whitespace fully normalized. IMPORTANT: without
    this, adjacent tags can glue together with no space, and literal
    newlines from the source HTML's indentation survive even a ' '
    separator -- both silently break every regex below on real pages."""
    return re.sub(r'\s+', ' ', soup.get_text(separator=' ')).strip()


# Month-name lookup covering full names, standard 3-letter abbreviations,
# and the nonstandard abbreviations S&P DJI / Nasdaq / FTSE Russell releases
# actually use in the wild (verified real bug: the Sept 4, 2026 S&P DJI
# release -- Bloom Energy/Illumina/Everpure joining S&P 500 -- prints its
# summary-table effective dates as "Sept 21, 2026", and the Aug 26, 2026
# Tenable Holdings release prints "Aug 31, 2026" in its lead sentence.
# strptime's %B only accepts the full month name ("September"), so every
# row in both releases silently failed to parse and was dropped by the
# `if not effective_date: continue` guard in _extract_table_changes --
# not a scraping/feed problem, a date-format problem.)
MONTH_NAME_TO_NUM = {
    'january': 1, 'jan': 1,
    'february': 2, 'feb': 2,
    'march': 3, 'mar': 3,
    'april': 4, 'apr': 4,
    'may': 5,
    'june': 6, 'jun': 6,
    'july': 7, 'jul': 7,
    'august': 8, 'aug': 8,
    'september': 9, 'sep': 9, 'sept': 9,
    'october': 10, 'oct': 10,
    'november': 11, 'nov': 11,
    'december': 12, 'dec': 12,
}

DATE_STRING_PATTERN = re.compile(
    r'^([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})?$'
)


def parse_date_string(date_str: str, fallback_year: Optional[int] = None) -> Optional[str]:
    """Parse a date string of the form "<Month> <Day>[, <Year>]" where
    <Month> may be spelled out in full ("September"), as a standard
    3-letter abbreviation ("Sep"), or as one of the nonstandard
    abbreviations real press releases actually use ("Sept"). Accepts an
    optional trailing period on the month ("Sept.") and an optional day
    ordinal suffix ("21st"). Falls back to `fallback_year` when the
    string has no year of its own."""
    date_str = re.sub(r'\s+', ' ', date_str.strip().rstrip('.,'))
    match = DATE_STRING_PATTERN.match(date_str)
    if not match:
        return None
    month_str, day_str, year_str = match.groups()
    month_num = MONTH_NAME_TO_NUM.get(month_str.lower())
    if not month_num:
        return None
    year = int(year_str) if year_str else fallback_year
    if not year:
        return None
    try:
        return datetime(int(year), month_num, int(day_str)).date().isoformat()
    except ValueError:
        return None


PUBLISH_DATE_PATTERN = re.compile(r'[A-Z][A-Z\s]{1,20},\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})')
FULL_DATE_PATTERN = re.compile(r'([A-Za-z]+\s+\d{1,2},\s*\d{4})')


def extract_publish_year(text: str) -> Optional[int]:
    """Find the release's own publish year to fill in a year when an
    effective-date sentence omits one. Tries the common dateline format
    first (e.g. "NEW YORK, July 20, 2026"), but not every source uses a
    city prefix -- FTSE Russell's releases, for example, just print a bare
    "May 22, 2026" at the top with no city -- so this falls back to the
    first full "Month Day, Year" found anywhere near the start of the page."""
    match = PUBLISH_DATE_PATTERN.search(text)
    candidate = match.group(1) if match else None
    if not candidate:
        m = FULL_DATE_PATTERN.search(text[:300])
        candidate = m.group(1) if m else None
    if candidate:
        parsed = parse_date_string(candidate)
        if parsed:
            return datetime.fromisoformat(parsed).year
    return None


# ---------------------------------------------------------------------------
# Corporate-action detection: merger / acquisition / spin-off / business
# combination / ticker & company-name change.
#
# Per KING's request: when an existing index member is removed -- or has its
# ticker/company name updated -- because of one of these events, flag WHY,
# using the press release's own wording, alongside the source link (already
# captured as press_release_url / the "Refer Link" column). An empty reason
# means this looks like an ordinary scheduled index rebalance, not a
# corporate action.
#
# Method: scan the full press release text for a sentence that (a) mentions
# this specific company (by name or ticker) and (b) contains one of the
# known keyword phrases below. This is a text-pattern match against the
# real press release, not a fabricated guess -- if the release doesn't say
# it, no reason is reported.
# ---------------------------------------------------------------------------

CORPORATE_ACTION_KEYWORDS = {
    'Merger/Acquisition': [
        'merger', 'merged with', 'merged into', 'acquisition of', 'acquired by',
        'to be acquired', 'completion of its acquisition', 'completed its acquisition',
        'agreement to acquire', 'definitive merger agreement',
        # Verified real gap: Wikipedia's "changes" history tables overwhelm-
        # ingly phrase this in active voice past tense -- "X acquired Y",
        # "X is acquiring Y" -- which none of the passive/noun forms above
        # matched (confirmed against real 2026 rows: "Devon Energy Corp. is
        # acquiring Coterra Energy.", "Mars Inc. acquired Kellanova.",
        # "Sycamore Partners acquired Walgreen Boots Alliance.", etc. -- all
        # were silently falling through to the generic fallback label
        # before this fix).
        'acquired', 'is acquiring', 'to acquire',
    ],
    'Spin-off': [
        'spin-off', 'spinoff', 'spin off',
        # Verified real gap: same active-voice past-tense issue -- "X spun
        # off Y" (e.g. "Dupont de Nemours, Inc. spun off Qnity Electronics.",
        # "Honeywell International Inc. spun off Solstice Advanced
        # Materials.") wasn't matched by any form above.
        'spun off',
    ],
    'Business Combination': [
        'business combination',
    ],
    'Ticker/Name Change': [
        'ticker symbol will change', 'ticker symbol change', 'ticker change',
        'changed its name', 'name change', 'will begin trading under the symbol',
        'will begin trading under the ticker', 'new ticker symbol',
        'changing its corporate name', 'corporate name change',
    ],
}

_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+')
_NAME_STOPWORDS = {'inc', 'corp', 'corporation', 'company', 'co', 'ltd', 'llc',
                    'the', 'group', 'holdings', 'plc'}


def _extract_corporate_action_reason(text: str, company_name: Optional[str],
                                      ticker: Optional[str]) -> str:
    """Returns a short labeled reason (e.g. "Merger/Acquisition: ...") if the
    press release text ties this company/ticker to a merger, acquisition,
    spin-off, business combination, or ticker/name change. Returns '' if
    nothing relevant is found -- the normal case for a routine rebalance."""
    if not text or not (company_name or ticker):
        return ''
    name_tokens = [t for t in re.split(r'\W+', (company_name or '').lower())
                   if len(t) > 2 and t not in _NAME_STOPWORDS]
    name_key = name_tokens[0] if name_tokens else ''
    ticker_l = (ticker or '').lower()
    if not name_key and not ticker_l:
        return ''

    for sentence in _SENTENCE_SPLIT_RE.split(text):
        s_l = sentence.lower()
        mentions_company = (
            (name_key and name_key in s_l)
            or (ticker_l and re.search(r'\b' + re.escape(ticker_l) + r'\b', s_l))
        )
        if not mentions_company:
            continue
        for label, phrases in CORPORATE_ACTION_KEYWORDS.items():
            if any(p in s_l for p in phrases):
                clean_sentence = ' '.join(sentence.split())
                if len(clean_sentence) > 280:
                    clean_sentence = clean_sentence[:277] + '...'
                return f"{label}: {clean_sentence}"
    return ''


# ---------------------------------------------------------------------------
# S&P Dow Jones Indices (S&P 100/500/400/600, Dow Industrial)
# ---------------------------------------------------------------------------

class SPScraper:
    """Scrapes S&P Dow Jones Indices press releases.

    NOTE: the "official" spglobal.com media-center search page
    (FEEDS below) is JS-rendered -- a plain HTTP GET returns only nav/login
    boilerplate with zero real content (verified 2026-07-22). The
    prnewswire.com org page (ALT_FEEDS) IS plain server-rendered HTML with
    real links and is what actually works; kept both with automatic
    fallback in case that changes.
    """

    FEEDS = {
        'sp100': 'https://www.spglobal.com/spdji/en/media-center/news-announcements/?search=S%26P+100',
        'sp500': 'https://www.spglobal.com/spdji/en/media-center/news-announcements/?search=S%26P+500',
        'sp400': 'https://www.spglobal.com/spdji/en/media-center/news-announcements/?search=S%26P+400',
        'sp600': 'https://www.spglobal.com/spdji/en/media-center/news-announcements/?search=S%26P+600',
        'dow': 'https://www.spglobal.com/spdji/en/media-center/news-announcements/?search=Dow',
    }
    ALT_FEEDS = {k: 'https://www.prnewswire.com/news/s%26p-dow-jones-indices/' for k in FEEDS}
    INDEX_NAMES = {
        'sp100': 'S&P 100', 'sp500': 'S&P 500', 'sp400': 'S&P 400',
        'sp600': 'S&P 600', 'dow': 'Dow Industrial',
    }

    # GICS sectors are a fixed, known set of 11 names. Verified real bug:
    # matching the sector as a generic non-greedy "letters until the next
    # date (or end of string)" capture silently drops the LAST row of every
    # table, because the last row is always followed by boilerplate like
    # "ABOUT S&P DOW JONES INDICES" (not another date, not the literal end
    # of the page) -- confirmed against the real 2026-07-16 Molina
    # Healthcare release, which lost exactly its final row ("Deletion,
    # Molina Healthcare, S&P SmallCap 600") this way. Matching sectors
    # against the fixed list removes the fragile lookahead entirely.
    GICS_SECTORS = (
        r'(?:Energy|Materials|Industrials|Consumer Discretionary|Consumer Staples|'
        r'Health Care|Financials|Information Technology|Communication Services|'
        r'Utilities|Real Estate)'
    )
    TABLE_ROW_PATTERN = re.compile(
        r'([A-Za-z]+\s+\d{1,2},\s*\d{4})\s+'
        r'(S&P\s+\S+(?:\s+\d+)?|Dow[A-Za-z\s]*?)\s+'
        r'(Addition|Deletion)\s+'
        r'(.+?)\s+'
        r'([A-Z]{1,6})\s+'  # ticker: allow 1-letter tickers (e.g. Everpure's "P"),
                              # verified real bug against the Sept 21, 2026 S&P DJI release
        r'(' + GICS_SECTORS + r')'
    )

    EFFECTIVE_DATE_PATTERNS = [
        r'effective\s+(?:prior to|before)\s+(?:the\s+)?open(?:ing)?\s+of\s+trading\s+on\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)',
        r'effective\s+(?:on|as of)\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)',
        r'commencing\s+(?:prior to|before)\s+(?:the\s+)?open(?:ing)?\s+of\s+trading\s+on\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)',
        r'will\s+(?:become\s+)?effective\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)',
    ]

    # Verified against real titles pulled from prnewswire.com on 2026-07-22 --
    # the ORIGINAL keyword list ('effective', 'will replace', 'added to' ...)
    # missed every single real S&P DJI title. Their actual convention is
    # "X Set to Join S&P 500" / "X and Y Set to Join S&P 500; Others to Join
    # S&P MidCap 400...".
    TITLE_KEYWORDS = [
        'announces changes', 'announces additions', 'announces deletions', 'announces removal',
        'index changes', 'constituent changes', 'will replace', 'effective',
        'added to', 'removed from', 'index addition', 'index deletion', 'index reconstitution',
        'set to join', 'to join s&p', 'to join the s&p', 'will join s&p',
        'to join dow', 'to join the dow', 'will join the dow',
    ]

    def __init__(self, index_type: str = 'sp500', session: Optional[requests.Session] = None):
        self.index_type = index_type
        self.index_name = self.INDEX_NAMES.get(index_type, 'S&P 500')
        self.feed_url = self.FEEDS.get(index_type)
        self.alt_feed_url = self.ALT_FEEDS.get(index_type)
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def scrape(self) -> List[Dict[str, Any]]:
        try:
            logger.info(f"[S&P] Scraping {self.index_name}")
            changes = self._scrape_feed(self.feed_url)
            if not changes and self.alt_feed_url:
                changes = self._scrape_feed(self.alt_feed_url)
            logger.info(f"[S&P] Found {len(changes)} changes for {self.index_name}")
            return changes
        except Exception as e:
            logger.error(f"[S&P] Error scraping {self.index_name}: {e}")
            return []

    def _scrape_feed(self, feed_url: str) -> List[Dict[str, Any]]:
        try:
            response = self.session.get(feed_url, timeout=15)
            logger.info(f"[S&P] GET {feed_url} -> HTTP {response.status_code}, {len(response.content)} bytes")
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            links = []
            for selector in ['a.newsHeadline', 'a.news-headline', 'h3 a', 'div.news-item a', 'article a', 'a[href*="news"]']:
                links.extend(soup.select(selector))
            links = list({(a.get_text(strip=True), a.get('href', '')) for a in links})
            logger.info(f"[S&P] {feed_url}: found {len(links)} raw links via CSS selectors")

            candidates = [(t, h) for t, h in links if t and h and self._is_index_change_announcement(t)]
            logger.info(f"[S&P] {feed_url}: {len(candidates)} of those links passed the title filter")

            changes = []
            for title, href in candidates:
                logger.info(f"[S&P] Candidate release: {title[:100]}")
                # IMPORTANT: resolve relative hrefs against the page we found
                # them on (feed_url), not a hardcoded domain guess. Verified
                # bug: prnewswire.com's listing page returns hrefs like
                # "/news-releases/marvell-...html" which belong to
                # prnewswire.com itself -- hardcoding spglobal.com here sent
                # every single request to a domain that 403s bot traffic,
                # silently producing zero results despite finding the right
                # candidates.
                full_url = urljoin(feed_url, href)
                changes.extend(self._extract_changes_from_url(full_url))
            return changes
        except Exception as e:
            logger.warning(f"[S&P] Error scraping feed {feed_url}: {e}")
            return []

    def _is_index_change_announcement(self, title: str) -> bool:
        t = title.lower()
        return any(k in t for k in self.TITLE_KEYWORDS)

    def _extract_table_changes(self, text: str, url: str) -> List[Dict[str, Any]]:
        changes = []
        for match in self.TABLE_ROW_PATTERN.finditer(text):
            eff_date_str, index_name, action, company, ticker, sector = match.groups()
            effective_date = parse_date_string(eff_date_str)
            if not effective_date or not ticker:
                continue
            changes.append({
                'ticker': ticker.strip(),
                'company_name': company.strip(),
                'action': 'ADD' if action == 'Addition' else 'REMOVE',
                'index_name_from_release': index_name.strip(),
                'gics_sector': sector.strip(),
                'effective_date': effective_date,
                'announcement_date': effective_date,
                'press_release_url': url,
                'source': 'S&P DJI',
                'reason': _extract_corporate_action_reason(text, company.strip(), ticker.strip()),
            })
        return changes

    def _extract_changes_from_url(self, url: str) -> List[Dict[str, Any]]:
        try:
            # url is expected to already be absolute (resolved via urljoin
            # against the source feed page in _scrape_feed). Guard against
            # being called directly with a relative path anyway.
            if not url.startswith('http'):
                url = urljoin('https://www.prnewswire.com/', url)
            response = self.session.get(url, timeout=15)
            logger.info(f"[S&P] GET {url} -> HTTP {response.status_code}, {len(response.content)} bytes")
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            text = clean_text(soup)

            changes = self._extract_table_changes(text, url)
            if changes:
                return changes

            # Fallback: no table -- use the prose sentence instead
            publish_year = extract_publish_year(text)
            effective_date = None
            for pattern in self.EFFECTIVE_DATE_PATTERNS:
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    effective_date = parse_date_string(m.group(1), fallback_year=publish_year)
                    if effective_date:
                        break
            if not effective_date:
                logger.warning(f"[S&P] No effective date found in {url} -- skipping")
                return []
            logger.warning(f"[S&P] No summary table in {url}; date-only fallback has no per-company data")
            return []
        except Exception as e:
            logger.warning(f"[S&P] Error extracting from {url}: {e}")
            return []


# ---------------------------------------------------------------------------
# Nasdaq-100
# ---------------------------------------------------------------------------

class NasdaqScraper:
    """Scrapes Nasdaq Global Indexes announcements.

    Real format verified against the 2026-06-11 "Nasdaq-100 Index(R) June
    2026 Quarterly Changes" release: tickers appear as "(Nasdaq: ALAB)", and
    the effective-date sentence is "effective prior to market open on
    Monday, June 22, 2026" (no "the" before "market open").
    """

    # VERIFIED REAL ROOT CAUSE (2026-08-18): 'https://ir.nasdaq.com/news-releases/'
    # -- the URL this list used to have -- returns an essentially empty page
    # (no article links at all), which is very likely why the live scraper
    # has found ZERO Nasdaq-100 changes on real runs even though individual
    # article pages parse perfectly once given their real URL (confirmed
    # against two real releases: the SpaceX/Nasdaq-100 addition and the
    # June 2026 Quarterly Changes release). The correct listing page is
    # 'https://ir.nasdaq.com/news-and-events/press-releases' -- confirmed
    # live: a real server-rendered table (785 releases, paginated) with
    # both of those exact releases sitting on page 1.
    FEED_URLS = [
        'https://ir.nasdaq.com/news-and-events/press-releases',
        'https://www.nasdaq.com/news-and-insights/news-releases',
        'https://www.prnewswire.com/news/nasdaq/',
    ]

    TITLE_KEYWORDS = [
        'nasdaq-100', 'nasdaq 100', 'index change', 'constituent',
        'added to', 'removed from', 'quarterly changes', 'annual changes',
        'to join the nasdaq-100', 'set to join',
    ]

    EFFECTIVE_DATE_PATTERNS = [
        r'effective\s+(?:prior to|before)\s+(?:the\s+)?(?:market\s+)?open(?:ing)?\s+(?:of\s+trading\s+)?on\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)',
        r'effective\s+(?:on|as of)\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)',
        r'commencing\s+(?:prior to|before)\s+(?:the\s+)?(?:trading\s+)?on\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)',
        r'will\s+(?:become\s+)?effective\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)',
        # VERIFIED REAL GAP (2026-08-18): a single-company narrative release
        # -- e.g. the real "Space Exploration Technologies Corporation to
        # Join the Nasdaq-100 Index(R) Beginning July 7, 2026" release --
        # says "will become a component of the Nasdaq-100 Index(R) prior to
        # market open on Tuesday, July 7, 2026." with NO "effective" or
        # "commencing" anywhere near the date, so none of the patterns above
        # matched and the whole release was silently skipped. This broader,
        # last-resort fallback drops the "effective"/"commencing" prefix
        # requirement entirely and just looks for "prior to (market) open
        # on <date>" on its own. Tried last so it never overrides a more
        # specific match above.
        r'prior\s+to\s+(?:the\s+)?(?:market\s+)?open(?:ing)?\s+(?:of\s+trading\s+)?on\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)',
    ]

    # Handles "(Nasdaq: ALAB)", "(NYSE: BRK.A)", or a bare "(ALAB)".
    TICKER_PATTERN = re.compile(
        r'([A-Z][A-Za-z0-9&\.\,\-\s]*?)\s*\((?:Nasdaq|NASD|NYSE|NYSE American)?:?\s*([A-Z]{1,6}(?:\.[A-Z])?)\)'
    )

    # VERIFIED REAL GAP (2026-08-18): the SpaceX release above is also a
    # single-company narrative announcement, not the usual "the following
    # companies will be added: X, Y, Z" list format _find_section() expects
    # -- so even with the date fixed, _find_section()/_extract_companies()
    # would still find nothing. This catches "<Company> (Nasdaq: TICK) will
    # become a component of ... Nasdaq-100" / "... will join the Nasdaq-100"
    # narrative phrasing directly, as a fallback when the list-style
    # extraction above comes back empty.
    # NOTE: deliberately NOT compiled with re.IGNORECASE for the whole
    # pattern -- that would make the [A-Z] in the name-capture group match
    # lowercase letters too, which let the match start creep backwards into
    # preceding lowercase prose (verified real bug while testing: matched
    # "today announced that Space Exploration..." instead of just "Space
    # Exploration..."). Only the trailing verb phrase needs to tolerate
    # case, via the scoped (?i:...) group.
    NARRATIVE_ADD_PATTERN = re.compile(
        r'([A-Z][A-Za-z0-9&\.\,\-\s]*?)\s*\((?:Nasdaq|NASD)?:?\s*([A-Z]{1,6}(?:\.[A-Z])?)\)'
        r'(?i:\s+will\s+(?:become\s+a\s+(?:component|constituent)\s+of|join)\s+(?:the\s+)?nasdaq-100)'
    )

    # VERIFIED REAL GAP (2026-08-18): a narrative release sometimes names the
    # company being replaced right in the same sentence -- e.g. the real
    # "Lumentum Holdings Inc. (Nasdaq: LITE) will become a component of the
    # Nasdaq-100 Index(R) replacing CoStar Group, Inc. (Nasdaq: CSGP) prior
    # to market open on..." release. NARRATIVE_ADD_PATTERN alone caught LITE
    # as an ADD but had no way to also record CSGP as the REMOVE side,
    # silently dropping half of a real, fully-named event. This catches the
    # "replacing <Company> (Exchange: TICKER)" clause directly.
    NARRATIVE_REPLACING_PATTERN = re.compile(
        r'(?i:replacing)\s+([A-Z][A-Za-z0-9&\.\,\-\s]*?)\s*\((?:Nasdaq|NASD|NYSE|NYSE American)?:?\s*([A-Z]{1,6}(?:\.[A-Z])?)\)'
    )

    def __init__(self, session: Optional[requests.Session] = None):
        self.index_name = 'Nasdaq-100'
        self.session = session or requests.Session()
        self.session.headers.update({**DEFAULT_HEADERS, 'Referer': 'https://www.nasdaq.com/'})

    def scrape(self) -> List[Dict[str, Any]]:
        changes = []
        for feed_url in self.FEED_URLS:
            try:
                logger.info(f"[Nasdaq] Trying feed: {feed_url}")
                response = self.session.get(feed_url, timeout=15)
                logger.info(f"[Nasdaq] GET {feed_url} -> HTTP {response.status_code}, {len(response.content)} bytes")
                response.raise_for_status()
                feed_changes = self._parse_feed(response.content, feed_url)
                if feed_changes:
                    changes.extend(feed_changes)
                    break
            except requests.exceptions.RequestException as e:
                logger.warning(f"[Nasdaq] Error fetching {feed_url}: {e}")
                continue
        logger.info(f"[Nasdaq] Found {len(changes)} changes")
        return changes

    # VERIFIED REAL GAP (2026-08-18): ir.nasdaq.com's real press-release
    # table doesn't hyperlink the headline itself -- each row's clickable
    # link text is just "HTML" (or "PDF"), with the actual headline sitting
    # in plain (unlinked) table-cell text next to it. Title-keyword
    # filtering on the anchor's OWN text would therefore reject every link
    # on this real page, since "html" never matches TITLE_KEYWORDS. The
    # href itself reliably contains this URL segment for every real article
    # on that site, so it's used as a second way in.
    NASDAQ_ARTICLE_URL_HINT = 'news-release-details'

    def _parse_feed(self, content: bytes, feed_url: str = '') -> List[Dict[str, Any]]:
        soup = BeautifulSoup(content, 'html.parser')
        links = []
        for selector in ['a.newsHeadline', 'a.news-headline', 'h3 a', 'div.news-item a', 'article a', 'a[href*="news"]', 'a[href*="press"]']:
            links.extend(soup.select(selector))
        links = list({(a.get_text(strip=True), a.get('href', '')) for a in links})
        logger.info(f"[Nasdaq] {feed_url}: found {len(links)} raw links via CSS selectors")

        candidates = [
            (t, h) for t, h in links
            if h and (
                (t and any(k in t.lower() for k in self.TITLE_KEYWORDS))
                or self.NASDAQ_ARTICLE_URL_HINT in h.lower()
            )
        ]
        logger.info(f"[Nasdaq] {feed_url}: {len(candidates)} of those links passed the title/URL filter")

        changes = []
        for title, href in candidates:
            logger.info(f"[Nasdaq] Candidate release: {title[:100]}")
            # Same fix as S&P: resolve against the actual page we scraped
            # (feed_url), never a hardcoded domain guess.
            full_url = urljoin(feed_url, href) if feed_url else href
            changes.extend(self._extract_changes_from_url(full_url))
        return changes

    def _find_section(self, text: str, action_words: str) -> str:
        """Isolate the sentence introducing additions/removals so we never
        mix the two lists together or pick up unrelated names (e.g. the
        "Nasdaq (Nasdaq: NDAQ)" self-reference in the intro sentence).

        VERIFIED REAL BUG (2026-08-18): when a REMOVE list is the LAST list
        in the release (no further "The following..." paragraph after it),
        the old lookahead only stopped at another "The following" or the
        absolute end of the whole page text (\\Z) -- which meant it swept
        up everything in between, including the "About Nasdaq Global
        Indexes" / "About Nasdaq" boilerplate that follows on every real
        release. That boilerplate itself contains "(Nasdaq: NDAQ)" as a
        self-reference, which TICKER_PATTERN then mistook for one more
        removed company -- confirmed against a real run's history file,
        which had a garbled row: ticker NDAQ, company_name "Nasdaq Global
        Indexes publishes and maintains more than 10,000 indexes across
        asset classes and geographies. About Nasdaq Nasdaq". Added the
        standard boilerplate section starters as additional stop points."""
        pattern = re.compile(
            r'(?:' + action_words + r')[^:]*:\s*(.+?)'
            r'(?=\.\s*(?:The following|For (?:additional|more) information|About Nasdaq|About the|$)|\Z)',
            re.IGNORECASE | re.DOTALL,
        )
        m = pattern.search(text)
        return m.group(1) if m else ''

    def _extract_companies(self, section_text: str) -> List[Dict[str, str]]:
        out = []
        for m in self.TICKER_PATTERN.finditer(section_text):
            name = m.group(1).strip().strip(',').strip()
            ticker = m.group(2)
            if name and 1 <= len(ticker) <= 6:
                out.append({'name': name, 'ticker': ticker})
        return out

    def _extract_single_company_narrative(self, text: str) -> List[Dict[str, str]]:
        """Fallback for narrative-style single-company releases that don't
        use the list-with-colon 'will be added:' structure _find_section()
        expects -- see NARRATIVE_ADD_PATTERN's docstring for the real
        SpaceX/Nasdaq-100 example that exposed this gap. Only ever called
        when the normal list-based extraction found nothing."""
        out = []
        for m in self.NARRATIVE_ADD_PATTERN.finditer(text):
            name = m.group(1).strip().strip(',').strip()
            ticker = m.group(2)
            if name and 1 <= len(ticker) <= 6 and ticker != 'NDAQ':
                out.append({'name': name, 'ticker': ticker})
        return out

    def _extract_narrative_replacement(self, text: str) -> List[Dict[str, str]]:
        """Fallback for the 'replacing <Company> (Exchange: TICKER)' clause
        some narrative releases include -- see NARRATIVE_REPLACING_PATTERN's
        docstring for the real Lumentum/CoStar example that exposed this."""
        out = []
        for m in self.NARRATIVE_REPLACING_PATTERN.finditer(text):
            name = m.group(1).strip().strip(',').strip()
            ticker = m.group(2)
            if name and 1 <= len(ticker) <= 6 and ticker != 'NDAQ':
                out.append({'name': name, 'ticker': ticker})
        return out

    def _extract_changes_from_url(self, url: str) -> List[Dict[str, Any]]:
        try:
            if not url.startswith('http'):
                url = urljoin('https://www.nasdaq.com/', url)
            response = self.session.get(url, timeout=15)
            logger.info(f"[Nasdaq] GET {url} -> HTTP {response.status_code}, {len(response.content)} bytes")
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            text = clean_text(soup)

            publish_year = extract_publish_year(text)
            effective_date = None
            for pattern in self.EFFECTIVE_DATE_PATTERNS:
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    effective_date = parse_date_string(m.group(1), fallback_year=publish_year)
                    if effective_date:
                        break
            if not effective_date:
                logger.warning(f"[Nasdaq] No effective date found in {url} -- skipping")
                return []

            changes = []
            add_section = self._find_section(text, r'will be added|companies added|to be added')
            for c in self._extract_companies(add_section):
                changes.append({
                    'ticker': c['ticker'], 'company_name': c['name'], 'action': 'ADD',
                    'effective_date': effective_date, 'announcement_date': effective_date,
                    'press_release_url': url, 'source': 'Nasdaq',
                    'reason': _extract_corporate_action_reason(text, c['name'], c['ticker']),
                })
            rem_section = self._find_section(text, r'will be removed|companies removed|to be removed')
            for c in self._extract_companies(rem_section):
                changes.append({
                    'ticker': c['ticker'], 'company_name': c['name'], 'action': 'REMOVE',
                    'effective_date': effective_date, 'announcement_date': effective_date,
                    'press_release_url': url, 'source': 'Nasdaq',
                    'reason': _extract_corporate_action_reason(text, c['name'], c['ticker']),
                })

            if not changes:
                # List-based extraction found nothing -- try the narrative
                # single-company fallback before giving up on this release.
                for c in self._extract_single_company_narrative(text):
                    changes.append({
                        'ticker': c['ticker'], 'company_name': c['name'], 'action': 'ADD',
                        'effective_date': effective_date, 'announcement_date': effective_date,
                        'press_release_url': url, 'source': 'Nasdaq',
                        'reason': _extract_corporate_action_reason(text, c['name'], c['ticker']),
                    })
                # Also check for a same-sentence "replacing X (Exchange:
                # TICKER)" clause naming the removed company -- easy to miss
                # since it's not a separate list, just a clause in the ADD
                # sentence (see the real Lumentum/CoStar example).
                for c in self._extract_narrative_replacement(text):
                    changes.append({
                        'ticker': c['ticker'], 'company_name': c['name'], 'action': 'REMOVE',
                        'effective_date': effective_date, 'announcement_date': effective_date,
                        'press_release_url': url, 'source': 'Nasdaq',
                        'reason': _extract_corporate_action_reason(text, c['name'], c['ticker']),
                    })

            return changes
        except requests.exceptions.RequestException as e:
            logger.warning(f"[Nasdaq] Network error {url}: {e}")
            return []
        except Exception as e:
            logger.warning(f"[Nasdaq] Error extracting {url}: {e}")
            return []


# ---------------------------------------------------------------------------
# FTSE Russell (3000 / 2000 / 1000)
# ---------------------------------------------------------------------------

class RussellScraper:
    """Scrapes FTSE Russell reconstitution announcements.

    HONEST LIMITATION (verified against the real 2026-05-22 "FTSE Russell
    Begins June 2026 Semi-Annual Russell US Indexes Reconstitution"
    announcement): unlike S&P and Nasdaq, FTSE Russell's press releases do
    NOT list individual company/ticker changes in prose -- they report
    aggregate statistics ("62 companies are expected to be added to the
    Russell 1000..."). The actual per-company additions/deletions are
    published as separate PDF documents whose URLs change every cycle.
    This scraper detects that a reconstitution has been announced and
    extracts its real effective date, but does NOT fabricate a per-company
    list. Parsing the PDFs is a separate follow-up task (needs a PDF text
    library and a way to discover each cycle's current PDF URLs).
    """

    FEEDS = {
        'r3000': 'https://www.lseg.com/en/media-centre/press-releases/ftse-russell/',
        'r2000': 'https://www.lseg.com/en/media-centre/press-releases/ftse-russell/',
        'r1000': 'https://www.lseg.com/en/media-centre/press-releases/ftse-russell/',
    }
    INDEX_NAMES = {'r3000': 'Russell 3000', 'r2000': 'Russell 2000', 'r1000': 'Russell 1000'}

    EFFECTIVE_DATE_PATTERNS = [
        r'effective\s+(?:prior to|before)\s+(?:the\s+)?open(?:ing)?\s+of\s+trading\s+on\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)',
        r'take\s+effect\s+(?:after|before)\s+.{0,40}?(?:close|open)\s+.{0,10}?on\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)',
        r'takes?\s+effect\s+.{0,60}?on\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)',
        r'commencing\s+(?:prior to|before)\s+(?:the\s+)?(?:trading\s+)?on\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)',
        r'will\s+(?:become\s+)?effective\s+(?:[A-Za-z]+,\s*)?([A-Za-z]+\s+\d{1,2}(?:,?\s*\d{4})?)',
    ]

    def __init__(self, index_type: str = 'r3000', session: Optional[requests.Session] = None):
        self.index_type = index_type
        self.index_name = self.INDEX_NAMES.get(index_type, 'Russell 3000')
        self.feed_url = self.FEEDS.get(index_type)
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def scrape(self) -> List[Dict[str, Any]]:
        try:
            response = self.session.get(self.feed_url, timeout=15)
            logger.info(f"[Russell] GET {self.feed_url} -> HTTP {response.status_code}, {len(response.content)} bytes")
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            all_links = soup.find_all('a')
            logger.info(f"[Russell] {self.feed_url}: found {len(all_links)} raw <a> tags")
            events = []
            candidates = 0
            for a in all_links:
                title = a.get_text(strip=True)
                href = a.get('href', '')
                if not title or not href:
                    continue
                t = title.lower()
                # Verified bug: requiring only "russell" OR "reconstitution"
                # let generic nav links through whose text is literally just
                # "FTSE Russell" (a breadcrumb/nav link, not an article) --
                # those resolve to a landing page with no effective date and
                # silently produce zero events. Require "reconstitution"
                # specifically, which only appears in real announcement
                # titles.
                if 'reconstitution' not in t:
                    continue
                candidates += 1
                logger.info(f"[Russell] Candidate release: {title[:100]}")
                full_url = urljoin(self.feed_url, href)
                events.extend(self._extract_from_url(full_url, title))
            logger.info(f"[Russell] {candidates} links passed the title filter; found {len(events)} reconstitution events for {self.index_name}")
            return events
        except Exception as e:
            logger.error(f"[Russell] Error scraping {self.index_name}: {e}")
            return []

    def _extract_from_url(self, url: str, title: str) -> List[Dict[str, Any]]:
        try:
            if not url.startswith('http'):
                url = 'https://www.lseg.com' + url
            response = self.session.get(url, timeout=15)
            logger.info(f"[Russell] GET {url} -> HTTP {response.status_code}, {len(response.content)} bytes")
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            text = clean_text(soup)

            publish_year = extract_publish_year(text)
            effective_date = None
            for pattern in self.EFFECTIVE_DATE_PATTERNS:
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    effective_date = parse_date_string(m.group(1), fallback_year=publish_year)
                    if effective_date:
                        break
            if not effective_date:
                logger.warning(f"[Russell] No effective date found in {url} -- skipping")
                return []

            # Honest: index-level event, not fabricated per-company data.
            return [{
                'ticker': None,
                'company_name': None,
                'action': 'RECONSTITUTION_ANNOUNCED',
                'effective_date': effective_date,
                'announcement_date': effective_date,
                'press_release_url': url,
                'title': title,
                'source': 'FTSE Russell',
                'note': 'Per-company additions/deletions are in separate PDF documents, not parsed by this script.',
            }]
        except Exception as e:
            logger.warning(f"[Russell] Error extracting {url}: {e}")
            return []


def classify_reason_label(reason_text: str) -> str:
    """Categorize a free-text reason (already known to be about a specific
    company -- e.g. one cell of a Wikipedia 'changes' table row) using the
    same keyword groups as _extract_corporate_action_reason. Unlike that
    function, no company-mention check is needed here since the caller
    already knows this text is about the row in question."""
    s_l = (reason_text or '').lower()
    for label, phrases in CORPORATE_ACTION_KEYWORDS.items():
        if any(p in s_l for p in phrases):
            return label
    return 'Corporate Action / Index Update'


# ---------------------------------------------------------------------------
# Wikipedia-sourced index "changes" history (S&P 500, S&P 400, S&P 600,
# S&P 100, Dow Industrial, Nasdaq-100).
#
# WHY THIS EXISTS: per KING's example -- WestRock silently became Smurfit
# Westrock (ticker WRK -> SW) after its merger with Smurfit Kappa, without
# S&P DJI necessarily issuing a press release that reads like a normal
# "index change" announcement. A merger/spin-off/business-combination can
# rename or re-ticker an EXISTING index member in place, which the
# press-release scrapers above can legitimately miss if the release's title
# or wording doesn't match their "is this an index-change announcement?"
# filters.
#
# Wikipedia's community-maintained "Selected changes" / "Changes" history
# table for each of these indices tracks every constituent change
# independently -- INCLUDING pure renames where only one side (Added or
# Removed) is populated because the same company simply continues under a
# new ticker/name -- with a plain-English reason already written in
# (merger, acquisition, spin-off, name change, market-cap reshuffle, etc).
# Verified live on 2026-08-17: the S&P 500 and Nasdaq-100 pages both have
# this exact 6-column table (Date, Added Ticker, Added Security, Removed
# Ticker, Removed Security, Reason); e.g. one real row reads "February 1,
# 2016 | AVGO | Broadcom | | | Avago Technologies changed its name to
# Broadcom. Former ticker BRCM retired." -- Removed side blank, meaning no
# actual departure, just a name/ticker update to the same constituent.
#
# HONEST LIMITATION: not confirmed live whether S&P 400 / S&P 600 / S&P 100
# / Dow maintain the identical table layout -- this scraper looks for it
# defensively (by table shape, not a hardcoded section name) and simply
# returns no rows for an index if it can't find a matching table, exactly
# like the Russell scraper already does when data isn't available. This is
# a second, independent source, not a replacement -- it never fabricates a
# reason Wikipedia doesn't state.
# ---------------------------------------------------------------------------

class WikipediaChangesScraper:
    PAGES = {
        'S&P 500': 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies',
        'S&P 400': 'https://en.wikipedia.org/wiki/List_of_S%26P_400_companies',
        'S&P 600': 'https://en.wikipedia.org/wiki/List_of_S%26P_600_companies',
        'S&P 100': 'https://en.wikipedia.org/wiki/S%26P_100',
        'Dow Industrial': 'https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average',
        'Nasdaq-100': 'https://en.wikipedia.org/wiki/Nasdaq-100',
    }

    def __init__(self, index_bucket: str, session: Optional[requests.Session] = None):
        self.index_bucket = index_bucket
        self.url = self.PAGES.get(index_bucket)
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def scrape(self) -> List[Dict[str, Any]]:
        if not self.url:
            return []
        try:
            response = self.session.get(self.url, timeout=20)
            logger.info(f"[WikiHistory] GET {self.url} -> HTTP {response.status_code}, {len(response.content)} bytes")
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            table = self._find_changes_table(soup)
            if table is None:
                logger.info(
                    f"[WikiHistory] No 'changes' history table found for {self.index_bucket} "
                    "-- skipping (not every index page has one)."
                )
                return []
            rows = self._parse_table(table)
            logger.info(f"[WikiHistory] {self.index_bucket}: {len(rows)} change(s) from Wikipedia history table")
            return rows
        except Exception as e:
            logger.warning(f"[WikiHistory] Error scraping {self.index_bucket}: {e}")
            return []

    def _find_changes_table(self, soup: BeautifulSoup):
        """Identify the changes-history table by its DATA shape (6 columns
        per row, first cell a real date, last cell a real sentence) rather
        than by section heading or CSS class -- robust to the two-row
        colspan/rowspan header Wikipedia uses for this table (Date / Added
        Ticker+Security / Removed Ticker+Security / Reason), which this
        approach never needs to parse at all."""
        best_table, best_score = None, 0
        for table in soup.find_all('table', class_=lambda c: c and 'wikitable' in c):
            data_rows = 0
            reason_like = 0
            for tr in table.find_all('tr'):
                tds = tr.find_all('td')
                if len(tds) != 6:
                    continue
                cell_texts = [td.get_text(strip=True) for td in tds]
                if parse_date_string(cell_texts[0]):
                    data_rows += 1
                    if len(cell_texts[5]) > 10 and ' ' in cell_texts[5]:
                        reason_like += 1
            if data_rows >= 5 and reason_like >= 3 and reason_like > best_score:
                best_table = table
                best_score = reason_like
        return best_table

    def _parse_table(self, table) -> List[Dict[str, Any]]:
        changes = []
        for tr in table.find_all('tr'):
            tds = tr.find_all('td')
            if len(tds) != 6:
                continue
            date_txt, add_ticker, add_name, rem_ticker, rem_name, reason_txt = [
                td.get_text(strip=True) for td in tds
            ]
            effective_date = parse_date_string(date_txt)
            if not effective_date:
                continue

            reason = reason_txt.strip()
            labeled_reason = f"{classify_reason_label(reason)}: {reason}" if reason else ''

            if add_ticker and add_name:
                changes.append({
                    'ticker': add_ticker, 'company_name': add_name, 'action': 'ADD',
                    'index_bucket': self.index_bucket,
                    'effective_date': effective_date, 'announcement_date': effective_date,
                    'press_release_url': self.url, 'source': 'Wikipedia (index history)',
                    'reason': labeled_reason,
                })
            if rem_ticker and rem_name:
                changes.append({
                    'ticker': rem_ticker, 'company_name': rem_name, 'action': 'REMOVE',
                    'index_bucket': self.index_bucket,
                    'effective_date': effective_date, 'announcement_date': effective_date,
                    'press_release_url': self.url, 'source': 'Wikipedia (index history)',
                    'reason': labeled_reason,
                })
        return changes


# ---------------------------------------------------------------------------
# SEC EDGAR enrichment: CIK + latest filed form (Proxy / Annual / Quarterly /
# IPO) for each ticker that shows up in an index change. Verified live
# against SEC EDGAR on 2026-07-22:
#   - Ticker -> CIK map:  https://www.sec.gov/files/company_tickers.json
#     (a single JSON object keyed "0","1",... each with cik_str/ticker/title;
#     confirmed real entry: {"cik_str":320193,"ticker":"AAPL","title":
#     "Apple Inc."}). Downloaded once per run and cached, not once per ticker.
#   - Filing history: https://data.sec.gov/submissions/CIK##########.json
#     (10-digit zero-padded CIK) -- "filings"."recent" holds parallel arrays
#     "form" and "filingDate"; confirmed real entries for Apple (CIK
#     0000320193) include "10-K" filed 2025-10-31.
# SEC requires a descriptive User-Agent identifying the requester (name/
# email) on every request to these hosts -- a generic browser UA can get
# rate-limited or blocked.
# ---------------------------------------------------------------------------

SEC_HEADERS = {
    'User-Agent': 'IndexMonitor/1.0 (maharajasm2186@gmail.com)',
    'Accept-Encoding': 'gzip, deflate',
}

# The four form types the user actually cares about, mapped to a plain-
# English category. DEF 14A = proxy statement, 10-K = annual report,
# 10-Q = quarterly report, S-1 = IPO registration statement (S-1/A and
# F-1/F-1A covered too since foreign private issuers and amendments use
# those instead).
SEC_FORM_CATEGORIES = {
    'DEF 14A': 'Proxy',
    'DEFA14A': 'Proxy',
    'DEFM14A': 'Proxy',
    '10-K': 'Annual',
    '10-K/A': 'Annual',
    '10-KT': 'Annual',
    '20-F': 'Annual',   # foreign private issuer annual report (e.g. Nebius Group N.V.)
    '20-F/A': 'Annual',
    '10-Q': 'Quarterly',
    '10-Q/A': 'Quarterly',
    'S-1': 'IPO',
    'S-1/A': 'IPO',
    'F-1': 'IPO',
    'F-1/A': 'IPO',
}

_TICKER_CIK_CACHE: Optional[Dict[str, str]] = None


def _load_ticker_cik_map(session: requests.Session) -> Dict[str, str]:
    """Download and cache SEC's official ticker -> CIK map. Cached at
    module level so a run covering many tickers only downloads this once."""
    global _TICKER_CIK_CACHE
    if _TICKER_CIK_CACHE is not None:
        return _TICKER_CIK_CACHE
    try:
        resp = session.get('https://www.sec.gov/files/company_tickers.json',
                            headers=SEC_HEADERS, timeout=20)
        logger.info(f"[SEC] GET company_tickers.json -> HTTP {resp.status_code}, {len(resp.content)} bytes")
        resp.raise_for_status()
        data = resp.json()
        _TICKER_CIK_CACHE = {
            entry['ticker'].upper(): str(entry['cik_str']).zfill(10)
            for entry in data.values()
        }
        logger.info(f"[SEC] Loaded {len(_TICKER_CIK_CACHE)} ticker->CIK mappings")
    except Exception as e:
        logger.warning(f"[SEC] Could not load ticker->CIK map: {e}")
        _TICKER_CIK_CACHE = {}
    return _TICKER_CIK_CACHE


def get_cik_and_latest_filing(ticker: Optional[str], session: Optional[requests.Session] = None) -> Dict[str, Any]:
    """Resolve a ticker to its SEC CIK and the most recently filed form
    among the four types that matter here: 10-K (Annual), 10-Q (Quarterly),
    DEF 14A (Proxy), S-1 (IPO). Returns Nones for anything it can't find
    rather than guessing."""
    empty = {'cik': None, 'latest_form_type': None, 'latest_form_category': None, 'latest_filing_date': None}
    ticker = (ticker or '').strip().upper()
    if not ticker:
        return dict(empty)

    session = session or requests.Session()
    cik_map = _load_ticker_cik_map(session)
    cik = cik_map.get(ticker)
    if not cik:
        logger.warning(f"[SEC] No CIK found for ticker {ticker}")
        return dict(empty)

    try:
        url = f'https://data.sec.gov/submissions/CIK{cik}.json'
        resp = session.get(url, headers=SEC_HEADERS, timeout=20)
        logger.info(f"[SEC] GET {url} -> HTTP {resp.status_code}, {len(resp.content)} bytes")
        resp.raise_for_status()
        data = resp.json()
        recent = data.get('filings', {}).get('recent', {})
        forms = recent.get('form', [])
        dates = recent.get('filingDate', [])

        best_form, best_date = None, None
        for form, date in zip(forms, dates):
            if form in SEC_FORM_CATEGORIES and (best_date is None or date > best_date):
                best_form, best_date = form, date

        if not best_form:
            logger.warning(f"[SEC] {ticker} (CIK {cik}): no 10-K/10-Q/DEF 14A/S-1 found in recent filings")
            return {'cik': cik, 'latest_form_type': None, 'latest_form_category': None, 'latest_filing_date': None}

        return {
            'cik': cik,
            'latest_form_type': best_form,
            'latest_form_category': SEC_FORM_CATEGORIES[best_form],
            'latest_filing_date': best_date,
        }
    except Exception as e:
        logger.warning(f"[SEC] Error fetching filings for {ticker} (CIK {cik}): {e}")
        return {'cik': cik, 'latest_form_type': None, 'latest_form_category': None, 'latest_filing_date': None}


def enrich_with_sec_filings(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add cik / latest_form_type / latest_form_category / latest_filing_date
    to each row that has a ticker. One shared session + cached ticker map
    keeps this to 1 + N requests total (N = distinct tickers), not one
    ticker-map download per row."""
    session = requests.Session()
    cache: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        ticker = (row.get('ticker') or '').strip().upper()
        if not ticker:
            row.update({'cik': None, 'latest_form_type': None, 'latest_form_category': None, 'latest_filing_date': None})
            continue
        if ticker not in cache:
            cache[ticker] = get_cik_and_latest_filing(ticker, session=session)
        row.update(cache[ticker])
    return rows


# ---------------------------------------------------------------------------
# Email notification (Gmail SMTP)
#
# Sender: maggy2186@gmail.com   (KING's designated "from" mailbox)
# Recipients (per KING's explicit instructions):
#   To:  maharajasm2186@gmail.com, maharaja@secanalyzer.net
#   Cc:  lawrence.amalraj@secanalyzer.net, chandru@secanalyzer.net
#
# SECURITY: the sender's Gmail credential is a Gmail "App Password" (a
# 16-character code from Google Account > Security > 2-Step Verification >
# App passwords), NOT the regular account password -- Gmail's SMTP no
# longer accepts a plain account password from a script. This code reads
# it from the SMTP_PASSWORD environment variable ONLY; it is never
# hardcoded here and Claude never sees or types it. Locally: set it as an
# environment variable before running this script, e.g. (PowerShell)
#   $env:SMTP_PASSWORD = "your 16 char app password"
#   $env:SMTP_SENDER_EMAIL = "maggy2186@gmail.com"
# On GitHub Actions: the workflow maps the repo secrets SENDER_EMAIL /
# SENDER_APP_PASSWORD to SMTP_SENDER_EMAIL / SMTP_PASSWORD.
#
# Per KING's request, the email no longer attaches the CSV/Excel file --
# the report is rendered directly in the email body as an HTML table (with
# a plain-text fallback for clients that don't render HTML).
# ---------------------------------------------------------------------------

def _load_local_email_config(path: str = 'email_config.txt') -> Dict[str, str]:
    """Reads KING's self-editable local config file, if present.

    Plain 'KEY=value' lines, '#' comments allowed, blank lines ignored.
    This lets KING add/remove the sender email, app password, and To/Cc
    recipients himself -- on his own machine -- without ever touching the
    Python code. It is only used for LOCAL runs: GitHub Actions / a VPS
    won't have this file, so they keep using repo/environment secrets
    exactly as before (this function simply returns {} if the file is
    absent, and every value below still falls back to the env var / the
    hardcoded default).

    SECURITY: this file contains a Gmail App Password in plain text -- it
    must never be committed to GitHub. It is listed in .gitignore for this
    reason. Keep it on your own machine only.
    """
    values: Dict[str, str] = {}
    if not os.path.isfile(path):
        return values
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, val = line.partition('=')
                key = key.strip().upper()
                val = val.strip()
                if key and val:
                    values[key] = val
    except OSError as e:
        logger.warning(f"Could not read {path}: {e}")
    return values


_LOCAL_EMAIL_CONFIG = _load_local_email_config()

SMTP_SENDER_EMAIL = _LOCAL_EMAIL_CONFIG.get(
    'SENDER_EMAIL', os.environ.get('SMTP_SENDER_EMAIL', 'maggy2186@gmail.com')
)
SMTP_PASSWORD = _LOCAL_EMAIL_CONFIG.get(
    'SENDER_APP_PASSWORD', os.environ.get('SMTP_PASSWORD')
)  # Gmail App Password -- required, no default
SMTP_HOST = _LOCAL_EMAIL_CONFIG.get(
    'SMTP_HOST', os.environ.get('SMTP_HOST', 'smtp.gmail.com')
)
SMTP_PORT = int(_LOCAL_EMAIL_CONFIG.get(
    'SMTP_PORT', os.environ.get('SMTP_PORT', '587')
))

# Comma-separated. Priority: email_config.txt (local, self-editable) ->
# env var (GitHub Actions / VPS secrets) -> hardcoded default.
SMTP_TO_EMAILS = [e.strip() for e in _LOCAL_EMAIL_CONFIG.get(
    'TO_EMAILS', os.environ.get(
        'SMTP_TO_EMAILS', 'maharajasm2186@gmail.com,maharaja@secanalyzer.net'
    )
).split(',') if e.strip()]
SMTP_CC_EMAILS = [e.strip() for e in _LOCAL_EMAIL_CONFIG.get(
    'CC_EMAILS', os.environ.get(
        'SMTP_CC_EMAILS', 'chandru@secanalyzer.net'
    )
).split(',') if e.strip()]


def _is_true(value: Optional[str]) -> bool:
    return (value or '').strip().lower() in ('1', 'true', 'yes', 'on')


# Per KING's request #4: whether to (re)generate the "Evidence" Excel of
# merger/acquisition/spin-off/business-combination/ticker-name-change-driven
# index changes on every run. Self-editable the same way as the recipients
# above -- add a GENERATE_EVIDENCE_REPORT=true/false line to
# email_config.txt (local runs), or set the GENERATE_EVIDENCE_REPORT env
# var (GitHub Actions / VPS). Defaults to on.
GENERATE_EVIDENCE_REPORT = _is_true(_LOCAL_EMAIL_CONFIG.get(
    'GENERATE_EVIDENCE_REPORT', os.environ.get('GENERATE_EVIDENCE_REPORT', 'true')
))

# The single table format used everywhere -- CSV, Excel, and the email
# table -- built on KING's reference file (index_changes_going_forward1.xlsx,
# sheet "Side by side"), plus the Reason and Refer Link columns added since.
# No CIK / SEC-filing columns in this version; that
# lookup code above (get_cik_and_latest_filing / enrich_with_sec_filings /
# format_latest_filing_text) is left in place but is no longer called from
# the main flow, per KING's "simplify everywhere" instruction.
REPORT_COLUMNS = [
    'Indices', 'Removed', 'Removed Ticker', 'Removed date',
    'Added', 'Added Ticker', 'Commencing date', 'Remarks', 'Reason', 'Refer Link',
]


def _dedupe_flat_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Defensive de-duplication of raw ADD/REMOVE change rows before they
    go into any report or the history file. Two rows are the same
    real-world event if they share the same index bucket, ticker, action,
    and effective date -- regardless of which press release or which day's
    run produced them (the same release can be re-scraped on consecutive
    days until its effective date passes)."""
    seen: Dict[tuple, Dict[str, Any]] = {}
    order = []
    for r in rows:
        key = (
            (r.get('index_bucket') or '').strip().lower(),
            (r.get('ticker') or '').strip().upper(),
            (r.get('action') or '').strip().upper(),
            (r.get('effective_date') or '').strip(),
        )
        if key in seen:
            # Same real-world event reported by more than one source (e.g.
            # a press release AND Wikipedia's history table). Keep the
            # first-seen row, but backfill a 'reason' from the duplicate if
            # the first source didn't provide one -- Wikipedia's history
            # table is often the one carrying the merger/spin-off/rename
            # explanation that a press release's own wording lacked.
            if not seen[key].get('reason') and r.get('reason'):
                seen[key]['reason'] = r['reason']
            continue
        seen[key] = r
        order.append(key)
    return [seen[k] for k in order]


def build_side_by_side_rows(flat_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Turn a flat list of ADD/REMOVE change rows into the 8-column
    Removed/Added paired table (one row per pairing, grouped and paired per
    index -- see _pair_added_removed_for_index for the pairing rules)."""
    flat_rows = _dedupe_flat_rows(flat_rows)
    added = [r for r in flat_rows if r.get('action') == 'ADD']
    removed = [r for r in flat_rows if r.get('action') == 'REMOVE']

    added_by_bucket = defaultdict(list)
    removed_by_bucket = defaultdict(list)
    for a in added:
        added_by_bucket[a.get('index_bucket') or ''].append(a)
    for r in removed:
        removed_by_bucket[r.get('index_bucket') or ''].append(r)

    all_buckets = sorted(set(added_by_bucket) | set(removed_by_bucket))
    table_rows = []
    for bucket in all_buckets:
        pairs = _pair_added_removed_for_index(added_by_bucket.get(bucket, []), removed_by_bucket.get(bucket, []))
        for removed_row, added_row, remark in pairs:
            # Prefer the ADD announcement's press-release link (that's
            # usually the one naming both the added and removed company
            # together); fall back to the REMOVE row's link if there's no
            # ADD side to this pairing.
            refer_link = ''
            if added_row and added_row.get('press_release_url'):
                refer_link = added_row['press_release_url']
            elif removed_row and removed_row.get('press_release_url'):
                refer_link = removed_row['press_release_url']

            # Merger / acquisition / spin-off / business combination /
            # ticker-or-name-change reason, if the press release stated one
            # for either side of this pairing. Blank means an ordinary
            # scheduled rebalance -- nothing unusual reported.
            reasons = []
            if added_row and added_row.get('reason'):
                reasons.append(added_row['reason'])
            if removed_row and removed_row.get('reason') and removed_row.get('reason') not in reasons:
                reasons.append(removed_row['reason'])
            reason_text = ' | '.join(reasons)

            # A one-sided pairing (only Removed or only Added) whose Reason
            # is a Ticker/Name Change is very likely the SAME company
            # continuing in the index under a new ticker/company name --
            # e.g. WestRock -> Smurfit Westrock -- rather than a genuine
            # departure/gap. Make that explicit instead of the generic
            # "no matching addition/removal found" wording.
            if remark in ("Added, no matching removal found", "Removed, no matching addition found") \
                    and reason_text.startswith('Ticker/Name Change'):
                remark = "Ticker/company name updated — same index member (see Reason)"

            table_rows.append({
                'Indices': bucket,
                'Removed': removed_row.get('company_name') if removed_row else '',
                'Removed Ticker': removed_row.get('ticker') if removed_row else '',
                'Removed date': removed_row.get('effective_date') if removed_row else '',
                'Added': added_row.get('company_name') if added_row else '',
                'Added Ticker': added_row.get('ticker') if added_row else '',
                'Commencing date': added_row.get('effective_date') if added_row else '',
                'Remarks': remark,
                'Reason': reason_text,
                'Refer Link': refer_link,
            })
    return table_rows


def build_html_table(rows: List[Dict[str, Any]]) -> str:
    """Render the 8-column paired table as an HTML <table> for embedding
    directly in the email body -- per KING's request for a table
    notification in the mail instead of a file attachment."""
    if not rows:
        return "<p><em>No changes to report for this period.</em></p>"
    th = "".join(
        f'<th style="padding:6px 10px;border:1px solid #ccc;background:#4472C4;'
        f'color:#fff;text-align:left;">{h}</th>' for h in REPORT_COLUMNS
    )
    body_rows = []
    for row in rows:
        cells = []
        for h in REPORT_COLUMNS:
            val = row.get(h) or ""
            if h == 'Refer Link' and val:
                cell_html = f'<a href="{val}" target="_blank">Source</a>'
            else:
                cell_html = val
            cells.append(f'<td style="padding:6px 10px;border:1px solid #ccc;">{cell_html}</td>')
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    return (
        '<table style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:13px;">'
        f'<thead><tr>{th}</tr></thead><tbody>{"".join(body_rows)}</tbody></table>'
    )


def build_plain_text_table(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "No changes to report for this period."
    lines = [" | ".join(REPORT_COLUMNS)]
    for row in rows:
        lines.append(" | ".join(str(row.get(h) or '') for h in REPORT_COLUMNS))
    return "\n".join(lines)


def send_report_email(table_rows: List[Dict[str, Any]], subject: str, intro: str) -> bool:
    """Send a report as an HTML table embedded in the email body (no
    attachments). Used for the daily going-forward report AND the weekly /
    month-end / year-end digests -- same recipients, same table format.
    Returns False (and logs why) instead of raising, so a mail failure
    never takes down the rest of the run."""
    if not SMTP_PASSWORD:
        logger.warning(
            "[Email] SMTP_PASSWORD environment variable is not set -- skipping email send. "
            f"Set it to a Gmail App Password for {SMTP_SENDER_EMAIL} (Google Account > "
            "Security > 2-Step Verification > App passwords) and re-run."
        )
        return False
    if not SMTP_TO_EMAILS:
        logger.warning("[Email] No SMTP_TO_EMAILS configured -- skipping email send.")
        return False

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = SMTP_SENDER_EMAIL
    msg['To'] = ', '.join(SMTP_TO_EMAILS)
    if SMTP_CC_EMAILS:
        msg['Cc'] = ', '.join(SMTP_CC_EMAILS)

    msg.set_content(f"{intro}\n\n{build_plain_text_table(table_rows)}")
    msg.add_alternative(f'<p>{intro}</p>{build_html_table(table_rows)}', subtype='html')

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(SMTP_SENDER_EMAIL, SMTP_PASSWORD)
            server.send_message(msg)
        logger.info(f"[Email] Sent '{subject}' to To={SMTP_TO_EMAILS} Cc={SMTP_CC_EMAILS}")
        return True
    except Exception as e:
        logger.error(f"[Email] Failed to send '{subject}': {e}")
        return False


# ---------------------------------------------------------------------------
# Persistent history + weekly / month-end / year-end digests
#
# The daily "going forward" report only shows changes whose effective date
# is still ahead of today. The weekly (Sunday) / month-end / year-end
# digests need everything that became effective DURING that period, even if
# it's no longer "going forward" by the time the digest runs -- so every
# run appends whatever it found (deduped) to a running history file, and
# the digests read from that file instead of a single run's results.
# ---------------------------------------------------------------------------

HISTORY_CSV_PATH = 'index_changes_history.csv'
HISTORY_COLUMNS = ['index_bucket', 'ticker', 'company_name', 'action', 'effective_date', 'press_release_url', 'reason']

# Default fiscal/calendar year-end date (MM-DD). Per KING: "default December
# 31, 2026" -- override via the YEAR_END_MMDD env var if a different date is
# ever needed without touching code.
YEAR_END_MMDD = os.environ.get('YEAR_END_MMDD', '12-31')


def _history_key(r: Dict[str, Any]) -> tuple:
    return (
        (r.get('index_bucket') or '').strip().lower(),
        (r.get('ticker') or '').strip().upper(),
        (r.get('action') or '').strip().upper(),
        (r.get('effective_date') or '').strip(),
    )


def load_history(path: str = HISTORY_CSV_PATH) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    with open(path, 'r', newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def append_to_history(flat_rows: List[Dict[str, Any]], path: str = HISTORY_CSV_PATH) -> List[Dict[str, Any]]:
    """Append newly-seen changes (deduped against what's already recorded)
    to the running history file and return the full updated history."""
    existing = load_history(path)
    existing_keys = {_history_key(r) for r in existing}

    new_rows = []
    for r in _dedupe_flat_rows(flat_rows):
        key = _history_key(r)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        new_rows.append({
            'index_bucket': r.get('index_bucket'),
            'ticker': r.get('ticker'),
            'company_name': r.get('company_name'),
            'action': r.get('action'),
            'effective_date': r.get('effective_date'),
            'press_release_url': r.get('press_release_url'),
            'reason': r.get('reason'),
        })

    combined = existing + new_rows
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS, extrasaction='ignore')
        writer.writeheader()
        for row in combined:
            writer.writerow(row)
    logger.info(f"[History] {len(new_rows)} new change(s) appended, {len(combined)} total in {path}")
    return combined


def filter_by_effective_range(history_rows: List[Dict[str, Any]], start: str, end: str) -> List[Dict[str, Any]]:
    """Keep rows whose effective_date falls within [start, end] inclusive
    -- ISO date strings compare correctly as plain text."""
    return [r for r in history_rows if start <= (r.get('effective_date') or '') <= end]


def get_week_range(today) -> tuple:
    """The 7 days ending on `today` (Monday..Sunday of the current ISO
    week) -- meant to be called on a Sunday."""
    from datetime import timedelta
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat(), today.isoformat()


def get_month_range(today) -> tuple:
    return today.replace(day=1).isoformat(), today.isoformat()


def get_year_range(today) -> tuple:
    return today.replace(month=1, day=1).isoformat(), today.isoformat()


def is_last_day_of_month(today) -> bool:
    from datetime import timedelta
    return (today + timedelta(days=1)).day == 1


def is_year_end(today) -> bool:
    return today.strftime('%m-%d') == YEAR_END_MMDD


def send_weekly_digest(history_rows: List[Dict[str, Any]], today) -> bool:
    start, end = get_week_range(today)
    table_rows = build_side_by_side_rows(filter_by_effective_range(history_rows, start, end))
    subject = f"Index Monitor — Weekly Digest — {start} to {end}"
    intro = f"All index changes effective between {start} and {end} (this week):"
    return send_report_email(table_rows, subject, intro)


def send_month_end_digest(history_rows: List[Dict[str, Any]], today) -> bool:
    start, end = get_month_range(today)
    table_rows = build_side_by_side_rows(filter_by_effective_range(history_rows, start, end))
    subject = f"Index Monitor — Month-End Digest — {start[:7]}"
    intro = f"All index changes effective between {start} and {end} (this month):"
    return send_report_email(table_rows, subject, intro)


def send_year_end_digest(history_rows: List[Dict[str, Any]], today) -> bool:
    start, end = get_year_range(today)
    table_rows = build_side_by_side_rows(filter_by_effective_range(history_rows, start, end))
    subject = f"Index Monitor — Year-End Digest — {start[:4]}"
    intro = f"All index changes effective between {start} and {end} (this year):"
    return send_report_email(table_rows, subject, intro)


# ---------------------------------------------------------------------------
# Combined runner
# ---------------------------------------------------------------------------

def normalize_index_bucket(index_name_from_release: Optional[str], fallback: str) -> str:
    """Map a row's own `index_name_from_release` (taken straight from the
    press release's summary table, e.g. "S&P SmallCap 600", "S&P MidCap
    400") to the bucket name it actually belongs in. This is what replaces
    re-scraping the identical feed once per index_type."""
    if not index_name_from_release:
        return fallback
    n = index_name_from_release.lower()
    if 'smallcap 600' in n or 's&p 600' in n:
        return 'S&P 600'
    if 'midcap 400' in n or 's&p 400' in n:
        return 'S&P 400'
    if 's&p 100' in n:
        return 'S&P 100'
    if 's&p 500' in n:
        return 'S&P 500'
    if 'transportation average' in n:
        return 'Dow Transportation'
    if 'utility average' in n or 'utilities average' in n:
        return 'Dow Utility'
    if 'industrial average' in n or n.strip() == 'dow':
        return 'Dow Industrial'
    # Unknown/unexpected label -- keep the release's own wording rather than
    # silently mislabeling it into one of the buckets above.
    return index_name_from_release


def run_all() -> Dict[str, List[Dict[str, Any]]]:
    results: Dict[str, List[Dict[str, Any]]] = {
        'S&P 500': [], 'S&P 400': [], 'S&P 600': [], 'S&P 100': [], 'Dow Industrial': [],
        'Nasdaq-100': [], 'Russell 3000': [], 'Russell 2000': [], 'Russell 1000': [],
    }

    # CONFIRMED BUG (fixed here): the old version created 5 separate
    # SPScraper instances -- one per index_type in
    # ['sp500','sp400','sp600','sp100','dow'] -- and called .scrape() on
    # each. But SPScraper's feed URL, TITLE_KEYWORDS, and extraction logic
    # never actually reference self.index_type, so all 5 instances hit the
    # EXACT SAME prnewswire.com feed and extracted the EXACT SAME rows --
    # just re-labeled under a different bucket key each time. That's why
    # the CSV showed every row duplicated 5x. The real per-row index
    # (S&P 500 vs MidCap 400 vs SmallCap 600 vs 100 vs Dow) is already
    # captured correctly per-row in `index_name_from_release` straight from
    # the release's own summary table -- so scrape the feed ONCE and bucket
    # each row using that field instead of the outer loop.
    sp_rows = SPScraper('sp500').scrape()
    for row in sp_rows:
        bucket = normalize_index_bucket(row.get('index_name_from_release'), 'S&P 500')
        results.setdefault(bucket, []).append(row)

    results['Nasdaq-100'] = NasdaqScraper().scrape()

    for index_type in ['r3000', 'r2000', 'r1000']:
        results[RussellScraper.INDEX_NAMES[index_type]] = RussellScraper(index_type).scrape()

    # Second, independent source: Wikipedia's maintained "changes" history
    # tables. Runs AFTER the press-release scrapers above so a specific
    # press-release link wins as the primary source when both report the
    # same event (see _dedupe_flat_rows); Wikipedia's main value-add is
    # catching merger/spin-off-driven ticker & name changes that never got
    # a distinct index-change press release in the first place -- see
    # WikipediaChangesScraper's docstring for the WestRock/Smurfit example.
    for bucket in ['S&P 500', 'S&P 400', 'S&P 600', 'S&P 100', 'Dow Industrial', 'Nasdaq-100']:
        results.setdefault(bucket, []).extend(WikipediaChangesScraper(bucket).scrape())

    return results


def flatten(results: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Turn the {index_name: [changes]} dict into one flat list of rows,
    each tagged with which index bucket it was found under."""
    rows = []
    for index_name, changes in results.items():
        for c in changes:
            row = dict(c)
            row['index_bucket'] = index_name
            rows.append(row)
    return rows


def filter_going_forward(rows: List[Dict[str, Any]], as_of: Optional[str] = None) -> List[Dict[str, Any]]:
    """Keep only rows whose effective_date is today or later. This is the
    "going forward" requirement: changes that have already taken effect
    (history) are dropped, so the CSV only shows what's still ahead."""
    cutoff = as_of or datetime.now().date().isoformat()
    kept = []
    for r in rows:
        eff = r.get('effective_date')
        if eff and eff >= cutoff:  # ISO date strings compare correctly as text
            kept.append(r)
    return kept


def write_csv(rows: List[Dict[str, Any]], path: str) -> None:
    """`rows` are the 8-column paired table rows (REPORT_COLUMNS keys), the
    same ones that go into the Excel report and the email table."""
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_COLUMNS, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    logger.info(f"Wrote {len(rows)} row(s) to {path}")


# ---------------------------------------------------------------------------
# Excel report -- single sheet, the same 8-column Removed/Added table as the
# email, matching KING's reference file (index_changes_going_forward1.xlsx,
# sheet "Side by side") exactly.
# ---------------------------------------------------------------------------

_XLSX_FONT = Font(name='Arial', size=10)
_XLSX_HEADER_FONT = Font(name='Arial', size=10, bold=True, color='FFFFFF')
_XLSX_HEADER_FILL = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
_XLSX_NOTE_FONT = Font(name='Arial', size=9, italic=True, color='808080')
_XLSX_LINK_FONT = Font(name='Arial', size=10, color='0563C1', underline='single')


def write_xlsx(rows: List[Dict[str, Any]], path: str, sheet_title: str = "Side by side") -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title

    for c, h in enumerate(REPORT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = _XLSX_HEADER_FONT
        cell.fill = _XLSX_HEADER_FILL

    r = 2
    for row in rows:
        for c, col_name in enumerate(REPORT_COLUMNS, start=1):
            value = row.get(col_name, '')
            cell = ws.cell(row=r, column=c, value=value)
            if col_name == 'Refer Link' and value:
                cell.hyperlink = value
                cell.font = _XLSX_LINK_FONT
            else:
                cell.font = _XLSX_FONT
        r += 1

    if r == 2:
        cell = ws.cell(row=r, column=1, value="(no changes found for this report)")
        cell.font = _XLSX_NOTE_FONT

    widths = {'A': 14, 'B': 32, 'C': 14, 'D': 14, 'E': 32, 'F': 14, 'G': 16, 'H': 34, 'I': 50, 'J': 40}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w

    wb.save(path)
    logger.info(f"Wrote Excel report ({len(rows)} row(s)) to {path}")


# ---------------------------------------------------------------------------
# "Evidence" report -- per KING's request #2/#3/#4: a single Excel file
# gathering, across all runs, every index change this script has traced
# specifically to a merger / acquisition / spin-off / business combination /
# ticker-or-name change -- INCLUDING the ones no distinct index-change press
# release ever covered (the WikipediaChangesScraper cases). Built from the
# full accumulated history file (index_changes_history.csv), not just
# today's run, so it's a complete record over time, not a daily snapshot.
# Controlled by GENERATE_EVIDENCE_REPORT (see email_config.txt) so KING can
# turn it on/off himself without touching code.
# ---------------------------------------------------------------------------

EVIDENCE_XLSX_PATH = 'index_changes_evidence.xlsx'
_CORPORATE_ACTION_LABELS = set(CORPORATE_ACTION_KEYWORDS.keys())  # Merger/Acquisition, Spin-off, Business Combination, Ticker/Name Change


def is_corporate_action_reason(reason: Optional[str]) -> bool:
    """True only for a REAL merger/acquisition/spin-off/business-combination
    /ticker-or-name-change reason. Deliberately excludes a blank reason and
    the generic 'Corporate Action / Index Update' fallback label (used for
    ordinary rebalance reasons like "Market capitalization change." that
    aren't a corporate action at all) -- this is what keeps the evidence
    report to only the events KING actually asked about."""
    if not reason:
        return False
    label = reason.split(':', 1)[0].strip()
    return label in _CORPORATE_ACTION_LABELS


def build_evidence_rows(history_rows: List[Dict[str, Any]], year: int) -> List[Dict[str, Any]]:
    """Filter the full accumulated history down to real corporate-action
    -driven changes effective in `year`, then pair them the same way as the
    main report -- so a pure rename (e.g. WestRock -> Smurfit Westrock)
    still gets the clear 'same index member' remark instead of looking like
    an unmatched add/remove."""
    year_prefix = f"{year:04d}-"
    filtered = [
        r for r in history_rows
        if (r.get('effective_date') or '').startswith(year_prefix)
        and is_corporate_action_reason(r.get('reason'))
    ]
    return build_side_by_side_rows(filtered)


def write_evidence_report(rows: List[Dict[str, Any]], year: int, path: str = EVIDENCE_XLSX_PATH) -> None:
    write_xlsx(rows, path, sheet_title=f"Corporate Actions {year}")
    logger.info(f"[Evidence] Wrote {len(rows)} corporate-action row(s) for {year} to {path}")


def format_latest_filing_text(row: Optional[Dict[str, Any]]) -> str:
    """Render a row's SEC filing fields as the short phrase KING's own
    reference file uses, e.g. "10-Q filed in 2026", "20-F/A filed in 2026",
    "New cik Yet not filed 10-K or 10-Q"."""
    if not row:
        return ''
    if not row.get('cik'):
        return 'CIK not found'
    if not row.get('latest_form_type'):
        return 'New cik Yet not filed 10-K or 10-Q'
    year = (row.get('latest_filing_date') or '')[:4] or '?'
    return f"{row['latest_form_type']} filed in {year}"


def _pair_added_removed_for_index(added_list: List[Dict[str, Any]],
                                   removed_list: List[Dict[str, Any]]) -> List[tuple]:
    """Pair each index's Removed rows with its Added rows for the "Side by
    side" sheet. Same-effective-date rows (the normal case -- a scheduled
    rebalance removes N and adds N on the same day) are paired first,
    alphabetically by company name, and marked "Same effective date".
    Anything left over (uneven counts, or historical removals/additions
    that don't share a date) is paired positionally afterward and marked
    so it's clear these aren't a direct one-for-one swap."""

    def by_date(rows_list):
        d = defaultdict(list)
        for r in rows_list:
            d[r.get('effective_date')].append(r)
        for k in d:
            d[k].sort(key=lambda r: (r.get('company_name') or ''))
        return d

    added_by_date = by_date(added_list)
    removed_by_date = by_date(removed_list)
    common_dates = sorted(set(added_by_date) & set(removed_by_date))

    pairs = []
    leftover_removed, leftover_added = [], []

    for d in common_dates:
        a_list, r_list = added_by_date[d], removed_by_date[d]
        n = min(len(a_list), len(r_list))
        for i in range(n):
            pairs.append((r_list[i], a_list[i], "Same effective date"))
        leftover_removed.extend(r_list[n:])
        leftover_added.extend(a_list[n:])

    for d, r_list in removed_by_date.items():
        if d not in common_dates:
            leftover_removed.extend(r_list)
    for d, a_list in added_by_date.items():
        if d not in common_dates:
            leftover_added.extend(a_list)

    leftover_removed.sort(key=lambda r: (r.get('effective_date') or '', r.get('company_name') or ''))
    leftover_added.sort(key=lambda r: (r.get('effective_date') or '', r.get('company_name') or ''))

    for i in range(max(len(leftover_removed), len(leftover_added))):
        r = leftover_removed[i] if i < len(leftover_removed) else None
        a = leftover_added[i] if i < len(leftover_added) else None
        if r and a:
            remark = "Different effective dates — paired for reference only"
        elif r:
            remark = "Removed, no matching addition found"
        else:
            remark = "Added, no matching removal found"
        pairs.append((r, a, remark))

    return pairs


if __name__ == '__main__':
    all_results = run_all()
    all_rows = _dedupe_flat_rows(flatten(all_results))
    today_date = datetime.now().date()
    today = today_date.isoformat()
    future_rows = filter_going_forward(all_rows, as_of=today)

    print(json.dumps(all_results, indent=2))
    print(f"\nTotal changes/events found (including history): {len(all_rows)}")
    print(f"Going-forward changes (effective_date >= {today}): {len(future_rows)}")

    table_rows = build_side_by_side_rows(future_rows)

    csv_path = 'index_changes_going_forward.csv'
    write_csv(table_rows, csv_path)
    print(f"\nGoing-forward results written to: {csv_path}")

    xlsx_path = 'index_changes_going_forward.xlsx'
    write_xlsx(table_rows, xlsx_path)
    print(f"Excel report written to: {xlsx_path}")

    if table_rows:
        for r in table_rows:
            print(f"  [{r['Indices']}] Removed: {r['Removed'] or '-'} ({r['Removed Ticker'] or '-'})  "
                  f"Added: {r['Added'] or '-'} ({r['Added Ticker'] or '-'})  {r['Remarks']}")
    else:
        print("  (none found -- either no upcoming changes were published yet, or a source "
              "failed to fetch; check the log lines above for HTTP status codes and link counts)")

    # Persist today's findings into the running history file -- this is
    # what the weekly / month-end / year-end digests below draw on, since
    # by the time those run, some of today's "going forward" items will
    # have already taken effect and dropped out of the going-forward view.
    history_rows = append_to_history(all_rows)

    # "Evidence" Excel of merger/acquisition/spin-off/business-combination/
    # ticker-name-change-driven changes for this year, built from the full
    # accumulated history -- see GENERATE_EVIDENCE_REPORT in email_config.txt.
    if GENERATE_EVIDENCE_REPORT:
        evidence_rows = build_evidence_rows(history_rows, today_date.year)
        write_evidence_report(evidence_rows, today_date.year)
        print(f"Evidence report ({len(evidence_rows)} corporate-action row(s) for {today_date.year}) "
              f"written to: {EVIDENCE_XLSX_PATH}")
    else:
        print("GENERATE_EVIDENCE_REPORT is off -- skipping evidence report "
              "(enable it in email_config.txt or the env var to turn back on).")

    print()
    daily_subject = f"Index Monitor — Going Forward Changes — {today}"
    daily_intro = f"Going-forward index changes as of {today} ({len(table_rows)} pairing(s)):"
    email_sent = send_report_email(table_rows, daily_subject, daily_intro)
    if email_sent:
        print(f"Daily email sent. To={SMTP_TO_EMAILS} Cc={SMTP_CC_EMAILS} From={SMTP_SENDER_EMAIL}.")
    else:
        print("Daily email NOT sent -- see the [Email] warning/error above "
              f"(most likely SMTP_PASSWORD isn't set yet; this needs a Gmail App Password for "
              f"{SMTP_SENDER_EMAIL}, not its regular password).")

    # ---- Weekly (Sunday) / month-end / year-end digests -------------------
    # All computed from the accumulated history file, not just this run, so
    # they include everything that became effective during the period even
    # if it's no longer "going forward" today.
    if today_date.weekday() == 6:  # Monday=0 ... Sunday=6
        print("\nToday is Sunday -- sending weekly digest...")
        sent = send_weekly_digest(history_rows, today_date)
        print("Weekly digest sent." if sent else "Weekly digest NOT sent (see [Email] log above).")

    if is_last_day_of_month(today_date):
        print("\nToday is the last day of the month -- sending month-end digest...")
        sent = send_month_end_digest(history_rows, today_date)
        print("Month-end digest sent." if sent else "Month-end digest NOT sent (see [Email] log above).")

    if is_year_end(today_date):
        print(f"\nToday matches the year-end date ({YEAR_END_MMDD}) -- sending year-end digest...")
        sent = send_year_end_digest(history_rows, today_date)
        print("Year-end digest sent." if sent else "Year-end digest NOT sent (see [Email] log above).")
