---
name: grocery-order
description: Build and manage a Whole Foods grocery order using the Whole Foods MCP tools. Use when the user wants to add groceries, build a shopping list, reorder from a previous order, or manage their Whole Foods cart.
---

# Whole Foods Grocery Ordering

## Tools overview

| Tool | Purpose | When to use |
|------|---------|-------------|
| `search_whole_foods` | Find products by keyword | Always the first step — returns ASIN, title, price, size |
| `get_product_details` | Deep dive into a specific product | When you need ingredients, allergens, exact weight, or to see the product image |
| `add_to_cart` | Add a product by ASIN | After confirming the right product via search (and optionally details) |
| `view_cart` | See what's currently in the cart | To verify adds, audit quantities, or show the user their cart |
| `remove_from_cart` | Remove a product by ASIN | When the user wants to remove a specific item |
| `clear_cart` | Empty the entire cart | When the user wants to start fresh |
| `login` | Open browser for Amazon sign-in | Only on first use or when the session has expired |
| `save_session` | Persist login cookies to disk | Immediately after the user finishes logging in |

## Core workflow: Search → Evaluate → Add

### Step 1: Search

Call `search_whole_foods` with a simple 1-2 word query. This returns up to 10 results with ASIN, title, price, and size — enough to pick the right item in most cases.

**Search tips:**

- Keep queries short. `banana` not `organic fresh banana produce`.
- For produce and meat, 1 word is best. For packaged goods, brand + product works.
- If nothing relevant comes back, try a broader or alternative term.

### Step 2: Evaluate

Look at the search results and decide which item matches what the user wants. **Never add blindly.**

- "banana" search → banana bread, banana chips, actual bananas → only add the actual bananas
- "malt vinegar" search → champagne vinegar, apple cider vinegar → none match, report unavailable

**When search results aren't enough to decide**, call `get_product_details` with the ASIN. This returns:

- Full description, feature bullets, ingredients, allergens
- Exact size/weight info
- A **screenshot** of the product page (so you can see the actual product image)
- Image URL

Use `get_product_details` when:

- Two search results look similar and you need to distinguish them
- The user asked about ingredients or allergens
- The title is ambiguous (e.g. "Organic Apple" — which variety?)
- You want to visually confirm the product before adding

Do NOT call `get_product_details` for every search result — it's slower (loads a full product page + screenshot). Use it selectively.

### Step 3: Add

Call `add_to_cart` with just the ASIN and quantity. The tool fetches the product page directly for a fresh add-to-cart token, so it works for all item types including weight-based produce and meat.

- `can_add_to_cart=false` in search results does NOT mean unavailable — `add_to_cart` handles this.
- Only HTTP 400 from `add_to_cart` means genuinely unavailable at the store.

## Parallel execution

Claude can call tools in parallel using agents. The recommended pattern for adding multiple items:

```
User: "Add bananas, eggs, and oat milk"

Step 1 — Search in parallel:
  Agent 1: search_whole_foods("banana")
  Agent 2: search_whole_foods("eggs")
  Agent 3: search_whole_foods("oat milk")

Step 2 — Evaluate all results, pick the right ASINs

Step 3 — Add in parallel:
  Agent 1: add_to_cart(asin="B07FYYKKQK", quantity=1)
  Agent 2: add_to_cart(asin="B07NQDTD7D", quantity=1)
  Agent 3: add_to_cart(asin="B08XYZ1234", quantity=1)
```

Each `add_to_cart` call creates its own browser page, so there are no conflicts. Cap at 6 concurrent agents to avoid Amazon rate limiting.

## Bags vs individual items

Pay close attention to whether search results are bags/multipacks or individual items:

- User asks for "1 onion" → add 1 individual onion, not a 3lb bag
- User asks for "4 potatoes" → add 4 individual potatoes (quantity=4), not a 5lb bag

## Substitutions

When an item is unavailable (HTTP 400):

- Search for close alternatives using simple queries
- Present alternatives to the user and let them decide
- Never silently substitute — always tell the user what you're swapping and why
- If nothing reasonable exists, report it as unavailable

## Quantity management

- Verify quantities after adding by checking `view_cart`
- `remove_from_cart` removes ALL of an item — to fix quantities, remove then re-add at the correct count

## Session setup

If tools fail with session errors or "no add-to-cart" for everything:

1. Call `login` to open the browser
2. User logs into Amazon and selects their Whole Foods store
3. Call `save_session` to persist
4. Resume shopping

## Common pitfalls

| Pitfall | Fix |
|---------|-----|
| Search returns irrelevant results | Shorten query to 1-2 words |
| `can_add_to_cart=false` assumed unavailable | Call `add_to_cart` anyway — it fetches the product page directly |
| Wrong item added (canned peaches for fresh) | Always evaluate search results before adding |
| Quantity wrong after multiple add attempts | Use `view_cart` to audit, remove and re-add if needed |
| Item was available but now returns 400 | Store inventory is live — items can go out of stock during a session |
