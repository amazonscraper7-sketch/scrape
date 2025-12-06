import pandas as pd

input_file = "/Users/adityakumar/Library/Mobile Documents/com~apple~CloudDocs/WEB/chat/products_export2.csv"
output_file = "products_export3.csv"

df = pd.read_csv(input_file)

# Drop rows from index 0 to 82155 (82156 rows)
df = df.drop(df.index[:142702])

df.to_csv(output_file, index=False)
print("Rows deleted successfully!")
