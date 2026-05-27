import pandas as pd

def read_file():
    try:
        df = pd.read_csv("Student Details.csv")  # 👈 changed here
        df.columns = df.columns.str.strip()
        return df
    except FileNotFoundError:
        print("ERROR: CSV file not found")
        return None


def process_data(df):
    if df is None or df.empty:   # 👈 small safe fix
        print("ERROR: CSV file is empty")
        return

    expected_columns = ["Name", "Department", "Blood Group", "Native"]
    changed_columns = [col for col in expected_columns if col not in df.columns]

    if changed_columns:
        for col in changed_columns:
            print(f"{col} column changed or deleted in CSV sheet")
        return

    for index, row in df.iterrows():
        missing = []
        for field in expected_columns:
            try:
                if pd.isna(row[field]) or str(row[field]).strip() == "":
                    missing.append(field)
            except Exception:
                missing.append(field)

        if missing:
            name = row["Name"]

            if pd.isna(name) or str(name).strip() == "":
                identifier = f"Row {index + 2}"
            else:
                identifier = str(name).strip()

            print(f"{identifier} -> Missing: {', '.join(missing)}")


def main():
    df = read_file()
    if df is not None:
        process_data(df)


if __name__ == "__main__":
    main()