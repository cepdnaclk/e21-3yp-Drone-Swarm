import cv2
import numpy as np

# Parameters for A4 @ 300 DPI
# A4 is 210 x 297 mm
# We will make 25mm squares (1 inch)
square_size_mm = 25
width_mm, height_mm = 210, 297
px_per_mm = 10  # Resolution

# Create a white canvas
image = np.ones((height_mm * px_per_mm, width_mm * px_per_mm), dtype=np.uint8) * 255

# Draw a 9x6 internal corner grid (10x7 squares)
rows, cols = 7, 10
sq_px = square_size_mm * px_per_mm

for r in range(rows):
    for c in range(cols):
        if (r + c) % 2 == 0:
            y = r * sq_px + 100 # Offset from top
            x = c * sq_px + 100 # Offset from left
            image[y:y+sq_px, x:x+sq_px] = 0

cv2.imwrite("checkerboard.png", image)
print("Checkerboard saved as checkerboard.png. Open and print it at 100% scale.")