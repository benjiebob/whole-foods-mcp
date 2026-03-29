---
name: grocery-order
description: Build and manage a Whole Foods grocery order using the Whole Foods MCP tools. Use when the user wants to add groceries, build a shopping list, reorder from a previous order, or manage their Whole Foods cart.
---

# Whole Foods Grocery Ordering

## Workflow

### 1. Search → Evaluate → Add (never auto-add blindly)

Always use a two-step process:

1. **Search** with `search_whole_foods` using simple queries
2. **Evaluate** the results yourself — pick the right item based on what the user asked for
3. **Add** with `add_to_cart` using the specific ASIN you chose

Never rely on keyword matching to pick items automatically. You must judge whether a search result is actually what the user wants. For example:
- "banana" search → banana bread, banana chips, actual bananas — only add the actual bananas
- "malt vinegar" search → champagne vinegar, apple cider vinegar — none of these are malt vinegar, report unavailable

### 2. Search tips

- **Use simple 1-2 word queries.** This is critical for produce.
  - Good: `banana`, `nectarine`, `apple`, `russet potato`
  - Bad: `organic fuji apple fresh produce`, `fresh peach nectarine plum stone fruit`
- **When an item isn't found, try related items as separate searches.**
  - Peach unavailable → search `nectarine`, then `plum` separately
  - Fuji apple unavailable → search `apple` to see what varieties exist
- **`can_add_to_cart=false` does NOT mean unavailable.** Weight-based items (produce, meat, deli) show false in search results but can still be added — `add_to_cart` handles this via the product page fallback.
- **Only HTTP 400 from `add_to_cart` means genuinely unavailable at this store.**

### 3. Bags vs individual items

Pay close attention to whether search results are bags/multipacks or individual items. If the user asks for "1 onion", don't add a 3lb onion bag. If they ask for "4 potatoes", add 4 individual potatoes, not a 5lb bag.

### 4. Substitutions

When an item is unavailable (HTTP 400):
- Search for close alternatives using simple queries
- Present alternatives to the user and let them decide
- Never silently substitute — always tell the user what you're swapping and why
- If nothing reasonable exists, report it as unavailable

### 5. Quantity management

- Always verify quantities after adding by checking `view_cart`
- The `remove_from_cart` tool removes ALL of an item — to fix quantities, remove then re-add at the correct count
- Weight-based items added via product page may need fresh CSRF tokens per unit — the tool handles this automatically

### 6. Store switching

- Different Whole Foods locations have different inventory
- Switching stores in the browser may drop items from the cart
- After a store switch, always `view_cart` to check what survived and re-add anything that was dropped

## Session setup

If `add_to_cart` fails with session errors or "No ATC" for everything:
1. Call `login` to open the browser
2. User logs into Amazon and selects their Whole Foods store
3. Call `save_session` to persist
4. Never run standalone scripts that write to `.browser_state/state.json` — this can corrupt the session

## Common pitfalls

| Pitfall | Fix |
|---------|-----|
| Search returns irrelevant results | Shorten query to 1-2 words |
| `can_add_to_cart=false` assumed unavailable | Try `add_to_cart` anyway — product page fallback works |
| Wrong item added (canned peaches for fresh) | Always evaluate search results before adding |
| Quantity wrong after multiple add attempts | Use `view_cart` to audit, remove and re-add if needed |
| All items fail after store switch | Re-check cart, re-add dropped items |
| Item was available but now returns 400 | Store inventory is live — items can go out of stock during a session |
