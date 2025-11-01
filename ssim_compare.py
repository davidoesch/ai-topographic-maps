import os
import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim
import json
from pathlib import Path
import argparse

"""
ssim_compare.py

Compare original satellite (aerial) tiles with generated/styled map tiles using
Structural Similarity Index (SSIM) and simple color-difference metrics.

Features:
- Compare single image pairs or all pairs in a directory where styled tiles
  use the suffix "_map" (e.g. tile.jpeg -> tile_map.jpeg).
- Produces a JSON report and a Markdown file with inline images for quick
  visual inspection.
- Resizes images as needed before comparison and converts to grayscale for SSIM.

Basic usage:
  Directory mode:
    python ssim_compare.py --dir /path/to/tiles --report report.json --markdown report.md

  Single-pair mode:
    python ssim_compare.py --original path/to/orig.jpeg --styled path/to/orig_map.jpeg

Dependencies:
  - Python 3.8+
  - numpy
  - pillow (PIL)
  - scikit-image

Author: David Oesch
Date: 2025-11-01
License: MIT
"""

def load_image(image_path):
    """Load image and convert to numpy array"""
    img = Image.open(image_path)
    return np.array(img)

def calculate_ssim(img1, img2):
    """Calculate SSIM between two images

    Returns:
        float: SSIM score between -1 and 1 (1 = identical)
    """
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
        print(f"  Resizing images: {img1_gray.shape} and {img2_gray.shape}")
        # Use the larger dimension as target
        target_shape = max(img1_gray.shape[0], img2_gray.shape[0]), max(img1_gray.shape[1], img2_gray.shape[1])

        # Resize using PIL for better quality
        if img1_gray.shape != target_shape:
            img1_pil = Image.fromarray(img1_gray)
            img1_pil = img1_pil.resize((target_shape[1], target_shape[0]), Image.LANCZOS)
            img1_gray = np.array(img1_pil)

        if img2_gray.shape != target_shape:
            img2_pil = Image.fromarray(img2_gray)
            img2_pil = img2_pil.resize((target_shape[1], target_shape[0]), Image.LANCZOS)
            img2_gray = np.array(img2_pil)

    # Calculate SSIM
    score, diff = ssim(img1_gray, img2_gray, full=True)
    return score, diff

def calculate_color_difference(img1, img2):
    """Calculate mean absolute difference in RGB space"""
    if len(img1.shape) == 3 and len(img2.shape) == 3:
        # Resize if dimensions don't match
        if img1.shape != img2.shape:
            target_shape = max(img1.shape[0], img2.shape[0]), max(img1.shape[1], img2.shape[1])

            if img1.shape[:2] != target_shape:
                img1_pil = Image.fromarray(img1)
                img1_pil = img1_pil.resize((target_shape[1], target_shape[0]), Image.LANCZOS)
                img1 = np.array(img1_pil)

            if img2.shape[:2] != target_shape:
                img2_pil = Image.fromarray(img2)
                img2_pil = img2_pil.resize((target_shape[1], target_shape[0]), Image.LANCZOS)
                img2 = np.array(img2_pil)

        return np.mean(np.abs(img1.astype(float) - img2.astype(float)))
    return None

def analyze_tile_pair(original_path, styled_path, ssim_threshold=0.85):
    """Analyze a pair of original and styled images

    Args:
        original_path: Path to original satellite image
        styled_path: Path to styled map image
        ssim_threshold: SSIM threshold above which images are considered too similar

    Returns:
        dict: Analysis results
    """
    # Load images
    img_original = load_image(original_path)
    img_styled = load_image(styled_path)

    # Calculate SSIM
    ssim_score, diff_img = calculate_ssim(img_original, img_styled)

    # Calculate color difference
    color_diff = calculate_color_difference(img_original, img_styled)

    # Determine if transformation was successful
    transformation_success = ssim_score < ssim_threshold

    result = {
        'original': str(original_path),
        'styled': str(styled_path),
        'ssim_score': float(ssim_score),
        'color_difference': float(color_diff) if color_diff is not None else None,
        'transformation_success': bool(transformation_success),
        'status': 'SUCCESS' if transformation_success else 'FAILED - Too similar to input'
    }

    return result

def generate_markdown_report(results, input_dir, output_file='comparison_report.md'):
    """Generate markdown file with image comparisons"""

    with open(output_file, 'w') as f:
        # Write header
        f.write("# Satellite to Map Transformation Results\n\n")
        f.write("| Aerial Photo | Generated Map | SSIM Score | Status |\n")
        f.write("|:---:|:---:|:---:|:---|\n")

        # Write each tile comparison
        for result in results:
            original_path = Path(result['original'])
            styled_path = Path(result['styled'])

            # Get relative paths
            original_rel = os.path.join(input_dir, original_path.name)
            styled_rel = os.path.join(input_dir, styled_path.name)

            ssim_score = result['ssim_score']
            success = result['transformation_success']

            # Create status text with color coding
            if success:
                status = f"✅ **SUCCESS**<br>SSIM: {ssim_score:.4f}"
                row_style = ""
            else:
                status = f"❌ **FAILED**<br>Too similar to input<br>SSIM: {ssim_score:.4f}"
                row_style = ' style="background-color: #ffe6e6;"'

            # Write table row
            f.write(f'| <img src="{original_rel}" width="300"> | ')
            f.write(f'<img src="{styled_rel}" width="300"> | ')
            f.write(f'{ssim_score:.4f} | ')
            f.write(f'{status} |\n')

        f.write("\n---\n\n")
        f.write("### Legend\n")
        f.write("- ✅ **SUCCESS**: Image successfully transformed (SSIM < threshold)\n")
        f.write("- ❌ **FAILED**: Generated image too similar to input (transformation did not occur)\n")
        f.write("- **SSIM Score**: Structural Similarity Index (0-1, higher = more similar)\n")

    print(f"Markdown report saved to: {output_file}")

def analyze_directory(input_dir, ssim_threshold=0.85, output_report='comparison_report.json', output_markdown='comparison_report.md'):
    """Analyze all tile pairs in a directory

    Args:
        input_dir: Directory containing original and styled tiles
        ssim_threshold: SSIM threshold for success detection
        output_report: Path to save JSON report
        output_markdown: Path to save Markdown report
    """
    input_path = Path(input_dir)

    # Find all original tiles (without _map suffix)
    original_tiles = []
    for file in input_path.glob("*.jpeg"):
        if not file.stem.endswith("_map"):
            original_tiles.append(file)

    print(f"Found {len(original_tiles)} original tiles to analyze")

    results = []
    success_count = 0
    failed_count = 0

    for original_file in sorted(original_tiles):
        # Construct styled filename
        styled_file = input_path / f"{original_file.stem}_map.jpeg"

        if not styled_file.exists():
            print(f"Warning: No styled version found for {original_file.name}")
            continue

        print(f"\nAnalyzing: {original_file.name}")

        try:
            result = analyze_tile_pair(original_file, styled_file, ssim_threshold)
            results.append(result)

            print(f"  SSIM Score: {result['ssim_score']:.4f}")
            print(f"  Color Diff: {result['color_difference']:.2f}" if result['color_difference'] else "")
            print(f"  Status: {result['status']}")

            if result['transformation_success']:
                success_count += 1
            else:
                failed_count += 1

        except Exception as e:
            print(f"  Error analyzing {original_file.name}: {e}")

    # Generate summary
    summary = {
        'total_tiles': int(len(results)),
        'successful_transformations': int(success_count),
        'failed_transformations': int(failed_count),
        'success_rate': float(success_count / len(results) if results else 0),
        'ssim_threshold': float(ssim_threshold),
        'average_ssim': float(np.mean([r['ssim_score'] for r in results]) if results else 0)
    }

    # Save JSON report
    report = {
        'summary': summary,
        'tiles': results
    }

    with open(output_report, 'w') as f:
        json.dump(report, f, indent=2)

    # Generate markdown report
    generate_markdown_report(results, input_dir, output_markdown)

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Total tiles analyzed: {summary['total_tiles']}")
    print(f"Successful transformations: {summary['successful_transformations']}")
    print(f"Failed transformations: {summary['failed_transformations']}")
    print(f"Success rate: {summary['success_rate']*100:.1f}%")
    print(f"Average SSIM score: {summary['average_ssim']:.4f}")
    print(f"\nJSON report saved to: {output_report}")
    print(f"Markdown report saved to: {output_markdown}")

    return report

def compare_single_pair(original_path, styled_path, ssim_threshold=0.85):
    """Compare a single pair of images"""
    result = analyze_tile_pair(original_path, styled_path, ssim_threshold)

    print(f"\nComparison Results:")
    print(f"{'='*60}")
    print(f"Original: {result['original']}")
    print(f"Styled: {result['styled']}")
    print(f"SSIM Score: {result['ssim_score']:.4f}")
    if result['color_difference']:
        print(f"Color Difference: {result['color_difference']:.2f}")
    print(f"Status: {result['status']}")
    print(f"{'='*60}")

    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Compare original satellite images with styled map images using SSIM'
    )
    parser.add_argument(
        '--dir',
        type=str,
        help='Directory containing tile pairs (default: output_tiles_ssmi)',
        default='output_tiles_ssmi'
    )
    parser.add_argument(
        '--original',
        type=str,
        help='Path to single original image (for single comparison mode)'
    )
    parser.add_argument(
        '--styled',
        type=str,
        help='Path to single styled image (for single comparison mode)'
    )
    parser.add_argument(
        '--threshold',
        type=float,
        default=0.85,
        help='SSIM threshold for success detection (default: 0.85)'
    )
    parser.add_argument(
        '--report',
        type=str,
        default='comparison_report.json',
        help='Output JSON report filename (default: comparison_report.json)'
    )
    parser.add_argument(
        '--markdown',
        type=str,
        default='comparison_report.md',
        help='Output Markdown report filename (default: comparison_report.md)'
    )

    args = parser.parse_args()

    # Single pair comparison mode
    if args.original and args.styled:
        compare_single_pair(args.original, args.styled, args.threshold)
    # Directory batch mode
    else:
        analyze_directory(args.dir, args.threshold, args.report, args.markdown)