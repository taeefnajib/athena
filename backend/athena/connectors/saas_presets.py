"""Ready-made REST settings for popular SaaS apps: base URL, authentication, pagination and endpoints.

Each preset becomes its own connector (``saas_<app>``) and feeds the SaaS Fetch node. They run on dlt's
declarative REST source like the generic REST API connector; nothing is downloaded. Written from each app's
public API documentation; the tests check them against local mock servers that mimic each API's paging and auth.

A paginator is a dlt paginator config, or ``{"type": "has_more", ...}`` for Athena's ``_AthenaHasMorePaginator``.
Paths may contain ``{placeholders}`` filled from the node's parameters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Resource:
    name: str
    path: str
    help: str
    data_selector: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    paginator: dict[str, Any] | None = None  # overrides the preset's


@dataclass(frozen=True)
class Credential:
    name: str
    label: str
    help: str
    secret: bool = False


@dataclass(frozen=True)
class Preset:
    app: str
    label: str
    description: str
    base_url: str                   # may contain {placeholders} filled from credentials (e.g. {subdomain})
    auth: str                       # bearer | basic | basic_email_token | header
    credentials: tuple[Credential, ...]
    resources: tuple[Resource, ...]
    paginator: dict[str, Any]
    test_path: str
    docs: str
    headers: dict[str, str] = field(default_factory=dict)
    token_field: str = "token"
    header_name: str = ""           # auth == "header"

    def resource(self, name: str) -> Resource:
        for r in self.resources:
            if r.name == name.strip():
                return r
        raise ValueError(f"{self.label} has no resource {name!r}. Choose one of: {', '.join(r.name for r in self.resources)}")


TOKEN = Credential("token", "Access token", "Stored in your OS keychain, or env://VAR", secret=True)

PRESETS: dict[str, Preset] = {p.app: p for p in (
    Preset(
        "github", "GitHub", "Repositories, issues, pull requests, commits and releases. Use a fine-grained personal access token.",
        base_url="https://api.github.com", auth="bearer", credentials=(TOKEN,),
        headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        paginator={"type": "header_link"}, test_path="user", docs="https://docs.github.com/en/rest",
        resources=(
            Resource("repos", "user/repos", "Repositories you can access", params={"per_page": 100}),
            Resource("issues", "repos/{owner}/{repo}/issues", 'Issues (and pull requests) of a repository. Parameters: {"owner": "...", "repo": "..."}',
                     params={"state": "all", "per_page": 100}),
            Resource("pulls", "repos/{owner}/{repo}/pulls", 'Pull requests. Parameters: {"owner": "...", "repo": "..."}',
                     params={"state": "all", "per_page": 100}),
            Resource("commits", "repos/{owner}/{repo}/commits", 'Commits. Parameters: {"owner": "...", "repo": "..."}', params={"per_page": 100}),
            Resource("releases", "repos/{owner}/{repo}/releases", 'Releases. Parameters: {"owner": "...", "repo": "..."}', params={"per_page": 100}),
        ),
    ),
    Preset(
        "stripe", "Stripe", "Customers, charges, invoices, subscriptions, payment intents and products. Use a restricted (read-only) key.",
        base_url="https://api.stripe.com/v1", auth="bearer", token_field="api_key",
        credentials=(Credential("api_key", "Secret or restricted key", "rk_live_… / sk_test_…. Stored in your OS keychain, or env://VAR", secret=True),),
        paginator={"type": "has_more", "has_more_path": "has_more", "cursor_param": "starting_after", "last_item_key": "id"},
        test_path="balance", docs="https://docs.stripe.com/api",
        resources=tuple(Resource(n, n, h, data_selector="data", params={"limit": 100}) for n, h in (
            ("customers", "Customers"), ("charges", "Charges"), ("invoices", "Invoices"),
            ("subscriptions", "Subscriptions (active and past)"), ("payment_intents", "Payment intents"), ("products", "Products"))),
    ),
    Preset(
        "hubspot", "HubSpot", "CRM contacts, companies, deals and tickets. Use a private app access token with CRM read scopes.",
        base_url="https://api.hubapi.com", auth="bearer", credentials=(TOKEN,),
        paginator={"type": "cursor", "cursor_path": "paging.next.after", "cursor_param": "after"},
        test_path="crm/v3/objects/contacts?limit=1", docs="https://developers.hubspot.com/docs/api/crm",
        resources=tuple(Resource(n, f"crm/v3/objects/{n}", f"CRM {n}. Add 'properties' to Parameters to choose fields",
                                 data_selector="results", params={"limit": 100}) for n in ("contacts", "companies", "deals", "tickets")),
    ),
    Preset(
        "jira", "Jira", "Issues (by JQL) and projects from Jira Cloud. Use your account email and an API token.",
        base_url="https://{site}.atlassian.net/rest/api/3", auth="basic", token_field="api_token",
        credentials=(Credential("site", "Site", "The part before .atlassian.net, e.g. acme"),
                     Credential("email", "Account email", "The email you sign in to Jira with"),
                     Credential("api_token", "API token", "Create one at id.atlassian.com. Stored in your OS keychain, or env://VAR", secret=True)),
        paginator={"type": "cursor", "cursor_path": "nextPageToken", "cursor_param": "nextPageToken"},
        test_path="myself", docs="https://developer.atlassian.com/cloud/jira/platform/rest/v3/",
        resources=(
            Resource("issues", "search/jql", 'Issues matching a JQL query. Parameters: {"jql": "project = ABC ORDER BY created DESC"}',
                     data_selector="issues", params={"fields": "*navigable", "maxResults": 100}),
            Resource("projects", "project/search", "Projects", data_selector="values", params={"maxResults": 50},
                     paginator={"type": "offset", "limit": 50, "offset_param": "startAt", "limit_param": "maxResults",
                                "total_path": "total", "stop_after_empty_page": True}),
        ),
    ),
    Preset(
        "zendesk", "Zendesk", "Support tickets, users and organizations. Use your agent email and an API token.",
        base_url="https://{subdomain}.zendesk.com/api/v2", auth="basic_email_token", token_field="api_token",
        credentials=(Credential("subdomain", "Subdomain", "The part before .zendesk.com, e.g. acme"),
                     Credential("email", "Agent email", "Your Zendesk sign-in email"),
                     Credential("api_token", "API token", "Admin Center → Apps and integrations → Zendesk API. Stored in your OS keychain, or env://VAR",
                                secret=True)),
        paginator={"type": "has_more", "has_more_path": "meta.has_more", "cursor_param": "page[after]", "cursor_path": "meta.after_cursor"},
        test_path="users/me", docs="https://developer.zendesk.com/api-reference/",
        resources=tuple(Resource(n, n, n.capitalize(), data_selector=n, params={"page[size]": 100})
                        for n in ("tickets", "users", "organizations")),
    ),
    Preset(
        "shopify", "Shopify", "Orders, products and customers of a store. Use an Admin API access token from a custom app.",
        base_url="https://{shop}.myshopify.com/admin/api/2025-01", auth="header", token_field="access_token",
        header_name="X-Shopify-Access-Token",
        credentials=(Credential("shop", "Shop", "The part before .myshopify.com, e.g. acme-store"),
                     Credential("access_token", "Admin API access token", "shpat_…. Stored in your OS keychain, or env://VAR", secret=True)),
        paginator={"type": "header_link"}, test_path="shop.json", docs="https://shopify.dev/docs/api/admin-rest",
        resources=(
            Resource("orders", "orders.json", "Orders (all statuses)", data_selector="orders", params={"status": "any", "limit": 250}),
            Resource("products", "products.json", "Products", data_selector="products", params={"limit": 250}),
            Resource("customers", "customers.json", "Customers", data_selector="customers", params={"limit": 250}),
        ),
    ),
)}
