from PIL import Image
import os

png_path = 'app/static/img/fondo.png'
webp_path = 'app/static/img/fondo.webp'

if os.path.exists(png_path):
    img = Image.open(png_path)
    # Convert to RGB if it has alpha channel, though WebP supports alpha.
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    # Save as WebP with 75% quality which is heavily optimized
    img.save(webp_path, 'WEBP', quality=75)
    print(f"Saved {webp_path}")
    print(f"Original size: {os.path.getsize(png_path) / 1024:.2f} KB")
    print(f"New size: {os.path.getsize(webp_path) / 1024:.2f} KB")
else:
    print("fondo.png not found")
