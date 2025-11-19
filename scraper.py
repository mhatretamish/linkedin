import tls_client
import json
import logging
import time
import re
from typing import Dict, Optional, Any, List
from bs4 import BeautifulSoup
from threading import Lock
from urllib.parse import urlparse, parse_qs

from config import config

logger = logging.getLogger(__name__)


class LinkedInScraper:
    def __init__(self):
        self.session = None
        self.session_lock = Lock()
        self.cookies_loaded = False
        self.last_request_time = 0
        self.request_count = 0
        self.session_created_at = 0
        self.proxy = None  # Initialize proxy as None
        self.initialize_session()

    def initialize_session(self) -> None:
        """Initialize or reinitialize TLS client session"""
        with self.session_lock:
            try:
                # Close existing session if any
                if self.session:
                    try:
                        self.session.close()
                    except Exception:
                        pass

                # Create new session with random TLS identifier
                tls_identifier = config.get_random_tls_identifier()
                self.session = tls_client.Session(
                    client_identifier=tls_identifier,
                    random_tls_extension_order=True
                )

                # Store proxy configuration
                self.proxy = None
                if config.PROXY_ENABLED and config.PROXY_URL:
                    # For tls_client, proxy should be the full URL string
                    self.proxy = config.PROXY_URL
                    # Parse for logging purposes
                    import re
                    proxy_pattern = r'http://([^:]+):([^@]+)@([^:]+):(\d+)'
                    match = re.match(proxy_pattern, config.PROXY_URL)
                    if match:
                        username, password, host, port = match.groups()
                        logger.info(f"Using proxy: {host}:{port} with authentication")
                    else:
                        logger.warning(f"Invalid proxy URL format: {config.PROXY_URL}")

                # Set random user agent
                headers = self._get_headers()
                self.session.headers.update(headers)

                # Load cookies
                self._load_cookies()

                self.session_created_at = time.time()
                logger.info(f"Session initialized with TLS identifier: {tls_identifier}")

            except Exception as e:
                logger.error(f"Failed to initialize session: {e}")
                raise

    def _get_headers(self) -> Dict[str, str]:
        """Get headers with random user agent"""
        user_agent = config.get_random_user_agent()
        return {
            "User-Agent": user_agent,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
            "DNT": "1",
            "Cache-Control": "max-age=0"
        }

    def _load_cookies(self) -> None:
        """Enhanced cookie loading with validation and fallback"""
        try:
            with open(config.COOKIES_FILE, "r") as file:
                cookies = json.load(file)
                
                if not cookies:
                    logger.warning("Cookies file is empty")
                    return
                
                loaded_count = 0
                for cookie in cookies:
                    try:
                        # Validate required cookie fields
                        if not all(key in cookie for key in ['name', 'value']):
                            logger.warning(f"Skipping invalid cookie: {cookie}")
                            continue
                        
                        # Set cookie with proper domain handling
                        domain = cookie.get('domain', '.linkedin.com')
                        if domain and not domain.startswith('.'):
                            domain = f'.{domain}'
                        
                        self.session.cookies.set(
                            cookie["name"], 
                            cookie["value"], 
                            domain=domain,
                            path=cookie.get('path', '/'),
                            secure=cookie.get('secure', True)
                        )
                        loaded_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to set cookie {cookie.get('name', 'unknown')}: {e}")
                        continue
                
                logger.info(f"Successfully loaded {loaded_count}/{len(cookies)} cookies")
                self.cookies_loaded = True
                
                # Validate critical cookies
                critical_cookies = ['li_at', 'JSESSIONID']
                missing_cookies = []
                for cookie_name in critical_cookies:
                    if not any(c['name'] == cookie_name for c in cookies):
                        missing_cookies.append(cookie_name)
                
                if missing_cookies:
                    logger.warning(f"Missing critical cookies: {missing_cookies}")
                    logger.warning("Consider updating cookies for better authentication")
                
        except FileNotFoundError:
            logger.warning("cookies.json file not found. Proceeding without cookies.")
            self.cookies_loaded = False
        except json.JSONDecodeError:
            logger.error("Error decoding cookies.json")
            self.cookies_loaded = False
        except Exception as e:
            logger.error(f"Error loading cookies: {e}")
            self.cookies_loaded = False

    def _check_session_health(self) -> bool:
        """Check if session needs refresh"""
        if not self.session:
            return False

        # Check session age
        session_age = time.time() - self.session_created_at
        if session_age > config.SESSION_TIMEOUT:
            logger.info("Session expired, needs refresh")
            return False

        return True

    def _apply_rate_limiting(self) -> None:
        """Apply rate limiting between requests"""
        current_time = time.time()

        # Apply random delay
        delay = config.get_random_delay()
        time.sleep(delay)

        self.last_request_time = current_time
        self.request_count += 1

    def _normalize_linkedin_job_url(self, url: str) -> str:
        """
        Advanced LinkedIn job URL normalization to handle all formats.
        
        Handles:
        - Collection URLs: /jobs/collections/recommended/?currentJobId=123
        - Search URLs: /jobs/search/?currentJobId=123
        - Path-based URLs: /jobs/view/title-at-company-123
        - Regional domains: in.linkedin.com, uk.linkedin.com, etc.
        - Tracking URLs: /jobs/view/123?position=1&pageNum=0&refId=...
        """
        original_url = url
        parsed = urlparse(url)
        
        # Normalize domain to www.linkedin.com
        if parsed.netloc and 'linkedin.com' in parsed.netloc:
            base_domain = "www.linkedin.com"
        else:
            base_domain = parsed.netloc
        
        # Method 1: Extract from currentJobId parameter (existing method)
        query_params = parse_qs(parsed.query)
        current_job_id = query_params.get('currentJobId')
        
        if current_job_id:
            job_id = current_job_id[0]
            normalized_url = f"https://{base_domain}/jobs/view/{job_id}"
            logger.info(f"Extracted job ID from currentJobId parameter: {job_id}")
            return normalized_url
        
        # Method 2: Extract from URL path using regex patterns
        path = parsed.path
        
        # Pattern 1: /jobs/view/title-at-company-1234567890
        pattern1 = r'/jobs/view/.*?-(\d{10,})(?:/.*)?$'
        match1 = re.search(pattern1, path)
        if match1:
            job_id = match1.group(1)
            normalized_url = f"https://{base_domain}/jobs/view/{job_id}"
            logger.info(f"Extracted job ID from path pattern (title-company-ID): {job_id}")
            return normalized_url
        
        # Pattern 2: /jobs/view/1234567890
        pattern2 = r'/jobs/view/(\d{10,})(?:/.*)?$'
        match2 = re.search(pattern2, path)
        if match2:
            job_id = match2.group(1)
            normalized_url = f"https://{base_domain}/jobs/view/{job_id}"
            logger.info(f"Extracted job ID from direct path: {job_id}")
            return normalized_url
        
        # Pattern 3: Extract from any part of URL using broader pattern
        pattern3 = r'(\d{10,})'
        matches = re.findall(pattern3, url)
        if matches:
            # Take the longest number (most likely to be job ID)
            job_id = max(matches, key=len)
            if len(job_id) >= 10:  # LinkedIn job IDs are typically 10+ digits
                normalized_url = f"https://{base_domain}/jobs/view/{job_id}"
                logger.info(f"Extracted job ID from URL pattern matching: {job_id}")
                return normalized_url
        
        # Method 3: If already a proper job view URL, just normalize domain
        if "/jobs/view/" in path and base_domain != parsed.netloc:
            normalized_url = f"https://{base_domain}{path}"
            if parsed.query:
                # Keep essential parameters, remove tracking
                essential_params = {}
                for param, value in query_params.items():
                    if param not in ['position', 'pageNum', 'refId', 'trackingId', 'ref']:
                        essential_params[param] = value
                if essential_params:
                    from urllib.parse import urlencode
                    normalized_url += "?" + urlencode(essential_params, doseq=True)
            logger.info(f"Normalized domain and cleaned tracking parameters")
            return normalized_url
        
        # If no job ID found, return original URL (will be tried as-is)
        logger.warning(f"Could not extract job ID from URL: {original_url}")
        return original_url

    def _extract_meta_data(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract job data from meta tags"""
        result = {}
        
        # OpenGraph meta tags
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            content = og_title["content"]
            # Extract company from title like "LinkedIn hiring Sr Business Analyst in Location"
            if " hiring " in content:
                parts = content.split(" hiring ")
                if len(parts) >= 2:
                    result["company"] = parts[0].strip()
                    title_location = parts[1]
                    if " in " in title_location:
                        title_parts = title_location.split(" in ")
                        result["title"] = title_parts[0].strip()
                        if len(title_parts) > 1:
                            result["location"] = title_parts[1].replace(" | LinkedIn", "").strip()
        
        og_description = soup.find("meta", property="og:description")
        if og_description and og_description.get("content"):
            result["meta_description"] = og_description["content"]
        
        og_url = soup.find("meta", property="og:url")
        if og_url and og_url.get("content"):
            result["canonical_url"] = og_url["content"]
        
        # Twitter meta tags as fallback
        if not result.get("title"):
            twitter_title = soup.find("meta", attrs={"name": "twitter:title"})
            if twitter_title and twitter_title.get("content"):
                result["title"] = twitter_title["content"].replace(" | LinkedIn", "").strip()
        
        if not result.get("meta_description"):
            twitter_desc = soup.find("meta", attrs={"name": "twitter:description"})
            if twitter_desc and twitter_desc.get("content"):
                result["meta_description"] = twitter_desc["content"]
        
        return result

    def _extract_structured_data(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract structured data from JSON-LD and other sources"""
        result = {}
        
        # JSON-LD structured data
        json_ld_scripts = soup.find_all("script", type="application/ld+json")
        for script in json_ld_scripts:
            if script.string:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        if data.get("@type") == "JobPosting":
                            result.update({
                                "title": data.get("title"),
                                "description": data.get("description"),
                                "company": data.get("hiringOrganization", {}).get("name"),
                                "location": data.get("jobLocation", {}).get("address", {}).get("addressLocality"),
                                "employment_type": data.get("employmentType"),
                                "date_posted": data.get("datePosted"),
                                "valid_through": data.get("validThrough")
                            })
                            break
                except json.JSONDecodeError:
                    continue
        
        return result

    def _extract_job_from_json(self, json_data: dict) -> Dict[str, Any]:
        """Extract job description AND header fields from LinkedIn's embedded JSON data"""
        try:
            result = {
                "description": None,
                "title": None,
                "company": None,
                "company_url": None,
                "company_logo": None,
                "location": None,
                "posted_time": None
            }

            # Method 1: Check for direct job posting data
            if "data" in json_data:
                job_data = json_data["data"]

                # Extract job description from various possible fields
                desc_fields = ["description", "jobDescription", "details", "content"]
                for field in desc_fields:
                    if field in job_data:
                        desc = job_data[field]
                        if isinstance(desc, dict):
                            if "text" in desc:
                                result["description"] = desc["text"].replace("\\n", "\n")
                            elif "markup" in desc:
                                result["description"] = desc["markup"]
                        elif isinstance(desc, str) and len(desc) > 50:
                            result["description"] = desc

                        if result.get("description"):
                            logger.info(f"✓ Extracted description from JSON (length: {len(result['description'])})")
                            break

                # Extract TITLE
                if "title" in job_data and job_data["title"]:
                    result["title"] = job_data["title"]
                    logger.info(f"✓ Extracted title from JSON: {result['title']}")

                # Extract LOCATION
                location_fields = ["formattedLocation", "location", "workRemoteAllowed"]
                for field in location_fields:
                    if field in job_data and job_data[field]:
                        if isinstance(job_data[field], str):
                            result["location"] = job_data[field]
                            logger.info(f"✓ Extracted location from JSON: {result['location']}")
                            break

                # Extract POSTED TIME from timestamp
                if "listedAt" in job_data and job_data["listedAt"]:
                    try:
                        timestamp_ms = job_data["listedAt"]
                        current_time = time.time() * 1000  # Convert to milliseconds
                        time_diff_ms = current_time - timestamp_ms

                        # Convert to relative time
                        time_diff_seconds = time_diff_ms / 1000
                        if time_diff_seconds < 3600:
                            minutes = int(time_diff_seconds / 60)
                            result["posted_time"] = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
                        elif time_diff_seconds < 86400:
                            hours = int(time_diff_seconds / 3600)
                            result["posted_time"] = f"{hours} hour{'s' if hours != 1 else ''} ago"
                        else:
                            days = int(time_diff_seconds / 86400)
                            result["posted_time"] = f"{days} day{'s' if days != 1 else ''} ago"

                        logger.info(f"✓ Extracted posted_time from JSON: {result['posted_time']}")
                    except Exception as e:
                        logger.debug(f"Error converting timestamp: {e}")

            # Extract COMPANY information from "included" array
            if "included" in json_data and isinstance(json_data["included"], list):
                for item in json_data["included"]:
                    if isinstance(item, dict):
                        # Look for company object (usually has $type containing "Company")
                        item_type = item.get("$type", "")

                        # Check if this is a company object
                        if "company" in item_type.lower() or "name" in item:
                            # Extract company name
                            if "name" in item and item["name"] and not result.get("company"):
                                result["company"] = item["name"]
                                logger.info(f"✓ Extracted company from JSON: {result['company']}")

                            # Extract company URL
                            if "url" in item and item["url"] and not result.get("company_url"):
                                result["company_url"] = item["url"]
                                logger.info(f"✓ Extracted company_url from JSON: {result['company_url']}")

                            # Extract company logo
                            if "logo" in item and isinstance(item["logo"], dict):
                                logo_data = item["logo"]

                                # Try different logo extraction methods
                                if "rootUrl" in logo_data and "artifacts" in logo_data:
                                    artifacts = logo_data["artifacts"]
                                    if isinstance(artifacts, list) and len(artifacts) > 0:
                                        # Get the first artifact (usually the best quality)
                                        artifact = artifacts[0]
                                        if "fileIdentifyingUrlPathSegment" in artifact:
                                            logo_url = logo_data["rootUrl"] + artifact["fileIdentifyingUrlPathSegment"]
                                            result["company_logo"] = logo_url
                                            logger.info(f"✓ Extracted company_logo from JSON: {result['company_logo']}")

                                # Alternative: vectorImage
                                elif "vectorImage" in logo_data and isinstance(logo_data["vectorImage"], dict):
                                    vector = logo_data["vectorImage"]
                                    if "rootUrl" in vector and "artifacts" in vector:
                                        artifacts = vector["artifacts"]
                                        if isinstance(artifacts, list) and len(artifacts) > 0:
                                            artifact = artifacts[0]
                                            if "fileIdentifyingUrlPathSegment" in artifact:
                                                logo_url = vector["rootUrl"] + artifact["fileIdentifyingUrlPathSegment"]
                                                result["company_logo"] = logo_url
                                                logger.info(f"✓ Extracted company_logo from vectorImage: {result['company_logo']}")

                            # If we found company info, we can break (unless we're still missing some fields)
                            if result.get("company") and result.get("company_url"):
                                break

            # Try deep search if no description found yet
            if not result.get("description"):
                deep_result = self._deep_search_for_job_content(json_data)
                if deep_result and deep_result.get("description"):
                    result["description"] = deep_result["description"]
                    logger.info(f"✓ Extracted description from deep search (length: {len(result['description'])})")

            # Log summary of extraction
            extracted_fields = [k for k, v in result.items() if v is not None]
            logger.info(f"JSON extraction complete. Extracted fields: {', '.join(extracted_fields) if extracted_fields else 'NONE'}")

            return result

        except Exception as e:
            logger.error(f"Error extracting job from JSON: {e}")
            return {
                "description": None,
                "title": None,
                "company": None,
                "company_url": None,
                "company_logo": None,
                "location": None,
                "posted_time": None
            }

    def _deep_search_for_job_content(self, data, max_depth=5, current_depth=0):
        """Recursively search for job description content in JSON data"""
        if current_depth > max_depth:
            return None
            
        if isinstance(data, dict):
            # Look for description-like fields
            desc_keys = ["description", "jobDescription", "content", "details", "summary"]
            for key in desc_keys:
                if key in data:
                    value = data[key]
                    if isinstance(value, str) and len(value) > 100:
                        # Check if it looks like a real job description
                        job_indicators = ["experience", "skills", "responsibilities", "qualifications", "requirements"]
                        if any(indicator in value.lower() for indicator in job_indicators):
                            return value
                    elif isinstance(value, dict) and "text" in value:
                        text = value["text"]
                        if isinstance(text, str) and len(text) > 100:
                            return text.replace("\\n", "\n")
            
            # Recursively search in nested objects
            for key, value in data.items():
                if key not in ["$type", "locale", "lixTreatment"]:  # Skip metadata
                    result = self._deep_search_for_job_content(value, max_depth, current_depth + 1)
                    if result:
                        return result
                        
        elif isinstance(data, list):
            for item in data:
                result = self._deep_search_for_job_content(item, max_depth, current_depth + 1)
                if result:
                    return result
        
        return None

    def _validate_linkedin_url(self, url: str) -> bool:
        """Validate if URL is a LinkedIn URL (including regional domains)"""
        try:
            parsed = urlparse(url)
            # Support all LinkedIn domains including regional ones
            valid_domains = [
                "www.linkedin.com", 
                "linkedin.com",
                "in.linkedin.com",    # India
                "uk.linkedin.com",    # United Kingdom
                "ca.linkedin.com",    # Canada
                "au.linkedin.com",    # Australia
                "br.linkedin.com",    # Brazil
                "de.linkedin.com",    # Germany
                "fr.linkedin.com",    # France
                "es.linkedin.com",    # Spain
                "it.linkedin.com",    # Italy
                "nl.linkedin.com",    # Netherlands
                "se.linkedin.com",    # Sweden
                "jp.linkedin.com",    # Japan
                "kr.linkedin.com",    # South Korea
                "sg.linkedin.com",    # Singapore
                "hk.linkedin.com",    # Hong Kong
                "tw.linkedin.com",    # Taiwan
                "mx.linkedin.com",    # Mexico
                "ar.linkedin.com",    # Argentina
                "cl.linkedin.com",    # Chile
                "co.linkedin.com",    # Colombia
                "pe.linkedin.com",    # Peru
                "za.linkedin.com",    # South Africa
                "ae.linkedin.com",    # UAE
                "il.linkedin.com",    # Israel
                "tr.linkedin.com",    # Turkey
                "ru.linkedin.com",    # Russia
                "pl.linkedin.com",    # Poland
                "cz.linkedin.com",    # Czech Republic
                "hu.linkedin.com",    # Hungary
                "ro.linkedin.com",    # Romania
                "bg.linkedin.com",    # Bulgaria
                "hr.linkedin.com",    # Croatia
                "sk.linkedin.com",    # Slovakia
                "si.linkedin.com",    # Slovenia
                "lt.linkedin.com",    # Lithuania
                "lv.linkedin.com",    # Latvia
                "ee.linkedin.com",    # Estonia
                "fi.linkedin.com",    # Finland
                "dk.linkedin.com",    # Denmark
                "no.linkedin.com",    # Norway
                "is.linkedin.com",    # Iceland
                "ie.linkedin.com",    # Ireland
                "pt.linkedin.com",    # Portugal
                "gr.linkedin.com",    # Greece
                "cy.linkedin.com",    # Cyprus
                "mt.linkedin.com",    # Malta
                "lu.linkedin.com",    # Luxembourg
                "be.linkedin.com",    # Belgium
                "at.linkedin.com",    # Austria
                "ch.linkedin.com",    # Switzerland
                "li.linkedin.com",    # Liechtenstein
                "mc.linkedin.com",    # Monaco
                "sm.linkedin.com",    # San Marino
                "va.linkedin.com",    # Vatican
                "ad.linkedin.com"     # Andorra
            ]
            
            # Also allow any subdomain of linkedin.com
            if parsed.netloc.endswith('.linkedin.com') or parsed.netloc == 'linkedin.com':
                return True
                
            return parsed.netloc in valid_domains
        except Exception:
            return False

    def _detect_content_type(self, url: str) -> str:
        """Detect LinkedIn content type from URL"""
        if "/jobs/" in url or "currentJobId=" in url:
            return "job"
        elif "/in/" in url:
            return "profile"
        elif "/company/" in url:
            return "company"
        elif "/posts/" in url:
            return "post"
        else:
            return "unknown"

    def fetch_content(self, url: str, bypass_cache: bool = False) -> Dict[str, Any]:
        """
        Enhanced fetch content with advanced URL handling and robust error recovery

        Args:
            url: LinkedIn URL to scrape
            bypass_cache: Whether to bypass cache

        Returns:
            Dict containing scraped content and metadata
        """
        start_time = time.time()
        original_url = url
        
        # Validate URL
        if not self._validate_linkedin_url(url):
            raise ValueError(f"Invalid LinkedIn URL: {url}")

        # Advanced URL normalization
        url = self._normalize_linkedin_job_url(url)
        if url != original_url:
            logger.info(f"URL normalized: {original_url} -> {url}")

        # Detect content type
        content_type = self._detect_content_type(url)
        logger.info(f"Detected content type: {content_type}")

        # Retry logic with session management
        max_proxy_retries = 2  # Try proxy only 2 times
        max_total_retries = config.MAX_RETRIES
        retry_count = 0
        last_error = None
        proxy_failed = False

        while retry_count <= max_total_retries:
            try:
                # Check session health and reinitialize if needed
                # On first attempt, skip reinit to preserve TLS session for API
                if retry_count == 0 and self._check_session_health():
                    # Session is healthy and it's first attempt, keep it
                    pass
                else:
                    # Either session is unhealthy or it's a retry
                    logger.info(f"Reinitializing session (attempt {retry_count + 1})")
                    self.initialize_session()

                # Apply rate limiting
                self._apply_rate_limiting()

                # Update referer based on content type
                referer = config.LINKEDIN_BASE_URL
                if content_type == "job":
                    referer = f"{config.LINKEDIN_BASE_URL}/jobs/"
                
                self.session.headers.update({"Referer": referer})

                # Determine if we should use proxy
                use_proxy = self.proxy and not proxy_failed and retry_count < max_proxy_retries
                
                if use_proxy:
                    logger.info(f"Fetching {content_type} content from: {url[:60]}... (attempt {retry_count + 1} with proxy)")
                else:
                    if proxy_failed:
                        logger.info(f"Fetching {content_type} content from: {url[:60]}... (attempt {retry_count + 1} WITHOUT proxy - fallback)")
                    else:
                        logger.info(f"Fetching {content_type} content from: {url[:60]}... (attempt {retry_count + 1} direct connection)")

                # Try both original and normalized URLs if they're different
                urls_to_try = [url]
                if url != original_url:
                    urls_to_try.append(original_url)

                response = None
                for attempt_url in urls_to_try:
                    try:
                        logger.info(f"Trying URL: {attempt_url[:60]}...")
                        
                        # Make request with or without proxy based on logic
                        if use_proxy:
                            response = self.session.get(attempt_url, proxy=self.proxy)
                        else:
                            response = self.session.get(attempt_url)
                        
                        # Check for successful response
                        if response.status_code == 200:
                            logger.info(f"Successfully fetched content from: {attempt_url[:60]}...")
                            break
                        elif response.status_code == 404:
                            logger.warning(f"URL not found (404): {attempt_url[:60]}...")
                            continue
                        else:
                            logger.warning(f"HTTP {response.status_code} for URL: {attempt_url[:60]}...")
                            
                    except Exception as e:
                        logger.warning(f"Request failed for {attempt_url[:60]}...: {e}")
                        # If proxy failed and we haven't exceeded max proxy retries, mark proxy as failed
                        if use_proxy and "407" in str(e):
                            if retry_count >= max_proxy_retries - 1:
                                proxy_failed = True
                                logger.warning("Proxy authentication failed, switching to direct connection for remaining attempts")
                        continue

                if not response or response.status_code != 200:
                    if response:
                        status_code = response.status_code
                        if status_code == 429:
                            wait_time = config.RETRY_DELAY * (2 ** retry_count)
                            logger.warning(f"Rate limited (429), waiting {wait_time}s before retry...")
                            time.sleep(wait_time)
                            retry_count += 1
                            continue
                        elif status_code == 403:
                            logger.error("Access forbidden (403) - cookies might be expired")
                            # Try refreshing session on 403
                            if retry_count < max_total_retries:
                                retry_count += 1
                                continue
                            raise Exception("Access forbidden - check cookies and proxy settings")
                        elif status_code == 404:
                            raise Exception(f"Job posting not found (404) - URL may be invalid: {url}")
                        else:
                            raise Exception(f"HTTP {status_code}")
                    else:
                        raise Exception("No response received")

                # Parse content
                soup = BeautifulSoup(response.text, "html.parser")
                processing_time = (time.time() - start_time) * 1000

                # Extract content based on type with enhanced methods
                if content_type == "job":
                    # Try API for job posts (AFTER page is loaded, ONLY on first attempt)
                    # Note: LinkedIn's API validates TLS session, so we can't use it after session reinit
                    job_id = self._extract_job_id_from_url(url)
                    if job_id and retry_count == 0:
                        logger.info(f"Attempting to fetch job data from API for job ID: {job_id}")
                        api_data = self._fetch_job_from_api(job_id)
                        if api_data:
                            content = self._parse_api_job_data(api_data)
                            logger.info(f"API extraction successful, got {len(content.get('description', ''))} chars of description")
                            # Still extract header fields from HTML if API didn't provide them
                            if not content.get("title") or not content.get("company"):
                                logger.info("Extracting missing fields from HTML")
                                self._extract_header_fields(soup, response.text, content)
                        else:
                            logger.warning("API fetch failed, falling back to HTML scraping")
                            content = self._extract_job_description(soup, response.text)
                    else:
                        if retry_count > 0:
                            logger.info("Skipping API on retry attempt, using HTML scraping")
                        content = self._extract_job_description(soup, response.text)
                elif content_type == "profile":
                    content = self._extract_profile_info(soup, response.text)
                elif content_type == "company":
                    content = self._extract_company_info(soup, response.text)
                else:
                    # Generic content extraction
                    content = {"raw_text": soup.get_text()[:1000]}

                # Wrap metadata into description for job posts
                if content_type == "job" and isinstance(content, dict):
                    content = self._wrap_metadata_into_description(content)

                # Build comprehensive result
                result = {
                    "success": True,
                    "type": content_type,
                    "url": response.url,
                    "original_url": original_url,
                    "content": content,
                    "timestamp": time.time(),
                    "processing_time_ms": processing_time,
                    "attempts": retry_count + 1,
                    "status_code": response.status_code,
                    "response_size": len(response.text),
                    "extraction_methods": content.get("extraction_methods", []) if isinstance(content, dict) else []
                }

                # Validate that we got meaningful content
                if content_type == "job":
                    if not content.get("description") and not content.get("title"):
                        logger.warning("No meaningful job content extracted, this may indicate parsing issues")
                        if retry_count < max_total_retries:
                            retry_count += 1
                            time.sleep(config.RETRY_DELAY)
                            continue
                
                logger.info(f"Successfully extracted {content_type} content in {processing_time:.1f}ms")
                return result

            except Exception as e:
                last_error = e
                retry_count += 1
                
                if retry_count <= max_total_retries:
                    wait_time = config.RETRY_DELAY * retry_count
                    logger.warning(f"Attempt {retry_count} failed: {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"All {max_total_retries + 1} attempts failed. Last error: {e}")
                    break

        # If we get here, all retries failed
        processing_time = (time.time() - start_time) * 1000
        error_result = {
            "success": False,
            "type": content_type,
            "url": url,
            "original_url": original_url,
            "error": str(last_error),
            "timestamp": time.time(),
            "processing_time_ms": processing_time,
            "attempts": retry_count
        }
        
        logger.error(f"Failed to fetch content after {retry_count} attempts: {last_error}")
        return error_result

    def _extract_header_fields(self, soup: BeautifulSoup, html: str, result: Dict[str, Any]) -> None:
        """Extract header fields: title, company, location, posted_time, company_logo"""
        logger.info("Starting header fields extraction...")

        # Debug: Check if we have the expected HTML structure
        top_card = soup.find("section", class_="top-card-layout")
        if top_card:
            logger.info("Found top-card-layout section")
        else:
            logger.warning("top-card-layout section NOT found - LinkedIn may have changed structure")

        # Extract Title
        if not result.get("title"):
            logger.debug("Attempting to extract title...")

            # First, check if ANY h1 elements exist
            all_h1 = soup.find_all("h1")
            logger.debug(f"Found {len(all_h1)} h1 elements in total")
            if all_h1:
                for idx, h1 in enumerate(all_h1[:3]):  # Log first 3
                    logger.debug(f"H1 #{idx+1}: classes={h1.get('class', [])}, text={h1.get_text(strip=True)[:50]}")

            title_selectors = [
                "h1.top-card-layout__title",
                "h1.topcard__title",  # This might match!
                "h3.sub-nav-cta__header",
                "h1.job-title",
                "h1[data-test-id='job-title']",
                ".job-details-jobs-unified-top-card__job-title h1",
                ".jobs-unified-top-card__job-title h1",
                "h1.jobs-unified-top-card__job-title",
                "h1.job-details-jobs-unified-top-card__job-title",
                "div.jobs-unified-top-card__content--two-pane h1",
                "h1[class*='job-title']",
                "h1[data-test='job-title']",
                # More flexible - match ANY h1 with these partial class names
                "section.top-card-layout h1",
                "div.top-card-layout__entity-info h1"
            ]
            for selector in title_selectors:
                title_elem = soup.select_one(selector)
                if title_elem:
                    result["title"] = title_elem.get_text(strip=True)
                    logger.info(f"Found title using selector: {selector}")
                    break
                else:
                    logger.debug(f"Selector '{selector}' matched nothing")

        # Extract Company
        if not result.get("company"):
            company_selectors = [
                "a.topcard__org-name-link",  # More general - should match!
                "a.sub-nav-cta__optional-url",
                "a.topcard__org-name-link.topcard__flavor--black-link",
                ".job-details-jobs-unified-top-card__company-name a",
                ".jobs-unified-top-card__company-name a",
                "[data-test-id='job-details-company-name'] a",
                "a.jobs-unified-top-card__company-name",
                "div.jobs-unified-top-card__company-name a",
                "span.jobs-unified-top-card__company-name a",
                "a[data-test='job-details-company-name']",
                "div[class*='company-name'] a",
                # More flexible
                "section.top-card-layout a.topcard__org-name-link",
                "div.topcard__flavor-row a[class*='org-name']"
            ]
            for selector in company_selectors:
                company_elem = soup.select_one(selector)
                if company_elem:
                    result["company"] = company_elem.get_text(strip=True)
                    # Extract company URL if available
                    company_url = company_elem.get("href")
                    if company_url and not result.get("company_url"):
                        result["company_url"] = company_url
                    logger.info(f"Found company using selector: {selector}")
                    break

        # Extract Location
        if not result.get("location"):
            location_selectors = [
                "span.topcard__flavor.topcard__flavor--bullet",  # Specific match
                "span.topcard__flavor--bullet",
                "span.sub-nav-cta__meta-text",
                ".topcard__flavor--bullet",
                ".job-details-jobs-unified-top-card__primary-description",
                ".jobs-unified-top-card__bullet",
                "[data-test-id='job-details-location']",
                "span.jobs-unified-top-card__bullet",
                "div.jobs-unified-top-card__primary-description",
                "span[class*='location']",
                "div[data-test='job-details-location']",
                "span.job-details-jobs-unified-top-card__bullet",
                # More flexible
                "div.topcard__flavor-row span.topcard__flavor--bullet",
                "section.top-card-layout span[class*='bullet']"
            ]
            for selector in location_selectors:
                location_elem = soup.select_one(selector)
                if location_elem:
                    location_text = location_elem.get_text(strip=True)
                    # Clean up location text
                    location_text = re.sub(r'[·•].*$', '', location_text).strip()
                    if location_text and len(location_text) > 2:
                        result["location"] = location_text
                        logger.info(f"Found location using selector: {selector}")
                        break

        # Extract Posted Time
        if not result.get("posted_time"):
            posted_time_selectors = [
                "span.posted-time-ago__text",  # More general first
                "span.posted-time-ago__text.topcard__flavor--metadata",
                "span.posted-time-ago__text.posted-time-ago__text--new",  # NEW!
                "time.posted-time-ago__text",
                "span[class*='posted-time']",
                "div.topcard__flavor-row span.topcard__flavor--metadata",
                # More flexible
                "section.top-card-layout span[class*='posted-time']",
                "div.topcard__flavor-row span[class*='posted-time']"
            ]
            for selector in posted_time_selectors:
                posted_elem = soup.select_one(selector)
                if posted_elem:
                    result["posted_time"] = posted_elem.get_text(strip=True)
                    logger.info(f"Found posted time using selector: {selector}")
                    break

        # Extract Company Logo
        if not result.get("company_logo"):
            logo_selectors = [
                "img.artdeco-entity-image",  # More general first - should match!
                "img.sub-nav-cta__image",
                "img.top-card-layout__entity-image",
                "img[alt*='logo']",
                "img.topcard__org-logo",
                # More flexible
                "section.top-card-layout img.artdeco-entity-image",
                "a[data-tracking-control-name='public_jobs_topcard_logo'] img"
            ]
            for selector in logo_selectors:
                logo_elem = soup.select_one(selector)
                if logo_elem:
                    # Try to get the actual image URL from data-delayed-url or src
                    logo_url = logo_elem.get("data-delayed-url") or logo_elem.get("src")
                    if logo_url and not logo_url.startswith("data:") and "ghost" not in logo_url:
                        result["company_logo"] = logo_url
                        logger.info(f"Found company logo using selector: {selector}")
                        break

        # Extract job ID from HTML
        if not result.get("job_id"):
            job_id_patterns = [
                r'"jobId["\']:\s*["\']?(\d{10,})["\']?',
                r'jobPosting["\']:\s*["\']?(\d{10,})["\']?',
                r'currentJobId["\']:\s*["\']?(\d{10,})["\']?',
                r'/jobs/view/(\d{10,})'
            ]
            for pattern in job_id_patterns:
                matches = re.findall(pattern, html)
                if matches:
                    result["job_id"] = matches[0]
                    break

        # Log summary of extracted header fields
        extracted_fields = [k for k in ["title", "company", "company_url", "location", "posted_time", "company_logo", "job_id"] if result.get(k)]
        logger.info(f"Header extraction complete. Extracted fields: {', '.join(extracted_fields) if extracted_fields else 'NONE'}")

        if not extracted_fields:
            logger.warning("WARNING: No header fields were extracted! This indicates the HTML structure may have changed.")

    def _save_debug_html(self, html: str, job_id: str = "unknown") -> None:
        """Save HTML to file for debugging purposes"""
        try:
            import os
            debug_dir = "debug_html"
            if not os.path.exists(debug_dir):
                os.makedirs(debug_dir)
            
            timestamp = int(time.time())
            filename = f"{debug_dir}/job_{job_id}_{timestamp}.html"
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(html)
            
            logger.info(f"Debug HTML saved to: {filename}")
        except Exception as e:
            logger.warning(f"Failed to save debug HTML: {e}")

    def _extract_job_id_from_url(self, url: str) -> Optional[str]:
        """Extract job ID from LinkedIn URL"""
        # Try different patterns
        patterns = [
            r'/jobs/view/.*?-(\d{10,})(?:/.*)?$',  # title-at-company-ID
            r'/jobs/view/(\d{10,})(?:/.*)?$',  # direct ID
            r'currentJobId=(\d{10,})',  # query parameter
            r'(\d{10,})'  # any 10+ digit number
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                job_id = match.group(1)
                logger.info(f"Extracted job ID: {job_id} from URL using pattern: {pattern}")
                return job_id
        
        logger.warning(f"Could not extract job ID from URL: {url}")
        return None

    def _fetch_job_from_api(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Fetch job data from LinkedIn's internal API using a fresh session"""
        try:
            import tls_client
            import json
            
            # Create a FRESH session just for the API call (to avoid TLS fingerprint issues)
            api_session = tls_client.Session(client_identifier='chrome_120')
            
            # Load cookies from file
            with open(config.COOKIES_FILE, 'r') as f:
                cookies = json.load(f)
                for c in cookies:
                    api_session.cookies.set(c['name'], c['value'], domain=c.get('domain', '.linkedin.com'))
            
            # Get CSRF token
            csrf_token = None
            for cookie in api_session.cookies:
                if cookie.name == 'JSESSIONID':
                    csrf_token = cookie.value
                    break
            
            if not csrf_token:
                logger.warning("CSRF token not found")
                return None
            
            # Set API headers
            api_session.headers.update({
                "Accept": "application/vnd.linkedin.normalized+json+2.1",
                "csrf-token": csrf_token,
                "x-restli-protocol-version": "2.0.0",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            
            # Construct API URL with decoration parameter to get resolved company data
            api_url = f"https://www.linkedin.com/voyager/api/jobs/jobPostings/{job_id}?decorationId=com.linkedin.voyager.deco.jobs.web.shared.WebFullJobPosting-65"
            
            logger.info(f"Fetching job data from API (fresh session): {api_url}")
            
            # Make API request
            response = api_session.get(api_url)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Successfully fetched job data from API - {len(str(data))} bytes")
                return data
            else:
                logger.warning(f"API request failed with status {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching from API: {e}")
            return None

    def _parse_api_job_data(self, api_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse job data from LinkedIn API response"""
        result = {
            "description": None,
            "extraction_methods": ["linkedin_api"]
        }
        
        try:
            job_data = api_data.get("data", {})
            
            # Extract title
            if job_data.get("title"):
                result["title"] = job_data["title"]
            
            # Extract company from 'included' array (resolved by decoration parameter)
            included = api_data.get("included", [])
            for item in included:
                if item.get("$type") == "com.linkedin.voyager.organization.Company":
                    if item.get("name"):
                        result["company"] = item["name"]
                        logger.info(f"Extracted company name from API: {result['company']}")
                        break
            
            # Extract location
            if job_data.get("formattedLocation"):
                result["location"] = job_data["formattedLocation"]
            
            # Extract employment type
            if job_data.get("formattedEmploymentStatus"):
                result["employment_type"] = job_data["formattedEmploymentStatus"]
            
            # Extract experience level
            if job_data.get("formattedExperienceLevel"):
                result["experience_level"] = job_data["formattedExperienceLevel"]
            
            # Extract job functions
            if job_data.get("formattedJobFunctions"):
                result["job_functions"] = job_data["formattedJobFunctions"]
            
            # Extract industries
            if job_data.get("formattedIndustries"):
                result["industries"] = job_data["formattedIndustries"]
            
            # Extract description (main content)
            description_data = job_data.get("description", {})
            if isinstance(description_data, dict) and description_data.get("text"):
                result["description"] = description_data["text"]
                logger.info(f"Extracted job description from API: {len(result['description'])} characters")
            
            # Extract company description
            company_desc = job_data.get("companyDescription", {})
            if isinstance(company_desc, dict) and company_desc.get("text"):
                result["company_description"] = company_desc["text"]
            
            # Extract apply URL
            apply_method = job_data.get("applyMethod", {})
            if apply_method.get("companyApplyUrl"):
                result["apply_url"] = apply_method["companyApplyUrl"]
            
            # Extract posted date
            if job_data.get("listedAt"):
                result["posted_at"] = job_data["listedAt"]
            
            # Extract closed date
            if job_data.get("closedAt"):
                result["closed_at"] = job_data["closedAt"]
            
            return result
            
        except Exception as e:
            logger.error(f"Error parsing API data: {e}")
            return result

    def _wrap_metadata_into_description(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Wrap all job metadata into the description field as formatted text"""
        try:
            # Build formatted header with all metadata
            header_parts = []
            
            # Add title
            if content.get("title"):
                header_parts.append(f"📋 **Job Title:** {content['title']}")
            
            # Add company
            if content.get("company"):
                header_parts.append(f"🏢 **Company:** {content['company']}")
            
            # Add location
            if content.get("location"):
                header_parts.append(f"📍 **Location:** {content['location']}")
            
            # Add employment type
            if content.get("employment_type"):
                header_parts.append(f"💼 **Employment Type:** {content['employment_type']}")
            
            # Add experience level
            if content.get("experience_level"):
                header_parts.append(f"📊 **Experience Level:** {content['experience_level']}")
            
            # Add job functions
            if content.get("job_functions"):
                header_parts.append(f"🔧 **Job Functions:** {content['job_functions']}")
            
            # Add industries
            if content.get("industries"):
                header_parts.append(f"🏭 **Industries:** {content['industries']}")
            
            # Add posted date
            if content.get("posted_at"):
                from datetime import datetime
                try:
                    if isinstance(content["posted_at"], (int, float)):
                        # Convert timestamp to readable date
                        posted_date = datetime.fromtimestamp(content["posted_at"] / 1000).strftime("%B %d, %Y")
                        header_parts.append(f"📅 **Posted Date:** {posted_date}")
                    else:
                        header_parts.append(f"📅 **Posted Date:** {content['posted_at']}")
                except:
                    pass
            
            # Add apply URL
            if content.get("apply_url"):
                header_parts.append(f"🔗 **Apply URL:** {content['apply_url']}")
            
            # Combine header and description
            header = "\n".join(header_parts)
            original_description = content.get("description", "")
            
            if header and original_description:
                # Wrap: Header + separator + Description
                wrapped_description = f"{header}\n\n{'='*60}\n\n**Job Description:**\n\n{original_description}"
            elif header:
                wrapped_description = header
            else:
                wrapped_description = original_description
            
            # Create new content with wrapped description
            wrapped_content = {
                "description": wrapped_description,
                "extraction_methods": content.get("extraction_methods", [])
            }
            
            return wrapped_content
            
        except Exception as e:
            logger.error(f"Error wrapping metadata: {e}")
            return content

    def _extract_job_description(self, soup: BeautifulSoup, html: str) -> Dict[str, Any]:
        """Extract job description and header information"""
        result = {
            "description": None,
            "extraction_methods": []
        }

        # PRIORITY: Extract header fields FIRST (title, company, location, posted_time, company_logo)
        # This ensures these are always extracted regardless of description extraction method
        self._extract_header_fields(soup, html, result)

        # Method 1: Extract from meta tags first (most reliable)
        meta_data = self._extract_meta_data(soup)
        if meta_data:
            result.update({k: v for k, v in meta_data.items() if v and not result.get(k)})
            if meta_data:
                result["extraction_methods"].append("meta_tags")

        # Method 2: Extract from structured JSON-LD data
        structured_data = self._extract_structured_data(soup)
        if structured_data:
            result.update({k: v for k, v in structured_data.items() if v and not result.get(k)})
            if structured_data:
                result["extraction_methods"].append("json_ld")

        # Method 3: Enhanced HTML selectors for job description (updated for 2024/2025 LinkedIn)
        job_description_selectors = [
            "section.show-more-less-html",
            "div.show-more-less-html__markup", 
            "div[class*='show-more-less-html__markup']",
            "div.jobs-description__content div.show-more-less-html__markup",
            "div.jobs-box__content div.show-more-less-html__markup",
            "div.job-details-jobs-unified-top-card__job-description div",
            "section[data-section='jobDetailsModule'] div.show-more-less-html__markup",
            "div.jobs-description-content__text",
            "div.jobs-description__text",
            "div[id*='job-details'] div.show-more-less-html__markup",
            "div.jobs-unified-description div.show-more-less-html__markup",
            # New 2024+ selectors
            "div.jobs-description-content div.show-more-less-html__markup",
            "article.jobs-description__container div.show-more-less-html__markup",
            "div.job-details-module div.show-more-less-html__markup",
            # More generic but commonly used selectors
            "div.description__text",
            "div.description__text--rich",
            "div.jobs-description",
            "section.jobs-description",
            # Try without requiring nested div
            "div.show-more-less-html__markup",
            "section.core-section-container__content",
        ]
        
        logger.debug(f"Attempting {len(job_description_selectors)} HTML selectors for job description...")
        
        for idx, selector in enumerate(job_description_selectors):
            job_description_section = soup.select_one(selector)
            if job_description_section and not result.get("description"):
                logger.debug(f"Selector #{idx+1} '{selector}' found a match!")
                # Clean up the element by removing unwanted nested elements
                desc_element = job_description_section.copy()
                
                # Remove script tags, style tags, code tags and other unwanted elements
                for unwanted in desc_element.find_all(['script', 'style', 'code']):
                    unwanted.decompose()
                
                desc_text = desc_element.get_text(separator="\n").strip()
                
                # More rigorous validation
                if desc_text and len(desc_text) > 50:
                    # Check for JSON/config data markers
                    json_markers = ["\"$type\":", "\"locale\":", "\"lixTreatment\":", "experimentId"]
                    marker_count = sum(1 for marker in json_markers if marker in desc_text)
                    
                    # Only accept if it doesn't look like JSON config
                    if marker_count < 2 and not (desc_text.startswith('{') or desc_text.startswith('[') or 
                           desc_text.startswith('"data":"')):
                        result["description"] = desc_text
                        result["extraction_methods"].append("html_selectors")
                        logger.info(f"✓ Found job description using selector: {selector}")
                        break
                    else:
                        logger.debug(f"Selector matched but content looks like JSON (markers: {marker_count})")
            else:
                if idx < 5:  # Only log first few to avoid spam
                    logger.debug(f"Selector #{idx+1} '{selector}' - no match")

        # Method 4: Enhanced JSON-LD script parsing
        if not result.get("description"):
            script_tags = soup.find_all("script", type="application/ld+json")
            for script in script_tags:
                if script.string and "description" in script.string:
                    try:
                        data = json.loads(script.string)
                        if "description" in data and not result.get("description"):
                            result["description"] = data["description"]
                            result["extraction_methods"].append("json_ld_scripts")
                        if "title" in data and not result.get("title"):
                            result["title"] = data["title"]
                        if "hiringOrganization" in data and not result.get("company"):
                            result["company"] = data["hiringOrganization"].get("name")
                    except json.JSONDecodeError:
                        continue

        # Method 5: Enhanced code block parsing for description only
        if not result.get("description"):
            code_blocks = soup.find_all("code")
            logger.info(f"Found {len(code_blocks)} code blocks to analyze")
            
            for i, code in enumerate(code_blocks):
                if code.string and len(code.string) > 100:
                    try:
                        json_str = code.string.strip()
                        
                        # Look for blocks that contain job posting data
                        if ("fsd_jobPosting" in json_str or "dashEntityUrn" in json_str or 
                            "jobDescription" in json_str or ('"title":' in json_str and len(json_str) > 5000)):
                            
                            # Handle HTML entities
                            json_str = json_str.replace('&quot;', '"').replace('&#61;', '=').replace('&amp;', '&')
                            
                            data = json.loads(json_str)
                            job_details = self._extract_job_from_json(data)

                            if job_details and job_details.get("description"):
                                # Validate the description is clean job content
                                desc = job_details.get("description", "")
                                if (len(desc) > 100 and
                                    not desc.startswith('{') and
                                    not desc.startswith('[') and
                                    not any(unwanted in desc for unwanted in [
                                        "$type", "chameleonConfig", "lixTreatment", "voyager.dash"
                                    ])):
                                    # Merge ALL fields from JSON extraction (not just description)
                                    for key, value in job_details.items():
                                        if value and not result.get(key):
                                            result[key] = value
                                            logger.info(f"Merged {key} from JSON extraction")

                                    result["extraction_methods"].append("code_blocks")
                                    logger.info(f"Successfully extracted job data from code block {i+1}")
                                    break
                            
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        logger.debug(f"Error processing code block {i+1}: {e}")
                        continue

        # Method 6: Fallback extraction methods for job description
        if not result.get("description"):
            # Try broader selectors but with better filtering
            fallback_selectors = [
                "div[class*='description']",
                "div[class*='job-details']",
                "section[class*='description']",
                "div[id*='description']",
                "div.jobs-box__html-content",
                "div.jobs-description-details",
                "p[class*='job-description']"
            ]
            
            for selector in fallback_selectors:
                elements = soup.select(selector)
                for elem in elements:
                    # Clean the element
                    clean_elem = elem.copy()
                    for unwanted in clean_elem.find_all(['script', 'style', 'code']):
                        unwanted.decompose()
                    
                    text = clean_elem.get_text(separator="\n").strip()
                    
                    # Must be substantial content and not contain unwanted patterns
                    if (text and len(text) > 100 and 
                        not any(unwanted in text for unwanted in [
                            "chameleon", "voyager", "ChameleonConfig", "lixTreatment",
                            "experimentId", "treatmentIndex", "$type", "\"data\":", "\"locale\"",
                            "configLixTrackingInfoListV2", "segmentIndex"
                        ])):
                        result["description"] = text
                        result["extraction_methods"].append("fallback_selectors")
                        logger.info(f"Found clean job description using fallback selector: {selector}")
                        break
                if result.get("description"):
                    break

        # Method 7: Text pattern matching for job descriptions (IMPROVED)
        if not result.get("description"):
            # Remove all code/script tags first to avoid JSON contamination
            soup_copy = BeautifulSoup(str(soup), "html.parser")
            for unwanted in soup_copy.find_all(['script', 'style', 'code']):
                unwanted.decompose()
            
            # Get clean text without code blocks
            all_text = soup_copy.get_text()
            
            # Look for common job description patterns in cleaned text
            description_patterns = [
                r"(Job Description[:\s]*.*?)(?:Requirements|Qualifications|Skills|Apply|Contact|Share|Save)",
                r"(About this role[:\s]*.*?)(?:Requirements|Qualifications|Skills|Apply|Contact|Share|Save)",
                r"(We are looking for[:\s]*.*?)(?:Requirements|Qualifications|Skills|Apply|Contact|Share|Save)",
                r"(Position Summary[:\s]*.*?)(?:Requirements|Qualifications|Skills|Apply|Contact|Share|Save)",
                r"(Role Overview[:\s]*.*?)(?:Requirements|Qualifications|Skills|Apply|Contact|Share|Save)",
                # New patterns for actual job content
                r"(About the job[:\s]*.*?)(?:Show more|Show less|LinkedIn|Share|Save|Report)",
                r"(Responsibilities[:\s]*.*?)(?:Qualifications|Requirements|Skills|Apply|Share|Save)"
            ]
            
            for pattern in description_patterns:
                matches = re.search(pattern, all_text, re.DOTALL | re.IGNORECASE)
                if matches and len(matches.group(1).strip()) > 100:
                    extracted_text = matches.group(1).strip()
                    # Double-check it doesn't contain unwanted JSON data
                    unwanted_check = ["chameleon", "voyager", "$type", "lixTreatment", "experimentId"]
                    if not any(term in extracted_text for term in unwanted_check):
                        result["description"] = extracted_text
                        result["extraction_methods"].append("pattern_matching")
                        logger.info("Found job description using pattern matching")
                        break

        # Clean up and validate results
        if result.get("description"):
            # Clean up description text
            desc = result["description"]
            
            # STRICTER VALIDATION: Check if it's JSON/config data
            # If it contains multiple JSON markers, it's likely not a real job description
            json_markers = [
                "\"$type\":", "\"locale\":", "\"lixTreatment\":", "\"chameleon", 
                "\"voyager", "experimentId", "treatmentIndex", "\"urn:li:",
                "configLixTrackingInfoListV2", "segmentIndex", "ChameleonConfig",
                "\"data\":{\"namespace\":", "\"message\":", "\"key\":\"i18n"
            ]
            
            # Count JSON markers
            marker_count = sum(1 for marker in json_markers if marker in desc)
            
            # If we have 3+ JSON markers, this is definitely unwanted config data
            if marker_count >= 3:
                logger.warning(f"Description contains {marker_count} JSON markers - filtering as config data")
                result["description"] = None
                result["extraction_methods"].remove("pattern_matching")
            else:
                # Only filter if the description is MOSTLY unwanted content (more than 30% unwanted)
                unwanted_patterns = [
                    "chameleon", "voyager", "ChameleonConfig", "lixTreatment",
                    "experimentId", "treatmentIndex", "$type", "configLixTrackingInfoListV2",
                    "urn:li:", "\"data\":{", "\"locale\":\"", "segmentIndex"
                ]
                
                # Count unwanted vs total content
                total_length = len(desc)
                unwanted_length = 0
                for pattern in unwanted_patterns:
                    unwanted_length += desc.count(pattern) * len(pattern)
                
                # Stricter threshold: 30% instead of 50%
                if total_length > 0 and (unwanted_length / total_length) > 0.3:
                    # Try to extract just the readable text part
                    lines = desc.split('\n')
                    clean_lines = []
                    for line in lines:
                        line = line.strip()
                        if (line and len(line) > 10 and 
                            not any(pattern in line for pattern in unwanted_patterns)):
                            clean_lines.append(line)
                    
                    if clean_lines and len('\n'.join(clean_lines)) > 100:
                        result["description"] = '\n'.join(clean_lines)
                        logger.info("Successfully cleaned unwanted config data from description")
                    else:
                        # If no substantial clean content found, remove the description
                        result["description"] = None
                        logger.warning("Filtered out unwanted config data - no clean content remaining")
            
            if result.get("description"):
                # Final cleanup
                result["description"] = re.sub(r'\n\s*\n', '\n\n', result["description"])
                result["description"] = result["description"].strip()
                
                # If description is too short after cleaning, remove it
                if len(result["description"]) < 50:
                    result["description"] = None
                    logger.warning("Description too short after cleaning")

        if result.get("title"):
            # Remove company name from title if it appears at the end
            title = result["title"]
            if result.get("company") and title.endswith(f" | {result['company']}"):
                result["title"] = title.replace(f" | {result['company']}", "").strip()

        # Log extraction success
        methods_used = ", ".join(result["extraction_methods"])
        logger.info(f"Data extraction completed using methods: {methods_used}")

        if result.get("description"):
            logger.info(f"Successfully extracted job description ({len(result['description'])} chars)")
        else:
            logger.warning("No job description found with any extraction method")
            # Save HTML for debugging when extraction fails
            job_id = result.get("job_id", "unknown")
            self._save_debug_html(html, job_id)

        # Format description with header fields at the top
        formatted_description = ""

        # Add header fields to description
        if result.get("title"):
            formatted_description += f"Job Title: {result['title']}\n"

        if result.get("company"):
            formatted_description += f"Company: {result['company']}\n"

        if result.get("company_url"):
            formatted_description += f"Company URL: {result['company_url']}\n"

        if result.get("location"):
            formatted_description += f"Location: {result['location']}\n"

        if result.get("posted_time"):
            formatted_description += f"Posted: {result['posted_time']}\n"

        # Add separator line if we have header fields
        if formatted_description:
            formatted_description += "\n" + "="*80 + "\n\n"

        # Add the actual job description
        if result.get("description"):
            formatted_description += result["description"]

        # Return structured result with formatted description
        structured_result = {
            "description": formatted_description if formatted_description else result.get("description"),
            "extraction_methods": result.get("extraction_methods", [])
        }

        return structured_result

    def _extract_profile_info(self, soup: BeautifulSoup, html: str) -> Dict[str, Any]:
        """Extract profile information"""
        result = {
            "name": None,
            "headline": None,
            "location": None,
            "about": None,
            "experience": [],
            "education": [],
            "skills": []
        }

        # Extract name
        name_elem = soup.find("h1", class_=re.compile("text-heading-xlarge"))
        if name_elem:
            result["name"] = name_elem.get_text(strip=True)

        # Extract headline
        headline_elem = soup.find("div", class_=re.compile("text-body-medium"))
        if headline_elem:
            result["headline"] = headline_elem.get_text(strip=True)

        # Extract about section
        about_section = soup.find("section", {"data-section": "summary"})
        if about_section:
            about_text = about_section.find("div", class_=re.compile("inline-show-more"))
            if about_text:
                result["about"] = about_text.get_text(separator="\n").strip()

        return result

    def _extract_company_info(self, soup: BeautifulSoup, html: str) -> Dict[str, Any]:
        """Extract company information"""
        result = {
            "name": None,
            "industry": None,
            "size": None,
            "headquarters": None,
            "about": None,
            "website": None
        }

        # Extract company name
        name_elem = soup.find("h1", class_=re.compile("org-top-card__name"))
        if name_elem:
            result["name"] = name_elem.get_text(strip=True)

        # Extract about section
        about_section = soup.find("section", class_=re.compile("org-about"))
        if about_section:
            about_text = about_section.find("p")
            if about_text:
                result["about"] = about_text.get_text(strip=True)

        return result

    def _extract_generic_content(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract generic content when type is unknown"""
        # Get main content area
        main_content = soup.find("main") or soup.find("body")

        if main_content:
            # Remove script and style tags
            for tag in main_content(["script", "style"]):
                tag.decompose()

            text = main_content.get_text(separator="\n").strip()
            # Clean up excessive whitespace
            text = re.sub(r'\n\s*\n', '\n\n', text)

            return {
                "raw_text": text[:10000],  # Limit to prevent huge responses
                "title": soup.title.string if soup.title else None
            }

        return {"error": "Could not extract content"}

    def batch_fetch(self, urls: List[str], bypass_cache: bool = False) -> List[Dict[str, Any]]:
        """Fetch multiple URLs (synchronous)"""
        results = []
        for url in urls:
            try:
                result = self.fetch_content(url, bypass_cache)
                results.append(result)
            except Exception as e:
                results.append({
                    "success": False,
                    "url": url,
                    "error": str(e),
                    "timestamp": time.time()
                })
            # Add delay between batch requests
            time.sleep(config.get_random_delay())

        return results

    def get_session_stats(self) -> Dict[str, Any]:
        """Get current session statistics"""
        return {
            "session_active": self.session is not None,
            "cookies_loaded": self.cookies_loaded,
            "request_count": self.request_count,
            "session_age": time.time() - self.session_created_at if self.session else 0,
            "last_request": self.last_request_time
        }


# Global scraper instance
scraper: Optional[LinkedInScraper] = None

def initialize_scraper() -> LinkedInScraper:
    """Initialize the global scraper"""
    global scraper
    scraper = LinkedInScraper()
    return scraper

def get_scraper() -> Optional[LinkedInScraper]:
    """Get the global scraper instance"""
    return scraper
