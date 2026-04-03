---
name: web-fetch
description: "Fetch any URL and return clean markdown via Jina Reader API. Falls back to WebFetch built-in if Jina fails. Use this INSTEAD of WebFetch for all web page reads."
risk: safe
source: internal
date_added: "2026-04-03"
---

# Web Fetch — Jina Reader Priority

## Purpose

Fetch any web page and return clean, LLM-friendly markdown.
Uses **Jina Reader API** as primary method — faster, deterministic, no token cost.
Falls back to **WebFetch** built-in only on failure.

## When to Use

**Always** when you need to read a web page, documentation, article, or any URL content.
This skill replaces direct `WebFetch` calls as the default method.

## Procedure

### Step 1: Fetch via Jina Reader

Use `WebFetch` with the Jina Reader proxy URL:

```
URL:    https://r.jina.ai/{TARGET_URL}
Prompt: "Return the full content exactly as provided, no summarization."
```

Example — to fetch `https://docs.example.com/api`:
- URL: `https://r.jina.ai/https://docs.example.com/api`
- Prompt: `"Return the full content exactly as provided, no summarization."`

Jina Reader will:
- Strip ads, navigation, cookie banners, boilerplate
- Convert HTML to clean markdown
- Handle PDFs natively
- Handle JS-rendered pages (SPAs)

### Step 2: Check Result

Evaluate the response. It is **negative** if ANY of these:
- Empty or near-empty content (< 50 chars of meaningful text)
- Error message from Jina (rate limit, timeout, DNS failure)
- HTTP error codes surfaced in response (404, 403, 429, 500, 502, 503)
- Content is clearly not the target page (redirect notice, captcha, block page)

### Step 3: Fallback to WebFetch

**Only if Step 2 detected a negative result**, retry with standard WebFetch:

```
URL:    {TARGET_URL}  (the original URL, NOT via r.jina.ai)
Prompt: {original prompt or "Extract the main content of this page."}
```

### Step 4: Report

When returning results to the user or using them in your work:
- Do NOT mention which method was used unless asked
- If both methods failed, say so explicitly with the error details

## Notes

- Jina Reader free tier: 10M tokens per API key, 500 RPM
- No API key required for basic usage (rate limited by IP)
- For PDFs, Jina is significantly faster than WebFetch
- Jina does NOT work with authenticated pages (login-required) — fall back immediately for those
