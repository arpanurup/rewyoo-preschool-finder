import streamlit as st
import pandas as pd
import requests
import re
import json
import io
import time

from bs4 import BeautifulSoup
from urllib.parse import urlparse
from ddgs import DDGS
from datetime import datetime


# ==========================================
# APPLICATION SETTINGS
# ==========================================

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
        "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    )
}

BLOCKED_DOMAINS = [
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "linkedin.com",
    "twitter.com",
    "pinterest.com",
    "wikipedia.org",
    "scribd.com",
    "quora.com",
    "reddit.com",
    "justdial.com",
    "sulekha.com",
    "yellowpages.com",
    "yellowpages.in",
    "edustoke.com",
    "yellowpages.net",
    "mouthshut.com",
    "shiksha.com",
    "collegedunia.com",
    "proeves.com",
    "schoolmykids.com",
    "preprimaryschools.com"
]

BLOCKED_PATHS = [
    "/blog/",
    "/blogs/",
    "/article/",
    "/articles/",
    "/news/",
    "/stories/",
    "/document/",
    "/documents/",
    "/wiki/",
    "/definition/",
    "/what-is-",
    "/guide/",
    "/guides/",
    "/registration/"
]


# ==========================================
# SESSION STORAGE
# ==========================================

if "results" not in st.session_state:
    st.session_state.results = []

if "history" not in st.session_state:
    st.session_state.history = []


# ==========================================
# TEXT UTILITIES
# ==========================================

def clean_text(value):

    if not value:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value)
    ).strip()


def normalize(value):

    value = clean_text(value).lower()

    value = re.sub(
        r"[^a-z0-9\s]",
        " ",
        value
    )

    return re.sub(
        r"\s+",
        " ",
        value
    ).strip()


def root_website(url):

    try:

        parsed = urlparse(url)

        if not parsed.netloc:
            return ""

        return (
            f"{parsed.scheme or 'https'}://"
            f"{parsed.netloc.lower()}"
        )

    except Exception:

        return ""


def valid_domain(url):

    try:

        domain = urlparse(url).netloc.lower()

        if not domain:
            return False

        for blocked in BLOCKED_DOMAINS:

            if blocked in domain:
                return False

        path = urlparse(url).path.lower()

        for blocked in BLOCKED_PATHS:

            if blocked in path:
                return False

        return True

    except Exception:

        return False


def location_match(text, locality, district, state):

    text = normalize(text)

    if locality.strip():

        return normalize(locality) in text

    if district.strip():

        return normalize(district) in text

    if state.strip():

        return normalize(state) in text

    return False


# ==========================================
# JSON-LD EXTRACTION
# ==========================================

def extract_jsonld(soup):

    output = []

    for script in soup.find_all(
        "script",
        type="application/ld+json"
    ):

        try:

            data = json.loads(
                script.string or script.get_text()
            )

            if isinstance(data, list):

                output.extend(data)

            else:

                output.append(data)

        except Exception:

            continue

    return output


def flatten_json(data):

    result = []

    def walk(obj):

        if isinstance(obj, dict):

            result.append(obj)

            for value in obj.values():

                walk(value)

        elif isinstance(obj, list):

            for value in obj:

                walk(value)

    walk(data)

    return result


# ==========================================
# BUSINESS INFORMATION
# ==========================================

def get_business_details(items):

    details = {

        "name": "",
        "branch": "",
        "address": "",
        "locality": "",
        "pincode": "",
        "district": "",
        "state": "",
        "country": "",
        "email": "",
        "phone": "",
        "established": ""

    }

    for item in items:

        item_type = item.get("@type", "")

        if isinstance(item_type, list):

            item_type = " ".join(item_type)

        item_type = str(item_type).lower()

        business_types = [
            "preschool",
            "school",
            "localbusiness",
            "childcare",
            "educationalorganization",
            "organization"
        ]

        if (
            not details["name"]
            and any(x in item_type for x in business_types)
        ):

            details["name"] = clean_text(
                item.get("name", "")
            )

        if (
            not details["branch"]
            and item.get("branchOf")
        ):

            branch = item.get("branchOf")

            if isinstance(branch, dict):

                details["branch"] = clean_text(
                    branch.get("name", "")
                )

        address = item.get("address")

        if isinstance(address, dict):

            details["address"] = clean_text(
                ", ".join(
                    str(address.get(k, ""))
                    for k in [
                        "streetAddress",
                        "addressLocality",
                        "addressRegion",
                        "postalCode",
                        "addressCountry"
                    ]
                    if address.get(k)
                )
            )

            details["locality"] = clean_text(
                address.get("addressLocality", "")
            )

            details["pincode"] = clean_text(
                address.get("postalCode", "")
            )

            details["district"] = clean_text(
                address.get("addressLocality", "")
            )

            details["state"] = clean_text(
                address.get("addressRegion", "")
            )

            country = address.get(
                "addressCountry",
                ""
            )

            if isinstance(country, dict):

                country = country.get("name", "")

            details["country"] = clean_text(country)

        elif isinstance(address, str):

            details["address"] = clean_text(address)

        if not details["email"]:

            details["email"] = clean_text(
                item.get("email", "")
            )

        if not details["phone"]:

            details["phone"] = clean_text(
                item.get("telephone", "")
            )

        if not details["established"]:

            date = item.get("foundingDate")

            if date:

                match = re.search(
                    r"\b(19|20)\d{2}\b",
                    str(date)
                )

                if match:

                    details["established"] = (
                        match.group(0)
                    )

    return details


# ==========================================
# ESTABLISHED YEAR EXTRACTION
# ==========================================

def extract_established_year(text):

    patterns = [

        r"(?:established|founded|started|incorporated)"
        r"\s+(?:in\s+)?(?:the\s+year\s+)?(19\d{2}|20[0-2]\d)",

        r"(?:since|est\.?)\s+(19\d{2}|20[0-2]\d)",

        r"(19\d{2}|20[0-2]\d)"
        r"\s+(?:was\s+)?(?:established|founded)",

        r"(?:our\s+journey\s+began|founded\s+in)"
        r"\s+(19\d{2}|20[0-2]\d)"

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            year = int(match.group(1))

            if 1950 <= year <= datetime.now().year:

                return str(year)

    return ""


# ==========================================
# PHONE EXTRACTION
# ==========================================

def extract_phones(text):

    matches = re.findall(
        r"(?:\+91[\s-]?)?[6-9]\d{9}",
        text
    )

    output = []

    for phone in matches:

        phone = re.sub(
            r"\D",
            "",
            phone
        )

        if len(phone) == 12 and phone.startswith("91"):

            phone = phone[2:]

        if (
            len(phone) == 10
            and phone[0] in "6789"
            and phone not in output
        ):

            output.append(phone)

    return output


# ==========================================
# WEBPAGE EXTRACTION
# ==========================================

def extract_page(url):

    details = {

        "name": "",
        "branch": "",
        "email": "",
        "phones": [],
        "address": "",
        "locality": "",
        "pincode": "",
        "district": "",
        "state": "",
        "country": "",
        "established": "",
        "text": ""

    }

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=15
        )

        if response.status_code != 200:

            return details

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        json_items = flatten_json(
            extract_jsonld(soup)
        )

        structured = get_business_details(
            json_items
        )

        for key in structured:

            if structured[key]:

                details[key] = structured[key]

        # Page title

        if not details["name"]:

            if soup.title:

                details["name"] = clean_text(
                    soup.title.get_text()
                )

        # Emails

        emails = []

        for link in soup.find_all(
            "a",
            href=True
        ):

            href = link["href"]

            if href.lower().startswith("mailto:"):

                emails.append(
                    href.replace(
                        "mailto:",
                        ""
                    ).split("?")[0]
                )

        page_emails = re.findall(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            response.text
        )

        emails.extend(page_emails)

        for email in emails:

            email = email.strip().lower()

            if (
                re.fullmatch(
                    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                    email
                )
                and not any(
                    bad in email
                    for bad in [
                        "example.com",
                        "domain.com",
                        "test.com"
                    ]
                )
            ):

                details["email"] = email

                break

        # Phone numbers

        page_text = clean_text(
            soup.get_text(" ", strip=True)
        )

        details["phones"] = extract_phones(
            page_text
        )

        # Address

        if not details["address"]:

            for tag in soup.find_all(
                "address",
                limit=5
            ):

                address = clean_text(
                    tag.get_text(" ", strip=True)
                )

                if len(address) > 10:

                    details["address"] = address

                    break

        # Remove irrelevant text from the page

        for tag in soup([
            "script",
            "style",
            "noscript"
        ]):

            tag.decompose()

        details["text"] = clean_text(
            soup.get_text(" ", strip=True)
        )[:20000]

        # Pincode

        if not details["pincode"]:

            match = re.search(
                r"\b[1-8]\d{5}\b",
                details["text"]
            )

            if match:

                details["pincode"] = match.group(0)

        # Established year

        if not details["established"]:

            details["established"] = (
                extract_established_year(
                    details["text"]
                )
            )

        return details

    except Exception:

        return details


# ==========================================
# PRESCHOOL VALIDATION
# ==========================================

def preschool_validation(text, locality, district, state):

    text = normalize(text)

    keywords = [

        "preschool",
        "pre school",
        "pre school education",
        "playschool",
        "play school",
        "montessori",
        "kindergarten",
        "nursery school",
        "daycare",
        "day care"

    ]

    if not any(
        keyword in text
        for keyword in keywords
    ):

        return False

    irrelevant = [

        "what is montessori",
        "definition of montessori",
        "psychology",
        "research paper",
        "school registration form",
        "government of california",
        "captcha",
        "download pdf",
        "best schools in india blog",
        "top 10 schools blog"

    ]

    if any(
        word in text
        for word in irrelevant
    ):

        return False

    return location_match(
        text,
        locality,
        district,
        state
    )


# ==========================================
# NAME EXTRACTION
# ==========================================

def clean_name(name):

    name = clean_text(name)

    separators = [
        " | ",
        " - ",
        " – ",
        " — ",
        " : "
    ]

    for separator in separators:

        if separator in name:

            name = name.split(
                separator
            )[0].strip()

    return name[:150]


# ==========================================
# SEARCH ENGINE
# ==========================================

def search_preschools(

    location,
    locality,
    district,
    state,
    country,
    categories,
    limit

):

    results = []

    seen_urls = set()

    seen_branches = set()

    search_queries = []

    # Multiple search variations

    for category in categories:

        search_queries.extend([

            f"{category} {locality} {district} {state} address contact",

            f"preschool {locality} {district} official website",

            f"playschool {locality} {state} phone address",

            f"Montessori preschool {locality} {district}",

            f"daycare preschool {locality} {district} contact"

        ])

    search_queries = list(
        dict.fromkeys(search_queries)
    )

    progress = st.progress(0)

    status = st.empty()

    total_queries = len(search_queries)

    for query_number, query in enumerate(search_queries):

        if len(results) >= limit:

            break

        status.write(
            f"Searching: {query}"
        )

        try:

            with DDGS() as ddgs:

                search_results = list(
                    ddgs.text(
                        query,
                        max_results=min(limit, 40)
                    )
                )

        except Exception:

            search_results = []

        for result in search_results:

            if len(results) >= limit:

                break

            url = result.get("href", "")

            if not url.startswith("http"):

                continue

            if not valid_domain(url):

                continue

            website = root_website(url)

            if url in seen_urls:

                continue

            seen_urls.add(url)

            snippet = clean_text(
                result.get("body", "")
            )

            title = clean_text(
                result.get("title", "")
            )

            # Extract website information

            page = extract_page(url)

            combined_text = (

                title + " " +
                snippet + " " +
                page["text"] + " " +
                page["address"] + " " +
                page["name"]

            )

            # Validate preschool and location

            if not preschool_validation(

                combined_text,
                locality,
                district,
                state

            ):

                continue

            # Prefer actual business name

            name = clean_name(
                page["name"]
            )

            if not name:

                name = clean_name(title)

            if not name:

                continue

            # Reject generic article titles

            generic_names = [

                "what is montessori",
                "montessori education",
                "best preschools",
                "preschool admission",
                "kindergarten registration",
                "preschool meaning"

            ]

            if normalize(name) in generic_names:

                continue

            # Phone

            phones = page["phones"]

            phone = (
                phones[0]
                if len(phones) > 0
                else ""
            )

            alternate = (
                phones[1]
                if len(phones) > 1
                else ""
            )

            # Branch address

            address = page["address"]

            actual_locality = page["locality"]

            actual_district = page["district"]

            actual_state = page["state"]

            actual_country = page["country"]

            pincode = page["pincode"]

            # Only use locality input after location validation

            if not actual_locality and locality:

                if normalize(locality) in normalize(combined_text):

                    actual_locality = locality

            # Fill country only if the location is validated

            if not actual_country and country:

                actual_country = country

            # Branch key

            branch_key = (

                normalize(name),

                normalize(address),

                phone

            )

            if branch_key in seen_branches:

                continue

            seen_branches.add(branch_key)

            # Identify branch name from structured data

            branch = page["branch"]

            record = {

                "Preschool Name": name,

                "Branch Name": branch,

                "Website": website,

                "Email": page["email"],

                "Phone Number": phone,

                "Alternate Phone": alternate,

                "Full Address": address,

                "Locality": actual_locality,

                "Pincode": pincode,

                "District": actual_district,

                "State": actual_state,

                "Country": actual_country,

                "Preschool Type": "Preschool",

                "Category": "Preschool",

                "Established Year": page["established"]

            }

            results.append(record)

            time.sleep(0.5)

        progress.progress(

            min(
                100,
                int(
                    ((query_number + 1) / total_queries) * 100
                )
            )

        )

    status.success(
        f"Search completed. {len(results)} relevant records discovered."
    )

    return results


# ==========================================
# APPLICATION INTERFACE
# ==========================================

st.title("Rewyoo Preschool Finder")

st.caption(
    "Preschool discovery, data extraction and Excel export across India"
)

st.info(
    "Discover preschool businesses and their branches using public web sources."
)


# ==========================================
# LOCATION
# ==========================================

st.subheader("1. Search Location")

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

    max_results = st.select_slider(
        "Maximum number of preschool records",
        options=list(range(5, 501, 5)),
        value=100,
        format_func=lambda x: f"{x} records"
    )


# ==========================================
# CATEGORY
# ==========================================

st.subheader("2. Preschool Categories")

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
    "All categories are selected by default."
)


# ==========================================
# START SEARCH
# ==========================================

st.divider()

st.subheader("3. Start Data Extraction")

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

        location = ", ".join(
            x for x in [
                locality,
                district,
                state,
                country
            ]
            if x.strip()
        )

        try:

            new_records = search_preschools(

                location=location,

                locality=locality,

                district=district,

                state=state,

                country=country,

                categories=categories,

                limit=max_results

            )

            combined = (
                st.session_state.results
                + new_records
            )

            df = pd.DataFrame(
                combined,
                columns=FIELDS
            )

            df["_key"] = (

                df["Preschool Name"]
                .fillna("")
                .apply(normalize)

                + "|"

                +

                df["Full Address"]
                .fillna("")
                .apply(normalize)

                + "|"

                +

                df["Phone Number"]
                .fillna("")

            )

            df = df.drop_duplicates(
                subset="_key",
                keep="first"
            )

            df = df.drop(
                columns=["_key"]
            )

            st.session_state.results = (
                df.to_dict("records")
            )

            st.session_state.history.append({

                "Search Date": datetime.now().strftime(
                    "%d-%m-%Y %H:%M"
                ),

                "Location": location,

                "Records Found": len(new_records)

            })

            st.success(
                f"{len(new_records)} new records discovered."
            )

        except Exception as error:

            st.error(
                f"Search failed: {error}"
            )


# ==========================================
# RESULTS
# ==========================================

st.divider()

st.subheader("4. Extracted Preschool Database")

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

        worksheet = writer.sheets[
            "Preschool Data"
        ]

        worksheet.freeze_panes = "A2"

        worksheet.auto_filter.ref = (
            worksheet.dimensions
        )

        for column in worksheet.columns:

            width = max(
                len(str(cell.value or ""))
                for cell in column
            )

            worksheet.column_dimensions[
                column[0].column_letter
            ].width = min(
                width + 2,
                40
            )

    st.download_button(

        "Download Preschool Data in Excel",

        data=output.getvalue(),

        file_name="Rewyoo_Preschool_Database.xlsx",

        mime=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),

        type="primary",

        use_container_width=True

    )

    if st.button("Clear Current Results"):

        st.session_state.results = []

        st.rerun()

else:

    st.info(
        "No records available. Start a search."
    )


# ==========================================
# SEARCH HISTORY
# ==========================================

st.divider()

st.subheader("5. Search History")

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
        "Search history is available during the current session."
    )


st.divider()

st.caption(
    "Rewyoo Preschool Finder | Preschool Discovery and Data Extraction"
)
