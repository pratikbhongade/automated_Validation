import time
from selenium import webdriver
from selenium.webdriver.common.by import By
import pyautogui
from PIL import Image, ImageDraw

# Function to create a circular highlight image
def create_highlight_image(radius=30, color=(255, 0, 0), thickness=5):
    size = (radius * 2, radius * 2)
    img = Image.new("RGBA", size, (0, 0, 0, 0))  # Create a transparent image
    draw = ImageDraw.Draw(img)
    draw.ellipse((thickness, thickness, size[0] - thickness, size[1] - thickness), outline=color, width=thickness)
    return img

# Function to display the highlight around the mouse cursor
def highlight_mouse(x, y, duration=0.5):
    highlight_image = create_highlight_image()
    highlight_image.show()
    
    # Move the image window to the mouse position (this would require additional control or a custom window)
    # Simulating that the highlight stays at the mouse position

    # Move the mouse to the desired position
    pyautogui.moveTo(x, y)

    # Show the highlight for the specified duration
    time.sleep(duration)

    # Hide the highlight (since the image will be automatically closed after duration)
    highlight_image.close()

# Ask the user for the validation portal link
validation_portal_link = input("Please enter the validation portal link: ")

# Initialize the Selenium WebDriver (Edge/Chrome)
driver = webdriver.Edge()  # or webdriver.Chrome(), depending on your setup

# Step 2: Navigate to the provided link
driver.get(validation_portal_link)

# Step 3: Find the 'Set Testing Results' button and click it
try:
    set_testing_results_button = driver.find_element(By.XPATH, "//button[@type='Button' and contains(text(),'Set Testing Results')]")
    set_testing_results_button.click()
    print("Set Testing Results button clicked.")
except Exception as e:
    print(f"Error clicking Set Testing Results button: {e}")
    driver.quit()

# Pause to allow new window to load
time.sleep(5)  # Adjust based on loading time

# Step 4-6: Use PyAutoGUI to select the Success radio button and click OK with highlighting

try:
    # Highlight and click the Success radio button
    highlight_mouse(543, 360, duration=0.5)
    pyautogui.click(543, 360)
    time.sleep(1)

    # Highlight and click the first OK button
    highlight_mouse(1398, 865, duration=0.5)
    pyautogui.click(1398, 865)
    time.sleep(1)

    # Highlight and click the confirmation OK button
    highlight_mouse(1068, 618, duration=0.5)
    pyautogui.click(1068, 618)

    print("Test results successfully submitted!")
except Exception as e:
    print(f"Error using PyAutoGUI: {e}")

# Close the browser
driver.quit()
