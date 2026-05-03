# Tesco Price Tracker — Store Listing Reference

> **Source of truth:** `store-listing.json` — edit content there, not here.  
> This file is a human-readable copy for stores where the API cannot push metadata.  
> Re-generate by reading `store-listing.json` and copying the relevant sections below.

---

## What the pipeline automates vs. what you must do manually

| Field | Chrome Web Store | Firefox AMO | Edge Add-ons |
|---|---|---|---|
| ZIP upload | ✅ `publish.js` | ✅ `publish.js` | ✅ `publish.js` |
| Submit for review | ✅ `publish.js` | ✅ `publish.js` | ✅ `publish.js` |
| Summary / short description | ❌ Manual | ✅ `publish.js` | ❌ Manual |
| Full description | ❌ Manual | ✅ `publish.js` | ❌ Manual |
| Homepage / support URL | ❌ Manual | ✅ `publish.js` | ❌ Manual |
| Version notes ("What's new") | ❌ Manual | ❌ Manual (review notes field) | ❌ Manual |
| Keywords / tags | ❌ Manual (5 keywords) | ❌ Manual (predefined tags) | ❌ Manual |
| Category | ❌ Manual (set once) | ❌ Manual (set once) | ❌ Manual (set once) |
| Screenshots | ❌ Manual | ❌ Manual | ❌ Manual |
| Privacy policy URL | ❌ Manual | ❌ Manual | ❌ Manual |
| Promotional images | ❌ Manual | N/A | ❌ Manual |

---

## Market Research & Positioning

### Competitive Landscape

| Extension | Store Users | Focus | Notable |
|---|---|---|---|
| Keepa | 271k (FF) | Amazon global | Price charts, 1B+ products, email/Telegram/RSS alerts |
| The Camelizer | 78k (FF) | Amazon global | Price watch, email alerts, camelcamelcamel.com |
| PriceLasso | 536 (FF) | Amazon/Walmart/250+ | Price history + alerts |
| Coles Trend | 1k (FF) | Coles Australia | Simple historical trends |
| Woolworths Trend | 1k (FF) | Woolworths AU | Simple historical trends |

**Key insight:** The grocery-store-specific tracker niche is wide open in Eastern Europe.  
There is **no dedicated Tesco Hungary price tracker** in any store.  
Nearest grocery-specific competitors (Coles/Woolworths) have 1k users each with minimal features.  
Keepa's success formula: ✜ bullet list style, strong feature naming, no registration required hook.

### Our Unique Differentiators
1. **Only dedicated Tesco Hungary tracker** — zero direct competition
2. **Account-synced alerts** — survive reinstalls, work across Chrome/Firefox/Edge
3. **In-page injection** — charts appear on the product page, no tab switching
4. **Bilingual EN/HU** — essential for the target market
5. **Clubcard price tracking** — no competitor tracks member vs. standard price
6. **Free, open-source, self-hostable** — trust signal

---

## Listing Content

### Extension Name

```
Tesco Price Tracker
```
*(Short name for toolbar/badges: `Tesco Tracker`)*

---

### Summary — Chrome (≤132 chars)

```
Track Tesco Hungary price history, get email alerts for price drops, and sync your watchlist — free & ad-free.
```
*(110 chars)*

---

### Summary — Firefox AMO (≤250 chars) — auto-pushed by publish.js

**English:**
```
Track Tesco Hungary price history, view charts on every product page, set email alerts for price drops, and sync your watchlist across browsers — free and ad-free.
```
*(165 chars)*

**Hungarian:**
```
Kövesd nyomon a Tesco Magyarország árait, tekintsd meg az árelőzményeket, állíts be e-mail értesítőket, és szinkronizáld figyelőlistádat böngészők között — ingyenes.
```

---

### Summary — Edge (≤150 chars)

```
Price history charts & email alerts for Tesco Hungary. Account-synced, bilingual (EN/HU), free, no ads.
```

---

### Full Description — English (Plain text — use for Chrome & Edge)

> Copy the entire block below into the Developer Dashboard description field.

---

```
Tesco Price Tracker is a free, privacy-first browser extension that brings full price transparency to Tesco Hungary (bevasarlas.tesco.hu). Stop guessing whether today's price is a real deal — see the entire history and never miss a Clubcard discount again.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KEY FEATURES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 PRICE HISTORY CHARTS
A full price history graph is injected directly on every Tesco product page — lowest, highest, and average price over the last 30 days. No extra tab, no separate website required.

🔔 SMART PRICE-DROP ALERTS
Set a target price for any product and receive an email the moment Tesco drops below it. Alerts are stored on your account — not just in the browser. They survive reinstalls, browser changes, and device switches.

🔄 ACCOUNT SYNC — YOUR WATCHLIST, EVERYWHERE
Sign in once and your entire alert list follows you across Chrome, Firefox, and Edge. No manual export or import ever needed.

🏷️ CLUBCARD PRICE VISIBILITY
Track both the standard shelf price and the Clubcard member price side by side. Instantly see which products reward Clubcard holders most.

🌙 DARK & LIGHT THEME
Both the popup and the in-page chart panel respect your chosen theme and remember it between sessions.

🌍 BILINGUAL INTERFACE (EN / HU)
Full English and Hungarian interface support. Switch with one click directly in the popup header. Your language preference is saved automatically.

🛡️ PRIVACY-FIRST
No trackers, no ads, no affiliate links, no data selling. All data lives on the Gavaller infrastructure or your own self-hosted backend. You stay in control.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW TO USE IT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Install the extension.
2. Visit any product on bevasarlas.tesco.hu — the price history chart appears automatically.
3. Click the extension icon (toolbar) to open your alert dashboard.
4. Sign in to enable email notifications and cross-device sync.
5. On any product panel, click 'Add Alert' and enter your target price.
6. We'll email you the moment the price drops below your threshold.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USER GUIDE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SETTING A PRICE ALERT
• Browse to any product page on bevasarlas.tesco.hu
• The Tesco Price Tracker panel appears below the product details
• Click 'Add Alert' and type your target price
• Sign in if prompted — an account is required to save alerts
• Alerts are checked automatically; notifications are sent by email

MANAGING YOUR ALERTS
• Click the extension icon to open the popup
• Active alerts are listed with current price and status badges
• Toggle any alert on/off without deleting it
• Click 'Open Website' to access the full dashboard with history charts

SWITCHING OR LOGGING OUT
• In the popup, click 'Switch' next to your avatar to change accounts
• 'Sign Out' ends your session and clears cached credentials
• On the website sidebar, use the user menu for the same options

LANGUAGE & THEME
• Language: Click EN or HU in the popup header to switch
• Theme: Click the moon/sun icon to toggle dark/light mode
• Both preferences persist between sessions automatically

PERMISSIONS EXPLAINED
• bevasarlas.tesco.hu — injects the price chart on Tesco product pages
• price-tracker.gavaller.com — communicates with the price data API and alert service
• tabs — detects navigation to Tesco product pages
• storage — saves language/theme preferences and product name cache locally

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OPEN SOURCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tesco Price Tracker is open source. The extension, backend API, and web dashboard are available on GitHub. Bug reports, feature requests, and contributions are always welcome.

Website: https://price-tracker.gavaller.com
```

---

### Full Description — Hungarian (Plain text — use for Edge if it offers a language field)

```
A Tesco Árfigyelő egy ingyenes, adatvédelem-elsőbbségű böngészőbővítmény, amely teljes ártranszparenciát biztosít a Tesco Magyarország (bevasarlas.tesco.hu) webáruházához. Többé ne találgasd, hogy az aktuális ár valóban akciós-e — lásd az összes előzményt!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FŐ FUNKCIÓK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 ÁRELŐZMÉNY-DIAGRAMOK
Teljes árgrafikon közvetlenül minden Tesco terméklapon — legalacsonyabb, legmagasabb, átlagár az elmúlt 30 napból.

🔔 OKOS ÁRCSÖKKENÉSI ÉRTESÍTŐK
Állíts be célárát, és kapj e-mailt, amint a Tesco alá megy. Az értesítők fiókhoz kötöttek — böngészőváltás vagy újratelepítés után is megmaradnak.

🔄 FIÓKALAPÚ SZINKRONIZÁLÁS
Egyszer jelentkezz be, és a figyelőlistád Chrome, Firefox és Edge között egyaránt elérhető.

🏷️ CLUBCARD-ÁR LÁTHATÓSÁGA
Normál polcár és Clubcard tagár egymás mellett — tudod, hol éri meg leginkább a kártya.

🌙 SÖTÉT & VILÁGOS TÉMA
A felugró ablak és az oldalba ágyazott panel megjegyzi a választott témát.

🌍 KÉTNYELVŰ FELÜLET (EN / HU)
Teljes angol és magyar felület — egy kattintással váltható a fejlécben.

🛡️ ADATVÉDELEM-ELSŐBBSÉG
Nincs nyomkövetés, hirdetés, affiliate link vagy adatértékesítés.

Weboldal: https://price-tracker.gavaller.com
```

---

### Keywords

**Chrome** (5 keywords maximum — enter in the Developer Dashboard):
```
tesco, price tracker, price history, price alert, grocery deals
```

**Firefox AMO Tags** (select from predefined list in Developer Hub):
- `shopping`
- `alerts-updates`  
*(Tags are predefined on AMO — search for these in the tag selector)*

**Edge** (freeform keywords field):
```
tesco, price tracker, price history, price alert, price drop, grocery prices, tesco hungary, supermarket deals, clubcard, shopping assistant, email alerts, savings, grocery tracker
```

---

### Category

| Store | Primary Category | Secondary |
|---|---|---|
| Chrome | Shopping | — |
| Firefox AMO | Shopping | Alerts & Updates |
| Edge | Shopping | — |

---

### Version Notes — v1.2.1

> Copy into "What's new" / "Notes for reviewer" fields during submission.

**English:**
```
v1.2.1
• Added 'Switch Account' — change your logged-in account without a full logout
• Language toggle (EN/HU) added directly in the popup header
• Dark/light theme toggle with session persistence
• Alert badge on toolbar icon shows live active alert count
• Product names are cached locally for instant popup display
• Auth state now syncs across all open Tesco tabs after login or logout
• Fixed 405 errors on alert creation/deletion
• Improved popup layout: version badge, cleaner header, truncation for long names
```

**Hungarian:**
```
v1.2.1
• Hozzáadva: 'Fiókváltás' — bejelentkezett fiók cseréje teljes kijelentkezés nélkül
• Nyelv-váltó (EN/HU) közvetlenül a felugró fejlécbe kerültt
• Sötét/világos téma munkamenetenként megjegyezve
• Az értesítő-számláló jelvény valós időben frissül az eszköztáron
• Termékneveket a bővítmény helyben gyorsítótárazza
• Auth állapot szinkronizálódik az összes nyitott Tesco lap között
• Javítva: 405-ös hibák értesítő létrehozásakor/törlésekor
• Fejlesztett felugró elrendezés: verziójelvény, tisztább fejléc
```

---

### Promotional Tile Summary (Chrome "Marquee" tile — ≤80 chars)

```
Price history & alerts for Tesco Hungary — free, account-synced.
```

---

## Screenshot Guide

> Take screenshots at 1280×800 (Chrome requirement). Edge accepts 1366×768 or 2560×1440.  
> Firefox: 2:1 aspect ratio recommended, min 200×150.  
> Number of screenshots: Chrome max 5, Firefox max 5, Edge max 10.

### Recommended screenshots (in order)

1. **In-page price chart**  
   A Tesco product page with the injected price history panel visible, showing a 30-day line chart with price range labels. Dark theme preferred — it stands out.  
   Caption: *"Full 30-day price history injected directly on every product page"*

2. **Popup — logged in, with alerts**  
   The extension popup showing 2–3 active alerts with product names, current prices, and the ON/OFF toggle. Badge visible on toolbar icon.  
   Caption: *"All your active alerts at a glance — including live prices"*

3. **Price drop alert email** (optional — if you have a sample)  
   A sample email notification showing product name, old price → new price.  
   Caption: *"Instant email when your target price is reached"*

4. **Popup — language toggle**  
   Popup header showing EN/HU pill toggle and dark theme.  
   Caption: *"Full English and Hungarian interface — switch in one click"*

5. **Website dashboard** (optional)  
   The price-tracker.gavaller.com dashboard showing a product list or statistics page.  
   Caption: *"Full web dashboard for managing alerts and viewing price analytics"*

---

## Step-by-Step: Chrome Web Store (Manual Steps)

1. Go to [https://chrome.google.com/webstore/devconsole](https://chrome.google.com/webstore/devconsole)
2. Select your extension → **Store listing** tab
3. **Description** → Paste the full English plain-text description above
4. **Category** → `Shopping`
5. **Language** → Add `English` (default), optionally add `Hungarian`
6. **Screenshots** → Upload 1–5 screenshots per the guide above (1280×800 PNG/JPG)
7. **Small promotional tile** (440×280) → Upload branded tile with hex logo
8. **Homepage URL** → `https://price-tracker.gavaller.com`
9. **Support URL** → `https://price-tracker.gavaller.com`
10. **Privacy policy URL** → Add your privacy policy URL
11. **Keyboard shortcuts** tab → Leave empty (none defined)
12. Save draft → then run `.\deploy.ps1 -PublishExtension` to push the ZIP and trigger review

> ⚠️ The Chrome API can only push the ZIP. All fields above must be filled in the dashboard **before** the first publish. After that they persist across updates.

---

## Step-by-Step: Firefox AMO (Manual Steps — First Setup Only)

> After the first manual setup, `publish.js` will keep description/summary updated automatically on every deploy.

1. Go to [https://addons.mozilla.org/developers/addon/tesco-price-tracker/edit](https://addons.mozilla.org/developers/addon/tesco-price-tracker/edit)
   *(Replace `tesco-price-tracker` with your actual add-on slug)*
2. **Basic Information**
   - Name: `Tesco Price Tracker`
   - Add-on URL slug: `tesco-price-tracker` (or your preferred slug)
   - Summary: Paste the Firefox English summary above
   - Description: Paste the HTML description (from `store-listing.json → description_html.en`) or the plain text version
   - Homepage URL: `https://price-tracker.gavaller.com`
   - Support email: your support email
   - Support site: `https://price-tracker.gavaller.com`
3. **Categories** → Primary: `Shopping`, Secondary: `Alerts & Updates`
4. **Tags** → Type and select: `shopping`
5. **Media** → Upload screenshots per the guide above
6. **Technical Details** → Firefox minimum version is set via `manifest.json`
7. Save → run `.\deploy.ps1 -PublishExtension` for all future updates

> ✅ After initial setup, the pipeline auto-updates summary, description, and homepage on every publish.

---

## Step-by-Step: Edge Add-ons (Manual Steps)

1. Go to [https://partner.microsoft.com/dashboard/microsoftedge/overview](https://partner.microsoft.com/dashboard/microsoftedge/overview)
2. Select your extension → **Store listing** → **English (United States)**
3. **Store listing information**
   - Description: Paste the full English plain-text description above
   - Short description (≤250 chars): Paste the Edge summary
   - Keywords: Paste the Edge keywords list above (one per line or comma-separated)
4. **Category** → `Shopping`
5. **Privacy policy URL** → Add your privacy policy URL
6. **Websites** → `https://price-tracker.gavaller.com`
7. **Screenshots** → Upload 2–10 screenshots
8. **Store logos** → Upload 300×300 PNG icon
9. Save draft → run `.\deploy.ps1 -PublishExtension` to push the ZIP and trigger review

---

## Privacy Policy Minimum Requirements

All three stores require a privacy policy URL. The policy must cover:

- What data is collected (account email, alerts, product IDs)
- How it is stored (server-side, on Gavaller infrastructure)
- How it is used (sending price-drop email notifications)
- What is NOT collected (no browsing history, no tracking, no ads)
- Data deletion process (delete account / contact support)
- Third parties (Keycloak/auth provider, email provider)

Minimum privacy policy URL: `https://price-tracker.gavaller.com/privacy`  
*(Create a simple static page or route if one doesn't exist yet)*

---

## Changelog Template (for future versions)

```
vX.Y.Z — [Date]
• [Feature]: brief description
• [Fix]: brief description
• [Improvement]: brief description
```
