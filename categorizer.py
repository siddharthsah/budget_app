import pandas as pd
import streamlit as st
import os
import json
import camelot
import tempfile
import re

st.set_page_config(layout="centered", page_title="Budget Categorizer")

st.title("📊 Budget Categorizer: Credit/Debit Analyzer")

# Define the file path for saving categories
CATEGORY_FILE = "categories.json"

# Load existing categories or initialize an empty dictionary
# This function handles the file loading to ensure it's done safely
def load_categories():
    if os.path.exists(CATEGORY_FILE):
        try:
            with open(CATEGORY_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            st.warning("Error reading categories.json. Starting with empty categories.")
            return {}
    return {}

# Save categories to a JSON file
# This function handles the file saving
def save_categories(categories):
    try:
        with open(CATEGORY_FILE, 'w') as f:
            json.dump(categories, f, indent=2)
    except IOError as e:
        st.error(f"Error saving categories: {e}")

# Function to process PDF files
def process_pdf(uploaded_file):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
            temp_pdf.write(uploaded_file.getvalue())
            temp_pdf_path = temp_pdf.name

        tables = camelot.read_pdf(temp_pdf_path, pages='all', flavor='stream')
        os.unlink(temp_pdf_path)  # Clean up the temporary file

        if tables:
            for table in tables:
                # Check if the table contains 'Standard Purchases'
                if any("Standard Purchases" in str(cell) for _, row in table.df.iterrows() for cell in row):
                    df = table.df
                    # The data is in a single column, so we need to parse it
                    parsed_data = []
                    for index, row in df.iterrows():
                        line = row[0]
                        # Regex to capture date, description, and amount
                        match = re.search(r'(\d{2}/\d{2})(.*?)(\$[\d,]+\.\d{2})', line)
                        if match:
                            date = match.group(1)
                            description = match.group(2).strip()
                            amount = match.group(3)
                            parsed_data.append([date, description, amount])

                    if parsed_data:
                        new_df = pd.DataFrame(parsed_data, columns=['Date', 'Description', 'Amount'])
                        return new_df

            st.error("Could not find a transaction table with 'Standard Purchases'.")
            return None
        else:
            st.error("No tables found in the PDF file.")
            return None
    except Exception as e:
        st.error(f"An error occurred during PDF processing: {e}")
        return None

# Load categories at the start of the script
saved_categories = load_categories()

# --- Main Application Flow ---

# Step 1: Upload CSV or PDF file
st.subheader("Step 1: Upload your CSV or PDF Statement")
uploaded_file = st.file_uploader("Upload your bank or credit card statement", type=["csv", "pdf"])

if uploaded_file is not None:
    try:
        file_type = uploaded_file.type
        df = None

        if file_type == "text/csv":
            df = pd.read_csv(uploaded_file)
        elif file_type == "application/pdf":
            df = process_pdf(uploaded_file)

        if df is not None:
            # Clean amount column
            for col in df.columns:
                if 'amount' in str(col).lower():
                    df[col] = df[col].astype(str).str.replace(r'[$,]', '', regex=True)
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            st.success("File uploaded successfully! Here's a preview:")
            st.dataframe(df.head())

            st.markdown("---")
            st.subheader("Step 2: Select Columns")

            # Dropdown for selecting Date, Description, and Amount columns
            try:
                date_col = st.selectbox("Select the Date Column", df.columns, index=df.columns.get_loc('Date') if 'Date' in df.columns else 0)
                desc_col = st.selectbox("Select the Description Column", df.columns, index=df.columns.get_loc('Description') if 'Description' in df.columns else (df.columns.get_loc('Transaction') if 'Transaction' in df.columns else 0))

                # Option to use single amount column or credit/debit columns
                amount_option = st.radio("How is the transaction amount provided?", ["Single amount column", "Separate credit and debit columns"])

                if amount_option == "Single amount column":
                    amount_col = st.selectbox("Select the Amount Column", df.columns, index=df.columns.get_loc('Amount') if 'Amount' in df.columns else 0)
                    df['Amount'] = pd.to_numeric(df[amount_col], errors='coerce')
                else:
                    credit_col = st.selectbox("Select the Credit Column", df.columns, index=df.columns.get_loc('Credit') if 'Credit' in df.columns else 0)
                    debit_col = st.selectbox("Select the Debit Column", df.columns, index=df.columns.get_loc('Debit') if 'Debit' in df.columns else 0)
                    
                    # Convert to numeric, coercing errors to NaN and filling NaN with 0
                    df[credit_col] = pd.to_numeric(df[credit_col], errors='coerce').fillna(0)
                    df[debit_col] = pd.to_numeric(df[debit_col], errors='coerce').fillna(0)
                    
                    # Calculate net amount: Credit - Debit
                    df['Amount'] = df[credit_col] - df[debit_col]

                # Convert date column to datetime objects
                df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                df = df.dropna(subset=[date_col]) # Drop rows where date conversion failed
                
                # Extract month for grouping
                df['Month'] = df[date_col].dt.to_period('M')

                st.markdown("---")
                st.subheader("Step 3: Categorize Each Transaction")

                # Get unique categories from saved_categories for the dropdown
                all_known_categories = sorted(list(set(saved_categories.values())))
                # Add a default option and an "Add New" option
                category_options_for_dropdown = ["Select Category", "--- Add New Category ---"] + all_known_categories

                category_list = [] # To store the final category for each row

                for i, row in df.iterrows():
                    desc = str(row[desc_col]).strip().lower()
                    auto_category = saved_categories.get(desc, "")

                    # Determine the initial selection for the dropdown
                    initial_selection_index = 0 # Default to "Select Category"
                    if auto_category in category_options_for_dropdown:
                        initial_selection_index = category_options_for_dropdown.index(auto_category)
                    elif auto_category: # If auto_category exists but not in current dropdown options
                        # This handles cases where a category was just added via the manage section
                        # or manually, and the app hasn't rerun yet.
                        # We'll temporarily add it to this specific selectbox's options.
                        temp_options = category_options_for_dropdown + [auto_category]
                        temp_options = sorted(list(set(temp_options))) # Ensure unique and sorted
                        initial_selection_index = temp_options.index(auto_category)
                        category_options_for_dropdown = temp_options # Use this updated list for the current selectbox
                    
                    st.write(f"**Transaction:** {row[date_col].date()} | {row[desc_col]} | **${row['Amount']:.2f}**")
                    
                    selected_category = st.selectbox(
                        "Assign Category:",
                        options=category_options_for_dropdown,
                        index=initial_selection_index,
                        key=f"cat_select_{i}"
                    )

                    final_category_for_row = selected_category

                    if selected_category == "--- Add New Category ---":
                        new_manual_category = st.text_input("Enter new category for this transaction:", key=f"new_manual_cat_input_{i}").strip()
                        if new_manual_category:
                            final_category_for_row = new_manual_category
                            # Update saved_categories for persistence
                            if saved_categories.get(desc) != final_category_for_row:
                                saved_categories[desc] = final_category_for_row
                                save_categories(saved_categories) # Save to file immediately
                        else:
                            final_category_for_row = "" # If user selected "Add New" but typed nothing
                    elif selected_category == "Select Category":
                        final_category_for_row = "" # Treat as unassigned

                    category_list.append(final_category_for_row)

                # Assign the collected categories back to the DataFrame
                df['Category'] = category_list
                st.success("Transactions categorized!")

                st.markdown("---")
                st.subheader("Step 4: Analyze Credit/Debit by Month")

                # Determine transaction type (Credit or Debit) based on amount
                df['Type'] = df['Amount'].apply(lambda x: 'Credit' if x > 0 else 'Debit')

                # Group by Month and Type to get summary of amounts
                summary = df.groupby(['Month', 'Type'])[['Amount']].sum().unstack(fill_value=0)
                
                # Clean up column names after unstacking
                summary.columns = summary.columns.droplevel()
                summary = summary.rename(columns={
                    'Credit': 'Total Credit',
                    'Debit': 'Total Debit'
                })

                st.write("### Monthly Summary")
                st.dataframe(summary)

                st.markdown("---")
                st.write("### Categorized Transactions")
                # Display the full categorized DataFrame
                st.dataframe(df[[date_col, desc_col, 'Amount', 'Type', 'Category']])

                # Provide a download button for the categorized CSV
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Categorized CSV",
                    data=csv,
                    file_name='categorized_transactions.csv',
                    mime='text/csv'
                )
            except KeyError as e:
                st.error(f"Error: Selected column not found in the file. Please check your column selections. Missing column: {e}")
            except Exception as e:
                st.error(f"An unexpected error occurred during column processing or categorization: {e}")

    except Exception as e:
        st.error(f"Error reading the file. Please ensure it's a valid file and try again. Details: {e}")
else:
    st.info("Please upload a CSV or PDF file to begin.")

# --- Dedicated UI for Category Management ---
st.markdown("---")
st.header("⚙️ Manage Categories")
st.write("Here you can view, add, edit, or delete your saved category mappings.")

# Convert saved_categories dictionary to a DataFrame for display
if saved_categories:
    categories_df = pd.DataFrame(saved_categories.items(), columns=['Description', 'Category'])
    st.dataframe(categories_df, use_container_width=True)
else:
    st.info("No categories saved yet. Start categorizing transactions or add them below.")

# Add New Category Mapping
st.subheader("Add New Category Mapping")
with st.form("add_category_form"):
    new_desc = st.text_input("Transaction Description (e.g., 'starbucks')", key="new_desc").strip().lower()
    new_cat = st.text_input("Category Name (e.g., 'Coffee')", key="new_cat").strip()
    add_button = st.form_submit_button("Add Mapping")

    if add_button:
        if new_desc and new_cat:
            if new_desc in saved_categories and saved_categories[new_desc] == new_cat:
                st.warning(f"Mapping for '{new_desc}' to '{new_cat}' already exists.")
            else:
                saved_categories[new_desc] = new_cat
                save_categories(saved_categories)
                st.success(f"Added mapping: '{new_desc}' -> '{new_cat}'")
                st.rerun() # Rerun to update the displayed categories
        else:
            st.warning("Please enter both a description and a category.")

st.markdown("---")

# Edit/Delete Category Mapping
st.subheader("Edit or Delete Category Mapping")
if saved_.categories:
    descriptions = sorted(list(saved_categories.keys()))
    selected_desc = st.selectbox("Select Description to Edit/Delete", descriptions, key="select_desc")
    
    if selected_desc:
        current_category = saved_categories.get(selected_desc, "")
        edited_category = st.text_input("Edit Category", value=current_category, key="edited_cat")

        col1, col2 = st.columns(2)
        with col1:
            update_button = st.button("Update Category")
        with col2:
            delete_button = st.button("Delete Mapping")

        if update_button:
            if edited_category.strip():
                saved_categories[selected_desc] = edited_category.strip()
                save_categories(saved_categories)
                st.success(f"Updated mapping: '{selected_desc}' -> '{edited_category}'")
                st.rerun() # Rerun to update the displayed categories
            else:
                st.warning("Category cannot be empty. Please enter a category or delete the mapping.")
        
        if delete_button:
            if selected_desc in saved_categories:
                del saved_categories[selected_desc]
                save_categories(saved_categories)
                st.success(f"Deleted mapping for: '{selected_desc}'")
                st.rerun() # Rerun to update the displayed categories
else:
    st.info("No categories to edit or delete yet.")
