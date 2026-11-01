import streamlit as st
import pandas as pd
import requests
import re
import json
import time
import io
from bs4 import BeautifulSoup
from urllib.parse import urlparse
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

BLOCKED_DOMAINS = [
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "scribd.com",
    "pinterest.com",
    "wikipedia.org",
    "justdial.com",
    "sulekha.com",
    "yellowpages.com",
    "yellowpages.in",
    "mouthshut.com",
    "quora.com",
    "reddit.com"
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    )
}


# --------------------------------------------------
# SESSION STORAGE
# --------------------------------------------------

if "results" not in st.session_state:
    st.session_state.results = []

if "history" not in st.session_state:
    st.session_state.history = []


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def clean_text(value):
    if not value:
        return ""

    return re.sub(r"\s+", " ", str(value)).strip()


def root_website(url):
    try:
        parsed = urlparse(url)

        if not parsed.netloc:
            return ""

        domain = parsed.netloc.lower()

        if not parsed.scheme:
            return "https://" + domain

        return f"{parsed.scheme}://{domain}"

    except Exception:
        return ""


def is_valid_domain(url):

    try:
        domain = urlparse(url).netloc.lower()

        if not domain:
            return False

        if any(blocked in domain for blocked in BLOCKED_DOMAINS):
            return False

        return True

    except Exception:
        return False


def extract_jsonld(soup):

    collected = []

    for script in soup.find_all(
        "script",
        type="application/ld+json"
    ):

        try:
            parsed = json.loads(
                script.string or script.get_text()
            )

            if isinstance(parsed, list):
                collected.extend(parsed)
            else:
                collected.append(parsed)

        except Exception:
            continue

    return collected


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


def get_jsonld_details(items):

    details = {
        "name": "",
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

        if not details["name"]:

            name = item.get("name")

            if isinstance(name, str):
                details["name"] = clean_text(name)

        address = item.get("address")

        if isinstance(address, dict):

            details["address"] = clean_text(
                ", ".join(
                    str(address.get(key, ""))
                    for key in [
                        "streetAddress",
                        "addressLocality",
                        "addressRegion",
                        "postalCode",
                        "addressCountry"
                    ]
                    if address.get(key)
                )
            )

            details["locality"] = clean_text(
                address.get("addressLocality", "")
            )

            details["pincode"] = clean_text(
                address.get("postalCode", "")
            )

            details["state"] = clean_text(
                address.get("addressRegion", "")
            )

            country = address.get("addressCountry", "")

            if isinstance(country, dict):
                country = country.get("name", "")

            details["country"] = clean_text(country)

        elif isinstance(address, str):

            details["address"] = clean_text(address)

        if not details["email"] and item.get("email"):
            details["email"] = clean_text(item["email"])

        if not details["phone"] and item.get("telephone"):
            details["phone"] = clean_text(item["telephone"])

        if not details["established"] and item.get("foundingDate"):

            year = re.search(
                r"\b(19|20)\d{2}\b",
                str(item["foundingDate"])
            )

            if year:
                details["established"] = year.group(0)

    return details


def extract_page(url):

    details = {
        "name": "",
        "email": "",
        "phones": [],
        "address": "",
        "locality": "",
        "pincode": "",
        "district": "",
        "state": "",
        "country": "",
        "established": "",
        "page_text": ""
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

        title = soup.title

        if title:
            details["name"] = clean_text(
                title.get_text()
            )

        json_items = flatten_json(
            extract_jsonld(soup)
        )

        structured = get_jsonld_details(json_items)

        for key in structured:

            if structured[key]:
                details[key] = structured[key]

        # Extract emails

        emails = re.findall(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            response.text
        )

        emails = list(dict.fromkeys(emails))

        emails = [
            email for email in emails
            if not any(
                bad in email.lower()
                for bad in [
                    "example.com",
                    "domain.com",
                    "test.com"
                ]
            )
        ]

        if not details["email"] and emails:
            details["email"] = emails[0]

        # Extract phone numbers

        phones = re.findall(
            r"(?:\+91[\s-]?)?[6-9]\d{9}",
            response.text
        )

        cleaned_phones = []

        for phone in phones:

            phone = re.sub(r"\D", "", phone)

            if len(phone) == 12 and phone.startswith("91"):
                phone = phone[2:]

            if len(phone) == 10 and phone[0] in "6789":

                if phone not in cleaned_phones:
                    cleaned_phones.append(phone)

        details["phones"] = cleaned_phones

        # Extract page text

        for tag in soup([
            "script",
            "style",
            "noscript"
        ]):
            tag.decompose()

        details["page_text"] = clean_text(
            soup.get_text(" ", strip=True)
        )[:15000]

        # Extract pincode if structured data did not provide it

        if not details["pincode"]:

            pincode = re.search(
                r"\b[1-8]\d{5}\b",
                details["page_text"]
            )

            if pincode:
                details["pincode"] = pincode.group(0)

        # Extract visible address elements if available

        if not details["address"]:

            for tag in soup.find_all(
                ["address"],
                limit=5
            ):

                address = clean_text(
                    tag.get_text(" ", strip=True)
                )

                if len(address) > 10:
                    details["address"] = address
                    break

        return details

    except Exception:
        return details


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


def clean_preschool_name(name):

    name = clean_text(name)

    for separator in [
        " | ",
        " - ",
        " – ",
        " — ",
        " : "
    ]:

        if separator in name:
            name = name.split(separator)[0].strip()

    return name[:150]


def get_domain_name(url):

    domain = urlparse(url).netloc.lower()

    domain = domain.replace("www.", "")

    return domain


def is_preschool_relevant(text):

    text = text.lower()

    keywords = [
        "preschool",
        "pre-school",
        "playschool",
        "play school",
        "montessori",
        "kindergarten",
        "nursery school",
        "daycare",
        "day care"
    ]

    return any(
        keyword in text
        for keyword in keywords
    )


# --------------------------------------------------
# SEARCH ENGINE
# --------------------------------------------------

def search_preschools(
    location,
    selected_categories,
    limit,
    locality,
    district,
    state,
    country
):

    found = []

    seen_urls = set()
    seen_branches = set()

    queries = [
        f"{category} in {location} India"
        for category in selected_categories
    ]

    progress_text = st.empty()

    progress_bar = st.progress(0)

    total_queries = len(queries)

    for query_number, query in enumerate(queries):

        if len(found) >= limit:
            break

        progress_text.write(
            f"Searching: {query}"
        )

        try:

            with DDGS() as ddgs:

                search_results = list(
                    ddgs.text(
                        query,
                        max_results=limit
                    )
                )

        except Exception:

            search_results = []

        for result in search_results:

            if len(found) >= limit:
                break

            url = result.get("href", "")

            if not url.startswith("http"):
                continue

            if not is_valid_domain(url):
                continue

            normalized_url = root_website(url)

            if url in seen_urls:
                continue

            seen_urls.add(url)

            snippet = clean_text(
                result.get("body", "")
            )

            page = extract_page(url)

            combined_text = (
                page["name"] + " " +
                snippet + " " +
                page["page_text"]
            )

            if not is_preschool_relevant(combined_text):
                continue

            # Identify preschool name

            name = page["name"]

            if not name:

                name = get_domain_name(url)

                name = name.replace(
                    ".com",
                    ""
                ).replace(
                    ".in",
                    ""
                ).replace(
                    "-",
                    " "
                ).title()

            name = clean_preschool_name(name)

            if not name:
                continue

            # Extract phone numbers

            phones = page["phones"]

            primary_phone = (
                phones[0] if len(phones) > 0 else ""
            )

            alternate_phone = (
                phones[1] if len(phones) > 1 else ""
            )

            # Use branch address information only when available

            address = page["address"]

            actual_locality = page["locality"]

            actual_district = page["district"]

            actual_state = page["state"]

            actual_country = page["country"]

            pincode = page["pincode"]

            # Deduplicate using name and address.
            # Do not merge different branches merely because
            # they belong to the same preschool brand.

            branch_key = (
                name.lower(),
                address.lower()
            )

            if branch_key in seen_branches:
                continue

            seen_branches.add(branch_key)

            record = {

                "Preschool Name": name,

                "Branch Name": "",

                "Website": normalized_url,

                "Email": page["email"],

                "Phone Number": primary_phone,

                "Alternate Phone": alternate_phone,

                "Full Address": address,

                "Locality": actual_locality,

                "Pincode": pincode,

                "District": actual_district,

                "State": actual_state,

                "Country": actual_country,

                "Preschool Type": classify_preschool(
                    combined_text
                ),

                "Category": "Preschool",

                "Established Year": page["established"]

            }

            found.append(record)

            time.sleep(0.3)

        progress_bar.progress(
            min(
                100,
                int(
                    ((query_number + 1) / total_queries) * 100
                )
            )
        )

    progress_text.success(
        f"Search completed. {len(found)} records discovered."
    )

    return found


# --------------------------------------------------
# APPLICATION INTERFACE
# --------------------------------------------------

st.title("Rewyoo Preschool Finder")

st.caption(
    "Preschool discovery, data extraction and Excel export across India"
)

st.info(
    "Search for preschools in any Indian locality, city, "
    "district or state."
)


# --------------------------------------------------
# LOCATION INPUT
# --------------------------------------------------

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


# --------------------------------------------------
# CATEGORY SELECTION
# --------------------------------------------------

st.subheader("2. Preschool Categories")

categories = st.multiselect(

    "Select the types of preschools to discover",

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
    "Search includes independent preschools, "
    "branded chains, franchises and daycare-cum-preschools."
)


# --------------------------------------------------
# START SEARCH
# --------------------------------------------------

st.divider()

st.subheader("3. Start Data Extraction")

start = st.button(
    "Start Preschool Search",
    type="primary",
    use_container_width=True
)


if start:

    if not any([
        locality.strip(),
        district.strip(),
        state.strip()
    ]):

        st.error(
            "Please enter at least a locality, district or state."
        )

    elif not categories:

        st.error(
            "Please select at least one preschool category."
        )

    else:

        location_parts = [
            locality.strip(),
            district.strip(),
            state.strip(),
            country.strip()
        ]

        location = ", ".join(
            part
            for part in location_parts
            if part
        )

        try:

            records = search_preschools(

                location=location,

                selected_categories=categories,

                limit=max_results,

                locality=locality,

                district=district,

                state=state,

                country=country

            )

            combined = (
                st.session_state.results + records
            )

            df = pd.DataFrame(
                combined,
                columns=FIELDS
            )

            # Remove exact duplicate records

            df["_key"] = (

                df["Preschool Name"]
                .fillna("")
                .str.lower()
                .str.strip()

                + "|"

                +

                df["Full Address"]
                .fillna("")
                .str.lower()
                .str.strip()

                + "|"

                +

                df["Phone Number"]
                .fillna("")
                .str.lower()
                .str.strip()

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

                "Records Found": len(records)

            })

            st.success(
                f"Search completed. {len(records)} new records discovered."
            )

        except Exception as error:

            st.error(
                f"Search failed: {str(error)}"
            )


# --------------------------------------------------
# DATABASE DISPLAY
# --------------------------------------------------

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

    # Excel export

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

            max_length = max(
                len(str(cell.value or ""))
                for cell in column
            )

            worksheet.column_dimensions[
                column[0].column_letter
            ].width = min(
                max_length + 2,
                40
            )

    st.download_button(

        label="Download Preschool Data in Excel",

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
        "No records available yet. Start a search to discover preschools."
    )


# --------------------------------------------------
# SEARCH HISTORY
# --------------------------------------------------

st.divider()

st.subheader("5. Search History")

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
        "Search history is maintained during the current app session."
    )


# --------------------------------------------------
# FOOTER
# --------------------------------------------------

st.divider()

st.caption(
    "Rewyoo Preschool Finder | Public Web Discovery and Data Extraction"
)
