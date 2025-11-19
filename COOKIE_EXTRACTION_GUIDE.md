# LinkedIn Cookie Extraction Guide

## Prerequisites
1. Complete LinkedIn signup and verify your email
2. Log in to LinkedIn in Chrome/Edge
3. Browse to any job posting page (e.g., https://www.linkedin.com/jobs/view/XXXXXXX)

## Method 1: Manual Cookie Export (Recommended)

### Step 1: Open DevTools
1. Press `F12` or `Ctrl+Shift+I` to open Developer Tools
2. Go to the **Application** tab (or **Storage** in Firefox)

### Step 2: Export Cookies
1. In the left sidebar, expand **Cookies**
2. Click on `https://www.linkedin.com`
3. You'll see a table with all cookies

### Step 3: Copy Important Cookies
You need these cookies (copy Name, Value, Domain, Path, Expires, Secure, HttpOnly):

**Critical Cookies:**
- `li_at` - Main authentication token (MOST IMPORTANT)
- `JSESSIONID` - Session ID
- `lidc` - Load balancer cookie
- `bcookie` - Browser cookie
- `bscookie` - Browser session cookie
- `li_rm` - Remember me token
- `lang` - Language preference

### Step 4: Format as JSON
Create a file with this structure:

```json
[
  {
    "name": "li_at",
    "value": "YOUR_LI_AT_VALUE_HERE",
    "domain": ".linkedin.com",
    "path": "/",
    "expires": 1795098943,
    "secure": true,
    "httpOnly": true
  },
  {
    "name": "JSESSIONID",
    "value": "ajax:1234567890123456789",
    "domain": ".linkedin.com",
    "path": "/",
    "expires": -1,
    "secure": true,
    "httpOnly": false
  }
  // ... add all other cookies
]
```

## Method 2: Using Browser Extension

### Option A: EditThisCookie (Chrome/Edge)
1. Install "EditThisCookie" extension
2. Visit https://www.linkedin.com (while logged in)
3. Click the extension icon
4. Click **Export** button
5. Paste the exported JSON into `cookies.json`

### Option B: Cookie-Editor (Firefox/Chrome)
1. Install "Cookie-Editor" extension  
2. Visit https://www.linkedin.com (while logged in)
3. Click extension icon
4. Click **Export** → **JSON**
5. Save to `cookies.json`

## Method 3: Using JavaScript Console

### Quick Export Script
1. Open DevTools Console (`F12` → Console tab)
2. Paste this script:

```javascript
copy(JSON.stringify(
  document.cookie.split(';').map(c => {
    const [name, value] = c.trim().split('=');
    return {
      name,
      value,
      domain: '.linkedin.com',
      path: '/',
      secure: true,
      httpOnly: false
    };
  }),
  null,
  2
));
```

3. The cookies are now copied to clipboard
4. Paste into `cookies.json`

## Important Notes

### ⚠️ Critical Cookie: `li_at`
The **`li_at`** cookie is your authentication token. Without it, you cannot access authenticated content.

- **Validity**: Usually valid for 1 year
- **Location**: Set after login
- **Required**: YES - mandatory for scraping

### Cookie Expiration
- Cookies have expiration dates (Unix timestamps)
- `"expires": -1` means session cookie (expires when browser closes)
- `"expires": 1795098943` means expires at that Unix timestamp

### Security Warning
⚠️ **Never share your `cookies.json` file!**
- Contains your authentication tokens
- Anyone with these cookies can access your LinkedIn account
- Add `cookies.json` to `.gitignore`

## Verification

After updating `cookies.json`, verify it works:

1. Start your scraper server
2. Try scraping a job URL
3. Check logs for "Successfully loaded X/X cookies"
4. If extraction fails, cookies might be invalid/expired

## Troubleshooting

### "No job description found"
- Cookies might be expired
- Missing `li_at` cookie
- Account not fully verified

### "403 Forbidden"
- Cookies are invalid or expired
- LinkedIn detected automated access
- Try logging in again and re-exporting cookies

### "429 Too Many Requests"
- Rate limiting kicked in
- Wait a few minutes
- Reduce request frequency

## Cookie Format Example

```json
[
  {
    "name": "li_at",
    "value": "AQEDATEzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDEyMw",
    "domain": ".linkedin.com",
    "path": "/",
    "expires": 1795098943,
    "secure": true,
    "httpOnly": true
  },
  {
    "name": "JSESSIONID",
    "value": "ajax:7666607991881317780",
    "domain": ".www.linkedin.com",
    "path": "/",
    "expires": -1,
    "secure": true,
    "httpOnly": false
  },
  {
    "name": "lidc",
    "value": "b=OGST03:s=O:r=O:a=O:p=O:g=3695:u=1:x=1:i=1763562899:t=1763649299:v=2:sig=AQH95tvVn9wiRW0lZ7sP8b1PEzhhlg1b",
    "domain": ".linkedin.com",
    "path": "/",
    "expires": 1763649299,
    "secure": true,
    "httpOnly": false
  },
  {
    "name": "bcookie",
    "value": "v=2&7e8afa2c-c84c-44f5-8a98-44c4c1a8580c",
    "domain": ".linkedin.com",
    "path": "/",
    "expires": 1795098943,
    "secure": true,
    "httpOnly": false
  },
  {
    "name": "bscookie",
    "value": "v=1&202511191434592841b653-1e61-4b8c-8375-bf58f385a2c8AQGU-WFmMCKiM5wqirMtcLuj5Wx5_051",
    "domain": ".www.linkedin.com",
    "path": "/",
    "expires": 1795098943,
    "secure": true,
    "httpOnly": false
  },
  {
    "name": "lang",
    "value": "v=2&lang=en-us",
    "domain": ".linkedin.com",
    "path": "/",
    "expires": -1,
    "secure": false,
    "httpOnly": false
  }
]
```

## Next Steps

1. Extract cookies using one of the methods above
2. Save to `cookies.json`
3. Restart your scraper server
4. Test with a job URL
5. Check debug HTML if extraction still fails
