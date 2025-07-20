import pandas as pd
import streamlit as st
import os
import json

st.title("📊 Budget Categorizer: Credit/Debit Analyzer")

CATEGORY_FILE = "categories.json"

# Load existing categories
if os.path.exists(CATEGORY_FILE):
    with open(CATEGORY_FILE, 'r') as f:
        saved_categories = json.load(f)
else:
    saved_categories = {}

# Step 1: Upload CSV file
uploaded_file = st.file_uploader("Upload your bank or credit card CSV statement", type=["csv"])

if uploaded_file is not None:
    df = pd.read_csv(uploaded_file)

    st.subheader("Step 1: Preview of Transactions")
    st.write(df.head())

    st.markdown("---")
    st.subheader("Step 2: Select Columns")

    date_col = st.selectbox("Select the Date Column", df.columns)
    desc_col = st.selectbox("Select the Description Column", df.columns)

    # Option to use single amount column or credit/debit columns
    amount_option = st.radio("How is the transaction amount provided?", ["Single amount column", "Separate credit and debit columns"])

    if amount_option == "Single amount column":
        amount_col = st.selectbox("Select the Amount Column", df.columns)
        df['Amount'] = df[amount_col]
    else:
        credit_col = st.selectbox("Select the Credit Column", df.columns)
        debit_col = st.selectbox("Select the Debit Column", df.columns)
        df[credit_col] = pd.to_numeric(df[credit_col], errors='coerce').fillna(0)
        df[debit_col] = pd.to_numeric(df[debit_col], errors='coerce').fillna(0)
        df['Amount'] = df[credit_col] - df[debit_col]  # Net amount

    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
    df = df.dropna(subset=[date_col])
    df['Month'] = df[date_col].dt.to_period('M')

    st.markdown("---")
    st.subheader("Step 3: Categorize Each Transaction")

    category_list = []
    for i, row in df.iterrows():
        desc = str(row[desc_col]).strip().lower()

        # Auto-categorize if exists
        auto_category = saved_categories.get(desc, "")
        user_input = st.text_input(f"{row[date_col].date()} | {row[desc_col]} | ${row['Amount']:.2f}", value=auto_category, key=f"cat_{i}")
        
        # Save category if new and not blank
        if user_input.strip() and desc not in saved_categories:
            saved_categories[desc] = user_input.strip()

        category_list.append(user_input.strip())

    df['Category'] = category_list

    # Save updated categories to file
    with open(CATEGORY_FILE, 'w') as f:
        json.dump(saved_categories, f, indent=2)

    st.markdown("---")
    st.subheader("Step 4: Analyze Credit/Debit by Month")

    df['Type'] = df['Amount'].apply(lambda x: 'Credit' if x > 0 else 'Debit')

    summary = df.groupby(['Month', 'Type'])[['Amount']].sum().unstack(fill_value=0)
    summary.columns = summary.columns.droplevel()
    summary = summary.rename(columns={
        'Credit': 'Total Credit',
        'Debit': 'Total Debit'
    })

    st.write("### Monthly Summary")
    st.dataframe(summary)

    st.markdown("---")
    st.write("### Categorized Transactions")
    st.dataframe(df[[date_col, desc_col, 'Amount', 'Type', 'Category']])

    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Download Categorized CSV",
        data=csv,
        file_name='categorized_transactions.csv',
        mime='text/csv'
    )
