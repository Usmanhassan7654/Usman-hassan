"""Generate the demo catalog: 200 grocery products with SVG pictures.

    python scripts/make_dataset.py

Writes data/products.json and data/images/<id>.svg. Brands are fictional and
prices are illustrative.
"""

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# name, brand, price, size, diet tags, allergens, shape, color, extra search words, pairs with
# diet tags: vegan, vegetarian, gluten-free, dairy-free, organic, keto, nut-free, low-sugar, high-protein
CATALOG = {
    "Dairy & Eggs": [
        ("Organic Whole Milk", "Green Valley", 4.00, "1 gal", "vegetarian gluten-free organic nut-free", "milk", "carton", "#e8f1fb", "dairy milk", "cereal cookies"),
        ("2% Reduced Fat Milk", "Green Valley", 3.49, "1 gal", "vegetarian gluten-free nut-free", "milk", "carton", "#dbeafe", "dairy milk low fat", "cereal"),
        ("Unsweetened Almond Milk", "Nature's Basket", 3.29, "64 fl oz", "vegan dairy-free gluten-free low-sugar", "tree-nuts", "carton", "#f5e6d3", "plant milk non-dairy", "oats granola"),
        ("Oat Milk Original", "Nature's Basket", 4.29, "64 fl oz", "vegan dairy-free nut-free", "", "carton", "#f3e3c3", "plant milk non-dairy", "coffee cereal"),
        ("Pasture-Raised Eggs", "Harvest Farm", 5.00, "12 ct", "vegetarian gluten-free high-protein keto", "eggs", "box", "#f6e7c8", "eggs dozen breakfast", "bread bacon"),
        ("Large White Eggs", "Sunny Fields", 3.29, "12 ct", "vegetarian gluten-free high-protein keto", "eggs", "box", "#faf3e3", "eggs dozen", "bread"),
        ("Greek Yogurt Plain", "Green Valley", 5.49, "32 oz", "vegetarian gluten-free high-protein", "milk", "tub", "#eef6ff", "yogurt yoghurt protein", "granola berries honey"),
        ("Strawberry Yogurt Cups", "Green Valley", 4.99, "4 x 5.3 oz", "vegetarian gluten-free", "milk", "tub", "#fbd5dc", "yogurt kids snack", "granola"),
        ("Unsalted Butter", "Harvest Farm", 4.79, "1 lb", "vegetarian gluten-free keto", "milk", "box", "#fde68a", "butter baking", "bread flour"),
        ("Aged Parmesan", "Bella Cucina", 5.40, "200 g", "vegetarian gluten-free keto", "milk", "block", "#fcd34d", "parmesan cheese italian", "pasta alfredo"),
        ("Sharp Cheddar Cheese", "Harvest Farm", 4.49, "8 oz", "vegetarian gluten-free keto", "milk", "block", "#f59e0b", "cheddar cheese sandwich", "bread crackers"),
        ("Fresh Mozzarella", "Bella Cucina", 4.99, "8 oz", "vegetarian gluten-free keto", "milk", "tub", "#f8fafc", "mozzarella cheese pizza lasagna", "tomatoes basil"),
        ("Ricotta Cheese", "Bella Cucina", 3.99, "15 oz", "vegetarian gluten-free", "milk", "tub", "#fefce8", "ricotta cheese lasagna", "lasagna sheets"),
        ("Gourmet Heavy Cream", "Green Valley", 3.20, "250 ml", "vegetarian gluten-free keto", "milk", "carton", "#fffbeb", "heavy cream whipping alfredo", "pasta"),
        ("Sour Cream", "Green Valley", 2.49, "16 oz", "vegetarian gluten-free keto", "milk", "tub", "#f8fafc", "sour cream tacos", "tortillas"),
        ("Cream Cheese", "Green Valley", 2.99, "8 oz", "vegetarian gluten-free keto", "milk", "block", "#eff6ff", "cream cheese bagel", "bagels"),
        ("Vegan Cheddar Shreds", "Nature's Basket", 5.29, "7 oz", "vegan dairy-free gluten-free", "", "bag", "#fde047", "dairy-free cheese plant", "tortillas"),
        ("Cottage Cheese", "Sunny Fields", 3.79, "16 oz", "vegetarian gluten-free high-protein", "milk", "tub", "#f1f5f9", "cottage cheese protein", "fruit"),
    ],
    "Bakery": [
        ("Whole Wheat Sandwich Bread", "Baker's Choice", 3.49, "20 oz", "vegan", "wheat", "loaf", "#c08457", "bread loaf toast", "peanut butter jam"),
        ("White Sandwich Bread", "Baker's Choice", 2.79, "20 oz", "vegetarian", "wheat milk", "loaf", "#e7c9a0", "bread loaf toast", "butter jam"),
        ("Gluten-Free Bread", "Nature's Basket", 5.99, "16 oz", "vegetarian gluten-free", "eggs", "loaf", "#d6b98c", "bread gluten free celiac", "butter"),
        ("Sourdough Loaf", "Baker's Choice", 4.99, "24 oz", "vegan", "wheat", "loaf", "#b7895a", "sourdough artisan bread", "olive oil"),
        ("Plain Bagels", "Baker's Choice", 3.99, "6 ct", "vegan", "wheat", "bag", "#d9a066", "bagels breakfast", "cream cheese"),
        ("Butter Croissants", "Baker's Choice", 4.49, "4 ct", "vegetarian", "wheat milk eggs", "box", "#e9b872", "croissant pastry breakfast", "jam coffee"),
        ("Flour Tortillas", "Sol Cocina", 2.99, "10 ct", "vegan", "wheat", "bag", "#f3e2c3", "tortilla wraps tacos burritos", "salsa beans"),
        ("Corn Tortillas", "Sol Cocina", 2.49, "30 ct", "vegan gluten-free", "", "bag", "#f7d774", "corn tortilla tacos gluten free", "salsa"),
        ("Hamburger Buns", "Baker's Choice", 2.99, "8 ct", "vegetarian", "wheat", "bag", "#e2b07a", "burger buns", "ground beef"),
        ("Garlic Bread", "Bella Cucina", 3.49, "16 oz", "vegetarian", "wheat milk", "loaf", "#e6c07b", "garlic bread italian side", "pasta"),
        ("Blueberry Muffins", "Baker's Choice", 4.99, "4 ct", "vegetarian", "wheat milk eggs", "box", "#7c83c8", "muffins breakfast bakery", "coffee"),
        ("Pita Bread", "Baker's Choice", 2.79, "6 ct", "vegan", "wheat", "bag", "#ecd5a8", "pita flatbread", "hummus"),
    ],
    "Fruits": [
        ("Bananas", "Fresh", 1.49, "6 ct", "vegan gluten-free organic", "", "fruit", "#facc15", "banana fruit", "oats yogurt"),
        ("Gala Apples", "Fresh", 3.99, "3 lb bag", "vegan gluten-free", "", "fruit", "#ef4444", "apple fruit snack", "peanut butter"),
        ("Strawberries", "Fresh", 3.99, "1 lb", "vegan gluten-free", "", "fruit", "#e11d48", "strawberry berries", "yogurt cream"),
        ("Blueberries", "Fresh", 4.49, "1 pint", "vegan gluten-free organic", "", "fruit", "#3730a3", "blueberry berries", "yogurt oats"),
        ("Seasonal Fruit Medley", "Fresh", 9.00, "2 lb", "vegan gluten-free", "", "fruit", "#fb923c", "fruit mix assorted fresh fruit", "yogurt"),
        ("Navel Oranges", "Fresh", 4.99, "4 lb bag", "vegan gluten-free", "", "fruit", "#f97316", "orange citrus vitamin c", ""),
        ("Lemons", "Fresh", 2.99, "2 lb bag", "vegan gluten-free", "", "fruit", "#fde047", "lemon citrus", "chicken fish"),
        ("Limes", "Fresh", 2.49, "1 lb bag", "vegan gluten-free", "", "fruit", "#84cc16", "lime citrus tacos", "avocado"),
        ("Hass Avocados", "Fresh", 4.99, "4 ct", "vegan gluten-free keto", "", "fruit", "#4d7c0f", "avocado guacamole", "tortilla chips limes"),
        ("Red Grapes", "Fresh", 3.99, "2 lb", "vegan gluten-free", "", "fruit", "#9f1239", "grapes fruit snack", "cheese"),
        ("Pineapple", "Fresh", 3.49, "1 ct", "vegan gluten-free", "", "fruit", "#eab308", "pineapple tropical", ""),
        ("Watermelon Chunks", "Fresh", 5.99, "2 lb", "vegan gluten-free", "", "fruit", "#f43f5e", "watermelon melon", ""),
        ("Mango", "Fresh", 1.29, "1 ct", "vegan gluten-free", "", "fruit", "#f59e0b", "mango tropical", "yogurt"),
        ("Pears", "Fresh", 3.49, "2 lb", "vegan gluten-free", "", "fruit", "#a3e635", "pear fruit", "cheese"),
        ("Raspberries", "Fresh", 4.99, "6 oz", "vegan gluten-free", "", "fruit", "#be123c", "raspberry berries", "yogurt"),
        ("Organic Baby Spinach", "Fresh", 3.99, "5 oz", "vegan gluten-free organic keto", "", "bag", "#15803d", "spinach salad greens leafy", "eggs pasta"),
    ],
    "Vegetables": [
        ("Farm Fresh Vegetables Bundle", "Fresh", 10.00, "assorted 3 lb", "vegan gluten-free", "", "bunch", "#16a34a", "vegetables veggies mix assorted", "chicken rice"),
        ("Yellow Onions", "Fresh", 2.99, "3 lb bag", "vegan gluten-free", "", "veg", "#d97706", "onion", "garlic"),
        ("Fresh Garlic", "Fresh", 0.99, "3 ct", "vegan gluten-free", "", "veg", "#f5f5f4", "garlic", "onion pasta"),
        ("Fresh Parsley & Garlic", "Fresh", 2.10, "bundle", "vegan gluten-free", "", "bunch", "#22c55e", "parsley garlic herbs fresh bundle", "pasta chicken"),
        ("Roma Tomatoes", "Fresh", 2.49, "2 lb", "vegan gluten-free keto", "", "veg", "#dc2626", "tomato tomatoes", "mozzarella basil"),
        ("Russet Potatoes", "Fresh", 4.49, "5 lb bag", "vegan gluten-free", "", "veg", "#a16207", "potato potatoes", "butter sour cream"),
        ("Sweet Potatoes", "Fresh", 2.99, "2 lb", "vegan gluten-free", "", "veg", "#ea580c", "sweet potato yam", ""),
        ("Carrots", "Fresh", 1.99, "2 lb bag", "vegan gluten-free", "", "veg", "#f97316", "carrot carrots", "hummus"),
        ("Broccoli Crowns", "Fresh", 2.99, "1 lb", "vegan gluten-free keto", "", "veg", "#15803d", "broccoli green vegetable", "chicken rice"),
        ("Red Bell Peppers", "Fresh", 3.49, "3 ct", "vegan gluten-free keto", "", "veg", "#ef4444", "bell pepper capsicum", "chicken fajitas"),
        ("Cucumbers", "Fresh", 1.79, "2 ct", "vegan gluten-free keto", "", "veg", "#4ade80", "cucumber salad", "tomatoes"),
        ("Romaine Lettuce", "Fresh", 2.99, "3 hearts", "vegan gluten-free keto", "", "bunch", "#65a30d", "lettuce salad romaine", "dressing"),
        ("Zucchini", "Fresh", 1.99, "1 lb", "vegan gluten-free keto", "", "veg", "#4d7c0f", "zucchini courgette squash", ""),
        ("White Mushrooms", "Fresh", 2.79, "8 oz", "vegan gluten-free keto", "", "tray", "#e7e5e4", "mushrooms", "pasta"),
        ("Fresh Basil", "Fresh", 2.49, "0.75 oz", "vegan gluten-free", "", "bunch", "#16a34a", "basil herbs italian", "tomatoes mozzarella"),
        ("Cilantro", "Fresh", 0.99, "1 bunch", "vegan gluten-free", "", "bunch", "#22c55e", "cilantro coriander herbs", "limes tacos"),
        ("Green Beans", "Fresh", 2.99, "1 lb", "vegan gluten-free", "", "bag", "#16a34a", "green beans", ""),
        ("Sweet Corn", "Fresh", 2.00, "4 ears", "vegan gluten-free", "", "veg", "#facc15", "corn on the cob", "butter"),
        ("Celery", "Fresh", 1.99, "1 bunch", "vegan gluten-free keto", "", "bunch", "#84cc16", "celery", "peanut butter"),
        ("Cauliflower", "Fresh", 3.49, "1 head", "vegan gluten-free keto", "", "veg", "#f5f5f4", "cauliflower low carb", ""),
        ("Ginger Root", "Fresh", 1.49, "4 oz", "vegan gluten-free", "", "veg", "#d4a373", "ginger", "garlic"),
        ("Sweet Green Peas", "Fresh", 2.49, "12 oz", "vegan gluten-free", "", "bag", "#22c55e", "peas green", "rice"),
    ],
    "Meat & Seafood": [
        ("Fresh Chicken Breasts", "Harvest Farm", 12.00, "1.5 lb", "gluten-free high-protein keto dairy-free", "", "tray", "#fecaca", "chicken breast boneless skinless poultry", "rice vegetables"),
        ("Fresh Chicken Breast Fillets", "Harvest Farm", 9.50, "300 g", "gluten-free high-protein keto dairy-free", "", "tray", "#fecdd3", "chicken breast fillet poultry small pack", "pasta cream"),
        ("Chicken Thighs Boneless", "Harvest Farm", 7.99, "1.5 lb", "gluten-free high-protein keto dairy-free", "", "tray", "#fda4af", "chicken thighs poultry", "rice"),
        ("Whole Chicken", "Harvest Farm", 9.99, "4 lb", "gluten-free high-protein keto dairy-free", "", "tray", "#fbcfe8", "whole chicken roast", "potatoes"),
        ("Lean Ground Beef 90/10", "Prairie Ranch", 6.99, "1 lb", "gluten-free high-protein keto dairy-free", "", "tray", "#b91c1c", "ground beef mince burger", "buns lasagna tacos"),
        ("Ground Turkey", "Prairie Ranch", 5.99, "1 lb", "gluten-free high-protein keto dairy-free", "", "tray", "#f87171", "ground turkey lean", "tacos"),
        ("Beef Sirloin Steak", "Prairie Ranch", 11.99, "1 lb", "gluten-free high-protein keto dairy-free", "", "tray", "#991b1b", "steak beef sirloin", "potatoes"),
        ("Pork Chops", "Prairie Ranch", 7.49, "1.25 lb", "gluten-free high-protein keto dairy-free", "", "tray", "#fca5a5", "pork chops", "apples"),
        ("Thick-Cut Bacon", "Prairie Ranch", 6.49, "12 oz", "gluten-free keto dairy-free", "", "pack", "#dc2626", "bacon breakfast pork", "eggs"),
        ("Italian Sausage", "Bella Cucina", 5.99, "1 lb", "gluten-free high-protein dairy-free", "", "pack", "#b45309", "sausage italian pork", "pasta peppers"),
        ("Atlantic Salmon Fillets", "Ocean Catch", 12.99, "1 lb", "gluten-free high-protein keto dairy-free", "fish", "tray", "#fb923c", "salmon fish seafood omega-3", "lemons rice"),
        ("Raw Shrimp", "Ocean Catch", 10.99, "1 lb", "gluten-free high-protein keto dairy-free", "shellfish", "bag", "#fdba74", "shrimp prawns seafood", "garlic pasta"),
        ("Tilapia Fillets", "Ocean Catch", 8.49, "1 lb", "gluten-free high-protein keto dairy-free", "fish", "tray", "#fed7aa", "tilapia white fish", "lemons"),
        ("Canned Tuna in Water", "Ocean Catch", 1.49, "5 oz", "gluten-free high-protein dairy-free", "fish", "can", "#60a5fa", "tuna canned fish", "bread mayo"),
        ("Deli Sliced Turkey", "Harvest Farm", 4.99, "8 oz", "gluten-free high-protein dairy-free", "", "pack", "#fde2e4", "turkey slices deli sandwich", "bread cheese"),
        ("Plant-Based Burger Patties", "Nature's Basket", 6.99, "2 ct", "vegan dairy-free high-protein", "soy", "box", "#78350f", "veggie burger meatless plant protein", "buns"),
    ],
    "Pasta, Rice & Grains": [
        ("Artisan Pasta", "Bella Cucina", 3.80, "500 g", "vegan", "wheat", "box", "#fde68a", "pasta penne italian", "parmesan sauce"),
        ("Spaghetti", "Bella Cucina", 1.99, "1 lb", "vegan", "wheat", "box", "#facc15", "spaghetti pasta noodles", "marinara meatballs"),
        ("Fettuccine", "Bella Cucina", 2.29, "1 lb", "vegan", "wheat", "box", "#fcd34d", "fettuccine pasta alfredo", "heavy cream parmesan"),
        ("Lasagna Sheets", "Bella Cucina", 2.99, "1 lb", "vegan", "wheat", "box", "#fbbf24", "lasagna noodles pasta", "ricotta mozzarella beef"),
        ("Gluten-Free Penne", "Nature's Basket", 3.49, "12 oz", "vegan gluten-free", "", "box", "#fef08a", "gluten free pasta penne rice pasta", "sauce"),
        ("Whole Wheat Rotini", "Bella Cucina", 2.49, "1 lb", "vegan", "wheat", "box", "#d6a75c", "rotini whole wheat pasta", ""),
        ("Jasmine Rice", "Golden Mill", 8.00, "2 kg", "vegan gluten-free", "", "bag", "#f8fafc", "jasmine rice", "chicken vegetables"),
        ("Long Grain White Rice", "Golden Mill", 3.49, "2 lb", "vegan gluten-free", "", "bag", "#f1f5f9", "white rice", "beans"),
        ("Brown Rice", "Golden Mill", 3.99, "2 lb", "vegan gluten-free", "", "bag", "#b08968", "brown rice whole grain", ""),
        ("Basmati Rice", "Golden Mill", 6.99, "4 lb", "vegan gluten-free", "", "bag", "#fefce8", "basmati rice", "curry"),
        ("Quinoa", "Nature's Basket", 5.49, "16 oz", "vegan gluten-free high-protein", "", "bag", "#e7d7b1", "quinoa grain protein", "vegetables"),
        ("Rolled Oats", "Morning Glow", 3.99, "42 oz", "vegan", "", "box", "#d6bc8a", "oats oatmeal porridge", "bananas berries"),
        ("Couscous", "Golden Mill", 2.99, "10 oz", "vegan", "wheat", "box", "#f3d9a4", "couscous", ""),
        ("Egg Noodles", "Golden Mill", 2.49, "12 oz", "vegetarian", "wheat eggs", "bag", "#fde047", "egg noodles soup", "chicken"),
        ("Ramen Noodles", "Golden Mill", 0.69, "3 oz", "vegan", "wheat soy", "pack", "#f97316", "ramen instant noodles", "eggs"),
        ("All-Purpose Flour", "Golden Mill", 3.29, "5 lb", "vegan", "wheat", "bag", "#fafaf9", "flour baking", "sugar butter eggs"),
    ],
    "Pantry": [
        ("Marinara Sauce", "Bella Cucina", 3.99, "24 oz", "vegan gluten-free", "", "jar", "#b91c1c", "marinara pasta sauce tomato sauce", "spaghetti"),
        ("Alfredo Sauce", "Bella Cucina", 3.79, "15 oz", "vegetarian gluten-free", "milk", "jar", "#fef3c7", "alfredo sauce white sauce", "fettuccine chicken"),
        ("Basil Pesto", "Bella Cucina", 4.99, "6 oz", "vegetarian gluten-free", "milk tree-nuts", "jar", "#4d7c0f", "pesto basil sauce", "pasta"),
        ("Crushed Tomatoes", "Bella Cucina", 1.99, "28 oz", "vegan gluten-free", "", "can", "#dc2626", "crushed tomatoes canned", "lasagna pasta"),
        ("Tomato Paste", "Bella Cucina", 0.99, "6 oz", "vegan gluten-free", "", "can", "#991b1b", "tomato paste", ""),
        ("Extra Virgin Olive Oil", "Bella Cucina", 8.99, "500 ml", "vegan gluten-free keto", "", "bottle", "#65a30d", "olive oil cooking oil", "pasta salad"),
        ("Vegetable Oil", "Golden Mill", 4.49, "48 fl oz", "vegan gluten-free", "", "bottle", "#fde047", "vegetable oil cooking oil frying", ""),
        ("Black Beans", "Sol Cocina", 1.19, "15 oz", "vegan gluten-free high-protein", "", "can", "#1f2937", "black beans canned", "rice tortillas"),
        ("Chickpeas", "Nature's Basket", 1.29, "15 oz", "vegan gluten-free high-protein", "", "can", "#d4a373", "chickpeas garbanzo canned", ""),
        ("Chunky Salsa", "Sol Cocina", 3.49, "16 oz", "vegan gluten-free", "", "jar", "#ef4444", "salsa dip", "tortilla chips"),
        ("Taco Seasoning", "Spice Route", 1.29, "1 oz", "vegan gluten-free", "", "pack", "#c2410c", "taco seasoning spice mix", "ground beef tortillas"),
        ("Sea Salt", "Spice Route", 2.49, "26 oz", "vegan gluten-free keto", "", "jar", "#f8fafc", "salt", ""),
        ("Black Pepper", "Spice Route", 3.99, "4 oz", "vegan gluten-free keto", "", "jar", "#292524", "pepper ground black pepper spice", ""),
        ("Italian Seasoning", "Spice Route", 2.99, "1 oz", "vegan gluten-free", "", "jar", "#4d7c0f", "italian herbs oregano seasoning", "pasta"),
        ("Garlic Powder", "Spice Route", 2.79, "3 oz", "vegan gluten-free", "", "jar", "#e7e5e4", "garlic powder spice", ""),
        ("Chicken Broth", "Harvest Farm", 2.49, "32 oz", "gluten-free dairy-free", "", "carton", "#fbbf24", "chicken stock broth soup", "noodles"),
        ("Vegetable Broth", "Nature's Basket", 2.49, "32 oz", "vegan gluten-free", "", "carton", "#84cc16", "vegetable stock broth soup", ""),
        ("Granulated Sugar", "Golden Mill", 3.49, "4 lb", "vegan gluten-free", "", "bag", "#fafafa", "sugar baking", "flour"),
        ("Pure Honey", "Morning Glow", 6.99, "12 oz", "vegetarian gluten-free", "", "jar", "#f59e0b", "honey sweetener", "yogurt tea"),
        ("Creamy Peanut Butter", "Morning Glow", 3.49, "16 oz", "vegan gluten-free high-protein", "peanuts", "jar", "#b45309", "peanut butter", "bread bananas"),
        ("Strawberry Jam", "Morning Glow", 3.29, "18 oz", "vegan gluten-free", "", "jar", "#be123c", "jam jelly preserves", "bread peanut butter"),
        ("Soy Sauce", "Spice Route", 2.99, "15 fl oz", "vegan dairy-free", "soy wheat", "bottle", "#451a03", "soy sauce asian", "rice"),
        ("Coconut Milk", "Nature's Basket", 2.29, "13.5 oz", "vegan gluten-free dairy-free keto", "", "can", "#f5f5f4", "coconut milk curry", "rice"),
        ("Mayonnaise", "Harvest Farm", 3.99, "30 oz", "vegetarian gluten-free", "eggs", "jar", "#fefce8", "mayo mayonnaise", "bread tuna"),
        ("Yellow Mustard", "Harvest Farm", 1.49, "14 oz", "vegan gluten-free", "", "bottle", "#facc15", "mustard condiment", "hot dogs"),
        ("Tomato Ketchup", "Harvest Farm", 2.79, "32 oz", "vegan gluten-free", "", "bottle", "#dc2626", "ketchup condiment", "fries burgers"),
    ],
    "Breakfast": [
        ("Honey Oat Granola", "Morning Glow", 4.49, "12 oz", "vegetarian", "wheat tree-nuts", "bag", "#d97706", "granola cereal", "yogurt milk"),
        ("Gluten-Free Granola", "Nature's Basket", 5.99, "11 oz", "vegan gluten-free", "tree-nuts", "bag", "#ca8a04", "granola gluten free cereal", "yogurt"),
        ("Corn Flakes Cereal", "Morning Glow", 3.99, "18 oz", "vegan", "", "box", "#f59e0b", "cereal corn flakes", "milk bananas"),
        ("Whole Grain O's Cereal", "Morning Glow", 4.29, "18 oz", "vegan low-sugar", "", "box", "#eab308", "cereal oats whole grain", "milk"),
        ("Pancake & Waffle Mix", "Morning Glow", 3.29, "32 oz", "vegetarian", "wheat milk", "box", "#fbbf24", "pancake mix waffle", "maple syrup eggs"),
        ("Pure Maple Syrup", "Morning Glow", 7.99, "12 fl oz", "vegan gluten-free", "", "bottle", "#92400e", "maple syrup", "pancake mix"),
        ("Instant Oatmeal Variety", "Morning Glow", 3.99, "10 ct", "vegetarian", "", "box", "#d4a373", "oatmeal instant breakfast", "bananas"),
        ("Ground Coffee Medium Roast", "Bean & Brew", 8.99, "12 oz", "vegan gluten-free", "", "bag", "#422006", "coffee ground", "milk cream"),
        ("Coffee Pods Dark Roast", "Bean & Brew", 9.99, "24 ct", "vegan gluten-free", "", "box", "#292524", "coffee pods capsules", ""),
        ("Black Tea Bags", "Bean & Brew", 3.49, "100 ct", "vegan gluten-free", "", "box", "#7f1d1d", "tea black tea bags", "honey milk"),
        ("Green Tea Bags", "Bean & Brew", 3.99, "40 ct", "vegan gluten-free", "", "box", "#65a30d", "green tea", "honey"),
        ("Protein Pancake Mix", "Morning Glow", 6.49, "20 oz", "vegetarian high-protein", "wheat milk eggs", "box", "#f59e0b", "protein pancakes", "maple syrup"),
    ],
    "Snacks": [
        ("Gluten-Free Pretzels", "Crunch Co.", 4.29, "8 oz", "vegan gluten-free", "", "bag", "#d97706", "pretzels gluten free snack", "hummus"),
        ("Sea Salt Potato Chips", "Crunch Co.", 3.99, "8 oz", "vegan gluten-free", "", "bag", "#fde047", "potato chips crisps snack", "salsa"),
        ("Tortilla Chips", "Sol Cocina", 3.49, "13 oz", "vegan gluten-free", "", "bag", "#facc15", "tortilla chips nachos", "salsa guacamole"),
        ("Rice Cakes Lightly Salted", "Crunch Co.", 2.99, "4.5 oz", "vegan gluten-free low-sugar", "", "bag", "#f5f5f4", "rice cakes gluten free snack", "peanut butter"),
        ("Mixed Nuts Unsalted", "Crunch Co.", 8.99, "16 oz", "vegan gluten-free keto high-protein", "tree-nuts peanuts", "jar", "#a16207", "nuts mixed almonds cashews snack", ""),
        ("Roasted Almonds", "Crunch Co.", 6.99, "12 oz", "vegan gluten-free keto high-protein", "tree-nuts", "bag", "#92400e", "almonds nuts snack", ""),
        ("Classic Hummus", "Nature's Basket", 3.99, "10 oz", "vegan gluten-free", "sesame", "tub", "#e7c9a0", "hummus dip", "pita carrots"),
        ("Dark Chocolate Bar 70%", "Cocoa Lane", 3.49, "3.5 oz", "vegan gluten-free", "", "bar", "#3f1d0b", "dark chocolate", ""),
        ("Milk Chocolate Bar", "Cocoa Lane", 2.49, "3.5 oz", "vegetarian", "milk soy", "bar", "#7c2d12", "milk chocolate candy", ""),
        ("Chocolate Chip Cookies", "Baker's Choice", 3.99, "13 oz", "vegetarian", "wheat milk eggs soy", "pack", "#92400e", "cookies chocolate chip", "milk"),
        ("Gluten-Free Oat Cookies", "Nature's Basket", 4.99, "8 oz", "vegan gluten-free", "", "pack", "#d6a75c", "cookies gluten free", ""),
        ("Popcorn Sea Salt", "Crunch Co.", 3.29, "6 oz", "vegan gluten-free", "", "bag", "#fef08a", "popcorn snack", ""),
        ("Protein Bars Variety", "Fit Fuel", 9.99, "6 ct", "gluten-free high-protein", "milk peanuts", "box", "#0f766e", "protein bars snack", ""),
        ("Fruit Snacks", "Crunch Co.", 2.99, "10 ct", "vegetarian gluten-free", "", "box", "#ec4899", "fruit snacks gummies kids", ""),
        ("Cheese Crackers", "Crunch Co.", 3.49, "7 oz", "vegetarian", "wheat milk", "box", "#f97316", "crackers cheese snack", ""),
        ("Whole Grain Crackers", "Crunch Co.", 3.29, "9 oz", "vegan", "wheat", "box", "#b45309", "crackers whole grain", "cheese"),
        ("Trail Mix", "Crunch Co.", 5.99, "14 oz", "vegetarian gluten-free", "tree-nuts peanuts milk", "bag", "#78350f", "trail mix nuts raisins", ""),
        ("Seaweed Snacks", "Nature's Basket", 3.99, "6 ct", "vegan gluten-free keto", "", "pack", "#14532d", "seaweed snack low calorie", ""),
    ],
    "Beverages": [
        ("Spring Water", "Pure Spring", 4.99, "24 x 16.9 oz", "vegan gluten-free", "", "bottle", "#38bdf8", "water bottled", ""),
        ("Sparkling Water Lime", "Pure Spring", 4.49, "8 x 12 oz", "vegan gluten-free keto low-sugar", "", "can", "#a3e635", "sparkling water seltzer", ""),
        ("Orange Juice No Pulp", "Sunny Fields", 4.49, "52 fl oz", "vegan gluten-free", "", "carton", "#fb923c", "orange juice oj", "breakfast"),
        ("Apple Juice", "Sunny Fields", 3.49, "64 fl oz", "vegan gluten-free", "", "bottle", "#fbbf24", "apple juice", ""),
        ("Cola", "Fizz", 6.49, "12 x 12 oz", "vegan gluten-free", "", "can", "#991b1b", "cola soda soft drink", "pizza"),
        ("Diet Cola", "Fizz", 6.49, "12 x 12 oz", "vegan gluten-free keto low-sugar", "", "can", "#a8a29e", "diet cola soda zero sugar", ""),
        ("Lemon-Lime Soda", "Fizz", 6.49, "12 x 12 oz", "vegan gluten-free", "", "can", "#84cc16", "lemon lime soda", ""),
        ("Iced Tea Unsweetened", "Bean & Brew", 2.99, "64 fl oz", "vegan gluten-free low-sugar", "", "bottle", "#b45309", "iced tea", "lemons"),
        ("Cold Brew Coffee", "Bean & Brew", 4.99, "32 fl oz", "vegan gluten-free", "", "bottle", "#292524", "cold brew iced coffee", "oat milk"),
        ("Sports Drink Variety", "Fit Fuel", 7.99, "12 x 20 oz", "vegan gluten-free", "", "bottle", "#2563eb", "sports drink electrolytes", ""),
        ("Coconut Water", "Nature's Basket", 3.99, "33.8 fl oz", "vegan gluten-free", "", "carton", "#f5f5f4", "coconut water hydration", ""),
        ("Kombucha Ginger", "Nature's Basket", 3.49, "16 fl oz", "vegan gluten-free organic", "", "bottle", "#d97706", "kombucha probiotic", ""),
        ("Protein Shake Chocolate", "Fit Fuel", 8.99, "4 x 11 fl oz", "gluten-free high-protein", "milk", "bottle", "#451a03", "protein shake", ""),
        ("Lemonade", "Sunny Fields", 3.29, "52 fl oz", "vegan gluten-free", "", "carton", "#fde047", "lemonade", ""),
        ("Energy Drink", "Fit Fuel", 2.79, "16 fl oz", "vegan gluten-free", "", "can", "#16a34a", "energy drink caffeine", ""),
        ("Chocolate Milk", "Green Valley", 2.99, "half gal", "vegetarian gluten-free", "milk", "carton", "#78350f", "chocolate milk kids", ""),
    ],
    "Frozen": [
        ("Frozen Mixed Vegetables", "Frosty Farms", 2.49, "16 oz", "vegan gluten-free", "", "bag", "#22c55e", "frozen vegetables peas carrots corn", "rice"),
        ("Frozen Broccoli Florets", "Frosty Farms", 2.29, "12 oz", "vegan gluten-free keto", "", "bag", "#15803d", "frozen broccoli", ""),
        ("Frozen Mixed Berries", "Frosty Farms", 4.99, "32 oz", "vegan gluten-free", "", "bag", "#7e22ce", "frozen berries smoothie", "yogurt"),
        ("Margherita Pizza", "Bella Cucina", 6.99, "16 oz", "vegetarian", "wheat milk", "box", "#dc2626", "frozen pizza margherita", "cola"),
        ("Gluten-Free Cheese Pizza", "Nature's Basket", 8.99, "14 oz", "vegetarian gluten-free", "milk eggs", "box", "#f97316", "gluten free pizza frozen", ""),
        ("Vanilla Ice Cream", "Frosty Farms", 4.99, "48 oz", "vegetarian gluten-free", "milk", "tub", "#fef9c3", "ice cream dessert vanilla", "berries"),
        ("Dairy-Free Chocolate Frozen Dessert", "Nature's Basket", 5.99, "16 oz", "vegan dairy-free gluten-free", "", "tub", "#451a03", "vegan ice cream dairy free dessert", ""),
        ("Frozen French Fries", "Frosty Farms", 3.49, "32 oz", "vegan gluten-free", "", "bag", "#facc15", "fries french fries frozen potatoes", "ketchup burgers"),
        ("Chicken Nuggets", "Frosty Farms", 7.99, "29 oz", "high-protein", "wheat", "bag", "#f59e0b", "chicken nuggets kids frozen", "ketchup"),
        ("Veggie Fried Rice", "Frosty Farms", 3.99, "20 oz", "vegan", "soy wheat", "bag", "#fbbf24", "fried rice frozen meal", ""),
    ],
    "Household": [
        ("Dish Soap Lemon", "CleanHome", 3.49, "24 fl oz", "", "", "bottle", "#facc15", "dish soap washing up liquid", "sponges"),
        ("Laundry Detergent", "CleanHome", 11.99, "64 loads", "", "", "bottle", "#2563eb", "laundry detergent", ""),
        ("All-Purpose Cleaner", "CleanHome", 3.99, "32 fl oz", "", "", "bottle", "#06b6d4", "cleaner spray kitchen bathroom", "paper towels"),
        ("Paper Towels", "CleanHome", 8.99, "6 rolls", "", "", "pack", "#f8fafc", "paper towels kitchen roll", ""),
        ("Toilet Paper", "CleanHome", 9.99, "12 rolls", "", "", "pack", "#e0f2fe", "toilet paper tissue", ""),
        ("Trash Bags 13 Gal", "CleanHome", 7.99, "40 ct", "", "", "box", "#1f2937", "trash bags garbage bags", ""),
        ("Sponges", "CleanHome", 2.99, "6 ct", "", "", "pack", "#fde047", "sponges scrub", "dish soap"),
        ("Aluminum Foil", "CleanHome", 4.49, "75 sq ft", "", "", "box", "#d4d4d8", "foil aluminium", ""),
        ("Dishwasher Pods", "CleanHome", 12.99, "45 ct", "", "", "tub", "#3b82f6", "dishwasher tablets pods", ""),
        ("Zip Storage Bags", "CleanHome", 3.99, "40 ct", "", "", "box", "#93c5fd", "storage bags sandwich bags", ""),
    ],
    "Personal Care": [
        ("Fluoride Toothpaste", "FreshCare", 3.49, "4.8 oz", "", "", "tube", "#22d3ee", "toothpaste", "toothbrush"),
        ("Soft Toothbrushes", "FreshCare", 3.99, "2 ct", "", "", "pack", "#38bdf8", "toothbrush", "toothpaste"),
        ("Moisturizing Body Wash", "FreshCare", 5.99, "18 fl oz", "", "", "bottle", "#c4b5fd", "body wash shower gel", ""),
        ("Bar Soap", "FreshCare", 4.49, "4 ct", "", "", "box", "#fbcfe8", "soap bar", ""),
        ("Shampoo Daily Care", "FreshCare", 6.49, "13.5 fl oz", "", "", "bottle", "#a78bfa", "shampoo hair", "conditioner"),
        ("Conditioner Daily Care", "FreshCare", 6.49, "13.5 fl oz", "", "", "bottle", "#f0abfc", "conditioner hair", "shampoo"),
        ("Hand Soap Refill", "FreshCare", 4.99, "34 fl oz", "", "", "bottle", "#86efac", "hand soap", ""),
        ("Deodorant Fresh Scent", "FreshCare", 4.99, "2.6 oz", "", "", "tube", "#e0e7ff", "deodorant", ""),
    ],
}

PREFIX = {"Dairy & Eggs": "DAI", "Bakery": "BAK", "Fruits": "FRU", "Vegetables": "VEG", "Meat & Seafood": "MEA",
          "Pasta, Rice & Grains": "GRA", "Pantry": "PAN", "Breakfast": "BRK", "Snacks": "SNK", "Beverages": "BEV",
          "Frozen": "FRZ", "Household": "HOM", "Personal Care": "PER"}
OUT_OF_STOCK = {"Raspberries", "Basmati Rice", "Kombucha Ginger", "Cold Brew Coffee", "Gluten-Free Cheese Pizza"}


def describe(name, brand, cat, size, tags, allergens):
    parts = [f"{name} from {brand}" if brand != "Fresh" else f"Fresh {name.lower()}", f"({size})."]
    nice = [t.replace("-", " ") for t in tags.split() if t in ("organic", "gluten-free", "vegan", "dairy-free", "high-protein", "keto", "low-sugar")]
    if nice:
        parts.append("It is " + ", ".join(nice) + ".")
    if allergens:
        parts.append("Contains " + ", ".join(a.replace("-", " ") for a in allergens.split()) + ".")
    return " ".join(parts)


def svg(name, shape, color):
    """A simple product illustration as an SVG (vector) image."""
    from html import escape
    lines = [""]
    for w in name.split():  # wrap on whole words: two lines of about 17 characters
        if len(lines[-1]) + len(w) + 1 > 17 and lines[-1]:
            lines.append(w)
        else:
            lines[-1] = (lines[-1] + " " + w).strip()
    label1, label2 = escape(lines[0]), escape(" ".join(lines[1:]))[:20]
    ink = "#1f2937"
    shapes = {
        "carton": f'<path d="M70 60 L130 60 L140 85 L140 200 L60 200 L60 85 Z" fill="{color}" stroke="{ink}" stroke-width="3"/><path d="M70 60 L100 40 L130 60" fill="{color}" stroke="{ink}" stroke-width="3"/>',
        "bottle": f'<rect x="88" y="30" width="24" height="28" rx="4" fill="{ink}"/><path d="M80 58 h40 v20 q14 10 14 30 v92 h-68 v-92 q0-20 14-30 z" fill="{color}" stroke="{ink}" stroke-width="3"/>',
        "jar": f'<rect x="66" y="52" width="68" height="18" rx="4" fill="{ink}"/><rect x="58" y="70" width="84" height="130" rx="14" fill="{color}" stroke="{ink}" stroke-width="3"/>',
        "can": f'<rect x="60" y="60" width="80" height="140" rx="10" fill="{color}" stroke="{ink}" stroke-width="3"/><ellipse cx="100" cy="62" rx="40" ry="8" fill="#e5e7eb" stroke="{ink}" stroke-width="3"/>',
        "box": f'<rect x="50" y="55" width="100" height="145" rx="6" fill="{color}" stroke="{ink}" stroke-width="3"/><rect x="50" y="55" width="100" height="22" fill="{ink}" opacity=".15"/>',
        "bag": f'<path d="M55 70 q45 -20 90 0 l10 130 h-110 z" fill="{color}" stroke="{ink}" stroke-width="3"/><path d="M60 70 q40 -14 80 0" fill="none" stroke="{ink}" stroke-width="3"/>',
        "tub": f'<path d="M55 90 h90 l-10 110 h-70 z" fill="{color}" stroke="{ink}" stroke-width="3"/><rect x="50" y="78" width="100" height="16" rx="6" fill="{ink}" opacity=".85"/>',
        "loaf": f'<path d="M45 150 q0 -70 55 -70 q55 0 55 70 v45 h-110 z" fill="{color}" stroke="{ink}" stroke-width="3"/><path d="M70 110 l10 -10 M95 105 l10 -10 M120 110 l10 -10" stroke="{ink}" stroke-width="3"/>',
        "fruit": f'<circle cx="100" cy="130" r="58" fill="{color}" stroke="{ink}" stroke-width="3"/><path d="M100 72 q4 -18 18 -24" stroke="#166534" stroke-width="5" fill="none"/><ellipse cx="120" cy="56" rx="14" ry="7" fill="#22c55e"/>',
        "veg": f'<ellipse cx="100" cy="135" rx="60" ry="52" fill="{color}" stroke="{ink}" stroke-width="3"/><path d="M90 85 q10 -30 25 -36 M100 85 q-5 -25 -20 -34" stroke="#166534" stroke-width="5" fill="none"/>',
        "bunch": f'<path d="M100 200 v-70" stroke="#166534" stroke-width="6"/><circle cx="75" cy="105" r="32" fill="{color}" stroke="{ink}" stroke-width="3"/><circle cx="125" cy="105" r="32" fill="{color}" stroke="{ink}" stroke-width="3"/><circle cx="100" cy="80" r="34" fill="{color}" stroke="{ink}" stroke-width="3"/>',
        "tray": f'<rect x="40" y="110" width="120" height="70" rx="12" fill="#e5e7eb" stroke="{ink}" stroke-width="3"/><ellipse cx="100" cy="135" rx="48" ry="26" fill="{color}" stroke="{ink}" stroke-width="3"/>',
        "pack": f'<rect x="45" y="65" width="110" height="130" rx="12" fill="{color}" stroke="{ink}" stroke-width="3"/><path d="M45 85 h110" stroke="{ink}" stroke-width="3" stroke-dasharray="6 6"/>',
        "block": f'<path d="M50 110 l50 -30 l50 30 v70 h-100 z" fill="{color}" stroke="{ink}" stroke-width="3"/><circle cx="80" cy="140" r="7" fill="{ink}" opacity=".2"/><circle cx="115" cy="155" r="9" fill="{ink}" opacity=".2"/>',
        "bar": f'<rect x="40" y="90" width="120" height="80" rx="8" fill="{color}" stroke="{ink}" stroke-width="3"/><path d="M80 90 v80 M120 90 v80 M40 130 h120" stroke="{ink}" stroke-width="2" opacity=".4"/>',
        "tube": f'<path d="M70 40 h60 l-8 150 h-44 z" fill="{color}" stroke="{ink}" stroke-width="3"/><rect x="84" y="190" width="32" height="14" rx="3" fill="{ink}"/>',
    }
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 240" role="img" aria-label="{escape(name)}">'
            f'<rect width="200" height="240" fill="#ffffff"/>{shapes[shape]}'
            f'<rect x="24" y="206" width="152" height="0" fill="none"/>'
            f'<text x="100" y="222" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" font-weight="700" fill="{ink}">{label1}</text>'
            f'<text x="100" y="236" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="#4b5563">{label2}</text></svg>')


def main():
    rng = random.Random(7)
    products, images = [], ROOT / "data" / "images"
    images.mkdir(parents=True, exist_ok=True)
    for cat, rows in CATALOG.items():
        for i, (name, brand, price, size, tags, allergens, shape, color, words, pairs) in enumerate(rows, 1):
            pid = f"{PREFIX[cat]}-{i:03d}"
            (images / f"{pid}.svg").write_text(svg(name, shape, color), encoding="utf-8")
            products.append({
                "id": pid, "name": name, "brand": brand, "category": cat, "price": price, "size": size,
                "description": describe(name, brand, cat, size, tags, allergens),
                "dietary": tags.split(), "allergens": allergens.split(), "keywords": words,
                "pairs_with": pairs.split(), "stock": 0 if name in OUT_OF_STOCK else rng.randint(6, 80),
                "rating": round(rng.uniform(3.8, 4.9), 1), "image": f"/images/{pid}.svg",
            })
    assert len(products) == 200, len(products)
    (ROOT / "data" / "products.json").write_text(json.dumps(products, indent=1), encoding="utf-8")
    print(f"Wrote {len(products)} products and {len(products)} SVG images.")


if __name__ == "__main__":
    main()
