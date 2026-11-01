import streamlit as st
import pandas as pd
import requests
import re
import json
import time
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from ddgs import DDGS
from datetime import datetime

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

if "results" not in st.session_state:
    st.session_state.results = []

if "history" not in st.session_state:
    st.session_state.history = []

st.title("Rewyoo Preschool Finder")
st.caption("Preschool discovery, data extraction and Excel export across India")

st.info(
    "Search for preschools in any Indian locality, city, district or state. "
    "The application extracts information available from public websites."
)

st.subheader("1. Search Location")

col1, col2, col3 = st.columns(3)

with col1:
    locality = st.text_input("Locality / Area", placeholder="Example: Whitefield")

with col2:
    district = st.text_input("District", placeholder="Example: Bengaluru Urban")

with col3:
    state = st.text_input("State", placeholder="Example: Karnataka")

col4, col5 = st.columns(2)

with col4:
    country = st.text_input("Country", value="India")

with col5:
    max_results = st.selectbox(
        "Maximum search results per search category",
        [10, 20, 30, 40],
        index=1
    )

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
    "The search includes independent centres, branded chains and franchise branches."
)

def clean_text(value):
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()

def extract_jsonld(soup):
    data = []

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            parsed = json.loads(script.string or script.get_text())
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

def get_address(items):
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
            result = ", ".join(clean_text(x) for x in parts if x)
            if result:
                return result

        elif isinstance(address, str) and address.strip():
            return clean_text(address)

    return ""

def extract_page(url):
    details = {
        "Website": url,
        "Email": "",
        "Phone Number": "",
        "Alternate Phone": "",
        "Full Address": "",
        "Pincode": "",
        "Established Year": "",
        "Page Title": "",
        "Page Text": ""
    }

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; RewyooPreschoolFinder/1.0)"
        }

        response = requests.get(
            url,
            headers=headers,
            timeout=12
        )

        if response.status_code != 200:
            return details

        soup = BeautifulSoup(response.text, "html.parser")

        details["Page Title"] = clean_text(
            soup.title.get_text() if soup.title else ""
        )

        for tag in soup(["script", "style", "noscript", "header", "footer"]):
            tag.decompose()

        page_text = clean_text(soup.get_text(" ", strip=True))
        details["Page Text"] = page_text[:12000]

        emails = list(set(re.findall(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            response.text
        )))

        emails = [
            email for email in emails
            if not any(x in email.lower() for x in [
                "example.com", "domain.com", ".png", ".jpg"
            ])
        ]

        if emails:
            details["Email"] = emails[0]

        phones = list(set(re.findall(
            r"(?:\+91[\s-]?)?[6-9]\d{9}",
            page_text
        )))

        phones = [re.sub(r"\D", "", p) for p in phones]
        phones = list(dict.fromkeys(phones))

        if len(phones) > 0:
            details["Phone Number"] = phones[0]

        if len(phones) > 1:
            details["Alternate Phone"] = phones[1]

        json_items = flatten_json(extract_jsonld(soup))

        details["Full Address"] = get_address(json_items)

        pincode = re.search(r"\b[1-8]\d{5}\b", page_text)
        if pincode:
            details["Pincode"] = pincode.group(0)

        for item in json_items:
            if item.get("foundingDate"):
                year = re.search(r"\b(19|20)\d{2}\b", str(item["foundingDate"]))
                if year:
                    details["Established Year"] = year.group(0)
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

def extract_name(title, url):
    title = clean_text(title)

    if title:
        for separator in [" | ", " - ", " – ", " — ", " : "]:
            if separator in title:
                title = title.split(separator)[0].strip()

        return title[:120]

    domain = urlparse(url).netloc.replace("www.", "")
    return domain.split(".")[0].replace("-", " ").title()

def search_preschools(location, selected_categories, limit):
    found = []
    seen_urls = set()

    with DDGS() as ddgs:
        for category in selected_categories:

            query = f"{category} in {location} India"

            try:
                search_results = list(
                    ddgs.text(query, max_results=limit)
                )
            except Exception:
                search_results = []

            for result in search_results:

                url = result.get("href", "")

                if not url.startswith("http"):
                    continue

                domain = urlparse(url).netloc.lower()

                if any(x in domain for x in [
                    "facebook.com",
                    "instagram.com",
                    "youtube.com",
                    "linkedin.com",
                    "justdial.com",
                    "sulekha.com"
                ]):
                    continue

                if url in seen_urls:
                    continue

                seen_urls.add(url)

                page = extract_page(url)

                title = page.get("Page Title", "")
                snippet = clean_text(result.get("body", ""))

                name = extract_name(title, url)

                combined_text = (
                    name + " " + snippet + " " +
                    page.get("Page Text", "")
                )

                if not any(word in combined_text.lower() for word in [
                    "preschool",
                    "pre-school",
                    "playschool",
                    "play school",
                    "montessori",
                    "kindergarten",
                    "nursery",
                    "daycare",
                    "day care"
                ]):
                    continue

                address = page.get("Full Address", "")

                found.append({
                    "Preschool Name": name,
                    "Branch Name": "",
                    "Website": url,
                    "Email": page.get("Email", ""),
                    "Phone Number": page.get("Phone Number", ""),
                    "Alternate Phone": page.get("Alternate Phone", ""),
                    "Full Address": address,
                    "Locality": locality,
                    "Pincode": page.get("Pincode", ""),
                    "District": district,
                    "State": state,
                    "Country": country,
                    "Preschool Type": classify_preschool(combined_text),
                    "Category": "Preschool",
                    "Established Year": page.get("Established Year", "")
                })

                time.sleep(0.5)

    return found

st.divider()
st.subheader("3. Start Data Extraction")

start = st.button(
    "Start Preschool Search",
    type="primary",
    use_container_width=True
)

if start:

    if not any([locality.strip(), district.strip(), state.strip()]):
        st.error("Please enter at least a locality, district or state.")
    elif not categories:
        st.error("Please select at least one preschool category.")
    else:

        location_parts = [
            locality.strip(),
            district.strip(),
            state.strip(),
            country.strip()
        ]

        location = ", ".join(x for x in location_parts if x)

        progress = st.progress(0)
        status = st.empty()

        status.write("Searching public websites. Please wait...")

        try:
            records = search_preschools(
                location,
                categories,
                max_results
            )

            progress.progress(100)

            existing = st.session_state.results

            combined = existing + records

            df = pd.DataFrame(combined, columns=FIELDS)

            df["_key"] = (
                df["Preschool Name"].str.lower().fillna("") + "|" +
                df["Website"].str.lower().fillna("")
            )

            df = df.drop_duplicates(subset="_key", keep="first")
            df = df.drop(columns=["_key"])

            st.session_state.results = df.to_dict("records")

            st.session_state.history.append({
                "Search Date": datetime.now().strftime("%d-%m-%Y %H:%M"),
                "Location": location,
                "Records Found": len(records)
            })

            status.success(
                f"Search completed. {len(records)} records discovered."
            )

        except Exception as error:
            st.error(f"Search could not be completed: {error}")

st.divider()
st.subheader("4. Extracted Preschool Database")

if st.session_state.results:

    df = pd.DataFrame(st.session_state.results, columns=FIELDS)

    st.metric("Total Preschool Records", len(df))

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
    )

    excel_data = None

    import io
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(
            writer,
            index=False,
            sheet_name="Preschool Data"
        )

    excel_data = output.getvalue()

    st.download_button(
        label="Download Preschool Data in Excel",
        data=excel_data,
        file_name="Rewyoo_Preschool_Database.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True
    )

    if st.button("Clear Current Results"):
        st.session_state.results = []
        st.rerun()

else:
    st.info("No records available yet. Start a search to discover preschools.")

st.divider()
st.subheader("5. Search History")

if st.session_state.history:
    history_df = pd.DataFrame(st.session_state.history)
    st.dataframe(history_df, use_container_width=True, hide_index=True)
else:
    st.caption("Your searches will appear here during the current app session.")

st.caption(
    "Rewyoo Preschool Finder | Initial Version | "
    "Public web discovery and data extraction"
)
