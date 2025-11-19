import tls_client
import json
import logging
import time
import re
import requests
import html
from typing import Dict, Optional, Any, List
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from abc import ABC, abstractmethod

from config import config
from scraper import LinkedInScraper

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Base class for all site-specific scrapers"""
    
    @abstractmethod
    def detect_url(self, url: str) -> bool:
        """Detect if URL belongs to this scraper's site"""
        pass
    
    @abstractmethod
    def scrape(self, url: str) -> Dict[str, Any]:
        """Scrape job/content from the URL"""
        pass
    
    @abstractmethod
    def normalize_url(self, url: str) -> str:
        """Normalize URL to standard format for the site"""
        pass


class InternshalaJobScraper(BaseScraper):
    """Scraper for Internshala job postings"""
    
    def __init__(self):
        self.session = None
        self.initialize_session()
    
    def initialize_session(self) -> None:
        """Initialize TLS client session for Internshala"""
        try:
            # Create new session with Chrome TLS identifier
            self.session = tls_client.Session(
                client_identifier="chrome_140",
                random_tls_extension_order=True
            )
            
            # Set headers to mimic a real browser
            self.session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            })
            
            logger.info("Internshala session initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize Internshala session: {e}")
            raise
    
    def detect_url(self, url: str) -> bool:
        """Detect if URL is from Internshala"""
        parsed = urlparse(url)
        return 'internshala.com' in parsed.netloc.lower()
    
    def normalize_url(self, url: str) -> str:
        """Normalize Internshala URL - they're usually already in good format"""
        parsed = urlparse(url)
        
        # Extract job ID from URL pattern like: /job/detail/title-jobId
        path = parsed.path
        
        # Pattern: /job/detail/job-title-at-company-12345678
        pattern = r'/job/detail/.*?-(\d{8,})'
        match = re.search(pattern, path)
        if match:
            job_id = match.group(1)
            logger.info(f"Extracted Internshala job ID: {job_id}")
        
        # For now, return the original URL as Internshala URLs are typically well-formed
        return url
    
    def scrape(self, url: str) -> Dict[str, Any]:
        """Scrape Internshala job posting"""
        start_time = time.time()
        original_url = url
        
        try:
            # Normalize URL
            url = self.normalize_url(url)
            if url != original_url:
                logger.info(f"Internshala URL normalized: {original_url} -> {url}")
            
            # Add rate limiting
            time.sleep(1)  # Be respectful to Internshala
            
            logger.info(f"Fetching Internshala job from: {url[:60]}...")
            
            # Make request
            response = self.session.get(url)
            
            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}")
            
            # Parse HTML
            soup = BeautifulSoup(response.text, "html.parser")
            processing_time = (time.time() - start_time) * 1000
            
            # Extract job information
            job_info = self._extract_job_info(soup)
            
            result = {
                "success": True,
                "type": "job",
                "platform": "internshala",
                "url": response.url,
                "original_url": original_url,
                "content": job_info,
                "timestamp": time.time(),
                "processing_time_ms": processing_time,
                "attempts": 1,
                "status_code": response.status_code,
                "response_size": len(response.text)
            }
            
            logger.info(f"Successfully extracted Internshala job content in {processing_time:.1f}ms")
            return result
            
        except Exception as e:
            processing_time = (time.time() - start_time) * 1000
            logger.error(f"Failed to scrape Internshala job: {e}")
            
            return {
                "success": False,
                "type": "job",
                "platform": "internshala",
                "url": url,
                "original_url": original_url,
                "error": str(e),
                "timestamp": time.time(),
                "processing_time_ms": processing_time,
                "attempts": 1
            }
    
    def _extract_job_info(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract comprehensive job information from Internshala page and format like LinkedIn"""
        # Temporary storage for extracted data
        temp_data = {}

        # 1. Extract Job Title
        title_elem = soup.find("h1", class_="heading_2_4 heading_title")
        if title_elem:
            temp_data["title"] = title_elem.get_text(strip=True)

        # Alternative title extraction from profile section
        if not temp_data.get("title"):
            profile_elem = soup.find("div", class_="heading_4_5 profile")
            if profile_elem:
                temp_data["title"] = profile_elem.get_text(strip=True)

        # 2. Extract Company Name
        company_link = soup.find("a", class_="link_display_like_text")
        if company_link:
            temp_data["company"] = company_link.get_text(strip=True)

        # 3. Extract Location
        location_elem = soup.find("p", id="location_names")
        if location_elem:
            location_links = location_elem.find_all("a")
            if location_links:
                locations = [link.get_text(strip=True) for link in location_links]
                temp_data["location"] = ", ".join(locations)
            else:
                temp_data["location"] = location_elem.get_text(strip=True).replace("📍", "").strip()

        # 4. Extract Job Description from "About the job" section
        job_description = None
        internship_details = soup.find("div", class_="internship_details")
        if internship_details:
            about_job_heading = internship_details.find("h2", string=re.compile(r"About the job", re.IGNORECASE))
            if about_job_heading:
                text_container = about_job_heading.find_next("div", class_="text-container")
                if text_container:
                    job_description = text_container.get_text(separator="\n", strip=True)

        # 5. Extract Start Date
        start_date_elem = soup.find("div", id="start-date-first")
        if start_date_elem:
            temp_data["start_date"] = start_date_elem.get_text(strip=True)

        # 6. Extract Salary Information
        salary_elem = soup.find("div", class_="item_body salary")
        if salary_elem:
            temp_data["salary"] = salary_elem.get_text(strip=True)

        # Extract detailed salary breakdown
        salary_breakdown = {}
        salary_container = soup.find("div", class_="text-container salary_container")
        if salary_container:
            salary_paragraphs = salary_container.find_all("p")
            for p in salary_paragraphs:
                text = p.get_text(strip=True)
                if "Annual CTC:" in text:
                    temp_data["salary"] = text.replace("Annual CTC:", "").strip()
                elif "Fixed pay:" in text:
                    salary_breakdown["fixed"] = text.replace("1. Fixed pay:", "").strip()
                elif "Variable pay:" in text:
                    salary_breakdown["variable"] = text.replace("2. Variable pay:", "").strip()

        # 7. Extract Experience Required
        experience_elem = soup.find("div", class_="other_detail_item job-experience-item")
        if experience_elem:
            exp_body = experience_elem.find("div", class_="item_body")
            if exp_body:
                temp_data["experience"] = exp_body.get_text(strip=True)

        # 8. Extract Apply By Date
        apply_by_items = soup.find_all("div", class_="item_heading")
        for item in apply_by_items:
            if "Apply By" in item.get_text():
                apply_by_body = item.find_next("div", class_="item_body")
                if apply_by_body:
                    temp_data["apply_by"] = apply_by_body.get_text(strip=True)
                    break

        # 9. Extract Posted Date
        posted_elem = soup.find("div", class_="status status-small status-inactive")
        if posted_elem and "Posted" in posted_elem.get_text():
            temp_data["posted_date"] = posted_elem.get_text(strip=True)

        # 10. Extract Employment Type (Job/Internship)
        job_type_elem = soup.find("div", class_="status status-small status-inactive", string="Job")
        if job_type_elem:
            temp_data["employment_type"] = "Job"
        else:
            internship_type_elem = soup.find("div", class_="status status-small status-inactive", string="Internship")
            if internship_type_elem:
                temp_data["employment_type"] = "Internship"

        # 11. Extract Applicants Count
        applicants_elem = soup.find("div", class_="applications_message")
        if applicants_elem:
            applicants_text = applicants_elem.get_text(strip=True)
            match = re.search(r'(\d+)\s+applicants?', applicants_text, re.IGNORECASE)
            if match:
                temp_data["applicants_count"] = int(match.group(1))

        # 12. Extract Skills Required
        skills_list = []
        skills_heading = soup.find("h3", class_="section_heading heading_5_5 skills_heading")
        if skills_heading:
            skills_container = skills_heading.find_next("div", class_="round_tabs_container")
            if skills_container:
                skill_elements = skills_container.find_all("span", class_="round_tabs")
                skills_list = [skill.get_text(strip=True) for skill in skill_elements]

        # 13. Extract "Who can apply" information
        who_can_apply = None
        who_can_apply_heading = soup.find("p", class_="section_heading heading_5_5", string="Who can apply")
        if who_can_apply_heading:
            who_can_apply_container = who_can_apply_heading.find_next("div", class_="text-container who_can_apply")
            if who_can_apply_container:
                who_can_apply = who_can_apply_container.get_text(separator="\n", strip=True)

        # 14. Extract Number of Openings
        openings_heading = soup.find("h3", class_="section_heading heading_5_5", string="Number of openings")
        if openings_heading:
            openings_container = openings_heading.find_next("div", class_="text-container")
            if openings_container:
                openings_text = openings_container.get_text(strip=True)
                temp_data["openings"] = openings_text

        # 15. Extract About Company Information
        about_company = None
        about_company_heading = soup.find("h2", class_="section_heading heading_5_5")
        if about_company_heading and "About" in about_company_heading.get_text():
            about_company_text = soup.find("div", class_="text-container about_company_text_container")
            if about_company_text:
                about_company = about_company_text.get_text(strip=True)

            # Extract company website
            website_link = soup.find("div", class_="text-container website_link")
            if website_link:
                website_elem = website_link.find("a")
                if website_elem:
                    temp_data["company_website"] = website_elem.get("href")

        # 16. Extract Job ID from URL (if available in the HTML)
        job_id = None
        url_input = soup.find("input", {"name": "link"})
        if url_input:
            url_value = url_input.get("value", "")
            match = re.search(r'job-in-[^-]+-at-[^-]+-(\d+)', url_value)
            if match:
                job_id = match.group(1)

        # Now build the LinkedIn-style formatted description
        description_parts = []

        # Add company info at the top (like LinkedIn)
        if about_company:
            description_parts.append(f"About {temp_data.get('company', 'the Company')}:\n\n{about_company}")

        # Add the main job description
        if job_description:
            description_parts.append(f"\nJob Description:\n\n{job_description}")

        # Add job details section
        job_details = []

        if temp_data.get("employment_type"):
            job_details.append(f"Employment Type: {temp_data['employment_type']}")

        if temp_data.get("location"):
            job_details.append(f"Location: {temp_data['location']}")

        if temp_data.get("experience"):
            job_details.append(f"Experience Required: {temp_data['experience']}")

        if temp_data.get("salary"):
            salary_text = f"Salary: {temp_data['salary']}"
            if salary_breakdown:
                if salary_breakdown.get("fixed"):
                    salary_text += f"\n  - Fixed: {salary_breakdown['fixed']}"
                if salary_breakdown.get("variable"):
                    salary_text += f"\n  - Variable: {salary_breakdown['variable']}"
            job_details.append(salary_text)

        if temp_data.get("start_date"):
            job_details.append(f"Start Date: {temp_data['start_date']}")

        if temp_data.get("openings"):
            job_details.append(f"Number of Openings: {temp_data['openings']}")

        if temp_data.get("apply_by"):
            job_details.append(f"Apply By: {temp_data['apply_by']}")

        if temp_data.get("posted_date"):
            job_details.append(f"Posted: {temp_data['posted_date']}")

        if temp_data.get("applicants_count"):
            job_details.append(f"Applicants: {temp_data['applicants_count']}")

        if job_details:
            description_parts.append("\n\nJob Details:\n\n" + "\n".join(job_details))

        # Add skills section
        if skills_list:
            description_parts.append("\n\nSkills Required:\n\n" + ", ".join(skills_list))

        # Add who can apply section
        if who_can_apply:
            description_parts.append(f"\n\nWho Can Apply:\n\n{who_can_apply}")

        # Add company website if available
        if temp_data.get("company_website"):
            description_parts.append(f"\n\nCompany Website: {temp_data['company_website']}")

        # Combine all parts into final description
        final_description = "\n".join(description_parts)

        # Clean up formatting
        final_description = re.sub(r'\n\s*\n\s*\n', '\n\n', final_description)  # Remove excessive newlines
        final_description = final_description.strip()

        # Return in LinkedIn format (only description and job_id in content)
        result = {
            "description": final_description
        }

        # Add job_id if found
        if job_id:
            result["job_id"] = job_id

        return result


class IndeedJobScraper(BaseScraper):
    """Scraper for Indeed job postings"""
    
    def __init__(self):
        self.session = None
        self.initialize_session()
    
    def initialize_session(self) -> None:
        """Initialize TLS client session for Indeed"""
        try:
            # Create new session with Chrome TLS identifier
            self.session = tls_client.Session(
                client_identifier="chrome_140",
                random_tls_extension_order=True
            )
            
            # Set headers to mimic a real browser
            self.session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Cache-Control": "max-age=0"
            })
            
            logger.info("Indeed session initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize Indeed session: {e}")
            raise
    
    def detect_url(self, url: str) -> bool:
        """Detect if URL is from Indeed"""
        parsed = urlparse(url)
        return 'indeed.com' in parsed.netloc.lower()
    
    def normalize_url(self, url: str) -> str:
        """
        Normalize Indeed URL to standard format
        
        Indeed URLs typically contain 'jk' parameter with job key
        Example: https://in.indeed.com/viewjob?jk=f521d46062b182d1&...
        We want to extract the jk parameter and create a clean URL
        """
        parsed = urlparse(url)
        
        # Extract job key (jk parameter) from URL
        query_params = parse_qs(parsed.query)
        job_key = query_params.get('jk')
        
        if job_key:
            job_key = job_key[0]
            logger.info(f"Extracted Indeed job key: {job_key}")
            
            # Create normalized URL with just the essential parameters
            # Keep the original domain (in.indeed.com, ca.indeed.com, etc.)
            base_domain = parsed.netloc if parsed.netloc else "in.indeed.com"
            normalized_url = f"https://{base_domain}/viewjob?jk={job_key}"
            
            logger.info(f"Indeed URL normalized: {url[:60]}... -> {normalized_url}")
            return normalized_url
        
        # If no job key found, return original URL
        logger.warning(f"Could not extract job key from Indeed URL: {url}")
        return url
    
    def scrape(self, url: str) -> Dict[str, Any]:
        """Scrape Indeed job posting"""
        start_time = time.time()
        original_url = url
        
        try:
            # Normalize URL
            url = self.normalize_url(url)
            if url != original_url:
                logger.info(f"Indeed URL normalized: {original_url[:60]}... -> {url[:60]}...")
            
            # Add rate limiting
            time.sleep(1)  # Be respectful to Indeed
            
            logger.info(f"Fetching Indeed job from: {url[:60]}...")
            
            # Make request
            response = self.session.get(url)
            
            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}")
            
            # Parse HTML
            soup = BeautifulSoup(response.text, "html.parser")
            processing_time = (time.time() - start_time) * 1000
            
            # Extract job information
            job_info = self._extract_job_info(soup, response.text)
            
            result = {
                "success": True,
                "type": "job",
                "platform": "indeed",
                "url": response.url,
                "original_url": original_url,
                "content": job_info,
                "timestamp": time.time(),
                "processing_time_ms": processing_time,
                "attempts": 1,
                "status_code": response.status_code,
                "response_size": len(response.text)
            }
            
            logger.info(f"Successfully extracted Indeed job content in {processing_time:.1f}ms")
            return result
            
        except Exception as e:
            processing_time = (time.time() - start_time) * 1000
            logger.error(f"Failed to scrape Indeed job: {e}")
            
            return {
                "success": False,
                "type": "job",
                "platform": "indeed",
                "url": url,
                "original_url": original_url,
                "content": {},
                "error": str(e),
                "timestamp": time.time(),
                "processing_time_ms": processing_time,
                "attempts": 1
            }
    
    def _extract_job_info(self, soup: BeautifulSoup, html: str) -> Dict[str, Any]:
        """Extract comprehensive job information from Indeed page and format like LinkedIn"""
        # Temporary storage for extracted data
        temp_data = {
            "description": None,
            "title": None,
            "company": None,
            "location": None,
            "salary": None,
            "job_type": None,
            "benefits": [],
            "required_skills": [],
            "additional_attributes": []
        }

        # Method 1: Extract from JSON data in script tags (most reliable for Indeed)
        json_data = self._extract_json_data(html)
        if json_data:
            for key, value in json_data.items():
                if key in temp_data and value:
                    temp_data[key] = value

        # Method 2: Extract from meta tags
        meta_data = self._extract_meta_data(soup)
        if meta_data:
            for key, value in meta_data.items():
                if key in temp_data and value and not temp_data.get(key):
                    temp_data[key] = value

        # Method 3: Extract from page title
        if not temp_data.get("title"):
            title_tag = soup.find("title")
            if title_tag and title_tag.string:
                title_text = title_tag.string.strip()
                # Clean up Indeed's title format "Job Title - Company Name - Indeed"
                title_text = re.sub(r'\s*-\s*Indeed\s*$', '', title_text, flags=re.IGNORECASE)
                if ' - ' in title_text:
                    parts = title_text.split(' - ')
                    if len(parts) >= 2:
                        temp_data["title"] = parts[0].strip()
                        if not temp_data.get("company"):
                            temp_data["company"] = parts[1].strip()
                else:
                    temp_data["title"] = title_text

        # Method 4: Extract from structured HTML content
        if not temp_data.get("description"):
            description_selectors = [
                "#jobDescriptionText",
                ".jobsearch-jobDescriptionText",
                ".jobsearch-JobComponent-description",
                "[data-testid='job-description']",
                ".icl-u-xs-mt--xs",
                "div[id*='job-description']",
                "div[class*='jobDescription']"
            ]

            for selector in description_selectors:
                element = soup.select_one(selector)
                if element:
                    desc_text = element.get_text(separator="\n", strip=True)
                    if desc_text and len(desc_text) > 50:
                        temp_data["description"] = desc_text
                        break

        # Method 5: Extract salary information
        if not temp_data.get("salary"):
            salary_selectors = [
                ".salary",
                ".jobsearch-JobMetadataHeader-item",
                "[data-testid='job-salary']",
                ".icl-u-xs-mr--xs"
            ]

            for selector in salary_selectors:
                element = soup.select_one(selector)
                if element:
                    salary_text = element.get_text(strip=True)
                    if any(currency in salary_text for currency in ["₹", "$", "£", "€"]) or "salary" in salary_text.lower():
                        temp_data["salary"] = salary_text
                        break

        # Method 6: Extract location
        if not temp_data.get("location"):
            location_selectors = [
                "[data-testid='job-location']",
                ".jobsearch-JobMetadataHeader-item",
                ".icl-u-xs-mt--xs"
            ]

            for selector in location_selectors:
                elements = soup.select(selector)
                for element in elements:
                    location_text = element.get_text(strip=True)
                    if location_text:
                        temp_data["location"] = location_text
                        break
                if temp_data.get("location"):
                    break

        # Try to extract additional job details if not found
        if not temp_data.get("title") or not temp_data.get("company"):
            title_patterns = [
                r'"jobTitle"\s*:\s*"([^"]+)"',
                r'"title"\s*:\s*"([^"]+)"',
                r'"name"\s*:\s*"([^"]+)"'
            ]
            company_patterns = [
                r'"hiringOrganization"[^}]*"name"\s*:\s*"([^"]+)"',
                r'"companyName"\s*:\s*"([^"]+)"',
                r'"employer"[^}]*"name"\s*:\s*"([^"]+)"'
            ]

            if not temp_data.get("title"):
                for pattern in title_patterns:
                    title_match = re.search(pattern, html)
                    if title_match:
                        temp_data["title"] = title_match.group(1)
                        break

            if not temp_data.get("company"):
                for pattern in company_patterns:
                    company_match = re.search(pattern, html)
                    if company_match:
                        temp_data["company"] = company_match.group(1)
                        break

        # Now build LinkedIn-style formatted description
        description_parts = []

        # Add company info at the top if available
        if temp_data.get("company"):
            description_parts.append(f"Company: {temp_data['company']}")

        # Add the main job description
        if temp_data.get("description"):
            # Clean up description
            description = temp_data["description"]
            description = re.sub(r'\n\s*\n', '\n\n', description)
            description = re.sub(r'\s+', ' ', description)
            description_parts.append(f"\n\n{description.strip()}")

        # Add job details section
        job_details = []

        if temp_data.get("job_type"):
            job_details.append(f"Job Type: {temp_data['job_type']}")

        if temp_data.get("location"):
            job_details.append(f"Location: {temp_data['location']}")

        if temp_data.get("salary"):
            job_details.append(f"Salary: {temp_data['salary']}")

        if job_details:
            description_parts.append("\n\nJob Details:\n\n" + "\n".join(job_details))

        # Add skills section (deduplicate)
        if temp_data.get("required_skills") and isinstance(temp_data["required_skills"], list):
            unique_skills = list(set(temp_data["required_skills"]))
            if unique_skills:
                description_parts.append("\n\nSkills Required:\n\n" + ", ".join(unique_skills))

        # Add benefits section (deduplicate)
        if temp_data.get("benefits") and isinstance(temp_data["benefits"], list):
            unique_benefits = list(set(temp_data["benefits"]))
            if unique_benefits:
                description_parts.append("\n\nBenefits:\n\n" + ", ".join(unique_benefits))

        # Combine all parts into final description
        final_description = "".join(description_parts)

        # Clean up formatting
        final_description = re.sub(r'\n\s*\n\s*\n', '\n\n', final_description)
        final_description = final_description.strip()

        # Extract job ID from URL if available
        job_id = None
        match = re.search(r'jk=([a-f0-9]+)', html)
        if match:
            job_id = match.group(1)

        # Return in LinkedIn format (only description and job_id in content)
        result = {
            "description": final_description
        }

        # Add job_id if found
        if job_id:
            result["job_id"] = job_id

        return result
    
    def _extract_json_data(self, html: str) -> Dict[str, Any]:
        """Extract comprehensive job data from JSON embedded in Indeed HTML"""
        result = {}
        
        # Look for various JSON patterns in Indeed pages
        json_patterns = [
            # Pattern 1: Main job data object (comprehensive)
            r'"job"\s*:\s*({[^}]*"jk"\s*:\s*"[^"]+[^}]*})',
            # Pattern 2: window._initialData or similar
            r'window\._initialData\s*=\s*({.+?});',
            # Pattern 3: Job description object with all fields
            r'"description"\s*:\s*({[^}]*"__typename"\s*:\s*"JobDescription"[^}]*})',
            # Pattern 4: Location object
            r'"location"\s*:\s*({[^}]*"__typename"\s*:\s*"JobLocation"[^}]*})',
            # Pattern 5: Employer/Company information
            r'"employer"\s*:\s*({[^}]*"name"\s*:\s*"[^"]+[^}]*})',
            # Pattern 6: Salary information
            r'"estimatedSalary"\s*:\s*({[^}]*"min"\s*:\s*[0-9]+[^}]*})',
            # Pattern 7: Benefits and attributes
            r'"benefits"\s*:\s*(\[[^\]]*\])',
            # Pattern 8: Job attributes
            r'"attributes"\s*:\s*(\[[^\]]*\])',
            # Pattern 9: Sanitized job description (fallback)
            r'"sanitizedJobDescription"\s*:\s*"([^"]+)"',
            # Pattern 10: Text description (fallback)
            r'"text"\s*:\s*"([^"]+)"'
        ]
        
        for pattern in json_patterns:
            try:
                matches = re.finditer(pattern, html, re.DOTALL | re.IGNORECASE)
                for match in matches:
                    match_text = match.group(0)
                    
                    # Handle different types of JSON data
                    if '"description"' in match_text and '"__typename": "JobDescription"' in match_text:
                        # Extract comprehensive description data
                        desc_data = self._parse_description_json(match_text)
                        if desc_data:
                            result.update(desc_data)
                    
                    elif '"location"' in match_text and '"__typename": "JobLocation"' in match_text:
                        # Extract comprehensive location data
                        location_data = self._parse_location_json(match_text)
                        if location_data:
                            result.update(location_data)
                    
                    elif '"benefits"' in match_text and isinstance(match_text, str):
                        # Extract benefits information
                        benefits_data = self._parse_benefits_json(match_text)
                        if benefits_data:
                            result.update(benefits_data)
                    
                    elif '"attributes"' in match_text and isinstance(match_text, str):
                        # Extract job attributes
                        attributes_data = self._parse_attributes_json(match_text)
                        if attributes_data:
                            result.update(attributes_data)
                    
                    elif '"employer"' in match_text or '"hiringOrganization"' in match_text:
                        # Extract company information
                        company_data = self._parse_company_json(match_text)
                        if company_data:
                            result.update(company_data)
                    
                    elif '"estimatedSalary"' in match_text or '"baseSalary"' in match_text:
                        # Extract salary information
                        salary_data = self._parse_salary_json(match_text)
                        if salary_data:
                            result.update(salary_data)
                    
                    elif "sanitizedJobDescription" in match_text:
                        # Extract the sanitized description (fallback)
                        desc_match = re.search(r'"sanitizedJobDescription"\s*:\s*"([^"]+)"', match_text)
                        if desc_match and not result.get("description"):
                            raw_desc = desc_match.group(1)
                            clean_desc = self._clean_html_content(raw_desc)
                            if len(clean_desc) > 100:
                                result["description"] = clean_desc
                    
                    elif '"text"' in match_text and 'description' in match_text.lower():
                        # Extract from text field in description object (fallback)
                        text_match = re.search(r'"text"\s*:\s*"([^"]+)"', match_text)
                        if text_match and not result.get("description"):
                            raw_text = text_match.group(1)
                            clean_text = self._clean_text_content(raw_text)
                            if len(clean_text) > 100:
                                result["description"] = clean_text
                
                # Break if we found substantial content
                if result.get("description") and len(result.get("description", "")) > 200:
                    break
                    
            except Exception as e:
                logger.debug(f"JSON pattern {pattern[:30]}... failed: {e}")
                continue
        
        return result
    
    def _parse_description_json(self, json_text: str) -> Dict[str, Any]:
        """Parse description JSON object for comprehensive job description data"""
        result = {}
        try:
            # Extract HTML content
            html_match = re.search(r'"html"\s*:\s*"([^"]+)"', json_text)
            if html_match:
                raw_html = html_match.group(1)
                clean_desc = self._clean_html_content(raw_html)
                if clean_desc and len(clean_desc) > 50:
                    result["description"] = clean_desc
            
            # Extract plain text content as fallback
            if not result.get("description"):
                text_match = re.search(r'"text"\s*:\s*"([^"]+)"', json_text)
                if text_match:
                    raw_text = text_match.group(1)
                    clean_text = self._clean_text_content(raw_text)
                    if clean_text and len(clean_text) > 50:
                        result["description"] = clean_text
        except Exception as e:
            logger.debug(f"Description JSON parsing failed: {e}")
        
        return result
    
    def _parse_location_json(self, json_text: str) -> Dict[str, Any]:
        """Parse location JSON object for comprehensive location data"""
        result = {}
        try:
            # Extract formatted location
            formatted_match = re.search(r'"formatted"\s*:\s*{[^}]*"long"\s*:\s*"([^"]+)"', json_text)
            if formatted_match:
                result["location"] = formatted_match.group(1)
            
            # Extract individual location components
            city_match = re.search(r'"admin3Name"\s*:\s*"([^"]+)"', json_text)
            state_match = re.search(r'"admin1Name"\s*:\s*"([^"]+)"', json_text)
            country_match = re.search(r'"countryCode"\s*:\s*"([^"]+)"', json_text)
            street_match = re.search(r'"streetAddress"\s*:\s*"([^"]+)"', json_text)
            
            # Build detailed location if formatted not available
            if not result.get("location"):
                location_parts = []
                if street_match:
                    location_parts.append(street_match.group(1))
                if city_match:
                    location_parts.append(city_match.group(1))
                if state_match:
                    location_parts.append(state_match.group(1))
                
                if location_parts:
                    result["location"] = ", ".join(location_parts)
            
            # Extract coordinates if available
            lat_match = re.search(r'"latitude"\s*:\s*([0-9.-]+)', json_text)
            lng_match = re.search(r'"longitude"\s*:\s*([0-9.-]+)', json_text)
            if lat_match and lng_match:
                result["coordinates"] = {
                    "latitude": float(lat_match.group(1)),
                    "longitude": float(lng_match.group(1))
                }
        except Exception as e:
            logger.debug(f"Location JSON parsing failed: {e}")
        
        return result
    
    def _parse_benefits_json(self, json_text: str) -> Dict[str, Any]:
        """Parse benefits JSON array for job benefits"""
        result = {}
        try:
            # Extract all benefit labels
            benefit_matches = re.findall(r'"label"\s*:\s*"([^"]+)"', json_text)
            if benefit_matches:
                result["benefits"] = benefit_matches
        except Exception as e:
            logger.debug(f"Benefits JSON parsing failed: {e}")
        
        return result
    
    def _parse_attributes_json(self, json_text: str) -> Dict[str, Any]:
        """Parse attributes JSON array for job attributes and skills"""
        result = {}
        try:
            # Extract all attribute labels
            attribute_matches = re.findall(r'"label"\s*:\s*"([^"]+)"', json_text)
            if attribute_matches:
                # Separate different types of attributes
                skills = []
                job_types = []
                other_attrs = []
                
                for attr in attribute_matches:
                    attr_lower = attr.lower()
                    skill_keywords = getattr(config, "SKILL_KEYWORDS", ['excel', 'communication', 'negotiation', 'networking'])
                    if any(skill_word in attr_lower for skill_word in skill_keywords):
                        skills.append(attr)
                    elif any(type_word in attr_lower for type_word in ['full-time', 'part-time', 'contract', 'in-person', 'remote']):
                        job_types.append(attr)
                    else:
                        other_attrs.append(attr)
                
                if skills:
                    result["required_skills"] = skills
                if job_types:
                    result["job_type"] = ", ".join(job_types)
                if other_attrs:
                    result["additional_attributes"] = other_attrs
        except Exception as e:
            logger.debug(f"Attributes JSON parsing failed: {e}")
        
        return result
    
    def _parse_company_json(self, json_text: str) -> Dict[str, Any]:
        """Parse company/employer JSON for company information"""
        result = {}
        try:
            # Extract company name
            name_patterns = [
                r'"name"\s*:\s*"([^"]+)"',
                r'"hiringOrganization"[^}]*"name"\s*:\s*"([^"]+)"',
                r'"employer"[^}]*"name"\s*:\s*"([^"]+)"'
            ]
            
            for pattern in name_patterns:
                match = re.search(pattern, json_text)
                if match:
                    result["company"] = match.group(1)
                    break
        except Exception as e:
            logger.debug(f"Company JSON parsing failed: {e}")
        
        return result
    
    def _parse_salary_json(self, json_text: str) -> Dict[str, Any]:
        """Parse salary JSON for compensation information"""
        result = {}
        try:
            # Extract salary range
            min_match = re.search(r'"min"\s*:\s*([0-9.]+)', json_text)
            max_match = re.search(r'"max"\s*:\s*([0-9.]+)', json_text)
            currency_match = re.search(r'"currency"\s*:\s*"([^"]+)"', json_text)
            period_match = re.search(r'"unitText"\s*:\s*"([^"]+)"', json_text)
            
            if min_match or max_match:
                salary_parts = []
                currency = currency_match.group(1) if currency_match else "₹"
                period = period_match.group(1) if period_match else "month"
                
                if min_match and max_match:
                    salary_parts.append(f"{currency}{min_match.group(1)} - {currency}{max_match.group(1)} per {period}")
                elif min_match:
                    salary_parts.append(f"From {currency}{min_match.group(1)} per {period}")
                elif max_match:
                    salary_parts.append(f"Up to {currency}{max_match.group(1)} per {period}")
                
                if salary_parts:
                    result["salary"] = salary_parts[0]
        except Exception as e:
            logger.debug(f"Salary JSON parsing failed: {e}")
        
        return result
    
    def _clean_html_content(self, raw_html: str) -> str:
        """Clean HTML encoded content and convert to readable text"""
        try:
            import html
            # Decode HTML entities and unescape
            decoded_desc = html.unescape(raw_html)
            # Remove HTML tags but preserve structure
            decoded_desc = re.sub(r'\\u[0-9a-fA-F]{4}', '', decoded_desc)  # Remove unicode escapes
            decoded_desc = re.sub(r'\\[nt]', '\n', decoded_desc)  # Convert \n, \t to actual newlines
            decoded_desc = re.sub(r'\\/', '/', decoded_desc)  # Unescape forward slashes
            
            # Parse HTML to text
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(decoded_desc, 'html.parser')
            clean_text = soup.get_text(separator='\n', strip=True)
            
            return clean_text.strip()
        except Exception as e:
            logger.debug(f"HTML cleaning failed: {e}")
            return raw_html
    
    def _clean_text_content(self, raw_text: str) -> str:
        """Clean raw text content"""
        try:
            import html
            # Clean up the text
            clean_text = html.unescape(raw_text)
            clean_text = re.sub(r'\\n', '\n', clean_text)
            clean_text = re.sub(r'\\u[0-9a-fA-F]{4}', '', clean_text)
            clean_text = re.sub(r'\\/', '/', clean_text)
            
            return clean_text.strip()
        except Exception as e:
            logger.debug(f"Text cleaning failed: {e}")
            return raw_text
    
    def _extract_meta_data(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract job data from meta tags"""
        result = {}
        
        # OpenGraph meta tags
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            result["title"] = og_title["content"].replace(" - Indeed", "").strip()
        
        og_description = soup.find("meta", property="og:description")
        if og_description and og_description.get("content"):
            result["description"] = og_description["content"]
        
        # Twitter meta tags as fallback
        if not result.get("title"):
            twitter_title = soup.find("meta", attrs={"name": "twitter:title"})
            if twitter_title and twitter_title.get("content"):
                result["title"] = twitter_title["content"].replace(" - Indeed", "").strip()
        
        if not result.get("description"):
            twitter_desc = soup.find("meta", attrs={"name": "twitter:description"})
            if twitter_desc and twitter_desc.get("content"):
                result["description"] = twitter_desc["content"]
        
        return result


class UniversalJobScraper:
    """Universal scraper that routes to appropriate site-specific scrapers"""
    
    def __init__(self):
        self.scrapers = [
            LinkedInScraper(),
            InternshalaJobScraper(),
            IndeedJobScraper()
        ]
        logger.info(f"UniversalJobScraper initialized with {len(self.scrapers)} scrapers")
    
    def detect_site(self, url: str) -> Optional[BaseScraper]:
        """Detect which scraper should handle the URL"""
        for scraper in self.scrapers:
            if hasattr(scraper, 'detect_url') and scraper.detect_url(url):
                return scraper
            elif isinstance(scraper, LinkedInScraper) and self._is_linkedin_url(url):
                return scraper
        return None
    
    def _is_linkedin_url(self, url: str) -> bool:
        """Check if URL is from LinkedIn"""
        parsed = urlparse(url)
        return 'linkedin.com' in parsed.netloc.lower()
    
    def scrape(self, url: str) -> Dict[str, Any]:
        """Scrape job/content from any supported site"""
        start_time = time.time()
        
        try:
            # Detect appropriate scraper
            scraper = self.detect_site(url)
            
            if not scraper:
                parsed = urlparse(url)
                supported_sites = ["linkedin.com", "internshala.com", "indeed.com"]
                return {
                    "success": False,
                    "type": "unknown",
                    "platform": "unsupported",
                    "url": url,
                    "content": {},
                    "error": f"Unsupported site: {parsed.netloc}. Supported sites: {', '.join(supported_sites)}",
                    "timestamp": time.time(),
                    "processing_time_ms": (time.time() - start_time) * 1000
                }
            
            # Determine platform name
            platform = "unknown"
            if isinstance(scraper, LinkedInScraper):
                platform = "linkedin"
            elif isinstance(scraper, InternshalaJobScraper):
                platform = "internshala"
            elif isinstance(scraper, IndeedJobScraper):
                platform = "indeed"
            
            logger.info(f"Using {platform} scraper for URL: {url[:60]}...")
            
            # Use the appropriate scraper
            if isinstance(scraper, LinkedInScraper):
                # Use existing LinkedIn scraper method
                result = scraper.fetch_content(url)
                # Normalize the response format for consistency
                if isinstance(result, dict):
                    # Add platform info
                    result["platform"] = "linkedin"
                    
                    # Ensure content field exists (required by ScrapeResponse model)
                    if "content" not in result:
                        if result.get("success", False):
                            # For successful LinkedIn results, extract content from the result
                            content = {}
                            for key in ["description", "title", "company", "location", "extraction_methods"]:
                                if key in result:
                                    content[key] = result[key]
                            result["content"] = content
                        else:
                            # For failed results, ensure empty content dict
                            result["content"] = {}
            else:
                # Use the new BaseScraper interface
                result = scraper.scrape(url)
            
            return result
            
        except Exception as e:
            processing_time = (time.time() - start_time) * 1000
            logger.error(f"Universal scraper error: {e}")
            
            return {
                "success": False,
                "type": "unknown",
                "platform": "error",
                "url": url,
                "content": {},
                "error": str(e),
                "timestamp": time.time(),
                "processing_time_ms": processing_time
            }
    
    def get_supported_sites(self) -> List[str]:
        """Get list of supported sites"""
        return ["linkedin.com", "internshala.com", "indeed.com"]