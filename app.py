import streamlit as st
import pandas as pd
import requests
import re
import time

from io import BytesIO


# =====================================================
# PAGE CONFIGURATION
# =====================================================

st.set_page_config(
    page_title="Rewyoo Preschool Finder",
    page_icon="🏫",
    layout="wide"
)

st.title("Rewyoo Preschool Finder")
st.caption("Verified preschool discovery across India")

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
# HTTP SESSION
# =====================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "RewyooPreschoolFinder/1.0 (educational business directory)"
})


# =====================================================
# PINCODE VALIDATION
# =====================================================

def get_pincode_details(pin):

    url = (
        "https://api.pincodeapi.in/"
        f"api/v1/pincode/{pin}"
    )

    try:

        response = session.get(
            url,
            timeout=20
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("success"):
            return None

        postal_data = data.get("data", {})

        offices = postal_data.get(
            "post_offices",
            []
        )

        if not offices:
            return None

        district = ""
        state = ""

        for office in offices:

            district = (
                office.get("district")
                or district
            )

            state = (
                office.get("state")
                or state
            )

        if not district or not state:
            return None

        return {
            "district": district,
            "state": state,
            "offices": offices
        }

    except Exception as error:

        st.error(
            f"PIN code validation service error: {error}"
        )

        return None


# =====================================================
# CATEGORY KEYWORD MAPPING
# =====================================================

CATEGORY_KEYWORDS = {

    "Preschool": [
        "preschool",
        "pre-school",
        "pre school"
    ],

    "Playschool": [
        "playschool",
        "play school",
        "play-school"
    ],

    "Montessori": [
        "montessori"
    ],

    "Nursery School": [
        "nursery school",
        "nursery"
    ],

    "Kindergarten": [
        "kindergarten",
        "kindergarden"
    ],

    "Daycare and Preschool": [
        "daycare",
        "day care",
        "child care",
        "childcare"
    ]
}


# =====================================================
# PRESCHOOL CLASSIFICATION
# =====================================================

def identify_categories(tags, selected_categories):

    name = tags.get("name", "").lower()

    combined = " ".join([
        name,
        tags.get("description", "").lower(),
        tags.get("operator", "").lower()
    ])

    matched = []

    for category in selected_categories:

        keywords = CATEGORY_KEYWORDS.get(
            category,
            []
        )

        if any(
            keyword in combined
            for keyword in keywords
        ):

            matched.append(category)

    # OSM kindergarten and childcare classifications
    amenity = tags.get("amenity", "").lower()
    childcare = tags.get("childcare", "").lower()

    if amenity == "kindergarten":

        if "Kindergarten" in selected_categories:
            matched.append("Kindergarten")

    if childcare in ["yes", "kindergarten"]:

        if "Daycare and Preschool" in selected_categories:
            matched.append("Daycare and Preschool")

    return list(set(matched))


# =====================================================
# ADDRESS EXTRACTION
# =====================================================

def build_address(tags):

    parts = []

    address_fields = [
        "addr:housenumber",
        "addr:building",
        "addr:street",
        "addr:suburb",
        "addr:neighbourhood",
        "addr:city",
        "addr:district",
        "addr:postcode"
    ]

    for field in address_fields:

        value = tags.get(field, "").strip()

        if value and value not in parts:
            parts.append(value)

    return ", ".join(parts)


# =====================================================
# CONTACT EXTRACTION
# =====================================================

def extract_phone(tags):

    phone = (
        tags.get("contact:phone")
        or tags.get("phone")
        or ""
    )

    return phone.strip()


def extract_email(tags):

    email = (
        tags.get("contact:email")
        or tags.get("email")
        or ""
    )

    return email.strip()


def extract_website(tags):

    website = (
        tags.get("contact:website")
        or tags.get("website")
        or ""
    )

    return website.strip()


# =====================================================
# EXACT PINCODE SEARCH
# =====================================================

def search_preschools(
    pin,
    district,
    state,
    selected_categories,
    limit
):

    overpass_servers = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter"
    ]

    query = f"""
    [out:json][timeout:60];

    (
      nwr["addr:postcode"="{pin}"]["amenity"="kindergarten"];
      nwr["addr:postcode"="{pin}"]["amenity"="childcare"];
      nwr["addr:postcode"="{pin}"]["name"~"preschool|pre-school|playschool|play school|montessori|nursery|kindergarten|daycare|day care",i];
      nwr["addr:postcode"="{pin}"]["office"="educational_institution"]["name"~"preschool|pre-school|playschool|montessori|nursery|kindergarten",i];
    );

    out center tags;
    """

    data = None
    last_error = None

    for server in overpass_servers:

        try:

            response = session.post(
                server,
                data={"data": query},
                timeout=90
            )

            response.raise_for_status()

            data = response.json()

            break

        except Exception as error:

            last_error = error
            time.sleep(2)

    if data is None:

        raise Exception(
            f"OpenStreetMap search service unavailable: {last_error}"
        )

    elements = data.get("elements", [])

    records = []
    seen = set()

    for element in elements:

        if len(records) >= limit:
            break

        tags = element.get("tags", {})

        name = tags.get("name", "").strip()

        if not name:
            continue

        # Exact postcode validation
        result_pin = (
            tags.get("addr:postcode", "")
            .strip()
        )

        if result_pin != pin:
            continue

        # Check country where available
        country = tags.get(
            "addr:country",
            ""
        ).strip().lower()

        if country and country not in ["in", "india"]:
            continue

        # Check state where available
        result_state = tags.get(
            "addr:state",
            ""
        ).strip().lower()

        if result_state:

            if (
                "karnataka" not in result_state
                and "karnataka" in state.lower()
            ):
                continue

        matched_categories = identify_categories(
            tags,
            selected_categories
        )

        if not matched_categories:
            continue

        element_type = element.get("type", "")
        element_id = element.get("id", "")

        unique_id = f"{element_type}_{element_id}"

        if unique_id in seen:
            continue

        seen.add(unique_id)

        address = build_address(tags)

        latitude = ""
        longitude = ""

        if "lat" in element:
            latitude = element.get("lat", "")
            longitude = element.get("lon", "")

        elif "center" in element:

            center = element.get("center", {})

            latitude = center.get("lat", "")
            longitude = center.get("lon", "")

        locality = (
            tags.get("addr:suburb")
            or tags.get("addr:neighbourhood")
            or tags.get("addr:city")
            or ""
        )

        records.append({

            "Preschool Name": name,

            "Branch Name": tags.get(
                "branch",
                ""
            ),

            "Website": extract_website(tags),

            "Email": extract_email(tags),

            "Phone Number": extract_phone(tags),

            "Alternate Phone": tags.get(
                "contact:phone:alternate",
                ""
            ),

            "Full Address": address,

            "Locality": locality,

            "Pincode": pin,

            "District": district,

            "State": state,

            "Country": "India",

            "Preschool Type": ", ".join(
                matched_categories
            ),

            "Category": ", ".join(
                matched_categories
            ),

            "Established Year": tags.get(
                "start_date",
                ""
            ),

            "Latitude": latitude,

            "Longitude": longitude,

            "Source": (
                f"https://www.openstreetmap.org/"
                f"{element_type}/{element_id}"
            )

        })

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
        "Established Year",
        "Latitude",
        "Longitude",
        "Source"
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

        worksheet = writer.sheets[
            "Preschool Data"
        ]

        worksheet.freeze_panes = "A2"

        worksheet.auto_filter.ref = (
            worksheet.dimensions
        )

        for column_cells in worksheet.columns:

            max_length = max(
                len(str(cell.value or ""))
                for cell in column_cells
            )

            worksheet.column_dimensions[
                column_cells[0].column_letter
            ].width = min(
                max_length + 3,
                45
            )

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
            "Validating PIN code..."
        ):

            pin_details = get_pincode_details(
                pincode
            )

        if not pin_details:

            st.error(
                "Unable to validate the PIN code. "
                "Please try again later."
            )

        else:

            district = pin_details["district"]
            state = pin_details["state"]

            st.success(
                f"PIN code verified: {district}, {state}, India"
            )

            st.info(
                "Searching OpenStreetMap for preschool listings "
                "with the exact PIN code."
            )

            try:

                with st.spinner(
                    "Searching and verifying preschool locations..."
                ):

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
                        f"Found {len(records)} matching "
                        "preschool listings."
                    )

                    st.subheader("Preschool Search Results")

                    st.dataframe(
                        df,
                        use_container_width=True,
                        hide_index=True
                    )

                    excel_file = create_excel(
                        records
                    )

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

                else:

                    st.warning(
                        "No matching preschool records were found "
                        "with this exact PIN code in OpenStreetMap."
                    )

                    st.info(
                        "This does not necessarily mean there are "
                        "no preschools in this area. The listings "
                        "may not be available in the open database."
                    )

            except Exception as error:

                st.error(
                    "Search could not be completed."
                )

                st.caption(str(error))


# =====================================================
# FOOTER
# =====================================================

st.divider()

st.caption(
    "Rewyoo Preschool Finder | India"
)

st.caption(
    "Location source: OpenStreetMap. "
    "Postal validation: Pincode API."
)
