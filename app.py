import streamlit as st
import pandas as pd
import requests
import re
import json
import io
import time

from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from ddgs import DDGS
from datetime import datetime


# --------------------------------------------------
# APPLICATION SETTINGS
# --------------------------------------------------

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
    "scribd.com",
    "reddit.com",
    "justdial.com",
    "sulekha.com",
    "yellowpages.com",
    "yellowslate.com",
    "edustoke.com",
    "schoolmykids.com"
]

if "results" not in st.session_state:
    st.session_state.results = []

if "history" not in st.session_state:
    st.session_state.history = []


# --------------------------------------------------
# TEXT UTILITIES
# --------------------------------------------------

def clean_text(value):

    if not value:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value)
    ).strip()


def normalise(value):

    return re.sub(
        r"[^a-z0-9]",
        "",
        clean_text(value).lower()
    )


def get_domain(url):

    return urlparse(url).netloc.lower().replace(
        "www.",
        ""
    )


# --------------------------------------------------
# STRUCTURED WEBSITE DATA
# --------------------------------------------------

def extract_jsonld(soup):

    data = []

    for script in soup.find_all(
        "script",
        type="application/ld+json"
    ):

        try:

            parsed = json.loads(
                script.string or script.get_text()
            )

            if isinstance(parsed, list):
                data.extend(parsed)
            else:
                data.append(parsed)

        except Exception:
            continue

    return data


def flatten_json(data):

    items = []

    def walk(obj):

        if isinstance(obj, dict):

            items.append(obj)

            for value in obj.values():
                walk(value)

        elif isinstance(obj, list):

            for value in obj:
                walk(value)

    walk(data)

    return items


def extract_structured_name(items):

    for item in items:

        item_type = item.get("@type", "")

        if isinstance(item_type, list):
            item_type = " ".join(item_type)

        if any(
            word in str(item_type).lower()
            for word in [
                "preschool",
                "school",
                "educationalorganization",
                "localbusiness",
                "childcare",
                "organization"
            ]
        ):

            name = clean_text(
                item.get("name", "")
            )

            if name:
                return name

    return ""


def extract_address(items):

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
                clean_text(x)
                for x in parts
                if x
            )

            if result:
                return result

        elif isinstance(address, str):

            if address.strip():
                return clean_text(address)

    return ""


# --------------------------------------------------
# CONTACT EXTRACTION
# --------------------------------------------------

def extract_email(text):

    emails = re.findall(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        text
    )

    emails = list(dict.fromkeys(emails))

    emails = [
        email for email in emails
        if not any(
            x in email.lower()
            for x in [
                "example.com",
                "domain.com"
            ]
        )
    ]

    return emails[0] if emails else ""


def extract_phones(text):

    phones = re.findall(
        r"(?:\+91[\s-]?)?[6-9]\d{9}",
        text
    )

    cleaned = []

    for phone in phones:

        number = re.sub(
            r"\D",
            "",
            phone
        )

        if len(number) == 10:

            if number not in cleaned:
                cleaned.append(number)

    return cleaned


# --------------------------------------------------
# ESTABLISHED YEAR EXTRACTION
# --------------------------------------------------

def extract_year(text, items):

    current_year = datetime.now().year

    # Structured founding dates.

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

    # Explicit establishment statements.

    patterns = [
        r"established\s+(?:in\s+)?(?:the\s+year\s+)?((?:19|20)\d{2})",
        r"founded\s+(?:in\s+)?((?:19|20)\d{2})",
        r"since\s+((?:19|20)\d{2})",
        r"started\s+(?:in\s+)?((?:19|20)\d{2})",
        r"incorporated\s+(?:in\s+)?((?:19|20)\d{2})",
        r"establishment\s+year\s*[:\-]?\s*((?:19|20)\d{2})",
        r"our\s+journey\s+began\s+in\s+((?:19|20)\d{2})",
        r"founded\s+in\s+the\s+year\s+((?:19|20)\d{2})"
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


# --------------------------------------------------
# BRANCH IDENTIFICATION
# --------------------------------------------------

def extract_branch_name(
    items,
    title,
    address,
    locality
):

    # Prefer explicit branch or location names
    # in structured website data.

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

    # Prefer the physical address when available.

    if address:

        parts = [
            clean_text(x)
            for x in address.split(",")
            if clean_text(x)
        ]

        if parts:
            return ", ".join(parts[:2])

    # Look for the requested locality in the page title.

    if locality and title:

        if locality.lower() in title.lower():
            return locality

    # Check common branch naming patterns.

    patterns = [
        r"\bbranch\s*[-:]?\s*([A-Za-z0-9\s,]+)",
        r"\bcentre\s*[-:]?\s*([A-Za-z0-9\s,]+)",
        r"\bcenter\s*[-:]?\s*([A-Za-z0-9\s,]+)",
        r"\bin\s+([A-Za-z0-9\s]+?)(?:\s*[-|,]|$)",
        r"\bat\s+([A-Za-z0-9\s]+?)(?:\s*[-|,]|$)"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            title,
            re.IGNORECASE
        )

        if match:

            branch = clean_text(
                match.group(1)
            )

            if branch:
                return branch[:100]

    return ""


# --------------------------------------------------
# PRESCHOOL NAME
# --------------------------------------------------

def extract_preschool_name(
    title,
    url,
    structured_name=""
):

    if structured_name:
        return clean_text(structured_name)[:120]

    title = clean_text(title)

    if title:

        for separator in [
            " | ",
            " - ",
            " – ",
            " — ",
            " : "
        ]:

            if separator in title:
                title = title.split(
                    separator
                )[0].strip()

        if title:
            return title[:120]

    domain = get_domain(url)

    return domain.split(".")[0].replace(
        "-",
        " "
    ).title()


# --------------------------------------------------
# CATEGORY IDENTIFICATION
# --------------------------------------------------

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


# --------------------------------------------------
# WEBSITE EXTRACTION
# --------------------------------------------------

def read_page(url):

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=12
        )

        if response.status_code != 200:
            return None, None

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        return response, soup

    except Exception:

        return None, None


def extract_page(url, locality):

    details = {
        "Website": url,
        "Email": "",
        "Phone Number": "",
        "Alternate Phone": "",
        "Full Address": "",
        "Pincode": "",
        "Established Year": "",
        "Page Title": "",
        "Page Text": "",
        "Branch Name": "",
        "Preschool Name": ""
    }

    response, soup = read_page(url)

    if response is None:
        return details

    details["Page Title"] = clean_text(
        soup.title.get_text()
        if soup.title else ""
    )

    items = flatten_json(
        extract_jsonld(soup)
    )

    details["Full Address"] = extract_address(
        items
    )

    structured_name = extract_structured_name(
        items
    )

    details["Preschool Name"] = extract_preschool_name(
        details["Page Title"],
        url,
        structured_name
    )

    # Extract visible website content.

    for tag in soup([
        "script",
        "style",
        "noscript"
    ]):

        tag.decompose()

    page_text = clean_text(
        soup.get_text(" ", strip=True)
    )

    details["Page Text"] = page_text[:40000]

    # Extract contacts.

    details["Email"] = extract_email(
        response.text
    )

    phones = extract_phones(
        page_text
    )

    if phones:
        details["Phone Number"] = phones[0]

    if len(phones) > 1:
        details["Alternate Phone"] = phones[1]

    # Extract pincode.

    pincode = re.search(
        r"\b[1-8]\d{5}\b",
        details["Full Address"] + " " + page_text
    )

    if pincode:
        details["Pincode"] = pincode.group()

    # Extract year.

    details["Established Year"] = extract_year(
        page_text,
        items
    )

    # Extract branch.

    details["Branch Name"] = extract_branch_name(
        items,
        details["Page Title"],
        details["Full Address"],
        locality
    )

    # Check relevant internal pages.

    internal_links = []

    for link in soup.find_all(
        "a",
        href=True
    ):

        href = urljoin(
            url,
            link["href"]
        )

        label = clean_text(
            link.get_text(" ")
        ).lower()

        combined = (
            href + " " + label
        ).lower()

        relevant = any(
            word in combined
            for word in [
                "about",
                "contact",
                "location",
                "branch",
                "centre",
                "center",
                "our-story",
                "our story"
            ]
        )

        if relevant:

            if get_domain(href) == get_domain(url):

                if href not in internal_links:
                    internal_links.append(href)

    # Visit up to four relevant pages.

    for link in internal_links[:4]:

        sub_response, sub_soup = read_page(link)

        if sub_response is None:
            continue

        sub_items = flatten_json(
            extract_jsonld(sub_soup)
        )

        sub_text = clean_text(
            sub_soup.get_text(" ", strip=True)
        )

        # Missing email.

        if not details["Email"]:

            details["Email"] = extract_email(
                sub_response.text
            )

        # Missing phone.

        if not details["Phone Number"]:

            sub_phones = extract_phones(
                sub_text
            )

            if sub_phones:

                details["Phone Number"] = sub_phones[0]

                if len(sub_phones) > 1:
                    details["Alternate Phone"] = sub_phones[1]

        # Missing address.

        if not details["Full Address"]:

            details["Full Address"] = extract_address(
                sub_items
            )

        # Missing year.

        if not details["Established Year"]:

            details["Established Year"] = extract_year(
                sub_text,
                sub_items
            )

        # Missing branch.

        if not details["Branch Name"]:

            details["Branch Name"] = extract_branch_name(
                sub_items,
                clean_text(
                    sub_soup.title.get_text()
                    if sub_soup.title else ""
                ),
                details["Full Address"],
                locality
            )

        # Missing pincode.

        if not details["Pincode"]:

            match = re.search(
                r"\b[1-8]\d{5}\b",
                details["Full Address"] + " " + sub_text
            )

            if match:
                details["Pincode"] = match.group()

        time.sleep(0.2)

    return details


# --------------------------------------------------
# SEARCH ENGINE
# --------------------------------------------------

def is_blocked(url):

    domain = get_domain(url)

    return any(
        blocked in domain
        for blocked in BLOCKED_DOMAINS
    )


def search_preschools(
    location,
    categories,
    max_results,
    locality,
    district,
    state,
    country,
    progress_bar,
    status
):

    found = []

    seen_urls = set()

    total_categories = len(categories)

    for category_number, category in enumerate(categories):

        queries = [
            f"{category} in {location} India official website",
            f"{category} branches locations in {location} India",
            f"{category} centres in {location} India contact"
        ]

        category_results = []

        for query in queries:

            status.write(
                f"Searching: {query}"
            )

            try:

                with DDGS() as ddgs:

                    search_results = list(
                        ddgs.text(
                            query,
                            max_results=max_results
                        )
                    )

                category_results.extend(
                    search_results
                )

            except Exception as error:

                status.warning(
                    f"Some search results could not be retrieved: {error}"
                )

            time.sleep(1)

        for result in category_results:

            url = result.get(
                "href",
                ""
            )

            if not url.startswith("http"):
                continue

            if is_blocked(url):
                continue

            # Remove tracking fragments and query strings.

            parsed = urlparse(url)

            clean_url = (
                parsed.scheme
                + "://"
                + parsed.netloc
                + parsed.path
            ).rstrip("/")

            if clean_url in seen_urls:
                continue

            seen_urls.add(clean_url)

            status.write(
                f"Extracting information from: {clean_url}"
            )

            page = extract_page(
                clean_url,
                locality
            )

            title = page["Page Title"]

            snippet = clean_text(
                result.get("body", "")
            )

            combined_text = (
                title + " "
                + snippet + " "
                + page["Page Text"]
            )

            keywords = [
                "preschool",
                "pre-school",
                "playschool",
                "play school",
                "montessori",
                "kindergarten",
                "nursery",
                "daycare",
                "day care"
            ]

            if not any(
                word in combined_text.lower()
                for word in keywords
            ):
                continue

            record = {
                "Preschool Name": page["Preschool Name"],
                "Branch Name": page["Branch Name"],
                "Website": clean_url,
                "Email": page["Email"],
                "Phone Number": page["Phone Number"],
                "Alternate Phone": page["Alternate Phone"],
                "Full Address": page["Full Address"],
                "Locality": locality,
                "Pincode": page["Pincode"],
                "District": district,
                "State": state,
                "Country": country,
                "Preschool Type": classify_preschool(
                    combined_text
                ),
                "Category": "Preschool",
                "Established Year": page["Established Year"]
            }

            found.append(record)

        progress_bar.progress(
            int(
                ((category_number + 1) / total_categories) * 100
            )
        )

    return found


# --------------------------------------------------
# DUPLICATE REMOVAL
# --------------------------------------------------

def deduplicate_records(records):

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


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

st.title(
    "Rewyoo Preschool Finder"
)

st.caption(
    "Preschool discovery, data extraction and Excel export across India"
)

st.info(
    "Discover independent preschools, playschools, Montessori centres, "
    "kindergartens and daycare-cum-preschools across India."
)


# LOCATION

st.subheader(
    "1. Search Location"
)

col1, col2, col3 = st.columns(3)

with col1:

    locality = st.text_input(
        "Locality / Area",
        placeholder="Example: Whitefield"
    )

with col2:

    district = st.text_input(
        "District",
        placeholder="Example: Bengaluru Urban"
    )

with col3:

    state = st.text_input(
        "State",
        placeholder="Example: Karnataka"
    )

col4, col5 = st.columns(2)

with col4:

    country = st.text_input(
        "Country",
        value="India"
    )

with col5:

    max_results = st.selectbox(
        "Maximum search results per category",
        [50, 100, 200, 300, 500],
        index=4
    )


# CATEGORIES

st.subheader(
    "2. Preschool Categories"
)

categories = st.multiselect(
    "Select preschool types",
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
    "One physical branch should be represented by one Excel row. "
    "Unavailable information will remain blank."
)

st.divider()


# START SEARCH

st.subheader(
    "3. Start Data Extraction"
)

if st.button(
    "Start Preschool Search",
    type="primary",
    use_container_width=True
):

    if not any([
        locality.strip(),
        district.strip(),
        state.strip()
    ]):

        st.error(
            "Enter at least a locality, district or state."
        )

    elif not categories:

        st.error(
            "Select at least one preschool category."
        )

    else:

        location_parts = [
            locality.strip(),
            district.strip(),
            state.strip(),
            country.strip()
        ]

        location = ", ".join(
            x for x in location_parts if x
        )

        progress_bar = st.progress(0)

        status = st.empty()

        try:

            records = search_preschools(
                location,
                categories,
                max_results,
                locality.strip(),
                district.strip(),
                state.strip(),
                country.strip(),
                progress_bar,
                status
            )

            new_df = deduplicate_records(
                records
            )

            existing_df = pd.DataFrame(
                st.session_state.results,
                columns=FIELDS
            )

            combined_df = pd.concat(
                [
                    existing_df,
                    new_df
                ],
                ignore_index=True
            )

            combined_df = deduplicate_records(
                combined_df.to_dict("records")
            )

            st.session_state.results = (
                combined_df.to_dict("records")
            )

            st.session_state.history.append({
                "Search Date": datetime.now().strftime(
                    "%d-%m-%Y %H:%M"
                ),
                "Location": location,
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
    "4. Extracted Preschool Database"
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
        label="Download Preschool Database in Excel",
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
    "5. Search History"
)

if st.session_state.history:

    history_df = pd.DataFrame(
        st.session_state.history
    )

    st.dataframe(
        history_df,
        use_container_width=True,
        hide_index=True
    )

else:

    st.caption(
        "Search history is available during the current app session."
    )


st.caption(
    "Rewyoo Preschool Finder | Version 3.0"
)
