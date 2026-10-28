"""Replace the vector pictures with real photos from Wikimedia Commons (free, no key).

    python scripts/fetch_photos.py               every product that still has a vector picture
    python scripts/fetch_photos.py DAI-001 SNK-004   only these products (to try again)
    python scripts/fetch_photos.py --undo        go back to the vector pictures

Stop the app first (Ctrl+C), run this, then start the app again.

For each product it searches Wikimedia Commons by the product's name, picks a
photo that is free to use commercially, saves it as data/images/<id>.jpg and
writes that file name into the image column of data/products.csv. Progress is
saved after every product, so it can be stopped and run again. The vector
pictures stay in data/images, and products whose picture was uploaded from the
dashboard are never touched.

When it finishes it opens data/photo_review.html: every photo next to its
product. Replace any wrong one from the dashboard (Edit -> Picture), or add a
better search word to QUERIES below and run the script again with that ID.
Photographers' names and licenses are kept in data/images/CREDITS.csv.
"""

from __future__ import annotations

import csv
import html
import re
import sys
import time
import webbrowser
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.products import CSV_PATH, IMAGES, read_csv, write_csv  # noqa: E402

API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "HBInnovationsShopDemo/1.0 (https://www.hbinnovations.net) python-requests"}
CREDITS = IMAGES / "CREDITS.csv"
REVIEW = ROOT / "data" / "photo_review.html"

# Licenses that allow commercial use.
FREE = re.compile(r"^\s*(cc0|public domain|pd\b|cc by(-sa)?\b)", re.I)
# Titles that are usually not a photo of the food or product itself.
NOT_PRODUCT = re.compile(r"map|logo|label|poster|painting|drawing|diagram|chart|stamp|coat of arms|advert|museum|"
                         r"church|portrait|menu|sign\b|plant|tree|flower|field|farm|market|factory|festival", re.I)
# Words in our product names that don't help a photo search.
FILLER = {"fresh", "organic", "pure", "classic", "gourmet", "artisan", "original", "variety", "premium", "farm", "large",
          "seasonal", "daily", "care", "lightly", "no", "pulp", "thick-cut", "pasture-raised", "unsalted", "unsweetened",
          "boneless", "lean", "90/10", "13", "gal", "70%", "medium", "roast", "dark", "gluten-free", "refill", "scent"}
# Better searches for names that are hard to find as written.
QUERIES = {
    "Organic Whole Milk": "milk bottle", "2% Reduced Fat Milk": "glass of milk", "Unsweetened Almond Milk": "almond milk",
    "Oat Milk Original": "oat milk", "Pasture-Raised Eggs": "brown eggs", "Large White Eggs": "white eggs",
    "Strawberry Yogurt Cups": "strawberry yogurt", "Gourmet Heavy Cream": "whipped cream", "Vegan Cheddar Shreds": "grated cheese",
    "Aged Parmesan": "parmesan cheese", "Fresh Mozzarella": "mozzarella", "Gluten-Free Bread": "bread loaf",
    "Butter Croissants": "croissants", "Seasonal Fruit Medley": "fruit salad", "Navel Oranges": "oranges",
    "Gala Apples": "red apples", "Hass Avocados": "avocado", "Watermelon Chunks": "watermelon", "Organic Baby Spinach": "spinach leaves",
    "Farm Fresh Vegetables Bundle": "assorted vegetables", "Fresh Parsley & Garlic": "parsley", "Broccoli Crowns": "broccoli",
    "Red Bell Peppers": "red bell pepper", "Sweet Green Peas": "green peas", "Fresh Chicken Breasts": "raw chicken breast",
    "Fresh Chicken Breast Fillets": "chicken breast fillet", "Chicken Thighs Boneless": "chicken thighs", "Whole Chicken": "raw whole chicken",
    "Lean Ground Beef 90/10": "ground beef", "Beef Sirloin Steak": "sirloin steak", "Thick-Cut Bacon": "bacon",
    "Atlantic Salmon Fillets": "salmon fillet", "Canned Tuna in Water": "canned tuna", "Deli Sliced Turkey": "sliced turkey meat",
    "Plant-Based Burger Patties": "veggie burger patty", "Artisan Pasta": "dried pasta", "Gluten-Free Penne": "penne",
    "Extra Virgin Olive Oil": "olive oil bottle", "Chunky Salsa": "salsa", "Basil Pesto": "pesto", "Italian Seasoning": "dried herbs",
    "Pure Honey": "honey jar", "Honey Oat Granola": "granola", "Gluten-Free Granola": "granola bowl", "Corn Flakes Cereal": "corn flakes",
    "Whole Grain O's Cereal": "breakfast cereal bowl", "Pancake & Waffle Mix": "pancakes", "Protein Pancake Mix": "stack of pancakes",
    "Pure Maple Syrup": "maple syrup", "Instant Oatmeal Variety": "oatmeal bowl", "Ground Coffee Medium Roast": "ground coffee",
    "Coffee Pods Dark Roast": "coffee capsules", "Black Tea Bags": "tea bags", "Green Tea Bags": "green tea",
    "Gluten-Free Pretzels": "pretzels", "Sea Salt Potato Chips": "potato chips", "Rice Cakes Lightly Salted": "rice cakes",
    "Mixed Nuts Unsalted": "mixed nuts", "Dark Chocolate Bar 70%": "dark chocolate", "Milk Chocolate Bar": "milk chocolate",
    "Gluten-Free Oat Cookies": "oat cookies", "Popcorn Sea Salt": "popcorn", "Protein Bars Variety": "protein bar",
    "Fruit Snacks": "gummy candy", "Seaweed Snacks": "seaweed snack", "Sparkling Water Lime": "sparkling water",
    "Orange Juice No Pulp": "orange juice glass", "Cola": "cola glass", "Diet Cola": "cola can", "Lemon-Lime Soda": "lemon lime soda",
    "Iced Tea Unsweetened": "iced tea", "Cold Brew Coffee": "iced coffee", "Sports Drink Variety": "sports drink",
    "Protein Shake Chocolate": "chocolate milkshake", "Energy Drink": "energy drink can", "Frozen Mixed Vegetables": "frozen vegetables",
    "Gluten-Free Cheese Pizza": "cheese pizza", "Dairy-Free Chocolate Frozen Dessert": "chocolate ice cream",
    "Frozen French Fries": "french fries", "Veggie Fried Rice": "vegetable fried rice", "Dish Soap Lemon": "dish soap",
    "All-Purpose Cleaner": "cleaning spray bottle", "Paper Towels": "paper towel roll", "Toilet Paper": "toilet paper roll",
    "Trash Bags 13 Gal": "garbage bags", "Aluminum Foil": "aluminium foil", "Dishwasher Pods": "dishwasher tablet",
    "Zip Storage Bags": "zipper storage bag", "Fluoride Toothpaste": "toothpaste", "Soft Toothbrushes": "toothbrush",
    "Moisturizing Body Wash": "shower gel", "Shampoo Daily Care": "shampoo bottle", "Conditioner Daily Care": "hair conditioner",
    "Hand Soap Refill": "liquid hand soap", "Deodorant Fresh Scent": "deodorant",
}


def searches(name: str) -> list[str]:
    """Searches to try for a product, most specific first."""
    words = [w for w in re.sub(r"[()&]", " ", name).split() if w.lower() not in FILLER]
    tries = [QUERIES.get(name), " ".join(words), " ".join(words[-2:]), words[-1] if words else name]
    return list(dict.fromkeys(q for q in tries if q))


def get(url: str, **params) -> requests.Response:
    """GET with a polite pause and patience for Wikimedia's rate limit."""
    for attempt in range(6):
        r = requests.get(url, params=params or None, headers=HEADERS, timeout=30)
        if r.status_code != 429 and r.status_code < 500:
            time.sleep(0.5)
            return r
        wait = int(r.headers.get("retry-after") or 0) + 3 * (attempt + 1)
        print(f"   Wikimedia asks us to wait {wait} s...")
        time.sleep(wait)
    r.raise_for_status()
    return r


def find_photo(query: str) -> dict | None:
    data = get(API, action="query", format="json", generator="search", gsrsearch=f"{query} filetype:bitmap", gsrnamespace=6,
               gsrlimit=25, prop="imageinfo", iiprop="url|size|mime|extmetadata", iiurlwidth=500,
               iiextmetadatafilter="LicenseShortName|Artist").json()
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p["index"])
    key = query.lower().split()[-1].rstrip("s")
    good = []
    for page in pages:
        info = page["imageinfo"][0]
        meta = info.get("extmetadata", {})
        license_ = meta.get("LicenseShortName", {}).get("value", "")
        if info["mime"] not in ("image/jpeg", "image/png") or not FREE.match(license_) or NOT_PRODUCT.search(page["title"]):
            continue
        if info["width"] < 500 or not 0.6 < info["width"] / info["height"] < 1.8:
            continue
        artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip() or "Unknown"
        url = info["thumburl"].replace("://thumb.wikimedia.org/", "://upload.wikimedia.org/").split("?")[0]
        good.append({"url": url, "page": info["descriptionurl"], "license": license_, "artist": artist[:150],
                     "title": page["title"], "named": key in page["title"].lower()})
    good.sort(key=lambda c: not c["named"])  # photos whose title names the product first, keeping Wikimedia's order
    return good[0] if good else None


def load_credits() -> dict:
    if not CREDITS.exists():
        return {}
    with open(CREDITS, newline="", encoding="utf-8") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def save_credits(credits: dict) -> None:
    with open(CREDITS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "product", "photo_page", "author", "license"])
        w.writeheader()
        w.writerows(credits.values())


def write_review(products: list[dict], credits: dict) -> None:
    cards = []
    for p in products:
        c = credits.get(p["id"])
        note = (f'<a href="{html.escape(c["photo_page"])}" target="_blank">{html.escape(c["license"])}</a> · {html.escape(c["author"][:60])}'
                if c else "vector picture (no photo found)")
        cards.append(f'<figure><img src="images/{html.escape(p["image"])}" alt=""><figcaption><b>{html.escape(p["name"])}</b>'
                     f'<span>{html.escape(p["id"])}</span><small>{note}</small></figcaption></figure>')
    REVIEW.write_text(f"""<!doctype html><meta charset="utf-8"><title>Photo review</title>
<style>body{{font:14px system-ui;margin:20px;background:#f3f7ff;color:#0f1e3d}}main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px}}
figure{{margin:0;background:#fff;border:1px solid #dbe4f4;border-radius:12px;overflow:hidden}}img{{width:100%;aspect-ratio:1;object-fit:contain;background:#fff}}
figcaption{{padding:8px;display:flex;flex-direction:column;gap:2px}}span,small{{color:#5a6a8a;font-size:12px}}</style>
<h1>Photo review</h1><p>Check each photo matches its product. Fix a wrong one in the dashboard (Edit → Picture), or run
<code>python scripts/fetch_photos.py ID</code> after adding a better search to QUERIES in the script.</p><main>{"".join(cards)}</main>""",
                      encoding="utf-8")


def undo() -> None:
    products = read_csv(CSV_PATH)
    for p in products:
        if (IMAGES / f"{p['id']}.svg").exists() and not p["image"].endswith(".svg"):
            p["image"] = f"{p['id']}.svg"
    write_csv(products, CSV_PATH)
    print("Back to the vector pictures. The downloaded photos are still in data/images if you want them again.")


def main(ids: list[str]) -> None:
    products = read_csv(CSV_PATH)
    credits = load_credits()
    todo = [p for p in products if p["id"] in ids] if ids else [p for p in products if p["image"].endswith(".svg") or not p["image"]]
    print(f"Finding photos for {len(todo)} products. This takes about {max(1, len(todo) * 3 // 60)} minutes...")
    found, failures = 0, 0
    for n, p in enumerate(todo, 1):
        photo, r = None, None
        try:
            for q in searches(p["name"]):
                photo = find_photo(q)
                if photo:
                    break
            if photo:
                r = get(photo["url"])
        except requests.RequestException as e:
            failures += 1
            print(f"[{n}/{len(todo)}] {p['name']}: internet problem, skipped.")
            if failures >= 3:
                print(f"\nStopped: can't reach Wikimedia Commons from this computer.\nError: {e}\n"
                      "Check that https://commons.wikimedia.org opens in your browser, and try turning off a VPN or "
                      "antivirus web shield. Then run this script again; it continues where it stopped.")
                break
            continue
        failures = 0
        if not photo:
            print(f"[{n}/{len(todo)}] {p['name']}: no photo found, keeping the vector picture")
            continue
        if not r.ok or not r.headers.get("content-type", "").startswith("image/"):
            print(f"[{n}/{len(todo)}] {p['name']}: download failed, keeping the vector picture")
            continue
        ext = ".png" if "png" in r.headers["content-type"] else ".jpg"
        for old in IMAGES.glob(f"{p['id']}.*"):  # an earlier photo of this product (never the vector picture)
            if old.suffix in (".jpg", ".png") and old.suffix != ext:
                old.unlink()
        (IMAGES / f"{p['id']}{ext}").write_bytes(r.content)
        p["image"] = f"{p['id']}{ext}"
        credits[p["id"]] = {"id": p["id"], "product": p["name"], "photo_page": photo["page"], "author": photo["artist"],
                            "license": photo["license"]}
        write_csv(products, CSV_PATH)  # save progress after every product
        save_credits(credits)
        found += 1
        print(f"[{n}/{len(todo)}] {p['name']}: {photo['title']}")
    write_review(products, credits)
    print(f"\nDone: {found} of {len(todo)} products now have a photo.")
    print(f"Check them here: {REVIEW}")
    try:
        webbrowser.open(REVIEW.as_uri())
    except Exception:
        pass


if __name__ == "__main__":
    args = sys.argv[1:]
    undo() if args == ["--undo"] else main([a.upper() for a in args])
