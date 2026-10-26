"""Product kinds: the shared vocabulary for suitability.

Every published product is classified into exactly one kind (or "unknown").
Every customer need names the kind(s) that can satisfy it. A product can
only fill a need when its kind is accepted by that need, so "potato chips"
(snacks.chips) can never fill "potatoes" (produce.potato), and "chocolate
spread" can never fill "milk".

Keywords are matched against product names and categories at ingest time.
They include English, Roman Urdu and Urdu terms. `not` lists words that veto
a kind (e.g. "chips" vetoes produce.potato). `subs` lists kinds that may be
offered as an explicit, explained substitution, never silently.

`norm` is a rough weekly amount per person used for quantity estimates, in
the kind's base unit (g, ml or pc). Estimates are labelled as such to the
customer; they are not nutritional advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Kind:
    id: str
    label: str
    keywords: tuple[str, ...]
    not_words: tuple[str, ...] = ()
    subs: tuple[str, ...] = ()
    unit: str = ""          # base unit for norms: g, ml, pc
    norm: float = 0.0       # per person per week, in `unit`
    categories: tuple[str, ...] = ()  # feed category words that strongly suggest this kind


def K(id, label, keywords, not_words=(), subs=(), unit="", norm=0.0, categories=()):
    return Kind(id, label, tuple(keywords), tuple(not_words), tuple(subs), unit, norm, tuple(categories))


_SNACKY = ("chips", "crisps", "fries", "snack", "flakes", "nimko", "slanty", "kurkure", "wafer")
_SWEET = ("spread", "chocolate", "nutella", "candy", "toffee", "ice cream", "kulfi", "biscuit", "cookie", "cake")
_CLEANING = ("soap", "detergent", "dishwash", "cleaner", "shampoo", "lotion", "wash", "face", "hair", "skin")

KINDS: list[Kind] = [
    # ---- dairy & eggs
    K("dairy.milk", "Milk (liquid)", ["milk", "doodh", "دودھ", "uht milk", "full cream milk", "milkpak", "olpers milk"],
      not_words=("powder", "spread", "chocolate", "nutrition", "formula", "condensed", "evaporated", "tea whitener",
                 "whitener", "coconut", "shake", "flavoured", "flavored", "biscuit", "cake", "soap", "lotion", "milky"),
      subs=("dairy.milk_powder",), unit="ml", norm=1750, categories=("milk",)),
    K("dairy.milk_powder", "Milk powder", ["milk powder", "powdered milk", "nido", "everyday", "doodh powder"],
      not_words=("formula", "infant", "baby", "nutrition drink", "chocolate"), unit="g", norm=0),
    K("dairy.flavoured_milk", "Flavoured milk drinks", ["flavoured milk", "flavored milk", "chocolate milk", "strawberry milk", "milk shake"], unit="ml"),
    K("dairy.tea_whitener", "Tea whitener", ["tea whitener", "whitener", "tarang", "everyday tea whitener", "dairy omung"], unit="ml"),
    K("dairy.yogurt", "Yogurt", ["yogurt", "yoghurt", "dahi", "دہی", "curd"], not_words=("drink", "raita masala"),
      unit="g", norm=500),
    K("dairy.butter", "Butter", ["butter", "makhan", "مکھن"], not_words=("peanut", "cookie", "biscuit", "popcorn"), unit="g", norm=50),
    K("dairy.cheese", "Cheese", ["cheese", "cheddar", "mozzarella", "paneer"], not_words=("cracker", "balls", "puffs"), unit="g"),
    K("dairy.cream", "Cream", ["cream", "malai", "fresh cream", "cooking cream"], not_words=_CLEANING + ("ice cream", "biscuit"), unit="ml"),
    K("dairy.eggs", "Eggs", ["eggs", "egg", "anday", "anda", "انڈے", "انڈا"], not_words=("noodle", "eggless", "mayo", "custard"),
      unit="pc", norm=4, categories=("eggs",)),
    # ---- staples
    K("staples.flour", "Wheat flour (aata)", ["atta", "aata", "flour", "chakki atta", "آٹا", "wheat flour"],
      not_words=("corn flour", "cornflour", "gram flour", "besan", "rice flour", "maida", "self raising"), unit="g", norm=1500),
    K("staples.maida", "Maida / all-purpose flour", ["maida", "all purpose flour", "plain flour", "fine flour"], unit="g"),
    K("staples.besan", "Gram flour (besan)", ["besan", "gram flour", "بیسن"], unit="g"),
    K("staples.rice", "Rice", ["rice", "chawal", "چاول", "basmati", "sella", "kainat", "super kernel"],
      not_words=("flour", "cake", "crispies", "krispies", "vinegar", "noodle", "rice cracker", "kheer mix"), unit="g", norm=500),
    K("staples.sugar", "Sugar", ["sugar", "cheeni", "چینی", "shakar"], not_words=("free", "icing", "brown sugar syrup", "candy"),
      subs=("staples.brown_sugar",), unit="g", norm=250),
    K("staples.brown_sugar", "Brown sugar / shakkar", ["brown sugar", "shakkar", "gur", "jaggery"], unit="g"),
    K("staples.salt", "Salt", ["salt", "namak", "نمک"], not_words=("salted", "chips", "butter", "biscuit", "pepper mix"), unit="g", norm=60),
    K("staples.daal_masoor", "Masoor daal (red lentils)", ["masoor", "red lentil", "مسور"], unit="g", norm=150),
    K("staples.daal_chana", "Chana daal (split chickpea)", ["chana daal", "chana dal", "daal chana", "dal chana"], unit="g", norm=150),
    K("staples.daal_moong", "Moong daal", ["moong", "mung"], unit="g", norm=150),
    K("staples.daal_mash", "Mash daal (urad)", ["mash daal", "maash", "urad"], unit="g", norm=100),
    K("staples.chickpeas", "Chickpeas (kabuli chana)", ["chickpeas", "kabuli chana", "safaid chana", "white chana", "chole"],
      not_words=("daal", "dal", "chips"), unit="g"),
    K("staples.vermicelli", "Vermicelli (sewaiyan)", ["vermicelli", "sewaiyan", "seviyan"], unit="g"),
    K("staples.pasta", "Pasta & noodles", ["pasta", "spaghetti", "macaroni", "penne", "noodles", "noodle"], unit="g"),
    # ---- oils & fats
    K("oils.cooking_oil", "Cooking oil", ["cooking oil", "oil", "tel", "تیل", "canola", "sunflower oil", "soybean oil", "corn oil"],
      not_words=("olive", "hair", "massage", "coconut hair", "almond oil", "body", "baby oil", "mustard oil", "fish oil", "engine"),
      subs=("oils.ghee",), unit="ml", norm=250, categories=("cooking oil",)),
    K("oils.ghee", "Ghee / banaspati", ["ghee", "banaspati", "گھی", "desi ghee", "vanaspati"], subs=("oils.cooking_oil",), unit="g", norm=150),
    K("oils.olive_oil", "Olive oil", ["olive oil", "zaitoon"], unit="ml"),
    # ---- spices & cooking aids
    K("spices.biryani_masala", "Biryani masala", ["biryani masala", "biryani mix", "sindhi biryani", "bombay biryani", "biryani recipe mix"],
      unit="g"),
    K("spices.chaat_masala", "Chaat masala", ["chaat masala", "chat masala", "fruit chaat", "chaat and fries masala", "fries masala"], unit="g"),
    K("spices.karahi_masala", "Karahi masala", ["karahi masala", "karahi mix", "kadai"], unit="g"),
    K("spices.nihari_masala", "Nihari masala", ["nihari"], unit="g"),
    K("spices.korma_masala", "Korma masala", ["korma"], unit="g"),
    K("spices.tikka_masala", "Tikka / BBQ masala", ["tikka masala", "tikka mix", "bbq masala", "tandoori", "seekh kabab masala", "tikka seekh", "kabab masala"], unit="g"),
    K("spices.curry_masala", "Curry & salan masala", ["chicken masala", "curry masala", "salan masala", "qorma masala", "meat masala"], unit="g"),
    K("spices.garam_masala", "Garam masala", ["garam masala", "گرم مصالحہ"], unit="g"),
    K("spices.red_chilli", "Red chilli powder", ["red chilli", "red chili", "lal mirch", "لال مرچ", "chilli powder", "chili powder"],
      not_words=("sauce", "flakes chips"), unit="g"),
    K("spices.turmeric", "Turmeric (haldi)", ["turmeric", "haldi", "ہلدی"], unit="g"),
    K("spices.coriander_powder", "Coriander powder", ["coriander powder", "dhania powder", "dhaniya powder"], unit="g"),
    K("spices.cumin", "Cumin (zeera)", ["cumin", "zeera", "jeera", "زیرہ"], unit="g"),
    K("spices.black_pepper", "Black pepper", ["black pepper", "kali mirch"], unit="g"),
    K("spices.whole_garam", "Whole spices", ["cloves", "laung", "cardamom", "elaichi", "cinnamon", "darchini", "bay leaf", "tez patta"], unit="g"),
    K("spices.ginger_garlic_paste", "Ginger garlic paste", ["ginger garlic paste", "adrak lehsan paste", "garlic paste", "ginger paste"], unit="g"),
    K("condiments.ketchup", "Ketchup & sauces", ["ketchup", "tomato sauce", "chilli sauce", "chilli garlic sauce", "garlic sauce", "hot sauce", "soy sauce"], unit="g"),
    K("condiments.mayo", "Mayonnaise", ["mayonnaise", "mayo"], unit="g"),
    K("condiments.pickle", "Pickle (achar)", ["pickle", "achar", "achaar", "اچار"], unit="g"),
    K("condiments.vinegar", "Vinegar", ["vinegar", "sirka"], unit="ml"),
    # ---- fresh produce
    K("produce.potato", "Potatoes (fresh)", ["potato", "potatoes", "aloo", "آلو"], not_words=_SNACKY + ("starch", "mash mix", "powder", "samosa", "patties"),
      unit="g", norm=750, categories=("vegetable", "vegetables", "fresh", "produce", "sabzi")),
    K("produce.onion", "Onions (fresh)", ["onion", "onions", "pyaz", "piyaz", "پیاز"], not_words=("powder", "rings", "fried onion", "chips"),
      unit="g", norm=750, categories=("vegetable", "vegetables", "fresh", "produce")),
    K("produce.tomato", "Tomatoes (fresh)", ["tomato", "tomatoes", "tamatar", "ٹماٹر"], not_words=("ketchup", "sauce", "paste", "puree", "soup", "chips"),
      unit="g", norm=500, categories=("vegetable", "vegetables", "fresh", "produce")),
    K("produce.ginger", "Ginger (fresh)", ["ginger", "adrak", "ادرک"], not_words=("paste", "powder", "biscuit", "ale", "tea"), unit="g", norm=50),
    K("produce.garlic", "Garlic (fresh)", ["garlic", "lehsan", "lahsan", "لہسن"], not_words=("paste", "powder", "mayo", "sauce", "bread"), unit="g", norm=50),
    K("produce.green_chilli", "Green chillies", ["green chilli", "green chili", "hari mirch", "ہری مرچ"], not_words=("sauce", "powder"), unit="g", norm=50),
    K("produce.herbs", "Fresh coriander & mint", ["coriander", "dhania", "dhaniya", "mint", "podina", "pudina"],
      not_words=("powder", "seeds", "chutney", "sauce"), unit="g"),
    K("produce.lemon", "Lemons", ["lemon", "lemons", "lime", "nimbu", "leemu"], not_words=("juice", "drink", "malt", "soap", "dishwash", "flavour", "squash"), unit="pc"),
    K("produce.vegetables", "Other fresh vegetables", ["cabbage", "cauliflower", "gobi", "spinach", "palak", "carrot", "gajar", "peas", "matar",
                                                      "okra", "bhindi", "cucumber", "kheera", "capsicum", "shimla mirch", "brinjal", "baingan", "bitter gourd", "karela",
                                                      "pumpkin", "kaddu", "radish", "mooli", "lettuce"],
      not_words=("frozen", "pickle", "achar", "soup", "chips", "juice"), unit="g", categories=("vegetable", "vegetables")),
    K("produce.fruit", "Fresh fruit", ["banana", "kela", "apple", "saib", "orange", "kinnow", "mango", "aam", "grapes", "angoor", "guava", "amrood",
                                       "pomegranate", "anaar", "melon", "watermelon", "tarbooz", "papaya", "dates", "khajoor", "strawberry"],
      not_words=("juice", "drink", "jam", "jelly", "flavour", "flavor", "biscuit", "squash", "nectar", "cake", "candy", "shake", "yogurt", "chips"),
      unit="g", categories=("fruit", "fruits")),
    # ---- meat
    K("meat.chicken", "Chicken (raw)", ["chicken", "murgh", "murghi", "مرغی", "broiler", "chicken breast", "chicken boneless", "drumsticks"],
      not_words=("nuggets", "sausage", "kebab", "kabab", "seekh", "patties", "powder", "cube", "stock", "noodles", "soup", "masala", "spread", "chips", "salami"),
      unit="g", norm=500, categories=("meat", "poultry", "chicken")),
    K("meat.mutton", "Mutton (raw)", ["mutton", "bakra", "goat meat", "gosht"], not_words=("masala", "nihari", "korma", "pulao mix"), unit="g", norm=300),
    K("meat.beef", "Beef (raw)", ["beef", "bara gosht", "qeema", "keema", "mince"], not_words=("masala", "kebab", "burger", "sausage", "salami", "nuggets"), unit="g", norm=300),
    K("meat.frozen_ready", "Frozen ready-to-cook", ["nuggets", "kebab", "kabab", "seekh kabab", "sausage", "patties", "samosa", "paratha", "spring roll", "shami"],
      unit="pc", categories=("frozen",)),
    # ---- bakery & breakfast
    K("bakery.bread", "Bread", ["bread", "double roti", "ڈبل روٹی", "sandwich bread", "milky bread", "brown bread"],
      not_words=("crumbs", "garlic bread mix"), unit="g", norm=300),
    K("bakery.rusk", "Rusk", ["rusk", "papay", "paapey"], unit="g"),
    K("breakfast.cereal", "Breakfast cereal", ["cornflakes", "corn flakes", "cereal", "oats", "muesli", "granola"], not_words=("chips",), unit="g"),
    K("breakfast.jam", "Jam & honey", ["jam", "jelly", "honey", "shehad", "marmalade"], not_words=("jelly crystals",), unit="g"),
    K("breakfast.spread", "Chocolate & nut spreads", ["chocolate spread", "nutella", "hazelnut spread", "peanut butter"], unit="g"),
    # ---- beverages
    K("bev.tea", "Tea (chai patti)", ["tea", "chai", "chai patti", "چائے", "tapal", "lipton", "danedar", "green tea", "tea bags"],
      not_words=("whitener", "biscuit", "cup", "kettle", "tea spoon", "ice tea", "iced tea"), unit="g", norm=50, categories=("tea",)),
    K("bev.coffee", "Coffee", ["coffee", "nescafe"], not_words=("whitener", "mate", "biscuit", "cake"), unit="g"),
    K("bev.juice", "Juice", ["juice", "nectar", "squash", "sharbat", "rooh afza", "tang"], not_words=("lemon fresh",), unit="ml"),
    K("bev.soft_drink", "Soft drinks", ["cola", "pepsi", "coke", "coca cola", "sprite", "7up", "fanta", "mirinda", "dew", "soft drink", "fizzy"], unit="ml"),
    K("bev.water", "Drinking water", ["water", "mineral water", "pani", "nestle pure life", "aquafina"], not_words=("rose water", "coconut", "gripe"), unit="ml"),
    K("bev.nutrition", "Nutrition & health drinks", ["nutrition", "horlicks", "ovaltine", "milo", "complan", "ensure", "health drink", "nutrition powder"],
      unit="g"),
    # ---- snacks & sweets
    K("snacks.chips", "Chips & crisps", ["chips", "crisps", "lays", "slanty", "kurkure", "nimko", "cheetos", "pringles", "potato sticks", "super crisp"],
      unit="g"),
    K("snacks.biscuits", "Biscuits & cookies", ["biscuit", "biscuits", "cookies", "cookie", "rio", "prince", "sooper", "tuc", "zeera plus", "marie"], unit="g"),
    K("snacks.chocolate", "Chocolate & sweets", ["chocolate", "dairy milk", "kitkat", "snickers", "candy", "toffee", "lollipop"],
      not_words=("spread", "milk powder", "drink", "flavoured", "flavored", "biscuit", "biscuits", "cookie", "cookies", "masala"), unit="g"),
    K("snacks.dessert_mix", "Dessert mixes", ["custard", "kheer mix", "jelly crystals", "firni", "pudding", "falooda"], unit="g"),
    # ---- household
    K("home.laundry", "Laundry detergent", ["detergent", "surf", "surf excel", "ariel", "bonus", "washing powder", "laundry"],
      not_words=("dishwash", "dish wash"), unit="g"),
    K("home.dishwash", "Dishwashing", ["dishwash", "dish wash", "dishwashing", "lemon max", "bartan", "vim"], unit="g"),
    K("home.cleaner", "Surface & toilet cleaners", ["cleaner", "harpic", "phenyl", "bleach", "glass cleaner", "floor cleaner", "dettol liquid", "mr muscle"],
      not_words=("face", "skin"), unit="ml"),
    K("home.tissue", "Tissues & paper", ["tissue", "tissues", "toilet roll", "kitchen roll", "napkin", "rose petal"], unit="pc"),
    K("home.trash_bags", "Garbage bags", ["garbage bag", "trash bag", "bin bag"], unit="pc"),
    # ---- personal care
    K("care.soap", "Bath soap", ["soap", "sabun", "صابن", "lifebuoy", "lux", "safeguard", "dettol soap", "dove bar"],
      not_words=("dish", "dishwash", "detergent", "liquid hand", "handwash", "surf"), unit="pc"),
    K("care.handwash", "Hand wash", ["hand wash", "handwash"], unit="ml"),
    K("care.shampoo", "Shampoo", ["shampoo", "sunsilk", "head & shoulders", "head and shoulders", "pantene", "clear shampoo"], unit="ml"),
    K("care.toothpaste", "Toothpaste", ["toothpaste", "tooth paste", "colgate", "sensodyne", "medicam", "close up"], not_words=("brush",), unit="g"),
    K("care.hair_oil", "Hair oil", ["hair oil"], unit="ml"),
    K("care.toothbrush", "Toothbrush", ["toothbrush", "tooth brush"], unit="pc"),
    K("baby.diapers", "Diapers", ["diaper", "diapers", "pampers", "nappy", "molfix", "canbebe"], unit="pc"),
]

UNKNOWN = "unknown"
BY_ID: dict[str, Kind] = {k.id: k for k in KINDS}


def get(kind_id: str) -> Kind | None:
    return BY_ID.get(kind_id)


def catalog_prompt() -> str:
    """Compact list of kinds for the model: id and label."""
    return "\n".join(f"{k.id}: {k.label}" for k in KINDS)


def closest(kind_id: str, n: int = 5) -> list[str]:
    """Suggest valid kind ids for an invalid one (by shared words)."""
    words = set(kind_id.replace(".", " ").replace("_", " ").lower().split())
    scored = []
    for k in KINDS:
        hay = set(f"{k.id} {k.label}".replace(".", " ").replace("_", " ").lower().split())
        score = len(words & hay)
        if score:
            scored.append((score, k.id))
    scored.sort(reverse=True)
    return [kid for _, kid in scored[:n]]
