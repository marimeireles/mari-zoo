"""Helper functions for programmatic evaluation.

These functions are called from task configs using the `func:` prefix.
Example: "locator": "func:shopping_get_price(page)"
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from playwright.async_api import Page


# Zoo URLs
SHOPPING_URL = "https://onestopshop.zoo"
SHOPPING_ADMIN_URL = "https://onestopshop.zoo/admin"

# Default admin credentials for Zoo services
ZOO_ADMIN_USER = "admin"
ZOO_ADMIN_PASS = "admin123"

# Registry of helper functions
HELPER_FUNCTIONS: dict[str, callable] = {}


def helper(fn):
    """Decorator to register a helper function."""
    HELPER_FUNCTIONS[fn.__name__] = fn
    return fn


# --- Shopping Site Helpers ---


@helper
async def shopping_get_auth_token(client: httpx.AsyncClient) -> str:
    """Get admin API token for shopping site."""
    response = await client.post(
        f"{SHOPPING_URL}/rest/default/V1/integration/admin/token",
        json={"username": ZOO_ADMIN_USER, "password": ZOO_ADMIN_PASS},
        headers={"Content-Type": "application/json"},
    )
    return response.json()


@helper
async def shopping_get_latest_order_url(client: httpx.AsyncClient) -> str:
    """Get URL of the most recent order."""
    token = await shopping_get_auth_token(client)
    response = await client.get(
        f"{SHOPPING_URL}/rest/V1/orders",
        params={"searchCriteria[sortOrders][0][field]": "created_at",
                "searchCriteria[sortOrders][0][direction]": "DESC",
                "searchCriteria[pageSize]": 1},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    items = response.json().get("items", [])
    if items:
        order_id = items[0]["entity_id"]
        return f"{SHOPPING_ADMIN_URL}/sales/order/view/order_id/{order_id}/"
    return ""


@helper
async def shopping_get_product_price(page: "Page") -> str:
    """Extract product price from page."""
    return await page.evaluate("""
        () => {
            const el = document.querySelector('.price-wrapper .price');
            return el ? el.textContent.trim() : '';
        }
    """)


@helper
async def shopping_get_num_reviews(page: "Page") -> str:
    """Get number of reviews for a product."""
    return await page.evaluate("""
        () => {
            const el = document.querySelector('.reviews-actions .action.view');
            if (!el) return '0';
            const match = el.textContent.match(/\\d+/);
            return match ? match[0] : '0';
        }
    """)


@helper
async def shopping_get_rating_as_percentage(page: "Page") -> str:
    """Get product rating as percentage."""
    return await page.evaluate("""
        () => {
            const el = document.querySelector('.rating-result');
            if (!el) return '';
            const style = el.querySelector('span').style.width;
            return style.replace('%', '');
        }
    """)


@helper
async def shopping_get_sku_latest_review_author(page: "Page", sku: str = "") -> str:
    """Get author of the latest review for a SKU."""
    return await page.evaluate("""
        () => {
            const review = document.querySelector('.review-item:first-child .review-author');
            return review ? review.textContent.trim() : '';
        }
    """)


@helper
async def shopping_get_sku_latest_review_rating(page: "Page", sku: str = "") -> str:
    """Get rating of the latest review for a SKU."""
    return await page.evaluate("""
        () => {
            const review = document.querySelector('.review-item:first-child .rating-result span');
            if (!review) return '';
            return review.style.width.replace('%', '');
        }
    """)


@helper
async def shopping_get_sku_latest_review_text(page: "Page", sku: str = "") -> str:
    """Get text of the latest review for a SKU."""
    return await page.evaluate("""
        () => {
            const review = document.querySelector('.review-item:first-child .review-content');
            return review ? review.textContent.trim() : '';
        }
    """)


@helper
async def shopping_get_sku_latest_review_title(page: "Page", sku: str = "") -> str:
    """Get title of the latest review for a SKU."""
    return await page.evaluate("""
        () => {
            const review = document.querySelector('.review-item:first-child .review-title');
            return review ? review.textContent.trim() : '';
        }
    """)


@helper
async def shopping_get_order_product_quantity(page: "Page", sku: str) -> str:
    """Get quantity of a product in an order."""
    return await page.evaluate(f"""
        () => {{
            const rows = document.querySelectorAll('.order-items tbody tr');
            for (const row of rows) {{
                const skuCell = row.querySelector('.col-sku');
                if (skuCell && skuCell.textContent.includes('{sku}')) {{
                    const qtyCell = row.querySelector('.col-qty');
                    return qtyCell ? qtyCell.textContent.trim() : '';
                }}
            }}
            return '';
        }}
    """)


@helper
async def shopping_get_order_product_name_list(page: "Page") -> str:
    """Get list of product names in an order."""
    return await page.evaluate("""
        () => {
            const names = [];
            const rows = document.querySelectorAll('.order-items tbody tr');
            for (const row of rows) {
                const nameCell = row.querySelector('.col-product');
                if (nameCell) names.push(nameCell.textContent.trim());
            }
            return names.join(', ');
        }
    """)


# --- Reddit (Postmill) Helpers ---


@helper
async def reddit_get_latest_comment_content_by_username(page: "Page", username: str) -> str:
    """Get the latest comment text by a specific user."""
    return await page.evaluate(f"""
        () => {{
            const comments = document.querySelectorAll('.comment');
            for (const comment of comments) {{
                const author = comment.querySelector('.comment-author');
                if (author && author.textContent.includes('{username}')) {{
                    const body = comment.querySelector('.comment-body');
                    return body ? body.textContent.trim() : '';
                }}
            }}
            return '';
        }}
    """)


@helper
async def reddit_get_post_url(page: "Page") -> str:
    """Get the URL of the current post."""
    return page.url


# --- Generic Helpers ---


@helper
async def get_query_text(page: "Page", selector: str) -> str:
    """Get text content of an element by CSS selector."""
    return await page.evaluate(f"""
        () => {{
            const el = document.querySelector('{selector}');
            return el ? el.textContent.trim() : '';
        }}
    """)


@helper
async def get_query_text_lowercase(page: "Page", selector: str) -> str:
    """Get lowercase text content of an element by CSS selector."""
    text = await get_query_text(page, selector)
    return text.lower()


# --- Function Invocation ---


def parse_func_call(func_str: str) -> tuple[str, list[str]]:
    """Parse a func: string into function name and arguments.

    Example: "shopping_get_price(page)" -> ("shopping_get_price", ["page"])
    """
    match = re.match(r"(\w+)\((.*)\)", func_str)
    if not match:
        return func_str, []

    func_name = match.group(1)
    args_str = match.group(2).strip()

    if not args_str:
        return func_name, []

    # Simple argument parsing (handles strings and identifiers)
    args = []
    for arg in args_str.split(","):
        arg = arg.strip().strip("'\"")
        args.append(arg)

    return func_name, args


async def invoke_helper(
    func_str: str,
    page: "Page" | None = None,
    client: httpx.AsyncClient | None = None,
    context: dict[str, Any] | None = None,
) -> str:
    """Invoke a helper function from a func: string.

    Args:
        func_str: Function call string like "shopping_get_price(page)"
        page: Playwright page object
        client: HTTP client for API calls
        context: Additional context variables

    Returns:
        Result as string
    """
    func_name, args = parse_func_call(func_str)

    if func_name not in HELPER_FUNCTIONS:
        raise ValueError(f"Unknown helper function: {func_name}")

    fn = HELPER_FUNCTIONS[func_name]

    # Build actual arguments
    call_args = []
    for arg in args:
        if arg == "page":
            call_args.append(page)
        elif arg == "client":
            call_args.append(client)
        elif context and arg in context:
            call_args.append(context[arg])
        else:
            call_args.append(arg)

    result = await fn(*call_args)
    return str(result) if result is not None else ""
