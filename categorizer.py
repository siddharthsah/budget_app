import pandas as pd
import streamlit as st
import os
import json
import camelot
import tempfile
import re
import altair as alt
import io

st.set_page_config(layout="centered", page_title="Budget Categorizer")

st.title("📊 Budget Categorizer: Credit/Debit Analyzer")

# --- File Paths ---
CATEGORY_FILE = "categories.json"
PDF_MAPPING_FILE = "pdf_mappings.json"

# --- Helper Functions ---

def load_json(file_path, default_value):
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            st.warning(f"Error reading {file_path}. Starting with empty data.")
            return default_value
    return default_value

def save_json(data, file_path):
    try:
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        st.error(f"Error saving to {file_path}: {e}")

def get_pdf_text(file_path):
    """Extracts text from the first page of a PDF."""
    try:
        tables = camelot.read_pdf(file_path, pages='1')
        if tables:
            return tables[0].df.to_string()
    except Exception:
        return ""
    return ""

def find_matching_mapping(text, mappings):
    """Finds a matching mapping based on keywords."""
    for name, mapping in mappings.items():
        if all(keyword.lower() in text.lower() for keyword in mapping.get("keywords", [])):
            return name, mapping
    return None, None

def process_pdf_with_mapping(tables, mapping):
    """Processes a list of tables using a saved mapping."""
    try:
        table_index = mapping.get("table_index", 0)
        if table_index < len(tables):
            df = tables[table_index].df
            
            # Find the start row
            start_row = 0
            if "start_row_keyword" in mapping:
                for i, row in df.iterrows():
                    if mapping["start_row_keyword"] in row.to_string():
                        start_row = i + 1
                        break
            
            df = df.iloc[start_row:]
            
            # Parse data using regex if specified
            if "regex" in mapping:
                parsed_data = []
                for _, row in df.iterrows():
                    line = " ".join(row.astype(str).tolist())
                    match = re.search(mapping["regex"], line)
                    if match:
                        parsed_data.append(match.groups())
                
                if parsed_data:
                    new_df = pd.DataFrame(parsed_data, columns=mapping["regex_columns"])
                    return new_df
            else:
                # Rename columns if no regex
                df = df.rename(columns=mapping["column_mapping"])
                return df
        else:
            st.error(f"Table index {table_index} is out of bounds.")
            return None

    except Exception as e:
        st.error(f"Error applying the saved mapping: {e}")
        return None

def create_dashboard(df):
    st.subheader("Budgeting Dashboard")

    # Date Range Filter
    st.sidebar.header("Filter by Date")
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df = df.dropna(subset=['Date'])

    if df.empty:
        st.warning("No valid dates found in the data. Cannot generate dashboard.")
        return

    min_date = df['Date'].min().date()
    max_date = df['Date'].max().date()
    start_date = st.sidebar.date_input("Start date", min_date, min_value=min_date, max_value=max_date)
    end_date = st.sidebar.date_input("End date", max_date, min_value=min_date, max_value=max_date)

    # Filter DataFrame by date range
    filtered_df = df[(df['Date'].dt.date >= start_date) & (df['Date'].dt.date <= end_date)]

    # Income vs. Expenses
    expenses = filtered_df[filtered_df['Amount'] < 0]['Amount'].sum()
    income = filtered_df[filtered_df['Amount'] > 0]['Amount'].sum()

    st.metric("Total Expenses", f"${abs(expenses):,.2f}")
    st.metric("Total Income", f"${income:,.2f}")

    # Spending by Category
    category_spending = filtered_df[filtered_df['Amount'] < 0].groupby('Category')['Amount'].sum().abs().reset_index()
    
    chart = alt.Chart(category_spending).mark_bar().encode(
        x=alt.X('Category', sort=None),
        y='Amount',
        tooltip=['Category', 'Amount']
    ).properties(
        title="Spending by Category"
    )
    st.altair_chart(chart, use_container_width=True)

    # Export to Excel
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Budget')
    
    st.download_button(
        label="Export to Excel",
        data=output.getvalue(),
        file_name="budget.xlsx",
        mime="application/vnd.ms-excel"
    )


# --- Main Application ---

# Load data at the start
saved_categories = load_json(CATEGORY_FILE, {})
pdf_mappings = load_json(PDF_MAPPING_FILE, {})

# Initialize session state
if 'step' not in st.session_state:
    st.session_state.step = 1
if 'df' not in st.session_state:
    st.session_state.df = None

# --- Main Application Flow ---

st.subheader("Step 1: Upload your Statement")
uploaded_file = st.file_uploader("Upload your bank or credit card statement", type=["csv", "pdf"])

if uploaded_file is not None:
    file_type = uploaded_file.type

    if file_type == "text/csv":
        with st.spinner('Reading CSV...'):
            st.session_state.df = pd.read_csv(uploaded_file)
            st.session_state.step = 3.5 # Skip to editing
    elif file_type == "application/pdf":
        with st.spinner('Reading PDF...'):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
                temp_pdf.write(uploaded_file.getvalue())
                temp_pdf_path = temp_pdf.name

            pdf_text = get_pdf_text(temp_pdf_path)
            mapping_name, mapping = find_matching_mapping(pdf_text, pdf_mappings)

            if mapping and not st.session_state.get("force_new_mapping", False):
                st.success(f"Found matching mapping: '{mapping_name}'")
                tables = camelot.read_pdf(temp_pdf_path, pages='all', flavor='stream')
                st.session_state.df = process_pdf_with_mapping(tables, mapping)
                st.session_state.step = 3.5 # Skip to editing
            else:
                if st.session_state.step == 1:
                    try:
                        st.session_state.camelot_tables = camelot.read_pdf(temp_pdf_path, pages='all', flavor='stream')
                    finally:
                        os.unlink(temp_pdf_path)

                    if st.session_state.camelot_tables:
                        st.subheader("Step 2: Select Transaction Table(s)")
                        st.info("Select the table(s) that contain your transaction data. You can select multiple tables.")
                        selected_indices = []
                        for i, table in enumerate(st.session_state.camelot_tables):
                            st.write(f"--- Table {i+1} ---")
                            st.dataframe(table.df)
                            if st.checkbox(f"Use this table", key=f"table_{i}"):
                                selected_indices.append(i)
                        
                        if st.button("Continue with selected table(s)"):
                            if selected_indices:
                                st.session_state.selected_tables_indices = selected_indices
                                st.session_state.tables = [st.session_state.camelot_tables[i].df for i in selected_indices]
                                st.session_state.merged_df = pd.concat(st.session_state.tables, ignore_index=True)
                                st.session_state.step = 2
                                st.rerun()
                            else:
                                st.warning("Please select at least one table.")
                    else:
                        st.error("No tables found in the PDF file. Try using a different PDF or check the file for corruption.")

    if st.session_state.step == 2:
        st.subheader("Step 3: Map Columns")
        st.info("Map the columns from your statement to the standard columns: Date, Description, and Amount.")
        st.write("Merged Table:")
        st.dataframe(st.session_state.merged_df)

        use_regex = st.checkbox("Use Regex for advanced parsing")

        if use_regex:
            st.info("Use regular expressions to capture specific parts of your transaction data. This is useful for complex statements where data is not in neat columns.")
            regex_pattern = st.text_area("Regex Pattern")
            regex_columns = st.text_input("Column Names (comma-separated)")
            if st.button("Test Regex"):
                try:
                    parsed_data = []
                    for _, row in st.session_state.merged_df.iterrows():
                        line = " ".join(row.astype(str).tolist())
                        match = re.search(regex_pattern, line)
                        if match:
                            parsed_data.append(match.groups())
                    
                    if parsed_data:
                        st.write("Regex Test Results:")
                        st.dataframe(pd.DataFrame(parsed_data, columns=regex_columns.split(",")))
                    else:
                        st.warning("Regex did not match any rows.")
                except Exception as e:
                    st.error(f"Error testing regex: {e}")
        else:
            column_mapping = {}
            cols = st.session_state.merged_df.columns.tolist()
            
            date_col = st.selectbox("Select the Date Column", cols)
            desc_col = st.selectbox("Select the Description Column", cols)
            amount_col = st.selectbox("Select the Amount Column", cols)
        
        mapping_name = st.text_input("Enter a name for this mapping (e.g., 'Citi Credit Card')")
        keywords = st.text_input("Enter keywords to identify this PDF format (comma-separated)")

        if st.button("Save Mapping and Process"):
            if mapping_name and keywords:
                if use_regex:
                    pdf_mappings[mapping_name] = {
                        "keywords": [k.strip() for k in keywords.split(",")],
                        "table_index": st.session_state.selected_tables_indices[0],
                        "regex": regex_pattern,
                        "regex_columns": [c.strip() for c in regex_columns.split(",")]
                    }
                else:
                    column_mapping = {date_col: 'Date', desc_col: 'Description', amount_col: 'Amount'}
                    pdf_mappings[mapping_name] = {
                        "keywords": [k.strip() for k in keywords.split(",")],
                        "table_index": st.session_state.selected_tables_indices[0],
                        "column_mapping": column_mapping
                    }
                save_json(pdf_mappings, PDF_MAPPING_FILE)
                st.success(f"Mapping '{mapping_name}' saved!")
                
                with st.spinner('Processing PDF with new mapping...'):
                    st.session_state.df = process_pdf_with_mapping(st.session_state.camelot_tables, pdf_mappings[mapping_name])
                    st.session_state.step = 3.5
            else:
                st.warning("Please enter a name and keywords for the mapping.")

    if st.session_state.step == 3.5:
        st.subheader("Step 3.5: Edit Data")
        st.info("You can now edit your data before proceeding to categorization. Check the 'Delete' box for rows you want to remove.")
        st.session_state.df['Delete'] = False
        edited_df = st.data_editor(st.session_state.df)

        if st.button("Delete Selected Rows"):
            st.session_state.df = edited_df[edited_df['Delete'] == False]
            st.session_state.df = st.session_state.df.drop(columns=['Delete'])
            st.rerun()

        if st.button("Confirm Changes"):
            st.session_state.df = edited_df.drop(columns=['Delete'])
            st.session_state.step = 4
            st.rerun()

    if st.session_state.df is not None and st.session_state.step == 4:
        # --- This part of the code runs after a DataFrame has been successfully loaded ---
        st.subheader("Step 4: Categorize Transactions")
        st.info("Review and categorize each transaction. The app will remember your choices for future uploads.")
        
        # Clean amount column
        if 'Amount' in st.session_state.df.columns:
            st.session_state.df['Amount'] = st.session_state.df['Amount'].astype(str).str.replace(r'[$,]', '', regex=True)
            st.session_state.df['Amount'] = pd.to_numeric(st.session_state.df['Amount'], errors='coerce')

        st.success("Data loaded successfully! Here's a preview:")
        st.dataframe(st.session_state.df.head())

        # --- Categorization Logic ---
        st.subheader("Step 5: Categorize Transactions")

        # Get unique categories
        categories = list(saved_categories.keys())
        if "Uncategorized" not in categories:
            categories.insert(0, "Uncategorized")

        # Add a new category
        with st.expander("Add a new category"):
            new_category = st.text_input("New Category Name")
            if st.button("Add Category") and new_category:
                if new_category not in categories:
                    categories.append(new_category)
                    saved_categories[new_category] = []
                    save_json(saved_categories, CATEGORY_FILE)
                    st.success(f"Category '{new_category}' added.")
                else:
                    st.warning(f"Category '{new_category}' already exists.")

        # Display transactions and categorize
        if 'Category' not in st.session_state.df.columns:
            st.session_state.df['Category'] = 'Uncategorized'

        progress_bar = st.progress(0)
        counter = 0
        for i, row in st.session_state.df.iterrows():
            with st.expander(f"**{row['Description']}** - ${row['Amount']}"):
                # Check for existing category memory
                for category, keywords in saved_categories.items():
                    if any(keyword.lower() in str(row['Description']).lower() for keyword in keywords):
                        st.session_state.df.at[i, 'Category'] = category
                        break

                # Category selector
                selected_category = st.selectbox(
                    "Category",
                    categories,
                    index=categories.index(st.session_state.df.at[i, 'Category']),
                    key=f"category_{i}"
                )
                st.session_state.df.at[i, 'Category'] = selected_category

                # Add to category memory
                if selected_category != "Uncategorized":
                    if row['Description'] not in saved_categories[selected_category]:
                        saved_categories[selected_category].append(row['Description'])
            counter += 1
            progress_bar.progress(counter / len(st.session_state.df))

        if st.button("Save Categories & Generate Dashboard"):
            save_json(saved_categories, CATEGORY_FILE)
            st.success("Categories saved!")
            st.dataframe(st.session_state.df)
            create_dashboard(st.session_state.df)

if st.button("Create new PDF mapping"):
    st.session_state.step = 1
    st.session_state.force_new_mapping = True
    st.rerun()

