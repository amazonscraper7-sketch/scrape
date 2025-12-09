import requests
from bs4 import BeautifulSoup
import json
import pandas as pd
import csv
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

API_KEY = "692da13802188135941fe805"

def get_asins_from_file(file_path):
    print(f"Reading ASINs from {file_path}...")
    try:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".csv":
            df = pd.read_csv(file_path, header=None)
        else:
            df = pd.read_excel(file_path, header=None)
        # Flatten all columns into a single list
        all_asins = df.values.flatten()
        # Filter out NaNs and empty strings, convert to string
        clean_asins = [str(a).strip() for a in all_asins if pd.notna(a) and str(a).strip() != ""]
        unique_asins = sorted(list(set(clean_asins)))
        print(f"Found {len(unique_asins)} unique ASINs.")
        return unique_asins
    except Exception as e:
        print(f"Error reading file: {e}")
        return []

import sys

# Read ASINs from the Excel file
# Use command line argument if provided, else default
excel_file = sys.argv[1] if len(sys.argv) > 1 else "asins_b0_500percol.xlsx"
product_category_arg = sys.argv[2] if len(sys.argv) > 2 else "Health & Supplements"
product_type_arg = sys.argv[3] if len(sys.argv) > 3 else "Dietary Supplement"
price_formula_arg = sys.argv[4] if len(sys.argv) > 4 else "x"

asins = get_asins_from_file(excel_file)

# Limit removed for production use
# Limit removed for production use
# asins = asins[:18]

def extract_images(soup):
    images = set()

    # 1. Main product image
    landing = soup.find("img", {"id": "landingImage"})
    if landing and landing.get("data-a-dynamic-image"):
        try:
            d = json.loads(landing["data-a-dynamic-image"])
            for url in d.keys():
                url = url.split("._")[0] + ".jpg"
                images.add(url)
        except:
            pass

    # 2. Product gallery thumbnails (REAL PRODUCT ONLY)
    for img in soup.select("#altImages .a-button-thumbnail img"):
        attrs = ["src", "data-src", "data-thumb", "data-zoom-image", "data-a-image-name", "data-a-dynamic-image"]
        for attr in attrs:
            url = img.get(attr)
            if not url:
                continue
            if "https" not in url:
                continue

            # Skip recommended product images using filter:
            # If the URL does NOT contain the same image base as landingImage, skip it.
            base = landing.get("src", "").split("._")[0]
            if base and base[:20] not in url:  # Weak but works
                continue

            # Remove resize variations
            url = url.split("._")[0] + ".jpg"
            images.add(url)

    return list(images)

def clean_price(price_str):
    if not price_str: return ""
    # Keep only digits and dots
    return re.sub(r"[^\d.]", "", price_str)

def apply_price_formula(price_str, formula):
    if not price_str or not formula or formula.strip() == "x":
        return price_str
    
    try:
        x = float(price_str)
        # Normalize common shorthand like '2x' -> '2*x' and 'x2' -> 'x*2'
        norm = formula.strip()
        norm = re.sub(r"(?<![A-Za-z_])(\d+(?:\.\d+)?)\s*x", r"\1*x", norm)
        norm = re.sub(r"x\s*(\d+(?:\.\d+)?)", r"x*\1", norm)
        # Safe evaluation
        allowed_names = {"x": x, "abs": abs, "round": round, "min": min, "max": max}
        new_price = eval(norm, {"__builtins__": None}, allowed_names)
        return f"{new_price:.2f}"
    except Exception as e:
        print(f"Error applying formula '{formula}' to price '{price_str}': {e}")
        return price_str

def create_body_html(item):
    # Combine description, bullets, and tech details into a simple HTML block
    html_parts = []
    
    if item.get("full_description"):
        html_parts.append(f"<p>{item['full_description']}</p>")
        
    if item.get("description_bullets"):
        html_parts.append("<ul>")
        for bullet in item["description_bullets"]:
            html_parts.append(f"<li>{bullet}</li>")
        html_parts.append("</ul>")
        
    if item.get("technical_details"):
        html_parts.append("<h3>Technical Details</h3><ul>")
        for k, v in item["technical_details"].items():
            html_parts.append(f"<li><strong>{k}:</strong> {v}</li>")
        html_parts.append("</ul>")
        
    return "".join(html_parts)

csv_file = "products_export.csv"
csv_columns = [
    "Handle", "Title", "Body (HTML)", "Vendor", "Type", "Tags", "Published", "Option1 Name", "Option1 Value",
    "Option2 Name", "Option2 Value", "Option3 Name", "Option3 Value", "Variant SKU", "Variant Grams",
    "Variant Inventory Tracker", "Variant Inventory Qty", "Variant Inventory Policy", "Variant Fulfillment Service",
    "Variant Price", "Variant Compare At Price", "Variant Requires Shipping", "Variant Taxable", "Variant Barcode",
    "Image Src", "Image Position", "Image Alt Text", "Gift Card", "SEO Title", "SEO Description",
    "Google Shopping / Google Product Category", "Google Shopping / Gender", "Google Shopping / Age Group",
    "Google Shopping / MPN", "Google Shopping / AdWords Grouping", "Google Shopping / AdWords Labels",
    "Google Shopping / Condition", "Google Shopping / Custom Product", "Google Shopping / Custom Label 0",
    "Google Shopping / Custom Label 1", "Google Shopping / Custom Label 2", "Google Shopping / Custom Label 3",
    "Google Shopping / Custom Label 4", "Variant Image", "Variant Weight Unit", "Tax 1 Name", "Tax 1 Type",
    "Tax 1 Value", "Tax 2 Name", "Tax 2 Type", "Tax 2 Value", "Tax 3 Name", "Tax 3 Type", "Tax 3 Value",
    "Cost per item", "Product Category", "Cost Price"
]

CHECKPOINT_FILE = "fetched_asins.txt"
CONCURRENCY = int(os.getenv("SCRAPER_CONCURRENCY", "5"))

def scrape_asin(asin):
    url = f"https://www.amazon.com/dp/{asin}"
    api = f"https://api.scrapingdog.com/scrape?api_key={API_KEY}&url={url}&dynamic=true"

    html = requests.get(api).text
    soup = BeautifulSoup(html, "html.parser")

    def txt(sel):
        tag = soup.select_one(sel)
        return tag.get_text(strip=True) if tag else None

    # description bullets
    bullets = [
        li.get_text(strip=True)
        for li in soup.select("#feature-bullets ul li")
    ]

    # full description (if exists)
    description = txt("#productDescription")

    # technical details
    tech_details = {}
    for row in soup.select("#productDetails_techSpec_section_1 tr"):
        key = row.select_one("th")
        val = row.select_one("td")
        if key and val:
            tech_details[key.get_text(strip=True)] = val.get_text(strip=True)

    # Try multiple price selectors
    def get_price(soup, html):
        price_selectors = [
            ".apexPriceToPay .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-offscreen",
            "#corePrice_feature_div .a-offscreen",
            "#priceblock_ourprice",
            "#priceblock_dealprice",
            "#priceblock_saleprice",
            "#price_inside_buybox",
            ".a-price .a-offscreen",
            ".reinventPricePriceToPayMargin .a-offscreen",
            "span[data-a-color='base'] .a-offscreen",
            "#newBuyBoxPrice"
        ]
        
        for sel in price_selectors:
            tag = soup.select_one(sel)
            if tag:
                price_text = tag.get_text(strip=True)
                if price_text and any(c.isdigit() for c in price_text):
                    return price_text

        # Fallback: Extract price from JSON using regex (hidden pricing)
        match = re.search(r'"priceAmount"\s*:\s*"(\d+\.\d+)"', html)
        if match:
            return match.group(1)

        return None

    price = get_price(soup, html)
            
    # Check availability
    if not price and "Currently unavailable" in html:
        print(f"WARNING: Product {asin} is currently unavailable.")

    # Manufacturer / Brand Extraction
    manufacturer = txt("tr.po-manufacturer .po-break-word")
    if not manufacturer:
        manufacturer = txt("tr.po-brand .po-break-word")
    
    if not manufacturer:
        keywords = ["Manufacturer", "Brand", "Manufactured by"]
        for li in soup.select("ul.detail-bullet-list li"):
            text = li.get_text()
            for kw in keywords:
                if kw in text:
                     manufacturer = li.select("span")[-1].get_text(strip=True)
                     break
            if manufacturer: break

    return {
        "asin": asin,
        "title": txt("#productTitle"),
        "price": price,
        "rating": txt("span.a-icon-alt"),
        "description_bullets": bullets,
        "full_description": description,
        "main_image": extract_images(soup)[0] if extract_images(soup) else None,
        "all_images": extract_images(soup),
        "technical_details": tech_details,
        "manufacturer": manufacturer
    }

# Load fetched ASINs into a set for robust checking
fetched_asins = set()
if os.path.exists(CHECKPOINT_FILE):
    with open(CHECKPOINT_FILE, "r") as f:
        fetched_asins = set(line.strip() for line in f if line.strip())
print(f"Loaded {len(fetched_asins)} already fetched ASINs.")

# Initialize CSV file (write header if new)
file_exists = os.path.exists(csv_file)
with open(csv_file, mode='a', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=csv_columns)
    # Write header if file is new or empty
    if not file_exists or os.stat(csv_file).st_size == 0:
        writer.writeheader()

    # Build target list excluding already fetched ASINs
    targets = [a for a in asins if a and a not in fetched_asins]
    total = len(targets)
    print(f"Starting scrape with concurrency={CONCURRENCY} for {total} products...")

    processed = 0
    # Run network-bound scraping concurrently; write results in main thread
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = {executor.submit(scrape_asin, asin): asin for asin in targets}

        for future in as_completed(futures):
            asin = futures[future]
            processed += 1
            try:
                data = future.result()
            except Exception as e:
                print(f"Error scraping {asin}: {e}")
                data = None

            if data:
                # Prepare data for CSV
                handle = data["asin"]
                title = data["title"]
                body_html = create_body_html(data)
                # Use Manufacturer if available, else fallback to Brand, else Amazon
                vendor = data.get("manufacturer") or data["technical_details"].get("Brand", "Amazon")
                product_type = product_type_arg  # Use argument
                tags = ""
                variant_sku = data["asin"]
                raw_price = clean_price(data["price"])
                variant_price = apply_price_formula(raw_price, price_formula_arg)

                if not variant_price:
                    print(f"Skipping CSV write for {asin}: No price found.")
                else:
                    # Get all images
                    images = data["all_images"] if data["all_images"] else []

                    # Row 1: Main Product Data + First Image
                    row1 = {
                        "Handle": handle,
                        "Title": title,
                        "Body (HTML)": body_html,
                        "Vendor": vendor,
                        "Type": product_type,
                        "Tags": tags,
                        "Published": "TRUE",
                        "Variant SKU": variant_sku,
                        "Variant Price": variant_price,
                        "Image Src": images[0] if images else "",
                        "Image Position": 1 if images else "",
                        "Image Alt Text": title,
                        "Product Category": product_category_arg,  # Use argument
                        "Cost Price": raw_price
                    }
                    writer.writerow(row1)

                    # Rows 2..N: Additional Images (only Handle and Image columns needed)
                    for j, img_url in enumerate(images[1:], start=2):
                        row_img = {
                            "Handle": handle,
                            "Image Src": img_url,
                            "Image Position": j,
                            "Image Alt Text": title
                        }
                        writer.writerow(row_img)

                    # Flush to ensure data is written
                    f.flush()

            # Update checkpoint (always, even if no price)
            with open(CHECKPOINT_FILE, "a") as cf:
                cf.write(f"{asin}\n")
            fetched_asins.add(asin)

            print(f"Completed {processed}/{total}: {asin}")

print("Done.")