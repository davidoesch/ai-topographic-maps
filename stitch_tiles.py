import os
from pathlib import Path
from PIL import Image
import re

# Configuration
INPUT_DIR = "output_tiles_ssmi_fixed"
OUTPUT_FILE = "stitched_map.jpeg"
TILE_SIZE = 256  # pixels

def parse_tile_filename(filename):
    """Extract tile column and row from filename

    Expected format: {col}_{row}_map.jpeg
    Returns: (col, row) or None if invalid
    """
    match = re.match(r'(\d+)_(\d+)_map\.jpeg$', filename)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None

def find_all_tiles(input_dir):
    """Find all _map tiles and determine grid dimensions

    Returns: dict of {(col, row): filepath}, min/max col/row
    """
    tiles = {}
    min_col = min_row = float('inf')
    max_col = max_row = float('-inf')

    for filename in os.listdir(input_dir):
        if filename.endswith('_map.jpeg'):
            coords = parse_tile_filename(filename)
            if coords:
                col, row = coords
                tiles[(col, row)] = os.path.join(input_dir, filename)

                min_col = min(min_col, col)
                max_col = max(max_col, col)
                min_row = min(min_row, row)
                max_row = max(max_row, row)

    if not tiles:
        raise ValueError(f"No _map.jpeg tiles found in {input_dir}")

    print(f"Found {len(tiles)} tiles")
    print(f"Column range: {min_col} to {max_col} ({max_col - min_col + 1} tiles)")
    print(f"Row range: {min_row} to {max_row} ({max_row - min_row + 1} tiles)")

    return tiles, min_col, max_col, min_row, max_row

def detect_tile_size(tiles):
    """Detect actual tile size from first available tile"""
    for tile_path in tiles.values():
        try:
            with Image.open(tile_path) as img:
                width, height = img.size
                print(f"\nDetected tile size: {width}x{height} pixels")
                if width != height:
                    print(f"⚠️  Warning: Tiles are not square ({width}x{height})")
                return width, height
        except Exception as e:
            print(f"Error reading tile {tile_path}: {e}")
            continue
    raise ValueError("Could not detect tile size - no valid tiles found")

def stitch_tiles(tiles, min_col, max_col, min_row, max_row, output_file):
    """Stitch tiles into a single image"""

    # Detect actual tile size from images
    tile_width, tile_height = detect_tile_size(tiles)

    # Calculate output dimensions
    width = (max_col - min_col + 1) * tile_width
    height = (max_row - min_row + 1) * tile_height

    print(f"Creating stitched image: {width}x{height} pixels")

    # Create output image (RGB)
    output_img = Image.new('RGB', (width, height), (255, 255, 255))

    # Track statistics
    pasted_tiles = 0
    missing_tiles = []

    # Paste each tile
    for col in range(min_col, max_col + 1):
        for row in range(min_row, max_row + 1):
            if (col, row) in tiles:
                # Calculate position in output image
                x = (col - min_col) * tile_width
                y = (row - min_row) * tile_height

                # Load and paste tile
                try:
                    tile_img = Image.open(tiles[(col, row)])
                    output_img.paste(tile_img, (x, y))
                    pasted_tiles += 1

                    if pasted_tiles % 10 == 0:
                        print(f"  Pasted {pasted_tiles}/{len(tiles)} tiles...", end='\r')
                except Exception as e:
                    print(f"\nError loading tile {col}_{row}: {e}")
                    missing_tiles.append((col, row))
            else:
                missing_tiles.append((col, row))

    print(f"\n  Pasted {pasted_tiles}/{len(tiles)} tiles")

    if missing_tiles:
        print(f"\n⚠️  Warning: {len(missing_tiles)} tiles are missing from the grid:")
        for col, row in missing_tiles[:10]:  # Show first 10
            print(f"    {col}_{row}")
        if len(missing_tiles) > 10:
            print(f"    ... and {len(missing_tiles) - 10} more")

    # Save output
    print(f"\nSaving stitched image to: {output_file}")
    output_img.save(output_file, quality=95)
    print(f"✅ Done! Image size: {width}x{height} pixels")

    return output_img

def main():
    print("=" * 60)
    print("WMTS Tile Stitcher")
    print("=" * 60)

    # Check input directory exists
    if not os.path.isdir(INPUT_DIR):
        print(f"❌ Error: Input directory '{INPUT_DIR}' not found")
        return

    # Find all tiles
    tiles, min_col, max_col, min_row, max_row = find_all_tiles(INPUT_DIR)

    # Stitch tiles together
    stitch_tiles(tiles, min_col, max_col, min_row, max_row, OUTPUT_FILE)

    print(f"\n{'=' * 60}")
    print("Stitching complete!")
    print(f"{'=' * 60}")

if __name__ == "__main__":
    main()