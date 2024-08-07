import os
import cv2 as cv
from IPython.display import clear_output
import matplotlib.pyplot as plt
import pandas as pd
from PIL import Image, ImageOps, ImageChops, ImageDraw
import numpy as np
import SimpleITK as sitk
from skimage.color import rgb2hed
from skimage.exposure import histogram
from skimage.filters import threshold_otsu
from skimage.morphology import remove_small_holes

import sys
sys.path.insert(0, r'G:\projects\GitHub\HE\Kfbreader-win10-python36')
import kfbReader

# pathological slice cut location info
TEMPLATE_SLIDE_NAME = '202328973-10'
HE_KI67_SLIDES_CUT_INFO_PAIR = {
    '202328973-10': [[1, 1,      688/1536, 537/625],         [1, 1,        -1, -1]],
    '202335455-17': [[1, 96/323, 619/1533, 298/323-96/323],  [1, 425/798,  -1, -1]]
    }

SLIDES_PATH = r'K:\pathological_KFB_KI67'
OUTPUT_PATH = r'K:\pathological_KFB_KI67_RESULT_11241'
SLIDE_READ_SCALE = 20
TILE_SIZE = 80
SAVE_TILE_SIZE = 224
GREEN_FILTER_THRESHOLD = 240
HE_GRAY_FILTER_TOLERANCE = 15
KI67_GRAY_FILTER_TOLERANCE = 2
CANCER_THRESH=0.39
NON_CANCER_THRESH=0.40

VERBOSE = True
HE_NAME = 'HE.kfb'
KI67_NAME = 'ki67.kfb'
VERBOSE = True
if VERBOSE:
    verbose_print = lambda *args: print(*args)
    verbose_save_img = lambda img, path, img_type: img.save(path, img_type)
    verbose_save_fig = lambda fig, path, dpi=300: fig.savefig(path, dpi=dpi)
else:
    verbose_print = lambda *args: None
    verbose_save_img = lambda *args: None
    verbose_save_fig = lambda *args: None


######################
# Image Registration #
######################

def get_itk_from_pil(pil_img):
    """Converts Pillow image into ITK image
    """
    return sitk.GetImageFromArray(np.array(pil_img))

def get_pil_from_itk(itk_img):
    """Converts ITK image into Pillow Image
    """
    return Image.fromarray(sitk.GetArrayFromImage(itk_img).astype(np.uint8))

def show_alignment(fixed_img, moving_img, prefilter = None):
    """Visualises alignment of fixed image with moving image
    
    Fixed image is displayed as blue
    Moving image is displayed as pink 
    """
    if prefilter == 'TP53':
        tp53_filtered = filter_green(moving_img)
        tp53_filtered = filter_grays(tp53_filtered, tolerance = 3)
        moving_img = filter_otsu_global(tp53_filtered, 'PIL')
        he_filtered = filter_green(fixed_img)
        he_filtered = filter_grays(he_filtered, tolerance = 15)
        fixed_img = filter_otsu_global(he_filtered, 'PIL')
    background = (255,255,255)
    img_red = ImageOps.colorize(moving_img.convert('L'), (255, 0, 0), background)
    img_blue = ImageOps.colorize(fixed_img.convert('L'), (0, 0, 255), background)
    img_red.putalpha(120)
    img_blue.putalpha(70)
    return Image.alpha_composite(img_red, img_blue)

def sitk_transform_rgb(moving_rgb_img, fixed_rgb_img, transform, interpolator = sitk.sitkLanczosWindowedSinc):
    """Applies a Simple ITK transform (e.g. Affine, B-spline) to an RGB image
    
    The transform is applied to each channel
    
    Parameters
    ----------
    moving_rgb_img : Pillow Image 
        This image will be transformed to produce the output image
    fixed_rgb_img : Pillow Image
        This reference image provides the output information (spacing, size, and direction) of the output image
    transform : SimpleITK transform
        Generated from image registration
    interpolator : SimpleITK interpolator
    
    Returns
    -------
    rgb_transformed : Pillow Image
        Transformed moving image 
    """
    transformed_channels = []
    r_moving, g_moving, b_moving, = moving_rgb_img.convert('RGB').split()
    r_fixed, g_fixed, b_fixed = fixed_rgb_img.convert('RGB').split()
    for moving_img, fixed_img in [(r_moving, r_fixed), (g_moving, g_fixed), (b_moving, b_fixed)]:
        moving_img_itk = get_itk_from_pil(moving_img)
        fixed_img_itk = get_itk_from_pil(fixed_img)
        transformed_img = sitk.Resample(moving_img_itk, fixed_img_itk, transform, 
                            interpolator, 0.0, moving_img_itk.GetPixelID())
        transformed_channels.append(get_pil_from_itk(transformed_img))
    rgb_transformed = Image.merge('RGB', transformed_channels)
    return rgb_transformed    

def start_plot():
    """Setup data for plotting
    
    Invoked when StartEvent happens at the beginning of registration.
    """
    global metric_values, multires_iterations
    
    metric_values = []
    multires_iterations = []

def end_plot():
    """Cleanup the data and figures 
    """
    global metric_values, multires_iterations
    
    del metric_values
    del multires_iterations
    # Close figure, we don't want to get a duplicate of the plot latter on.
    plt.close()

def update_plot(registration_method):
    """Plot metric value after each registration iteration
    
    Invoked when IterationEvent happens.
    """
    global metric_values, multires_iterations
    
    metric_values.append(registration_method.GetMetricValue())                                       
    # Clear the output area (wait=True, to reduce flickering), and plot current data
    clear_output(wait=True)
    # Plot the similarity metric values
    plt.plot(metric_values, 'r')
    plt.plot(multires_iterations, [metric_values[index] for index in multires_iterations], 'b*')
    plt.xlabel('Iteration Number', fontsize=12)
    plt.ylabel('Metric', fontsize=12)
    plt.show()
    
def update_multires_iterations():
    """Update the index in the metric values list that corresponds to a change in registration resolution
    
    Invoked when the sitkMultiResolutionIterationEvent happens.
    """
    global metric_values, multires_iterations
    multires_iterations.append(len(metric_values))
    
def plot_metric(title = 'Plot of registration metric vs iterations'):
    """Plots the mutual information over registration iterations
    
    Parameters
    ----------
    title : str
    
    Returns
    -------
    fig : matplotlib figure
    """
    global metric_values, multires_iterations
    
    fig, ax = plt.subplots()
    ax.set_title(title)
    ax.set_xlabel('Iteration Number', fontsize=12)
    ax.set_ylabel('Mutual Information Cost', fontsize=12)
    ax.plot(metric_values, 'r')
    ax.plot(multires_iterations, [metric_values[index] for index in multires_iterations], 'b*', label = 'change in resolution')
    ax.legend()
    return fig

################################
# Mutual Information Functions #
################################

def mutual_information(hgram):
    """Mutual information for joint histogram
    """
    # Convert bins counts to probability values
    pxy = hgram / float(np.sum(hgram))
    px = np.sum(pxy, axis = 1) # marginal for x over y
    py = np.sum(pxy, axis = 0) # marginal for y over x
    px_py = px[:, None] * py[None, :] #Broadcat to multiply marginals
    # Now we can do the calculation using the pxy, px_py 2D arrays
    nzs = pxy > 0 # Only non-zero pxy values contribute to the sum
    return np.sum(pxy[nzs] * np.log(pxy[nzs] / px_py[nzs]))

def mutual_info_histogram(fixed_img, moving_img, bins = 20, log = False):
    hist_2d, x_edges, y_edges = np.histogram2d(fixed_img.ravel(), moving_img.ravel(), bins = bins)
    if log:
        hist_2d_log = np.zeros(hist_2d.shape)
        non_zeros = hist_2d != 0
        hist_2d_log[non_zeros] = np.log(hist_2d[non_zeros])
        return hist_2d_log
    return hist_2d

def plot_mutual_info_histogram(histogram):
    plt.imshow(histogram.T, origin = 'lower')
    plt.xlabel('Fixed Image')
    plt.ylabel('Moving Image')

def calculate_mutual_info(fixed_img, moving_img):
    hist = mutual_info_histogram(fixed_img, moving_img)
    return mutual_information(hist)

#################
# Image Filters #
#################

def filter_green(img, g_thresh = 240):
    """Replaces green pixels greater than threshold with white pixels
    
    Used to remove background from tissue images
    """
    img = img.convert('RGB')
    r, g, b = img.split()
    green_mask = (np.array(g) > g_thresh)*255
    green_mask_img = Image.fromarray(green_mask.astype(np.uint8), 'L')
    white_image = Image.new('RGB', img.size, (255,255,255))
    img_filtered = img.copy()
    img_filtered.paste(white_image, mask = green_mask_img)
    return img_filtered

def filter_grays(img, tolerance = 3):
    """Replaces gray pixels greater than threshold with white pixels
    
    Used to remove background from tissue images
    """
    img = img.convert('RGB')
    r, g, b = img.split()
    rg_diff = np.array(ImageChops.difference(r,g)) <= tolerance
    rb_diff = np.array(ImageChops.difference(r,b)) <= tolerance
    gb_diff = np.array(ImageChops.difference(g,b)) <= tolerance
    grays = (rg_diff & rb_diff & gb_diff)*255
    grays_mask = Image.fromarray(grays.astype(np.uint8), 'L')
    white_image = Image.new('RGB', img.size, (255,255,255))
    img_filtered = img.copy()
    img_filtered.paste(white_image, mask = grays_mask)
    return img_filtered

def filter_otsu_global(img, mode = 'PIL'):
    """Performs global otsu thresholding on Pillow Image
    """
    img_gray = img.convert('L')
    threshold = threshold_otsu(np.array(img_gray))
    img_binary = np.array(img_gray) > threshold
    if mode == '1':
        return img_binary
    else:
        return binary_array_to_pil(img_binary)

####################
# Image Operations #
####################

def thumbnail(img, size = (1000,1000)):
    """Converts Pillow images to a different size without modifying the original image
    """
    img_thumbnail = img.copy()
    img_thumbnail.thumbnail(size)
    return img_thumbnail

def binary_array_to_pil(array):
    """Converts a binary array to a Pillow Image
    """
    img_shape = array.shape
    img = Image.new('1', img_shape)
    int_list = array.astype(int).tolist()
    pixels = img.load()
    for i in range(img.size[0]):
        for j in range(img.size[1]):
            pixels[i,j] = int_list[i][j]
    return ImageOps.mirror(img).rotate(90, expand = True)

def binary2gray(img):
    """Converts binary arrays to grayscale Pillow image
    
    Parameters
    ----------
    img : binary ndarray
    
    Returns
    -------
    out : grayscale Pillow image
    """
    img_rescaled = (img*255).astype('uint8')
    return Image.fromarray(img_rescaled).convert('L')

def tile_gen(img, tile_size):
    '''Generates tiles for Pillow images
    '''
    width, height = img.size
    x_tiles = int(np.floor(width/tile_size))
    y_tiles = int(np.floor(height/tile_size))
    yield (x_tiles, y_tiles)
    for y in range(y_tiles):
        for x in range(x_tiles):
            x_coord = x*tile_size
            y_coord = y*tile_size
            yield img.crop((x_coord, y_coord, np.int(np.round(x_coord+tile_size)), np.int(np.round(y_coord+tile_size))))
            
def max_tiles(img_dim, tile_dim, overlap = 0):
    """Maximum tiles that can fit across an image dimension
    
    Parameters
    ----------
    img_dim : int, float
    tile_dim : int, float
    overlap : float
        overlap as a proportion - zero is no overlap, one is complete overlap
    
    Returns
    -------
    out : int
    """
    max_tiles = ((img_dim/tile_dim) - 1)/(1- overlap) + 1
    return int(np.floor(max_tiles))

def tile_coordinates(img, tile_size, overlap = 0):
    """Computes a dataframe of tile coordinates for an image
    
    Parameters
    ----------
    img : Pillow image 
    tile_size : int, float
    overlap : float
        overlap as a proportion - zero is no overlap, one is complete overlap
    
    Returns
    -------
    out : DataFrame
    """
    width, height = img.size
    x_tiles = max_tiles(width, tile_size, overlap)
    y_tiles = max_tiles(height, tile_size, overlap)
    coords = []
    for y in range(y_tiles):
        for x in range(x_tiles):
            x_top_left = x*tile_size*(1-overlap)
            y_top_left = y*tile_size*(1-overlap)
            x_bottom_right = x_top_left + tile_size
            y_bottom_right = y_top_left + tile_size
            coords.append([x, y, x_top_left, y_top_left, x_bottom_right, y_bottom_right])
    return pd.DataFrame(coords, columns = ['X','Y','x_top_left', 'y_top_left', 'x_bottom_right', 'y_bottom_right'])


class PlotImageAlignment:
    """Plot the alignment between two identically sized images
    """

    def __init__(self, style='vertical', pixel_spacing=300):
        self.px_spacing = pixel_spacing
        self.style = style

    def plot_images(self, img1, img2):
        mask = self.generate_mask(img1.size)
        overlay = img1.copy()
        overlay.paste(img2, (0, 0), mask)
        return overlay

    def generate_mask(self, img_size):
        blank_mask = Image.new('L', img_size, 0)
        if self.style == 'horizontal':
            return self.draw_horizontal_mask(blank_mask)
        elif self.style == 'vertical':
            return self.draw_vertical_mask(blank_mask)
        else:
            # Draw Tile Mask
            horizontal_mask = self.draw_horizontal_mask(blank_mask.copy())
            vertical_mask = self.draw_vertical_mask(blank_mask.copy())
            return ImageChops.difference(horizontal_mask, vertical_mask)

    def draw_horizontal_mask(self, mask):
        draw = ImageDraw.Draw(mask)
        img_width, img_height = mask.size
        x_top_left, y_top_left = 0, 0
        x_bottom_right, y_bottom_right = img_width, self.px_spacing
        while y_top_left < img_height:
            draw.rectangle((x_top_left, y_top_left, x_bottom_right, y_bottom_right), fill=255)
            y_top_left += self.px_spacing*2
            y_bottom_right += self.px_spacing*2
        return mask

    def draw_vertical_mask(self, mask):
        draw = ImageDraw.Draw(mask)
        img_width, img_height = mask.size
        x_top_left, y_top_left = 0, 0
        x_bottom_right, y_bottom_right = self.px_spacing, img_height
        while x_top_left < img_width:
            draw.rectangle((x_top_left, y_top_left, x_bottom_right, y_bottom_right), fill=255)
            x_top_left += self.px_spacing * 2
            x_bottom_right += self.px_spacing * 2
        return mask
            
##################
# Mask Functions #
##################

def threshold_otsu_masked(hed_img):
    """Otsu thresholds the DAB component of an image

       Masks the background so only tissue regions are used for threshold calculation.
       Without masking, the background would likely be thresholded from the tissue due to background staining.

    Parameters
    ----------
    hed_img : ndarray
        The image in Hematoxylin, Eosin, DAB (HED) format, in a 3-D array of shape ``(.., .., 3)``

    Returns
    -------
    threshold : float
        Pixel threshold value that best segments the DAB stain, as determined by the ostu method
    """
    dab = -hed_img[:, :, 2]
    hem = -hed_img[:, :, 0]
    hem_thresh = threshold_otsu(hem)

    hem_binary_otsu = hem > hem_thresh
    # Use binary mask to mask out background of DAB images
    dab_masked = np.where(hem_binary_otsu == False, dab, 0)
    dab_values = np.array([i for i in dab_masked.ravel() if i != 0])
    # Otsu Thresholding
    hist, bin_centers = histogram(dab_values, 256)
    hist = hist.astype(float)

    # class probabilities for all possible thresholds
    weight1 = np.cumsum(hist)
    weight2 = np.cumsum(hist[::-1])[::-1]
    # class means for all possible thresholds
    mean1 = np.cumsum(hist * bin_centers) / weight1
    mean2 = (np.cumsum((hist * bin_centers)[::-1]) / weight2[::-1])[::-1]

    # Clip ends to align class 1 and class 2 variables:
    # The last value of `weight1`/`mean1` should pair with zero values in
    # `weight2`/`mean2`, which do not exist.
    variance12 = weight1[:-1] * weight2[1:] * (mean1[:-1] - mean2[1:]) ** 2
    idx = np.argmax(variance12)

    # Consider all cells are normal if variance is too small
    if variance12[idx] < 100000:
        threshold = 0
    else:
        threshold = bin_centers[:-1][idx]
    return threshold


def tissue_mask_grabcut(img_filtered, tile_size, min_tissue = 0.05):
    """Generates a tissue mask where each tile has a minimum proportion of tissue 
    
    Uses the Grabcut Algorithm 
    
    Parameters
    ----------
    img_filtered : Pillow image (RGB)
        image where background pixels are white - [255, 255, 255]
    tile_size : int, float
    min_tissue : float
        proportion of tissue on a tile needed for the tile to be considered
        tissue instead of background.
    
    Returns
    -------
    out : ndarray
        mask where zero represents tissue and one represents background
    """
    img_cv = np.array(img_filtered)[:, :, ::-1]   #Convert RGB to BGR
    mask_initial = (np.array(img_filtered.convert('L')) != 255).astype(np.uint8)
    # Grabcut
    bgdModel = np.zeros((1,65),np.float64)
    fgdModel = np.zeros((1,65),np.float64)
    cv.grabCut(img_cv, mask_initial, None, bgdModel, fgdModel, 5, cv.GC_INIT_WITH_MASK)
    mask_final = np.where((mask_initial==2)|(mask_initial==0),0,1).astype('uint8')
    # Generate a rough 'filled in' mask of the tissue
    kernal_64 = cv.getStructuringElement(cv.MORPH_ELLIPSE, (64,64))
    mask_closed = cv.morphologyEx(mask_final, cv.MORPH_CLOSE, kernal_64)
    mask_opened = cv.morphologyEx(mask_closed, cv.MORPH_OPEN, kernal_64)
    # Use rough mask to remove small debris in grabcut mask
    mask_cleaned = cv.bitwise_and(mask_final, mask_final, mask = mask_opened)
    mask_cleaned_pil = Image.fromarray(mask_cleaned.astype(np.bool))
    # Generate tile mask
    tile_mask = []
    tgen = tile_gen(mask_cleaned_pil, tile_size)
    shape = next(tgen)
    for tile in tgen:
        tile_np = np.array(tile)
        tile_count = np.count_nonzero(tile_np)
        total_pixels = tile_np.size
        tissue_proportion = tile_count / total_pixels
        if tissue_proportion > min_tissue:
            tile_mask.append(0)
        else:
            tile_mask.append(1)
    return np.reshape(tile_mask, shape)


def plot_mask_new(img, c_mask, t_mask, tile_size, is_he=True, u_mask=None, width_proportion=0.05):
    """Plots cancer, tissue and uncertain (optional) masks onto an image

    Colours:
    Cancer - Red
    Non-cancer - Lime
    Uncertain - Orange

    Parameters
    ----------
    img : Pillow image (RGB)
    c_mask : ndarray
    t_mask : ndarray
    tile_size : int, float
    u_mask : ndarray (optional)

    Returns
    -------
    overlay_img : Pillow image (RGB)
    """
    img_overlay = img.copy()
    d = ImageDraw.Draw(img_overlay)
    tile_coords = tile_coordinates(img, tile_size)
    tile_coords['c_mask'] = c_mask.ravel()
    tile_coords['t_mask'] = t_mask.ravel()
    if u_mask is not None:
        tile_coords['u_mask'] = u_mask.ravel()
    width = int(np.round(tile_size * width_proportion))
    for row in tile_coords.itertuples(index=False):
        x_top_left, y_top_left = np.round(row[2:4])
        x_bottom_right, y_bottom_right = np.ceil(row[4:6])
        if row[6] == 0:
            outline = 'red'
        elif row[7] == 0:
            outline = 'green'
        else:
            outline = 'blue'
        if u_mask is not None and row[8] == 0:
            if outline != 'green':
                outline = 'red'  # 'orange'

        if is_he and outline == 'blue':
            d.rectangle([(x_top_left, y_top_left), (x_bottom_right, y_bottom_right)], fill="#a9a9a9")
        else:
            d.rectangle([(x_top_left, y_top_left), (x_bottom_right, y_bottom_right)], outline=outline, width=width)

    return img_overlay

def get_slide_cut_info(slide_name):
    for k, v in HE_KI67_SLIDES_CUT_INFO_PAIR.items():
        if k == slide_name:
            return v

def read_kfb_region(slide_name, is_he, mag=1 / 4, dx=0, dy=0, w=0, h=0):
    reader = kfbReader.reader()
    slide_path = os.path.join(SLIDES_PATH, slide_name + (HE_NAME if is_he else KI67_NAME))
    reader.ReadInfo(slide_path, SLIDE_READ_SCALE, True)
    reader.setReadScale(SLIDE_READ_SCALE)
    img_w = reader.getWidth()
    img_h = reader.getHeight()

    slide_pair_cut_info = get_slide_cut_info(slide_name)
    cut_info = slide_pair_cut_info[0] if is_he else slide_pair_cut_info[1]
    start_x = cut_info[0] if cut_info[0] >= 1 else int(img_w * cut_info[0])
    start_y = cut_info[1] if cut_info[1] >= 1 else int(img_h * cut_info[1])
    if w == 0:
        region_w = int(img_w * cut_info[2]) if cut_info[2] != -1 else (img_w - start_x)
        region_h = int(img_h * cut_info[3]) if cut_info[3] != -1 else (img_h - start_y)
        result_img = reader.ReadRoi(int(start_x * mag), int(start_y * mag), int(region_w * mag), int(region_h * mag),
                                    int(SLIDE_READ_SCALE * mag))
    else:
        result_img = reader.ReadRoi(start_x + dx, start_y + dy, w, h, SLIDE_READ_SCALE)

    result_img = cv.cvtColor(result_img, cv.COLOR_BGR2RGB)
    result_img = Image.fromarray(result_img)
    return result_img


def tile_gen_at_mag_for_kfb(he_name, tile_coords, tile_size, mag=4):
    x_tiles = max(list(tile_coords['X'])) + 1
    y_tiles = max(list(tile_coords['Y'])) + 1
    yield (x_tiles, y_tiles)

    for row in tile_coords.itertuples(index=False):
        x_top_left, y_top_left = np.round(row[2:4])
        x_bottom_right, y_bottom_right = np.ceil(row[4:6])
        x_top_left_new = int(x_top_left * mag)
        y_top_left_new = int(y_top_left * mag)

        x_bottom_right_new = int(x_bottom_right * mag)
        y_bottom_right_new = int(y_bottom_right * mag)
        wid = x_bottom_right_new - x_top_left_new
        hei = y_bottom_right_new - y_top_left_new
        tile = read_kfb_region(he_name, True, dx=x_top_left_new, dy=y_top_left_new, w=wid, h=hei)

        yield tile.resize((tile_size, tile_size), resample=Image.BICUBIC), [row[0], row[1]], wid, hei


def save_tiles_for_kfb(normaliser, path, tile_gen, cancer_mask, tissue_mask, uncertain_mask, prefix=''):
    os.makedirs(os.path.join(path, 'positive'), exist_ok=True)
    os.makedirs(os.path.join(path, 'negative'), exist_ok=True)
    x_tiles, y_tiles = next(tile_gen)
    verbose_print('Whole Image Size is {0} x {1}'.format(x_tiles, y_tiles))
    i = 0
    cancer = 0
    uncertain = 0
    non_cancer = 0
    for tile, pos, w, h in tile_gen:
        img = tile.convert('RGB')
        img_norm = normaliser.transform_tile(img)

        if cancer_mask.ravel()[i] == 0:
            cls = 'r'
        elif tissue_mask.ravel()[i] == 0:
            cls = 'g'
        else:
            cls = 'b'

        if uncertain_mask is not None and uncertain_mask.ravel()[i] == 0:
            if cls != 'g':
                cls = 'o'

        tile_name = prefix + '_' + str(pos[0]) + '_' + str(pos[1])
        if cls in ['r', 'o']:
            img_norm.save(os.path.join(path, 'positive', tile_name + '.jpeg'), 'JPEG')
            cancer += 1
        elif cls == 'g':
            img_norm.save(os.path.join(path, 'negative', tile_name + '.jpeg'), 'JPEG')
            non_cancer += 1
        i += 1

    verbose_print(
        'Cancer tiles: {0}, Non Cancer tiles: {1}, Uncertain tiles: {2}'.format(cancer, non_cancer, uncertain))
    verbose_print('Exported tiles for {0} wid {1} hei {2}'.format(prefix, w, h))
    return w, h


def threshold_mask(tile_gen, threshold):
    """Creates mask from tiles using a threshold

    Averages the pixel intensities of each tile and applies a threshold.

    Parameters
    ----------
    tile_gen : tile generator
    threshold : float

    Returns
    -------
    out : ndarray
        binary mask where zero is below threshold
    """
    mask = []
    shape = next(tile_gen)
    for tile in tile_gen:
        if np.array(tile).mean() < threshold:
            mask.append(0)
        else:
            mask.append(1)
    return np.reshape(mask, shape)


def uncertain_mask(img, tile_size, cancer_thresh, non_cancer_thresh):
    """Create mask of uncertain tiles

    Parameters
    ----------
    img : Pillow image (RGB)
    tile_size : int
    cancer_thresh : float
        DAB intensity threshold between 0 and 1.0 (inclusive)
        Below threshold is cancer
    non_cancer_thresh : float
        DAB intensity threshold between 0 and 1.0 (inclusive)
        Above threshold is non-cancer

    Returns
    -------
    uncertain_mask : ndarray
    """
    dab_array = dab_tile_array(img, tile_size)
    binary_mask = ((cancer_thresh < dab_array) & (dab_array < non_cancer_thresh))
    return (np.invert(binary_mask)).astype(np.uint8)


def cancer_mask(img, tile_size, cancer_thresh=250):
    """Generates a cancer mask

    Parameters
    ----------
    img : Pillow image (RGB)
    tile_size : int, float
    cancer_thresh : int, float

    Returns
    -------
    c_mask : ndarray
        mask where zero represents cancer and one represents background
    """
    # Determine Dab threshold with a smaller 1000x1000 image
    downsample = max(img.size) / 1000
    img_small_size = tuple([np.int(np.round(dim / downsample)) for dim in img.size])
    img_small = img.resize(img_small_size, resample=Image.BICUBIC)
    hed_small = rgb2hed(img_small)
    dab_thresh = threshold_otsu_masked(hed_small)
    # Extract Dab channel (stain)
    hed = rgb2hed(img)
    dab_channel = -hed[:, :, 2]
    dab_binary = dab_channel > dab_thresh

    # Remove background staining
    dab_binary_filtered = remove_small_holes(dab_binary, area_threshold=64)
    tgen = tile_gen(binary2gray(dab_binary_filtered), tile_size)
    c_mask = threshold_mask(tgen, cancer_thresh)
    return c_mask


def dab_tile_array(img, tile_size):
    """Creates array with mean DAB intensity value for each tile

    Parameters
    ----------
    img : Pillow image (RGB)
    tile_size : int

    Returns
    -------
    dab_tile_array : ndarray
    """
    dab_values = []
    tgen = tile_gen(img, tile_size)
    shape = next(tgen)
    for tile in tgen:
        tile = tile.convert('RGB')
        tile_hed = rgb2hed(tile)
        tile_dab = -tile_hed[:, :, 2]
        dab_values.append(tile_dab.mean())
    return np.reshape(dab_values, shape)