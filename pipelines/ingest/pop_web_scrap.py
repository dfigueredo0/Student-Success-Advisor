from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.firefox import GeckoDriverManager
import os
import re
import time

e_list = []
service = Service(executable_path=GeckoDriverManager().install())

driver = webdriver.Firefox(service=service)
driver.get("https://pop.weclarify.com/spring2025.html") # change this to the desired semester's URL

wait = WebDriverWait(driver, 15)
search_box = wait.until(EC.presence_of_element_located((By.ID, "search")))
search_box.clear()
search_box.send_keys("spring")      # [fall, spring, summer]
search_box.send_keys(Keys.ENTER)

wait.until(EC.presence_of_element_located((By.CLASS_NAME, "course")))
time.sleep(2)

SECTIONS_ID = re.compile(r"^[A-Za-z]{2,4}\s?-?\d{3}-sections$")
sections = [
    div for div in driver.find_elements(By.CSS_SELECTOR, 'div[id$="-sections"]')
    if SECTIONS_ID.match(div.get_attribute("id"))
]

for section in sections:
    # Layout for each course:
    #   <h2>AAH 119: Hist of World Architecture I</h2>   
    #   <p>catalog / evaluation links</p>                 
    #   <p>course description</p>                        
    #   <p><em>requirements</em></p>
    #   <div id="aah119-sections">...</div>
    header = section.find_element(By.XPATH, "preceding-sibling::h2[1]")
    description = header.find_element(By.XPATH, "following-sibling::p[2]")

    section_rows = []
    for row in section.find_elements(By.XPATH, ".//tr[td/a[@class='section']]"):
        semester = row.find_element(By.CSS_SELECTOR, "td.semester").text.strip()
        availability = row.find_element(By.CSS_SELECTOR, "a.section").text.strip()
        section_rows.append(f"{semester}: {availability}")

    e_list.append((header.text.strip(), description.text.strip(), section_rows))

# TODO: Currently outputs as a text file. Need to decide on outputting as a CSV or JSON.
output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "courses.txt")
with open(output_path, "w", encoding="utf-8") as f:
    for header, description, section_rows in e_list:
        f.write(header + "\n")
        f.write(description + "\n")
        for row in section_rows:
            f.write(row + "\n")
        f.write("\n")

print(f"Wrote {len(e_list)} courses to {output_path}")
driver.quit()