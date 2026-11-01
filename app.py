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


# ==================================================
# APPLICATION CONFIGURATION
# ==================================================

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
    "blogspot.com"
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
    "top 10",
    "best schools",
    "best preschool",
    "how to",
    "blog",
    "article",
    "news",
    "ranking",
    "comparison"
]

PRESCHOOL_WORDS = [
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

st.session_state.setdefault("results", [])
st.session_state.setdefault("history", [])


# ==================================================
# TEXT UTILITIES
# ==================================================

def clean_text(value):

    if not value:
        return ""

    value = html.unescape(str(value))

    return re.sub(
        r"\s+",
        " ",
        value
    ).strip()


def get_domain(url):

    return urlparse(url).netloc.lower().replace(
        "www.",
        ""
    )


def is_blocked(url):

    domain = get_domain(url)

    return any(
        blocked in domain
        for blocked in BLOCKED_DOMAINS
    )


def normalise_url(url):

    parsed = urlparse(url)

    return (
        parsed.scheme
        + "://"
        + parsed.netloc.lower()
        + parsed.path.rstrip("/")
    )


def is_article_url(url):

    path = urlparse(url).path.lower()

    article_paths = [
        "/blog/",
        "/blogs/",
        "/article/",
        "/articles/",
        "/news/",
        "/what-is-",
        "/guide/",
        "/guides/",
        "/history/",
        "/definition/"
    ]

    return any(
        item in path
        for item in article_paths
    )


def contains_preschool_terms(text):

    text = text.lower()

    return any(
        word in text
        for word in PRESCHOOL_WORDS
    )


# ==================================================
# LOCATION VALIDATION
# ==================================================

def location_matches(text, locality, district, state):

    text = text.lower()

    locality = locality.lower().strip()
    district = district.lower().strip()
    state = state.lower().strip()

    # Whitefield is mandatory when searching Whitefield.

    if locality:

        locality_variants = [
            locality,
            locality.replace(" ", ""),
            locality.replace(" ", "-")
        ]

        locality_found = any(
            value in text
            for value in locality_variants
        )

        # Known spelling variations.

        if locality == "whitefield":

            locality_found = (
                locality_found
                or "white field" in text
            )

        if not locality_found:
            return False

    # Bengaluru / Bangalore variations.

    if district:

        district_variants = [
            district,
            district.replace("bengaluru", "bangalore"),
            district.replace("bangalore", "bengaluru")
        ]

        district_found = any(
            value in text
            for value in district_variants
        )

        if not district_found:
            return False

    if state and state not in text:
        return False

    return True


# ==================================================
# STRUCTURED WEBSITE DATA
# ==================================================

def get_jsonld(soup):

    records = []

    for script in soup.find_all(
        "script",
        type="application/ld+json"
    ):

        try:

            parsed = json.loads(
                script.string or script.get_text()
            )

            records.append(parsed)

        except Exception:
            continue

    return records


def flatten_json(data):

    records = []

    def walk(obj):

        if isinstance(obj, dict):

            records.append(obj)

            for value in obj.values():
                walk(value)

        elif isinstance(obj, list):

            for value in obj:
                walk(value)

    walk(data)

    return records


def get_organisation_name(items):

    accepted_types = [
        "preschool",
        "school",
        "educationalorganization",
        "localbusiness",
        "childcare",
        "organization"
    ]

    for item in items:

        item_type = item.get("@type", "")

        if isinstance(item_type, list):
            item_type = " ".join(item_type)

        item_type = str(item_type).lower()

        if any(
            word in item_type
            for word in accepted_types
        ):

            name = clean_text(
                item.get("name", "")
            )

            if name:
                return name

    return ""


def get_structured_address(items):

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

            address_text = ", ".join(
                clean_text(x)
                for x in parts
                if x
            )

            if address_text:
                return address_text

        elif isinstance(address, str):

            return clean_text(address)

    return ""


# ==================================================
# CONTACT INFORMATION
# ==================================================

def extract_email(text):

    emails = re.findall(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        text
    )

    emails = list(dict.fromkeys(emails))

    invalid = [
        "example.com",
        "domain.com",
        "email.com"
    ]

    for email in emails:

        if not any(
            value in email.lower()
            for value in invalid
        ):

            return email

    return ""


def extract_phones(text):

    matches = re.findall(
        r"(?:\+91[\s-]?)?[6-9]\d{9}",
        text
    )

    numbers = []

    for match in matches:

        number = re.sub(
            r"\D",
            "",
            match
        )

        if len(number) == 12 and number.startswith("91"):
            number = number[2:]

        if len(number) == 10:

            if number not in numbers:
                numbers.append(number)

    return numbers


# ==================================================
# ESTABLISHED YEAR
# ==================================================

def extract_established_year(text, items):

    current_year = datetime.now().year

    # Structured founding date.

    for item in items:

        for key in [
            "foundingDate",
            "dateCreated"
        ]:

            value = str(
                item.get(key, "")
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
        r"established\s+(?:in\s+)?(?:the\s+year\s+)?((?:19|20)\d{2})",
        r"founded\s+(?:in\s+)?((?:19|20)\d{2})",
        r"since\s+((?:19|20)\d{2})",
        r"started\s+(?:in\s+)?((?:19|20)\d{2})",
        r"incorporated\s+(?:in\s+)?((?:19|20)\d{2})",
        r"establishment\s+year\s*[:\-]?\s*((?:19|20)\d{2})",
        r"our\s+journey\s+began\s+in\s+((?:19|20)\d{2})"
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


# ==================================================
# BRANCH INFORMATION
# ==================================================

def extract_branch_name(
    items,
    address,
    locality
):

    for item in items:

        for key in [
            "branchName",
            "locationName"
        ]:

            value = clean_text(
                item.get(key, "")
            )

            if value:
                return value

    if address:

        parts = [
            clean_text(part)
            for part in address.split(",")
            if clean_text(part)
        ]

        if parts:

            # Avoid copying the entire street address
            # into the branch name.

            if len(parts) >= 2:
                return parts[-2]

            return parts[0]

    return locality


# ==================================================
# PRESCHOOL NAME
# ==================================================

def extract_preschool_name(
    title,
    structured_name
):

    if structured_name:
        return structured_name

    title = clean_text(title)

    for separator in [
        " | ",
        " - ",
        " – ",
        " — ",
        " : "
    ]:

        if separator in title:
            title = title.split(separator)[0].strip()

    if title and len(title) < 120:
        return title

    return ""


# ==================================================
# PRESCHOOL CATEGORY
# ==================================================

def classify_preschool(text):

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


# ==================================================
# WEBSITE READER
# ==================================================

def read_page(url):

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=12
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


# ==================================================
# EXTRACT PRESCHOOL WEBSITE
# ==================================================

def extract_preschool(
    url,
    locality,
    district,
    state
):

    response, soup = read_page(url)

    if response is None:
        return None

    title = clean_text(
        soup.title.get_text()
        if soup.title else ""
    )

    items = flatten_json(
        get_jsonld(soup)
    )

    structured_name = get_organisation_name(
        items
    )

    address = get_structured_address(
        items
    )

    # Extract visible content.

    for tag in soup([
        "script",
        "style",
        "noscript"
    ]):

        tag.decompose()

    page_text = clean_text(
        soup.get_text(" ", strip=True)
    )

    full_text = (
        title + " "
        + address + " "
        + page_text
    )

    # Strict preschool validation.

    if not contains_preschool_terms(full_text):
        return None

    # Strict location validation.

    location_text = (
        full_text + " "
        + url
    )

    if not location_matches(
        location_text,
        locality,
        district,
        state
    ):
        return None

    # Reject informational articles.

    if any(
        word in title.lower()
        for word in ARTICLE_WORDS
    ):
        return None

    # Require a meaningful organisation name.

    name = extract_preschool_name(
        title,
        structured_name
    )

    if not name:
        return None

    # Avoid generic information pages.

    generic_names = [
        "home",
        "about us",
        "contact us",
        "montessori",
        "montessori theory",
        "what is montessori",
        "preschool education",
        "early childhood education"
    ]

    if name.lower() in generic_names:
        return None

    # Contacts.

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

    # Address and pincode.

    pincode_match = re.search(
        r"\b[1-8]\d{5}\b",
        address + " " + page_text
    )

    pincode = (
        pincode_match.group()
        if pincode_match
        else ""
    )

    # Establishment year.

    established_year = extract_established_year(
        page_text,
        items
    )

    branch = extract_branch_name(
        items,
        address,
        locality
    )

    return {
        "Preschool Name": name,
        "Branch Name": branch,
        "Website": normalise_url(url),
        "Email": email,
        "Phone Number": phone,
        "Alternate Phone": alternate,
        "Full Address": address,
        "Locality": locality,
        "Pincode": pincode,
        "District": district,
        "State": state,
        "Country": "India",
        "Preschool Type": classify_preschool(full_text),
        "Category": "Preschool",
        "Established Year": established_year
    }


# ==================================================
# SEARCH ENGINE
# ==================================================

def search_preschools(
    locality,
    district,
    state,
    categories,
    max_results,
    progress,
    status
):

    location = (
        f"{locality}, {district}, {state}, India"
    )

    queries = []

    for category in categories:

        queries.extend([
            f'{category} "{locality}" "{district}" India',
            f'{category} in {locality} Bengaluru Karnataka',
            f'{category} centres {locality} Bangalore India'
        ])

    discovered = []

    seen_urls = set()

    total = len(queries)

    for index, query in enumerate(queries):

        status.write(
            f"Searching: {query}"
        )

        try:

            with DDGS() as ddgs:

                results = list(
                    ddgs.text(
                        query,
                        max_results=max_results,
                        region="in-en"
                    )
                )

        except Exception as error:

            status.warning(
                f"Search request could not be completed: {error}"
            )

            results = []

        for result in results:

            url = result.get("href", "")

            if not url.startswith("http"):
                continue

            if is_blocked(url):
                continue

            if is_article_url(url):
                continue

            clean_url = normalise_url(url)

            if clean_url in seen_urls:
                continue

            seen_urls.add(clean_url)

            status.write(
                f"Checking preschool website: {clean_url}"
            )

            record = extract_preschool(
                clean_url,
                locality,
                district,
                state
            )

            if record:

                discovered.append(record)

            time.sleep(0.4)

        progress.progress(
            int(((index + 1) / total) * 100)
        )

        time.sleep(0.5)

    return discovered


# ==================================================
# DUPLICATE REMOVAL
# ==================================================

def remove_duplicates(records):

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

    df = df.drop(
        columns=["_url"]
    )

    return df


# ==================================================
# DASHBOARD
# ==================================================

st.title(
    "Rewyoo Preschool Finder"
)

st.caption(
    "Preschool discovery and data extraction across India"
)

st.info(
    "Search for actual preschool establishments and physical branches. "
    "Educational articles and general information pages are excluded."
)


# LOCATION

st.subheader(
    "1. Search Location"
)

col1, col2, col3 = st.columns(3)

with col1:

    locality = st.text_input(
        "Locality / Area",
        value="Whitefield"
    )

with col2:

    district = st.text_input(
        "District",
        value="Bengaluru Urban"
    )

with col3:

    state = st.text_input(
        "State",
        value="Karnataka"
    )


# RESULT LIMIT

st.subheader(
    "2. Search Results"
)

max_results = st.selectbox(
    "Show results",
    [10, 50, 100, 300, 500],
    index=0
)

st.caption(
    "This controls the maximum number of search results requested "
    "for each search query. Actual verified preschool records may be fewer."
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
    "Includes independent centres, chains and franchise branches."
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

    if not locality.strip():

        st.error(
            "Please enter a locality."
        )

    elif not district.strip() or not state.strip():

        st.error(
            "Please enter the district and state."
        )

    elif not categories:

        st.error(
            "Please select at least one category."
        )

    else:

        progress = st.progress(0)

        status = st.empty()

        try:

            records = search_preschools(
                locality.strip(),
                district.strip(),
                state.strip(),
                categories,
                max_results,
                progress,
                status
            )

            new_df = remove_duplicates(
                records
            )

            old_df = pd.DataFrame(
                st.session_state.results,
                columns=FIELDS
            )

            combined = pd.concat(
                [old_df, new_df],
                ignore_index=True
            )

            combined = remove_duplicates(
                combined.to_dict("records")
            )

            st.session_state.results = (
                combined.to_dict("records")
            )

            st.session_state.history.append({
                "Search Date": datetime.now().strftime(
                    "%d-%m-%Y %H:%M"
                ),
                "Location": (
                    f"{locality}, {district}, {state}, India"
                ),
                "Records Found": len(new_df)
            })

            status.success(
                f"Search completed. "
                f"{len(new_df)} relevant records discovered."
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
        "No preschool records available. Start a search to discover preschools."
    )


# HISTORY

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
    "Rewyoo Preschool Finder | Location-filtered extraction"
)
