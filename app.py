import streamlit as st

st.set_page_config(
    page_title="Rewyoo Preschool Finder",
    page_icon="🏫",
    layout="wide"
)

# Application Header
st.title("Rewyoo Preschool Finder")
st.caption("Preschool discovery and data extraction across India")

st.divider()

# Search Configuration
st.subheader("Search Configuration")

# Pincode Input
pincode = st.text_input(
    "Enter Pincode",
    placeholder="Example: 560066",
    max_chars=6
)

# Fixed Country
st.text_input(
    "Country",
    value="India",
    disabled=True
)

# Maximum Records
result_limit = st.selectbox(
    "Maximum Records",
    [5, 10, 25, 50, 100, 200, 300, 400, 500],
    index=0
)

# Preschool Categories
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

# Search Button
if st.button(
    "Start Preschool Search",
    type="primary",
    use_container_width=True
):

    # Validate Pincode
    if (
        not pincode.isdigit()
        or len(pincode) != 6
        or pincode[0] == "0"
    ):
        st.error("Please enter a valid six-digit Indian PIN code.")

    # Validate Categories
    elif not categories:
        st.error("Please select at least one preschool category.")

    else:
        st.success("Search configuration is ready.")

        st.write("**Pincode:**", pincode)
        st.write("**Country:** India")
        st.write("**Maximum Records:**", result_limit)
        st.write("**Selected Categories:**", ", ".join(categories))

st.divider()

# Footer
st.caption("Rewyoo Preschool Finder | India")
