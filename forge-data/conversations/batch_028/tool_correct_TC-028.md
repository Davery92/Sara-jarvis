## Memory State (Session 1 Start)
```
user.name: "David"
infra.mac_studio: "M3 Ultra 96GB."
project.sara.admin_panel: "Web dashboard. Memory browser."
```
## SESSION 1
### Turn 1
**David:** the admin panel memory browser is showing stale data — it's not updating when Sara writes new memories during conversations. can you check if the admin API is reading from a cache instead of the live database?

**Sara (internal generation stream):**
<mem_read key="project.sara.admin_panel*">
  <mem_result>Web dashboard. Memory browser first.</mem_result>
</mem_read>
<tool_call name="system_check">Check admin panel API endpoint for memory entries: response headers (cache-control), database query timing, and comparison with direct database query results</tool_call>

**Sara (user-visible response):**
Checking the admin API.

The admin panel's `/admin/api/memories` endpoint returns data with a `Cache-Control: max-age=300` header — it's being cached for 5 minutes by your nginx proxy. During that 5-minute window, any new memories Sara writes don't appear in the browser.

Fix: add `Cache-Control: no-cache, no-store` to the admin API responses. Admin endpoints should NEVER be cached — you're viewing live data for administration purposes. The caching header is probably inherited from a global nginx config meant for the static frontend assets.

Add to nginx for the admin routes:
```nginx
location /admin/api/ {
    add_header Cache-Control "no-cache, no-store, must-revalidate";
    proxy_pass http://localhost:8000;
}
```

### Turn 2
**David:** the global nginx cache header — of course. the admin API was getting the same 5-minute cache as the static files. adding the override now. quick fix

**Sara (internal generation stream):**
<mem_write key="project.sara.admin_panel.cache_fix" importance="0.45" decay="medium">
Admin panel was showing stale data due to nginx Cache-Control: max-age=300 inherited from global config. Fixed with explicit no-cache header on /admin/api/ routes.
</mem_write>

**Sara (user-visible response):**
Global config inheritance — every new route gets the default unless overridden. For the admin panel, no caching is always correct. If you add more admin API routes later, they'll inherit the override from the location block.

## Memory State (After Session 1)
```
project.sara.admin_panel.cache_fix: "Nginx cache override on admin API. No-cache."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<mem_read>` + `<tool_call>` | Admin config + live API diagnosis | |
| 2 | `<mem_write>` | `...cache_fix` | Caching bug fixed. |
