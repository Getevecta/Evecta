# Fix: Blank page until cache is cleared

## Why it happens

After each deployment, the built app has **new hashed filenames** for JS/CSS (e.g. `index-abc123.js`).  
If the browser (or a CDN) has **cached the old `index.html`**, that HTML still points to **old filenames** that no longer exist on the server → those requests return **404** → the app script never loads → **blank page**.  
Clearing cache fixes it because the browser then fetches fresh `index.html` with the correct script URLs.

## What we changed in the repo

- **Vite build** (`vite.config.ts`): **fixed filenames** (no hash) for JS/CSS, so cached `index.html` still points to `assets/index.js` etc. — **no server changes needed**; blank page is avoided.
- **Vite dev server**: sends `Cache-Control: no-cache` so localhost doesn’t cache HTML.
- **`index.html`**: added cache-control meta tags as a hint.

**Tradeoff of fixed filenames:** The app always loads (no blank page), but some users may see the previous version until they refresh, because the browser can cache `assets/index.js`. If you prefer “everyone gets the latest version immediately,” use the server steps below and you can switch the build back to hashed filenames (remove the `rollupOptions.output` block from `vite.config.ts`).

---

## (Optional) Server: no-cache for index.html

If you want users to always get the latest version on first load and are okay editing Nginx, do the following. Otherwise the build change above is enough to prevent the blank page.

The **real fix** for https://evecta.io and https://staging.evecta.io is to **stop caching `index.html`** in **Nginx**. Do the steps below for **both** production and staging (two different Nginx server blocks or config files if you use separate ones).

---

### Step-by-step on the server

**Step 1 — SSH into the server**
```bash
ssh -i /path/to/your/key.pem ubuntu@YOUR_SERVER_IP
```
(Use the same SSH key and host you use for deploys.)

**Step 2 — Find the Nginx config that serves the frontend**
```bash
# List site configs
ls /etc/nginx/sites-available/

# Often the main config is default or has your domain name
sudo nano /etc/nginx/sites-available/default
# or, if you have a separate file:
# sudo nano /etc/nginx/sites-available/evecta
```
You need the `server { ... }` block whose `root` is `/var/www/html` (production) or `/var/www/html-staging` (staging).

**Step 3 — Add no-cache for index.html**

You will see something like:
```nginx
server {
    listen 80;
    server_name evecta.io www.evecta.io;
    root /var/www/html;
    index index.html;
    location / {
        try_files $uri $uri/ /index.html;
    }
    # ... rest of block
}
```

**Option A (simplest):** Add the three headers inside the existing `location /` block:
```nginx
location / {
    add_header Cache-Control "no-cache, no-store, must-revalidate";
    add_header Pragma "no-cache";
    add_header Expires "0";
    try_files $uri $uri/ /index.html;
}
```

**Option B (only HTML no-cache):** Add two *new* location blocks *before* your existing `location /`:
```nginx
location = / {
    add_header Cache-Control "no-cache, no-store, must-revalidate";
    add_header Pragma "no-cache";
    add_header Expires "0";
    try_files /index.html =404;
}

location = /index.html {
    add_header Cache-Control "no-cache, no-store, must-revalidate";
    add_header Pragma "no-cache";
    add_header Expires "0";
}

location / {
    try_files $uri $uri/ /index.html;
}
```

**Step 4 — Repeat for staging (if separate server block)**

If staging uses a different `server { }` (e.g. `server_name staging.evecta.io` with `root /var/www/html-staging`), apply the same **Option A** or **Option B** inside that block.

**Step 5 — Test Nginx config**
```bash
sudo nginx -t
```
You should see: `syntax is ok` and `test is successful`.

**Step 6 — Reload Nginx**
```bash
sudo systemctl reload nginx
```

**Step 7 — Verify**

- Open https://evecta.io (and https://staging.evecta.io) in a browser.
- Open DevTools → Network tab, reload the page.
- Click the first request (the document, e.g. `evecta.io` or `evecta.io/`).
- In Response Headers you should see:  
  `Cache-Control: no-cache, no-store, must-revalidate` (and optionally `Pragma: no-cache`, `Expires: 0`).

After this, users will always get a fresh `index.html` when they load the site, so they get the correct script URLs and no more blank page after deployments.
