import requests
import xml.etree.ElementTree as ET
from google import genai
from PIL import Image
from io import BytesIO
import os
import math
import time
from pathlib import Path
from pyproj import Transformer
import numpy as np
from skimage.metrics import structural_similarity as ssim

# Configuration
ZOOM_LEVEL = 26
WMTS_BASE_URL = "https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.swissimage/default/current/2056"
OUTPUT_DIR = "output_tiles_ssmi_fixed"
SECRETS_DIR = "secrets"
AREA_URL = "https://public.geo.admin.ch/api/kml/files/GOgTC2UBSsWhqx5w2gFGEQ"
SSIM_THRESHOLD = 0.35
MAX_RETRY_ATTEMPTS = 3

# Swiss coordinate system parameters (EPSG:2056)
TILE_SIZE = 256  # pixels
BBOX_MIN_X = 2420000
BBOX_MAX_X = 2900000
BBOX_MIN_Y = 1030000
BBOX_MAX_Y = 1350000
ORIGIN_X = BBOX_MIN_X
ORIGIN_Y = BBOX_MAX_Y

# Resolution table from documentation
RESOLUTIONS = {
    0: 4000, 1: 3750, 2: 3500, 3: 3250, 4: 3000, 5: 2750, 6: 2500, 7: 2250,
    8: 2000, 9: 1750, 10: 1500, 11: 1250, 12: 1000, 13: 750, 14: 650,
    15: 500, 16: 250, 17: 100, 18: 50, 19: 20, 20: 10, 21: 5, 22: 2.5,
    23: 2, 24: 1.5, 25: 1, 26: 0.5, 27: 0.25, 28: 0.1
}

def read_api_key():
    """Read Gemini API key from file"""
    key_path = os.path.join(SECRETS_DIR, 'genai_key.txt')
    with open(key_path, 'r') as f:
        return f.read().strip()

def read_prompt(filename='prompt.txt'):
    """Read transformation prompt from file"""
    with open(filename, 'r') as f:
        return f.read().strip()

def calculate_ssim_score(img1, img2):
    """Calculate SSIM between two images

    Returns:
        float: SSIM score between -1 and 1 (1 = identical)
    """
    # Convert PIL images to numpy arrays
    if isinstance(img1, Image.Image):
        img1 = np.array(img1)
    if isinstance(img2, Image.Image):
        img2 = np.array(img2)

    # Convert to grayscale if images are RGB
    if len(img1.shape) == 3:
        img1_gray = np.mean(img1, axis=2).astype(np.uint8)
    else:
        img1_gray = img1

    if len(img2.shape) == 3:
        img2_gray = np.mean(img2, axis=2).astype(np.uint8)
    else:
        img2_gray = img2

    # Resize images to same dimensions if needed
    if img1_gray.shape != img2_gray.shape:
        target_shape = max(img1_gray.shape[0], img2_gray.shape[0]), max(img1_gray.shape[1], img2_gray.shape[1])

        if img1_gray.shape != target_shape:
            img1_pil = Image.fromarray(img1_gray)
            img1_pil = img1_pil.resize((target_shape[1], target_shape[0]), Image.LANCZOS)
            img1_gray = np.array(img1_pil)

        if img2_gray.shape != target_shape:
            img2_pil = Image.fromarray(img2_gray)
            img2_pil = img2_pil.resize((target_shape[1], target_shape[0]), Image.LANCZOS)
            img2_gray = np.array(img2_pil)

    # Calculate SSIM
    score, _ = ssim(img1_gray, img2_gray, full=True)
    return float(score)

def download_kml(kml_url):
    """Download KML file from URL"""
    print(f"Downloading KML from: {kml_url}")
    response = requests.get(kml_url)
    response.raise_for_status()
    return response.content

def parse_kml_bbox(kml_content):
    """Extract bounding box from KML (WGS84) and convert to Swiss coordinates (EPSG:2056)"""
    root = ET.fromstring(kml_content)

    namespaces = {
        'kml': 'http://www.opengis.net/kml/2.2',
        'gx': 'http://www.google.com/kml/ext/2.2'
    }

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:2056", always_xy=True)

    coords_wgs84 = []
    for coord_elem in root.findall('.//kml:coordinates', namespaces):
        coord_text = coord_elem.text.strip()
        for line in coord_text.split():
            parts = line.split(',')
            if len(parts) >= 2:
                lon, lat = float(parts[0]), float(parts[1])
                coords_wgs84.append((lon, lat))

    if not coords_wgs84:
        raise ValueError("No coordinates found in KML")

    print(f"Found {len(coords_wgs84)} coordinates in KML")

    coords_swiss = []
    for lon, lat in coords_wgs84:
        x, y = transformer.transform(lon, lat)
        coords_swiss.append((x, y))

    xs, ys = zip(*coords_swiss)
    bbox = {
        'min_x': min(xs),
        'max_x': max(xs),
        'min_y': min(ys),
        'max_y': max(ys)
    }

    print(f"Bounding box (EPSG:2056): {bbox}")
    print(f"  Width: {bbox['max_x'] - bbox['min_x']:.2f}m")
    print(f"  Height: {bbox['max_y'] - bbox['min_y']:.2f}m")
    return bbox

def swiss_to_tile(x, y, zoom):
    """Convert Swiss coordinates (EPSG:2056) to WMTS tile indices"""
    resolution = RESOLUTIONS[zoom]
    tile_width_m = TILE_SIZE * resolution
    tile_col = int((x - ORIGIN_X) / tile_width_m)
    tile_row = int((ORIGIN_Y - y) / tile_width_m)
    return tile_col, tile_row

def get_tiles_in_bbox(bbox, zoom):
    """Get all tile indices within bounding box"""
    min_tile_col, max_tile_row = swiss_to_tile(bbox['min_x'], bbox['min_y'], zoom)
    max_tile_col, min_tile_row = swiss_to_tile(bbox['max_x'], bbox['max_y'], zoom)

    print(f"Tile range - Col: {min_tile_col} to {max_tile_col}, Row: {min_tile_row} to {max_tile_row}")

    tiles = []
    for tile_col in range(min_tile_col, max_tile_col + 1):
        for tile_row in range(min_tile_row, max_tile_row + 1):
            tiles.append((tile_col, tile_row))

    print(f"Found {len(tiles)} tiles to process")
    return tiles

def download_tile(tile_col, tile_row, zoom):
    """Download a WMTS tile"""
    url = f"{WMTS_BASE_URL}/{zoom}/{tile_col}/{tile_row}.jpeg"
    print(f"Downloading tile: Col={tile_col}, Row={tile_row} from {url}")

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return Image.open(BytesIO(response.content))
    except Exception as e:
        print(f"Error downloading tile {tile_col}/{tile_row}: {e}")
        return None

def apply_style_transfer(client, image, prompt, tile_col, tile_row, max_retries=3):
    """Apply Gemini style transfer to image"""
    print(f"Applying style transfer to tile Col={tile_col}, Row={tile_row}")

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-image",
                contents=[image, prompt],
            )

            image_parts = [
                part.inline_data.data
                for part in response.candidates[0].content.parts
                if part.inline_data
            ]

            if image_parts:
                return Image.open(BytesIO(image_parts[0]))
            else:
                print(f"No image generated for tile {tile_col}/{tile_row}")
                return None

        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 10
                print(f"Error on attempt {attempt + 1}, retrying in {wait_time}s: {e}")
                time.sleep(wait_time)
            else:
                print(f"Failed to process tile {tile_col}/{tile_row} after {max_retries} attempts: {e}")
                return None

    return None

def process_tile_with_validation(client, original_image, prompt, prompt_retry, tile_col, tile_row,
                                  original_path, styled_path, threshold=0.35, max_attempts=3):
    """Process a tile with SSIM validation and retry logic"""

    for attempt in range(max_attempts):
        # Use retry prompt after first attempt
        current_prompt = prompt if attempt == 0 else prompt_retry
        prompt_type = "main" if attempt == 0 else "retry"

        print(f"\n  Attempt {attempt + 1}/{max_attempts} using {prompt_type} prompt")

        # Apply style transfer
        styled_image = apply_style_transfer(client, original_image, current_prompt, tile_col, tile_row)
        if styled_image is None:
            print(f"  Style transfer failed on attempt {attempt + 1}")
            continue

        # Save styled tile
        styled_image.save(styled_path)
        print(f"  Saved styled: {styled_path}")

        # Calculate SSIM
        ssim_score = calculate_ssim_score(original_image, styled_image)
        print(f"  SSIM Score: {ssim_score:.4f} (threshold: {threshold})")

        # Check if transformation was successful
        if ssim_score < threshold:
            print(f"  ✅ SUCCESS - Image successfully transformed (SSIM: {ssim_score:.4f})")
            return True, ssim_score
        else:
            print(f"  ❌ FAILED - Too similar to input (SSIM: {ssim_score:.4f})")
            if attempt < max_attempts - 1:
                print(f"  Retrying with alternative prompt...")
                time.sleep(2)

    print(f"  ⚠️  All {max_attempts} attempts failed for tile {tile_col}_{tile_row}")
    return False, ssim_score

def main():
    # Create output directory
    Path(OUTPUT_DIR).mkdir(exist_ok=True)

    # Read API key and prompts
    api_key = read_api_key()
    os.environ['GEMINI_API_KEY'] = api_key
    client = genai.Client()

    prompt = read_prompt('prompt.txt')
    print(f"Main prompt loaded: {prompt[:100]}...")

    # Try to load retry prompt, fallback to main prompt if not found
    try:
        prompt_retry = read_prompt('prompt_restart.txt')
        print(f"Retry prompt loaded: {prompt_retry[:100]}...")
    except FileNotFoundError:
        print("Warning: prompt_restart.txt not found, using main prompt for retries")
        prompt_retry = prompt

    # Download and parse KML
    kml_url = AREA_URL
    kml_content = download_kml(kml_url)
    bbox = parse_kml_bbox(kml_content)

    # Get tiles in bounding box
    tiles = get_tiles_in_bbox(bbox, ZOOM_LEVEL)

    # Statistics tracking
    total_tiles = len(tiles)
    successful_tiles = 0
    failed_tiles = 0
    retry_needed = 0

    # Process each tile
    for i, (tile_col, tile_row) in enumerate(tiles):
        print(f"\n{'='*60}")
        print(f"Processing tile {i+1}/{total_tiles}: Col={tile_col}, Row={tile_row}")
        print(f"{'='*60}")

        # Download original tile
        original_image = download_tile(tile_col, tile_row, ZOOM_LEVEL)
        if original_image is None:
            failed_tiles += 1
            continue

        # Save original tile
        original_path = os.path.join(OUTPUT_DIR, f"{tile_col}_{tile_row}.jpeg")
        original_image.save(original_path)
        print(f"Saved original: {original_path}")

        # Process with validation and retry
        styled_path = os.path.join(OUTPUT_DIR, f"{tile_col}_{tile_row}_map.jpeg")
        success, final_ssim = process_tile_with_validation(
            client, original_image, prompt, prompt_retry,
            tile_col, tile_row, original_path, styled_path,
            threshold=SSIM_THRESHOLD, max_attempts=MAX_RETRY_ATTEMPTS
        )

        if success:
            successful_tiles += 1
        else:
            failed_tiles += 1
            if final_ssim >= SSIM_THRESHOLD:
                retry_needed += 1

        # Rate limiting - wait between tiles
        time.sleep(2)

    # Print final summary
    print(f"\n{'='*60}")
    print("PROCESSING SUMMARY")
    print(f"{'='*60}")
    print(f"Total tiles: {total_tiles}")
    print(f"Successful transformations: {successful_tiles}")
    print(f"Failed transformations: {failed_tiles}")
    print(f"Success rate: {successful_tiles/total_tiles*100:.1f}%")
    print(f"Tiles that needed retry: {retry_needed}")
    print(f"\nOutput saved to {OUTPUT_DIR}/")

if __name__ == "__main__":
    main()