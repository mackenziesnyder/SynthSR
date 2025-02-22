"""This script enables to launch predictions with SynthSeg from the terminal.


If you use this code, please the SynthSR paper in:
https://github.com/BBillot/SynthSR/blob/master/bibtex.bib

Copyright 2020 Benjamin Billot

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in
compliance with the License. You may obtain a copy of the License at
http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software distributed under the License is
distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
implied. See the License for the specific language governing permissions and limitations under the
License.
"""


# print information
print('\n')
print('SynthSR prediction')
print('\n')

# python imports
import os
import sys
import numpy as np
from argparse import ArgumentParser

# add main folder to python path and import SynthSR packages
synthSR_home = os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0])))
print(f"SynthSR home directory: {synthSR_home}")
sys.path.append(synthSR_home)
from ext.neuron import models as nrn_models
from ext.lab2im import utils
from ext.lab2im import edit_volumes

# parse arguments
parser = ArgumentParser()
parser.add_argument("path_images", type=str,
                    help="images to super-resolve / synthesize. Can be the path to a single image or to a folder")
parser.add_argument("path_predictions", type=str,
                    help="path where to save the synthetic 1mm MP-RAGEs. Must be the same type "
                         "as path_images (path to a single image or to a folder)")
parser.add_argument("--cpu", action="store_true", help="enforce running with CPU rather than GPU.")
parser.add_argument("--threads", type=int, default=1, dest="threads",
                    help="number of threads to be used by tensorflow when running on CPU.")
parser.add_argument("--ct", action="store_true", help="use this flag for ct scans.")
parser.add_argument("--model", default=None, help="(optional) Use a different model file.")
parser.add_argument("--disable_flipping", action="store_true", help="(optional) Use this flag to disable flipping augmentation at test time.")

args = vars(parser.parse_args())

# Log arguments
print(f"Arguments parsed: {args}")

# enforce CPU processing if necessary
if args['cpu']:
    print('using CPU, hiding all CUDA_VISIBLE_DEVICES')
    os.environ['CUDA_VISIBLE_DEVICES'] = '-1'

# limit the number of threads to be used if running on CPU
import tensorflow as tf

print(f"Setting TensorFlow threads to: {args['threads']}")
tf.config.threading.set_intra_op_parallelism_threads(args['threads'])

# Build Unet and load weights
print("Building Unet model...")
unet_model = nrn_models.unet(nb_features=24,
                             input_shape=[None, None, None, 1],
                             nb_levels=5,
                             conv_size=3,
                             nb_labels=1,
                             feat_mult=2,
                             nb_conv_per_level=2,
                             conv_dropout=0,
                             final_pred_activation='linear',
                             batch_norm=-1,
                             activation='elu',
                             input_model=None)

if args['model'] is None:
    print(f"Loading default model: {os.path.join(synthSR_home, 'models/SynthSR_v10_210712.h5')}")
    unet_model.load_weights(os.path.join(synthSR_home, 'models/SynthSR_v10_210712.h5'), by_name=True)
else:
    print(f"Loading user-specified model: {args['model']}")
    unet_model.load_weights(args['model'], by_name=True)

# Prepare list of images to process
path_images = os.path.abspath(args['path_images'])
basename = os.path.basename(path_images)
path_predictions = os.path.abspath(args['path_predictions'])

# Log input and output paths
print(f"Input images path: {path_images}")
print(f"Output predictions path: {path_predictions}")

# prepare input/output volumes
# First case: you're providing directories
if ('.nii.gz' not in basename) & ('.nii' not in basename) & ('.mgz' not in basename) & ('.npz' not in basename):
    if os.path.isfile(path_images):
        raise Exception('Extension not supported for %s, only use: nii.gz, .nii, .mgz, or .npz' % path_images)
    images_to_segment = utils.list_images_in_folder(path_images)
    print(f"Found {len(images_to_segment)} images to process in the directory.")
    
    utils.mkdir(path_predictions)
    path_predictions = [os.path.join(path_predictions, os.path.basename(image)).replace('.nii', '_SynthSR.nii') for image in images_to_segment]
    path_predictions = [seg_path.replace('.mgz', '_SynthSR.mgz') for seg_path in path_predictions]
    path_predictions = [seg_path.replace('.npz', '_SynthSR.npz') for seg_path in path_predictions]
else:
    assert os.path.isfile(path_images), f"File does not exist: {path_images}. Please make sure the path and the extension are correct."
    images_to_segment = [path_images]
    path_predictions = [path_predictions]

# Log the number of images found
print(f"Found {len(images_to_segment)} images to process")

# Do the actual work
for idx, (path_image, path_prediction) in enumerate(zip(images_to_segment, path_predictions)):
    print(f"Processing image {idx + 1}: {path_image}")
    
    im, aff, hdr = utils.load_volume(path_image, im_only=False, dtype='float')
    print(f"Loaded image: {path_image}, shape: {im.shape}")

    if args['ct']:
        print(f"CT scan detected. Applying CT-specific preprocessing.")
        im[im < 0] = 0
        im[im > 80] = 80

    print(f"Resampling image to 1mm isotropic resolution.")
    im, aff = edit_volumes.resample_volume(im, aff, [1.0, 1.0, 1.0])

    print(f"Aligning image to reference space.")
    im, aff2 = edit_volumes.align_volume_to_ref(im, aff, aff_ref=np.eye(4), return_aff=True, n_dims=3)
    
    print(f"Normalizing image values to range [0, 1].")
    im = im - np.min(im)
    im = im / np.max(im)

    print(f"Reshaping image for model input.")
    I = im[np.newaxis, ..., np.newaxis]
    W = (np.ceil(np.array(I.shape[1:-1]) / 32.0) * 32).astype('int')
    idx = np.floor((W - I.shape[1:-1]) / 2).astype('int')
    S = np.zeros([1, *W, 1])
    S[0, idx[0]:idx[0] + I.shape[1], idx[1]:idx[1] + I.shape[2], idx[2]:idx[2] + I.shape[3], :] = I

    if args['disable_flipping']:
        print("Flipping augmentation disabled. Running prediction on single input.")
        output = unet_model.predict(S)
    else:
        print("Flipping augmentation enabled. Running prediction on flipped inputs.")
        output = 0.5 * unet_model.predict(S) + 0.5 * np.flip(unet_model.predict(np.flip(S, axis=1)), axis=1)
    
    print(f"Prediction completed. Squeezing output shape.")
    pred = np.squeeze(output)
    pred = 255 * pred
    pred[pred < 0] = 0
    pred[pred > 128] = 128
    pred = pred[idx[0]:idx[0] + I.shape[1], idx[1]:idx[1] + I.shape[2], idx[2]:idx[2] + I.shape[3]]

    print(f"Saving prediction to {path_prediction}.")
    utils.save_volume(pred, aff2, None, path_prediction)

print('\nAll done!')