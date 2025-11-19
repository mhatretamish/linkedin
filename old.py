import tls_client


def load_cookies(session):
    import json

    try:
        with open("cookies.json", "r") as file:
            cookies = json.load(file)
            for cookie in cookies:
                session.cookies.set(
                    cookie["name"], cookie["value"], domain=cookie.get("domain")
                )
        print("Cookies loaded successfully.")
    except FileNotFoundError:
        print("cookies.json file not found. Proceeding without loading cookies.")
    except json.JSONDecodeError:
        print("Error decoding cookies.json. Proceeding without loading cookies.")


def fetch_linkedin_job_description(url):
    # Create a session
    session = tls_client.Session(client_identifier="chrome_140")

    # Set headers to mimic a real browser
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Referer": "https://www.linkedin.com/",
        "DNT": "1",
    }
    session.headers.update(headers)
    load_cookies(session)
    # Send a GET request to the URL
    response = session.get(url)
    print(response.status_code)
    if response.status_code == 200:
        # Parse the HTML content to find the job description
        from bs4 import BeautifulSoup

        print("Page fetched successfully.")
        # save the response to a file for inspection
        with open("linkedin_job_page.html", "w", encoding="utf-8") as file:
            file.write(response.text)
            file.close()
        soup = BeautifulSoup(response.text, "html.parser")

        # Try multiple selectors to find job description
        job_description_section = soup.find("section", class_="show-more-less-html")

        if not job_description_section:
            # Try finding the div directly
            job_description_section = soup.find(
                "div", class_="show-more-less-html__markup"
            )

        if not job_description_section:
            # Try with partial class match
            job_description_section = soup.find(
                "div", class_=lambda x: x and "show-more-less-html__markup" in x
            )

        if not job_description_section:
            # Try to find in script tags (LinkedIn often stores data in JSON)
            import re

            script_tags = soup.find_all("script", type="application/ld+json")
            for script in script_tags:
                if "description" in script.string:
                    try:
                        import json

                        data = json.loads(script.string)
                        if "description" in data:
                            return data["description"]
                    except:
                        pass

            # Try finding code blocks with job data
            code_blocks = soup.find_all("code")
            for code in code_blocks:
                if code.string and "description" in code.string:
                    try:
                        import json

                        data = json.loads(code.string)
                        if "data" in data and "description" in data["data"]:
                            desc = data["data"]["description"]
                            if isinstance(desc, dict) and "text" in desc:
                                return desc["text"].replace("\\n", "\n")
                    except:
                        pass

        if job_description_section:
            job_description = job_description_section.get_text(separator="\n").strip()
            return job_description
        else:
            print("Job description section not found.")
            return None
    else:
        print(f"Failed to retrieve the page. Status code: {response.status_code}")
        return None


if __name__ == "__main__":
    url = "https://www.linkedin.com/jobs/search/?currentJobId=4294605442&f_C=1586&originToLandingJobPostings=4294605442%2C4261075585%2C4300970694%2C4106004770&trk=d_flagship3_company"
    job_description = fetch_linkedin_job_description(url)
    if job_description:
        with open("job_description.txt", "w", encoding="utf-8") as file:
            file.write(job_description)
        print("Job description saved to job_description.txt")
    else:
        print("No job description found.")
