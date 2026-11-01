import streamlit as st
import pandas as pd
import requests
import re
import json
import io
import time
import html

from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from ddgs import DDGS
from datetime import datetime


# =====================================================
# CONFIGURATION
# =====================================================

st.set_page_config(
    page_title="Rewyoo Preschool Finder",
    page_icon="🏫",
    layout="wide"
)

FIELDS = [
    "Preschool Name",
    "Branch Name",
    "Website",
    "Email",
    "Phone Number",
    "Alternate Phone",
    "Full Address",
    "Locality",
    "Pincode",
    "District",
    "State",
    "Country",
    "Preschool Type",
    "Category",
    "Established Year"
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120 Safari/537.36"
    )
}

BLOCKED_DOMAINS = [
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "linkedin.com",
    "pinterest.com",
    "wikipedia.org",
    "britannica.com",
    "scribd.com",
    "reddit.com",
    "justdial.com",
    "sulekha.com",
    "yellowpages.com",
    "yellowslate.com",
    "edustoke.com",
    "schoolmykids.com",
    "quora.com",
    "medium.com",
    "wordpress.com",
    "blogspot.com",
    "glassdoor.com"
]

ARTICLE_WORDS = [
    "what is",
    "meaning of",
    "definition of",
    "benefits of",
    "advantages of",
    "disadvantages of",
    "history of",
    "theory",
    "method guide",
    "how to",
    "blog",
    "article",
    "news",
    "ranking",
    "comparison"
]

PRESCHOOL_TERMS = [
    "preschool",
    "pre-school",
    "playschool",
    "play school",
    "montessori school",
    "kindergarten",
    "nursery school",
    "early learning centre",
    "early learning center",
    "daycare",
    "day care",
    "child care"
]

BUSINESS_INDICATORS = [
    "admission",
    "admissions",
    "contact us",
    "our centres",
    "our centers",
    "our branches",
    "visit us",
    "enrol",
    "enroll",
    "fees",
    "school hours",
    "location",
    "campus"
]

st.session_state.setdefault("results", [])
st.session_state.setdefault("history", [])


# =====================================================
# UTILITIES
# =====================================================

def clean(value):

    if not value:
        return ""

    return re.sub(
        r"\s+",
        " ",
        html.unescape(str(value))
    ).strip()


def domain_of(url):

    return urlparse(url).netloc.lower().replace(
        "www.", ""
    )


def clean_url(url):

    parsed = urlparse(url)

    return (
        parsed.scheme
        + "://"
        + parsed.netloc.lower()
        + parsed.path.rstrip("/")
    )


def blocked(url):

    domain = domain_of(url)

    return any(
        item in domain
        for item in BLOCKED_DOMAINS
    )


def article_page(title, url):

    title = title.lower()
    path = urlparse(url).path.lower()

    if any(word in title for word in ARTICLE_WORDS):
        return True

    article_paths = [
        "/blog/",
        "/blogs/",
        "/article/",
        "/articles/",
        "/news/",
        "/what-is-",
        "/guide/",
        "/guides/"
    ]

    return any(
        item in path
        for item in article_paths
    )


# =====================================================
# LOCATION VALIDATION
# =====================================================

def location_terms(city, district, state):

    terms = []

    for value in [city, district, state]:

        value = value.strip().lower()

        if value:
            terms.append(value)

    # Bengaluru / Bangalore spelling variation.

    if city.lower().strip() == "bengaluru":
        terms.append("bangalore")

    if city.lower().strip() == "bangalore":
        terms.append("bengaluru")

    return list(set(terms))


def validate_location(
    text,
    locality,
    city,
    district,
    state,
    country,
    pincode
):

    text = text.lower()

    locality = locality.lower().strip()
    city = city.lower().strip()
    state = state.lower().strip()
    country = country.lower().strip()

    # Country validation.

    if country == "india":

        india_evidence = [
            "india",
            "indian",
            "karnataka",
            "bengaluru",
            "bangalore",
            "+91"
        ]

        has_india_evidence = any(
            item in text
            for item in india_evidence
        )

        if not has_india_evidence:
            return False

    # Locality must match.

    if locality:

        variations = [
            locality,
            locality.replace(" ", ""),
            locality.replace(" ", "-")
        ]

        if not any(
            item in text
            for item in variations
        ):

            if locality == "whitefield":

                if "white field" not in text:
                    return False

            else:
                return False

    # City validation.

    if city:

        city_variations = [
            city,
            city.replace("bengaluru", "bangalore"),
            city.replace("bangalore", "bengaluru")
        ]

        if not any(
            item in text
            for item in city_variations
        ):
            return False

    # State validation.

    if state and state not in text:
        return False

    # Exact pincode validation when supplied.

    if pincode:

        pin_match = re.search(
            r"\b\d{6}\b",
            text
        )

        if not pin_match:
            return False

        if pincode not in text:
            return False

    return True


# =====================================================
# STRUCTURED DATA
# =====================================================

def extract_jsonld(soup):

    records = []

    for script in soup.find_all(
        "script",
        type="application/ld+json"
    ):

        try:

            data = json.loads(
                script.string or script.get_text()
            )

            records.append(data)

        except Exception:
            continue

    return records


def flatten(data):

    records = []

    def walk(obj):

        if isinstance(obj, dict):

            records.append(obj)

            for value in obj.values():
                walk(value)

        elif isinstance(obj, list):

            for item in obj:
                walk(item)

    walk(data)

    return records


def organisation_name(items):

    allowed = [
        "preschool",
        "school",
        "educationalorganization",
        "localbusiness",
        "childcare",
        "organization"
    ]

    for item in items:

        typ = item.get("@type", "")

        if isinstance(typ, list):
            typ = " ".join(typ)

        if any(
            word in str(typ).lower()
            for word in allowed
        ):

            name = clean(
                item.get("name", "")
            )

            if name:
                return name

    return ""


def structured_address(items):

    for item in items:

        address = item.get("address")

        if isinstance(address, dict):

            parts = [
                address.get("streetAddress", ""),
                address.get("addressLocality", ""),
                address.get("addressRegion", ""),
                address.get("postalCode", ""),
                address.get("addressCountry", "")
            ]

            result = ", ".join(
                clean(part)
                for part in parts
                if part
            )

            if result:
                return result

        elif isinstance(address, str):

            if address:
                return clean(address)

    return ""


# =====================================================
# CONTACT EXTRACTION
# =====================================================

def extract_email(text):

    matches = re.findall(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        text
    )

    for email in dict.fromkeys(matches):

        if not any(
            item in email.lower()
            for item in [
                "example.com",
                "domain.com",
                "email.com"
            ]
        ):

            return email

    return ""


def extract_phones(text):

    matches = re.findall(
        r"(?:\+91[\s-]?)?[6-9]\d{9}",
        text
    )

    numbers = []

    for value in matches:

        number = re.sub(
            r"\D",
            "",
            value
        )

        if len(number) == 12 and number.startswith("91"):
            number = number[2:]

        if len(number) == 10:

            if number not in numbers:
                numbers.append(number)

    return numbers


# =====================================================
# ESTABLISHED YEAR
# =====================================================

def extract_year(text, items):

    current_year = datetime.now().year

    for item in items:

        value = str(
            item.get("foundingDate", "")
        )

        match = re.search(
            r"\b(?:19|20)\d{2}\b",
            value
        )

        if match:

            year = int(match.group())

            if 1900 <= year <= current_year:
                return str(year)

    patterns = [
        r"established\s+(?:in\s+)?((?:19|20)\d{2})",
        r"founded\s+(?:in\s+)?((?:19|20)\d{2})",
        r"since\s+((?:19|20)\d{2})",
        r"started\s+(?:in\s+)?((?:19|20)\d{2})",
        r"incorporated\s+(?:in\s+)?((?:19|20)\d{2})"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            year = int(match.group(1))

            if 1900 <= year <= current_year:
                return str(year)

    return ""


# =====================================================
# PRESCHOOL IDENTIFICATION
# =====================================================

def preschool_name(title, structured_name):

    if structured_name:
        return structured_name

    title = clean(title)

    for separator in [
        " | ",
        " - ",
        " – ",
        " — ",
        " : "
    ]:

        if separator in title:
            title = title.split(separator)[0].strip()

    if not title or len(title) > 100:
        return ""

    return title


def branch_name(items, address, locality):

    for item in items:

        for key in [
            "branchName",
            "locationName"
        ]:

            value = clean(
                item.get(key, "")
            )

            if value:
                return value

    # Do not invent a branch name from an address.

    # Use the locality only when no branch-specific
    # information is available.

    return locality


def preschool_type(text):

    text = text.lower()

    if "montessori" in text:
        return "Montessori"

    if "daycare" in text or "day care" in text:
        return "Daycare and Preschool"

    if "kindergarten" in text:
        return "Kindergarten"

    if "nursery" in text:
        return "Nursery School"

    if "playschool" in text or "play school" in text:
        return "Playschool"

    return "Preschool"


# =====================================================
# WEBSITE EXTRACTION
# =====================================================

def get_page(url):

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=15
        )

        if response.status_code != 200:
            return None, None

        content_type = response.headers.get(
            "Content-Type",
            ""
        ).lower()

        if "html" not in content_type:
            return None, None

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        return response, soup

    except Exception:

        return None, None


def extract_preschool(
    url,
    locality,
    city,
    district,
    state,
    country,
    pincode,
    search_evidence
):

    response, soup = get_page(url)

    if response is None:
        return None

    title = clean(
        soup.title.get_text()
        if soup.title else ""
    )

    items = flatten(
        extract_jsonld(soup)
    )

    org_name = organisation_name(items)

    address = structured_address(items)

    for tag in soup([
        "script",
        "style",
        "noscript"
    ]):

        tag.decompose()

    page_text = clean(
        soup.get_text(" ", strip=True)
    )

    # Location validation uses actual page content,
    # structured address and search result evidence.

    evidence = (
        address + " "
        + page_text + " "
        + search_evidence
    )

    if not validate_location(
        evidence,
        locality,
        city,
        district,
        state,
        country,
        pincode
    ):
        return None

    combined = title + " " + page_text

    if not any(
        word in combined.lower()
        for word in PRESCHOOL_TERMS
    ):
        return None

    if article_page(title, url):
        return None

    if any(
        word in title.lower()
        for word in ARTICLE_WORDS
    ):
        return None

    name = preschool_name(
        title,
        org_name
    )

    if not name:
        return None

    generic_names = [
        "home",
        "about us",
        "contact us",
        "montessori theory",
        "what is montessori",
        "preschool education",
        "early childhood education"
    ]

    if name.lower() in generic_names:
        return None

    # Require evidence of an actual operating centre.

    has_business_evidence = (
        bool(address)
        or bool(extract_phones(page_text))
        or any(
            word in combined.lower()
            for word in BUSINESS_INDICATORS
        )
    )

    if not has_business_evidence:
        return None

    email = extract_email(
        response.text
    )

    phones = extract_phones(
        page_text
    )

    phone = phones[0] if phones else ""

    alternate = (
        phones[1]
        if len(phones) > 1
        else ""
    )

    # Extract pincode from actual page evidence.

    pin_match = re.search(
        r"\b[1-8]\d{5}\b",
        address + " " + page_text
    )

    extracted_pin = (
        pin_match.group()
        if pin_match
        else ""
    )

    # Do not insert the searched pincode if the website
    # does not publish it.

    if pincode and extracted_pin != pincode:
        return None

    established = extract_year(
        page_text,
        items
    )

    branch = branch_name(
        items,
        address,
        locality
    )

    return {
        "Preschool Name": name,
        "Branch Name": branch,
        "Website": clean_url(url),
        "Email": email,
        "Phone Number": phone,
        "Alternate Phone": alternate,
        "Full Address": address,
        "Locality": locality,
        "Pincode": extracted_pin,
        "District": district,
        "State": state,
        "Country": country,
        "Preschool Type": preschool_type(combined),
        "Category": "Preschool",
        "Established Year": established
    }


# =====================================================
# SEARCH
# =====================================================

def search_preschools(
    locality,
    pincode,
    city,
    district,
    state,
    country,
    categories,
    limit,
    progress,
    status
):

    all_records = []

    seen_urls = set()

    for index, category in enumerate(categories):

        queries = [
            (
                f'{category} "{locality}" "{pincode}" '
                f'"{city}" "{state}" {country} preschool centre'
            ),
            (
                f'{category} in "{locality}" "{city}" '
                f'"{state}" India official website'
            )
        ]

        for query in queries:

            status.write(
                f"Searching: {query}"
            )

            try:

                with DDGS() as ddgs:

                    results = list(
                        ddgs.text(
                            query,
                            region="in-en",
                            max_results=limit
                        )
                    )

            except Exception as error:

                status.warning(
                    f"Search provider error: {error}"
                )

                results = []

            for result in results:

                url = result.get("href", "")

                if not url.startswith("http"):
                    continue

                if blocked(url):
                    continue

                if article_page(
                    result.get("title", ""),
                    url
                ):
                    continue

                url = clean_url(url)

                if url in seen_urls:
                    continue

                seen_urls.add(url)

                search_evidence = (
                    clean(result.get("title", ""))
                    + " "
                    + clean(result.get("body", ""))
                )

                status.write(
                    f"Checking: {url}"
                )

                record = extract_preschool(
                    url,
                    locality,
                    city,
                    district,
                    state,
                    country,
                    pincode,
                    search_evidence
                )

                if record:
                    all_records.append(record)

                time.sleep(0.3)

        progress.progress(
            int(((index + 1) / len(categories)) * 100)
        )

    return all_records


# =====================================================
# DEDUPLICATION
# =====================================================

def deduplicate(records):

    df = pd.DataFrame(
        records,
        columns=FIELDS
    )

    if df.empty:
        return df

    df["_url"] = (
        df["Website"]
        .fillna("")
        .str.lower()
        .str.rstrip("/")
    )

    df = df.drop_duplicates(
        subset="_url",
        keep="first"
    )

    return df.drop(
        columns=["_url"]
    )


# =====================================================
# DASHBOARD
# =====================================================

st.title(
    "Rewyoo Preschool Finder"
)

st.caption(
    "Preschool discovery and data extraction across India"
)

st.info(
    "Search for actual preschool establishments and branches. "
    "Location filters are applied before adding records."
)


# LOCATION INPUTS

st.subheader(
    "1. Search Location"
)

col1, col2 = st.columns(2)

with col1:

    locality = st.text_input(
        "Locality / Area",
        value="Whitefield"
    )

    pincode = st.text_input(
        "Pincode (optional)",
        value="560066",
        max_chars=6
    )

    city = st.text_input(
        "City",
        value="Bengaluru"
    )

with col2:

    district = st.text_input(
        "District",
        value="Bengaluru Urban"
    )

    state = st.text_input(
        "State",
        value="Karnataka"
    )

    country = st.text_input(
        "Country",
        value="India"
    )


# RESULT LIMIT

st.subheader(
    "2. Search Results"
)

limit = st.selectbox(
    "Show results",
    [10, 50, 100, 300, 500],
    index=0
)


# CATEGORIES

st.subheader(
    "3. Preschool Categories"
)

categories = st.multiselect(
    "Select preschool categories",
    [
        "Preschool",
        "Playschool",
        "Montessori",
        "Nursery School",
        "Kindergarten",
        "Daycare and Preschool"
    ],
    default=[
        "Preschool",
        "Playschool",
        "Montessori",
        "Nursery School",
        "Kindergarten",
        "Daycare and Preschool"
    ]
)

st.caption(
    "Includes independent preschools, chains, franchise centres "
    "and daycare-cum-preschools."
)

st.divider()


# START SEARCH

st.subheader(
    "4. Start Data Extraction"
)

if st.button(
    "Start Preschool Search",
    type="primary",
    use_container_width=True
):

    if not all([
        locality.strip(),
        city.strip(),
        district.strip(),
        state.strip(),
        country.strip()
    ]):

        st.error(
            "Please complete all mandatory location fields."
        )

    elif pincode and not re.fullmatch(
        r"\d{6}",
        pincode
    ):

        st.error(
            "Enter a valid six-digit pincode or leave it blank."
        )

    elif not categories:

        st.error(
            "Select at least one preschool category."
        )

    else:

        progress = st.progress(0)

        status = st.empty()

        try:

            records = search_preschools(
                locality.strip(),
                pincode.strip(),
                city.strip(),
                district.strip(),
                state.strip(),
                country.strip(),
                categories,
                limit,
                progress,
                status
            )

            new_df = deduplicate(records)

            old_df = pd.DataFrame(
                st.session_state.results,
                columns=FIELDS
            )

            combined = pd.concat(
                [old_df, new_df],
                ignore_index=True
            )

            combined = deduplicate(
                combined.to_dict("records")
            )

            st.session_state.results = (
                combined.to_dict("records")
            )

            st.session_state.history.append({
                "Search Date": datetime.now().strftime(
                    "%d-%m-%Y %H:%M"
                ),
                "Locality": locality,
                "Pincode": pincode,
                "City": city,
                "District": district,
                "State": state,
                "Country": country,
                "Records Found": len(new_df)
            })

            status.success(
                f"Search completed. {len(new_df)} records discovered."
            )

        except Exception as error:

            st.error(
                f"Search failed: {error}"
            )


# DATABASE

st.divider()

st.subheader(
    "5. Extracted Preschool Database"
)

if st.session_state.results:

    df = pd.DataFrame(
        st.session_state.results,
        columns=FIELDS
    )

    st.metric(
        "Total Preschool Records",
        len(df)
    )

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
    )

    output = io.BytesIO()

    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:

        df.to_excel(
            writer,
            index=False,
            sheet_name="Preschool Data"
        )

    st.download_button(
        "Download Preschool Database in Excel",
        data=output.getvalue(),
        file_name="Rewyoo_Preschool_Database.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True
    )

    if st.button(
        "Clear Current Results"
    ):

        st.session_state.results = []

        st.rerun()

else:

    st.info(
        "No records available. Start a search to discover preschools."
    )


# SEARCH HISTORY

st.divider()

st.subheader(
    "6. Search History"
)

if st.session_state.history:

    st.dataframe(
        pd.DataFrame(
            st.session_state.history
        ),
        use_container_width=True,
        hide_index=True
    )

else:

    st.caption(
        "Search history is maintained during the current app session."
    )


st.caption(
    "Rewyoo Preschool Finder"
)
