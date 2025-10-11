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

# Configuration
ZOOM_LEVEL = 26
WMTS_BASE_URL = "https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.swissimage/default/current/2056"
OUTPUT_DIR = "output_tiles"
SECRETS_DIR = "secrets"
AREA_URL = "https://public.geo.admin.ch/api/kml/files/GOgTC2UBSsWhqx5w2gFGEQ"

# Swiss coordinate system parameters (EPSG:2056)
# WMTS tile matrix for Swiss coordinates - based on official documentation
TILE_SIZE = 256  # pixels
# TileMatrixSet 2056 bounds
BBOX_MIN_X = 2420000
BBOX_MAX_X = 2900000
BBOX_MIN_Y = 1030000
BBOX_MAX_Y = 1350000
# Tile origin is at TOP-LEFT corner
ORIGIN_X = BBOX_MIN_X
ORIGIN_Y = BBOX_MAX_Y  # Top of bounding box

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

def read_prompt():
    """Read transformation prompt from file"""
    with open('prompt.txt', 'r') as f:
        return f.read().strip()

def download_kml(kml_url):
    """Download KML file from URL"""
    print(f"Downloading KML from: {kml_url}")
    response = requests.get(kml_url)
    response.raise_for_status()
    return response.content

def parse_kml_bbox(kml_content):
    """Extract bounding box from KML (WGS84) and convert to Swiss coordinates (EPSG:2056)"""
    root = ET.fromstring(kml_content)

    # Handle namespaces
    namespaces = {
        'kml': 'http://www.opengis.net/kml/2.2',
        'gx': 'http://www.google.com/kml/ext/2.2'
    }

    # Create transformer from WGS84 (EPSG:4326) to Swiss LV95 (EPSG:2056)
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:2056", always_xy=True)

    # Find all coordinates in the KML
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

    # Convert all coordinates to Swiss LV95
    coords_swiss = []
    for lon, lat in coords_wgs84:
        x, y = transformer.transform(lon, lat)
        coords_swiss.append((x, y))

    # Calculate bounding box in Swiss coordinates
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
    """Convert Swiss coordinates (EPSG:2056) to WMTS tile indices

    Origin is at top-left corner (ORIGIN_X, ORIGIN_Y)
    X increases to the right (East)
    Y decreases downward (South) - this is key!
    """
    resolution = RESOLUTIONS[zoom]
    tile_width_m = TILE_SIZE * resolution

    # Calculate tile indices
    # X: distance from left edge / tile width
    tile_col = int((x - ORIGIN_X) / tile_width_m)

    # Y: distance from top edge / tile width (note: Y decreases going down)
    tile_row = int((ORIGIN_Y - y) / tile_width_m)

    return tile_col, tile_row

def get_tiles_in_bbox(bbox, zoom):
    """Get all tile indices within bounding box"""
    # Convert bbox corners to tile coordinates
    # min_x, min_y = bottom-left corner
    # max_x, max_y = top-right corner

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
    """Download a WMTS tile

    URL structure: .../TileMatrixSet/TileSetId/TileCol/TileRow.jpeg
    For EPSG:2056, use col/row order (not row/col like EPSG:21781)
    """
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

    # Convert PIL Image to bytes
    img_byte_arr = BytesIO()
    image.save(img_byte_arr, format='JPEG')
    img_byte_arr.seek(0)

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-image",
                contents=[image, prompt],
            )

            # Extract generated image
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

def main():
    # Create output directory
    Path(OUTPUT_DIR).mkdir(exist_ok=True)

    # Read API key and prompt
    api_key = read_api_key()
    os.environ['GEMINI_API_KEY'] = api_key
    client = genai.Client()

    prompt = read_prompt()
    print(f"Prompt: {prompt[:100]}...")

    # Download and parse KML
    kml_url = AREA_URL 
    kml_content = download_kml(kml_url)
    bbox = parse_kml_bbox(kml_content)

    # Get tiles in bounding box
    tiles = get_tiles_in_bbox(bbox, ZOOM_LEVEL)



    # Process each tile
    for i, (tile_col, tile_row) in enumerate(tiles):
        print(f"\nProcessing tile {i+1}/{len(tiles)}: Col={tile_col}, Row={tile_row}")

        # Download original tile
        original_image = download_tile(tile_col, tile_row, ZOOM_LEVEL)
        if original_image is None:
            continue



        # Save original tile (optional)
        original_path = os.path.join(OUTPUT_DIR, f"{tile_col}_{tile_row}.jpeg")
        original_image.save(original_path)
        print(f"Saved original: {original_path}")

        # Apply style transfer
        styled_image = apply_style_transfer(client, original_image, prompt, tile_col, tile_row)
        if styled_image is None:
            continue

        # Save styled tile
        styled_path = os.path.join(OUTPUT_DIR, f"{tile_col}_{tile_row}_map.jpeg")
        styled_image.save(styled_path)
        print(f"Saved styled: {styled_path}")

        # Rate limiting - wait between requests
        time.sleep(2)

    print(f"\nProcessing complete! Output saved to {OUTPUT_DIR}/")

if __name__ == "__main__":
    main()