import pandas as pd

def normalize_input(data, input_type="file"):
    if input_type == "file":
        if data.filename.endswith(".csv"):
            df = pd.read_csv(data.file)
        elif data.filename.endswith((".xls", ".xlsx")):
            df = pd.read_excel(data.file)
        else:
            raise ValueError("Unsupported file format")
    elif input_type == "json":
        df = pd.DataFrame(data)  # already structured list of dicts
    else:
        raise ValueError("Unsupported input type")

    df = df.dropna(how="all")
    df.columns = df.columns.str.strip()
    return df
