import streamlit as st
import pandas as pd
import requests
import re
import time

from io import BytesIO
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from ddgs import DDGS


# =====================================================
# PAGE CONFIGURATION
# =====================================================

st.set_page_config(
    page_title="Rewyoo Preschool Finder",
    page_icon="🏫",
    layout="wide"
)

st.title("Rewyoo Preschool Finder")
st.caption("Preschool discovery and data extraction across India")

st.divider()


# =====================================================
# SEARCH CONFIGURATION
# =====================================================

st.subheader("Search Configuration")

pincode = st.text_input(
    "Enter Pincode",
    placeholder="Example: 560066",
    max_chars=6
)

st.text_input(
    "Country",
    value="India",
    disabled=True
)

result_limit = st.selectbox(
    "Maximum Records",
    [5, 10, 25, 50, 100, 200, 300, 400, 500],
    index=0
)

categories = st.multiselect(
    "Preschool Categories",
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

st.divider()


# =====================================================
# PINCODE RESPONSE PARSER
# =====================================================

def parse_pincode_response(data):

    if not isinstance(data, dict):
        return None

    # Current V1 API response format
    if data.get("success") is True:

        api_data = data.get("data", {})

        offices = api_data.get("post_offices", [])

        if offices:

            first_office = offices[0]

            district = first_office.get("district", "")
            state = first_office.get("state", "")

            if district and state:
                return {
                    "district": district,
                    "state": state,
                    "offices": offices
                }

    # Alternative API response format
    api_data = data.get("data")

    if isinstance(api_data, dict):

        offices = api_data.get("post_offices", [])

        if offices:

            first_office = offices[0]

            district = first_office.get("district", "")
            state = first_office.get("state", "")

            if district and state:
                return {
                    "district": district,
                    "state": state,
                    "offices": offices
                }

    # Older API response format
    if isinstance(api_data, list) and api_data:

        first_office = api_data[0]

        district = (
            first_office.get("District")
            or first_office.get("district")
            or ""
        )

        state = (
            first_office.get("State")
            or first_office.get("state")
            or first_office.get("statename")
            or ""
        )

        if district and state:
            return {
                "district": district,
                "state": state,
                "offices": api_data
            }

    return None


# =====================================================
# PINCODE VALIDATION
# =====================================================

def get_pincode_details(pin):

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }

    api_urls = [
        f"https://api.postalpincode.in/pincode/{pin}",
        f"https://api.pincodeapi.in/v1/pincode/{pin}",
        f"https://api.pincodeapi.in/api/v1/pincode/{pin}"
    ]

    for url in api_urls:

        try:

            response = requests.get(
                url,
                headers=headers,
                timeout=15
            )

            response.raise_for_status()

            data = response.json()

            # India Post API format
            if isinstance(data, list):

                if data and data[0].get("Status") == "Success":

                    offices = data[0].get("PostOffice") or []

                    if offices:

                        return {
                            "district": offices[0].get("District", ""),
                            "state": offices[0].get("State", ""),
                            "offices": offices
                        }

            # Other API formats
            result = parse_pincode_response(data)

            if result:
                return result

        except Exception:
            continue

    return None


# =====================================================
# CONTACT EXTRACTION
# =====================================================

def extract_contacts(url):

    emails = set()
    phones = set()

    try:

        response = requests.get(
            url,
            timeout=12,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        if response.status_code != 200:
            return "", ""

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        text = soup.get_text(" ", strip=True)

        # Email extraction
        email_matches = re.findall(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            text
        )

        for email in email_matches:

            email = email.lower()

            if not email.endswith(
                (".png", ".jpg", ".jpeg", ".webp")
            ):
                emails.add(email)

        # Phone extraction
        phone_matches = re.findall(
            r"(?:\+91[\s-]?)?[6-9]\d{9}",
            text
        )

        for phone in phone_matches:

            cleaned = re.sub(r"\D", "", phone)

            if cleaned.startswith("91") and len(cleaned) == 12:
                cleaned = cleaned[2:]

            if len(cleaned) == 10:
                phones.add(cleaned)

    except Exception:
        pass

    return (
        ", ".join(sorted(emails)),
        ", ".join(sorted(phones))
    )


# =====================================================
# PRESCHOOL SEARCH
# =====================================================

def search_preschools(
    pin,
    district,
    state,
    selected_categories,
    limit
):

    records = []

    seen_urls = set()
    seen_names = set()

    location = f"{district} {state} India"

    progress = st.progress(0)
    status = st.empty()

    total_categories = len(selected_categories)

    try:

        with DDGS() as search_engine:

            for index, category in enumerate(selected_categories):

                status.info(
                    f"Searching for {category} near PIN code {pin}..."
                )

                queries = [
                    f'{category} "{pin}" India',
                    f'{category} near PIN code {pin} {location}',
                    f'{category} in {district} {state} India'
                ]

                for query in queries:

                    if len(records) >= limit:
                        break

                    try:

                        results = search_engine.text(
                            query,
                            region="in-en",
                            safesearch="moderate",
                            max_results=15
                        )

                    except Exception:
                        continue

                    for result in results:

                        if len(records) >= limit:
                            break

                        title = result.get(
                            "title", ""
                        ).strip()

                        url = result.get(
                            "href", ""
                        ).strip()

                        snippet = result.get(
                            "body", ""
                        ).strip()

                        if not title or not url:
                            continue

                        parsed_url = urlparse(url)

                        if parsed_url.scheme not in [
                            "http",
                            "https"
                        ]:
                            continue

                        if not parsed_url.netloc:
                            continue

                        combined_text = (
                            title + " " + snippet
                        ).lower()

                        preschool_terms = [
                            "preschool",
                            "pre school",
                            "playschool",
                            "play school",
                            "montessori",
                            "nursery",
                            "kindergarten",
                            "daycare",
                            "day care"
                        ]

                        if not any(
                            term in combined_text
                            for term in preschool_terms
                        ):
                            continue

                        normalized_url = (
                            url.split("?")[0]
                            .rstrip("/")
                            .lower()
                        )

                        normalized_name = re.sub(
                            r"[^a-z0-9]",
                            "",
                            title.lower()
                        )

                        if normalized_url in seen_urls:
                            continue

                        if normalized_name in seen_names:
                            continue

                        seen_urls.add(normalized_url)
                        seen_names.add(normalized_name)

                        status.info(
                            f"Extracting details: {title}"
                        )

                        email, phone = extract_contacts(url)

                        records.append({

                            "Preschool Name": title,
                            "Branch Name": "",
                            "Website": url,
                            "Email": email,
                            "Phone Number": phone,
                            "Alternate Phone": "",
                            "Full Address": snippet,
                            "Locality": "",
                            "Pincode": pin,
                            "District": district,
                            "State": state,
                            "Country": "India",
                            "Preschool Type": category,
                            "Category": category,
                            "Established Year": ""

                        })

                        time.sleep(0.3)

                progress.progress(
                    (index + 1) / total_categories
                )

    finally:

        progress.empty()
        status.empty()

    return records


# =====================================================
# EXCEL GENERATION
# =====================================================

def create_excel(records):

    columns = [
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

    df = pd.DataFrame(
        records,
        columns=columns
    )

    output = BytesIO()

    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:

        df.to_excel(
            writer,
            index=False,
            sheet_name="Preschool Data"
        )

        worksheet = writer.sheets["Preschool Data"]

        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions

        for column_cells in worksheet.columns:

            max_length = max(
                len(str(cell.value or ""))
                for cell in column_cells
            )

            worksheet.column_dimensions[
                column_cells[0].column_letter
            ].width = min(max_length + 3, 45)

    output.seek(0)

    return output


# =====================================================
# START SEARCH
# =====================================================

if st.button(
    "Start Preschool Search",
    type="primary",
    use_container_width=True
):

    if (
        not pincode.isdigit()
        or len(pincode) != 6
        or pincode[0] == "0"
    ):

        st.error(
            "Please enter a valid six-digit Indian PIN code."
        )

    elif not categories:

        st.error(
            "Please select at least one preschool category."
        )

    else:

        with st.spinner(
            "Validating Indian PIN code..."
        ):

            pin_details = get_pincode_details(pincode)

        if not pin_details:

            st.error(
                "Unable to retrieve PIN code information "
                "from the available postal services. "
                "Please try again later."
            )

        else:

            district = pin_details["district"]
            state = pin_details["state"]

            st.success(
                f"PIN code verified: {district}, {state}, India"
            )

            st.info(
                "Searching public websites for preschool listings. "
                "This may take a few minutes."
            )

            try:

                records = search_preschools(
                    pincode,
                    district,
                    state,
                    categories,
                    result_limit
                )

                if records:

                    df = pd.DataFrame(records)

                    st.success(
                        f"Search completed. "
                        f"Found {len(records)} potential listings."
                    )

                    st.subheader("Search Results")

                    st.dataframe(
                        df,
                        use_container_width=True,
                        hide_index=True
                    )

                    excel_file = create_excel(records)

                    st.download_button(
                        label="Download Excel",
                        data=excel_file,
                        file_name=(
                            f"Rewyoo_Preschools_{pincode}.xlsx"
                        ),
                        mime=(
                            "application/vnd.openxmlformats-officedocument."
                            "spreadsheetml.sheet"
                        ),
                        type="primary",
                        use_container_width=True
                    )

                    st.caption(
                        "Please verify the listings and contact details "
                        "before using them. Public search results may "
                        "contain incomplete or outdated information."
                    )

                else:

                    st.warning(
                        "No matching preschool listings were found. "
                        "Please try again later."
                    )

            except Exception as error:

                st.error(
                    "The preschool search could not be completed."
                )

                st.caption(str(error))


# =====================================================
# FOOTER
# =====================================================

st.divider()

st.caption(
    "Rewyoo Preschool Finder | India"
)
