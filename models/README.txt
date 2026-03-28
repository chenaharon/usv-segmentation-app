Syllable classification (CNN) needs a Keras model at:

  models/model_weights.h6

This can be either a single HDF5-style weights file, or a directory (still named
model_weights.h6) containing a TensorFlow SavedModel: saved_model.pb plus a
variables/ folder. If your copy only has names like variables-001.data-00000-of-00001
but TensorFlow expects variables.data-00000-of-00001, the app copies the missing
canonical filenames automatically before loading.

Place it in this folder (next to this README), or set the environment variable
USV_MODEL_PATH to the full path of the file or folder.

Without this, the pipeline still runs but reports "Classification skipped" and
fills syllable class 10 as a placeholder.
