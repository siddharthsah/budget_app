import pandas as pd
import streamlit as st
import os
import json
import camelot
import tempfile
import re

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

def process_pdf_with_mapping(df, mapping):
    """Processes a DataFrame using a saved mapping."""
    try:
        # This is a simplified version. A more robust implementation would be needed.
        # For example, to handle multi-table mappings or more complex transformations.
        df = df.rename(columns=mapping["column_mapping"])
        return df
    except Exception as e:
        st.error(f"Error applying the saved mapping: {e}")
        return None

# --- Main Application ---

# Load data at the start
saved_categories = load_json(CATEGORY_FILE, {})
pdf_mappings = load_json(PDF_MAPPING_FILE, {})

# Initialize session state
if 'step' not in st.session_state:
    st.session_state.step = 1
if 'selected_tables' not in st.session_state:
    st.session_state.selected_tables = []
if 'merged_df' not in st.session_state:
    st.session_state.merged_df = None

# --- Main Application Flow ---

st.subheader("Step 1: Upload your Statement")
uploaded_file = st.file_uploader("Upload your bank or credit card statement", type=["csv", "pdf"])

if uploaded_file is not None:
    df = None
    file_type = uploaded_file.type

    if file_type == "text/csv":
        df = pd.read_csv(uploaded_file)
        st.session_state.step = 4 # Skip to categorization
    elif file_type == "application/pdf":
        if st.session_state.step == 1:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
                temp_pdf.write(uploaded_file.getvalue())
                temp_pdf_path = temp_pdf.name
            try:
                tables = camelot.read_pdf(temp_pdf_path, pages='all', flavor='stream')
            finally:
                os.unlink(temp_pdf_path)

            if tables:
                st.subheader("Step 2: Select Transaction Table(s)")
                selected_indices = []
                for i, table in enumerate(tables):
                    st.write(f"--- Table {i+1} ---")
                    st.dataframe(table.df)
                    if st.checkbox(f"Use this table", key=f"table_{i}"):
                        selected_indices.append(i)
                
                if st.button("Continue with selected table(s)"):
                    if selected_indices:
                        st.session_state.selected_tables = [tables[i].df for i in selected_indices]
                        st.session_state.merged_df = pd.concat(st.session_state.selected_tables, ignore_index=True)
                        st.session_state.step = 2
                        st.rerun()
                    else:
                        st.warning("Please select at least one table.")
            else:
                st.error("No tables found in the PDF file.")

    if st.session_state.step == 2:
        st.subheader("Step 3: Map Columns")
        st.write("Merged Table:")
        st.dataframe(st.session_state.merged_df)

        column_mapping = {}
        cols = st.session_state.merged_df.columns.tolist()
        
        column_mapping[st.selectbox("Select the Date Column", cols)] = 'Date'
        column_mapping[st.selectbox("Select the Description Column", cols)] = 'Description'
        column_mapping[st.selectbox("Select the Amount Column", cols)] = 'Amount'
        
        mapping_name = st.text_input("Enter a name for this mapping (e.g., 'Citi Credit Card')")

        if st.button("Save Mapping and Process"):
            if mapping_name:
                # Invert the mapping for processing
                inverted_mapping = {v: k for k, v in column_mapping.items()}
                pdf_mappings[mapping_name] = {
                    "column_mapping": inverted_mapping
                }
                save_json(pdf_mappings, PDF_MAPPING_FILE)
                st.success(f"Mapping '{mapping_name}' saved!")
                
                # Process the dataframe with the new mapping
                df = process_pdf_with_mapping(st.session_state.merged_df, pdf_mappings[mapping_name])
                st.session_state.step = 4
            else:
                st.warning("Please enter a name for the mapping.")

    if df is not None and st.session_state.step == 4:
        # --- This part of the code runs after a DataFrame has been successfully loaded ---
        st.subheader("Step 4: Categorize Transactions")
        
        # Clean amount column
        for col in df.columns:
            if 'amount' in str(col).lower():
                df[col] = df[col].astype(str).str.replace(r'[$,]', '', regex=True)
                df[col] = pd.to_numeric(df[col], errors='coerce')

        st.success("Data loaded successfully! Here's a preview:")
        st.dataframe(df.head())

        # The rest of the categorization logic will go here
        # For now, we just show the loaded data
else:
    st.info("Please upload a file to begin.")

# --- Category Management UI (for later) ---
# ...